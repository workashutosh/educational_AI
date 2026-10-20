"""
Bucket-scoped vector similarity search over Chunk embeddings.

Brute-force cosine in numpy (JSON embeddings). Filters to indexed,
non-deleted documents only. Optionally expands each hit with ±1 neighbor
chunks from the same document so Example/Solution halves stay together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import logging

import numpy as np
from django.conf import settings
from django.db.models import Q

from ..models import Chunk, Document
from .embedding_service import embed_query
from .vector_store import nearest_chunk_ids, pgvector_available

logger = logging.getLogger(__name__)

_ANSWER_KEY_FILE = re.compile(r"(?:^|[_-])an\.pdf$|(?:answers?|solutions?)\.pdf$", re.I)
_TOC_HEADING = re.compile(r"\b(contents|preface|foreword|answers?)\b", re.I)


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_filename: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str
    score: float


def search_bucket(
    bucket_id: int,
    query: str,
    top_k: int | None = None,
    *,
    kinds: list[str] | None = None,
    document_ids: list[int] | None = None,
    min_score: float | None = None,
    expand_neighbors: bool | None = None,
) -> list[RetrievedChunk]:
    if top_k is None:
        top_k = int(getattr(settings, "RAG_TOP_K", 8) or 8)
    if expand_neighbors is None:
        expand_neighbors = bool(getattr(settings, "RAG_EXPAND_NEIGHBORS", True))

    qs = Chunk.objects.filter(
        bucket_id=bucket_id,
        embedding__isnull=False,
        document__status=Document.STATUS_INDEXED,
        document__deleted_at__isnull=True,
    ).select_related("document")
    if kinds:
        qs = qs.filter(document__kind__in=kinds)
    if document_ids:
        qs = qs.filter(document_id__in=document_ids)
    fields = (
        "id",
        "document_id",
        "document__original_filename",
        "heading_path",
        "page_start",
        "page_end",
        "text",
        "order_index",
    )
    query_vec = embed_query(query)
    pool_size = max(top_k * 6, top_k)

    ann = _ann_candidates(qs, bucket_id, query_vec, pool_size, fields, kinds, document_ids)
    if ann is not None:
        rows, scores, candidates = ann
    else:
        rows = list(qs.values(*fields, "embedding"))
        if not rows:
            return []
        matrix = np.array([row["embedding"] for row in rows], dtype=np.float32)
        query_np = np.array(query_vec, dtype=np.float32)

        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        query_norm = np.linalg.norm(query_np) or 1.0

        scores = (matrix @ query_np) / (norms * query_norm)

        pool = min(pool_size, len(rows))
        candidates = np.argpartition(-scores, pool - 1)[:pool]

    ranked: list[tuple[float, int]] = []
    query_terms = _lexical_terms(query)
    for i in candidates:
        adj = float(scores[i]) * _quality_multiplier(rows[i])
        if query_terms:
            adj += 0.04 * _lexical_overlap(query_terms, rows[i])
        ranked.append((adj, int(i)))
    ranked.sort(key=lambda t: -t[0])

    if min_score is None:
        floor = float(getattr(settings, "RAG_MIN_SCORE", 0.0) or 0.0)
    else:
        floor = float(min_score)

    # Index rows by (document_id, order_index) for neighbor expansion
    by_doc_order: dict[tuple[int, int], int] = {}
    for idx, row in enumerate(rows):
        by_doc_order[(row["document_id"], int(row["order_index"]))] = idx

    seen_ids: set[int] = set()
    out: list[RetrievedChunk] = []

    def add_row(i: int, score: float) -> None:
        row = rows[i]
        cid = int(row["id"])
        if cid in seen_ids:
            return
        seen_ids.add(cid)
        out.append(
            RetrievedChunk(
                chunk_id=cid,
                document_id=row["document_id"],
                document_filename=row["document__original_filename"],
                heading_path=row["heading_path"] or [],
                page_start=row["page_start"],
                page_end=row["page_end"],
                text=row["text"],
                score=score,
            )
        )

    for adj, i in ranked:
        if floor and adj < floor:
            continue
        if len(out) >= top_k and not expand_neighbors:
            break
        add_row(i, adj)
        if expand_neighbors:
            doc_id = rows[i]["document_id"]
            order = int(rows[i]["order_index"])
            for neighbor_order in (order - 1, order + 1):
                j = by_doc_order.get((doc_id, neighbor_order))
                if j is not None:
                    # Neighbor inherits a slightly lower score for ranking display
                    add_row(j, adj * 0.95)
        if len([c for c in out if c.score >= (floor or 0)]) >= top_k and len(out) >= top_k:
            # Keep expanding a bit for neighbors of the top hits only
            if len(out) >= top_k + min(4, top_k):
                break

    # Prefer original hit order: higher score first, hard-cap to top_k (+1 neighbor max)
    out.sort(key=lambda c: -c.score)
    # Neighbor expansion can inflate the list — answer path must stay small for LLM TPM.
    return out[:top_k]


def _ann_candidates(qs, bucket_id, query_vec, pool_size, fields, kinds, document_ids):
    """
    pgvector path: nearest candidates + their ±1 neighbours. Returns
    (rows, scores, candidate_indices) or None to use brute-force numpy.
    """
    if not pgvector_available():
        return None
    try:
        hits = nearest_chunk_ids(
            bucket_id, query_vec, pool_size, kinds=kinds, document_ids=document_ids
        )
    except Exception:
        logger.warning("pgvector search failed; using brute force", exc_info=True)
        return None
    if len(hits) < pool_size and len(hits) < qs.count():
        # Filtered HNSW under-filled (or vectors not backfilled yet).
        return None
    score_by_id = dict(hits)
    rows = list(qs.filter(id__in=list(score_by_id)).values(*fields))
    if not rows:
        return [], [], []
    wanted = Q()
    for row in rows:
        wanted |= Q(
            document_id=row["document_id"],
            order_index__in=[row["order_index"] - 1, row["order_index"] + 1],
        )
    have = {row["id"] for row in rows}
    neighbours = [r for r in qs.filter(wanted).values(*fields) if r["id"] not in have]
    candidates = list(range(len(rows)))
    scores = [score_by_id[row["id"]] for row in rows] + [0.0] * len(neighbours)
    return rows + neighbours, scores, candidates


def _quality_multiplier(row: dict) -> float:
    filename = row.get("document__original_filename") or ""
    heading = " ".join(row.get("heading_path") or [])
    text = (row.get("text") or "")[:200]

    mult = 1.0
    if _ANSWER_KEY_FILE.search(filename) or _TOC_HEADING.search(heading):
        mult *= 0.55
    if _TOC_HEADING.search(text) and len(text) < 400:
        mult *= 0.85
    if len((row.get("text") or "").strip()) < 80:
        mult *= 0.7
    # TOC-only "Appendix" listings are not real appendix content
    body = (row.get("text") or "").lower()
    if "appendix" in body and ("contents" in heading.lower() or len(body) < 900):
        if "example" not in body and "proof" not in body and "modelling" not in body:
            mult *= 0.5
    return mult


def _lexical_terms(query: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-zA-Z0-9]{3,}", (query or "").lower())
        if t
        not in {
            "the",
            "and",
            "for",
            "what",
            "when",
            "with",
            "from",
            "that",
            "this",
            "are",
            "how",
            "example",
            "exact",
            "steps",
            "formula",
        }
    }


def _lexical_overlap(terms: set[str], row: dict) -> float:
    if not terms:
        return 0.0
    blob = (
        f"{' '.join(row.get('heading_path') or [])} {row.get('text') or ''}"
    ).lower()
    hits = sum(1 for t in terms if t in blob)
    return min(1.0, hits / max(3, len(terms)))
