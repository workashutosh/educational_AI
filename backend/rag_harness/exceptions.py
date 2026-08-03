"""Harness-specific errors surfaced as clean API responses."""


class HarnessError(Exception):
    """Base harness error."""


class HarnessLLMError(HarnessError):
    """PageIndex / LiteLLM / answer-model failure (map to HTTP 502)."""


class HarnessRetrievalError(HarnessError):
    """Retrieval failed after permission checks passed."""
