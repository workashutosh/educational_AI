"""Homework APIs: teachers create/assign/grade; students submit and see returned work."""
from __future__ import annotations

import logging
import mimetypes

from django.db.models import Count, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.api_utils import accessible_buckets, bucket_for, display_name, int_list, is_staff
from ingestion.models import SchoolMembership
from ingestion.permissions import IsSchoolMember, IsStaffMember

from .models import Assignment, AssignmentTarget, Submission
from .serializers import AssignmentWriteSerializer, AssignSerializer, GradeSerializer
from .services import (
    HomeworkError,
    assign_students,
    grade,
    publish,
    release_submission,
    student_status,
    submit,
)

logger = logging.getLogger(__name__)


def _can_manage(member: SchoolMembership, a: Assignment) -> bool:
    if member.school_id != a.school_id or not is_staff(member):
        return False
    return member.is_manager_or_above or a.created_by_id == member.id or member.has_bucket_access(a.bucket)


def _assignment_for(member, pk, *, manage: bool = False) -> Assignment:
    a = get_object_or_404(Assignment.objects.select_related("bucket", "created_by__user"), pk=pk, school=member.school)
    if manage or is_staff(member):
        if not _can_manage(member, a):
            raise PermissionDenied("You cannot manage this homework.")
        return a
    if a.status == Assignment.STATUS_DRAFT or not a.targets.filter(student=member).exists():
        raise PermissionDenied("This homework is not assigned to you.")
    return a


def _file_payload(f, sub_id) -> dict:
    return {
        "id": f.id,
        "name": f.original_filename,
        "content_type": f.content_type,
        "byte_size": f.byte_size,
        "url": f"/api/homework/submissions/{sub_id}/files/{f.id}/",
    }


def _submission_payload(sub: Submission, *, for_staff: bool) -> dict:
    visible = for_staff or sub.student_can_see_result()
    data = {
        "id": sub.id,
        "assignment_id": sub.assignment_id,
        "student_id": sub.student_id,
        "student_name": display_name(sub.student),
        "text_answer": sub.text_answer,
        "files": [_file_payload(f, sub.id) for f in sub.files.all()],
        "status": sub.status,
        "is_late": sub.is_late,
        "submitted_at": sub.submitted_at,
        "released": bool(sub.released_at),
        "released_at": sub.released_at,
        "ai_status": sub.ai_status,
        "ai_score": sub.ai_score if visible else None,
        "ai_feedback": sub.ai_feedback if visible else "",
        "teacher_score": sub.teacher_score if (for_staff or sub.released_at) else None,
        "teacher_feedback": sub.teacher_feedback if (for_staff or sub.released_at) else "",
        "max_marks": sub.assignment.max_marks,
    }
    if for_staff:
        data["extracted_text"] = sub.extracted_text
        data["graded_at"] = sub.graded_at
    return data


def _assignment_payload(a: Assignment, member: SchoolMembership, *, detail: bool = False) -> dict:
    data = {
        "id": a.id,
        "bucket_id": a.bucket_id,
        "bucket_name": a.bucket.name,
        "title": a.title,
        "instructions": a.instructions,
        "due_at": a.due_at,
        "is_overdue": a.is_overdue,
        "max_marks": a.max_marks,
        "allow_late": a.allow_late,
        "ai_grading": a.ai_grading,
        "results_mode": a.results_mode,
        "status": a.status,
        "attachment_url": f"/api/homework/{a.id}/attachment/" if a.attachment else None,
        "attachment_name": a.attachment_name,
        "created_by_name": display_name(a.created_by) if a.created_by_id else "",
        "created_at": a.created_at,
        "published_at": a.published_at,
        "can_manage": _can_manage(member, a),
    }
    if is_staff(member):
        data["assigned_count"] = getattr(a, "assigned_count", None) or a.targets.count()
        data["submitted_count"] = getattr(a, "submitted_count", None) or a.submissions.count()
        if detail:
            data["rubric"] = a.rubric
            data["model_answer"] = a.model_answer
    else:
        sub = a.submissions.filter(student=member).prefetch_related("files").first()
        data["my_status"] = student_status(a, sub)
        if detail:
            data["my_submission"] = _submission_payload(sub, for_staff=False) if sub else None
    return data


def _queue_grading(sub: Submission) -> None:
    from .tasks import grade_submission, grade_submission_task

    try:
        grade_submission_task.delay(sub.id)
    except Exception:
        logger.warning("Celery unavailable; grading inline sub=%s", sub.id)
        grade_submission(sub.id)


class AssignmentListCreateView(APIView):
    """GET — staff: homework in their buckets; students: assigned homework. POST (staff) create."""

    permission_classes = [IsSchoolMember]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        member = request.member
        qs = Assignment.objects.filter(school=member.school).select_related("bucket", "created_by__user")
        if is_staff(member):
            qs = qs.filter(bucket__in=accessible_buckets(member)).annotate(
                assigned_count=Count("targets", distinct=True),
                submitted_count=Count("submissions", distinct=True),
            )
            if request.query_params.get("status"):
                qs = qs.filter(status=request.query_params["status"])
        else:
            qs = qs.filter(targets__student=member, status__in=["published", "closed"])
        if request.query_params.get("bucket_id"):
            qs = qs.filter(bucket_id=request.query_params["bucket_id"])
        return Response([_assignment_payload(a, member) for a in qs.order_by("-created_at")[:200]])

    @extend_schema(request=AssignmentWriteSerializer)
    def post(self, request):
        member = request.member
        if not is_staff(member):
            return Response({"detail": "Students cannot create homework."}, status=403)
        data = request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
        if "student_ids" in data:
            data["student_ids"] = int_list(request.data.getlist("student_ids") if hasattr(request.data, "getlist") else data["student_ids"])
        ser = AssignmentWriteSerializer(data=data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        if not vd.get("bucket_id") or not vd.get("title"):
            return Response({"detail": "bucket_id and title are required."}, status=400)
        bucket = bucket_for(member, vd["bucket_id"])
        a = Assignment.objects.create(
            school=member.school,
            bucket=bucket,
            created_by=member,
            title=vd["title"].strip(),
            instructions=vd.get("instructions") or "",
            due_at=vd.get("due_at"),
            max_marks=vd.get("max_marks") or 10,
            rubric=vd.get("rubric") or "",
            model_answer=vd.get("model_answer") or "",
            allow_late=vd.get("allow_late", True),
            ai_grading=vd.get("ai_grading", True),
            results_mode=vd.get("results_mode") or Assignment.RESULTS_AFTER_REVIEW,
        )
        upload = request.FILES.get("attachment")
        if upload:
            a.attachment = upload
            a.attachment_name = upload.name[:500]
            a.save(update_fields=["attachment", "attachment_name"])
        assign_students(a, student_ids=vd.get("student_ids"), assign_all=vd.get("assign_all", False))
        if vd.get("publish"):
            try:
                publish(a)
            except HomeworkError as exc:
                return Response({"detail": str(exc), "id": a.id}, status=400)
        return Response(_assignment_payload(a, member, detail=True), status=status.HTTP_201_CREATED)


class AssignmentDetailView(APIView):
    permission_classes = [IsSchoolMember]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, pk):
        a = _assignment_for(request.member, pk)
        return Response(_assignment_payload(a, request.member, detail=True))

    @extend_schema(request=AssignmentWriteSerializer)
    def patch(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        ser = AssignmentWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        for field in (
            "title",
            "instructions",
            "due_at",
            "max_marks",
            "rubric",
            "model_answer",
            "allow_late",
            "ai_grading",
            "results_mode",
        ):
            if field in ser.validated_data:
                setattr(a, field, ser.validated_data[field])
        upload = request.FILES.get("attachment")
        if upload:
            a.attachment = upload
            a.attachment_name = upload.name[:500]
        a.save()
        return Response(_assignment_payload(a, request.member, detail=True))

    def delete(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        if a.submissions.exists() and a.status != Assignment.STATUS_DRAFT:
            a.status = Assignment.STATUS_CLOSED
            a.closed_at = timezone.now()
            a.save(update_fields=["status", "closed_at"])
            return Response({"detail": "Homework has submissions, so it was closed instead."})
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentAttachmentView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        a = _assignment_for(request.member, pk)
        if not a.attachment:
            return Response({"detail": "No attachment."}, status=404)
        ctype = mimetypes.guess_type(a.attachment.name)[0] or "application/octet-stream"
        response = FileResponse(a.attachment.open("rb"), content_type=ctype)
        response["Content-Disposition"] = f'inline; filename="{a.attachment_name or "attachment"}"'
        return response


class AssignmentAssignView(APIView):
    permission_classes = [IsStaffMember]

    @extend_schema(request=AssignSerializer)
    def post(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        ser = AssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        added = assign_students(a, student_ids=ser.validated_data["student_ids"], assign_all=ser.validated_data["assign_all"])
        if added and a.status == Assignment.STATUS_PUBLISHED:
            publish(a)  # notifies newly added students (deduped for existing)
        return Response({"added": added, "assigned_count": a.targets.count()})

    def delete(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        ids = int_list(request.query_params.get("student_ids"))
        removed, _ = AssignmentTarget.objects.filter(assignment=a, student_id__in=ids).exclude(
            student__homework_submissions__assignment=a
        ).delete()
        return Response({"removed": removed})


class AssignmentPublishView(APIView):
    permission_classes = [IsStaffMember]

    def post(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        try:
            publish(a)
        except HomeworkError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(_assignment_payload(a, request.member, detail=True))


class AssignmentCloseView(APIView):
    permission_classes = [IsStaffMember]

    def post(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        a.status = Assignment.STATUS_CLOSED
        a.closed_at = timezone.now()
        a.save(update_fields=["status", "closed_at"])
        return Response(_assignment_payload(a, request.member, detail=True))


class AssignmentSubmitView(APIView):
    """POST multipart {text_answer, files[]} — student submits (resubmits until returned)."""

    permission_classes = [IsSchoolMember]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        member = request.member
        if is_staff(member):
            return Response({"detail": "Only students submit homework."}, status=403)
        a = _assignment_for(member, pk)
        uploads = request.FILES.getlist("files") or request.FILES.getlist("file")
        try:
            sub = submit(a, member, text=request.data.get("text_answer") or "", uploads=uploads)
        except HomeworkError as exc:
            return Response({"detail": str(exc)}, status=400)
        _queue_grading(sub)
        try:
            from engagement.services.notifications import create_notification

            if a.created_by_id:
                create_notification(
                    recipient=a.created_by,
                    kind="generic",
                    title=f"Homework submitted: {a.title}",
                    body=display_name(member),
                    link_path=f"/app/homework/{a.id}",
                    payload={"assignment_id": a.id, "type": "homework_submitted"},
                    dedupe_key=f"hw-sub:{a.id}",
                )
        except Exception:
            pass
        sub.refresh_from_db()
        return Response(_submission_payload(sub, for_staff=False), status=status.HTTP_201_CREATED)


class AssignmentSubmissionsView(APIView):
    """GET — roster: every assigned student with submission + grading state."""

    permission_classes = [IsStaffMember]

    def get(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        subs = {
            s.student_id: s
            for s in a.submissions.select_related("student__user", "assignment").prefetch_related("files")
        }
        rows = []
        for t in a.targets.select_related("student__user"):
            sub = subs.get(t.student_id)
            rows.append(
                {
                    "student_id": t.student_id,
                    "student_name": display_name(t.student),
                    "status": student_status(a, sub),
                    "submission": _submission_payload(sub, for_staff=True) if sub else None,
                }
            )
        rows.sort(key=lambda r: r["student_name"].lower())
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return Response({"assignment_id": a.id, "counts": counts, "students": rows})


class AssignmentReleaseView(APIView):
    """POST — return every graded (or AI-graded) submission to students."""

    permission_classes = [IsStaffMember]

    def post(self, request, pk):
        a = _assignment_for(request.member, pk, manage=True)
        released = 0
        for sub in a.submissions.filter(released_at__isnull=True).filter(
            Q(teacher_score__isnull=False) | Q(ai_score__isnull=False)
        ).select_related("student__school", "assignment"):
            release_submission(sub)
            released += 1
        return Response({"released": released})


def _submission_for(member, sid) -> Submission:
    sub = get_object_or_404(
        Submission.objects.select_related("assignment__bucket", "student__user").prefetch_related("files"),
        pk=sid,
        assignment__school=member.school,
    )
    if is_staff(member):
        if not _can_manage(member, sub.assignment):
            raise PermissionDenied("You cannot see this submission.")
    elif sub.student_id != member.id:
        raise PermissionDenied("Not your submission.")
    return sub


class SubmissionDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, sid):
        sub = _submission_for(request.member, sid)
        return Response(_submission_payload(sub, for_staff=is_staff(request.member)))


class SubmissionGradeView(APIView):
    """POST {score, feedback, release} — teacher's final mark (overrides AI)."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=GradeSerializer)
    def post(self, request, sid):
        sub = _submission_for(request.member, sid)
        ser = GradeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            grade(
                sub,
                request.member,
                score=ser.validated_data["score"],
                feedback=ser.validated_data["feedback"],
                release=ser.validated_data["release"],
            )
        except HomeworkError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(_submission_payload(sub, for_staff=True))


class SubmissionRegradeView(APIView):
    """POST — re-run OCR + AI grading."""

    permission_classes = [IsStaffMember]

    def post(self, request, sid):
        sub = _submission_for(request.member, sid)
        sub.extracted_text = ""
        sub.ai_status = Submission.AI_PENDING
        sub.save(update_fields=["extracted_text", "ai_status"])
        _queue_grading(sub)
        sub.refresh_from_db()
        return Response(_submission_payload(sub, for_staff=True))


class SubmissionFileView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, sid, fid):
        sub = _submission_for(request.member, sid)
        f = get_object_or_404(sub.files, pk=fid)
        ctype = f.content_type or mimetypes.guess_type(f.original_filename)[0] or "application/octet-stream"
        response = FileResponse(f.file.open("rb"), content_type=ctype)
        response["Content-Disposition"] = f'inline; filename="{f.original_filename}"'
        return response
