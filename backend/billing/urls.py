from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlanListView.as_view(), name="billing-plans"),
    path("subscription/", views.SubscriptionView.as_view(), name="billing-subscription"),
    path("checkout/", views.CheckoutView.as_view(), name="billing-checkout"),
    path("verify/", views.VerifyPaymentView.as_view(), name="billing-verify"),
    path("payments/", views.PaymentListView.as_view(), name="billing-payments"),
    path("webhook/razorpay/", views.RazorpayWebhookView.as_view(), name="billing-webhook"),
    path("usage/", views.UsageSummaryView.as_view(), name="billing-usage"),
    path("usage/schools/", views.PlatformUsageView.as_view(), name="billing-usage-schools"),
]
