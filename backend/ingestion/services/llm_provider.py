"""
Shared OpenAI-compatible chat client.

Prefer DeepSeek (https://api-docs.deepseek.com/) when DEEPSEEK_API_KEY is set;
fall back to Groq. OCR / PaddleOCR paths must never import this module.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from django.conf import settings

from .llm_errors import LLMProviderError, raise_for_llm_response

logger = logging.getLogger(__name__)

_DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com"
_DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass(frozen=True)
class ChatLLMConfig:
    provider: str
    api_key: str
    model: str
    chat_url: str


def get_chat_llm() -> ChatLLMConfig:
    """Resolve the active chat LLM from settings (DeepSeek first, then Groq)."""
    deepseek_key = (getattr(settings, "DEEPSEEK_API_KEY", "") or "").strip()
    if deepseek_key:
        base = (
            getattr(settings, "DEEPSEEK_BASE_URL", "") or _DEFAULT_DEEPSEEK_BASE
        ).rstrip("/")
        model = (
            getattr(settings, "DEEPSEEK_MODEL", "") or _DEFAULT_DEEPSEEK_MODEL
        ).strip()
        return ChatLLMConfig(
            provider="DeepSeek",
            api_key=deepseek_key,
            model=model,
            chat_url=f"{base}/chat/completions",
        )

    groq_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if groq_key:
        model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
        return ChatLLMConfig(
            provider="Groq",
            api_key=groq_key,
            model=model,
            chat_url=_GROQ_CHAT_URL,
        )

    raise RuntimeError(
        "No chat LLM configured. Set DEEPSEEK_API_KEY (preferred) or GROQ_API_KEY."
    )


def _post_chat(
    cfg: ChatLLMConfig,
    payload: dict,
    timeout: int,
    *,
    attempts: int = 2,
) -> requests.Response:
    """
    POST to the provider, converting network failures (DNS, refused, timeout)
    into LLMProviderError so callers never leak a traceback to the client.
    """
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return requests.post(
                cfg.chat_url, headers=headers, json=payload, timeout=timeout
            )
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "%s request failed (attempt %d/%d): %s",
                cfg.provider,
                attempt + 1,
                attempts,
                exc,
            )
            if attempt + 1 < attempts:
                time.sleep(1.0)
    raise LLMProviderError(
        0, raw=str(last_exc), provider=cfg.provider
    ) from last_exc


def _apply_thinking(cfg: ChatLLMConfig, payload: dict) -> None:
    """
    DeepSeek V4 reasons by default. Send the flag explicitly either way —
    disabling roughly halves completion tokens and latency for RAG answers.
    """
    if cfg.provider != "DeepSeek":
        return
    thinking = (getattr(settings, "DEEPSEEK_THINKING", "") or "disabled").strip().lower()
    if thinking in ("enabled", "true", "1", "yes"):
        payload["thinking"] = {"type": "enabled"}
        effort = (getattr(settings, "DEEPSEEK_REASONING_EFFORT", "") or "high").strip()
        if effort:
            payload["reasoning_effort"] = effort
    else:
        payload["thinking"] = {"type": "disabled"}


def extract_message_content(data: dict, *, provider: str = "AI") -> str:
    """
    Pull the assistant text out of a chat completion payload.

    Never falls back to `reasoning_content` — that is internal chain-of-thought
    and must not reach students.
    """
    try:
        content = (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("%s returned unexpected payload: %s", provider, str(data)[:400])
        raise RuntimeError(f"{provider} returned an empty response") from exc
    if not content:
        logger.warning("%s returned empty content: %s", provider, str(data)[:400])
        raise RuntimeError(f"{provider} returned an empty response")
    return content


def chat_completion(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    response_format: dict | None = None,
    timeout: int = 60,
    model: str | None = None,
    retries_on_429: int = 1,
) -> str:
    """
    POST /chat/completions and return assistant message content.
    Raises LLMProviderError / RuntimeError on failure.
    """
    cfg = get_chat_llm()
    payload: dict = {
        "model": model or cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    _apply_thinking(cfg, payload)

    response = _post_chat(cfg, payload, timeout)
    for _ in range(max(0, retries_on_429)):
        if response.status_code != 429:
            break
        time.sleep(1.5)
        response = _post_chat(cfg, payload, timeout)

    raise_for_llm_response(response, provider=cfg.provider)
    return extract_message_content(response.json(), provider=cfg.provider)


def chat_completion_raw(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    response_format: dict | None = None,
    timeout: int = 60,
) -> requests.Response:
    """
    Same as chat_completion but returns the Response for callers that need
    status-based shrink/retry (e.g. answer_service TPM handling).
    """
    cfg = get_chat_llm()
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    _apply_thinking(cfg, payload)

    return _post_chat(cfg, payload, timeout)
