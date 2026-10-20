"""Celery tasks for engagement lifecycle + digests."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="engagement.on_document_indexed", max_retries=0)
def on_document_indexed(document_id: int) -> dict:
    from engagement.services.micro_quiz import generate_micro_quiz_for_document
    from engagement.services.notifications import notify_many
    from ingestion.models import BucketAccess, Document, SchoolMembership

    try:
        doc = Document.objects.select_related("bucket").get(pk=document_id)
    except Document.DoesNotExist:
        return {"ok": False, "error": "missing"}

    # Notify students with access
    student_ids = BucketAccess.objects.filter(bucket=doc.bucket).values_list(
        "member_id", flat=True
    )
    students = SchoolMembership.objects.filter(
        id__in=student_ids,
        role=SchoolMembership.ROLE_STUDENT,
        is_active=True,
    )
    notify_many(
        students,
        kind="new_notes",
        title=f"New notes in {doc.bucket.name}",
        body=doc.original_filename,
        link_path=f"/app/chat?bucket={doc.bucket_id}",
        dedupe_key=f"doc:{doc.id}",
    )

    quiz = None
    from billing.services.usage import usage_scope

    try:
        with usage_scope(school_id=doc.bucket.school_id, feature="micro_quiz"):
            quiz = generate_micro_quiz_for_document(document_id)
    except Exception:
        logger.exception("micro quiz after index failed doc=%s", document_id)

    return {
        "ok": True,
        "quiz_id": quiz.id if quiz and quiz.status == "ready" else None,
    }


@shared_task(name="engagement.on_lecture_ended", max_retries=0)
def on_lecture_ended(lecture_id: int) -> dict:
    from engagement.services.micro_quiz import generate_micro_quiz_for_lecture
    from engagement.services.notifications import notify_many
    from ingestion.models import BucketAccess, SchoolMembership
    from lectures.models import Lecture

    try:
        lec = Lecture.objects.select_related("bucket").get(pk=lecture_id)
    except Lecture.DoesNotExist:
        return {"ok": False}

    student_ids = BucketAccess.objects.filter(bucket=lec.bucket).values_list(
        "member_id", flat=True
    )
    students = SchoolMembership.objects.filter(
        id__in=student_ids,
        role=SchoolMembership.ROLE_STUDENT,
        is_active=True,
    )
    notify_many(
        students,
        kind="lecture_ended",
        title=f"Lecture ended: {lec.title}",
        body="A short quick check may be ready — keep your streak going.",
        link_path=f"/app/lectures/{lec.id}",
        dedupe_key=f"lec_end:{lec.id}",
    )

    quiz = None
    from billing.services.usage import usage_scope

    try:
        with usage_scope(school_id=lec.school_id, feature="micro_quiz"):
            quiz = generate_micro_quiz_for_lecture(lecture_id)
    except Exception:
        logger.exception("micro quiz after lecture failed id=%s", lecture_id)

    return {"ok": True, "quiz_id": quiz.id if quiz else None}


@shared_task(name="engagement.send_teacher_daily_digests")
def send_teacher_daily_digests_task() -> dict:
    from engagement.services.digests import send_teacher_daily_digests

    return send_teacher_daily_digests()


@shared_task(name="engagement.send_student_weekly_digests")
def send_student_weekly_digests_task() -> dict:
    from engagement.services.digests import send_student_weekly_digests

    return send_student_weekly_digests()


@shared_task(name="engagement.recompute_member_mastery")
def recompute_member_mastery(member_id: int, bucket_id: int) -> dict:
    from engagement.services.mastery import recompute_mastery
    from ingestion.models import SchoolMembership, SubjectBucket

    try:
        member = SchoolMembership.objects.get(pk=member_id)
        bucket = SubjectBucket.objects.get(pk=bucket_id)
    except (SchoolMembership.DoesNotExist, SubjectBucket.DoesNotExist):
        return {"ok": False}
    m = recompute_mastery(member=member, bucket=bucket)
    return {"ok": True, "score": m.score_0_100}
