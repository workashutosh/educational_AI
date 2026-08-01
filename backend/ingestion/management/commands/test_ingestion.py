"""
Management command: test_ingestion <file_path> <bucket_id>

Runs the full parse → PageIndex pipeline synchronously (no Celery)
for local debugging.
"""
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from ingestion.models import Document, SubjectBucket
from ingestion.services import find_indexed_duplicate, sha256_of_file
from ingestion.tasks import process_document_sync


class Command(BaseCommand):
    help = "Run the ingestion pipeline synchronously for a local file."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to PDF/DOCX/PPTX/image/MD")
        parser.add_argument("bucket_id", type=int, help="SubjectBucket primary key")
        parser.add_argument(
            "--teacher-id",
            type=int,
            default=None,
            help="Optional Teacher id for uploaded_by attribution",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file_path"]).expanduser().resolve()
        bucket_id = options["bucket_id"]

        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        try:
            bucket = SubjectBucket.objects.get(pk=bucket_id)
        except SubjectBucket.DoesNotExist as exc:
            raise CommandError(f"Bucket {bucket_id} does not exist") from exc

        file_hash = sha256_of_file(file_path)
        duplicate = find_indexed_duplicate(bucket.id, file_hash)
        if duplicate:
            self.stdout.write(
                self.style.WARNING(
                    f"Exact duplicate of indexed document #{duplicate.pk} — "
                    f"creating Document with status=duplicate and skipping pipeline."
                )
            )

        teacher = None
        if options["teacher_id"]:
            from ingestion.models import Teacher

            try:
                teacher = Teacher.objects.get(pk=options["teacher_id"])
            except Teacher.DoesNotExist as exc:
                raise CommandError(f"Teacher {options['teacher_id']} not found") from exc

        with open(file_path, "rb") as fh:
            document = Document(
                bucket=bucket,
                uploaded_by=teacher,
                original_filename=file_path.name,
                file_hash=file_hash,
                status=Document.STATUS_DUPLICATE if duplicate else Document.STATUS_QUEUED,
                duplicate_of=duplicate,
            )
            document.file.save(file_path.name, File(fh), save=True)

        self.stdout.write(f"Created Document #{document.pk} (status={document.status})")

        if duplicate:
            return

        self.stdout.write("Running pipeline synchronously…")
        result = process_document_sync(document.pk)

        document.refresh_from_db()
        if result.get("ok") and document.status == Document.STATUS_INDEXED:
            nodes = 0
            tree = document.pageindex_tree or {}
            structure = tree.get("structure") or []
            if isinstance(structure, list):
                nodes = self._count_nodes(structure)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Indexed document #{document.pk}: "
                    f"pages={document.page_count}, tree_nodes≈{nodes}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Pipeline ended with status={document.status}: "
                    f"{document.error_message or result}"
                )
            )

    def _count_nodes(self, nodes) -> int:
        total = 0
        for node in nodes:
            total += 1
            total += self._count_nodes(node.get("nodes") or [])
        return total
