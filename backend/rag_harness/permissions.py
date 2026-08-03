"""
Bucket access gate for the harness.

Reuses ingestion's SchoolMembership.has_bucket_access rule
(admin/manager → all school buckets; else TeacherBucketAccess / BucketAccess row).
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied

from ingestion.models import SchoolMembership, SubjectBucket


def check_bucket_access(teacher: SchoolMembership | None, bucket: SubjectBucket) -> None:
    """
    Raise PermissionDenied if ``teacher`` may not use ``bucket``.

    ``teacher`` is a SchoolMembership (alias: Teacher).
    """
    if teacher is None:
        raise PermissionDenied("A school membership is required.")
    if bucket.is_archived:
        raise PermissionDenied("This subject bucket is archived.")
    if teacher.school_id != bucket.school_id:
        raise PermissionDenied("You do not have access to this subject bucket.")
    if not teacher.has_bucket_access(bucket):
        raise PermissionDenied("You do not have access to this subject bucket.")
