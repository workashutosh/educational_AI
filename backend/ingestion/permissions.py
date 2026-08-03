from rest_framework.permissions import BasePermission

from .models import SchoolMembership, SubjectBucket


def get_membership(user) -> SchoolMembership | None:
    if not user or not user.is_authenticated:
        return None
    try:
        membership = user.school_membership
    except SchoolMembership.DoesNotExist:
        return None
    if not membership.is_active:
        return None
    return membership


# Backwards-compatible name used across older views.
get_teacher = get_membership


class IsSchoolMember(BasePermission):
    """Authenticated user with an active school membership (any role)."""

    message = "A school membership is required."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None:
            return False
        request.member = member
        request.teacher = member  # legacy alias
        return True


# Legacy alias
IsTeacher = IsSchoolMember


class HasBucketAccess(BasePermission):
    """
    Shared access gate for upload, query, and ask.

    Admin/manager: all buckets in their school.
    Teacher/student: explicit BucketAccess row required.
    """

    message = "You do not have access to this subject bucket."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None:
            return False

        bucket_id = self._resolve_bucket_id(request, view)
        if bucket_id is None:
            request.member = member
            request.teacher = member
            return True

        try:
            bucket = SubjectBucket.objects.get(pk=bucket_id)
        except (SubjectBucket.DoesNotExist, ValueError, TypeError):
            self.message = "Subject bucket not found."
            return False

        if bucket.is_archived:
            self.message = "This subject bucket is archived."
            return False

        if not member.has_bucket_access(bucket):
            self.message = "You do not have access to this subject bucket."
            return False

        request.member = member
        request.teacher = member
        request.bucket = bucket
        return True

    def _resolve_bucket_id(self, request, view):
        if hasattr(view, "get_bucket_id"):
            return view.get_bucket_id()

        return (
            request.data.get("bucket_id")
            or request.query_params.get("bucket_id")
            or view.kwargs.get("bucket_id")
            or view.kwargs.get("id")
        )


class CanUpload(BasePermission):
    """Students may not upload notes."""

    message = "Your role is not allowed to upload documents."

    def has_permission(self, request, view):
        member = getattr(request, "member", None) or get_membership(request.user)
        if member is None or not member.can_upload:
            return False
        return True


class CanCreateStudents(BasePermission):
    """Admins, managers, and teachers may create student accounts."""

    message = "Your role is not allowed to create student profiles."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None or not member.can_create_students:
            return False
        request.member = member
        request.teacher = member
        return True


class CanListMembers(BasePermission):
    """Managers/admins (grants) and anyone who can create students (roster)."""

    message = "You cannot list school members."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None:
            return False
        if member.is_manager_or_above or member.can_create_students:
            request.member = member
            request.teacher = member
            return True
        return False


class IsSchoolAdmin(BasePermission):
    """School admin only."""

    message = "School admin privileges are required."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None or member.role != SchoolMembership.ROLE_ADMIN:
            return False
        request.member = member
        request.teacher = member
        return True


class IsManagerOrAdmin(BasePermission):
    """Admin or manager — bucket create / access grants."""

    message = "Manager or admin privileges are required."

    def has_permission(self, request, view):
        member = get_membership(request.user)
        if member is None or not member.is_manager_or_above:
            return False
        request.member = member
        request.teacher = member
        return True
