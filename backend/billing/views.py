"""Billing + usage APIs: plans, subscription, Razorpay checkout, metering dashboard."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.models import School
from ingestion.permissions import IsManagerOrAdmin, IsSchoolAdmin, IsSchoolMember

from .models import Payment, UsageEvent
from .plans import all_plans, get_plan
from .services import razorpay
from .services.subscription import activate_paid_plan, subscription_payload
from .services.usage import usage_summary

logger = logging.getLogger(__name__)


class CheckoutSerializer(serializers.Serializer):
    plan_code = serializers.CharField()
    months = serializers.IntegerField(min_value=1, max_value=12, default=1)


class VerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


def _payment_payload(p: Payment) -> dict:
    return {
        "id": p.id,
        "plan_code": p.plan_code,
        "months": p.months,
        "amount_paise": p.amount_paise,
        "currency": p.currency,
        "status": p.status,
        "order_id": p.provider_order_id,
        "payment_id": p.provider_payment_id,
        "created_at": p.created_at,
        "paid_at": p.paid_at,
    }


class PlanListView(APIView):
    """GET /api/billing/plans/ — public plan catalog (landing page + app)."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "plans": [p.as_dict() for p in all_plans()],
                "online_payments": razorpay.is_configured(),
            }
        )


class SubscriptionView(APIView):
    """GET /api/billing/subscription/ — current plan, limits, and seat usage."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        data = subscription_payload(request.member.school)
        data["online_payments"] = razorpay.is_configured()
        return Response(data)


class CheckoutView(APIView):
    """
    POST /api/billing/checkout/ {plan_code, months} → Razorpay order.

    Client opens Razorpay Checkout with {key_id, order_id, amount} and then
    calls /api/billing/verify/ with the handler's three fields.
    """

    permission_classes = [IsSchoolAdmin]

    @extend_schema(request=CheckoutSerializer)
    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = get_plan(ser.validated_data["plan_code"])
        if plan is None or not plan.is_paid:
            return Response({"detail": "Choose a paid plan."}, status=400)
        months = ser.validated_data["months"]
        amount = plan.price_paise_monthly * months
        school = request.member.school
        receipt = f"ck-{school.id}-{secrets.token_hex(6)}"
        try:
            order = razorpay.create_order(
                amount_paise=amount,
                receipt=receipt,
                notes={"school_id": str(school.id), "plan": plan.code, "months": str(months)},
            )
        except razorpay.BillingNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except razorpay.BillingProviderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        payment = Payment.objects.create(
            school=school,
            created_by=request.member,
            plan_code=plan.code,
            months=months,
            amount_paise=amount,
            provider_order_id=order["id"],
            raw={"order": order},
        )
        return Response(
            {
                "payment": _payment_payload(payment),
                "checkout": {
                    "key_id": razorpay.public_key_id(),
                    "order_id": order["id"],
                    "amount": amount,
                    "currency": "INR",
                    "name": "ClassKit",
                    "description": f"{plan.name} plan · {months} month(s)",
                    "prefill": {
                        "email": request.user.email or "",
                        "contact": school.contact_phone or "",
                    },
                },
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyPaymentView(APIView):
    """POST /api/billing/verify/ — confirm Checkout success and activate the plan."""

    permission_classes = [IsSchoolAdmin]

    @extend_schema(request=VerifySerializer)
    def post(self, request):
        ser = VerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        payment = Payment.objects.filter(
            provider_order_id=vd["razorpay_order_id"], school=request.member.school
        ).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=404)
        if not razorpay.verify_payment_signature(
            order_id=vd["razorpay_order_id"],
            payment_id=vd["razorpay_payment_id"],
            signature=vd["razorpay_signature"],
        ):
            payment.status = Payment.STATUS_FAILED
            payment.save(update_fields=["status"])
            return Response({"detail": "Payment could not be verified."}, status=400)

        payment.provider_payment_id = vd["razorpay_payment_id"]
        payment.raw = {**(payment.raw or {}), "verify": dict(vd)}
        activate_paid_plan(payment)
        payment.refresh_from_db()
        return Response(
            {
                "payment": _payment_payload(payment),
                "subscription": subscription_payload(payment.school),
            }
        )


class RazorpayWebhookView(APIView):
    """POST /api/billing/webhook/razorpay/ — signed server-to-server events."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        body = request.body
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not razorpay.verify_webhook_signature(body, signature):
            return Response({"detail": "Invalid signature."}, status=400)
        try:
            event = json.loads(body.decode() or "{}")
        except ValueError:
            return Response({"detail": "Bad payload."}, status=400)

        name = event.get("event", "")
        entity = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
        order_id = entity.get("order_id") or (
            ((event.get("payload") or {}).get("order") or {}).get("entity") or {}
        ).get("id")
        payment = Payment.objects.filter(provider_order_id=order_id).first() if order_id else None
        if payment is None:
            return Response({"ok": True, "ignored": True})

        if name in ("payment.captured", "order.paid"):
            payment.provider_payment_id = entity.get("id") or payment.provider_payment_id
            payment.raw = {**(payment.raw or {}), "webhook": name}
            activate_paid_plan(payment)
        elif name == "payment.failed" and payment.status == Payment.STATUS_CREATED:
            payment.status = Payment.STATUS_FAILED
            payment.save(update_fields=["status"])
        return Response({"ok": True})


class PaymentListView(APIView):
    """GET /api/billing/payments/ — school payment history (admin/manager)."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request):
        rows = Payment.objects.filter(school=request.member.school)[:100]
        return Response([_payment_payload(p) for p in rows])


def _days(request, default: int = 30) -> int:
    try:
        return max(1, min(365, int(request.query_params.get("days", default))))
    except (TypeError, ValueError):
        return default


class UsageSummaryView(APIView):
    """GET /api/billing/usage/?days=30 — AI/OCR usage + estimated cost for this school."""

    permission_classes = [IsManagerOrAdmin]

    def get(self, request):
        return Response(usage_summary(request.member.school, days=_days(request)))


class PlatformUsageView(APIView):
    """GET /api/billing/usage/schools/ — per-school usage for the platform operator."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        days = _days(request)
        since = timezone.now() - timedelta(days=days)
        rows = (
            UsageEvent.objects.filter(created_at__gte=since)
            .values("school_id")
            .annotate(tokens=Sum("total_tokens"), cost=Sum("cost_usd"), events=Count("id"))
            .order_by("-cost")
        )
        names = dict(School.objects.values_list("id", "name"))
        return Response(
            {
                "days": days,
                "schools": [
                    {
                        "school_id": r["school_id"],
                        "school_name": names.get(r["school_id"], "(unscoped)"),
                        "events": r["events"],
                        "tokens": int(r["tokens"] or 0),
                        "cost_usd": float(r["cost"] or 0),
                    }
                    for r in rows
                ],
            }
        )
