"""Teacher time-saved impact events."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from engagement.models import TeacherImpactEvent
from engagement.services.constants import (
    MINUTES_MICRO_AUTO,
    MINUTES_MOCK_GENERATE,
    MINUTES_PPT,
)


_KIND_MINUTES = {
    TeacherImpactEvent.KIND_PPT: MINUTES_PPT,
    TeacherImpactEvent.KIND_MOCK_GENERATE: MINUTES_MOCK_GENERATE,
    TeacherImpactEvent.KIND_MICRO_AUTO: MINUTES_MICRO_AUTO,
}


def record_impact(*, member, kind: str, ref_id: str = "") -> TeacherImpactEvent:
    minutes = _KIND_MINUTES.get(kind, 0)
    return TeacherImpactEvent.objects.create(
        school=member.school,
        member=member,
        kind=kind,
        minutes_saved=minutes,
        ref_id=str(ref_id or "")[:64],
    )


def impact_summary(member, *, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = TeacherImpactEvent.objects.filter(member=member, created_at__gte=since)
    total = qs.aggregate(t=Sum("minutes_saved"))["t"] or 0
    by_kind = {}
    for kind, _label in TeacherImpactEvent.KIND_CHOICES:
        m = (
            qs.filter(kind=kind).aggregate(t=Sum("minutes_saved"))["t"] or 0
        )
        by_kind[kind] = {
            "minutes": m,
            "hours": round(m / 60, 1),
            "events": qs.filter(kind=kind).count(),
        }
    return {
        "days": days,
        "minutes_saved": total,
        "hours_saved": round(total / 60, 1),
        "by_kind": by_kind,
    }
