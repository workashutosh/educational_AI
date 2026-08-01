"""Shared helpers for the ingestion pipeline."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ingestion.models import Document


def sha256_of_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_uploaded_file(uploaded_file) -> str:
    """Hash an InMemoryUploadedFile / TemporaryUploadedFile without exhausting it."""
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def find_indexed_duplicate(bucket_id: int, file_hash: str, exclude_id: int | None = None):
    qs = Document.objects.filter(
        bucket_id=bucket_id,
        file_hash=file_hash,
        status=Document.STATUS_INDEXED,
        deleted_at__isnull=True,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.order_by("created_at").first()


def human_error(exc: BaseException, stage: str) -> str:
    """Human-readable error for Document.error_message — never a raw stack trace."""
    detail = str(exc).strip() or exc.__class__.__name__
    return f"{stage} failed: {detail}"
