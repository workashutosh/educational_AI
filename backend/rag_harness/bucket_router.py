"""Resolve a SubjectBucket to its indexed Documents."""
from __future__ import annotations

from collections.abc import Iterable

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from ingestion.models import Document, SubjectBucket


def get_bucket(bucket_id: int) -> SubjectBucket:
    return get_object_or_404(SubjectBucket, pk=bucket_id)


def normalize_kinds(kinds: Iterable[str] | None) -> list[str] | None:
    """Return validated kind list, or None meaning all kinds."""
    if kinds is None:
        return None
    allowed = {Document.KIND_NOTES, Document.KIND_QUESTION_PAPER}
    cleaned = [k for k in kinds if k in allowed]
    return cleaned or None


def get_indexed_documents(
    bucket: SubjectBucket,
    *,
    kinds: Iterable[str] | None = None,
) -> QuerySet[Document]:
    """Documents in ``bucket`` with status=indexed and not soft-deleted."""
    qs = Document.objects.filter(
        bucket=bucket,
        status=Document.STATUS_INDEXED,
        deleted_at__isnull=True,
    )
    cleaned = normalize_kinds(kinds)
    if cleaned is not None:
        qs = qs.filter(kind__in=cleaned)
    return qs.order_by("id")
