"""
Plan catalog. Code-defined (not a table) so limits ship with releases;
prices can be overridden per environment via BILLING_PRICE_<CODE>_PAISE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.conf import settings

from ingestion.models import FREE_TRIAL_MAX_USERS, GB

PLAN_FREE = "free"
PLAN_STANDARD = "standard"
PLAN_PRO = "pro"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_paise_monthly: int
    max_buckets: int
    bucket_quota_bytes: int
    max_users: int  # 0 = unlimited
    max_managers: int  # 0 = unlimited
    monthly_ai_tokens: int  # 0 = unlimited
    features: list[str] = field(default_factory=list)

    @property
    def is_paid(self) -> bool:
        return self.price_paise_monthly > 0

    def as_dict(self) -> dict:
        data = asdict(self)
        data["is_paid"] = self.is_paid
        data["price_inr_monthly"] = self.price_paise_monthly / 100
        return data


def _price(code: str, default_paise: int) -> int:
    return int(getattr(settings, f"BILLING_PRICE_{code.upper()}_PAISE", default_paise))


def all_plans() -> list[Plan]:
    return [
        Plan(
            code=PLAN_FREE,
            name="Free trial",
            price_paise_monthly=0,
            max_buckets=5,
            bucket_quota_bytes=GB,
            max_users=FREE_TRIAL_MAX_USERS,
            max_managers=1,
            monthly_ai_tokens=2_000_000,
            features=["AI chat", "Mock tests", "Presentations", "Question bank"],
        ),
        Plan(
            code=PLAN_STANDARD,
            name="Standard",
            price_paise_monthly=_price(PLAN_STANDARD, 299_900),
            max_buckets=15,
            bucket_quota_bytes=2 * GB,
            max_users=150,
            max_managers=5,
            monthly_ai_tokens=20_000_000,
            features=[
                "Everything in Free",
                "Question papers + PDF export",
                "Homework with AI grading",
                "Lecture transcription",
                "Parent portal",
            ],
        ),
        Plan(
            code=PLAN_PRO,
            name="Pro",
            price_paise_monthly=_price(PLAN_PRO, 799_900),
            max_buckets=50,
            bucket_quota_bytes=5 * GB,
            max_users=1000,
            max_managers=20,
            monthly_ai_tokens=100_000_000,
            features=["Everything in Standard", "Priority support", "Higher AI limits"],
        ),
    ]


def get_plan(code: str) -> Plan | None:
    for plan in all_plans():
        if plan.code == code:
            return plan
    return None


def free_plan() -> Plan:
    return get_plan(PLAN_FREE)  # type: ignore[return-value]
