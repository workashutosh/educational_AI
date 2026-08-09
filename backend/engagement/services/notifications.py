"""In-app notifications with 24h dedupe."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from engagement.models import Notification, NotificationPreference
from engagement.services.constants import DEDUPE_HOURS

logger = logging.getLogger(__name__)


def get_or_create_prefs(member) -> NotificationPreference:
    prefs, _ = NotificationPreference.objects.get_or_create(member=member)
    return prefs


@transaction.atomic
def create_notification(
    *,
    recipient,
    kind: str,
    title: str,
    body: str = "",
    link_path: str = "",
    payload: dict | None = None,
    dedupe_key: str = "",
) -> Notification | None:
    """Create notification; return None if deduped within window."""
    school = recipient.school
    key = (dedupe_key or "")[:128]
    if key:
        since = timezone.now() - timedelta(hours=DEDUPE_HOURS)
        exists = Notification.objects.filter(
            recipient=recipient,
            kind=kind,
            dedupe_key=key,
            created_at__gte=since,
        ).exists()
        if exists:
            return None

    return Notification.objects.create(
        school=school,
        recipient=recipient,
        kind=kind,
        title=title[:255],
        body=body or "",
        link_path=(link_path or "")[:512],
        payload=payload or {},
        dedupe_key=key,
    )


def notify_many(recipients, **kwargs) -> int:
    created = 0
    for r in recipients:
        if create_notification(recipient=r, **kwargs):
            created += 1
    return created


def notification_payload(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link_path": n.link_path,
        "payload": n.payload or {},
        "is_read": n.is_read,
        "created_at": n.created_at,
    }
