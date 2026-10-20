"""
Per-topic performance from mock tests, quick checks, and flashcard reviews.

Every graded item contributes (earned, possible) marks to its question's topic.
Accuracy = earned / possible. A topic is "weak" below WEAK_THRESHOLD once at
least MIN_EVIDENCE items were seen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction

from engagement.models import MicroAttempt
from ingestion.api_utils import bucket_students, display_name
from ingestion.models import SchoolMembership, SubjectBucket
from learning.models import ReviewLog
from mock_tests.models import MockAttempt, MockQuestion
from question_bank.models import Topic

WEAK_THRESHOLD = 60.0
MIN_EVIDENCE = 2
FLASHCARD_WEIGHT = 0.5  # a review counts half as much as a test question


@dataclass
class TopicStat:
    topic_id: int
    earned: float = 0.0
    possible: float = 0.0
    items: int = 0
    last_seen: datetime | None = None
    sources: dict = field(default_factory=lambda: defaultdict(int))

    def add(self, earned: float, possible: float, when, source: str, weight: float = 1.0):
        self.earned += earned * weight
        self.possible += possible * weight
        self.items += 1
        self.sources[source] += 1
        if when and (self.last_seen is None or when > self.last_seen):
            self.last_seen = when

    @property
    def accuracy(self) -> float | None:
        return round(100 * self.earned / self.possible, 1) if self.possible else None


def _mock_question_score(q: MockQuestion, raw, grade) -> float:
    if q.qtype == MockQuestion.TYPE_MCQ:
        try:
            selected = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            selected = None
        correct = q.correct_indices or []
        return float(q.marks) if selected is not None and correct and selected == int(correct[0]) else 0.0
    if q.qtype == MockQuestion.TYPE_MULTI:
        if isinstance(raw, list):
            try:
                chosen = {int(x) for x in raw}
            except (TypeError, ValueError):
                chosen = set()
        else:
            chosen = set()
        correct = {int(i) for i in (q.correct_indices or [])}
        return float(q.marks) if correct and chosen == correct else 0.0
    if grade is None:
        return -1.0  # ungraded brief — skip
    score = grade.teacher_score if grade.teacher_score is not None else grade.ai_score
    return -1.0 if score is None else float(score)


def topic_stats(
    student: SchoolMembership,
    *,
    bucket: SubjectBucket | None = None,
    visible_only: bool = False,
) -> dict[int, TopicStat]:
    stats: dict[int, TopicStat] = {}

    def stat(tid: int) -> TopicStat:
        return stats.setdefault(tid, TopicStat(topic_id=tid))

    attempts = MockAttempt.objects.filter(student=student, submitted_at__isnull=False).select_related("test")
    if bucket is not None:
        attempts = attempts.filter(test__bucket=bucket)
    for attempt in attempts.prefetch_related("test__questions", "answer_grades"):
        if visible_only and not attempt.student_can_see_results():
            continue
        grades = {g.question_id: g for g in attempt.answer_grades.all()}
        for q in attempt.test.questions.all():
            if not q.topic_id:
                continue
            raw = attempt.answers.get(str(q.id), attempt.answers.get(q.id))
            earned = _mock_question_score(q, raw, grades.get(q.id))
            if earned < 0:
                continue
            stat(q.topic_id).add(earned, float(q.marks), attempt.submitted_at, "mock_test")

    micros = MicroAttempt.objects.filter(student=student).select_related("quiz")
    if bucket is not None:
        micros = micros.filter(quiz__bucket=bucket)
    for attempt in micros.prefetch_related("quiz__questions"):
        for q in attempt.quiz.questions.all():
            if not q.topic_id:
                continue
            chosen = attempt.answers.get(str(q.id))
            stat(q.topic_id).add(
                1.0 if chosen == q.correct_index else 0.0, 1.0, attempt.submitted_at, "quick_check"
            )

    reviews = ReviewLog.objects.filter(member=student, card__topic__isnull=False).select_related("card")
    if bucket is not None:
        reviews = reviews.filter(card__deck__bucket=bucket)
    for log in reviews.order_by("-reviewed_at")[:500]:
        stat(log.card.topic_id).add(
            1.0 if log.grade >= 3 else 0.0, 1.0, log.reviewed_at, "flashcards", FLASHCARD_WEIGHT
        )
    return stats


def _status(st: TopicStat) -> str:
    if st.items < MIN_EVIDENCE or st.accuracy is None:
        return "not_enough_data"
    if st.accuracy < WEAK_THRESHOLD:
        return "weak"
    if st.accuracy < 80:
        return "developing"
    return "strong"


def student_topic_report(student: SchoolMembership, *, bucket=None, visible_only: bool = False) -> dict:
    stats = topic_stats(student, bucket=bucket, visible_only=visible_only)
    topics = {t.id: t for t in Topic.objects.filter(pk__in=stats.keys()).select_related("bucket")}
    rows = []
    for tid, st in stats.items():
        topic = topics.get(tid)
        if topic is None:
            continue
        rows.append(
            {
                "topic_id": tid,
                "topic_name": topic.name,
                "bucket_id": topic.bucket_id,
                "bucket_name": topic.bucket.name,
                "accuracy": st.accuracy,
                "items": st.items,
                "status": _status(st),
                "sources": dict(st.sources),
                "last_seen": st.last_seen,
                "chat_prompt": f"Explain {topic.name} step by step with an example.",
            }
        )
    rows.sort(key=lambda r: (r["accuracy"] is None, r["accuracy"] if r["accuracy"] is not None else 0))
    weak = [r for r in rows if r["status"] == "weak"]
    return {
        "student_id": student.id,
        "name": display_name(student),
        "bucket_id": bucket.id if bucket else None,
        "topics": rows,
        "weak_topics": weak,
        "summary": (
            f"Needs work on {', '.join(r['topic_name'] for r in weak[:3])}"
            + (f" (+{len(weak) - 3} more)" if len(weak) > 3 else "")
            if weak
            else None
        ),
        "threshold": WEAK_THRESHOLD,
    }


def class_heatmap(bucket: SubjectBucket) -> dict:
    students = list(bucket_students(bucket))
    topics = list(Topic.objects.filter(bucket=bucket))
    matrix = []
    totals: dict[int, TopicStat] = {t.id: TopicStat(topic_id=t.id) for t in topics}
    for s in students:
        stats = topic_stats(s, bucket=bucket)
        cells = {}
        for t in topics:
            st = stats.get(t.id)
            if st:
                cells[str(t.id)] = {"accuracy": st.accuracy, "items": st.items, "status": _status(st)}
                agg = totals[t.id]
                agg.earned += st.earned
                agg.possible += st.possible
                agg.items += st.items
        weak = [t.name for t in topics if cells.get(str(t.id), {}).get("status") == "weak"]
        matrix.append(
            {
                "student_id": s.id,
                "name": display_name(s),
                "cells": cells,
                "weak_count": len(weak),
                "weak_topics": weak[:5],
            }
        )
    topic_rows = []
    for t in topics:
        agg = totals[t.id]
        weak_students = sum(1 for row in matrix if row["cells"].get(str(t.id), {}).get("status") == "weak")
        topic_rows.append(
            {
                "topic_id": t.id,
                "topic_name": t.name,
                "class_accuracy": agg.accuracy,
                "items": agg.items,
                "weak_students": weak_students,
            }
        )
    matrix.sort(key=lambda r: -r["weak_count"])
    return {
        "bucket_id": bucket.id,
        "bucket_name": bucket.name,
        "topics": topic_rows,
        "students": matrix,
        "threshold": WEAK_THRESHOLD,
    }


def class_weak_topics(bucket: SubjectBucket) -> list[dict]:
    heat = class_heatmap(bucket)
    rows = [t for t in heat["topics"] if t["class_accuracy"] is not None]
    rows.sort(key=lambda t: (t["class_accuracy"], -t["weak_students"]))
    return rows


@transaction.atomic
def build_remediation(
    actor: SchoolMembership | None,
    bucket: SubjectBucket,
    *,
    students: list[SchoolMembership],
    topic_ids: list[int] | None,
    question_count: int = 10,
    self_practice: bool = False,
) -> dict:
    """Practice test on weak topics from the bank (AI tops up the bank if short)."""
    from question_bank.models import QuestionItem
    from question_bank.services.bank import BankError, build_mock_test_from_bank, generate_items
    from question_bank.views import assign_and_publish

    if not topic_ids:
        weak: dict[int, int] = defaultdict(int)
        for s in students:
            for row in student_topic_report(s, bucket=bucket)["weak_topics"]:
                weak[row["topic_id"]] += 1
        topic_ids = [tid for tid, _ in sorted(weak.items(), key=lambda kv: -kv[1])[:5]]
    if not topic_ids:
        raise BankError("No weak topics found yet — students need a few graded tests or quick checks first.")
    topics = list(Topic.objects.filter(pk__in=topic_ids, bucket=bucket))
    if not topics:
        raise BankError("Pick topics from this AI Bucket.")

    available = QuestionItem.objects.filter(
        bucket=bucket, topic__in=topics, qtype="mcq", is_archived=False
    ).count()
    if available < question_count and actor is not None:
        per_topic = max(2, (question_count - available) // len(topics) + 1)
        for topic in topics:
            try:
                generate_items(actor, bucket, prompt=topic.name, counts={"mcq": per_topic}, topic=topic)
            except BankError:
                continue

    available = QuestionItem.objects.filter(
        bucket=bucket, topic__in=topics, qtype="mcq", is_archived=False
    ).count()
    question_count = min(question_count, available)
    if question_count < 1:
        raise BankError(
            "The question bank has no practice questions for these topics yet. "
            "Ask your teacher to add some."
        )
    test = build_mock_test_from_bank(
        actor,
        bucket,
        title=("Practice: " if self_practice else "Revision: ") + ", ".join(t.name for t in topics[:3])[:200],
        duration_minutes=max(10, question_count * 2),
        counts={"mcq": question_count},
        marks={"mcq": 1},
        topic_ids=[t.id for t in topics],
        results_mode="immediate",
    )
    if self_practice:
        test.created_by = None
        test.topic_prompt = "Self practice on weak topics"
        test.save(update_fields=["created_by", "topic_prompt"])
    assigned = assign_and_publish(
        test, actor or students[0], [s.id for s in students], publish=True
    )
    return {
        "mock_test_id": test.id,
        "title": test.title,
        "question_count": test.question_count,
        "topics": [{"topic_id": t.id, "topic_name": t.name} for t in topics],
        "assigned": assigned,
    }
