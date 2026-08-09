"""Timezone helpers for school-local calendar days."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def school_tz() -> ZoneInfo:
    name = getattr(settings, "SCHOOL_DEFAULT_TZ", "Asia/Kolkata") or "Asia/Kolkata"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def local_today() -> date:
    return timezone.now().astimezone(school_tz()).date()


def local_now() -> datetime:
    return timezone.now().astimezone(school_tz())


def week_start_for(d: date) -> date:
    """Monday as week start."""
    return d.fromordinal(d.toordinal() - d.weekday())
