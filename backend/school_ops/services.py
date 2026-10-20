"""Attendance marking/summaries and the parent's read-only child overview."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from ingestion.api_utils import bucket_students, display_name
from ingestion.models import SchoolMembership

from .models import AttendanceRecord, ParentLink, ParentProfile

logger = logging.getLogger(__name__)

LATE_AFTER = timedelta(minutes=10)
JOIN_WINDOW_BEFORE = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


def lecture_open_for_join(lecture) -> bool:
    if lecture.status == lecture.STATUS_LIVE:
        return True
    if lecture.status != lecture.STATUS_SCHEDULED:
        return False
    now = timezone.now()
    return lecture.starts_at - JOIN_WINDOW_BEFORE <= now <= lecture.ends_at


def record_join(lecture, student: SchoolMembership) -> AttendanceRecord | None:
    """Auto-mark a student who opened the lecture room while it was running."""
    if student.role != SchoolMembership.ROLE_STUDENT or not lecture_open_for_join(lecture):
        return None
    now = timezone.now()
    status = (
        AttendanceRecord.STATUS_LATE
        if now > lecture.starts_at + LATE_AFTER
        else AttendanceRecord.STATUS_PRESENT
    )
    record, created = AttendanceRecord.objects.get_or_create(
        lecture=lecture,
        student=student,
        defaults={
            "school_id": lecture.school_id,
            "status": status,
            "source": AttendanceRecord.SOURCE_AUTO,
            "first_seen_at": now,
        },
    )
    if not created and record.source == AttendanceRecord.SOURCE_AUTO and record.status == AttendanceRecord.STATUS_ABSENT:
        record.status = status
        record.first_seen_at = record.first_seen_at or now
        record.save(update_fields=["status", "first_seen_at", "updated_at"])
    if created:
        try:
            from engagement.models import EngagementActivity
            from engagement.services.activity import record_activity

            record_activity(
                member=student,
                kind=EngagementActivity.KIND_LECTURE_JOIN,
                bucket=lecture.bucket,
                ref_id=f"lecture:{lecture.id}",
            )
        except Exception:
            logger.exception("lecture join activity failed")
    return record


def finalize_lecture(lecture) -> int:
    """When a lecture ends, mark granted students who never joined as absent."""
    seen = set(
        AttendanceRecord.objects.filter(lecture=lecture).values_list("student_id", flat=True)
    )
    missing = [s for s in bucket_students(lecture.bucket) if s.id not in seen]
    AttendanceRecord.objects.bulk_create(
        [
            AttendanceRecord(
                school_id=lecture.school_id,
                lecture=lecture,
                student=s,
                status=AttendanceRecord.STATUS_ABSENT,
                source=AttendanceRecord.SOURCE_AUTO,
            )
            for s in missing
        ],
        ignore_conflicts=True,
    )
    return len(missing)


def lecture_roster(lecture) -> dict:
    records = {
        r.student_id: r
        for r in AttendanceRecord.objects.filter(lecture=lecture).select_related("student__user")
    }
    students = {s.id: s for s in bucket_students(lecture.bucket)}
    for sid, rec in records.items():
        students.setdefault(sid, rec.student)
    rows = []
    for sid, s in students.items():
        rec = records.get(sid)
        rows.append(
            {
                "student_id": sid,
                "name": display_name(s),
                "username": s.user.username,
                "status": rec.status if rec else "unmarked",
                "source": rec.source if rec else None,
                "first_seen_at": rec.first_seen_at if rec else None,
                "note": rec.note if rec else "",
            }
        )
    rows.sort(key=lambda r: r["name"].lower())
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "lecture_id": lecture.id,
        "lecture_title": lecture.title,
        "starts_at": lecture.starts_at,
        "status": lecture.status,
        "counts": counts,
        "students": rows,
    }


@transaction.atomic
def set_attendance(lecture, actor: SchoolMembership, entries: list[dict]) -> int:
    valid_status = {c[0] for c in AttendanceRecord.STATUS_CHOICES}
    allowed = {s.id for s in bucket_students(lecture.bucket)} | set(
        AttendanceRecord.objects.filter(lecture=lecture).values_list("student_id", flat=True)
    )
    changed = 0
    for entry in entries:
        sid = int(entry.get("student_id") or 0)
        status = entry.get("status")
        if sid not in allowed or status not in valid_status:
            continue
        AttendanceRecord.objects.update_or_create(
            lecture=lecture,
            student_id=sid,
            defaults={
                "school_id": lecture.school_id,
                "status": status,
                "source": AttendanceRecord.SOURCE_MANUAL,
                "note": (entry.get("note") or "")[:255],
                "marked_by": actor,
            },
        )
        changed += 1
    return changed


def student_attendance(student: SchoolMembership, *, bucket_id=None, days: int | None = None) -> dict:
    qs = AttendanceRecord.objects.filter(student=student).select_related("lecture__bucket")
    if bucket_id:
        qs = qs.filter(lecture__bucket_id=bucket_id)
    if days:
        qs = qs.filter(lecture__starts_at__gte=timezone.now() - timedelta(days=days))
    qs = qs.order_by("-lecture__starts_at")
    total = qs.exclude(status=AttendanceRecord.STATUS_EXCUSED).count()
    attended = qs.filter(status__in=AttendanceRecord.ATTENDED).count()
    by_bucket = []
    for row in (
        qs.values("lecture__bucket_id", "lecture__bucket__name")
        .annotate(
            total=Count("id", filter=~Q(status=AttendanceRecord.STATUS_EXCUSED)),
            attended=Count("id", filter=Q(status__in=AttendanceRecord.ATTENDED)),
        )
        .order_by("lecture__bucket__name")
    ):
        by_bucket.append(
            {
                "bucket_id": row["lecture__bucket_id"],
                "bucket_name": row["lecture__bucket__name"],
                "total": row["total"],
                "attended": row["attended"],
                "percent": round(100 * row["attended"] / row["total"], 1) if row["total"] else None,
            }
        )
    return {
        "student_id": student.id,
        "name": display_name(student),
        "total": total,
        "attended": attended,
        "percent": round(100 * attended / total, 1) if total else None,
        "by_bucket": by_bucket,
        "recent": [
            {
                "lecture_id": r.lecture_id,
                "lecture_title": r.lecture.title,
                "bucket_name": r.lecture.bucket.name,
                "starts_at": r.lecture.starts_at,
                "status": r.status,
                "note": r.note,
            }
            for r in qs[:30]
        ],
    }


def bucket_attendance(bucket) -> list[dict]:
    rows = []
    for s in bucket_students(bucket):
        summary = student_attendance(s, bucket_id=bucket.id)
        rows.append(
            {
                "student_id": s.id,
                "name": summary["name"],
                "total": summary["total"],
                "attended": summary["attended"],
                "percent": summary["percent"],
            }
        )
    rows.sort(key=lambda r: (r["percent"] is None, r["percent"] or 0))
    return rows


# ---------------------------------------------------------------------------
# Parents
# ---------------------------------------------------------------------------


def parent_profile_for(user) -> ParentProfile | None:
    if not user or not user.is_authenticated:
        return None
    try:
        profile = user.parent_profile
    except ParentProfile.DoesNotExist:
        return None
    return profile if profile and profile.is_active else None


def children_of(profile: ParentProfile):
    return SchoolMembership.objects.filter(
        parent_links__parent=profile, is_active=True, role=SchoolMembership.ROLE_STUDENT
    ).select_related("user")


def parent_payload(profile: ParentProfile) -> dict:
    return {
        "id": profile.id,
        "phone": profile.phone,
        "weekly_email": profile.weekly_email,
        "children": [
            {
                "student_id": link.student_id,
                "name": display_name(link.student),
                "relationship": link.relationship,
            }
            for link in profile.links.select_related("student__user").filter(student__is_active=True)
        ],
    }


def child_overview(student: SchoolMembership) -> dict:
    """Everything a parent sees: released results, attendance, streak, progress."""
    from engagement.services.activity import get_streak_payload
    from engagement.services.mastery import mastery_list_for_member
    from mock_tests.models import MockAssignment, MockAttempt

    attempts = MockAttempt.objects.filter(student=student, submitted_at__isnull=False).select_related(
        "test__bucket"
    )
    results = []
    for a in attempts.order_by("-submitted_at")[:20]:
        visible = a.student_can_see_results()
        results.append(
            {
                "test_id": a.test_id,
                "title": a.test.title,
                "bucket_name": a.test.bucket.name,
                "submitted_at": a.submitted_at,
                "released": visible,
                "score": a.score if visible else None,
                "max_score": a.max_score if visible else None,
                "percent": a.percent if visible else None,
            }
        )
    attempted = set(attempts.values_list("test_id", flat=True))
    pending = [
        {"test_id": a.test_id, "title": a.test.title, "bucket_name": a.test.bucket.name}
        for a in MockAssignment.objects.filter(student=student, test__status="published")
        .select_related("test__bucket")
        .exclude(test_id__in=attempted)[:20]
    ]
    homework = []
    try:
        from homework.services import student_homework_summary

        homework = student_homework_summary(student)
    except Exception:
        logger.exception("homework summary for parent failed")
    return {
        "student_id": student.id,
        "name": display_name(student),
        "school_name": student.school.name,
        "streak": get_streak_payload(student),
        "subjects": mastery_list_for_member(student),
        "attendance": student_attendance(student, days=90),
        "test_results": results,
        "pending_tests": pending,
        "homework": homework,
    }
