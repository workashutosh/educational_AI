"""
Single public harness entrypoint.

Future agents (question paper, PPT, …) should import only ``run_query``.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied

from ingestion.models import SchoolMembership

from .bucket_router import get_bucket, get_indexed_documents
from .context_builder import build_context
from .exceptions import HarnessLLMError
from .permissions import check_bucket_access
from .retriever import retrieve

logger = logging.getLogger(__name__)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM = (
    "You are a study assistant. Answer using ONLY the numbered source excerpts. "
    "Cite sources inline like [1] or [2][3]. If the excerpts do not contain the "
    "answer, say so plainly instead of guessing."
)


def run_query(
    teacher: SchoolMembership,
    bucket_id: int,
    query: str,
) -> dict[str, Any]:
    """
    Permissioned RAG query.

    Returns ``{answer, sources: [{document_id, section_title, page_ref}]}``.
    Raises ``PermissionDenied`` or ``HarnessLLMError``.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required")

    bucket = get_bucket(bucket_id)
    check_bucket_access(teacher, bucket)

    docs = get_indexed_documents(bucket)
    if not docs.exists():
        return {
            "answer": "No indexed notes in this AI Bucket yet.",
            "sources": [],
        }

    top_k = int(getattr(settings, "RAG_HARNESS_TOP_K", 5))
    try:
        nodes = retrieve(bucket, query=query, top_k=top_k)
    except HarnessLLMError:
        raise
    except Exception as exc:
        logger.exception("Harness retrieval failed bucket=%s", bucket_id)
        raise HarnessLLMError("Retrieval failed. Please try again.") from exc

    if not nodes:
        return {
            "answer": "I couldn't find anything about that in this subject's indexed notes.",
            "sources": [],
        }

    context = build_context(nodes)
    try:
        answer = _call_llm(query=query, context=context)
    except HarnessLLMError:
        raise
    except Exception as exc:
        logger.exception("Harness LLM failed bucket=%s", bucket_id)
        raise HarnessLLMError(
            "The language model failed or timed out. Please try again."
        ) from exc

    sources = [
        {
            "document_id": n["document_id"],
            "section_title": n.get("section_title") or "",
            "page_ref": n.get("page_ref"),
        }
        for n in nodes
    ]
    return {"answer": answer, "sources": sources}


def _resolve_litellm_model() -> str:
    """
    Reuse existing env keys — no new NIM/Qwen secrets.

    Prefer LiteLLM PAGEINDEX_MODEL when Gemini is configured; else Groq via LiteLLM.
    """
    if getattr(settings, "GEMINI_API_KEY", ""):
        return getattr(settings, "PAGEINDEX_MODEL", "gemini/gemini-2.5-flash")
    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if groq_key:
        groq_model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
        return f"groq/{groq_model}"
    raise HarnessLLMError(
        "No LLM configured. Set GROQ_API_KEY or GEMINI_API_KEY."
    )


def _call_llm(query: str, context: str) -> str:
    user_content = (
        f"Source excerpts:\n\n{context}\n\n"
        f"Question: {query}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_content},
    ]

    # Prefer LiteLLM (PageIndex stack) when available; fall back to Groq HTTP
    # used by /api/ask/ so the harness works with the same .env as today.
    try:
        return _call_litellm(messages)
    except HarnessLLMError:
        raise
    except Exception as exc:
        logger.warning("LiteLLM path failed (%s); trying Groq HTTP", exc)
        if getattr(settings, "GROQ_API_KEY", ""):
            return _call_groq_http(messages)
        raise HarnessLLMError(str(exc)) from exc


def _call_litellm(messages: list[dict]) -> str:
    try:
        from litellm import completion
    except ImportError as exc:
        raise RuntimeError("litellm is not installed") from exc

    model = _resolve_litellm_model()
    # Ensure Groq key is visible to LiteLLM when using groq/ models
    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if groq_key:
        import os

        os.environ.setdefault("GROQ_API_KEY", groq_key)

    try:
        resp = completion(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1400,
        )
    except Exception as exc:
        raise HarnessLLMError(f"LiteLLM error: {exc}") from exc

    try:
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        raise HarnessLLMError("LiteLLM returned an empty response") from exc


def _call_groq_http(messages: list[dict]) -> str:
    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        raise HarnessLLMError("GROQ_API_KEY is not set.")
    model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        response = requests.post(
            _GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1400,
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        raise HarnessLLMError(f"Groq request failed: {exc}") from exc

    if response.status_code != 200:
        raise HarnessLLMError(
            f"Groq API error ({response.status_code})"
        )
    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise HarnessLLMError("Groq returned an empty response") from exc


# Re-export for clarity in docs/tests
__all__ = ["run_query", "PermissionDenied", "HarnessLLMError"]
