"""Question bank, topics, and question-paper APIs (staff only)."""
from __future__ import annotations

import logging

from django.db.models import Count, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.api_utils import bucket_for, paginate
from ingestion.models import Document, SchoolMembership
from ingestion.permissions import IsStaffMember
from ingestion.services.llm_errors import LLMProviderError, http_status_for_llm_error

from .models import BankImportJob, PaperItem, PaperSection, QuestionItem, QuestionPaper, Topic
from .serializers import (
    BuildMockTestSerializer,
    CreatePaperSerializer,
    GenerateItemsSerializer,
    ImportDocumentSerializer,
    ImportMockSerializer,
    PaperItemSerializer,
    QuestionItemSerializer,
    QuestionItemWriteSerializer,
    QuestionPaperListSerializer,
    QuestionPaperSerializer,
    TopicCreateSerializer,
    TopicSerializer,
    UpdatePaperItemSerializer,
    UpdatePaperSerializer,
)
from .services import export as paper_export
from .services.bank import (
    BankError,
    add_items,
    bank_queryset_for,
    build_mock_test_from_bank,
    generate_items,
    import_from_mock_test,
)
from .services.papers import create_paper, paper_to_mock_test, refill_section, swap_item
from .services.tagging import suggest_topic, sync_topics_from_notes

logger = logging.getLogger(__name__)


def _llm_error(exc: LLMProviderError) -> Response:
    return Response({"detail": exc.public_message}, status=http_status_for_llm_error(exc))


def _item_for(member: SchoolMembership, pk: int) -> QuestionItem:
    item = get_object_or_404(QuestionItem.objects.select_related("bucket", "topic"), pk=pk, school=member.school)
    bucket_for(member, item.bucket_id)
    return item


def _paper_qs():
    return QuestionPaper.objects.select_related("bucket").prefetch_related(
        Prefetch("sections", queryset=PaperSection.objects.prefetch_related("items"))
    )


def _paper_for(member: SchoolMembership, pk: int) -> QuestionPaper:
    paper = get_object_or_404(_paper_qs(), pk=pk, school=member.school)
    bucket_for(member, paper.bucket_id)
    return paper


def _counts(data: dict | None) -> dict[str, int]:
    return {k: int(v) for k, v in (data or {}).items() if int(v or 0) > 0}


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TopicListCreateView(APIView):
    """GET ?bucket_id= — topics with question counts. POST {bucket_id, name}."""

    permission_classes = [IsStaffMember]

    @extend_schema(parameters=[OpenApiParameter("bucket_id", int, required=True)])
    def get(self, request):
        bucket = bucket_for(request.member, request.query_params.get("bucket_id"))
        rows = Topic.objects.filter(bucket=bucket).annotate(
            item_count=Count("items", distinct=True)
        )
        return Response(TopicSerializer(rows, many=True).data)

    @extend_schema(request=TopicCreateSerializer, responses=TopicSerializer)
    def post(self, request):
        ser = TopicCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        bucket = bucket_for(request.member, ser.validated_data["bucket_id"])
        name = ser.validated_data["name"].strip()
        if Topic.objects.filter(bucket=bucket, name__iexact=name).exists():
            return Response({"detail": "That topic already exists."}, status=400)
        parent = None
        if ser.validated_data.get("parent"):
            parent = get_object_or_404(Topic, pk=ser.validated_data["parent"], bucket=bucket)
        topic = Topic.objects.create(
            school=bucket.school,
            bucket=bucket,
            name=name,
            parent=parent,
            source=Topic.SOURCE_MANUAL,
            order=Topic.objects.filter(bucket=bucket).count(),
        )
        return Response(TopicSerializer(topic).data, status=status.HTTP_201_CREATED)


class TopicDetailView(APIView):
    permission_classes = [IsStaffMember]

    def _get(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, school=request.member.school)
        bucket_for(request.member, topic.bucket_id)
        return topic

    @extend_schema(request=TopicSerializer, responses=TopicSerializer)
    def patch(self, request, pk):
        topic = self._get(request, pk)
        name = (request.data.get("name") or "").strip()
        if name:
            topic.name = name[:200]
        if "order" in request.data:
            topic.order = int(request.data.get("order") or 0)
        if "parent" in request.data:
            pid = request.data.get("parent")
            topic.parent = get_object_or_404(Topic, pk=pid, bucket=topic.bucket) if pid else None
        topic.save()
        return Response(TopicSerializer(topic).data)

    def delete(self, request, pk):
        topic = self._get(request, pk)
        topic.delete()  # items keep existing with topic=NULL
        return Response(status=status.HTTP_204_NO_CONTENT)


class TopicSyncView(APIView):
    """POST {bucket_id} — create topics from chapter headings in indexed notes."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=ImportDocumentSerializer)
    def post(self, request):
        bucket = bucket_for(request.member, request.data.get("bucket_id"))
        created = sync_topics_from_notes(bucket)
        return Response(
            {
                "created": TopicSerializer(created, many=True).data,
                "total": Topic.objects.filter(bucket=bucket).count(),
            }
        )


class TagUntaggedView(APIView):
    """POST {bucket_id} — auto-tag bank items and mock questions without a topic."""

    permission_classes = [IsStaffMember]

    def post(self, request):
        from mock_tests.models import MockQuestion

        bucket = bucket_for(request.member, request.data.get("bucket_id"))
        tagged = 0
        for item in QuestionItem.objects.filter(bucket=bucket, topic__isnull=True)[:300]:
            topic = suggest_topic(bucket, item.prompt)
            if topic:
                item.topic = topic
                item.save(update_fields=["topic", "prompt_hash", "updated_at"])
                tagged += 1
        mock_tagged = 0
        for q in MockQuestion.objects.filter(test__bucket=bucket, topic__isnull=True)[:500]:
            topic = suggest_topic(bucket, q.prompt)
            if topic:
                q.topic = topic
                q.save(update_fields=["topic"])
                mock_tagged += 1
        return Response({"bank_items_tagged": tagged, "mock_questions_tagged": mock_tagged})


# ---------------------------------------------------------------------------
# Bank items
# ---------------------------------------------------------------------------


class ItemListCreateView(APIView):
    """
    GET — paginated bank (?bucket_id, topic_id, qtype, difficulty, source, year,
    q, untagged=1, include_archived=1, limit, offset).
    POST — add a teacher-written question.
    """

    permission_classes = [IsStaffMember]

    @extend_schema(
        parameters=[
            OpenApiParameter(n, t)
            for n, t in [
                ("bucket_id", int),
                ("topic_id", int),
                ("qtype", str),
                ("difficulty", str),
                ("source", str),
                ("year", int),
                ("q", str),
                ("limit", int),
                ("offset", int),
            ]
        ],
        responses=QuestionItemSerializer(many=True),
    )
    def get(self, request):
        qs = bank_queryset_for(request.member, request.query_params)
        page = paginate(request, qs)
        page["results"] = QuestionItemSerializer(page["results"], many=True).data
        return Response(page)

    @extend_schema(request=QuestionItemWriteSerializer, responses=QuestionItemSerializer)
    def post(self, request):
        ser = QuestionItemWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = dict(ser.validated_data)
        if not vd.get("bucket_id") or not vd.get("prompt"):
            return Response({"detail": "bucket_id and prompt are required."}, status=400)
        bucket = bucket_for(request.member, vd.pop("bucket_id"))
        topic = None
        if vd.get("topic_id"):
            topic = get_object_or_404(Topic, pk=vd["topic_id"], bucket=bucket)
        created, _ = add_items(
            bucket,
            [vd],
            source=QuestionItem.SOURCE_MANUAL,
            created_by=request.member,
            topic=topic,
            source_year=vd.get("source_year"),
        )
        if not created:
            return Response(
                {"detail": "Question is invalid or already in the bank (check options/answer)."},
                status=400,
            )
        return Response(QuestionItemSerializer(created[0]).data, status=status.HTTP_201_CREATED)


class ItemDetailView(APIView):
    permission_classes = [IsStaffMember]

    @extend_schema(responses=QuestionItemSerializer)
    def get(self, request, pk):
        return Response(QuestionItemSerializer(_item_for(request.member, pk)).data)

    @extend_schema(request=QuestionItemWriteSerializer, responses=QuestionItemSerializer)
    def patch(self, request, pk):
        item = _item_for(request.member, pk)
        ser = QuestionItemWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        if "topic_id" in vd:
            item.topic = (
                get_object_or_404(Topic, pk=vd["topic_id"], bucket=item.bucket)
                if vd["topic_id"]
                else None
            )
        for field in (
            "qtype",
            "prompt",
            "options",
            "correct_indices",
            "answer",
            "explanation",
            "marks",
            "difficulty",
            "tags",
            "source_year",
            "is_archived",
        ):
            if field in vd:
                setattr(item, field, vd[field])
        if item.qtype in QuestionItem.OBJECTIVE_TYPES:
            bad = [i for i in item.correct_indices if i >= len(item.options)]
            if len(item.options) < 2 or not item.correct_indices or bad:
                return Response(
                    {"detail": "Objective questions need 2+ options and valid correct answers."},
                    status=400,
                )
        else:
            item.options, item.correct_indices = [], []
        item.save()
        return Response(QuestionItemSerializer(item).data)

    def delete(self, request, pk):
        """Archive (default). ?hard=1 deletes only if never used in a paper/test."""
        item = _item_for(request.member, pk)
        if request.query_params.get("hard") in ("1", "true"):
            if item.paper_uses.exists() or item.mock_questions.exists():
                return Response({"detail": "Used in a paper or test — archive it instead."}, status=400)
            item.delete()
        else:
            item.is_archived = True
            item.save(update_fields=["is_archived", "prompt_hash", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class GenerateItemsView(APIView):
    """POST — AI-generate new bank questions from the bucket's notes."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=GenerateItemsSerializer, responses=QuestionItemSerializer(many=True))
    def post(self, request):
        ser = GenerateItemsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        topic = None
        if vd.get("topic_id"):
            topic = get_object_or_404(Topic, pk=vd["topic_id"], bucket=bucket)
        kinds = [Document.KIND_NOTES]
        if vd.get("use_past_papers"):
            kinds.append(Document.KIND_QUESTION_PAPER)
        try:
            created = generate_items(
                request.member,
                bucket,
                prompt=vd.get("prompt") or "",
                counts=_counts(vd["counts"]),
                difficulty=vd["difficulty"],
                topic=topic,
                kinds=kinds,
            )
        except BankError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LLMProviderError as exc:
            return _llm_error(exc)
        try:
            from engagement.models import TeacherImpactEvent
            from engagement.services.impact import record_impact

            record_impact(member=request.member, kind=TeacherImpactEvent.KIND_MOCK_GENERATE, ref_id=f"bank:{bucket.id}")
        except Exception:
            pass
        return Response(QuestionItemSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class ImportMockTestView(APIView):
    """POST {mock_test_id} — copy an existing mock test's questions into the bank."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=ImportMockSerializer)
    def post(self, request):
        from mock_tests.models import MockTest

        ser = ImportMockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        test = get_object_or_404(MockTest, pk=ser.validated_data["mock_test_id"], school=request.member.school)
        bucket_for(request.member, test.bucket_id)
        created, skipped = import_from_mock_test(test, created_by=request.member)
        return Response({"created": len(created), "skipped": skipped})


def _job_payload(job: BankImportJob) -> dict:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "document_filename": job.document.original_filename,
        "bucket_id": job.bucket_id,
        "status": job.status,
        "created_count": job.created_count,
        "skipped_duplicates": job.skipped_duplicates,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


class ImportDocumentView(APIView):
    """POST {document_id} — extract questions from a past paper (async; poll the job)."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=ImportDocumentSerializer)
    def post(self, request):
        from .tasks import import_document_task, run_import_job

        ser = ImportDocumentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        document = get_object_or_404(
            Document,
            pk=ser.validated_data["document_id"],
            bucket__school=request.member.school,
            deleted_at__isnull=True,
        )
        bucket_for(request.member, document.bucket_id)
        if document.status != Document.STATUS_INDEXED:
            return Response({"detail": "Wait until the document is ready."}, status=400)
        running = BankImportJob.objects.filter(
            document=document, status__in=[BankImportJob.STATUS_QUEUED, BankImportJob.STATUS_RUNNING]
        ).first()
        if running:
            return Response(_job_payload(running), status=status.HTTP_202_ACCEPTED)
        job = BankImportJob.objects.create(
            school=request.member.school,
            bucket=document.bucket,
            document=document,
            created_by=request.member,
        )
        try:
            import_document_task.delay(job.id)
        except Exception:
            logger.warning("Celery unavailable; importing inline job=%s", job.id)
            run_import_job(job.id)
            job.refresh_from_db()
        return Response(_job_payload(job), status=status.HTTP_202_ACCEPTED)


class ImportJobListView(APIView):
    """GET ?bucket_id= — recent past-paper import jobs."""

    permission_classes = [IsStaffMember]

    def get(self, request):
        qs = BankImportJob.objects.filter(school=request.member.school).select_related("document")
        if request.query_params.get("bucket_id"):
            bucket = bucket_for(request.member, request.query_params["bucket_id"])
            qs = qs.filter(bucket=bucket)
        return Response([_job_payload(j) for j in qs[:50]])


class ImportJobDetailView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, pk):
        job = get_object_or_404(
            BankImportJob.objects.select_related("document"), pk=pk, school=request.member.school
        )
        bucket_for(request.member, job.bucket_id)
        return Response(_job_payload(job))


class CoverageView(APIView):
    """GET ?bucket_id= — per-topic bank depth and how often each topic was tested."""

    permission_classes = [IsStaffMember]

    def get(self, request):
        from mock_tests.models import MockQuestion

        bucket = bucket_for(request.member, request.query_params.get("bucket_id"))
        items = QuestionItem.objects.filter(bucket=bucket, is_archived=False)
        by_topic: dict = {}
        for row in items.values("topic_id", "difficulty", "qtype").annotate(n=Count("id")):
            entry = by_topic.setdefault(
                row["topic_id"], {"total": 0, "difficulty": {}, "qtype": {}}
            )
            entry["total"] += row["n"]
            entry["difficulty"][row["difficulty"]] = entry["difficulty"].get(row["difficulty"], 0) + row["n"]
            entry["qtype"][row["qtype"]] = entry["qtype"].get(row["qtype"], 0) + row["n"]
        tested = dict(
            MockQuestion.objects.filter(test__bucket=bucket, test__status__in=["published", "closed"])
            .values_list("topic_id")
            .annotate(n=Count("id"))
            .values_list("topic_id", "n")
        )
        topics = list(Topic.objects.filter(bucket=bucket))
        rows = []
        for t in topics:
            entry = by_topic.get(t.id, {"total": 0, "difficulty": {}, "qtype": {}})
            rows.append(
                {
                    "topic_id": t.id,
                    "topic_name": t.name,
                    "bank_items": entry["total"],
                    "by_difficulty": entry["difficulty"],
                    "by_qtype": entry["qtype"],
                    "times_tested": tested.get(t.id, 0),
                }
            )
        untagged = by_topic.get(None, {"total": 0})["total"]
        rows.sort(key=lambda r: (r["bank_items"], r["times_tested"]))
        return Response(
            {
                "bucket_id": bucket.id,
                "total_items": items.count(),
                "untagged_items": untagged,
                "topics": rows,
                "under_covered": [r for r in rows if r["bank_items"] < 5][:10],
            }
        )


class BuildMockTestView(APIView):
    """POST — build a draft (optionally assigned + published) mock test from the bank."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=BuildMockTestSerializer)
    def post(self, request):
        ser = BuildMockTestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        try:
            test = build_mock_test_from_bank(
                request.member,
                bucket,
                title=vd.get("title") or "",
                duration_minutes=vd["duration_minutes"],
                counts=_counts(vd.get("counts")),
                marks=dict(vd.get("marks") or {}),
                topic_ids=vd.get("topic_ids") or None,
                difficulty_mix=dict(vd.get("difficulty_mix") or {}),
                results_mode=vd["results_mode"],
                item_ids=vd.get("item_ids") or None,
            )
        except BankError as exc:
            return Response({"detail": str(exc)}, status=400)

        assigned = assign_and_publish(test, request.member, vd.get("assign_student_ids") or [], vd.get("publish"))
        return Response(
            {
                "mock_test_id": test.id,
                "title": test.title,
                "status": test.status,
                "question_count": test.question_count,
                "assigned": assigned,
            },
            status=status.HTTP_201_CREATED,
        )


def assign_and_publish(test, actor: SchoolMembership, student_ids: list[int], publish: bool) -> int:
    """Assign students who can access the bucket; publish when asked and assigned."""
    from mock_tests.models import MockAssignment

    count = 0
    if student_ids:
        students = SchoolMembership.objects.filter(
            pk__in=student_ids,
            school=actor.school,
            role=SchoolMembership.ROLE_STUDENT,
            is_active=True,
            bucket_grants__bucket=test.bucket,
        ).distinct()
        for s in students:
            _, created = MockAssignment.objects.get_or_create(
                test=test, student=s, defaults={"assigned_by": actor}
            )
            count += int(created)
    if publish and MockAssignment.objects.filter(test=test).exists():
        test.mark_published()
        try:
            from engagement.services.notifications import notify_many

            notify_many(
                [a.student for a in test.assignments.select_related("student__school")],
                kind="test_assigned",
                title=f"New practice: {test.title}",
                body=f"{test.question_count} questions · {test.duration_minutes} min",
                link_path=f"/app/mock-tests/{test.id}",
                dedupe_key=f"mock:{test.id}",
            )
        except Exception:
            logger.exception("notify after bank publish failed")
    return count


# ---------------------------------------------------------------------------
# Question papers
# ---------------------------------------------------------------------------


class PaperListCreateView(APIView):
    permission_classes = [IsStaffMember]

    @extend_schema(responses=QuestionPaperListSerializer(many=True))
    def get(self, request):
        member = request.member
        qs = _paper_qs().filter(school=member.school)
        if not member.is_manager_or_above:
            qs = qs.filter(bucket__access_grants__member=member).distinct()
        if request.query_params.get("bucket_id"):
            qs = qs.filter(bucket_id=request.query_params["bucket_id"])
        return Response(QuestionPaperListSerializer(qs[:100], many=True).data)

    @extend_schema(request=CreatePaperSerializer, responses=QuestionPaperSerializer)
    def post(self, request):
        ser = CreatePaperSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        try:
            paper = create_paper(
                request.member,
                bucket,
                title=vd["title"],
                sections=[dict(s) for s in vd["sections"]],
                exam_name=vd.get("exam_name") or "",
                class_label=vd.get("class_label") or "",
                instructions=vd.get("instructions") or "",
                duration_minutes=vd["duration_minutes"],
                source_mode=vd["source_mode"],
                difficulty_mix=dict(vd.get("difficulty_mix") or {}),
                topic_ids=vd.get("topic_ids") or [],
            )
        except BankError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LLMProviderError as exc:
            return _llm_error(exc)
        try:
            from engagement.models import TeacherImpactEvent
            from engagement.services.impact import record_impact

            record_impact(member=request.member, kind=TeacherImpactEvent.KIND_MOCK_GENERATE, ref_id=f"paper:{paper.id}")
        except Exception:
            pass
        return Response(
            QuestionPaperSerializer(_paper_qs().get(pk=paper.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class PaperDetailView(APIView):
    permission_classes = [IsStaffMember]

    @extend_schema(responses=QuestionPaperSerializer)
    def get(self, request, pk):
        return Response(QuestionPaperSerializer(_paper_for(request.member, pk)).data)

    @extend_schema(request=UpdatePaperSerializer, responses=QuestionPaperSerializer)
    def patch(self, request, pk):
        paper = _paper_for(request.member, pk)
        ser = UpdatePaperSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        for field, value in ser.validated_data.items():
            setattr(paper, field, value)
        paper.save()
        return Response(QuestionPaperSerializer(_paper_qs().get(pk=paper.pk)).data)

    def delete(self, request, pk):
        _paper_for(request.member, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaperSectionRefillView(APIView):
    """POST — replace a section's questions with a fresh pick."""

    permission_classes = [IsStaffMember]

    def post(self, request, pk, section_id):
        paper = _paper_for(request.member, pk)
        if paper.status == QuestionPaper.STATUS_FINAL:
            return Response({"detail": "Final papers are locked. Set status back to draft first."}, status=400)
        section = get_object_or_404(PaperSection, pk=section_id, paper=paper)
        try:
            notes = refill_section(paper, section, request.member)
        except LLMProviderError as exc:
            return _llm_error(exc)
        data = QuestionPaperSerializer(_paper_qs().get(pk=paper.pk)).data
        data["notes"] = notes
        return Response(data)


class PaperItemDetailView(APIView):
    permission_classes = [IsStaffMember]

    def _get(self, request, pk, item_id):
        paper = _paper_for(request.member, pk)
        item = get_object_or_404(PaperItem.objects.select_related("question", "section"), pk=item_id, section__paper=paper)
        return paper, item

    @extend_schema(request=UpdatePaperItemSerializer, responses=PaperItemSerializer)
    def patch(self, request, pk, item_id):
        paper, item = self._get(request, pk, item_id)
        if paper.status == QuestionPaper.STATUS_FINAL:
            return Response({"detail": "Final papers are locked."}, status=400)
        ser = UpdatePaperItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        for field, value in ser.validated_data.items():
            setattr(item, field, value)
        item.save()
        return Response(PaperItemSerializer(item).data)

    def delete(self, request, pk, item_id):
        paper, item = self._get(request, pk, item_id)
        if paper.status == QuestionPaper.STATUS_FINAL:
            return Response({"detail": "Final papers are locked."}, status=400)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaperItemSwapView(APIView):
    """POST — replace one question with another unused bank question of the same type."""

    permission_classes = [IsStaffMember]

    @extend_schema(responses=PaperItemSerializer)
    def post(self, request, pk, item_id):
        paper = _paper_for(request.member, pk)
        if paper.status == QuestionPaper.STATUS_FINAL:
            return Response({"detail": "Final papers are locked."}, status=400)
        item = get_object_or_404(PaperItem.objects.select_related("question", "section"), pk=item_id, section__paper=paper)
        try:
            new = swap_item(paper, item)
        except BankError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(PaperItemSerializer(new).data)


class PaperExportView(APIView):
    """GET ?fmt=pdf|docx&answers=0|1 — printable paper or answer key."""

    permission_classes = [IsStaffMember]

    @extend_schema(
        parameters=[OpenApiParameter("fmt", str), OpenApiParameter("answers", bool)],
        responses={(200, "application/pdf"): bytes},
    )
    def get(self, request, pk):
        paper = _paper_for(request.member, pk)
        # Not ?format= — DRF reserves that for renderer negotiation.
        fmt = (request.query_params.get("fmt") or "pdf").lower()
        answers = request.query_params.get("answers") in ("1", "true", "yes")
        if fmt == "docx":
            data = paper_export.paper_docx(paper, include_answers=answers)
            ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "pdf":
            data = paper_export.paper_pdf(paper, include_answers=answers)
            ctype = "application/pdf"
        else:
            return Response({"detail": "fmt must be pdf or docx."}, status=400)
        response = HttpResponse(data, content_type=ctype)
        filename = paper_export.export_filename(paper, fmt, include_answers=answers)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class PaperToMockTestView(APIView):
    """POST — create a draft mock test from this paper."""

    permission_classes = [IsStaffMember]

    def post(self, request, pk):
        paper = _paper_for(request.member, pk)
        try:
            test = paper_to_mock_test(paper, request.member)
        except BankError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"mock_test_id": test.id, "title": test.title}, status=status.HTTP_201_CREATED)
