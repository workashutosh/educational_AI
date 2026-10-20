from __future__ import annotations

from django.db import models
from django.utils import timezone

from ingestion.models import School, SchoolMembership


class Subscription(models.Model):
    """Current plan for a school. Absent row = free plan."""

    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="subscription")
    plan_code = models.CharField(max_length=32, default="free")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.school} → {self.plan_code} [{self.status}]"

    @property
    def is_current(self) -> bool:
        if self.status != self.STATUS_ACTIVE:
            return False
        return self.current_period_end is None or self.current_period_end > timezone.now()


class Payment(models.Model):
    STATUS_CREATED = "created"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="payments")
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    plan_code = models.CharField(max_length=32)
    months = models.PositiveSmallIntegerField(default=1)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=8, default="INR")
    provider = models.CharField(max_length=32, default="razorpay")
    provider_order_id = models.CharField(max_length=64, unique=True)
    provider_payment_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CREATED)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider_order_id} {self.plan_code} [{self.status}]"


class UsageEvent(models.Model):
    """One metered call: LLM tokens, OCR pages, or transcription seconds."""

    KIND_LLM = "llm"
    KIND_OCR = "ocr"
    KIND_TRANSCRIPTION = "transcription"
    KIND_CHOICES = [
        (KIND_LLM, "LLM tokens"),
        (KIND_OCR, "OCR pages"),
        (KIND_TRANSCRIPTION, "Transcription seconds"),
    ]

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, null=True, blank=True, related_name="usage_events"
    )
    member = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_LLM)
    feature = models.CharField(max_length=64, blank=True, default="")
    provider = models.CharField(max_length=32, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    units = models.FloatField(default=0.0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school", "created_at"]),
            models.Index(fields=["school", "kind", "created_at"]),
        ]
