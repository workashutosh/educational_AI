"""
Verify ingest integrity: filename ↔ doc_id ↔ chunk document_id ↔ page ranges.

Usage:
  python manage.py verify_ingest <document_id>
  python manage.py verify_ingest --bucket-id <id>
  python manage.py verify_ingest --reindex <document_id>   # force re-run pipeline
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ingestion.models import Chunk, Document
from ingestion.services.indexing_service import build_live_manifest
from ingestion.tasks import process_document_sync


class Command(BaseCommand):
    help = "Print ingest manifest and check document_id integrity for chunks."

    def add_arguments(self, parser):
        parser.add_argument(
            "document_id",
            nargs="?",
            type=int,
            default=None,
            help="Document primary key",
        )
        parser.add_argument("--bucket-id", type=int, default=None)
        parser.add_argument(
            "--reindex",
            action="store_true",
            help="Force re-run parse+index on the given document_id (ignores duplicate skip)",
        )

    def handle(self, *args, **options):
        doc_id = options["document_id"]
        bucket_id = options["bucket_id"]
        reindex = options["reindex"]

        if reindex:
            if not doc_id:
                raise CommandError("--reindex requires document_id")
            self.stdout.write(f"Re-indexing document #{doc_id}…")
            result = process_document_sync(doc_id)
            self.stdout.write(str(result))

        if doc_id:
            docs = Document.objects.filter(pk=doc_id)
        elif bucket_id:
            docs = Document.objects.filter(bucket_id=bucket_id).order_by("id")
        else:
            raise CommandError("Pass document_id or --bucket-id")

        if not docs.exists():
            raise CommandError("No documents found")

        for doc in docs:
            manifest = build_live_manifest(doc)
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"=== {manifest['source_filename']} (doc_id={manifest['doc_id']}) ==="
            ))
            self.stdout.write(
                f"status={manifest['status']} bucket_id={manifest['bucket_id']} "
                f"pages={manifest['page_count']} chunks={manifest['chunk_count']} "
                f"chunk_pages={manifest['chunk_page_range']} "
                f"hash={(manifest['file_hash'] or '')[:16]}"
            )
            if manifest["document_id_mismatches"]:
                self.stdout.write(
                    self.style.ERROR(
                        f"BUG: {manifest['document_id_mismatches']} chunks "
                        f"have document_id != {doc.pk}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"OK: all {manifest['chunk_count']} chunks point at doc_id={doc.pk}"
                    )
                )
            for c in manifest["chunks"][:10]:
                self.stdout.write(
                    f"  chunk#{c['chunk_id']} order={c['order_index']} "
                    f"doc_id={c['document_id']} pages={c['page_start']}-{c['page_end']} "
                    f"path={' > '.join(c['heading_path'] or [])!r}"
                )
                self.stdout.write(f"    {c['preview']!r}")

            # Orphan check: chunks claiming this filename via join should match
            foreign = (
                Chunk.objects.filter(bucket_id=doc.bucket_id)
                .exclude(document_id=doc.pk)
                .filter(document__original_filename=doc.original_filename)
                .count()
            )
            if foreign:
                self.stdout.write(
                    self.style.WARNING(
                        f"Note: {foreign} other-doc chunks share filename "
                        f"{doc.original_filename!r} (re-uploads with same name)"
                    )
                )
