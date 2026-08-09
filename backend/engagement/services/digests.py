"""Daily teacher + weekly student email digests via Brevo."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from engagement.models import MicroQuiz
from engagement.services.activity import get_streak_payload
from engagement.services.impact import impact_summary
from engagement.services.mastery import mastery_list_for_member
from engagement.services.notifications import get_or_create_prefs
from ingestion.models import Document, SchoolMembership
from ingestion.services.brevo_service import BrevoError, send_transactional_email
from mock_tests.models import MockAssignment, MockAttempt, MockTest

logger = logging.getLogger(__name__)


def send_teacher_daily_digests() -> dict:
    teachers = SchoolMembership.objects.filter(
        is_active=True,
        role__in=[
            SchoolMembership.ROLE_TEACHER,
            SchoolMembership.ROLE_MANAGER,
            SchoolMembership.ROLE_ADMIN,
        ],
    ).select_related("user", "school")
    sent = 0
    skipped = 0
    for member in teachers:
        prefs = get_or_create_prefs(member)
        if not prefs.email_digests:
            skipped += 1
            continue
        email = (member.user.email or "").strip()
        if not email:
            skipped += 1
            continue
        body = _teacher_digest_body(member)
        if not body:
            skipped += 1
            continue
        try:
            send_transactional_email(
                to_email=email,
                to_name=member.user.get_full_name() or member.user.username,
                subject="ClassKit — your daily class digest",
                text=body["text"],
                html=body["html"],
            )
            sent += 1
        except BrevoError as exc:
            logger.warning("Teacher digest failed member=%s: %s", member.id, exc)
            skipped += 1
    return {"sent": sent, "skipped": skipped}


def send_student_weekly_digests() -> dict:
    students = SchoolMembership.objects.filter(
        is_active=True, role=SchoolMembership.ROLE_STUDENT
    ).select_related("user", "school")
    sent = 0
    skipped = 0
    for member in students:
        prefs = get_or_create_prefs(member)
        if not prefs.email_digests:
            skipped += 1
            continue
        email = (member.user.email or "").strip()
        if not email:
            skipped += 1
            continue
        body = _student_digest_body(member)
        if not body:
            skipped += 1
            continue
        try:
            send_transactional_email(
                to_email=email,
                to_name=member.user.get_full_name() or member.user.username,
                subject="ClassKit — your weekly learning digest",
                text=body["text"],
                html=body["html"],
            )
            sent += 1
        except BrevoError as exc:
            logger.warning("Student digest failed member=%s: %s", member.id, exc)
            skipped += 1
    return {"sent": sent, "skipped": skipped}


def _frontend(path: str = "/app") -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "http://127.0.0.1:5173").rstrip("/")
    return f"{base}{path}"


def _teacher_digest_body(member) -> dict | None:
    school = member.school
    since = timezone.now() - timedelta(hours=36)

    # Students who haven't started assigned published tests (school-wide for managers)
    pending_lines = []
    tests = MockTest.objects.filter(
        school=school, status=MockTest.STATUS_PUBLISHED
    )
    if member.role == SchoolMembership.ROLE_TEACHER:
        tests = tests.filter(created_by=member)
    for test in tests[:8]:
        assigned = test.assignments.count()
        started = MockAttempt.objects.filter(test=test).count()
        pending = assigned - started
        if pending > 0:
            pending_lines.append(
                f"• {pending} student(s) haven’t started “{test.title}”"
            )

    new_notes = Document.objects.filter(
        bucket__school=school,
        status=Document.STATUS_INDEXED,
        processed_at__gte=since,
        deleted_at__isnull=True,
    ).count()

    impact = impact_summary(member, days=30)
    lines = []
    if pending_lines:
        lines.append("Action needed:\n" + "\n".join(pending_lines[:5]))
    if new_notes:
        lines.append(f"New notes indexed recently: {new_notes}")
    lines.append(
        f"Time saved this month (est.): ~{impact['hours_saved']} hours "
        f"({impact['minutes_saved']} minutes)."
    )
    if not pending_lines and not new_notes and impact["minutes_saved"] == 0:
        return None

    text = (
        f"Hi {member.user.get_full_name() or member.user.username},\n\n"
        + "\n\n".join(lines)
        + f"\n\nOpen ClassKit: {_frontend('/app')}\n"
    )
    html = (
        f"<p>Hi {member.user.get_full_name() or member.user.username},</p>"
        + "".join(f"<p>{l.replace(chr(10), '<br/>')}</p>" for l in lines)
        + f"<p><a href=\"{_frontend('/app')}\">Open ClassKit</a></p>"
    )
    return {"text": text, "html": html}


def _student_digest_body(member) -> dict | None:
    streak = get_streak_payload(member)
    mastery = mastery_list_for_member(member)[:5]
    open_tests = MockAssignment.objects.filter(
        student=member, test__status=MockTest.STATUS_PUBLISHED
    ).exclude(test__attempts__student=member, test__attempts__submitted_at__isnull=False)
    # Simpler: published assigned without submitted attempt
    assigned = MockAssignment.objects.filter(
        student=member, test__status=MockTest.STATUS_PUBLISHED
    ).select_related("test")
    pending_tests = []
    for a in assigned[:10]:
        if not MockAttempt.objects.filter(
            test=a.test, student=member, submitted_at__isnull=False
        ).exists():
            pending_tests.append(a.test.title)

    open_micros = (
        MicroQuiz.objects.filter(
            bucket__access_grants__member=member,
            status=MicroQuiz.STATUS_READY,
        )
        .exclude(attempts__student=member)
        .distinct()[:5]
    )

    lines = [
        f"Current streak: {streak['current_streak']} day(s) "
        f"(best {streak['longest_streak']}).",
    ]
    if mastery:
        lines.append(
            "Subject progress: "
            + ", ".join(f"{m['bucket_name']} {m['score']}%" for m in mastery)
        )
    if pending_tests:
        lines.append("Open tests: " + ", ".join(pending_tests[:5]))
    if open_micros:
        lines.append(
            "Quick checks waiting: "
            + ", ".join(q.title for q in open_micros)
        )
        tip = open_micros[0]
        lines.append(f"Tip: try asking about topics in {tip.bucket.name}.")

    if (
        streak["current_streak"] == 0
        and not pending_tests
        and not list(open_micros)
        and not mastery
    ):
        return None

    text = (
        f"Hi {member.user.get_full_name() or member.user.username},\n\n"
        + "\n".join(lines)
        + f"\n\nKeep going: {_frontend('/app')}\n"
    )
    html = (
        f"<p>Hi {member.user.get_full_name() or member.user.username},</p>"
        + "".join(f"<p>{l}</p>" for l in lines)
        + f"<p><a href=\"{_frontend('/app')}\">Open ClassKit</a></p>"
    )
    return {"text": text, "html": html}
