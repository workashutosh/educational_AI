"""Auto-generate 3-question micro-quizzes from notes."""
from __future__ import annotations

import json
import logging
import re

from django.db import transaction

from engagement.models import MicroQuestion, MicroQuiz, TeacherImpactEvent
from engagement.services.impact import record_impact
from engagement.services.notifications import create_notification, notify_many
from ingestion.models import BucketAccess, Chunk, Document, SchoolMembership
from ingestion.services.llm_provider import chat_completion

logger = logging.getLogger(__name__)


def generate_micro_quiz_for_document(document_id: int) -> MicroQuiz | None:
    try:
        doc = Document.objects.select_related("bucket", "bucket__school").get(
            pk=document_id
        )
    except Document.DoesNotExist:
        return None
    if doc.status != Document.STATUS_INDEXED:
        return None
    if doc.kind == Document.KIND_QUESTION_PAPER:
        # Micro-quizzes target teaching notes
        return None
    return _generate(
        bucket=doc.bucket,
        source_type=MicroQuiz.SOURCE_DOCUMENT,
        source_id=doc.id,
        title=f"Quick check: {doc.original_filename[:80]}",
        created_by=doc.uploaded_by,
    )


def generate_micro_quiz_for_lecture(lecture_id: int) -> MicroQuiz | None:
    from lectures.models import Lecture

    try:
        lec = Lecture.objects.select_related("bucket", "school", "created_by").get(
            pk=lecture_id
        )
    except Lecture.DoesNotExist:
        return None
    return _generate(
        bucket=lec.bucket,
        source_type=MicroQuiz.SOURCE_LECTURE,
        source_id=lec.id,
        title=f"After class: {lec.title[:80]}",
        created_by=lec.created_by,
    )


@transaction.atomic
def _generate(*, bucket, source_type: str, source_id: int, title: str, created_by):
    existing = MicroQuiz.objects.filter(
        source_type=source_type, source_id=source_id
    ).first()
    if existing:
        return existing

    quiz = MicroQuiz.objects.create(
        school=bucket.school,
        bucket=bucket,
        source_type=source_type,
        source_id=source_id,
        title=title[:255],
        status=MicroQuiz.STATUS_DRAFT,
        created_by=created_by,
    )

    try:
        questions = _llm_questions(bucket.id, title)
        if len(questions) < 3:
            raise RuntimeError("Model returned fewer than 3 questions")
        for i, q in enumerate(questions[:3]):
            MicroQuestion.objects.create(
                quiz=quiz,
                order=i,
                prompt=str(q["prompt"])[:2000],
                options=[str(o)[:400] for o in q["options"][:4]],
                correct_index=int(q["correct_index"]),
                topic=_topic_for(bucket, str(q["prompt"])),
            )
        quiz.status = MicroQuiz.STATUS_READY
        quiz.error_message = ""
        quiz.save(update_fields=["status", "error_message"])
    except Exception as exc:
        logger.exception("Micro-quiz generation failed source=%s:%s", source_type, source_id)
        quiz.status = MicroQuiz.STATUS_FAILED
        quiz.error_message = str(exc)[:500]
        quiz.save(update_fields=["status", "error_message"])
        return quiz

    if created_by:
        try:
            record_impact(
                member=created_by,
                kind=TeacherImpactEvent.KIND_MICRO_AUTO,
                ref_id=f"micro:{quiz.id}",
            )
        except Exception:
            logger.exception("impact record failed")

    _notify_students(quiz)
    return quiz


def _topic_for(bucket, prompt: str):
    """Embedding-based topic tag (no LLM) so quick checks feed weak-topic analytics."""
    try:
        from question_bank.services.tagging import suggest_topic

        return suggest_topic(bucket, prompt)
    except Exception:
        logger.debug("micro question tagging skipped", exc_info=True)
        return None


def _notify_students(quiz: MicroQuiz) -> None:
    student_ids = BucketAccess.objects.filter(bucket=quiz.bucket).values_list(
        "member_id", flat=True
    )
    students = SchoolMembership.objects.filter(
        id__in=student_ids,
        role=SchoolMembership.ROLE_STUDENT,
        is_active=True,
    )
    notify_many(
        students,
        kind="micro_ready",
        title="New 3-question quick check",
        body=quiz.title,
        link_path=f"/app/micro-quizzes/{quiz.id}",
        dedupe_key=f"micro:{quiz.id}",
    )


def _context_text(bucket_id: int, limit: int = 8) -> str:
    chunks = (
        Chunk.objects.filter(document__bucket_id=bucket_id, document__kind="notes")
        .order_by("-id")[:limit]
    )
    parts = []
    for c in chunks:
        t = (c.text or "").strip()
        if t:
            parts.append(t[:800])
    if not parts:
        chunks = Chunk.objects.filter(document__bucket_id=bucket_id).order_by("-id")[
            :limit
        ]
        for c in chunks:
            t = (c.text or "").strip()
            if t:
                parts.append(t[:800])
    return "\n\n---\n\n".join(parts)[:6000]


def _llm_questions(bucket_id: int, title: str) -> list[dict]:
    ctx = _context_text(bucket_id)
    if not ctx.strip():
        raise RuntimeError("No indexed notes available for micro-quiz")

    system = (
        "You create short multiple-choice quizzes for school students. "
        "Return ONLY valid JSON: {\"questions\":[{\"prompt\":\"...\",\"options\":"
        "[\"A\",\"B\",\"C\",\"D\"],\"correct_index\":0}]} with exactly 3 questions. "
        "correct_index is 0-3. Use ONLY the provided notes."
    )
    user = f"Quiz context title: {title}\n\nNotes excerpts:\n{ctx}"
    content = chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=2048,
        timeout=60,
    )
    data = _parse_json(content)
    questions = data.get("questions") or []
    cleaned = []
    for q in questions:
        opts = list(q.get("options") or [])
        if len(opts) < 4:
            continue
        ci = int(q.get("correct_index", 0))
        if ci < 0 or ci > 3:
            ci = 0
        cleaned.append(
            {
                "prompt": str(q.get("prompt") or "").strip(),
                "options": [str(o) for o in opts[:4]],
                "correct_index": ci,
            }
        )
    return cleaned


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def submit_micro_attempt(*, quiz: MicroQuiz, student, answers: dict) -> "MicroAttempt":
    from engagement.models import MicroAttempt
    from engagement.services.activity import record_activity
    from engagement.services.mastery import recompute_mastery

    if quiz.status != MicroQuiz.STATUS_READY:
        raise ValueError("This quick check is not ready yet.")
    if MicroAttempt.objects.filter(quiz=quiz, student=student).exists():
        raise ValueError("You already completed this quick check.")

    qmap = {q.id: q for q in quiz.questions.all()}
    score = 0
    normalized = {}
    for qid, q in qmap.items():
        try:
            chosen = int(answers.get(str(qid), answers.get(qid, -1)))
        except (TypeError, ValueError):
            chosen = -1
        normalized[str(qid)] = chosen
        if chosen == q.correct_index:
            score += 1

    attempt = MicroAttempt.objects.create(
        quiz=quiz,
        student=student,
        answers=normalized,
        score=score,
        max_score=len(qmap) or 3,
    )
    record_activity(
        member=student,
        kind="micro_quiz",
        bucket=quiz.bucket,
        ref_id=f"micro:{quiz.id}",
    )
    try:
        recompute_mastery(member=student, bucket=quiz.bucket)
    except Exception:
        logger.exception("mastery recompute after micro failed")
    return attempt
