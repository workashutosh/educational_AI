"""
SM-2 spaced repetition (the SuperMemo-2 / early Anki scheduler).

Grades: 0-5. Apps usually show four buttons — Again=1, Hard=3, Good=4, Easy=5.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ingestion.api_utils import accessible_buckets

from ..models import CardState, Flashcard, FlashcardDeck, ReviewLog

MIN_EASE = 1.3
RELEARN_MINUTES = 10
NEW_CARDS_PER_DAY = 20
GRADE_BUTTONS = {"again": 1, "hard": 3, "good": 4, "easy": 5}


@dataclass
class Schedule:
    ease: float
    interval_days: float
    repetitions: int
    lapses: int
    due_in: timedelta


def next_schedule(*, ease: float, interval_days: float, repetitions: int, lapses: int, grade: int) -> Schedule:
    grade = max(0, min(5, int(grade)))
    new_ease = max(MIN_EASE, ease + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    if grade < 3:
        return Schedule(
            ease=new_ease,
            interval_days=0,
            repetitions=0,
            lapses=lapses + 1,
            due_in=timedelta(minutes=RELEARN_MINUTES),
        )
    if repetitions == 0:
        interval = 1.0
    elif repetitions == 1:
        interval = 6.0
    else:
        interval = max(1.0, interval_days) * new_ease
    if grade == 3:
        interval = max(1.0, interval * 0.8)
    elif grade == 5:
        interval *= 1.3
    interval = round(interval, 2)
    return Schedule(
        ease=round(new_ease, 3),
        interval_days=interval,
        repetitions=repetitions + 1,
        lapses=lapses,
        due_in=timedelta(days=interval),
    )


def visible_decks(member):
    return FlashcardDeck.objects.filter(
        Q(owner=member) | Q(visibility=FlashcardDeck.VISIBILITY_BUCKET, bucket__in=accessible_buckets(member)),
        school=member.school,
        bucket__is_archived=False,
    ).distinct()


def due_cards(member, *, bucket_id=None, deck_id=None, limit: int = 30) -> dict:
    """Review queue: due cards first, then today's allowance of new cards."""
    now = timezone.now()
    decks = visible_decks(member)
    if bucket_id:
        decks = decks.filter(bucket_id=bucket_id)
    if deck_id:
        decks = decks.filter(pk=deck_id)
    cards = Flashcard.objects.filter(deck__in=decks)

    due_states = (
        CardState.objects.filter(member=member, card__in=cards, due_at__lte=now)
        .select_related("card", "card__deck")
        .order_by("due_at")[:limit]
    )
    due = [s.card for s in due_states]

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new_seen_today = CardState.objects.filter(
        member=member, card__in=cards, last_reviewed_at__gte=start_of_day, repetitions__lte=1, lapses=0
    ).count()
    allowance = max(0, min(limit - len(due), NEW_CARDS_PER_DAY - new_seen_today))
    new_cards = list(
        cards.exclude(states__member=member).select_related("deck").order_by("deck_id", "order", "id")[:allowance]
    )
    total_due = CardState.objects.filter(member=member, card__in=cards, due_at__lte=now).count()
    total_new = cards.exclude(states__member=member).count()
    return {
        "cards": [(c, "review") for c in due] + [(c, "new") for c in new_cards],
        "due_count": total_due,
        "new_count": total_new,
    }


@transaction.atomic
def review_card(member, card: Flashcard, grade: int) -> CardState:
    state, _ = CardState.objects.select_for_update().get_or_create(card=card, member=member)
    sched = next_schedule(
        ease=state.ease,
        interval_days=state.interval_days,
        repetitions=state.repetitions,
        lapses=state.lapses,
        grade=grade,
    )
    now = timezone.now()
    state.ease = sched.ease
    state.interval_days = sched.interval_days
    state.repetitions = sched.repetitions
    state.lapses = sched.lapses
    state.last_grade = grade
    state.last_reviewed_at = now
    state.due_at = now + sched.due_in
    state.save()
    ReviewLog.objects.create(card=card, member=member, grade=grade, interval_days=sched.interval_days)
    return state


def deck_progress(member, deck: FlashcardDeck) -> dict:
    now = timezone.now()
    total = deck.cards.count()
    states = CardState.objects.filter(member=member, card__deck=deck)
    learned = states.filter(repetitions__gte=2).count()
    return {
        "total": total,
        "seen": states.count(),
        "learned": learned,
        "to_study": states.filter(due_at__lte=now).count() + max(0, total - states.count()),
    }
