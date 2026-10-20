"""Add, generate, import, and pick questions from the bank."""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Iterable

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ingestion.models import Chunk, Document, SchoolMembership, SubjectBucket
from ingestion.services.llm_json import LLMJSONError, llm_json
from rag_harness.context_builder import build_context
from rag_harness.retriever import retrieve

from ..models import QuestionItem, Topic, prompt_hash
from .tagging import suggest_topic

logger = logging.getLogger(__name__)

VALID_TYPES = {c[0] for c in QuestionItem.TYPE_CHOICES}
DEFAULT_MARKS = {"mcq": 1, "multi": 2, "brief": 3, "long": 5, "numeric": 4}
_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


class BankError(Exception):
    """User-facing validation error from bank operations."""


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_item(raw: dict) -> dict | None:
    """Coerce an LLM/user dict into a valid bank item dict, or None."""
    qtype = str(raw.get("qtype") or raw.get("type") or "mcq").strip().lower()
    if qtype in {"single", "mcq_single"}:
        qtype = "mcq"
    if qtype in {"multiple", "mcq_multi", "multi_select"}:
        qtype = "multi"
    if qtype in {"short", "short_answer"}:
        qtype = "brief"
    if qtype in {"long_answer", "essay"}:
        qtype = "long"
    if qtype in {"numerical", "integer"}:
        qtype = "numeric"
    if qtype not in VALID_TYPES:
        return None

    prompt = str(raw.get("prompt") or raw.get("question") or "").strip()
    if len(prompt) < 5:
        return None

    options: list[str] = []
    correct: list[int] = []
    if qtype in QuestionItem.OBJECTIVE_TYPES:
        options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()][:6]
        if len(options) < 2:
            return None
        raw_correct = raw.get("correct_indices")
        if raw_correct is None and raw.get("correct_index") is not None:
            raw_correct = [raw.get("correct_index")]
        for c in raw_correct or []:
            try:
                idx = int(c)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(options) and idx not in correct:
                correct.append(idx)
        if not correct:
            return None
        if qtype == "mcq":
            correct = correct[:1]
        elif len(correct) < 2:
            qtype = "mcq"

    difficulty = str(raw.get("difficulty") or "medium").strip().lower()
    if difficulty not in QuestionItem.DIFFICULTIES:
        difficulty = "medium"
    try:
        marks = int(raw.get("marks") or DEFAULT_MARKS[qtype])
    except (TypeError, ValueError):
        marks = DEFAULT_MARKS[qtype]

    return {
        "qtype": qtype,
        "prompt": prompt[:6000],
        "options": options,
        "correct_indices": sorted(correct),
        "answer": str(raw.get("answer") or raw.get("model_answer") or "").strip()[:6000],
        "explanation": str(raw.get("explanation") or "").strip()[:4000],
        "difficulty": difficulty,
        "marks": max(1, min(100, marks)),
        "tags": [str(t)[:50] for t in (raw.get("tags") or [])][:10],
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def add_items(
    bucket: SubjectBucket,
    items: Iterable[dict],
    *,
    source: str,
    created_by: SchoolMembership | None = None,
    topic: Topic | None = None,
    source_ref: str = "",
    source_document: Document | None = None,
    source_year: int | None = None,
    auto_tag: bool = True,
) -> tuple[list[QuestionItem], int]:
    """Insert normalized items; skips duplicates in the bucket. Returns (created, skipped)."""
    created: list[QuestionItem] = []
    skipped = 0
    existing = set(
        QuestionItem.objects.filter(bucket=bucket).values_list("prompt_hash", flat=True)
    )
    for raw in items:
        item = normalize_item(raw)
        if item is None:
            skipped += 1
            continue
        h = prompt_hash(item["prompt"])
        if h in existing:
            skipped += 1
            continue
        existing.add(h)
        item_topic = topic
        if item_topic is None and raw.get("topic_id"):
            item_topic = Topic.objects.filter(pk=raw["topic_id"], bucket=bucket).first()
        if item_topic is None and auto_tag:
            item_topic = suggest_topic(bucket, item["prompt"])
        created.append(
            QuestionItem.objects.create(
                school_id=bucket.school_id,
                bucket=bucket,
                topic=item_topic,
                source=source,
                source_ref=source_ref[:64],
                source_document=source_document,
                source_year=source_year,
                source_chunk_ids=list(raw.get("source_chunk_ids") or [])[:20],
                created_by=created_by,
                **item,
            )
        )
    return created, skipped


def mark_used(items: Iterable[QuestionItem]) -> None:
    ids = [i.id for i in items if i is not None]
    if ids:
        QuestionItem.objects.filter(pk__in=ids).update(
            times_used=F("times_used") + 1, last_used_at=timezone.now()
        )


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------

_GEN_SYSTEM = (
    "You write exam questions for school students from teacher notes.\n"
    "Use ONLY facts in the numbered excerpts. Respond with JSON only:\n"
    '{"questions":[{"qtype":"mcq|multi|brief|long|numeric","prompt":"...",'
    '"options":["..",".."],"correct_indices":[0],"answer":"model answer or numeric value",'
    '"explanation":"why the answer is right","difficulty":"easy|medium|hard"}]}\n'
    "Rules: mcq = exactly 4 options and one correct index; multi = 4 options and 2+ correct; "
    "brief/long/numeric = options [] and correct_indices []; numeric answers give the value "
    "with units. Produce exactly the requested counts and difficulty. Write math in LaTeX "
    "with $...$. Do not repeat questions listed under AVOID."
)


def generate_items(
    member: SchoolMembership,
    bucket: SubjectBucket,
    *,
    prompt: str,
    counts: dict[str, int],
    difficulty: str = "medium",
    topic: Topic | None = None,
    kinds: list[str] | None = None,
) -> list[QuestionItem]:
    total = sum(max(0, int(v or 0)) for v in counts.values())
    if total < 1:
        raise BankError("Ask for at least one question.")
    if total > 30:
        raise BankError("Generate at most 30 questions at a time.")
    focus = (prompt or "").strip() or (topic.name if topic else "")
    if not focus:
        raise BankError("Give a topic or instructions for the questions.")

    nodes = retrieve(
        bucket,
        query=focus,
        top_k=max(6, min(16, total + 4)),
        kinds=kinds or [Document.KIND_NOTES],
    )
    if not nodes:
        raise BankError("No indexed notes match that topic yet.")

    avoid = list(
        QuestionItem.objects.filter(bucket=bucket, topic=topic)
        .order_by("-created_at")
        .values_list("prompt", flat=True)[:15]
    ) if topic else []
    want = ", ".join(f"{n} {t}" for t, n in counts.items() if int(n or 0) > 0)
    user = (
        f"Excerpts:\n\n{build_context(nodes)}\n\n"
        f"Topic / instructions: {focus}\n"
        f"Difficulty: {difficulty}\n"
        f"Create exactly: {want}.\n"
        + ("AVOID:\n- " + "\n- ".join(a[:200] for a in avoid) if avoid else "")
    )
    try:
        data = llm_json(_GEN_SYSTEM, user, max_tokens=6000)
    except LLMJSONError as exc:
        raise BankError("The AI returned an unreadable answer. Please try again.") from exc

    raw_items = data.get("questions") or []
    chunk_ids = [n.get("chunk_id") for n in nodes if n.get("chunk_id")]
    for raw in raw_items:
        raw.setdefault("difficulty", difficulty)
        raw["source_chunk_ids"] = chunk_ids[:5]
    created, _ = add_items(
        bucket,
        raw_items,
        source=QuestionItem.SOURCE_AI,
        created_by=member,
        topic=topic,
    )
    if not created:
        raise BankError("The AI did not produce usable questions. Try a narrower topic.")
    return created


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def import_from_mock_test(test, *, created_by=None) -> tuple[list[QuestionItem], int]:
    """Copy a mock test's questions into the bank and tag the mock questions' topics."""
    created, skipped = [], 0
    for q in test.questions.all():
        new, skip = add_items(
            test.bucket,
            [
                {
                    "qtype": q.qtype,
                    "prompt": q.prompt,
                    "options": q.options,
                    "correct_indices": q.correct_indices,
                    "answer": q.model_answer,
                    "marks": q.marks,
                    "topic_id": q.topic_id,
                }
            ],
            source=QuestionItem.SOURCE_MOCK,
            created_by=created_by or test.created_by,
            source_ref=f"mock:{test.id}",
        )
        created.extend(new)
        skipped += skip
        topic_id = new[0].topic_id if new else None
        if topic_id is None:
            h = prompt_hash(q.prompt)
            topic_id = (
                QuestionItem.objects.filter(bucket=test.bucket, prompt_hash=h)
                .values_list("topic_id", flat=True)
                .first()
            )
        if topic_id and q.topic_id != topic_id:
            q.topic_id = topic_id
            q.save(update_fields=["topic"])
    return created, skipped


_EXTRACT_SYSTEM = (
    "You extract exam questions from the text of a previous-year question paper.\n"
    "Return JSON only: {\"questions\":[{\"qtype\":\"mcq|multi|brief|long|numeric\","
    "\"prompt\":\"full question text\",\"options\":[\"..\"],\"correct_indices\":[0],"
    "\"answer\":\"answer or solution if present in the text, else empty\","
    "\"marks\":4,\"difficulty\":\"easy|medium|hard\"}]}\n"
    "Copy question wording faithfully, keep math as LaTeX ($...$). If the answer key or "
    "solution is in the text, set correct_indices/answer from it; if not, give your best "
    "answer. Skip instructions, headers, and incomplete fragments."
)

_WINDOW_CHARS = 7000
_MAX_WINDOWS = 10


def year_from_filename(name: str) -> int | None:
    match = _YEAR.search(name or "")
    return int(match.group(1)) if match else None


def import_from_document(document: Document, *, created_by=None) -> tuple[int, int]:
    """Extract questions from a past paper's indexed chunks. Returns (created, skipped)."""
    chunks = list(
        Chunk.objects.filter(document=document).order_by("order_index").values_list("text", flat=True)
    )
    if not chunks:
        raise BankError("This document has no indexed text yet.")

    windows: list[str] = []
    buf = ""
    for text in chunks:
        if buf and len(buf) + len(text) > _WINDOW_CHARS:
            windows.append(buf)
            buf = ""
        buf += ("\n\n" if buf else "") + text
    if buf:
        windows.append(buf)

    year = year_from_filename(document.original_filename)
    created_total, skipped_total = 0, 0
    for window in windows[:_MAX_WINDOWS]:
        try:
            data = llm_json(
                _EXTRACT_SYSTEM,
                f"Paper: {document.original_filename}\n\nText:\n{window}",
                max_tokens=6000,
            )
        except LLMJSONError:
            logger.warning("past-paper extraction window unreadable doc=%s", document.id)
            continue
        created, skipped = add_items(
            document.bucket,
            data.get("questions") or [],
            source=QuestionItem.SOURCE_PAST_PAPER,
            created_by=created_by,
            source_ref=f"doc:{document.id}",
            source_document=document,
            source_year=year,
        )
        created_total += len(created)
        skipped_total += skipped
    return created_total, skipped_total


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------


def split_by_mix(count: int, mix: dict[str, Any] | None) -> dict[str, int]:
    """Split `count` across easy/medium/hard by percentage (largest remainder)."""
    mix = {k: float(v) for k, v in (mix or {}).items() if k in QuestionItem.DIFFICULTIES}
    if not mix or sum(mix.values()) <= 0:
        return {"any": count}
    total = sum(mix.values())
    exact = {k: count * v / total for k, v in mix.items()}
    out = {k: int(v) for k, v in exact.items()}
    remainder = count - sum(out.values())
    for k in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True)[:remainder]:
        out[k] += 1
    return {k: v for k, v in out.items() if v > 0}


def pick_items(
    bucket: SubjectBucket,
    *,
    qtype: str,
    count: int,
    topic_ids: list[int] | None = None,
    difficulty_mix: dict | None = None,
    exclude_ids: set[int] | None = None,
) -> list[QuestionItem]:
    """Least-used-first selection honouring topic and difficulty filters."""
    exclude_ids = set(exclude_ids or ())
    base = QuestionItem.objects.filter(bucket=bucket, qtype=qtype, is_archived=False)
    if topic_ids:
        base = base.filter(topic_id__in=topic_ids)
    picked: list[QuestionItem] = []

    def take(qs, n):
        rows = list(qs.exclude(pk__in=exclude_ids).order_by("times_used", "?")[: n * 3])
        rows.sort(key=lambda r: (r.times_used, random.random()))
        chosen = rows[:n]
        exclude_ids.update(r.id for r in chosen)
        return chosen

    for diff, n in split_by_mix(count, difficulty_mix).items():
        qs = base if diff == "any" else base.filter(difficulty=diff)
        picked.extend(take(qs, n))
    if len(picked) < count:  # relax difficulty before giving up
        picked.extend(take(base, count - len(picked)))
    return picked


def bank_queryset_for(member: SchoolMembership, params) -> Any:
    qs = QuestionItem.objects.filter(school=member.school).select_related("topic", "bucket")
    if not member.is_manager_or_above:
        qs = qs.filter(bucket__access_grants__member=member).distinct()
    if params.get("bucket_id"):
        qs = qs.filter(bucket_id=params["bucket_id"])
    if params.get("topic_id"):
        qs = qs.filter(topic_id=params["topic_id"])
    if params.get("qtype"):
        qs = qs.filter(qtype=params["qtype"])
    if params.get("difficulty"):
        qs = qs.filter(difficulty=params["difficulty"])
    if params.get("source"):
        qs = qs.filter(source=params["source"])
    if params.get("year"):
        qs = qs.filter(source_year=params["year"])
    if params.get("untagged") in ("1", "true"):
        qs = qs.filter(topic__isnull=True)
    if params.get("include_archived") not in ("1", "true"):
        qs = qs.filter(is_archived=False)
    search = (params.get("q") or "").strip()
    if search:
        qs = qs.filter(Q(prompt__icontains=search) | Q(answer__icontains=search))
    return qs


@transaction.atomic
def build_mock_test_from_bank(
    member: SchoolMembership,
    bucket: SubjectBucket,
    *,
    title: str,
    duration_minutes: int,
    counts: dict[str, int],
    marks: dict[str, int],
    topic_ids: list[int] | None = None,
    difficulty_mix: dict | None = None,
    results_mode: str = "after_review",
    item_ids: list[int] | None = None,
):
    """Create a draft MockTest from bank questions (no LLM call)."""
    from mock_tests.models import MockQuestion, MockTest

    chosen: dict[str, list[QuestionItem]] = {"mcq": [], "multi": [], "brief": []}
    if item_ids:
        rows = QuestionItem.objects.filter(pk__in=item_ids, bucket=bucket, is_archived=False)
        for row in rows:
            chosen[_mock_type(row.qtype)].append(row)
    else:
        used: set[int] = set()
        for qtype in ("mcq", "multi", "brief"):
            n = int(counts.get(qtype) or 0)
            if n <= 0:
                continue
            source_types = [qtype] if qtype != "brief" else ["brief", "long", "numeric"]
            for st in source_types:
                need = n - len(chosen[qtype])
                if need <= 0:
                    break
                got = pick_items(
                    bucket,
                    qtype=st,
                    count=need,
                    topic_ids=topic_ids,
                    difficulty_mix=difficulty_mix,
                    exclude_ids=used,
                )
                used.update(g.id for g in got)
                chosen[qtype].extend(got)
            if len(chosen[qtype]) < n:
                raise BankError(
                    f"The bank has only {len(chosen[qtype])} usable {qtype} question(s) "
                    f"for this selection (needed {n}). Generate more or relax the filters."
                )

    total = sum(len(v) for v in chosen.values())
    if total == 0:
        raise BankError("No questions selected.")
    test = MockTest.objects.create(
        school=bucket.school,
        bucket=bucket,
        created_by=member,
        title=(title or "Practice test").strip()[:255],
        topic_prompt="Built from the question bank",
        status=MockTest.STATUS_DRAFT,
        question_count=total,
        duration_minutes=max(5, min(300, int(duration_minutes or 30))),
        count_mcq=len(chosen["mcq"]),
        count_multi=len(chosen["multi"]),
        count_brief=len(chosen["brief"]),
        marks_mcq=int(marks.get("mcq") or 1),
        marks_multi=int(marks.get("multi") or 2),
        marks_brief=int(marks.get("brief") or 5),
        results_mode=results_mode
        if results_mode in (MockTest.RESULTS_IMMEDIATE, MockTest.RESULTS_AFTER_REVIEW)
        else MockTest.RESULTS_AFTER_REVIEW,
    )
    order = 1
    for qtype in ("mcq", "multi", "brief"):
        for item in chosen[qtype]:
            MockQuestion.objects.create(
                test=test,
                order=order,
                qtype=qtype,
                prompt=item.prompt,
                options=item.options if qtype != "brief" else [],
                correct_indices=item.correct_indices if qtype != "brief" else [],
                model_answer=item.answer or item.explanation,
                marks=int(marks.get(qtype) or item.marks),
                topic_id=item.topic_id,
                bank_item=item,
            )
            order += 1
    mark_used([i for v in chosen.values() for i in v])
    return test


def _mock_type(qtype: str) -> str:
    return qtype if qtype in ("mcq", "multi") else "brief"
