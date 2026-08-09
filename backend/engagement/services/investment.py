"""Bucket investment / switching-cost stats."""
from __future__ import annotations

from engagement.models import MicroQuiz
from ingestion.models import (
    BucketAccess,
    ChatSession,
    Document,
    SchoolMembership,
    SubjectBucket,
)
from mock_tests.models import MockTest

def bucket_investment(bucket: SubjectBucket) -> dict:
    notes = Document.objects.filter(
        bucket=bucket,
        kind=Document.KIND_NOTES,
        deleted_at__isnull=True,
    ).exclude(status=Document.STATUS_FAILED).count()
    papers = Document.objects.filter(
        bucket=bucket,
        kind=Document.KIND_QUESTION_PAPER,
        deleted_at__isnull=True,
    ).exclude(status=Document.STATUS_FAILED).count()
    tests = MockTest.objects.filter(bucket=bucket).exclude(
        status=MockTest.STATUS_DRAFT
    ).count()
    micros = MicroQuiz.objects.filter(
        bucket=bucket, status=MicroQuiz.STATUS_READY
    ).count()
    students = (
        BucketAccess.objects.filter(
            bucket=bucket,
            member__role=SchoolMembership.ROLE_STUDENT,
            member__is_active=True,
        )
        .values("member_id")
        .distinct()
        .count()
    )
    chats = ChatSession.objects.filter(bucket=bucket).count()
    return {
        "bucket_id": bucket.id,
        "bucket_name": bucket.name,
        "notes": notes,
        "question_papers": papers,
        "tests": tests,
        "micro_quizzes": micros,
        "students": students,
        "chat_sessions": chats,
        "summary": (
            f"{notes} notes · {papers} papers · {tests} tests · "
            f"{micros} quick checks · used by {students} students"
        ),
    }
