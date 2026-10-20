"""Flashcard generation, doubt routing, and answer-feedback analytics."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Avg, Count, Q
from django.utils import timezone

from ingestion.models import Chunk, ChatMessage, Document, SchoolMembership, SubjectBucket
from ingestion.services.llm_json import LLMJSONError, llm_json
from rag_harness.context_builder import build_context
from rag_harness.retriever import retrieve

from ..models import ChatFeedback, Doubt, Flashcard, FlashcardDeck

logger = logging.getLogger(__name__)

NOT_FOUND_ANSWER = "I couldn't find that in the indexed notes."
MAX_CARDS = 40


class LearningError(Exception):
    pass


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------

_CARDS_SYSTEM = (
    "You make study flashcards for school students from teacher notes.\n"
    "Use ONLY the excerpts. Return JSON only: "
    '{"title":"deck title","cards":[{"front":"short question or term","back":"concise answer"}]}\n'
    "Front: one idea, max 25 words. Back: max 60 words, exact definitions/formulas "
    "(LaTeX with $...$). No duplicates. Produce exactly the requested number."
)


def _context_for(bucket: SubjectBucket, *, prompt: str, document: Document | None, n: int) -> tuple[str, list[int]]:
    if document is not None:
        rows = list(
            Chunk.objects.filter(document=document).order_by("order_index").values("id", "text")[:30]
        )
        text, ids = "", []
        for row in rows:
            if len(text) > 9000:
                break
            text += f"\n\n[{len(ids) + 1}]\n{row['text'][:1500]}"
            ids.append(row["id"])
        return text.strip(), ids
    nodes = retrieve(bucket, query=prompt, top_k=max(6, min(14, n // 2 + 4)), kinds=[Document.KIND_NOTES])
    return build_context(nodes), [n_["chunk_id"] for n_ in nodes if n_.get("chunk_id")]


def generate_deck(
    member: SchoolMembership,
    bucket: SubjectBucket,
    *,
    prompt: str = "",
    title: str = "",
    count: int = 15,
    document: Document | None = None,
    topic=None,
    visibility: str = FlashcardDeck.VISIBILITY_BUCKET,
) -> FlashcardDeck:
    count = max(3, min(MAX_CARDS, int(count or 15)))
    focus = (prompt or "").strip() or (topic.name if topic else "") or (
        document.original_filename if document else ""
    )
    if not focus:
        raise LearningError("Give a topic, a document, or instructions for the deck.")
    context, chunk_ids = _context_for(bucket, prompt=focus, document=document, n=count)
    if not context.strip():
        raise LearningError("No indexed notes match that topic yet.")
    try:
        data = llm_json(
            _CARDS_SYSTEM,
            f"Excerpts:\n{context}\n\nFocus: {focus}\nMake exactly {count} cards.",
            max_tokens=4000,
        )
    except LLMJSONError as exc:
        raise LearningError("The AI returned an unreadable answer. Please try again.") from exc

    cards = []
    seen: set[str] = set()
    for raw in data.get("cards") or []:
        front = str(raw.get("front") or "").strip()
        back = str(raw.get("back") or "").strip()
        key = re.sub(r"\W+", " ", front.lower()).strip()
        if len(front) < 2 or len(back) < 1 or key in seen:
            continue
        seen.add(key)
        cards.append((front[:2000], back[:4000]))
    if not cards:
        raise LearningError("The AI did not produce usable cards. Try a narrower topic.")

    deck = FlashcardDeck.objects.create(
        school=bucket.school,
        bucket=bucket,
        owner=member,
        title=(title or data.get("title") or focus).strip()[:255],
        topic=topic,
        source_document=document,
        visibility=visibility,
    )
    Flashcard.objects.bulk_create(
        [
            Flashcard(
                deck=deck,
                order=i,
                front=front,
                back=back,
                topic=topic,
                source_chunk_id=chunk_ids[i % len(chunk_ids)] if chunk_ids else None,
            )
            for i, (front, back) in enumerate(cards[:count])
        ]
    )
    return deck


# ---------------------------------------------------------------------------
# Doubts
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()[:500]


def open_doubt(
    *,
    student: SchoolMembership,
    bucket: SubjectBucket,
    question: str,
    reason: str,
    ai_answer: str = "",
    chat_message: ChatMessage | None = None,
    student_note: str = "",
) -> tuple[Doubt, bool]:
    """Create (or reuse a same-day duplicate) doubt and notify bucket teachers."""
    question = (question or "").strip()
    if not question:
        raise LearningError("Question is required.")
    since = timezone.now() - timedelta(hours=24)
    for existing in Doubt.objects.filter(
        student=student, bucket=bucket, status=Doubt.STATUS_OPEN, created_at__gte=since
    ):
        if _norm(existing.question) == _norm(question):
            if student_note and not existing.student_note:
                existing.student_note = student_note
                existing.save(update_fields=["student_note"])
            return existing, False

    doubt = Doubt.objects.create(
        school=student.school,
        bucket=bucket,
        student=student,
        question=question[:4000],
        student_note=(student_note or "")[:2000],
        ai_answer=(ai_answer or "")[:8000],
        chat_message=chat_message,
        session=chat_message.session if chat_message else None,
        reason=reason,
    )
    _notify_teachers(doubt)
    return doubt, True


def bucket_teachers(bucket: SubjectBucket):
    return SchoolMembership.objects.filter(
        Q(role=SchoolMembership.ROLE_TEACHER, bucket_grants__bucket=bucket)
        | Q(role__in=[SchoolMembership.ROLE_ADMIN, SchoolMembership.ROLE_MANAGER]),
        school=bucket.school,
        is_active=True,
    ).distinct()


def _notify_teachers(doubt: Doubt) -> None:
    try:
        from engagement.services.notifications import notify_many

        teachers = bucket_teachers(doubt.bucket)
        # Prefer the subject teachers; fall back to admins only when none are granted.
        subject = [t for t in teachers if t.role == SchoolMembership.ROLE_TEACHER]
        notify_many(
            subject or list(teachers),
            kind="generic",
            title=f"New doubt in {doubt.bucket.name}",
            body=doubt.question[:200],
            link_path=f"/app/doubts?doubt={doubt.id}",
            payload={"doubt_id": doubt.id, "type": "doubt_opened"},
            dedupe_key=f"doubt:{doubt.id}",
        )
    except Exception:
        logger.exception("doubt notification failed")


def answer_doubt(
    doubt: Doubt, teacher: SchoolMembership, *, answer: str, add_to_notes: bool = False
) -> Doubt:
    answer = (answer or "").strip()
    if not answer:
        raise LearningError("Write an answer first.")
    doubt.answer = answer[:8000]
    doubt.answered_by = teacher
    doubt.answered_at = timezone.now()
    doubt.status = Doubt.STATUS_ANSWERED
    doubt.save(update_fields=["answer", "answered_by", "answered_at", "status"])
    if add_to_notes and doubt.published_document_id is None:
        doubt.published_document = publish_answer_as_note(doubt, teacher)
        doubt.save(update_fields=["published_document"])
    try:
        from engagement.services.notifications import create_notification

        create_notification(
            recipient=doubt.student,
            kind="generic",
            title="Your teacher answered your doubt",
            body=doubt.question[:200],
            link_path=f"/app/doubts?doubt={doubt.id}",
            payload={"doubt_id": doubt.id, "type": "doubt_answered"},
            dedupe_key=f"doubt-answered:{doubt.id}",
        )
    except Exception:
        logger.exception("doubt answered notification failed")
    return doubt


def publish_answer_as_note(doubt: Doubt, teacher: SchoolMembership) -> Document:
    """Index the Q&A as a notes document so future AI answers can use it."""
    from ingestion.services import sha256_of_uploaded_file
    from ingestion.tasks import process_document

    body = (
        f"# Teacher answer: {doubt.question[:120]}\n\n"
        f"## Question\n\n{doubt.question}\n\n"
        f"## Answer\n\n{doubt.answer}\n"
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "-", doubt.question[:50]).strip("-") or "answer"
    upload = ContentFile(body.encode("utf-8"), name=f"teacher-answer-{doubt.id}-{slug}.md")
    file_hash = sha256_of_uploaded_file(upload)
    document = Document.objects.create(
        bucket=doubt.bucket,
        uploaded_by=teacher,
        file=upload,
        original_filename=Path(upload.name).name,
        file_hash=file_hash,
        byte_size=len(body.encode("utf-8")),
        content_type="text/markdown",
        kind=Document.KIND_NOTES,
    )
    try:
        process_document.delay(document.id)
    except Exception:
        logger.exception("could not queue indexing for doubt answer doc=%s", document.id)
    return document


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def top_source_score(message: ChatMessage) -> float | None:
    scores = [s.get("score") for s in (message.sources or []) if isinstance(s, dict) and s.get("score") is not None]
    return float(max(scores)) if scores else None


def preceding_question(message: ChatMessage) -> str:
    prev = (
        ChatMessage.objects.filter(
            session=message.session, role=ChatMessage.ROLE_USER, created_at__lte=message.created_at
        )
        .exclude(pk=message.pk)
        .order_by("-created_at", "-id")
        .first()
    )
    return prev.content if prev else ""


def feedback_summary(school, *, bucket_id=None, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = ChatFeedback.objects.filter(school=school, created_at__gte=since)
    if bucket_id:
        qs = qs.filter(bucket_id=bucket_id)
    up = qs.filter(rating=ChatFeedback.RATING_UP)
    down = qs.filter(rating=ChatFeedback.RATING_DOWN)
    total = qs.count()
    reasons = list(
        down.exclude(reason="").values("reason").annotate(n=Count("id")).order_by("-n")
    )
    negatives = []
    for fb in down.select_related("message", "bucket").order_by("-created_at")[:25]:
        negatives.append(
            {
                "feedback_id": fb.id,
                "message_id": fb.message_id,
                "bucket_id": fb.bucket_id,
                "bucket_name": fb.bucket.name,
                "question": preceding_question(fb.message)[:500],
                "answer_excerpt": fb.message.content[:400],
                "reason": fb.reason,
                "comment": fb.comment,
                "top_score": fb.top_score,
                "created_at": fb.created_at,
            }
        )
    avg_up = up.aggregate(a=Avg("top_score"))["a"]
    avg_down = down.aggregate(a=Avg("top_score"))["a"]
    current_floor = float(getattr(settings, "RAG_MIN_SCORE", 0.22) or 0)
    hint = None
    if avg_up is not None and avg_down is not None and down.count() >= 5:
        if avg_down < avg_up - 0.05 and avg_down > current_floor:
            hint = round((avg_up + avg_down) / 2, 3)
    return {
        "days": days,
        "total": total,
        "helpful": up.count(),
        "not_helpful": down.count(),
        "helpful_rate": round(100 * up.count() / total, 1) if total else None,
        "by_reason": reasons,
        "avg_top_score_helpful": round(avg_up, 3) if avg_up is not None else None,
        "avg_top_score_not_helpful": round(avg_down, 3) if avg_down is not None else None,
        "current_min_score": current_floor,
        "suggested_min_score": hint,
        "recent_negative": negatives,
    }
