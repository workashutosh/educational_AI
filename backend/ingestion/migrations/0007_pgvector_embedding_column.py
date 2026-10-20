"""
Optional pgvector ANN column + HNSW index on Chunk.

Best effort: if the `vector` extension cannot be created (not installed, or
the DB role lacks permission) the migration logs and does nothing — retrieval
keeps using JSON embeddings. Run `manage.py vector_index --backfill` after
installing pgvector later.
"""
import logging

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)


def add_vector_column(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    dim = int(getattr(settings, "EMBEDDING_DIM", 384))
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT pgvector_setup")
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:  # pragma: no cover - depends on server
            cur.execute("ROLLBACK TO SAVEPOINT pgvector_setup")
            logger.warning("pgvector not available, skipping ANN column: %s", exc)
            return
        cur.execute(
            f"ALTER TABLE ingestion_chunk ADD COLUMN IF NOT EXISTS embedding_vec vector({dim})"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ingestion_chunk_embedding_vec_hnsw "
            "ON ingestion_chunk USING hnsw (embedding_vec vector_cosine_ops)"
        )
        cur.execute("RELEASE SAVEPOINT pgvector_setup")


def drop_vector_column(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS ingestion_chunk_embedding_vec_hnsw")
        cur.execute("ALTER TABLE ingestion_chunk DROP COLUMN IF EXISTS embedding_vec")


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0006_document_progress_message")]

    operations = [migrations.RunPython(add_vector_column, drop_vector_column)]
