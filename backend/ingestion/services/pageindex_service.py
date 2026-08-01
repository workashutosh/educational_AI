"""
PageIndex integration: tree building + LLM tree-search query.

Uses the local clone at pageindex_repo/ (added to sys.path in settings).
LLM calls go through LiteLLM → Google Gemini (Google AI Studio), configured
via PAGEINDEX_MODEL and GEMINI_API_KEY env vars.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_model() -> str:
    return getattr(settings, "PAGEINDEX_MODEL", "gemini/gemini-2.5-flash")


def _ensure_workspace() -> Path:
    workspace = Path(settings.PAGEINDEX_WORKSPACE)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def build_pageindex_tree(markdown_path: str | Path) -> dict[str, Any]:
    """
    Build a PageIndex hierarchical tree from parsed markdown output.

    Returns a JSON-serializable dict stored in Document.pageindex_tree:
      {doc_name, doc_description, line_count, structure, source}
    """
    from pageindex.page_index_md import md_to_tree

    markdown_path = Path(markdown_path)
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown not found: {markdown_path}")

    model = _get_model()
    _ensure_workspace()

    coro = md_to_tree(
        md_path=str(markdown_path),
        if_thinning=False,
        if_add_node_summary="yes",
        summary_token_threshold=200,
        model=model,
        if_add_doc_description="yes",
        if_add_node_text="yes",
        if_add_node_id="yes",
    )
    result = _run_async(coro)

    if not result or "structure" not in result:
        raise RuntimeError("PageIndex returned no structure for this document")

    return {
        "doc_name": result.get("doc_name") or markdown_path.stem,
        "doc_description": result.get("doc_description", ""),
        "line_count": result.get("line_count"),
        "structure": result["structure"],
        "source": str(markdown_path.name),
        "model": model,
    }


def query_bucket_trees(
    documents: list[dict[str, Any]],
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Run PageIndex LLM tree-search over indexed documents in a bucket.

    `documents` items: {id, original_filename, pageindex_tree}
    Returns matched nodes with page/section references and text.
    """
    from pageindex.utils import create_node_mapping, extract_json, llm_completion, remove_fields

    model = _get_model()
    matches: list[dict[str, Any]] = []

    for doc in documents:
        tree_payload = doc.get("pageindex_tree") or {}
        structure = tree_payload.get("structure")
        if not structure:
            continue

        # Strip heavy text fields for the LLM prompt (keep title/summary/ids/ranges)
        slim_tree = remove_fields(
            structure,
            fields=["text"],
        )

        prompt = f"""
You are given a query and the tree structure of a document.
You need to find all nodes that are likely to contain the answer.

Query: {query}

Document name: {doc.get("original_filename", tree_payload.get("doc_name", ""))}
Document description: {tree_payload.get("doc_description", "")}

Document tree structure: {json.dumps(slim_tree, ensure_ascii=False)}

Reply in the following JSON format:
{{
  "thinking": "<your reasoning about which nodes are relevant>",
  "node_list": ["node_id1", "node_id2"]
}}
""".strip()

        raw = llm_completion(model, prompt)
        parsed = extract_json(raw) if raw else {}
        node_ids = parsed.get("node_list") or []
        thinking = parsed.get("thinking", "")

        mapping = create_node_mapping(structure if isinstance(structure, list) else [structure])

        for node_id in node_ids[:top_k]:
            node = mapping.get(str(node_id)) or mapping.get(node_id)
            if not node:
                continue
            matches.append(
                {
                    "document_id": doc["id"],
                    "document_filename": doc.get("original_filename"),
                    "node_id": node.get("node_id"),
                    "title": node.get("title"),
                    "summary": node.get("summary") or node.get("prefix_summary", ""),
                    "text": node.get("text", ""),
                    "start_index": node.get("start_index") or node.get("line_num"),
                    "end_index": node.get("end_index"),
                    "page_ref": _page_ref(node),
                    "thinking": thinking,
                }
            )

    # Prefer denser matches first; cap overall
    return matches[:top_k]


def _page_ref(node: dict) -> str | None:
    start = node.get("start_index")
    end = node.get("end_index")
    if start is not None and end is not None:
        if start == end:
            return f"page {start}"
        return f"pages {start}-{end}"
    line = node.get("line_num")
    if line is not None:
        return f"line {line}"
    return None


def _run_async(coro):
    """Run a coroutine whether or not an event loop is already running (Celery)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
