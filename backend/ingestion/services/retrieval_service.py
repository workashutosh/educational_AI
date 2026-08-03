"""
Bucket-scoped vector similarity search over Chunk embeddings.

Deliberately brute-force cosine in numpy, not pgvector/ANN — this project's
local dev DB is SQLite (see .env), and per-bucket corpora (one subject's
worth of notes) are small enough that scanning every embedding is fast and
exact. Chunk.embedding is a plain JSON float list specifically so this is an
additive upgrade path: if/when Postgres + pgvector is provisioned, only this
module's internals change — the schema and every caller stay identical.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..models import Chunk
from .embedding_service import embed_query

# Answer-key / solutions appendices drown follow-up queries like "explain that"
# (which have weak lexical signal). Demote them so teaching chapters win.
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
    top_k: int = 5,
    *,
    kinds: list[str] | None = None,
) -> list[RetrievedChunk]:
    qs = Chunk.objects.filter(
        bucket_id=bucket_id, embedding__isnull=False
    ).select_related("document")
    if kinds:
        qs = qs.filter(document__kind__in=kinds)
    rows = list(
        qs.values(
            "id",
            "document_id",
            "document__original_filename",
            "heading_path",
            "page_start",
            "page_end",
            "text",
            "embedding",
        )
    )
    if not rows:
        return []

    matrix = np.array([row["embedding"] for row in rows], dtype=np.float32)
    query_vec = np.array(embed_query(query), dtype=np.float32)

    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    query_norm = np.linalg.norm(query_vec) or 1.0

    scores = (matrix @ query_vec) / (norms * query_norm)

    # Pull a wider candidate pool, then demote answer keys / TOC before cutting
    # to top_k — otherwise a vague follow-up query can return only ANSWERS pages.
    pool = min(max(top_k * 6, top_k), len(rows))
    candidates = np.argpartition(-scores, pool - 1)[:pool]

    ranked: list[tuple[float, int]] = []
    for i in candidates:
        adj = float(scores[i]) * _quality_multiplier(rows[i])
        ranked.append((adj, int(i)))
    ranked.sort(key=lambda t: -t[0])

    out: list[RetrievedChunk] = []
    for adj, i in ranked[:top_k]:
        out.append(
            RetrievedChunk(
                chunk_id=rows[i]["id"],
                document_id=rows[i]["document_id"],
                document_filename=rows[i]["document__original_filename"],
                heading_path=rows[i]["heading_path"] or [],
                page_start=rows[i]["page_start"],
                page_end=rows[i]["page_end"],
                text=rows[i]["text"],
                score=adj,
            )
        )
    return out


def _quality_multiplier(row: dict) -> float:
    filename = row.get("document__original_filename") or ""
    heading = " ".join(row.get("heading_path") or [])
    text = (row.get("text") or "")[:200]

    mult = 1.0
    if _ANSWER_KEY_FILE.search(filename) or _TOC_HEADING.search(heading):
        mult *= 0.55
    if _TOC_HEADING.search(text) and len(text) < 400:
        mult *= 0.85
    # Very short junk chunks (drop-cap leftovers etc.)
    if len((row.get("text") or "").strip()) < 80:
        mult *= 0.7
    return mult
