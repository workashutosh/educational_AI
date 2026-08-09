"""
Structure indexing: turns parsed markdown into Chunk rows (text + embedding)
plus a lightweight structural tree for citation/display.

No LLM involved — hierarchical, page-anchored structure from parse_service
markers, then local embeddings for retrieval.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from ..models import Chunk, Document
from .chunk_service import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_markdown
from .embedding_service import embed_texts, model_name

logger = logging.getLogger(__name__)


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

    # Atomic replace — never leave a document with deleted-but-not-recreated chunks
    with transaction.atomic():
        deleted_n = Chunk.objects.filter(document=document).delete()[0]
        Chunk.objects.bulk_create(
            [
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
            ]
        )

    page_nums = sorted(
        {
            p
            for span in spans
            for p in (span.page_start, span.page_end)
            if p is not None
        }
    )
    page_range = (
        f"{page_nums[0]}-{page_nums[-1]}" if page_nums else "unknown"
    )
    manifest = {
        "source_filename": document.original_filename,
        "doc_id": document.pk,
        "bucket_id": document.bucket_id,
        "file_hash": document.file_hash,
        "page_count": document.page_count,
        "chunk_page_range": page_range,
        "chunk_count": len(spans),
        "chunks_deleted_before_write": deleted_n,
        "embedding_model": embedding_model,
        "sample_chunks": [
            {
                "order_index": i,
                "page_start": span.page_start,
                "page_end": span.page_end,
                "heading_path": span.heading_path,
                "chars": len(span.text),
                "text_preview": span.text[:120].replace("\n", " "),
            }
            for i, span in enumerate(spans[:5])
        ],
    }
    logger.info(
        "INGEST_MANIFEST filename=%s doc_id=%s bucket_id=%s pages=%s "
        "chunk_page_range=%s chunk_count=%s deleted_old=%s hash=%s",
        manifest["source_filename"],
        manifest["doc_id"],
        manifest["bucket_id"],
        manifest["page_count"],
        manifest["chunk_page_range"],
        manifest["chunk_count"],
        manifest["chunks_deleted_before_write"],
        (manifest["file_hash"] or "")[:12],
    )

    structure = _build_structure_tree(spans)
    structure["ingest_manifest"] = {
        k: v for k, v in manifest.items() if k != "sample_chunks"
    }
    return {
        "chunk_count": len(spans),
        "embedding_model": embedding_model,
        "structure": structure,
        "manifest": manifest,
    }


def _build_structure_tree(spans) -> dict[str, Any]:
    """LLM-free structural summary stored on Document.pageindex_tree."""
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


def build_live_manifest(document: Document) -> dict[str, Any]:
    """Recompute a manifest from stored Chunk rows (post-ingest verification)."""
    chunks = list(
        Chunk.objects.filter(document=document).order_by("order_index").values(
            "id",
            "order_index",
            "page_start",
            "page_end",
            "heading_path",
            "char_count",
            "text",
            "document_id",
        )
    )
    mismatches = [c for c in chunks if c["document_id"] != document.pk]
    pages = sorted(
        {
            p
            for c in chunks
            for p in (c["page_start"], c["page_end"])
            if p is not None
        }
    )
    return {
        "source_filename": document.original_filename,
        "doc_id": document.pk,
        "bucket_id": document.bucket_id,
        "status": document.status,
        "file_hash": document.file_hash,
        "page_count": document.page_count,
        "chunk_count": len(chunks),
        "chunk_page_range": f"{pages[0]}-{pages[-1]}" if pages else "none",
        "document_id_mismatches": len(mismatches),
        "chunks": [
            {
                "chunk_id": c["id"],
                "order_index": c["order_index"],
                "document_id": c["document_id"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
                "heading_path": c["heading_path"],
                "chars": c["char_count"],
                "preview": (c["text"] or "")[:100].replace("\n", " "),
            }
            for c in chunks[:20]
        ],
    }
