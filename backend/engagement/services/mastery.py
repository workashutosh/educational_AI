"""Cached subject mastery from tests, micro-quizzes, and chat."""
from __future__ import annotations

import logging

from django.db.models import Avg, Count

from engagement.models import EngagementActivity, MicroAttempt, SubjectMastery
from engagement.services.constants import (
    CHAT_TURNS_FOR_FULL,
    MASTERY_WEIGHT_CHAT,
    MASTERY_WEIGHT_MICRO,
    MASTERY_WEIGHT_MOCK,
)
from ingestion.models import SchoolMembership
from mock_tests.models import MockAttempt

logger = logging.getLogger(__name__)


def recompute_mastery(*, member, bucket) -> SubjectMastery:
    # Released mock attempts only (or immediate results)
    attempts = MockAttempt.objects.filter(
        student=member,
        test__bucket=bucket,
        submitted_at__isnull=False,
    )
    # Prefer released; if immediate mode results_released_at may be set on submit
    released = attempts.exclude(results_released_at__isnull=True)
    use = released if released.exists() else attempts.none()

    mock_avg = use.aggregate(a=Avg("percent"))["a"]
    tests_taken = use.count()
    mock_component = float(mock_avg or 0.0)

    micros = MicroAttempt.objects.filter(student=member, quiz__bucket=bucket)
    micro_taken = micros.count()
    if micro_taken:
        # score / max_score * 100
        vals = []
        for a in micros:
            mx = max(1, int(a.max_score or 3))
            vals.append(100.0 * float(a.score) / mx)
        micro_component = sum(vals) / len(vals)
    else:
        micro_component = 0.0

    chat_turns = EngagementActivity.objects.filter(
        member=member,
        bucket=bucket,
        kind=EngagementActivity.KIND_ASK,
    ).count()
    chat_component = min(100.0, 100.0 * chat_turns / max(1, CHAT_TURNS_FOR_FULL))

    # If no signal at all, score 0
    has_signal = tests_taken or micro_taken or chat_turns
    if not has_signal:
        score = 0
    else:
        # Renormalize weights when some signals missing
        w_mock = MASTERY_WEIGHT_MOCK if tests_taken else 0.0
        w_micro = MASTERY_WEIGHT_MICRO if micro_taken else 0.0
        w_chat = MASTERY_WEIGHT_CHAT if chat_turns else 0.0
        total_w = w_mock + w_micro + w_chat
        if total_w <= 0:
            score = 0
        else:
            score = (
                w_mock * mock_component
                + w_micro * micro_component
                + w_chat * chat_component
            ) / total_w
            score = int(round(max(0.0, min(100.0, score))))

    obj, _ = SubjectMastery.objects.update_or_create(
        member=member,
        bucket=bucket,
        defaults={
            "score_0_100": score,
            "tests_taken": tests_taken,
            "micro_taken": micro_taken,
            "chat_turns": chat_turns,
        },
    )
    return obj


def mastery_list_for_member(member) -> list[dict]:
    rows = (
        SubjectMastery.objects.filter(member=member)
        .select_related("bucket")
        .order_by("-score_0_100")
    )
    return [
        {
            "bucket_id": r.bucket_id,
            "bucket_name": r.bucket.name,
            "score": r.score_0_100,
            "tests_taken": r.tests_taken,
            "micro_taken": r.micro_taken,
            "chat_turns": r.chat_turns,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


def class_mastery_for_bucket(bucket) -> list[dict]:
    students = SchoolMembership.objects.filter(
        school=bucket.school,
        role=SchoolMembership.ROLE_STUDENT,
        is_active=True,
        bucket_grants__bucket=bucket,
    ).select_related("user").distinct()
    out = []
    for s in students:
        m = SubjectMastery.objects.filter(member=s, bucket=bucket).first()
        out.append(
            {
                "member_id": s.id,
                "display_name": s.user.get_full_name() or s.user.username,
                "score": m.score_0_100 if m else 0,
            }
        )
    out.sort(key=lambda x: -x["score"])
    return out
