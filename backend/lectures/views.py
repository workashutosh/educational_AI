"""Lecture APIs: schedule with Teams meeting, room payload (notes + AI bucket)."""
from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.models import Document, SchoolMembership, SubjectBucket
from ingestion.permissions import IsSchoolMember, get_membership

from .models import Lecture
from .serializers import CreateLectureSerializer, UpdateLectureSerializer
from .services import (
    TeamsGraphError,
    TeamsNotConfigured,
    create_teams_online_meeting,
    teams_configured,
)


def _member(request) -> SchoolMembership:
    return getattr(request, "member", None) or get_membership(request.user)


def _can_manage(member: SchoolMembership, lecture: Lecture) -> bool:
    if member.school_id != lecture.school_id:
        return False
    if member.is_manager_or_above:
        return True
    return lecture.created_by_id == member.id


def _can_view(member: SchoolMembership, lecture: Lecture) -> bool:
    if member.school_id != lecture.school_id:
        return False
    if _can_manage(member, lecture):
        return True
    return member.has_bucket_access(lecture.bucket)


def _lecture_payload(lecture: Lecture, member: SchoolMembership) -> dict:
    return {
        "id": lecture.id,
        "title": lecture.title,
        "description": lecture.description,
        "status": lecture.status,
        "bucket_id": lecture.bucket_id,
        "bucket_name": lecture.bucket.name,
        "starts_at": lecture.starts_at,
        "ends_at": lecture.ends_at,
        "teams_join_url": lecture.teams_join_url,
        "teams_meeting_id": lecture.teams_meeting_id if _can_manage(member, lecture) else "",
        "teams_created": lecture.teams_created,
        "teams_error": lecture.teams_error if _can_manage(member, lecture) else "",
        "teams_organizer_upn": lecture.teams_organizer_upn,
        "created_by": lecture.created_by_id,
        "can_manage": _can_manage(member, lecture),
        "created_at": lecture.created_at,
        "ended_at": lecture.ended_at,
    }


def _room_notes(bucket: SubjectBucket) -> list[dict]:
    docs = (
        Document.objects.filter(
            bucket=bucket,
            kind=Document.KIND_NOTES,
            status=Document.STATUS_INDEXED,
            deleted_at__isnull=True,
        )
        .order_by("-created_at")
        .values("id", "original_filename", "page_count", "byte_size", "created_at")[:40]
    )
    return list(docs)


class TeamsStatusView(APIView):
    """GET /api/lectures/teams/status/ — whether Graph credentials are set."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            return Response({"configured": False})
        return Response(
            {
                "configured": teams_configured(),
                "organizer_configured": bool(
                    getattr(settings, "MS_GRAPH_ORGANIZER_USER_ID", "")
                ),
            }
        )


class LectureListCreateView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        bucket_id = request.query_params.get("bucket_id")
        qs = Lecture.objects.filter(school=member.school).select_related(
            "bucket", "created_by"
        )
        if bucket_id:
            qs = qs.filter(bucket_id=bucket_id)

        if member.role == SchoolMembership.ROLE_STUDENT:
            accessible = SubjectBucket.objects.filter(
                school=member.school,
                access_grants__member=member,
                is_archived=False,
            ).values_list("id", flat=True)
            qs = qs.filter(bucket_id__in=accessible).exclude(
                status=Lecture.STATUS_CANCELLED
            )
        elif not member.is_manager_or_above:
            # Teachers see lectures they created + others in buckets they access
            accessible = SubjectBucket.objects.filter(
                school=member.school,
                access_grants__member=member,
            ).values_list("id", flat=True)
            qs = qs.filter(
                Q(created_by=member) | Q(bucket_id__in=accessible)
            ).distinct()

        return Response([_lecture_payload(l, member) for l in qs[:100]])

    def post(self, request):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            return Response(
                {"detail": "Students cannot create lectures."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = CreateLectureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        bucket = get_object_or_404(
            SubjectBucket, pk=vd["bucket_id"], school=member.school, is_archived=False
        )
        if not member.has_bucket_access(bucket):
            return Response(
                {"detail": "You do not have access to this AI Bucket."},
                status=status.HTTP_403_FORBIDDEN,
            )

        lecture = Lecture(
            school=member.school,
            bucket=bucket,
            created_by=member,
            title=vd["title"].strip(),
            description=(vd.get("description") or "").strip(),
            starts_at=vd["starts_at"],
            ends_at=vd["ends_at"],
            teams_join_url=(vd.get("teams_join_url") or "").strip(),
        )

        want_teams = bool(vd.get("create_teams_meeting", True))
        if want_teams and not lecture.teams_join_url:
            try:
                meeting = create_teams_online_meeting(
                    subject=lecture.title,
                    start=lecture.starts_at,
                    end=lecture.ends_at,
                )
                lecture.teams_meeting_id = meeting.meeting_id
                lecture.teams_join_url = meeting.join_url
                lecture.teams_organizer_upn = meeting.organizer_upn
                lecture.teams_created = True
            except TeamsNotConfigured:
                lecture.teams_error = (
                    "Teams Graph not configured — add a join URL manually, "
                    "or set MS_GRAPH_* env vars."
                )
            except TeamsGraphError as exc:
                lecture.teams_error = str(exc)

        lecture.save()
        return Response(
            _lecture_payload(lecture, member), status=status.HTTP_201_CREATED
        )


class LectureDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(
            Lecture.objects.select_related("bucket"), pk=pk
        )
        if not _can_view(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)
        return Response(_lecture_payload(lecture, member))

    def patch(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(Lecture, pk=pk)
        if not _can_manage(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)
        serializer = UpdateLectureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        fields = []
        for key in ("title", "description", "starts_at", "ends_at", "teams_join_url"):
            if key in vd:
                setattr(lecture, key, vd[key])
                fields.append(key)
        if "status" in vd:
            lecture.status = vd["status"]
            fields.append("status")
            if vd["status"] == Lecture.STATUS_ENDED and not lecture.ended_at:
                lecture.ended_at = timezone.now()
                fields.append("ended_at")
        if not fields:
            return Response({"detail": "No changes."}, status=400)
        lecture.save(update_fields=fields + ["updated_at"])
        return Response(_lecture_payload(lecture, member))


class LectureRoomView(APIView):
    """
    GET /api/lectures/{id}/room/ — payload for the lecture console:
    meeting link, indexed notes for the bucket, AI ask hints.
    """

    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(
            Lecture.objects.select_related("bucket"), pk=pk
        )
        if not _can_view(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)

        data = _lecture_payload(lecture, member)
        data["notes"] = _room_notes(lecture.bucket)
        data["ai"] = {
            "bucket_id": lecture.bucket_id,
            "hint": (
                "Ask the AI about topics in this lecture’s notes. "
                "Students with bucket access can use this during class."
            ),
        }
        return Response(data)


class LectureGoLiveView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(Lecture, pk=pk)
        if not _can_manage(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)
        if lecture.status == Lecture.STATUS_CANCELLED:
            return Response({"detail": "Lecture was cancelled."}, status=400)
        lecture.mark_live()
        return Response(_lecture_payload(lecture, member))


class LectureEndView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(Lecture, pk=pk)
        if not _can_manage(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)
        lecture.mark_ended()
        return Response(_lecture_payload(lecture, member))


class LectureCreateTeamsView(APIView):
    """Retry creating a Teams meeting for an existing lecture."""

    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        lecture = get_object_or_404(Lecture, pk=pk)
        if not _can_manage(member, lecture):
            return Response({"detail": "Forbidden"}, status=403)
        try:
            meeting = create_teams_online_meeting(
                subject=lecture.title,
                start=lecture.starts_at,
                end=lecture.ends_at,
            )
        except TeamsNotConfigured as exc:
            return Response({"detail": str(exc)}, status=400)
        except TeamsGraphError as exc:
            lecture.teams_error = str(exc)
            lecture.save(update_fields=["teams_error", "updated_at"])
            return Response({"detail": str(exc)}, status=502)

        lecture.teams_meeting_id = meeting.meeting_id
        lecture.teams_join_url = meeting.join_url
        lecture.teams_organizer_upn = meeting.organizer_upn
        lecture.teams_created = True
        lecture.teams_error = ""
        lecture.save(
            update_fields=[
                "teams_meeting_id",
                "teams_join_url",
                "teams_organizer_upn",
                "teams_created",
                "teams_error",
                "updated_at",
            ]
        )
        return Response(_lecture_payload(lecture, member))
