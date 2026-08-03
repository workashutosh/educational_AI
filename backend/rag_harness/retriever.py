"""
Bucket retrieval for the harness.

Preferred path when Document.pageindex_tree holds a full PageIndex tree
(with node text): reuse ``ingestion.services.pageindex_service.query_bucket_trees``.

Today's indexing stores an LLM-free structure summary (no node text) and
embeddings on Chunk rows — so we fall back to ``search_bucket`` cosine
retrieval, which is what /api/ask/ uses. Matches are normalized to the
harness shape either way.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from ingestion.models import Document, SubjectBucket
from ingestion.services.pageindex_service import query_bucket_trees
from ingestion.services.retrieval_service import search_bucket

from .bucket_router import get_indexed_documents, normalize_kinds
from .exceptions import HarnessLLMError

logger = logging.getLogger(__name__)


def retrieve(
    bucket: SubjectBucket,
    query: str,
    top_k: int | None = None,
    *,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return global top_k matches across indexed docs in the bucket.

    ``kinds`` limits to document kinds (notes / question_paper). None = all.

    Each item: {document_id, section_title, page_ref, text, score?}
    """
    k = top_k if top_k is not None else int(
        getattr(settings, "RAG_HARNESS_TOP_K", 5)
    )
    kind_list = normalize_kinds(kinds)
    docs = list(get_indexed_documents(bucket, kinds=kind_list))
    if not docs:
        return []

    if _docs_have_pageindex_text(docs):
        try:
            return _retrieve_via_pageindex(docs, query, k)
        except Exception as exc:
            logger.warning(
                "PageIndex tree-search failed for bucket=%s; falling back to embeddings: %s",
                bucket.pk,
                exc,
            )

    return _retrieve_via_embeddings(bucket.id, query, k, kinds=kind_list)


def _docs_have_pageindex_text(docs: list[Document]) -> bool:
    """True if any stored tree looks like a real PageIndex payload with node text."""
    for doc in docs:
        tree = doc.pageindex_tree or {}
        structure = tree.get("structure")
        if not structure:
            continue
        nodes = structure if isinstance(structure, list) else [structure]
        for node in nodes[:5]:
            if isinstance(node, dict) and (node.get("text") or node.get("summary")):
                return True
            # Nested children (PageIndex trees)
            children = node.get("nodes") or node.get("children") if isinstance(node, dict) else None
            if children:
                return True
    return False


def _retrieve_via_pageindex(
    docs: list[Document],
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Run PageIndex tree-search per document, then take a global top_k.

    ``query_bucket_trees`` already caps the list; we pass a larger per-call
    budget by collecting ourselves for a true cross-doc merge.
    """
    payload = [
        {
            "id": d.id,
            "original_filename": d.original_filename,
            "pageindex_tree": d.pageindex_tree or {},
        }
        for d in docs
        if (d.pageindex_tree or {}).get("structure")
    ]
    if not payload:
        return []

    try:
        # Request more than top_k so early docs don't starve later ones;
        # query_bucket_trees returns a flat list we re-rank.
        raw = query_bucket_trees(payload, query=query, top_k=max(top_k * len(payload), top_k))
    except Exception as exc:
        raise HarnessLLMError(f"PageIndex tree-search failed: {exc}") from exc

    ranked = sorted(
        raw,
        key=lambda m: (len(m.get("text") or "") + len(m.get("summary") or ""),),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for m in ranked[:top_k]:
        text = (m.get("text") or m.get("summary") or "").strip()
        if not text:
            continue
        out.append(
            {
                "document_id": m["document_id"],
                "section_title": m.get("title") or "untitled section",
                "page_ref": m.get("page_ref"),
                "text": text,
                "score": None,
            }
        )
    return out


def _retrieve_via_embeddings(
    bucket_id: int,
    query: str,
    top_k: int,
    *,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    chunks = search_bucket(bucket_id, query=query, top_k=top_k, kinds=kinds)
    out: list[dict[str, Any]] = []
    for c in chunks:
        heading = " > ".join(c.heading_path) if c.heading_path else "untitled section"
        page_ref = _page_ref(c.page_start, c.page_end)
        out.append(
            {
                "document_id": c.document_id,
                "section_title": heading,
                "page_ref": page_ref,
                "text": c.text,
                "score": c.score,
            }
        )
    return out


def _page_ref(start: int | None, end: int | None) -> str | None:
    if start is None:
        return None
    if end is None or start == end:
        return f"page {start}"
    return f"pages {start}-{end}"
