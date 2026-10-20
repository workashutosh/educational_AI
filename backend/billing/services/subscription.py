"""Apply / expire plans and keep School limits in sync with the active plan."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ingestion.models import School, SubjectBucket

from ..models import Payment, Subscription
from ..plans import Plan, free_plan, get_plan

logger = logging.getLogger(__name__)

DAYS_PER_MONTH = 30


def plan_for_school_id(school_id: int) -> Plan:
    sub = Subscription.objects.filter(school_id=school_id).first()
    if sub and sub.is_current:
        plan = get_plan(sub.plan_code)
        if plan:
            return plan
    return free_plan()


def subscription_payload(school: School) -> dict:
    sub = Subscription.objects.filter(school=school).first()
    plan = plan_for_school_id(school.id)
    return {
        "plan": plan.as_dict(),
        "status": sub.status if sub else Subscription.STATUS_ACTIVE,
        "current_period_start": sub.current_period_start if sub else None,
        "current_period_end": sub.current_period_end if sub else None,
        "limits": {
            "max_buckets": school.max_buckets,
            "bucket_quota_bytes": school.bucket_quota_bytes,
            "max_users": school.max_users,
            "max_managers": school.max_managers,
        },
        "usage": {
            "buckets": SubjectBucket.objects.filter(school=school, is_archived=False).count(),
            "members": school.active_member_count(),
        },
    }


def apply_plan_limits(school: School, plan: Plan) -> None:
    old_quota = int(school.bucket_quota_bytes)
    school.max_buckets = plan.max_buckets
    school.bucket_quota_bytes = plan.bucket_quota_bytes
    school.max_users = plan.max_users
    school.max_managers = plan.max_managers
    school.save(
        update_fields=["max_buckets", "bucket_quota_bytes", "max_users", "max_managers"]
    )
    # Buckets that inherited the old school default follow the new one.
    SubjectBucket.objects.filter(school=school, quota_bytes=old_quota).update(
        quota_bytes=plan.bucket_quota_bytes
    )


@transaction.atomic
def activate_paid_plan(payment: Payment) -> Subscription:
    """Mark a payment paid (idempotent) and extend the school's subscription."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    sub, _ = Subscription.objects.select_for_update().get_or_create(school=payment.school)
    if payment.status == Payment.STATUS_PAID:
        return sub

    plan = get_plan(payment.plan_code)
    if plan is None:
        raise ValueError(f"Unknown plan {payment.plan_code}")

    now = timezone.now()
    extend_from = now
    if (
        sub.plan_code == plan.code
        and sub.is_current
        and sub.current_period_end
        and sub.current_period_end > now
    ):
        extend_from = sub.current_period_end
    else:
        sub.current_period_start = now

    sub.plan_code = plan.code
    sub.status = Subscription.STATUS_ACTIVE
    sub.current_period_end = extend_from + timedelta(days=DAYS_PER_MONTH * payment.months)
    sub.save()

    payment.status = Payment.STATUS_PAID
    payment.paid_at = now
    payment.save(update_fields=["status", "paid_at", "provider_payment_id", "raw"])

    apply_plan_limits(payment.school, plan)
    return sub


def expire_due_subscriptions() -> int:
    """Downgrade schools whose paid period ended. Returns count downgraded."""
    now = timezone.now()
    due = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE, current_period_end__lte=now
    ).select_related("school")
    count = 0
    for sub in due:
        sub.status = Subscription.STATUS_EXPIRED
        sub.save(update_fields=["status", "updated_at"])
        apply_plan_limits(sub.school, free_plan())
        count += 1
        logger.info("Subscription expired for school=%s", sub.school_id)
    return count
