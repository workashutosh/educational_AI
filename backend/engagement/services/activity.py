"""Record engagement activity and update streaks."""
from __future__ import annotations

import logging

from django.db import transaction

from engagement.models import EngagementActivity, StudentStreak
from engagement.services.timeutil import local_today, week_start_for

logger = logging.getLogger(__name__)


@transaction.atomic
def record_activity(
    *,
    member,
    kind: str,
    bucket=None,
    ref_id: str = "",
    bump_streak: bool = True,
) -> EngagementActivity:
    school = member.school
    activity = EngagementActivity.objects.create(
        school=school,
        member=member,
        kind=kind,
        bucket=bucket,
        ref_id=str(ref_id or "")[:64],
    )
    if bump_streak and member.role == member.ROLE_STUDENT:
        _bump_streak(member)
    return activity


def _bump_streak(member) -> StudentStreak:
    today = local_today()
    streak, _ = StudentStreak.objects.select_for_update().get_or_create(member=member)
    ws = week_start_for(today)
    if streak.week_start != ws:
        streak.week_start = ws
        streak.weekly_count = 0

    if streak.last_activity_date == today:
        # Already counted today — still allow weekly? only once per day
        streak.save(update_fields=["week_start", "weekly_count", "updated_at"])
        return streak

    if streak.last_activity_date:
        delta = (today - streak.last_activity_date).days
        if delta == 1:
            streak.current_streak = int(streak.current_streak or 0) + 1
        elif delta > 1:
            streak.current_streak = 1
        # delta == 0 handled above
    else:
        streak.current_streak = 1

    streak.longest_streak = max(int(streak.longest_streak or 0), streak.current_streak)
    streak.last_activity_date = today
    streak.weekly_count = int(streak.weekly_count or 0) + 1
    streak.save()
    return streak


def get_streak_payload(member) -> dict:
    try:
        s = StudentStreak.objects.get(member=member)
    except StudentStreak.DoesNotExist:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "weekly_count": 0,
            "last_activity_date": None,
        }
    today = local_today()
    current = s.current_streak
    # If missed yesterday+, show 0 until they act again (don't mutate here)
    if s.last_activity_date:
        gap = (today - s.last_activity_date).days
        if gap > 1:
            current = 0
    return {
        "current_streak": current,
        "longest_streak": s.longest_streak,
        "weekly_count": s.weekly_count if s.week_start == week_start_for(today) else 0,
        "last_activity_date": s.last_activity_date.isoformat()
        if s.last_activity_date
        else None,
    }
