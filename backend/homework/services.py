"""Homework lifecycle: assign, submit (with OCR of photos/files), AI grade, release."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from ingestion.api_utils import bucket_students
from ingestion.models import SchoolMembership
from ingestion.services.llm_errors import LLMProviderError
from ingestion.services.llm_json import LLMJSONError, llm_json

from .models import Assignment, AssignmentTarget, Submission, SubmissionFile

logger = logging.getLogger(__name__)

MAX_FILES = 10
MAX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx", ".txt", ".md", ".heic"}
OCR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx", ".txt", ".md"}


class HomeworkError(Exception):
    pass


def notify(recipients, **kwargs) -> None:
    try:
        from engagement.services.notifications import notify_many

        notify_many(recipients, **kwargs)
    except Exception:
        logger.exception("homework notification failed")


def assign_students(assignment: Assignment, *, student_ids=None, assign_all: bool = False) -> int:
    pool = bucket_students(assignment.bucket)
    if not assign_all:
        pool = pool.filter(pk__in=student_ids or [])
    created = 0
    for s in pool:
        _, made = AssignmentTarget.objects.get_or_create(assignment=assignment, student=s)
        created += int(made)
    return created


def publish(assignment: Assignment) -> None:
    if not assignment.targets.exists():
        raise HomeworkError("Assign at least one student before publishing.")
    assignment.status = Assignment.STATUS_PUBLISHED
    assignment.published_at = timezone.now()
    assignment.save(update_fields=["status", "published_at"])
    due = f" · due {timezone.localtime(assignment.due_at):%d %b, %H:%M}" if assignment.due_at else ""
    notify(
        [t.student for t in assignment.targets.select_related("student__school")],
        kind="generic",
        title=f"New homework: {assignment.title}",
        body=f"{assignment.bucket.name}{due}",
        link_path=f"/app/homework/{assignment.id}",
        payload={"assignment_id": assignment.id, "type": "homework_assigned"},
        dedupe_key=f"hw:{assignment.id}",
    )


def _extract_text(files: list[SubmissionFile]) -> str:
    """OCR / parse uploaded answer files with the same parser used for notes."""
    from ingestion.services.parse_service import parse_document

    parts: list[str] = []
    for f in files:
        ext = Path(f.original_filename).suffix.lower()
        if ext not in OCR_EXTS:
            continue
        with tempfile.TemporaryDirectory(prefix="hw_ocr_") as tmp:
            src = Path(tmp) / f"answer{ext}"
            with f.file.open("rb") as fh:
                src.write_bytes(fh.read())
            try:
                result = parse_document(src, Path(tmp) / "out")
            except Exception as exc:
                logger.warning("homework OCR failed file=%s: %s", f.id, exc)
                continue
            text = (result.markdown or "").strip()
            if text:
                parts.append(f"--- {f.original_filename} ---\n{text}")
    return "\n\n".join(parts)[:20000]


@transaction.atomic
def submit(assignment: Assignment, student: SchoolMembership, *, text: str, uploads: list) -> Submission:
    if assignment.status != Assignment.STATUS_PUBLISHED:
        raise HomeworkError("This homework is not open for submissions.")
    if not AssignmentTarget.objects.filter(assignment=assignment, student=student).exists():
        raise HomeworkError("This homework is not assigned to you.")
    late = assignment.is_overdue
    if late and not assignment.allow_late:
        raise HomeworkError("The due date has passed.")
    if len(uploads) > MAX_FILES:
        raise HomeworkError(f"Attach at most {MAX_FILES} files.")
    for up in uploads:
        if Path(up.name).suffix.lower() not in ALLOWED_EXTS:
            raise HomeworkError("Attach photos (JPG/PNG/WEBP), PDF, DOCX, or text files.")
        if up.size > MAX_FILE_BYTES:
            raise HomeworkError("Each file must be under 15 MB.")
    if not (text or "").strip() and not uploads:
        raise HomeworkError("Write an answer or attach your work.")

    sub, created = Submission.objects.select_for_update().get_or_create(
        assignment=assignment, student=student
    )
    if not created and sub.released_at:
        raise HomeworkError("This homework was already graded and returned.")
    sub.text_answer = (text or "").strip()[:20000]
    sub.is_late = late
    sub.submitted_at = timezone.now()
    sub.status = Submission.STATUS_SUBMITTED
    sub.ai_status = Submission.AI_PENDING if assignment.ai_grading else Submission.AI_SKIPPED
    sub.ai_score = None
    sub.ai_feedback = ""
    sub.extracted_text = ""
    sub.save()
    if uploads:
        for old in sub.files.all():
            old.file.delete(save=False)
        sub.files.all().delete()
        for up in uploads:
            SubmissionFile.objects.create(
                submission=sub,
                file=up,
                original_filename=up.name[:500],
                content_type=getattr(up, "content_type", "") or "",
                byte_size=up.size,
            )
    try:
        from engagement.models import EngagementActivity
        from engagement.services.activity import record_activity

        record_activity(
            member=student,
            kind=EngagementActivity.KIND_HOMEWORK,
            bucket=assignment.bucket,
            ref_id=f"hw:{assignment.id}",
        )
    except Exception:
        logger.exception("homework activity failed")
    return sub


_GRADE_SYSTEM = (
    "You are a fair school teacher grading homework. Use the marking scheme / model answer.\n"
    'Return JSON only: {"score": <number 0..max_marks>, "feedback": "2-5 sentences: what was '
    'right, what is missing, one tip", "strengths": ["..."], "improvements": ["..."]}\n'
    "Give partial credit. If the answer text looks like OCR noise or is empty, score 0 and say "
    "the work could not be read."
)


def ai_grade(sub: Submission) -> Submission:
    """Extract text from attachments and produce a provisional AI score."""
    assignment = sub.assignment
    if sub.files.exists() and not sub.extracted_text:
        sub.extracted_text = _extract_text(list(sub.files.all()))
        sub.save(update_fields=["extracted_text"])
    if not assignment.ai_grading:
        sub.ai_status = Submission.AI_SKIPPED
        sub.save(update_fields=["ai_status"])
        return sub
    answer = "\n\n".join(x for x in [sub.text_answer, sub.extracted_text] if x).strip()
    user = (
        f"Homework: {assignment.title}\n"
        f"Instructions: {assignment.instructions}\n"
        f"Max marks: {assignment.max_marks}\n"
        f"Marking scheme: {assignment.rubric or '(none given)'}\n"
        f"Model answer: {assignment.model_answer or '(none given)'}\n\n"
        f"Student answer:\n{answer[:12000] or '(empty)'}"
    )
    try:
        data = llm_json(_GRADE_SYSTEM, user, max_tokens=1200, temperature=0.1)
        score = float(data.get("score", 0))
        sub.ai_score = round(max(0.0, min(float(assignment.max_marks), score)), 1)
        feedback = str(data.get("feedback") or "").strip()
        tips = [str(t) for t in (data.get("improvements") or [])][:3]
        if tips:
            feedback += "\n\nTo improve:\n" + "\n".join(f"- {t}" for t in tips)
        sub.ai_feedback = feedback[:4000]
        sub.ai_status = Submission.AI_DONE
    except (LLMJSONError, LLMProviderError, ValueError, TypeError, RuntimeError):
        logger.exception("homework AI grading failed sub=%s", sub.id)
        sub.ai_status = Submission.AI_FAILED
    sub.save(update_fields=["ai_score", "ai_feedback", "ai_status"])
    return sub


def grade(sub: Submission, teacher: SchoolMembership, *, score: float, feedback: str, release: bool) -> Submission:
    max_marks = float(sub.assignment.max_marks)
    if score < 0 or score > max_marks:
        raise HomeworkError(f"Score must be between 0 and {sub.assignment.max_marks}.")
    sub.teacher_score = round(float(score), 2)
    sub.teacher_feedback = (feedback or "").strip()[:4000]
    sub.graded_by = teacher
    sub.graded_at = timezone.now()
    sub.status = Submission.STATUS_GRADED
    sub.save(update_fields=["teacher_score", "teacher_feedback", "graded_by", "graded_at", "status"])
    if release:
        release_submission(sub)
    return sub


def release_submission(sub: Submission) -> None:
    if sub.released_at:
        return
    if sub.teacher_score is None and sub.ai_score is not None:
        # Releasing without an override confirms the AI score.
        sub.teacher_score = sub.ai_score
        sub.status = Submission.STATUS_GRADED
        sub.graded_at = timezone.now()
    sub.released_at = timezone.now()
    sub.save(update_fields=["released_at", "teacher_score", "status", "graded_at"])
    notify(
        [sub.student],
        kind="generic",
        title=f"Homework returned: {sub.assignment.title}",
        body=f"Score: {sub.teacher_score}/{sub.assignment.max_marks}" if sub.teacher_score is not None else "",
        link_path=f"/app/homework/{sub.assignment_id}",
        payload={"assignment_id": sub.assignment_id, "type": "homework_returned"},
        dedupe_key=f"hw-return:{sub.id}",
    )


def student_status(assignment: Assignment, sub: Submission | None) -> str:
    if sub is None:
        return "overdue" if assignment.is_overdue else "pending"
    if sub.released_at:
        return "returned"
    return "submitted"


def student_homework_summary(student: SchoolMembership) -> list[dict]:
    rows = []
    targets = (
        AssignmentTarget.objects.filter(student=student, assignment__status__in=["published", "closed"])
        .select_related("assignment__bucket")
        .order_by("-assignment__published_at")[:30]
    )
    subs = {
        s.assignment_id: s
        for s in Submission.objects.filter(student=student, assignment__in=[t.assignment for t in targets])
    }
    for t in targets:
        a = t.assignment
        sub = subs.get(a.id)
        visible = bool(sub and sub.student_can_see_result())
        rows.append(
            {
                "assignment_id": a.id,
                "title": a.title,
                "bucket_name": a.bucket.name,
                "due_at": a.due_at,
                "status": student_status(a, sub),
                "is_late": bool(sub and sub.is_late),
                "score": (sub.teacher_score if sub.teacher_score is not None else sub.ai_score) if visible else None,
                "max_marks": a.max_marks,
            }
        )
    return rows
