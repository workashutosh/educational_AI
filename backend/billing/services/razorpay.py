"""
Razorpay Orders API (no SDK): create order → Checkout on the client →
verify signature server-side → activate plan. Webhook is the backstop when
the browser/app closes before /verify is called.

Docs: https://razorpay.com/docs/payments/server-integration/
"""
from __future__ import annotations

import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class BillingNotConfigured(RuntimeError):
    pass


class BillingProviderError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(
        getattr(settings, "RAZORPAY_KEY_ID", "") and getattr(settings, "RAZORPAY_KEY_SECRET", "")
    )


def public_key_id() -> str:
    return getattr(settings, "RAZORPAY_KEY_ID", "")


def create_order(*, amount_paise: int, receipt: str, notes: dict) -> dict:
    if not is_configured():
        raise BillingNotConfigured("Online payments are not set up yet.")
    try:
        resp = requests.post(
            _ORDERS_URL,
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={
                "amount": int(amount_paise),
                "currency": "INR",
                "receipt": receipt[:40],
                "notes": notes,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.warning("Razorpay order request failed: %s", exc)
        raise BillingProviderError("Payment service unreachable. Please try again.") from exc
    if resp.status_code not in (200, 201):
        logger.warning("Razorpay order error %s: %s", resp.status_code, resp.text[:500])
        raise BillingProviderError("Could not start the payment. Please try again.")
    return resp.json()


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_payment_signature(*, order_id: str, payment_id: str, signature: str) -> bool:
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not secret or not signature:
        return False
    expected = _hmac_hex(secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    return hmac.compare_digest(_hmac_hex(secret, body), signature)
