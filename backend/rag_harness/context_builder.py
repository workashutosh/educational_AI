"""Merge retrieved nodes into a single context string under a char budget."""
from __future__ import annotations

from typing import Any

from django.conf import settings


def build_context(retrieved_nodes: list[dict[str, Any]]) -> str:
    """
    Format numbered source blocks. If over RAG_HARNESS_MAX_CONTEXT_CHARS,
    drop lowest-relevance nodes first (tail of the list / lowest score).
    """
    if not retrieved_nodes:
        return ""

    max_chars = int(getattr(settings, "RAG_HARNESS_MAX_CONTEXT_CHARS", 12000))
    nodes = list(retrieved_nodes)

    # Prefer keeping higher scores; nodes without score keep list order (retriever rank).
    def sort_key(item: tuple[int, dict]) -> tuple:
        idx, node = item
        score = node.get("score")
        if score is None:
            return (0, -idx)  # earlier = better
        return (1, score)

    ranked = sorted(enumerate(nodes), key=sort_key, reverse=True)

    selected: list[tuple[int, dict]] = []
    used = 0
    for idx, node in ranked:
        block = _format_block(len(selected) + 1, node)
        # Tentative size with separators
        extra = len(block) + (2 if selected else 0)
        if selected and used + extra > max_chars:
            continue
        if not selected and len(block) > max_chars:
            # Single oversized node — truncate text
            truncated = dict(node)
            overhead = len(_format_block(1, {**node, "text": ""}))
            keep = max(200, max_chars - overhead - 20)
            truncated["text"] = (node.get("text") or "")[:keep] + "…"
            block = _format_block(1, truncated)
            selected.append((idx, truncated))
            used = len(block)
            break
        selected.append((idx, node))
        used += extra

    # Restore original relative order for readable citations
    selected.sort(key=lambda pair: pair[0])
    blocks = [_format_block(i, node) for i, (_, node) in enumerate(selected, start=1)]
    return "\n\n".join(blocks)


def _format_block(index: int, node: dict[str, Any]) -> str:
    title = node.get("section_title") or "untitled section"
    page = node.get("page_ref")
    doc_id = node.get("document_id")
    header_bits = [f"[{index}]", f"doc={doc_id}", title]
    if page:
        header_bits.append(str(page))
    header = " | ".join(str(b) for b in header_bits)
    body = (node.get("text") or "").strip()
    return f"{header}\n{body}"
