"""Question-paper generation: blueprint sections → bank picks → AI gap-fill."""
from __future__ import annotations

import logging

from django.db import transaction

from ingestion.models import SchoolMembership, SubjectBucket
from ingestion.services.llm_errors import LLMProviderError

from ..models import PaperItem, PaperSection, QuestionItem, QuestionPaper, Topic
from .bank import BankError, generate_items, mark_used, pick_items, split_by_mix

logger = logging.getLogger(__name__)

MAX_SECTIONS = 10
MAX_ITEMS = 120


def _snapshot(item: QuestionItem, *, section: PaperSection, order: int) -> PaperItem:
    return PaperItem(
        section=section,
        order=order,
        question=item,
        qtype=item.qtype,
        prompt=item.prompt,
        options=item.options,
        correct_indices=item.correct_indices,
        answer=item.answer,
        explanation=item.explanation,
        marks=section.marks_each or item.marks,
        difficulty=item.difficulty,
        topic_name=item.topic.name if item.topic_id else "",
    )


def _fill_section(
    paper: QuestionPaper,
    section: PaperSection,
    member: SchoolMembership,
    used: set[int],
) -> list[str]:
    """Pick (and if allowed, generate) questions for one section. Returns notes."""
    notes: list[str] = []
    bucket = paper.bucket
    need = section.requested_count
    chosen: list[QuestionItem] = []

    if paper.source_mode != QuestionPaper.MODE_AI_ONLY:
        chosen = pick_items(
            bucket,
            qtype=section.qtype,
            count=need,
            topic_ids=paper.topic_ids or None,
            difficulty_mix=paper.difficulty_mix,
            exclude_ids=used,
        )
        used.update(c.id for c in chosen)

    short = need - len(chosen)
    if short > 0 and paper.source_mode != QuestionPaper.MODE_BANK_ONLY:
        topics = list(Topic.objects.filter(pk__in=paper.topic_ids, bucket=bucket)) if paper.topic_ids else []
        focus = ", ".join(t.name for t in topics) or paper.title
        for diff, n in split_by_mix(short, paper.difficulty_mix).items():
            try:
                fresh = generate_items(
                    member,
                    bucket,
                    prompt=f"{focus}. {section.instructions}".strip(),
                    counts={section.qtype: n},
                    difficulty="medium" if diff == "any" else diff,
                    topic=topics[0] if len(topics) == 1 else None,
                )
            except (BankError, LLMProviderError) as exc:
                notes.append(f"{section.title}: AI could not add questions ({exc}).")
                break
            fresh = [f for f in fresh if f.qtype == section.qtype and f.id not in used][:n]
            used.update(f.id for f in fresh)
            chosen.extend(fresh)

    if len(chosen) < need:
        notes.append(
            f"{section.title}: only {len(chosen)} of {need} {section.get_qtype_display().lower()} "
            "question(s) available."
        )

    PaperItem.objects.bulk_create(
        [_snapshot(item, section=section, order=i) for i, item in enumerate(chosen, start=1)]
    )
    mark_used(chosen)
    return notes


def validate_sections(sections: list[dict]) -> list[dict]:
    if not sections:
        raise BankError("Add at least one section.")
    if len(sections) > MAX_SECTIONS:
        raise BankError(f"A paper can have at most {MAX_SECTIONS} sections.")
    valid_types = {c[0] for c in QuestionItem.TYPE_CHOICES}
    total = 0
    out = []
    for i, s in enumerate(sections, start=1):
        qtype = s.get("qtype")
        if qtype not in valid_types:
            raise BankError(f"Section {i}: unknown question type.")
        count = int(s.get("count") or 0)
        if count < 1:
            raise BankError(f"Section {i}: needs at least one question.")
        total += count
        out.append(
            {
                "title": (s.get("title") or f"Section {chr(64 + i)}").strip()[:200],
                "instructions": (s.get("instructions") or "").strip()[:2000],
                "qtype": qtype,
                "count": count,
                "marks_each": max(1, int(s.get("marks_each") or 1)),
            }
        )
    if total > MAX_ITEMS:
        raise BankError(f"A paper can have at most {MAX_ITEMS} questions.")
    return out


@transaction.atomic
def create_paper(
    member: SchoolMembership,
    bucket: SubjectBucket,
    *,
    title: str,
    sections: list[dict],
    exam_name: str = "",
    class_label: str = "",
    instructions: str = "",
    duration_minutes: int = 180,
    source_mode: str = QuestionPaper.MODE_BANK_THEN_AI,
    difficulty_mix: dict | None = None,
    topic_ids: list[int] | None = None,
) -> QuestionPaper:
    specs = validate_sections(sections)
    if source_mode not in {c[0] for c in QuestionPaper.MODE_CHOICES}:
        source_mode = QuestionPaper.MODE_BANK_THEN_AI
    valid_topics = list(
        Topic.objects.filter(bucket=bucket, pk__in=topic_ids or []).values_list("id", flat=True)
    )
    paper = QuestionPaper.objects.create(
        school=bucket.school,
        bucket=bucket,
        created_by=member,
        title=(title or "Question paper").strip()[:255],
        exam_name=exam_name.strip()[:255],
        class_label=(class_label or bucket.grade_level).strip()[:100],
        instructions=instructions.strip(),
        duration_minutes=max(10, min(600, int(duration_minutes or 180))),
        source_mode=source_mode,
        difficulty_mix=difficulty_mix or {},
        topic_ids=valid_topics,
    )
    used: set[int] = set()
    notes: list[str] = []
    for order, spec in enumerate(specs, start=1):
        section = PaperSection.objects.create(
            paper=paper,
            order=order,
            title=spec["title"],
            instructions=spec["instructions"],
            qtype=spec["qtype"],
            marks_each=spec["marks_each"],
            requested_count=spec["count"],
        )
        notes.extend(_fill_section(paper, section, member, used))
    paper.generation_notes = notes
    paper.save(update_fields=["generation_notes"])
    return paper


def refill_section(paper: QuestionPaper, section: PaperSection, member: SchoolMembership) -> list[str]:
    """Replace all questions in a section with a fresh selection."""
    section.items.all().delete()
    used = set(
        PaperItem.objects.filter(section__paper=paper, question__isnull=False).values_list(
            "question_id", flat=True
        )
    )
    return _fill_section(paper, section, member, used)


def swap_item(paper: QuestionPaper, item: PaperItem) -> PaperItem:
    """Replace one question with another bank question of the same type."""
    used = set(
        PaperItem.objects.filter(section__paper=paper, question__isnull=False).values_list(
            "question_id", flat=True
        )
    )
    topic_ids = None
    if item.question_id and item.question.topic_id:
        topic_ids = [item.question.topic_id]
    elif paper.topic_ids:
        topic_ids = paper.topic_ids
    candidates = pick_items(
        paper.bucket, qtype=item.qtype, count=1, topic_ids=topic_ids, exclude_ids=used
    )
    if not candidates and topic_ids:
        candidates = pick_items(paper.bucket, qtype=item.qtype, count=1, exclude_ids=used)
    if not candidates:
        raise BankError("No other bank question of this type is available.")
    new = _snapshot(candidates[0], section=item.section, order=item.order)
    new.marks = item.marks
    item.delete()
    new.save()
    mark_used(candidates)
    return new


@transaction.atomic
def paper_to_mock_test(paper: QuestionPaper, member: SchoolMembership):
    """Turn a paper into a draft mock test (objective + written questions)."""
    from mock_tests.models import MockQuestion, MockTest

    items = list(PaperItem.objects.filter(section__paper=paper).select_related("question", "section"))
    if not items:
        raise BankError("This paper has no questions.")
    counts = {"mcq": 0, "multi": 0, "brief": 0}
    rows = []
    for item in items:
        qtype = item.qtype if item.qtype in ("mcq", "multi") else "brief"
        counts[qtype] += 1
        rows.append((qtype, item))
    test = MockTest.objects.create(
        school=paper.school,
        bucket=paper.bucket,
        created_by=member,
        title=paper.title[:255],
        topic_prompt=f"From question paper #{paper.id}",
        status=MockTest.STATUS_DRAFT,
        question_count=len(rows),
        duration_minutes=max(5, min(300, paper.duration_minutes)),
        count_mcq=counts["mcq"],
        count_multi=counts["multi"],
        count_brief=counts["brief"],
    )
    for order, (qtype, item) in enumerate(rows, start=1):
        MockQuestion.objects.create(
            test=test,
            order=order,
            qtype=qtype,
            prompt=item.prompt,
            options=item.options if qtype != "brief" else [],
            correct_indices=item.correct_indices if qtype != "brief" else [],
            model_answer=item.answer or item.explanation,
            marks=item.marks,
            topic_id=item.question.topic_id if item.question_id else None,
            bank_item=item.question,
        )
    return test
