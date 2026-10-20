from django.contrib import admin

from .models import Payment, Subscription, UsageEvent


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("school", "plan_code", "status", "current_period_end")
    list_filter = ("plan_code", "status")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_order_id", "school", "plan_code", "amount_paise", "status", "created_at")
    list_filter = ("status", "plan_code")


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "kind", "feature", "model", "total_tokens", "units", "cost_usd")
    list_filter = ("kind", "feature", "provider")
