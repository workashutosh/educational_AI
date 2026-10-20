"""Weekly parent digest email."""
from __future__ import annotations

import html
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def _digest(profile) -> dict | None:
    from .services import child_overview, children_of

    sections = []
    for child in children_of(profile):
        o = child_overview(child)
        att = o["attendance"]
        lines = [f"{o['name']}"]
        if att["percent"] is not None:
            lines.append(f"Attendance (90 days): {att['percent']}% ({att['attended']}/{att['total']})")
        lines.append(f"Study streak: {o['streak']['current_streak']} day(s)")
        released = [r for r in o["test_results"] if r["released"]][:3]
        for r in released:
            lines.append(f"Test “{r['title']}”: {r['score']}/{r['max_score']} ({r['percent']}%)")
        if o["pending_tests"]:
            lines.append(f"Tests not started yet: {len(o['pending_tests'])}")
        pending_hw = [h for h in o["homework"] if h["status"] == "pending"]
        if pending_hw:
            lines.append(f"Homework due: {len(pending_hw)}")
        sections.append(lines)
    if not sections:
        return None
    base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
    text = "\n\n".join("\n".join(s) for s in sections) + f"\n\nOpen ClassKit: {base}/parent\n"
    body = "".join(
        f"<p><b>{html.escape(s[0])}</b><br/>" + "<br/>".join(html.escape(x) for x in s[1:]) + "</p>"
        for s in sections
    )
    return {"text": text, "html": body + f'<p><a href="{base}/parent">Open ClassKit</a></p>'}


def send_parent_weekly_digests() -> dict:
    from ingestion.services.brevo_service import BrevoError, send_transactional_email

    from .models import ParentProfile

    sent = skipped = 0
    for profile in ParentProfile.objects.filter(is_active=True, weekly_email=True).select_related("user"):
        email = (profile.user.email or "").strip()
        body = _digest(profile) if email else None
        if not body:
            skipped += 1
            continue
        try:
            send_transactional_email(
                to_email=email,
                to_name=profile.user.get_full_name() or profile.user.username,
                subject="ClassKit — your child's week",
                text=body["text"],
                html=body["html"],
            )
            sent += 1
        except BrevoError as exc:
            logger.warning("Parent digest failed profile=%s: %s", profile.id, exc)
            skipped += 1
    return {"sent": sent, "skipped": skipped}


@shared_task(name="school_ops.send_parent_weekly_digests")
def send_parent_weekly_digests_task() -> dict:
    return send_parent_weekly_digests()
