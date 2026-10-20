"""
Celery task: process_document

1. Dedup check (file_hash + indexed in same bucket)
2. parsing  → native text extract, PaddleOCR-VL hosted API fallback for scans
3. indexing → structure-aware chunking + local embeddings (no LLM/Gemini)
4. indexed  → save pageindex_tree (structural), page_count, processed_at
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Document
from .services import find_indexed_duplicate, human_error, sha256_of_file
from .services.parse_service import parse_document
from .services.indexing_service import index_document

logger = logging.getLogger(__name__)


def _set_progress(document_id: int, message: str) -> None:
    """Persist a short live status string for the UI (e.g. '4/16 pages')."""
    Document.objects.filter(pk=document_id).update(progress_message=(message or "")[:200])


def process_document_sync(document_id: int) -> dict:
    """
    Synchronous pipeline used by the Celery task and the test_ingestion
    management command.
    """
    try:
        document = Document.objects.select_related("bucket").get(pk=document_id)
    except Document.DoesNotExist:
        return {"ok": False, "error": f"Document {document_id} not found"}

    # Stale broker messages can outlive a deletion — never spend OCR/embedding
    # budget on a document the user already removed.
    if document.deleted_at is not None:
        logger.info("Skipping deleted document %s", document_id)
        return {"ok": False, "error": "Document was deleted before processing"}

    # --- Stage 1: dedup -------------------------------------------------------
    try:
        file_path = Path(document.file.path)
        if not document.file_hash:
            document.file_hash = sha256_of_file(file_path)
            document.save(update_fields=["file_hash"])

        duplicate = find_indexed_duplicate(
            bucket_id=document.bucket_id,
            file_hash=document.file_hash,
            exclude_id=document.pk,
        )
        if duplicate:
            document.status = Document.STATUS_DUPLICATE
            document.duplicate_of = duplicate
            document.error_message = ""
            document.progress_message = ""
            document.save(
                update_fields=["status", "duplicate_of", "error_message", "progress_message"]
            )
            return {"ok": True, "status": Document.STATUS_DUPLICATE, "duplicate_of": duplicate.pk}
    except Exception as exc:
        document.status = Document.STATUS_FAILED
        document.error_message = human_error(exc, "Deduplication")
        document.progress_message = ""
        document.save(update_fields=["status", "error_message", "progress_message"])
        return {"ok": False, "error": document.error_message}

    work_dir = Path(settings.MEDIA_ROOT) / "processing" / str(document.pk)
    work_dir.mkdir(parents=True, exist_ok=True)

    # --- Stage 2: parsing (native extract, PaddleOCR-VL API fallback) --------
    try:
        document.status = Document.STATUS_PARSING
        document.error_message = ""
        document.progress_message = "Starting…"
        document.save(update_fields=["status", "error_message", "progress_message"])

        parse_result = parse_document(
            file_path,
            work_dir,
            on_progress=lambda msg: _set_progress(document_id, msg),
        )
        document.page_count = parse_result.page_count
        document.save(update_fields=["page_count"])
        markdown_path = parse_result.output_path
    except Exception as exc:
        logger.exception("Parse failed for document %s", document_id)
        document.status = Document.STATUS_FAILED
        document.error_message = human_error(exc, "Parsing")
        document.progress_message = ""
        document.save(update_fields=["status", "error_message", "progress_message"])
        _cleanup(work_dir)
        return {"ok": False, "error": document.error_message}

    # --- Stage 3: indexing (structure-aware chunking + local embeddings) -----
    try:
        document.status = Document.STATUS_INDEXING
        document.progress_message = "Building chunks…"
        document.save(update_fields=["status", "progress_message"])

        result = index_document(
            document,
            markdown_path,
            on_progress=lambda msg: _set_progress(document_id, msg),
        )
        document.pageindex_tree = result["structure"]
        document.status = Document.STATUS_INDEXED
        document.processed_at = timezone.now()
        document.error_message = ""
        document.progress_message = ""
        document.save(
            update_fields=[
                "pageindex_tree",
                "status",
                "processed_at",
                "error_message",
                "progress_message",
            ]
        )
        manifest = result.get("manifest") or {}
        logger.info(
            "Indexed doc_id=%s filename=%s chunks=%s page_range=%s",
            document.pk,
            document.original_filename,
            manifest.get("chunk_count"),
            manifest.get("chunk_page_range"),
        )
    except Exception as exc:
        logger.exception("Indexing failed for document %s", document_id)
        document.status = Document.STATUS_FAILED
        document.error_message = human_error(exc, "Indexing")
        document.progress_message = ""
        document.save(update_fields=["status", "error_message", "progress_message"])
        _cleanup(work_dir)
        return {"ok": False, "error": document.error_message}

    _cleanup(work_dir)
    try:
        from engagement.tasks import on_document_indexed

        on_document_indexed.delay(document.pk)
    except Exception:
        logger.exception("Failed to enqueue engagement.on_document_indexed")
    return {"ok": True, "status": Document.STATUS_INDEXED, "document_id": document.pk}


@shared_task(bind=True, name="ingestion.process_document", max_retries=0)
def process_document(self, document_id: int) -> dict:
    """Celery entrypoint — must not block the upload request."""
    from billing.services.usage import usage_scope

    row = (
        Document.objects.filter(pk=document_id)
        .values("bucket__school_id", "uploaded_by_id")
        .first()
        or {}
    )
    with usage_scope(
        school_id=row.get("bucket__school_id"),
        member_id=row.get("uploaded_by_id"),
        feature="ingestion",
    ):
        return process_document_sync(document_id)


def _cleanup(work_dir: Path) -> None:
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        logger.warning("Could not clean work dir %s", work_dir)
