"""
User-safe errors for upstream LLM / embedding providers.

Never put provider JSON, org IDs, quotas, or stack traces in API `detail`.
Log the raw payload server-side only.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Raised when Groq (or similar) fails; `public_message` is safe for clients."""

    def __init__(
        self,
        status_code: int,
        public_message: str | None = None,
        *,
        raw: str = "",
        provider: str = "AI",
    ):
        self.status_code = int(status_code)
        self.raw = (raw or "")[:2000]
        self.provider = provider
        self.public_message = public_message or public_llm_message(self.status_code)
        super().__init__(self.public_message)


def public_llm_message(status_code: int) -> str:
    if status_code in (413, 429):
        return (
            "The AI service is busy right now. Please wait a few seconds and try again."
        )
    if status_code in (401, 403):
        return "The AI service is temporarily unavailable. Please try again later."
    if status_code >= 500 or status_code == 0:
        return "The AI service is temporarily unavailable. Please try again later."
    return "Something went wrong generating a response. Please try again."


def raise_for_llm_response(
    response,
    *,
    provider: str = "Groq",
) -> None:
    """If response is not OK, log body and raise LLMProviderError with safe copy."""
    status_code = getattr(response, "status_code", 0) or 0
    if status_code == 200:
        return
    raw = ""
    try:
        raw = response.text or ""
    except Exception:
        raw = ""
    logger.warning(
        "%s API error status=%s body=%s",
        provider,
        status_code,
        raw[:800],
    )
    # Groq returns 413 for oversized TPM requests (same UX as rate limit).
    if status_code == 413 or (
        status_code == 429 and "request too large" in (raw or "").lower()
    ):
        status_code = 413
    raise LLMProviderError(status_code, raw=raw, provider=provider)


def http_status_for_llm_error(exc: LLMProviderError) -> int:
    """Map provider failure to an HTTP status for our API (never leak provider body)."""
    if exc.status_code in (413, 429):
        return 429
    if exc.status_code >= 500 or exc.status_code == 0:
        return 502
    return 502
