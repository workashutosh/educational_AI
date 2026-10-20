"""Attendance APIs (staff + students) and parent portal APIs."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.api_utils import accessible_buckets, bucket_for, is_staff
from ingestion.models import SchoolMembership
from ingestion.permissions import CanCreateStudents, IsSchoolMember, IsStaffMember
from lectures.models import Lecture

from .models import AttendanceRecord, ParentLink, ParentProfile
from .services import (
    bucket_attendance,
    child_overview,
    children_of,
    lecture_roster,
    parent_payload,
    parent_profile_for,
    set_attendance,
    student_attendance,
)

User = get_user_model()


class AttendanceEntrySerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=[c[0] for c in AttendanceRecord.STATUS_CHOICES])
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AttendanceUpdateSerializer(serializers.Serializer):
    records = AttendanceEntrySerializer(many=True)


class ParentCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    student_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    relationship = serializers.ChoiceField(
        choices=[c[0] for c in ParentLink.RELATION_CHOICES], default="guardian"
    )


class ParentLinkSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    relationship = serializers.ChoiceField(
        choices=[c[0] for c in ParentLink.RELATION_CHOICES], default="guardian"
    )


def _lecture_for_staff(member, pk) -> Lecture:
    from lectures.views import _can_manage

    lecture = get_object_or_404(Lecture.objects.select_related("bucket"), pk=pk, school=member.school)
    if not (_can_manage(member, lecture) or member.has_bucket_access(lecture.bucket)):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("You cannot see this lecture's attendance.")
    return lecture


def _student_visible_to(member: SchoolMembership, student_id) -> SchoolMembership:
    student = get_object_or_404(
        SchoolMembership, pk=student_id, school=member.school, role=SchoolMembership.ROLE_STUDENT
    )
    if not member.is_manager_or_above:
        shared = accessible_buckets(member).filter(access_grants__member=student).exists()
        if not shared:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("This student is not in your AI Buckets.")
    return student


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


class LectureAttendanceView(APIView):
    """GET roster for a lecture; PUT {records:[{student_id,status,note}]} to mark manually."""

    permission_classes = [IsStaffMember]

    def get(self, request, lecture_id):
        return Response(lecture_roster(_lecture_for_staff(request.member, lecture_id)))

    @extend_schema(request=AttendanceUpdateSerializer)
    def put(self, request, lecture_id):
        lecture = _lecture_for_staff(request.member, lecture_id)
        ser = AttendanceUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        set_attendance(lecture, request.member, [dict(r) for r in ser.validated_data["records"]])
        return Response(lecture_roster(lecture))


class BucketAttendanceView(APIView):
    """GET — attendance % per student for one AI Bucket (lowest first)."""

    permission_classes = [IsStaffMember]

    def get(self, request, bucket_id):
        bucket = bucket_for(request.member, bucket_id)
        return Response({"bucket_id": bucket.id, "bucket_name": bucket.name, "students": bucket_attendance(bucket)})


class StudentAttendanceView(APIView):
    permission_classes = [IsStaffMember]

    @extend_schema(parameters=[OpenApiParameter("bucket_id", int), OpenApiParameter("days", int)])
    def get(self, request, student_id):
        student = _student_visible_to(request.member, student_id)
        days = request.query_params.get("days")
        return Response(
            student_attendance(
                student,
                bucket_id=request.query_params.get("bucket_id"),
                days=int(days) if days and days.isdigit() else None,
            )
        )


class MyAttendanceView(APIView):
    """GET — the signed-in student's own attendance."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        if is_staff(request.member):
            return Response({"detail": "Attendance is tracked for students."}, status=400)
        return Response(student_attendance(request.member, bucket_id=request.query_params.get("bucket_id")))


# ---------------------------------------------------------------------------
# Parent accounts (managed by school staff)
# ---------------------------------------------------------------------------


def _parent_row(profile: ParentProfile) -> dict:
    data = parent_payload(profile)
    data.update(
        {
            "username": profile.user.username,
            "email": profile.user.email,
            "full_name": profile.user.get_full_name() or profile.user.first_name,
            "is_active": profile.is_active,
            "created_at": profile.created_at,
        }
    )
    return data


class ParentListCreateView(APIView):
    """GET parents (staff see parents of their students); POST create a parent login."""

    permission_classes = [CanCreateStudents]

    def get(self, request):
        member = request.member
        qs = ParentProfile.objects.filter(school=member.school).select_related("user")
        if not member.is_manager_or_above:
            students = SchoolMembership.objects.filter(
                bucket_grants__bucket__in=accessible_buckets(member)
            )
            qs = qs.filter(links__student__in=students).distinct()
        if request.query_params.get("student_id"):
            qs = qs.filter(links__student_id=request.query_params["student_id"])
        return Response([_parent_row(p) for p in qs.order_by("user__username")[:500]])

    @extend_schema(request=ParentCreateSerializer)
    def post(self, request):
        ser = ParentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        username = vd["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            return Response({"detail": "That username is already taken."}, status=400)
        email = (vd.get("email") or "").strip().lower()
        students = [_student_visible_to(request.member, sid) for sid in vd["student_ids"]]
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=vd["password"],
                first_name=(vd.get("full_name") or "")[:150],
            )
            profile = ParentProfile.objects.create(
                user=user,
                school=request.member.school,
                phone=vd.get("phone") or "",
                created_by=request.member,
            )
            for s in students:
                ParentLink.objects.get_or_create(
                    parent=profile, student=s, defaults={"relationship": vd["relationship"]}
                )
        return Response(_parent_row(profile), status=status.HTTP_201_CREATED)


class ParentDetailView(APIView):
    permission_classes = [CanCreateStudents]

    def _get(self, request, pk) -> ParentProfile:
        profile = get_object_or_404(
            ParentProfile.objects.select_related("user"), pk=pk, school=request.member.school
        )
        if not request.member.is_manager_or_above:
            for link in profile.links.all():
                _student_visible_to(request.member, link.student_id)
        return profile

    def get(self, request, pk):
        return Response(_parent_row(self._get(request, pk)))

    def patch(self, request, pk):
        profile = self._get(request, pk)
        if "is_active" in request.data:
            profile.is_active = bool(request.data.get("is_active"))
            profile.user.is_active = profile.is_active
            profile.user.save(update_fields=["is_active"])
        if "phone" in request.data:
            profile.phone = str(request.data.get("phone") or "")[:32]
        profile.save()
        return Response(_parent_row(profile))


class ParentLinkView(APIView):
    """POST {student_id, relationship} — link a child to a parent account."""

    permission_classes = [CanCreateStudents]

    @extend_schema(request=ParentLinkSerializer)
    def post(self, request, pk):
        profile = get_object_or_404(ParentProfile, pk=pk, school=request.member.school)
        ser = ParentLinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        student = _student_visible_to(request.member, ser.validated_data["student_id"])
        ParentLink.objects.update_or_create(
            parent=profile, student=student, defaults={"relationship": ser.validated_data["relationship"]}
        )
        return Response(_parent_row(profile), status=status.HTTP_201_CREATED)


class ParentUnlinkView(APIView):
    """DELETE — remove a child from a parent account."""

    permission_classes = [CanCreateStudents]

    def delete(self, request, pk, student_id):
        profile = get_object_or_404(ParentProfile, pk=pk, school=request.member.school)
        _student_visible_to(request.member, student_id)
        ParentLink.objects.filter(parent=profile, student_id=student_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Parent portal (parent accounts only, read-only)
# ---------------------------------------------------------------------------


class IsParent(BasePermission):
    message = "A parent account is required."

    def has_permission(self, request, view):
        profile = parent_profile_for(request.user)
        if profile is None:
            return False
        request.parent_profile = profile
        return True


def _child_for(request, student_id) -> SchoolMembership:
    child = children_of(request.parent_profile).filter(pk=student_id).first()
    if child is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Child not found.")
    return child


class ParentMeView(APIView):
    """GET — parent profile, school, and linked children."""

    permission_classes = [IsParent]

    def get(self, request):
        profile = request.parent_profile
        data = parent_payload(profile)
        data["school"] = {"id": profile.school_id, "name": profile.school.name}
        data["user"] = {
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "full_name": request.user.get_full_name() or request.user.first_name,
        }
        return Response(data)


class ParentPreferencesView(APIView):
    permission_classes = [IsParent]

    def patch(self, request):
        profile = request.parent_profile
        if "weekly_email" in request.data:
            profile.weekly_email = bool(request.data.get("weekly_email"))
            profile.save(update_fields=["weekly_email"])
        return Response(parent_payload(profile))


class ParentChildOverviewView(APIView):
    """GET — child's released results, attendance, streak, subject progress, homework."""

    permission_classes = [IsParent]

    def get(self, request, student_id):
        return Response(child_overview(_child_for(request, student_id)))


class ParentChildAttendanceView(APIView):
    permission_classes = [IsParent]

    def get(self, request, student_id):
        child = _child_for(request, student_id)
        return Response(student_attendance(child, bucket_id=request.query_params.get("bucket_id")))

