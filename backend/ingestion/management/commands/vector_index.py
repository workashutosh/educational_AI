"""
Maintain chunk embeddings.

  manage.py vector_index --status            # counts per backend
  manage.py vector_index --backfill          # copy JSON embeddings → pgvector column
  manage.py vector_index --reembed [--bucket ID]
      # recompute embeddings with the current EMBEDDING_MODEL (e.g. after
      # switching to a multilingual model), then mirror to pgvector
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

from ingestion.models import Chunk
from ingestion.services.embedding_service import embed_texts, model_name
from ingestion.services.vector_store import COLUMN, TABLE, pgvector_available, reset_cache, write_vectors

BATCH = 64


class Command(BaseCommand):
    help = "Backfill / rebuild chunk embeddings and the optional pgvector index."

    def add_arguments(self, parser):
        parser.add_argument("--status", action="store_true")
        parser.add_argument("--backfill", action="store_true")
        parser.add_argument("--reembed", action="store_true")
        parser.add_argument("--bucket", type=int)

    def handle(self, *args, **opts):
        reset_cache()
        qs = Chunk.objects.all().order_by("id")
        if opts.get("bucket"):
            qs = qs.filter(bucket_id=opts["bucket"])

        if opts["reembed"]:
            name = model_name()
            done = 0
            ids = list(qs.values_list("id", flat=True))
            for start in range(0, len(ids), BATCH):
                batch = list(Chunk.objects.filter(id__in=ids[start : start + BATCH]))
                vectors = embed_texts([c.text for c in batch])
                for chunk, vec in zip(batch, vectors):
                    chunk.embedding = vec
                    chunk.embedding_model = name
                    chunk.embedding_dim = len(vec)
                Chunk.objects.bulk_update(batch, ["embedding", "embedding_model", "embedding_dim"])
                write_vectors([(c.id, c.embedding) for c in batch])
                done += len(batch)
                self.stdout.write(f"re-embedded {done}/{len(ids)}")
            self.stdout.write(self.style.SUCCESS(f"Re-embedded {done} chunks with {name}"))

        if opts["backfill"]:
            if not pgvector_available():
                self.stderr.write("pgvector column not present — install pgvector and run migrate.")
                return
            done = 0
            for start in range(0, qs.count(), 500):
                rows = list(qs.values_list("id", "embedding")[start : start + 500])
                done += write_vectors([(cid, emb) for cid, emb in rows if emb])
            self.stdout.write(self.style.SUCCESS(f"Backfilled {done} vectors"))

        if opts["status"] or not (opts["backfill"] or opts["reembed"]):
            total = qs.count()
            self.stdout.write(f"chunks: {total}")
            self.stdout.write(f"pgvector available: {pgvector_available()}")
            if pgvector_available():
                with connection.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {TABLE} WHERE {COLUMN} IS NOT NULL")
                    self.stdout.write(f"vectors in pgvector: {cur.fetchone()[0]}")
