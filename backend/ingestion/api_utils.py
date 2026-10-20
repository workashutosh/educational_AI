"""
Small helpers shared by the feature apps (question bank, homework, learning,
analytics, school ops, billing) so access rules stay identical everywhere.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from .models import SchoolMembership, SubjectBucket
from .permissions import get_membership


def member_of(request) -> SchoolMembership | None:
    return getattr(request, "member", None) or get_membership(request.user)


def is_staff(member: SchoolMembership) -> bool:
    """Admins, managers, and teachers (anyone who teaches)."""
    return member.role in {
        SchoolMembership.ROLE_ADMIN,
        SchoolMembership.ROLE_MANAGER,
        SchoolMembership.ROLE_TEACHER,
    }


def is_student(member: SchoolMembership) -> bool:
    return member.role == SchoolMembership.ROLE_STUDENT


def accessible_buckets(member: SchoolMembership):
    base = SubjectBucket.objects.filter(school=member.school, is_archived=False)
    if member.is_manager_or_above:
        return base
    return base.filter(access_grants__member=member).distinct()


def bucket_for(member: SchoolMembership, bucket_id) -> SubjectBucket:
    """404 for other schools, 403 when the member lacks access."""
    bucket = get_object_or_404(
        SubjectBucket, pk=bucket_id, school=member.school, is_archived=False
    )
    if not member.has_bucket_access(bucket):
        raise PermissionDenied("You do not have access to this AI Bucket.")
    return bucket


def bucket_students(bucket: SubjectBucket):
    """Active students explicitly granted to a bucket."""
    return SchoolMembership.objects.filter(
        school=bucket.school,
        role=SchoolMembership.ROLE_STUDENT,
        is_active=True,
        bucket_grants__bucket=bucket,
    ).select_related("user").distinct()


def display_name(member: SchoolMembership) -> str:
    user = member.user
    return (user.get_full_name() or user.first_name or user.username).strip()


def int_list(raw) -> list[int]:
    """Parse [1, "2"] or "1,2" into a de-duplicated list of ints (order kept)."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, (str, int)):
        raw = [raw]
    flat: list = []
    for item in raw:
        if isinstance(item, str):
            flat.extend(p for p in item.split(",") if p.strip())
        else:
            flat.append(item)
    raw = flat
    out: list[int] = []
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value not in out:
            out.append(value)
    return out


def paginate(request, items, *, default_size: int = 50, max_size: int = 200) -> dict:
    """
    Limit/offset pagination for list endpoints that can grow large.

    Response shape: {count, limit, offset, next_offset, results}. Mobile clients
    page with ?limit=&offset=; next_offset is null on the last page.
    """
    try:
        limit = int(request.query_params.get("limit", default_size))
    except (TypeError, ValueError):
        limit = default_size
    try:
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(max_size, limit))
    offset = max(0, offset)
    count = items.count() if hasattr(items, "count") and not isinstance(items, list) else len(items)
    page = list(items[offset : offset + limit])
    next_offset = offset + limit if offset + limit < count else None
    return {
        "count": count,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "results": page,
    }
