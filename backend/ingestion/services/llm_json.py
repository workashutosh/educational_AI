"""
JSON-mode chat helper for generation features (question bank, papers,
flashcards, homework grading, translation). Wraps llm_provider so every
feature gets the same response_format fallback and lenient parsing.
"""
from __future__ import annotations

import json
import re

from .llm_errors import LLMProviderError
from .llm_provider import chat_completion


class LLMJSONError(RuntimeError):
    """The model answered, but not with usable JSON."""


def parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise LLMJSONError("AI response was not valid JSON.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMJSONError("AI response was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise LLMJSONError("AI response was not a JSON object.")
    return data


def llm_json(
    system: str,
    user: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: int = 120,
) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = chat_completion(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
    except LLMProviderError as exc:
        # Some models reject response_format with a 400 — retry plain once.
        if exc.status_code != 400:
            raise
        raw = chat_completion(
            messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout
        )
    return parse_json_object(raw)


def llm_text(
    system: str,
    user: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    timeout: int = 90,
) -> str:
    return chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
