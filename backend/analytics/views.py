"""Weak-topic analytics: student reports, class heatmap, remediation practice."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.api_utils import bucket_for, bucket_students, is_staff
from ingestion.models import SchoolMembership
from ingestion.permissions import IsSchoolMember, IsStaffMember
from ingestion.services.llm_errors import LLMProviderError, http_status_for_llm_error
from question_bank.services.bank import BankError

from .services import build_remediation, class_heatmap, class_weak_topics, student_topic_report


class RemediateSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    student_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    question_count = serializers.IntegerField(default=10, min_value=3, max_value=30)


class SelfPracticeSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    question_count = serializers.IntegerField(default=10, min_value=3, max_value=20)


def _optional_bucket(member, request):
    bid = request.query_params.get("bucket_id")
    return bucket_for(member, bid) if bid else None


class MyTopicsView(APIView):
    """GET ?bucket_id — the student's own topic accuracy (released results only)."""

    permission_classes = [IsSchoolMember]

    @extend_schema(parameters=[OpenApiParameter("bucket_id", int)])
    def get(self, request):
        member = request.member
        return Response(
            student_topic_report(member, bucket=_optional_bucket(member, request), visible_only=True)
        )


class StudentTopicsView(APIView):
    """GET ?bucket_id — a student's topic report for teachers."""

    permission_classes = [IsStaffMember]

    def get(self, request, student_id):
        member = request.member
        bucket = _optional_bucket(member, request)
        student = get_object_or_404(
            SchoolMembership, pk=student_id, school=member.school, role=SchoolMembership.ROLE_STUDENT
        )
        if bucket and not bucket_students(bucket).filter(pk=student.id).exists():
            return Response({"detail": "Student is not in this AI Bucket."}, status=404)
        if not member.is_manager_or_above and bucket is None:
            return Response({"detail": "bucket_id is required."}, status=400)
        return Response(student_topic_report(student, bucket=bucket))


class BucketHeatmapView(APIView):
    """GET — students × topics accuracy matrix for one AI Bucket."""

    permission_classes = [IsStaffMember]

    def get(self, request, bucket_id):
        return Response(class_heatmap(bucket_for(request.member, bucket_id)))


class BucketWeakTopicsView(APIView):
    """GET — topics ordered by class accuracy (weakest first)."""

    permission_classes = [IsStaffMember]

    def get(self, request, bucket_id):
        bucket = bucket_for(request.member, bucket_id)
        return Response({"bucket_id": bucket.id, "topics": class_weak_topics(bucket)})


def _remediation_response(fn):
    try:
        return Response(fn(), status=status.HTTP_201_CREATED)
    except BankError as exc:
        return Response({"detail": str(exc)}, status=400)
    except LLMProviderError as exc:
        return Response({"detail": exc.public_message}, status=http_status_for_llm_error(exc))


class RemediateView(APIView):
    """
    POST {bucket_id, student_ids?, topic_ids?, question_count} — build, assign and
    publish a practice test on weak topics (all bucket students if none given).
    """

    permission_classes = [IsStaffMember]

    @extend_schema(request=RemediateSerializer)
    def post(self, request):
        ser = RemediateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        students = bucket_students(bucket)
        if vd["student_ids"]:
            students = students.filter(pk__in=vd["student_ids"])
        students = list(students)
        if not students:
            return Response({"detail": "No students with access to this AI Bucket."}, status=400)
        return _remediation_response(
            lambda: build_remediation(
                request.member,
                bucket,
                students=students,
                topic_ids=vd["topic_ids"] or None,
                question_count=vd["question_count"],
            )
        )


class SelfPracticeView(APIView):
    """POST {bucket_id, topic_ids?} — a student starts practice on their weak topics."""

    permission_classes = [IsSchoolMember]

    @extend_schema(request=SelfPracticeSerializer)
    def post(self, request):
        member = request.member
        if is_staff(member):
            return Response({"detail": "Self practice is for students."}, status=400)
        ser = SelfPracticeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(member, vd["bucket_id"])
        return _remediation_response(
            lambda: build_remediation(
                None,
                bucket,
                students=[member],
                topic_ids=vd["topic_ids"] or None,
                question_count=vd["question_count"],
                self_practice=True,
            )
        )
