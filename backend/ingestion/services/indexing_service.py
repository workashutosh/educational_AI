"""
Structure indexing: turns parsed markdown into Chunk rows (text + embedding)
plus a lightweight structural tree for citation/display.

No LLM involved — this is the "PageIndex methodology" (hierarchical,
page-anchored structure) applied deterministically from the heading/page
markers parse_service emits, then embedded locally for retrieval. Swapping
in an LLM-based enrichment pass later (titles, summaries, reasoning search)
is additive: it would decorate this same structure, not replace it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from ..models import Chunk, Document
from .chunk_service import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_markdown
from .embedding_service import embed_texts, model_name


def index_document(document: Document, markdown_path: str | Path) -> dict[str, Any]:
    markdown = Path(markdown_path).read_text(encoding="utf-8")
    spans = chunk_markdown(
        markdown,
        max_chars=getattr(settings, "CHUNK_MAX_CHARS", DEFAULT_MAX_CHARS),
        overlap_chars=getattr(settings, "CHUNK_OVERLAP_CHARS", DEFAULT_OVERLAP_CHARS),
    )

    if not spans:
        raise ValueError("Chunker produced no chunks for this document")

    embeddings = embed_texts([span.text for span in spans])
    embedding_model = model_name()

    Chunk.objects.filter(document=document).delete()
    Chunk.objects.bulk_create(
        Chunk(
            document=document,
            bucket_id=document.bucket_id,
            order_index=i,
            heading_path=span.heading_path,
            page_start=span.page_start,
            page_end=span.page_end,
            text=span.text,
            char_count=len(span.text),
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dim=len(embedding),
        )
        for i, (span, embedding) in enumerate(zip(spans, embeddings))
    )

    return {
        "chunk_count": len(spans),
        "embedding_model": embedding_model,
        "structure": _build_structure_tree(spans),
    }


def _build_structure_tree(spans) -> dict[str, Any]:
    """LLM-free structural summary stored on Document.pageindex_tree — used for
    citation/display, not for retrieval (Chunk.embedding is the source of truth)."""
    nodes = [
        {
            "node_id": f"{i:04d}",
            "title": span.heading_path[-1] if span.heading_path else "(untitled)",
            "heading_path": span.heading_path,
            "page_start": span.page_start,
            "page_end": span.page_end,
            "char_count": len(span.text),
        }
        for i, span in enumerate(spans)
    ]
    return {"structure": nodes, "chunk_count": len(nodes)}
