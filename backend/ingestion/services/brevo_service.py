"""Brevo transactional email helper (OTP and similar)."""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_BREVO_SMTP_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoError(RuntimeError):
    pass


def send_otp_email(*, to_email: str, otp: str, organization_name: str = "") -> None:
    """Send a 6-digit onboarding OTP via Brevo transactional email API."""
    api_key = getattr(settings, "BREVO_API_KEY", "") or ""
    sender_email = getattr(settings, "BREVO_SENDER_EMAIL", "") or ""
    sender_name = getattr(settings, "BREVO_SENDER_NAME", "Education AI") or "Education AI"
    if not api_key:
        raise BrevoError("BREVO_API_KEY is not configured")
    if not sender_email:
        raise BrevoError("BREVO_SENDER_EMAIL is not configured")

    org = organization_name.strip() or "your organization"
    subject = f"Your Education AI verification code: {otp}"
    text = (
        f"Your verification code for onboarding {org} is {otp}.\n\n"
        f"This code expires in {getattr(settings, 'OTP_TTL_SECONDS', 600) // 60} minutes.\n"
        "If you did not request this, ignore this email."
    )
    html = (
        "<html><body>"
        f"<p>Your verification code for onboarding <strong>{org}</strong> is:</p>"
        f"<p style=\"font-size:24px;letter-spacing:4px;\"><strong>{otp}</strong></p>"
        f"<p>This code expires in {getattr(settings, 'OTP_TTL_SECONDS', 600) // 60} minutes.</p>"
        "<p>If you did not request this, ignore this email.</p>"
        "</body></html>"
    )
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(_BREVO_SMTP_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.exception("Brevo request failed")
        raise BrevoError(f"Brevo request failed: {exc}") from exc

    if resp.status_code >= 400:
        logger.error("Brevo send failed status=%s body=%s", resp.status_code, resp.text[:500])
        raise BrevoError(f"Brevo send failed ({resp.status_code})")
    # Do not log OTP or full payload
    logger.info("Brevo OTP email accepted for %s", to_email)
