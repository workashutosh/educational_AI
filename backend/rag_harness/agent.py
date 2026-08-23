"""
Single public harness entrypoint.

Future agents (question paper, PPT, …) should import only ``run_query``.
"""
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied

from ingestion.models import SchoolMembership
from ingestion.services.llm_provider import chat_completion

from .bucket_router import get_bucket, get_indexed_documents
from .context_builder import build_context
from .exceptions import HarnessLLMError
from .permissions import check_bucket_access
from .retriever import retrieve

logger = logging.getLogger(__name__)

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


def _call_llm(query: str, context: str) -> str:
    user_content = (
        f"Source excerpts:\n\n{context}\n\n"
        f"Question: {query}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        return chat_completion(
            messages,
            temperature=0.2,
            max_tokens=1400,
            timeout=60,
            retries_on_429=1,
        )
    except Exception as exc:
        raise HarnessLLMError(str(exc)) from exc


# Re-export for clarity in docs/tests
__all__ = ["run_query", "PermissionDenied", "HarnessLLMError"]
