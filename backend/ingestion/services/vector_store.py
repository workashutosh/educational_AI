"""
Optional pgvector ANN index for Chunk embeddings.

The JSON `Chunk.embedding` column stays the source of truth (works on SQLite
and plain Postgres). When the `vector` extension and the `embedding_vec`
column exist (migration ingestion 0007 creates them if it can), indexing
mirrors vectors into it and retrieval asks Postgres for the nearest
candidates via an HNSW index instead of scoring every chunk in Python.

RAG_VECTOR_BACKEND: auto (default) | pgvector | json.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger(__name__)

TABLE = "ingestion_chunk"
COLUMN = "embedding_vec"
_available: bool | None = None


def reset_cache() -> None:
    global _available
    _available = None


def pgvector_available() -> bool:
    global _available
    backend = (getattr(settings, "RAG_VECTOR_BACKEND", "auto") or "auto").lower()
    if backend == "json" or connection.vendor != "postgresql":
        return False
    if _available is None:
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = %s",
                    [TABLE, COLUMN],
                )
                _available = cur.fetchone() is not None
        except Exception:
            logger.warning("pgvector availability check failed", exc_info=True)
            _available = False
        if backend == "pgvector" and not _available:
            logger.error("RAG_VECTOR_BACKEND=pgvector but %s.%s is missing", TABLE, COLUMN)
    return bool(_available)


def _literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"


def write_vectors(pairs: list[tuple[int, list[float]]]) -> int:
    """Mirror (chunk_id, embedding) pairs into the vector column."""
    if not pairs or not pgvector_available():
        return 0
    dim = int(getattr(settings, "EMBEDDING_DIM", 384))
    rows = [(_literal(v), cid) for cid, v in pairs if v and len(v) == dim]
    if not rows:
        return 0
    with connection.cursor() as cur:
        cur.executemany(f"UPDATE {TABLE} SET {COLUMN} = %s::vector WHERE id = %s", rows)
    return len(rows)


def nearest_chunk_ids(
    bucket_id: int,
    query_vec: list[float],
    limit: int,
    *,
    kinds: list[str] | None = None,
    document_ids: list[int] | None = None,
) -> list[tuple[int, float]]:
    """[(chunk_id, cosine_similarity)] nearest first, filtered to indexed docs."""
    where = [
        "c.bucket_id = %s",
        f"c.{COLUMN} IS NOT NULL",
        "d.status = 'indexed'",
        "d.deleted_at IS NULL",
    ]
    params: list = [bucket_id]
    if kinds:
        where.append("d.kind = ANY(%s)")
        params.append(list(kinds))
    if document_ids:
        where.append("c.document_id = ANY(%s)")
        params.append([int(i) for i in document_ids])
    vec = _literal(query_vec)
    sql = (
        f"SELECT c.id, 1 - (c.{COLUMN} <=> %s::vector) AS score "
        f"FROM {TABLE} c JOIN ingestion_document d ON d.id = c.document_id "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY c.{COLUMN} <=> %s::vector LIMIT %s"
    )
    with transaction.atomic(), connection.cursor() as cur:
        # Filtered HNSW scans can under-fill; widen the candidate list (txn-local).
        cur.execute("SET LOCAL hnsw.ef_search = 200")
        cur.execute(sql, [vec, *params, vec, int(limit)])
        return [(int(r[0]), float(r[1])) for r in cur.fetchall()]
