"""Engagement APIs: summary, notifications, micro-quizzes, mastery, impact, leaderboards."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from engagement.models import (
    LeaderboardSetting,
    MicroAttempt,
    MicroQuiz,
    Notification,
)
from engagement.services import (
    bucket_investment,
    class_mastery_for_bucket,
    get_or_create_prefs,
    get_streak_payload,
    impact_summary,
    mastery_list_for_member,
    notification_payload,
    submit_micro_attempt,
)
from ingestion.models import SchoolMembership, SubjectBucket
from ingestion.permissions import IsSchoolMember, get_membership
from mock_tests.models import MockAttempt, MockTest


def _member(request) -> SchoolMembership:
    return getattr(request, "member", None) or get_membership(request.user)


def _staff(member: SchoolMembership) -> bool:
    return member.role != SchoolMembership.ROLE_STUDENT


class EngagementSummaryView(APIView):
    """GET /api/engagement/summary/ — dashboard payload."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        unread = Notification.objects.filter(
            recipient=member, read_at__isnull=True
        ).count()
        nudges = [
            notification_payload(n)
            for n in Notification.objects.filter(recipient=member)[:8]
        ]

        if member.role == SchoolMembership.ROLE_STUDENT:
            open_micros = (
                MicroQuiz.objects.filter(
                    bucket__access_grants__member=member,
                    status=MicroQuiz.STATUS_READY,
                    school=member.school,
                )
                .exclude(attempts__student=member)
                .distinct()
                .select_related("bucket")[:6]
            )
            return Response(
                {
                    "role": "student",
                    "streak": get_streak_payload(member),
                    "mastery": mastery_list_for_member(member),
                    "unread_notifications": unread,
                    "nudges": nudges,
                    "open_micro_quizzes": [
                        {
                            "id": q.id,
                            "title": q.title,
                            "bucket_id": q.bucket_id,
                            "bucket_name": q.bucket.name,
                        }
                        for q in open_micros
                    ],
                }
            )

        # Staff
        impact = impact_summary(member, days=30)
        # Pending students across teacher's published tests
        pending_hints = []
        tests = MockTest.objects.filter(
            school=member.school, status=MockTest.STATUS_PUBLISHED
        )
        if member.role == SchoolMembership.ROLE_TEACHER:
            tests = tests.filter(created_by=member)
        for test in tests.select_related("bucket")[:12]:
            assigned = test.assignments.count()
            started = MockAttempt.objects.filter(test=test).count()
            pending = assigned - started
            if pending > 0:
                pending_hints.append(
                    {
                        "test_id": test.id,
                        "title": test.title,
                        "pending": pending,
                        "link_path": f"/app/mock-tests/{test.id}",
                    }
                )

        investments = []
        buckets = SubjectBucket.objects.filter(
            school=member.school, is_archived=False
        )
        if not member.is_manager_or_above:
            buckets = buckets.filter(access_grants__member=member).distinct()
        for b in buckets[:8]:
            investments.append(bucket_investment(b))

        return Response(
            {
                "role": member.role,
                "impact": impact,
                "unread_notifications": unread,
                "nudges": nudges,
                "pending_tests": pending_hints[:5],
                "bucket_investments": investments,
            }
        )


class NotificationListView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        qs = Notification.objects.filter(recipient=member)[:50]
        return Response([notification_payload(n) for n in qs])


class NotificationReadView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        n = get_object_or_404(Notification, pk=pk, recipient=member)
        n.mark_read()
        return Response(notification_payload(n))


class NotificationReadAllView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request):
        member = _member(request)
        Notification.objects.filter(recipient=member, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"ok": True})


class PreferenceView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        prefs = get_or_create_prefs(_member(request))
        return Response(
            {
                "email_digests": prefs.email_digests,
                "leaderboard_visible": prefs.leaderboard_visible,
            }
        )

    def patch(self, request):
        prefs = get_or_create_prefs(_member(request))
        if "email_digests" in request.data:
            prefs.email_digests = bool(request.data.get("email_digests"))
        if "leaderboard_visible" in request.data:
            prefs.leaderboard_visible = bool(request.data.get("leaderboard_visible"))
        prefs.save()
        return Response(
            {
                "email_digests": prefs.email_digests,
                "leaderboard_visible": prefs.leaderboard_visible,
            }
        )


class MicroQuizListView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        qs = MicroQuiz.objects.filter(
            school=member.school, status=MicroQuiz.STATUS_READY
        ).select_related("bucket")
        if member.role == SchoolMembership.ROLE_STUDENT:
            qs = qs.filter(bucket__access_grants__member=member).distinct()
        else:
            if not member.is_manager_or_above:
                qs = qs.filter(bucket__access_grants__member=member).distinct()
        rows = []
        for q in qs[:40]:
            mine = None
            if member.role == SchoolMembership.ROLE_STUDENT:
                att = MicroAttempt.objects.filter(quiz=q, student=member).first()
                if att:
                    mine = {
                        "score": att.score,
                        "max_score": att.max_score,
                        "submitted_at": att.submitted_at,
                    }
            rows.append(
                {
                    "id": q.id,
                    "title": q.title,
                    "bucket_id": q.bucket_id,
                    "bucket_name": q.bucket.name,
                    "source_type": q.source_type,
                    "my_attempt": mine,
                }
            )
        return Response(rows)


class MicroQuizDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        quiz = get_object_or_404(
            MicroQuiz.objects.select_related("bucket"),
            pk=pk,
            school=member.school,
        )
        if not member.has_bucket_access(quiz.bucket):
            return Response({"detail": "Forbidden"}, status=403)
        attempt = None
        if member.role == SchoolMembership.ROLE_STUDENT:
            attempt = MicroAttempt.objects.filter(quiz=quiz, student=member).first()
        questions = []
        for q in quiz.questions.all():
            item = {
                "id": q.id,
                "order": q.order,
                "prompt": q.prompt,
                "options": q.options,
            }
            if attempt or _staff(member):
                item["correct_index"] = q.correct_index
            questions.append(item)
        return Response(
            {
                "id": quiz.id,
                "title": quiz.title,
                "bucket_id": quiz.bucket_id,
                "bucket_name": quiz.bucket.name,
                "status": quiz.status,
                "questions": questions,
                "my_attempt": (
                    {
                        "score": attempt.score,
                        "max_score": attempt.max_score,
                        "answers": attempt.answers,
                        "submitted_at": attempt.submitted_at,
                    }
                    if attempt
                    else None
                ),
            }
        )


class MicroQuizSubmitView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        if member.role != SchoolMembership.ROLE_STUDENT:
            return Response({"detail": "Students only."}, status=403)
        quiz = get_object_or_404(MicroQuiz, pk=pk, school=member.school)
        if not member.has_bucket_access(quiz.bucket):
            return Response({"detail": "Forbidden"}, status=403)
        answers = request.data.get("answers") or {}
        try:
            attempt = submit_micro_attempt(
                quiz=quiz, student=member, answers=answers
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            {
                "score": attempt.score,
                "max_score": attempt.max_score,
                "answers": attempt.answers,
                "streak": get_streak_payload(member),
                "message": f"Nice work — {attempt.score}/{attempt.max_score}. Streak updated.",
            }
        )


class MasteryListView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        bucket_id = request.query_params.get("bucket_id")
        if bucket_id and _staff(member):
            bucket = get_object_or_404(
                SubjectBucket, pk=bucket_id, school=member.school
            )
            return Response(
                {
                    "bucket_id": bucket.id,
                    "class_mastery": class_mastery_for_bucket(bucket),
                }
            )
        return Response({"mastery": mastery_list_for_member(member)})


class ImpactView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            return Response({"detail": "Staff only."}, status=403)
        return Response(impact_summary(member, days=30))


class BucketInvestmentView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, bucket_id):
        member = _member(request)
        bucket = get_object_or_404(
            SubjectBucket, pk=bucket_id, school=member.school
        )
        if not member.has_bucket_access(bucket):
            return Response({"detail": "Forbidden"}, status=403)
        return Response(bucket_investment(bucket))


class LeaderboardSettingsView(APIView):
    permission_classes = [IsSchoolMember]

    def patch(self, request, pk):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            return Response({"detail": "Forbidden"}, status=403)
        test = get_object_or_404(MockTest, pk=pk, school=member.school)
        if member.role == SchoolMembership.ROLE_TEACHER and test.created_by_id != member.id:
            if not member.is_manager_or_above:
                return Response({"detail": "Forbidden"}, status=403)
        enabled = bool(request.data.get("enabled"))
        setting, _ = LeaderboardSetting.objects.update_or_create(
            mock_test=test,
            defaults={"enabled": enabled, "updated_by": member},
        )
        return Response({"test_id": test.id, "enabled": setting.enabled})


class LeaderboardView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk, school=member.school)
        try:
            setting = test.leaderboard_setting
            enabled = bool(setting.enabled)
        except LeaderboardSetting.DoesNotExist:
            enabled = False

        if _staff(member):
            rows = _leaderboard_rows(test, reveal_names=True)
            return Response(
                {"enabled": enabled, "entries": rows, "viewer": "staff"}
            )

        if not enabled:
            return Response(
                {
                    "enabled": False,
                    "entries": [],
                    "message": "Leaderboard is off for this test.",
                }
            )

        prefs = get_or_create_prefs(member)
        rows = _leaderboard_rows(test, reveal_names=False)
        # Annotate self
        my_rank = None
        for i, r in enumerate(rows, start=1):
            if r.get("member_id") == member.id:
                my_rank = i
                r["is_you"] = True
                if prefs.leaderboard_visible:
                    r["display_name"] = (
                        member.user.get_full_name() or member.user.username
                    )
                else:
                    r["display_name"] = "You"
            else:
                r["display_name"] = f"Student #{i}" if not prefs.leaderboard_visible else r.get("display_name", f"#{i}")
                # Privacy: never show other real names to students in v1
                r["display_name"] = f"#{i}"
                r.pop("member_id", None)

        return Response(
            {
                "enabled": True,
                "entries": rows,
                "my_rank": my_rank,
                "viewer": "student",
            }
        )


def _leaderboard_rows(test: MockTest, *, reveal_names: bool) -> list[dict]:
    attempts = (
        MockAttempt.objects.filter(
            test=test,
            submitted_at__isnull=False,
            results_released_at__isnull=False,
        )
        .select_related("student__user")
        .order_by("-percent", "submitted_at")
    )
    rows = []
    for a in attempts:
        name = a.student.user.get_full_name() or a.student.user.username
        rows.append(
            {
                "member_id": a.student_id,
                "display_name": name if reveal_names else "",
                "percent": a.percent,
                "score": a.score,
                "max_score": a.max_score,
            }
        )
    return rows
