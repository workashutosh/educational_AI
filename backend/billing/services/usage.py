"""
Metering for paid upstream calls (LLM tokens, OCR pages, transcription).

A request/task opens a `usage_scope`; llm_provider and the OCR/transcription
paths call `record_*` without knowing who triggered them. Recording must
never break the feature being metered, so every write is best-effort.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

logger = logging.getLogger(__name__)

_scope: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usage_scope", default=None)


class AIQuotaExceeded(RuntimeError):
    """School used its monthly AI token allowance."""

    public_message = (
        "Your school has used this month's AI allowance. "
        "Ask your admin to upgrade the plan in Settings → Billing."
    )

    def __init__(self):
        super().__init__(self.public_message)


@contextmanager
def usage_scope(*, school_id: int | None = None, member_id: int | None = None, feature: str = ""):
    token = _scope.set({"school_id": school_id, "member_id": member_id, "feature": feature})
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope() -> dict | None:
    return _scope.get()


def bind_member(member) -> None:
    """Attach the authenticated member to the open request scope (if any)."""
    scope = _scope.get()
    if scope is None or member is None:
        return
    if scope.get("member_id") is None:
        scope["member_id"] = member.id
        scope["school_id"] = member.school_id


def set_feature(feature: str) -> None:
    scope = _scope.get()
    if scope is not None and feature:
        scope["feature"] = feature


def _pricing() -> dict:
    return getattr(settings, "LLM_PRICING_USD_PER_MTOK", {}) or {}


def estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    table = _pricing()
    price = table.get(model) or table.get("default") or [0, 0]
    try:
        p_in, p_out = float(price[0]), float(price[1])
    except (TypeError, ValueError, IndexError):
        p_in = p_out = 0.0
    cost = (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000
    return Decimal(str(round(cost, 6)))


def _create(**fields) -> None:
    from billing.models import UsageEvent

    scope = _scope.get() or {}
    fields.setdefault("feature", scope.get("feature") or "")
    try:
        UsageEvent.objects.create(
            school_id=scope.get("school_id"),
            member_id=scope.get("member_id"),
            **fields,
        )
    except Exception:
        logger.exception("Usage recording failed (ignored)")


def record_llm_usage(*, provider: str, model: str, usage: dict | None) -> None:
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    if not total:
        return
    _create(
        kind="llm",
        provider=provider,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost_usd=estimate_llm_cost(model, prompt, completion),
    )


def record_units(*, kind: str, units: float, provider: str = "", model: str = "") -> None:
    if not units:
        return
    rate_key = {"ocr": "OCR_COST_USD_PER_PAGE", "transcription": "TRANSCRIPTION_COST_USD_PER_MINUTE"}
    rate = float(getattr(settings, rate_key.get(kind, ""), 0) or 0) if kind in rate_key else 0.0
    per_unit = rate / 60 if kind == "transcription" else rate
    _create(
        kind=kind,
        provider=provider,
        model=model,
        units=float(units),
        cost_usd=Decimal(str(round(per_unit * float(units), 6))),
    )


def _month_start():
    now = timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tokens_used_this_month(school_id: int) -> int:
    from billing.models import UsageEvent

    total = UsageEvent.objects.filter(
        school_id=school_id, kind="llm", created_at__gte=_month_start()
    ).aggregate(t=Sum("total_tokens"))["t"]
    return int(total or 0)


def check_ai_quota() -> None:
    """Raise AIQuotaExceeded when the scoped school is over its plan allowance."""
    if not getattr(settings, "BILLING_ENFORCE_AI_QUOTA", True):
        return
    scope = _scope.get()
    if not scope or not scope.get("school_id"):
        return
    try:
        from billing.services.subscription import plan_for_school_id

        plan = plan_for_school_id(scope["school_id"])
        if not plan.monthly_ai_tokens:
            return
        used = tokens_used_this_month(scope["school_id"])
    except Exception:
        logger.exception("AI quota check failed (allowing call)")
        return
    if used >= plan.monthly_ai_tokens:
        raise AIQuotaExceeded()


def usage_summary(school, *, days: int = 30) -> dict:
    from billing.models import UsageEvent
    from billing.services.subscription import plan_for_school_id

    since = timezone.now() - timedelta(days=days)
    qs = UsageEvent.objects.filter(school=school, created_at__gte=since)

    def _rows(field: str) -> list[dict]:
        return [
            {
                field: row[field] or "other",
                "events": row["events"],
                "tokens": int(row["tokens"] or 0),
                "units": float(row["units"] or 0),
                "cost_usd": float(row["cost"] or 0),
            }
            for row in qs.values(field)
            .annotate(
                events=Count("id"),
                tokens=Sum("total_tokens"),
                units=Sum("units"),
                cost=Sum("cost_usd"),
            )
            .order_by("-cost", "-tokens")
        ]

    daily = [
        {
            "date": row["day"].isoformat() if row["day"] else None,
            "tokens": int(row["tokens"] or 0),
            "cost_usd": float(row["cost"] or 0),
        }
        for row in qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(tokens=Sum("total_tokens"), cost=Sum("cost_usd"))
        .order_by("day")
    ]

    top_members = []
    for row in (
        qs.filter(member__isnull=False)
        .values("member_id", "member__user__username", "member__role")
        .annotate(tokens=Sum("total_tokens"), cost=Sum("cost_usd"))
        .order_by("-tokens")[:10]
    ):
        top_members.append(
            {
                "member_id": row["member_id"],
                "username": row["member__user__username"],
                "role": row["member__role"],
                "tokens": int(row["tokens"] or 0),
                "cost_usd": float(row["cost"] or 0),
            }
        )

    totals = qs.aggregate(tokens=Sum("total_tokens"), cost=Sum("cost_usd"), events=Count("id"))
    ocr_pages = qs.filter(kind="ocr").aggregate(u=Sum("units"))["u"] or 0
    transcription_seconds = qs.filter(kind="transcription").aggregate(u=Sum("units"))["u"] or 0

    plan = plan_for_school_id(school.id)
    used_month = tokens_used_this_month(school.id)
    return {
        "days": days,
        "totals": {
            "events": totals["events"] or 0,
            "tokens": int(totals["tokens"] or 0),
            "cost_usd": float(totals["cost"] or 0),
            "ocr_pages": float(ocr_pages),
            "transcription_minutes": round(float(transcription_seconds) / 60, 1),
        },
        "by_feature": _rows("feature"),
        "by_kind": _rows("kind"),
        "by_model": _rows("model"),
        "daily": daily,
        "top_members": top_members,
        "quota": {
            "plan": plan.code,
            "monthly_ai_tokens": plan.monthly_ai_tokens,
            "used_this_month": used_month,
            "percent_used": (
                round(100 * used_month / plan.monthly_ai_tokens, 1)
                if plan.monthly_ai_tokens
                else 0.0
            ),
        },
        "cost_note": "Costs are estimates from configured per-token/page/minute rates.",
    }
