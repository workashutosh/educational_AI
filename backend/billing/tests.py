import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from ingestion.services.llm_errors import LLMProviderError
from ingestion.testing import client_for, make_bucket, make_member, make_school

from .models import Payment, Subscription, UsageEvent
from .services.subscription import expire_due_subscriptions, plan_for_school_id
from .services.usage import record_llm_usage, usage_scope

SECRET = "rzp_test_secret"


def _sig(message: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class PlanAndCheckoutTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.admin = make_member(self.school, "admin")
        self.teacher = make_member(self.school, "teacher")

    def test_plans_are_public(self):
        res = self.client.get("/api/billing/plans/")
        self.assertEqual(res.status_code, 200)
        codes = [p["code"] for p in res.json()["plans"]]
        self.assertEqual(codes, ["free", "standard", "pro"])

    def test_checkout_without_keys_is_503(self):
        res = client_for(self.admin).post("/api/billing/checkout/", {"plan_code": "standard"}, format="json")
        self.assertEqual(res.status_code, 503)

    def test_checkout_admin_only(self):
        res = client_for(self.teacher).post("/api/billing/checkout/", {"plan_code": "standard"}, format="json")
        self.assertEqual(res.status_code, 403)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET=SECRET)
    def test_checkout_verify_activates_plan(self):
        with mock.patch("billing.services.razorpay.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"id": "order_123", "amount": 599800}
            res = client_for(self.admin).post(
                "/api/billing/checkout/", {"plan_code": "standard", "months": 2}, format="json"
            )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["checkout"]["order_id"], "order_123")
        self.assertEqual(Payment.objects.get().amount_paise, 299_900 * 2)

        bad = client_for(self.admin).post(
            "/api/billing/verify/",
            {"razorpay_order_id": "order_123", "razorpay_payment_id": "pay_1", "razorpay_signature": "nope"},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)

        Payment.objects.update(status=Payment.STATUS_CREATED)
        good = client_for(self.admin).post(
            "/api/billing/verify/",
            {
                "razorpay_order_id": "order_123",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _sig(b"order_123|pay_1"),
            },
            format="json",
        )
        self.assertEqual(good.status_code, 200, good.content)
        self.school.refresh_from_db()
        self.assertEqual(self.school.max_buckets, 15)
        self.assertEqual(plan_for_school_id(self.school.id).code, "standard")
        sub = Subscription.objects.get(school=self.school)
        self.assertGreater(sub.current_period_end, timezone.now() + timedelta(days=59))

    @override_settings(RAZORPAY_WEBHOOK_SECRET="whsec")
    def test_webhook_signature_and_activation(self):
        Payment.objects.create(
            school=self.school, plan_code="pro", amount_paise=799_900, provider_order_id="order_w"
        )
        body = json.dumps(
            {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_w", "order_id": "order_w"}}}}
        ).encode()
        res = self.client.post(
            "/api/billing/webhook/razorpay/", body, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="bad",
        )
        self.assertEqual(res.status_code, 400)
        res = self.client.post(
            "/api/billing/webhook/razorpay/", body, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=_sig(body, "whsec"),
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Payment.objects.get().status, Payment.STATUS_PAID)
        self.assertEqual(plan_for_school_id(self.school.id).code, "pro")

    def test_expiry_downgrades_to_free(self):
        Subscription.objects.create(
            school=self.school, plan_code="pro", current_period_end=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(expire_due_subscriptions(), 1)
        self.school.refresh_from_db()
        self.assertEqual(self.school.max_buckets, 5)


class UsageTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.admin = make_member(self.school, "admin")

    def test_llm_calls_are_metered_to_scoped_school(self):
        from ingestion.services import llm_provider

        fake = mock.Mock(status_code=200)
        fake.json.return_value = {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        with override_settings(DEEPSEEK_API_KEY="k"), mock.patch.object(
            llm_provider.requests, "post", return_value=fake
        ), usage_scope(school_id=self.school.id, member_id=self.admin.id, feature="chat"):
            self.assertEqual(llm_provider.chat_completion([{"role": "user", "content": "x"}]), "hi")
        event = UsageEvent.objects.get()
        self.assertEqual((event.school_id, event.total_tokens, event.feature), (self.school.id, 150, "chat"))
        self.assertGreater(event.cost_usd, 0)

    def test_quota_blocks_calls(self):
        from ingestion.services import llm_provider

        with usage_scope(school_id=self.school.id):
            record_llm_usage(provider="x", model="m", usage={"total_tokens": 3_000_000})
        with override_settings(DEEPSEEK_API_KEY="k"), usage_scope(school_id=self.school.id):
            with self.assertRaises(LLMProviderError) as ctx:
                llm_provider.chat_completion([{"role": "user", "content": "x"}])
        self.assertIn("allowance", ctx.exception.public_message)

    def test_usage_dashboard(self):
        make_bucket(self.school)
        with usage_scope(school_id=self.school.id, member_id=self.admin.id, feature="ask"):
            record_llm_usage(provider="DeepSeek", model="deepseek-v4-flash", usage={"prompt_tokens": 10, "completion_tokens": 5})
        res = client_for(self.admin).get("/api/billing/usage/?days=7")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["totals"]["tokens"], 15)
        self.assertEqual(data["by_feature"][0]["feature"], "ask")
        self.assertEqual(data["quota"]["plan"], "free")
