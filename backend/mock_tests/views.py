"""
Mock test APIs: blueprint generate, assign, publish, take, score, brief confirm.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.models import SchoolMembership, SubjectBucket
from ingestion.permissions import IsSchoolMember, get_membership

from .models import MockAnswerGrade, MockAssignment, MockAttempt, MockQuestion, MockTest
from .serializers import (
    AssignStudentsSerializer,
    ConfirmBriefGradeSerializer,
    GenerateMockTestSerializer,
    MockTestUpdateSerializer,
    QuestionUpdateSerializer,
    RegenerateMockTestSerializer,
    ReleaseResultsSerializer,
    SubmitAnswersSerializer,
)
from .services import (
    MockTestGenerationError,
    apply_draft_settings,
    build_review,
    generate_mock_test,
    regenerate_questions,
    release_attempt_with_email,
    submit_and_grade,
)

# Grace period after ends_at before rejecting late submits
logger = logging.getLogger(__name__)
_SUBMIT_GRACE = timedelta(seconds=30)


def _member(request) -> SchoolMembership:
    return getattr(request, "member", None) or get_membership(request.user)


def _can_manage_test(member: SchoolMembership, test: MockTest) -> bool:
    if member.school_id != test.school_id:
        return False
    if member.is_manager_or_above:
        return True
    return test.created_by_id == member.id


def _is_assigned(member: SchoolMembership, test: MockTest) -> bool:
    return MockAssignment.objects.filter(test=test, student=member).exists()


def _queue_bank_sync(test_id: int) -> None:
    """Copy generated questions into the question bank and tag their topics."""
    try:
        from question_bank.tasks import sync_mock_test_task

        sync_mock_test_task.delay(test_id)
    except Exception:
        logger.exception("Could not queue question-bank sync for mock %s", test_id)


def _question_payload(q: MockQuestion, *, reveal_correct: bool) -> dict:
    data = {
        "id": q.id,
        "order": q.order,
        "qtype": q.qtype,
        "prompt": q.prompt,
        "options": q.options,
        "marks": q.marks,
    }
    if reveal_correct:
        data["topic_id"] = q.topic_id
        data["topic_name"] = q.topic.name if q.topic_id else None
    if reveal_correct:
        data["correct_indices"] = q.correct_indices
        if q.qtype == MockQuestion.TYPE_BRIEF:
            data["model_answer"] = q.model_answer
        # back-compat for older UI
        if q.qtype == MockQuestion.TYPE_MCQ and q.correct_indices:
            data["correct_index"] = q.correct_indices[0]
    return data


def _blueprint_fields(test: MockTest) -> dict:
    return {
        "duration_minutes": test.duration_minutes,
        "count_mcq": test.count_mcq,
        "count_multi": test.count_multi,
        "count_brief": test.count_brief,
        "marks_mcq": test.marks_mcq,
        "marks_multi": test.marks_multi,
        "marks_brief": test.marks_brief,
        "max_score": test.computed_max_score() or test.blueprint_max_score,
        "results_mode": test.results_mode,
        "source_mode": test.source_mode,
        "reference_document_ids": test.reference_document_ids or [],
    }


def _student_attempt_payload(attempt: MockAttempt) -> dict:
    """Score/review only when teacher has released (or immediate mode)."""
    can_see = attempt.student_can_see_results()
    base = {
        "started_at": attempt.started_at,
        "ends_at": attempt.ends_at,
        "submitted_at": attempt.submitted_at,
        "auto_submitted": attempt.auto_submitted,
        "results_released": can_see,
        "results_mode": attempt.test.results_mode,
        "awaiting_teacher_review": attempt.is_submitted and not can_see,
        "answers": attempt.answers if not attempt.is_submitted else attempt.answers,
    }
    if not attempt.is_submitted:
        return {
            **base,
            "score": None,
            "max_score": None,
            "percent": None,
            "objective_score": None,
            "brief_pending_count": None,
            "grading_status": None,
            "review": None,
        }
    if not can_see:
        return {
            **base,
            "score": None,
            "max_score": None,
            "percent": None,
            "objective_score": None,
            "brief_pending_count": None,
            "grading_status": None,
            "review": None,
        }
    return {
        **base,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "percent": attempt.percent,
        "objective_score": attempt.objective_score,
        "brief_pending_count": attempt.brief_pending_count,
        "grading_status": attempt.grading_status,
        "review": build_review(attempt),
    }


def _test_list_item(test: MockTest, member: SchoolMembership) -> dict:
    assigned = test.assignments.count()
    submitted = test.attempts.filter(submitted_at__isnull=False).count()
    item = {
        "id": test.id,
        "title": test.title,
        "status": test.status,
        "bucket_id": test.bucket_id,
        "bucket_name": test.bucket.name,
        "question_count": test.question_count,
        "topic_prompt": test.topic_prompt,
        "created_at": test.created_at,
        "published_at": test.published_at,
        "assigned_count": assigned,
        "submitted_count": submitted,
        **_blueprint_fields(test),
    }
    if member.role == SchoolMembership.ROLE_STUDENT:
        attempt = MockAttempt.objects.filter(test=test, student=member).first()
        if attempt and attempt.is_submitted:
            my_status = "submitted"
        elif attempt:
            my_status = "in_progress"
        else:
            my_status = "not_started"
        can_see = bool(attempt and attempt.student_can_see_results())
        item["my_status"] = my_status
        item["my_results_released"] = can_see
        item["my_awaiting_review"] = bool(
            attempt and attempt.is_submitted and not can_see
        )
        item["my_percent"] = attempt.percent if can_see else None
        item["my_score"] = attempt.score if can_see else None
        item["my_max_score"] = attempt.max_score if can_see else None
        item["my_grading_status"] = attempt.grading_status if can_see else None
        item["ends_at"] = attempt.ends_at if attempt else None
    return item


def _test_detail(test: MockTest, member: SchoolMembership) -> dict:
    is_manager = _can_manage_test(member, test)
    is_student = member.role == SchoolMembership.ROLE_STUDENT
    attempt = None
    if is_student:
        attempt = MockAttempt.objects.filter(test=test, student=member).first()
    # Hide correct answers from students until results are released
    reveal = is_manager or (
        attempt is not None and attempt.student_can_see_results()
    )

    data = {
        "id": test.id,
        "title": test.title,
        "status": test.status,
        "bucket_id": test.bucket_id,
        "bucket_name": test.bucket.name,
        "topic_prompt": test.topic_prompt,
        "question_count": test.question_count,
        "created_at": test.created_at,
        "published_at": test.published_at,
        "closed_at": test.closed_at,
        "assigned_count": test.assignments.count(),
        "submitted_count": test.attempts.filter(submitted_at__isnull=False).count(),
        "questions": [
            _question_payload(q, reveal_correct=reveal) for q in test.questions.all()
        ],
        "can_manage": is_manager,
        **_blueprint_fields(test),
    }
    if is_manager:
        data["assignments"] = [
            {
                "student_id": a.student_id,
                "username": a.student.user.username,
                "full_name": a.student.user.first_name or "",
                "assigned_at": a.assigned_at,
            }
            for a in test.assignments.select_related("student__user")
        ]
        released_n = test.attempts.filter(
            submitted_at__isnull=False, results_released_at__isnull=False
        ).count()
        data["results_released_count"] = released_n
    if is_student and attempt:
        data["my_attempt"] = _student_attempt_payload(attempt)
    elif is_student:
        data["my_attempt"] = None
    return data


def _roster_status(att: MockAttempt | None) -> str:
    if not att:
        return "not_started"
    if not att.is_submitted:
        return "in_progress"
    if not att.student_can_see_results() and att.test.results_mode == MockTest.RESULTS_AFTER_REVIEW:
        if att.brief_pending_count > 0:
            return "grading"
        return "ready_to_release"
    if att.brief_pending_count > 0:
        return "grading"
    return "final"


class MockTestListCreateView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            test_ids = MockAssignment.objects.filter(student=member).values_list(
                "test_id", flat=True
            )
            qs = MockTest.objects.filter(
                id__in=test_ids,
                status__in=[MockTest.STATUS_PUBLISHED, MockTest.STATUS_CLOSED],
            ).select_related("bucket")
        elif member.is_manager_or_above:
            qs = MockTest.objects.filter(school=member.school).select_related("bucket")
        else:
            qs = MockTest.objects.filter(
                school=member.school, created_by=member
            ).select_related("bucket")

        return Response([_test_list_item(t, member) for t in qs[:100]])

    def post(self, request):
        member = _member(request)
        if member.role == SchoolMembership.ROLE_STUDENT:
            return Response(
                {"detail": "Students cannot create mock tests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = GenerateMockTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        try:
            test = generate_mock_test(
                member,
                bucket_id=vd["bucket_id"],
                prompt=vd["prompt"],
                title=vd.get("title") or "",
                duration_minutes=vd.get("duration_minutes", 60),
                count_mcq=vd.get("count_mcq", 0),
                count_multi=vd.get("count_multi", 0),
                count_brief=vd.get("count_brief", 0),
                marks_mcq=vd.get("marks_mcq", 1),
                marks_multi=vd.get("marks_multi", 2),
                marks_brief=vd.get("marks_brief", 5),
                results_mode=vd.get("results_mode") or MockTest.RESULTS_AFTER_REVIEW,
                source_mode=vd.get("source_mode") or MockTest.SOURCE_NOTES,
                reference_document_ids=vd.get("reference_document_ids") or None,
            )
        except DjangoPermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except SubjectBucket.DoesNotExist:
            return Response({"detail": "AI Bucket not found."}, status=404)
        except MockTestGenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        test = MockTest.objects.select_related("bucket").get(pk=test.pk)
        _queue_bank_sync(test.id)
        try:
            from engagement.models import TeacherImpactEvent
            from engagement.services.impact import record_impact

            record_impact(
                member=member,
                kind=TeacherImpactEvent.KIND_MOCK_GENERATE,
                ref_id=f"mock:{test.id}",
            )
        except Exception:
            pass
        return Response(
            _test_detail(test, member),
            status=status.HTTP_201_CREATED,
        )


class MockTestDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        test = get_object_or_404(
            MockTest.objects.select_related("bucket", "school"), pk=pk
        )
        if not _can_manage_test(member, test) and not _is_assigned(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if (
            member.role == SchoolMembership.ROLE_STUDENT
            and test.status == MockTest.STATUS_DRAFT
        ):
            return Response({"detail": "Test is not published yet."}, status=403)
        return Response(_test_detail(test, member))

    def patch(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        serializer = MockTestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        if not vd:
            return Response({"detail": "No changes."}, status=400)

        # results_mode may change even after publish; everything else is draft-only
        if test.status != MockTest.STATUS_DRAFT:
            if set(vd.keys()) - {"results_mode"}:
                return Response(
                    {"detail": "Only results mode can be changed after publish."},
                    status=400,
                )
            test.results_mode = vd["results_mode"]
            test.save(update_fields=["results_mode"])
            return Response(_test_detail(test, member))

        try:
            fields = apply_draft_settings(test, vd)
        except MockTestGenerationError as exc:
            return Response({"detail": str(exc)}, status=400)
        if not fields:
            return Response({"detail": "No changes."}, status=400)
        test.save(update_fields=fields)
        return Response(_test_detail(test, member))


class MockQuestionDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def patch(self, request, pk, qid):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if test.status != MockTest.STATUS_DRAFT:
            return Response({"detail": "Only draft questions can be edited."}, status=400)
        question = get_object_or_404(MockQuestion, pk=qid, test=test)
        serializer = QuestionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        if "prompt" in vd:
            question.prompt = vd["prompt"].strip()
        if "options" in vd:
            question.options = [str(o).strip() for o in vd["options"] if str(o).strip()]
        if "correct_indices" in vd:
            question.correct_indices = list(vd["correct_indices"])
        if "model_answer" in vd:
            question.model_answer = vd["model_answer"].strip()
        if "marks" in vd:
            question.marks = vd["marks"]
        if "order" in vd:
            question.order = vd["order"]
        question.save()
        test.question_count = test.questions.count()
        test.save(update_fields=["question_count"])
        return Response(_question_payload(question, reveal_correct=True))

    def delete(self, request, pk, qid):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if test.status != MockTest.STATUS_DRAFT:
            return Response({"detail": "Only draft questions can be removed."}, status=400)
        question = get_object_or_404(MockQuestion, pk=qid, test=test)
        question.delete()
        # re-number
        for i, q in enumerate(test.questions.order_by("order", "id"), start=1):
            if q.order != i:
                q.order = i
                q.save(update_fields=["order"])
        test.question_count = test.questions.count()
        test.save(update_fields=["question_count"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MockTestRegenerateView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        serializer = RegenerateMockTestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        try:
            regenerate_questions(test, member, overrides=serializer.validated_data or None)
        except DjangoPermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except MockTestGenerationError as exc:
            return Response({"detail": str(exc)}, status=400)
        test = MockTest.objects.select_related("bucket").get(pk=pk)
        _queue_bank_sync(test.id)
        return Response(_test_detail(test, member))


class MockTestAssignView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        serializer = AssignStudentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["student_ids"]
        should_publish = bool(serializer.validated_data.get("publish", True))
        students = SchoolMembership.objects.filter(
            id__in=ids,
            school=test.school,
            role=SchoolMembership.ROLE_STUDENT,
            is_active=True,
        )
        created = 0
        for s in students:
            _, was_created = MockAssignment.objects.get_or_create(
                test=test, student=s, defaults={"assigned_by": member}
            )
            if was_created:
                created += 1
                try:
                    from engagement.services.notifications import create_notification

                    create_notification(
                        recipient=s,
                        kind="test_assigned",
                        title=f"New test: {test.title}",
                        body="A mock test was assigned to you.",
                        link_path=f"/app/mock-tests/{test.id}",
                        dedupe_key=f"assign:{test.id}:{s.id}",
                    )
                except Exception:
                    pass

        published = False
        if should_publish and test.status == MockTest.STATUS_DRAFT:
            if test.questions.count() < 1:
                return Response(
                    {"detail": "Add questions before publishing."},
                    status=400,
                )
            if test.assignments.count() < 1:
                return Response(
                    {"detail": "Assign at least one student before publishing."},
                    status=400,
                )
            if not test.duration_minutes:
                return Response(
                    {"detail": "Set a duration before publishing."},
                    status=400,
                )
            test.mark_published()
            published = True

        return Response(
            {
                "assigned_count": test.assignments.count(),
                "newly_assigned": created,
                "published": published,
                "status": test.status,
            }
        )


class MockTestUnassignView(APIView):
    permission_classes = [IsSchoolMember]

    def delete(self, request, pk, student_id):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if MockAttempt.objects.filter(
            test=test, student_id=student_id, submitted_at__isnull=False
        ).exists():
            return Response(
                {"detail": "Cannot unassign a student who already submitted."},
                status=400,
            )
        MockAssignment.objects.filter(test=test, student_id=student_id).delete()
        MockAttempt.objects.filter(test=test, student_id=student_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MockTestPublishView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if test.questions.count() < 1:
            return Response({"detail": "Add questions before publishing."}, status=400)
        if test.assignments.count() < 1:
            return Response(
                {"detail": "Assign at least one student before publishing."},
                status=400,
            )
        if not test.duration_minutes:
            return Response({"detail": "Set a duration before publishing."}, status=400)
        if test.status == MockTest.STATUS_CLOSED:
            return Response({"detail": "Closed tests cannot be republished."}, status=400)
        test.mark_published()
        return Response(_test_detail(test, member))


class MockTestCloseView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        if test.status == MockTest.STATUS_DRAFT:
            return Response({"detail": "Publish the test before closing."}, status=400)
        test.mark_closed()
        return Response(_test_detail(test, member))


class MockTestStartView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if member.role != SchoolMembership.ROLE_STUDENT or not _is_assigned(
            member, test
        ):
            return Response({"detail": "Forbidden"}, status=403)
        if test.status != MockTest.STATUS_PUBLISHED:
            return Response(
                {"detail": "This test is not open for attempts."},
                status=400,
            )
        attempt, created = MockAttempt.objects.get_or_create(test=test, student=member)
        if attempt.is_submitted:
            return Response({"detail": "You already submitted this test."}, status=400)
        if created or not attempt.ends_at:
            attempt.set_ends_at_from_test()
            attempt.refresh_from_db()
        return Response(
            {
                "started_at": attempt.started_at,
                "ends_at": attempt.ends_at,
                "duration_minutes": test.duration_minutes,
                "question_count": test.question_count,
                "max_score": test.computed_max_score(),
            }
        )


class MockTestSubmitView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if member.role != SchoolMembership.ROLE_STUDENT or not _is_assigned(
            member, test
        ):
            return Response({"detail": "Forbidden"}, status=403)
        if test.status != MockTest.STATUS_PUBLISHED:
            return Response(
                {"detail": "This test is not open for submissions."},
                status=400,
            )
        serializer = SubmitAnswersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt, _ = MockAttempt.objects.get_or_create(test=test, student=member)
        if attempt.is_submitted:
            return Response({"detail": "You already submitted this test."}, status=400)
        if not attempt.ends_at:
            attempt.set_ends_at_from_test()
            attempt.refresh_from_db()

        auto = bool(serializer.validated_data.get("auto"))
        now = timezone.now()
        if attempt.ends_at and now > attempt.ends_at + _SUBMIT_GRACE and not auto:
            return Response(
                {"detail": "Time is up. Refresh to auto-submit, or contact your teacher."},
                status=400,
            )

        raw = serializer.validated_data["answers"]
        answers = _normalize_answers(raw, test)
        submit_and_grade(attempt, answers, auto=auto or (
            attempt.ends_at is not None and now > attempt.ends_at
        ))
        attempt.refresh_from_db()
        try:
            from engagement.models import EngagementActivity
            from engagement.services.activity import record_activity
            from engagement.services.mastery import recompute_mastery

            record_activity(
                member=member,
                kind=EngagementActivity.KIND_MOCK_SUBMIT,
                bucket=test.bucket,
                ref_id=f"mock:{test.id}",
            )
            recompute_mastery(member=member, bucket=test.bucket)
            # Nudge teacher if many still pending
            if test.created_by_id:
                from engagement.services.notifications import create_notification
                from mock_tests.models import MockAssignment

                assigned_n = MockAssignment.objects.filter(test=test).count()
                submitted_n = MockAttempt.objects.filter(
                    test=test, submitted_at__isnull=False
                ).count()
                pending = assigned_n - submitted_n
                if pending > 0 and test.created_by_id:
                    create_notification(
                        recipient=test.created_by,
                        kind="students_pending",
                        title=f"{pending} students still to attempt “{test.title}”",
                        body="Follow up so the class stays on track.",
                        link_path=f"/app/mock-tests/{test.id}",
                        dedupe_key=f"pending_submit:{test.id}",
                    )
        except Exception:
            pass
        payload = _student_attempt_payload(attempt)
        return Response(
            {
                **payload,
                "message": (
                    "Submitted. Your teacher will review and release your results."
                    if payload.get("awaiting_teacher_review")
                    else "Submitted."
                ),
            }
        )


def _normalize_answers(raw: dict, test: MockTest) -> dict:
    qmap = {q.id: q for q in test.questions.all()}
    out: dict = {}
    for k, v in (raw or {}).items():
        try:
            qid = int(k)
        except (TypeError, ValueError):
            continue
        q = qmap.get(qid)
        if not q:
            continue
        if q.qtype == MockQuestion.TYPE_BRIEF:
            out[str(qid)] = str(v or "")[:8000]
        elif q.qtype == MockQuestion.TYPE_MULTI:
            if isinstance(v, list):
                idxs = []
                for x in v:
                    try:
                        i = int(x)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= i < len(q.options) and i not in idxs:
                        idxs.append(i)
                out[str(qid)] = idxs
            else:
                try:
                    out[str(qid)] = [int(v)]
                except (TypeError, ValueError):
                    out[str(qid)] = []
        else:
            try:
                out[str(qid)] = int(v)
            except (TypeError, ValueError):
                continue
    return out


class MockTestMeView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if member.role != SchoolMembership.ROLE_STUDENT or not _is_assigned(
            member, test
        ):
            return Response({"detail": "Forbidden"}, status=403)
        attempt = MockAttempt.objects.filter(test=test, student=member).first()
        if not attempt:
            return Response({"status": "not_started", "review": None})
        if not attempt.is_submitted:
            return Response(
                {
                    "status": "in_progress",
                    "started_at": attempt.started_at,
                    "ends_at": attempt.ends_at,
                    "answers": attempt.answers,
                    "review": None,
                }
            )
        payload = _student_attempt_payload(attempt)
        return Response({"status": "submitted", **payload})


class MockTestResultsView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)

        assignments = list(
            test.assignments.select_related("student__user").order_by(
                "student__user__username"
            )
        )
        attempts = {
            a.student_id: a for a in test.attempts.select_related("student__user")
        }
        questions = list(test.questions.all())
        q_count = len(questions)

        roster = []
        submitted_percents: list[float] = []
        started = 0
        submitted = 0
        pending_brief = 0
        for a in assignments:
            att = attempts.get(a.student_id)
            st = _roster_status(att)
            if att and att.is_submitted:
                submitted += 1
                started += 1
                submitted_percents.append(att.percent)
                pending_brief += att.brief_pending_count
                score, mx, pct, sub_at = (
                    att.score,
                    att.max_score,
                    att.percent,
                    att.submitted_at,
                )
                grading = att.grading_status
                brief_pend = att.brief_pending_count
                released = att.student_can_see_results()
            elif att:
                started += 1
                score = mx = pct = sub_at = None
                grading = None
                brief_pend = None
                released = False
            else:
                score = mx = pct = sub_at = None
                grading = None
                brief_pend = None
                released = False
            roster.append(
                {
                    "student_id": a.student_id,
                    "username": a.student.user.username,
                    "full_name": a.student.user.first_name or "",
                    "status": st,
                    "score": score,
                    "max_score": mx,
                    "percent": pct,
                    "submitted_at": sub_at,
                    "grading_status": grading,
                    "brief_pending_count": brief_pend,
                    "results_released": released,
                }
            )

        submitted_attempts = [a for a in attempts.values() if a.is_submitted]
        q_stats = []
        for q in questions:
            correct = wrong = unanswered = 0
            for att in submitted_attempts:
                if q.qtype == MockQuestion.TYPE_BRIEF:
                    grade = MockAnswerGrade.objects.filter(
                        attempt=att, question=q
                    ).first()
                    if not grade or not grade.student_answer:
                        unanswered += 1
                    elif grade.teacher_score is not None:
                        if grade.teacher_score >= q.marks * 0.5:
                            correct += 1
                        else:
                            wrong += 1
                    else:
                        # pending — count as answered but not scored
                        wrong += 0
                        correct += 0
                    continue
                selected = att.answers.get(str(q.id))
                if selected is None:
                    selected = att.answers.get(q.id)
                if selected is None or selected == [] or selected == "":
                    unanswered += 1
                    continue
                if q.qtype == MockQuestion.TYPE_MCQ:
                    try:
                        ok = int(selected) == int((q.correct_indices or [0])[0])
                    except (TypeError, ValueError, IndexError):
                        ok = False
                else:
                    try:
                        sel = {int(x) for x in (selected if isinstance(selected, list) else [selected])}
                        ok = sel == set(int(i) for i in (q.correct_indices or []))
                    except (TypeError, ValueError):
                        ok = False
                if ok:
                    correct += 1
                else:
                    wrong += 1
            total = len(submitted_attempts) or 0
            q_stats.append(
                {
                    "question_id": q.id,
                    "order": q.order,
                    "qtype": q.qtype,
                    "prompt": q.prompt,
                    "marks": q.marks,
                    "correct_count": correct,
                    "wrong_count": wrong,
                    "unanswered_count": unanswered,
                    "correct_rate": round(correct / total, 3) if total else 0.0,
                }
            )

        assigned_n = len(assignments)
        summary = {
            "assigned": assigned_n,
            "started": started,
            "submitted": submitted,
            "not_started": assigned_n - started,
            "avg_percent": round(sum(submitted_percents) / len(submitted_percents), 1)
            if submitted_percents
            else None,
            "high_percent": max(submitted_percents) if submitted_percents else None,
            "low_percent": min(submitted_percents) if submitted_percents else None,
            "question_count": q_count,
            "max_score": test.computed_max_score(),
            "duration_minutes": test.duration_minutes,
            "pending_brief_grades": pending_brief,
            "results_mode": test.results_mode,
            "ready_to_release": sum(
                1
                for r in roster
                if r["status"] in ("ready_to_release", "grading", "final")
                and not r["results_released"]
            ),
            "results_released_count": sum(1 for r in roster if r["results_released"]),
        }
        return Response({"summary": summary, "roster": roster, "questions": q_stats})


class MockTestStudentResultView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk, student_id):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        student = get_object_or_404(
            SchoolMembership,
            pk=student_id,
            school=test.school,
            role=SchoolMembership.ROLE_STUDENT,
        )
        if not MockAssignment.objects.filter(test=test, student=student).exists():
            return Response({"detail": "Student is not assigned."}, status=404)
        attempt = MockAttempt.objects.filter(test=test, student=student).first()
        base = {
            "student_id": student.id,
            "username": student.user.username,
            "full_name": student.user.first_name or "",
        }
        if not attempt:
            return Response({**base, "status": "not_started", "review": None})
        if not attempt.is_submitted:
            return Response(
                {
                    **base,
                    "status": "in_progress",
                    "started_at": attempt.started_at,
                    "review": None,
                }
            )
        return Response(
            {
                **base,
                "status": _roster_status(attempt),
                "score": attempt.score,
                "max_score": attempt.max_score,
                "percent": attempt.percent,
                "objective_score": attempt.objective_score,
                "brief_pending_count": attempt.brief_pending_count,
                "grading_status": attempt.grading_status,
                "submitted_at": attempt.submitted_at,
                "results_released": attempt.student_can_see_results(),
                "results_mode": test.results_mode,
                "review": build_review(attempt, include_ai=True),
            }
        )


class MockTestReleaseResultsView(APIView):
    """POST — release results for one or many students (empty = all submitted)."""

    permission_classes = [IsSchoolMember]

    def post(self, request, pk, student_id=None):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)

        if student_id is not None:
            attempt = get_object_or_404(
                MockAttempt, test=test, student_id=student_id
            )
            if not attempt.is_submitted:
                return Response(
                    {"detail": "Student has not submitted yet."}, status=400
                )
            info = release_attempt_with_email(attempt, by=member)
            attempt.refresh_from_db()
            return Response(
                {
                    "released": 1,
                    "student_id": student_id,
                    "results_released": True,
                    "status": _roster_status(attempt),
                    "emailed": 1 if info["email"] == "sent" else 0,
                    "email_skipped": 1 if info["email"] == "skipped_no_email" else 0,
                    "email_failed": 1 if info["email"] == "failed" else 0,
                    "email_status": info["email"],
                }
            )

        serializer = ReleaseResultsSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data.get("student_ids") or []
        qs = list(
            test.attempts.filter(submitted_at__isnull=False).select_related(
                "student__user", "test"
            )
        )
        if ids:
            id_set = set(ids)
            qs = [a for a in qs if a.student_id in id_set]

        released = 0
        emailed = 0
        email_skipped = 0
        email_failed = 0
        for att in qs:
            # Always release + email on teacher "Release" action
            info = release_attempt_with_email(att, by=member)
            released += 1
            if info["email"] == "sent":
                emailed += 1
            elif info["email"] == "skipped_no_email":
                email_skipped += 1
            else:
                email_failed += 1

        visible_now = sum(
            1
            for a in test.attempts.filter(submitted_at__isnull=False)
            if a.student_can_see_results()
        )
        return Response(
            {
                "released": released,
                "results_released_count": visible_now,
                "submitted": len(qs),
                "results_mode": test.results_mode,
                "emailed": emailed,
                "email_skipped": email_skipped,
                "email_failed": email_failed,
            }
        )


class MockTestReleaseStudentResultsView(MockTestReleaseResultsView):
    """POST …/results/<student_id>/release/ — release one student's result."""


class MockTestConfirmBriefView(APIView):
    permission_classes = [IsSchoolMember]

    def post(self, request, pk, student_id, qid):
        member = _member(request)
        test = get_object_or_404(MockTest, pk=pk)
        if not _can_manage_test(member, test):
            return Response({"detail": "Forbidden"}, status=403)
        student = get_object_or_404(
            SchoolMembership,
            pk=student_id,
            school=test.school,
            role=SchoolMembership.ROLE_STUDENT,
        )
        attempt = get_object_or_404(MockAttempt, test=test, student=student)
        if not attempt.is_submitted:
            return Response({"detail": "Student has not submitted yet."}, status=400)
        question = get_object_or_404(
            MockQuestion, pk=qid, test=test, qtype=MockQuestion.TYPE_BRIEF
        )
        serializer = ConfirmBriefGradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        score = float(serializer.validated_data["score"])
        if score > float(question.marks):
            return Response(
                {"detail": f"Score cannot exceed {question.marks}."},
                status=400,
            )
        grade, _ = MockAnswerGrade.objects.get_or_create(
            attempt=attempt,
            question=question,
            defaults={"student_answer": ""},
        )
        grade.teacher_score = score
        grade.teacher_feedback = (serializer.validated_data.get("feedback") or "").strip()
        grade.confirmed_at = timezone.now()
        grade.confirmed_by = member
        grade.save()
        attempt.recompute_scores()
        attempt.refresh_from_db()
        # Optional: release + email student in the same action
        release = bool(request.data.get("release"))
        email_status = None
        if release:
            info = release_attempt_with_email(attempt, by=member)
            email_status = info["email"]
            attempt.refresh_from_db()
        return Response(
            {
                "student_id": student.id,
                "question_id": question.id,
                "teacher_score": grade.teacher_score,
                "teacher_feedback": grade.teacher_feedback,
                "score": attempt.score,
                "max_score": attempt.max_score,
                "percent": attempt.percent,
                "brief_pending_count": attempt.brief_pending_count,
                "grading_status": attempt.grading_status,
                "results_released": attempt.student_can_see_results(),
                "email_status": email_status,
                "review": build_review(attempt, include_ai=True),
            }
        )
