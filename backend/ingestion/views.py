"""
DRF views for school-scoped notes: buckets, documents, query/ask, chat.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BucketAccess,
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    SchoolMembership,
    SubjectBucket,
)
from .permissions import (
    CanCreateStudents,
    CanListMembers,
    CanUpload,
    HasBucketAccess,
    IsManagerOrAdmin,
    IsSchoolMember,
    get_membership,
)
from .serializers import (
    AskRequestSerializer,
    BucketAccessSerializer,
    ChatMessageSerializer,
    ChatSessionSerializer,
    CreateMemberSerializer,
    CreateStudentSerializer,
    DocumentSerializer,
    DocumentStatusSerializer,
    DocumentUploadSerializer,
    DownloadPptxRequestSerializer,
    GeneratePptxRequestSerializer,
    GrantAccessSerializer,
    MemberAccessSerializer,
    QueryRequestSerializer,
    SubjectBucketCreateSerializer,
    SubjectBucketSerializer,
    TranslateRequestSerializer,
)

from .services import find_indexed_duplicate, sha256_of_uploaded_file
from .services.answer_service import answer_question
from .services.language_service import (
    NOT_FOUND_EN,
    SUPPORTED_LANGUAGES,
    normalize_language,
    translate_text,
)
from .services.llm_errors import LLMProviderError, http_status_for_llm_error, public_llm_message
from .services.page_image_service import render_document_page
from .services.pptx_service import (
    PptxGenerationError,
    generate_pptx_outline,
    pptx_from_outline,
)
from .services.retrieval_service import search_bucket
from .tasks import process_document

logger = logging.getLogger(__name__)
User = get_user_model()


def _open_ask_allowed() -> bool:
    return bool(getattr(settings, "ALLOW_OPEN_ASK", False))


@login_required(login_url="/accounts/login/")
def ask_test_page(request):
    """Browser chat UI against the Mathematics bucket (pilot). Requires login."""
    bucket = (
        SubjectBucket.objects.filter(name__iexact="Mathematics", is_archived=False)
        .order_by("id")
        .first()
    )
    if bucket is None:
        bucket = SubjectBucket.objects.filter(is_archived=False).order_by("id").first()
    if bucket is None:
        return render(
            request,
            "ingestion/ask_test.html",
            {
                "bucket": None,
                "doc_count": 0,
                "chunk_count": 0,
                "error": "No subject buckets found. Create one first.",
            },
            status=404,
        )

    # Prefer a bucket the member can access
    from .permissions import get_membership

    member = get_membership(request.user)
    if member:
        accessible = _accessible_buckets(member)
        preferred = accessible.filter(name__iexact="Mathematics").first() or accessible.first()
        if preferred:
            bucket = preferred

    doc_count = Document.objects.filter(
        bucket=bucket, status=Document.STATUS_INDEXED, deleted_at__isnull=True
    ).count()
    chunk_count = Chunk.objects.filter(bucket=bucket).count()
    return render(
        request,
        "ingestion/ask_test.html",
        {
            "bucket": bucket,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
        },
    )


def _accessible_buckets(member: SchoolMembership):
    base = SubjectBucket.objects.filter(school=member.school, is_archived=False)
    if member.is_manager_or_above:
        return base
    return base.filter(access_grants__member=member).distinct()


class BucketListView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        member = request.member
        buckets = _accessible_buckets(member)
        return Response(SubjectBucketSerializer(buckets, many=True).data)


class DocumentListCreateView(APIView):
    permission_classes = [IsSchoolMember]
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSchoolMember(), HasBucketAccess(), CanUpload()]
        return [IsSchoolMember()]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id")

    def get(self, request):
        member = request.member
        qs = Document.objects.filter(
            bucket__school=member.school, deleted_at__isnull=True
        ).select_related("bucket", "uploaded_by", "duplicate_of")

        if not member.is_manager_or_above:
            qs = qs.filter(bucket__access_grants__member=member).distinct()

        bucket_id = request.query_params.get("bucket_id")
        if bucket_id:
            bucket = get_object_or_404(SubjectBucket, pk=bucket_id)
            if not member.has_bucket_access(bucket):
                return Response(
                    {"detail": "You do not have access to this subject bucket."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            qs = qs.filter(bucket_id=bucket_id)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        kind = (request.query_params.get("kind") or "").strip().lower()
        if kind in {Document.KIND_NOTES, Document.KIND_QUESTION_PAPER}:
            qs = qs.filter(kind=kind)

        return Response(DocumentSerializer(qs, many=True).data)

    def post(self, request):
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member = getattr(request, "member", None) or get_membership(request.user)
        bucket = getattr(request, "bucket", None) or get_object_or_404(
            SubjectBucket, pk=serializer.validated_data["bucket_id"]
        )

        uploaded = serializer.validated_data["file"]
        file_hash = sha256_of_uploaded_file(uploaded)
        kind = serializer.validated_data.get("kind") or Document.KIND_NOTES

        duplicate = find_indexed_duplicate(bucket.id, file_hash)
        document = Document.objects.create(
            bucket=bucket,
            uploaded_by=member,
            file=uploaded,
            original_filename=uploaded.name,
            file_hash=file_hash,
            byte_size=getattr(uploaded, "size", None),
            content_type=getattr(uploaded, "content_type", "") or "",
            kind=kind,
            status=Document.STATUS_DUPLICATE if duplicate else Document.STATUS_QUEUED,
            duplicate_of=duplicate,
        )

        if duplicate:
            return Response(
                DocumentSerializer(document).data,
                status=status.HTTP_201_CREATED,
            )

        process_document.delay(document.id)
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)


class DocumentStatusView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = request.member
        document = get_object_or_404(
            Document.objects.select_related("bucket"),
            pk=pk,
            bucket__school=member.school,
        )
        if not member.has_bucket_access(document.bucket):
            return Response(
                {"detail": "You do not have access to this document's bucket."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(DocumentStatusSerializer(document).data)


class DocumentPageImageView(APIView):
    """
    GET /api/documents/{id}/pages/{page}/ — PNG preview of a PDF/image page.
    Requires bucket access (teachers and students with grants).
    """

    permission_classes = [IsSchoolMember]

    def get(self, request, pk, page: int):
        member = request.member
        document = get_object_or_404(
            Document.objects.select_related("bucket"),
            pk=pk,
            bucket__school=member.school,
        )
        if not member.has_bucket_access(document.bucket):
            return Response(
                {"detail": "You do not have access to this document's bucket."},
                status=status.HTTP_403_FORBIDDEN,
            )
        path = render_document_page(document, int(page))
        if path is None:
            return Response(
                {"detail": "Page image not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return FileResponse(path.open("rb"), content_type="image/png")


def _page_ref(start: int | None, end: int | None) -> str | None:
    if start is None:
        return None
    if end is None or start == end:
        return f"page {start}"
    return f"pages {start}-{end}"


class QueryView(APIView):
    """POST /api/query/ — raw chunk retrieval (no LLM)."""

    def get_permissions(self):
        if _open_ask_allowed():
            # Still run TokenAuthentication (default authenticators) so logged-in
            # callers keep request.user; AllowAny only skips the membership gate.
            return [AllowAny()]
        return [IsSchoolMember(), HasBucketAccess()]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id")

    def post(self, request):
        serializer = QueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bucket = getattr(request, "bucket", None) or get_object_or_404(
            SubjectBucket, pk=serializer.validated_data["bucket_id"]
        )
        top_k = serializer.validated_data.get("top_k", 5)
        query = serializer.validated_data["query"]

        results = search_bucket(bucket.id, query=query, top_k=top_k, kinds=["notes"])
        if not results:
            return Response(
                {
                    "query": query,
                    "bucket_id": bucket.id,
                    "matches": [],
                    "detail": "No indexed content in this bucket yet.",
                }
            )

        matches = [
            {
                "document_id": r.document_id,
                "document_filename": r.document_filename,
                "heading_path": r.heading_path,
                "page_ref": _page_ref(r.page_start, r.page_end),
                "text": r.text,
                "score": round(r.score, 4),
            }
            for r in results
        ]
        return Response(
            {
                "query": query,
                "bucket_id": bucket.id,
                "match_count": len(matches),
                "matches": matches,
            }
        )


class AskView(APIView):
    """
    POST /api/ask/ — RAG answer. Optional session_id persists the turn.
    ALLOW_OPEN_ASK=True keeps the pilot chat page working without login,
    but authenticated Token requests still bind request.user so history saves.
    """

    def get_permissions(self):
        if _open_ask_allowed():
            return [AllowAny()]
        return [IsSchoolMember(), HasBucketAccess()]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id")

    def post(self, request):
        serializer = AskRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bucket = getattr(request, "bucket", None) or get_object_or_404(
            SubjectBucket, pk=serializer.validated_data["bucket_id"]
        )
        top_k = serializer.validated_data.get("top_k", 5)
        question = serializer.validated_data["query"]
        history = serializer.validated_data.get("history") or []
        session_id = serializer.validated_data.get("session_id")
        language = serializer.validated_data.get("language") or ""

        try:
            result = answer_question(
                bucket.id,
                question=question,
                top_k=top_k,
                history=history,
                language=language,
            )
        except LLMProviderError as exc:
            return Response(
                {"detail": exc.public_message},
                status=http_status_for_llm_error(exc),
            )
        except RuntimeError:
            logger.exception("AskView unexpected failure")
            return Response(
                {"detail": public_llm_message(502)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        sources = []
        for i, s in enumerate(result.sources, start=1):
            page = s.page_start
            image_url = None
            if page is not None:
                image_url = f"/api/documents/{s.document_id}/pages/{int(page)}/"
            sources.append(
                {
                    "index": i,
                    "document_id": s.document_id,
                    "document_filename": s.document_filename,
                    "heading_path": s.heading_path,
                    "page_ref": _page_ref(s.page_start, s.page_end),
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                    "image_url": image_url,
                    "score": round(s.score, 4),
                }
            )

        session_payload = None
        assistant_message = None
        member = getattr(request, "member", None) or get_membership(request.user)
        if member and session_id:
            session = get_object_or_404(
                ChatSession, pk=session_id, member=member, bucket=bucket
            )
            ChatMessage.objects.create(
                session=session, role=ChatMessage.ROLE_USER, content=question
            )
            assistant_message = ChatMessage.objects.create(
                session=session,
                role=ChatMessage.ROLE_ASSISTANT,
                content=result.answer,
                sources=sources,
                retrieval_query=result.retrieval_query or "",
                model=result.model,
            )
            placeholder = not session.title or session.title.strip().lower() in {
                "new chat",
                "untitled",
                "untitled chat",
            }
            if placeholder:
                session.title = question[:120]
            session.updated_at = timezone.now()
            session.save(update_fields=["title", "updated_at"])
            session_payload = {"id": session.id, "title": session.title}

        suggestions: list[str] = []
        if member:
            try:
                from engagement.models import EngagementActivity
                from engagement.services.activity import record_activity
                from engagement.services.mastery import recompute_mastery
                from engagement.services.suggestions import build_chat_suggestions

                record_activity(
                    member=member,
                    kind=EngagementActivity.KIND_ASK,
                    bucket=bucket,
                    ref_id=str(session_id or ""),
                )
                suggestions = build_chat_suggestions(
                    sources=result.sources,
                    bucket=bucket,
                    member=member,
                )
                try:
                    recompute_mastery(member=member, bucket=bucket)
                except Exception:
                    pass
            except Exception:
                suggestions = []

        doubt_id = _auto_escalate(member, bucket, question, result.answer, assistant_message)

        return Response(
            {
                "question": question,
                "bucket_id": bucket.id,
                "answer": result.answer,
                "model": result.model,
                "retrieval_query": result.retrieval_query,
                "sources": sources,
                "session": session_payload,
                "suggestions": suggestions,
                # Use with POST /api/learning/feedback/ (only when session_id was sent).
                "message_id": assistant_message.id if assistant_message else None,
                "language": normalize_language(language),
                # Set when a student's unanswered question was routed to teachers.
                "doubt_id": doubt_id,
            }
        )


def _auto_escalate(member, bucket, question, answer, message) -> int | None:
    """Route a student's 'not in the notes' question to the subject teachers."""
    if member is None or member.role != SchoolMembership.ROLE_STUDENT:
        return None
    if not (answer or "").strip().startswith(NOT_FOUND_EN):
        return None
    try:
        from learning.models import Doubt
        from learning.services.content import open_doubt

        doubt, _ = open_doubt(
            student=member,
            bucket=bucket,
            question=question,
            reason=Doubt.REASON_NO_ANSWER,
            ai_answer=answer,
            chat_message=message,
        )
        return doubt.id
    except Exception:
        logger.exception("auto doubt escalation failed")
        return None


class LanguageListView(APIView):
    """GET /api/languages/ — languages accepted by /api/ask/ and /api/translate/."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            [{"code": code, "name": name} for code, name in SUPPORTED_LANGUAGES.items()]
        )


class TranslateView(APIView):
    """POST /api/translate/ {text, target_language} — translate an answer or note excerpt."""

    permission_classes = [IsSchoolMember]

    def post(self, request):
        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = normalize_language(serializer.validated_data["target_language"])
        try:
            text = translate_text(serializer.validated_data["text"], target)
        except LLMProviderError as exc:
            return Response(
                {"detail": exc.public_message}, status=http_status_for_llm_error(exc)
            )
        except RuntimeError:
            logger.exception("TranslateView failure")
            return Response({"detail": public_llm_message(502)}, status=502)
        return Response({"text": text, "target_language": target})


class GeneratePptxView(APIView):
    """POST /api/generate-pptx/ — RAG + Groq → JSON outline for in-app preview."""

    permission_classes = [IsSchoolMember, HasBucketAccess, CanUpload]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id")

    def post(self, request):
        serializer = GeneratePptxRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bucket = getattr(request, "bucket", None) or get_object_or_404(
            SubjectBucket, pk=serializer.validated_data["bucket_id"]
        )
        prompt = serializer.validated_data["prompt"]
        slide_count = serializer.validated_data.get("slide_count", 8)
        style = serializer.validated_data.get("style", "creative")

        try:
            result = generate_pptx_outline(
                bucket.id, prompt=prompt, slide_count=slide_count, style=style
            )
        except PptxGenerationError as exc:
            # Domain validation messages are already written for teachers.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except LLMProviderError as exc:
            return Response(
                {"detail": exc.public_message},
                status=http_status_for_llm_error(exc),
            )
        except RuntimeError:
            logger.exception("GeneratePptxView unexpected failure")
            return Response(
                {"detail": public_llm_message(502)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        member = getattr(request, "member", None) or get_membership(request.user)
        if member:
            try:
                from engagement.models import TeacherImpactEvent
                from engagement.services.impact import record_impact

                record_impact(
                    member=member,
                    kind=TeacherImpactEvent.KIND_PPT,
                    ref_id=f"ppt:{bucket.id}",
                )
            except Exception:
                pass

        return Response(
            {
                "bucket_id": bucket.id,
                "prompt": result.prompt,
                "title": result.title,
                "model": result.model,
                "style": result.style,
                "slide_count": len(result.slides),
                "slides": result.slides,
            }
        )


class DownloadPptxView(APIView):
    """POST /api/generate-pptx/download/ — build .pptx from a previewed outline."""

    permission_classes = [IsSchoolMember, HasBucketAccess, CanUpload]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id")

    def post(self, request):
        serializer = DownloadPptxRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Access already checked via HasBucketAccess; ensure bucket exists.
        get_object_or_404(SubjectBucket, pk=serializer.validated_data["bucket_id"])

        try:
            result = pptx_from_outline(
                serializer.validated_data["title"],
                serializer.validated_data["slides"],
                style=serializer.validated_data.get("style", "creative"),
            )
        except PptxGenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(
            result.data,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{result.filename}"'
        response["X-Pptx-Title"] = result.title[:200]
        response["X-Pptx-Slide-Count"] = str(result.slide_count)
        return response


# ---------------------------------------------------------------------------
# Chat sessions (server-side history)
# ---------------------------------------------------------------------------


class ChatSessionListCreateView(APIView):
    permission_classes = [IsSchoolMember, HasBucketAccess]

    def get_bucket_id(self):
        return self.request.data.get("bucket_id") or self.request.query_params.get("bucket_id")

    def get(self, request):
        member = request.member
        bucket_id = request.query_params.get("bucket_id")
        qs = ChatSession.objects.filter(member=member).select_related("bucket")
        if bucket_id:
            qs = qs.filter(bucket_id=bucket_id)
        else:
            qs = qs.filter(bucket_id__in=_accessible_buckets(member).values("id"))
        return Response(ChatSessionSerializer(qs[:50], many=True).data)

    def post(self, request):
        bucket = getattr(request, "bucket", None)
        if bucket is None:
            return Response({"detail": "bucket_id required"}, status=400)
        title = (request.data.get("title") or "").strip()[:200]
        session = ChatSession.objects.create(
            bucket=bucket, member=request.member, title=title
        )
        return Response(ChatSessionSerializer(session).data, status=201)


class ChatSessionDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        session = get_object_or_404(
            ChatSession.objects.select_related("bucket"),
            pk=pk,
            member=request.member,
        )
        if not request.member.has_bucket_access(session.bucket):
            return Response({"detail": "Forbidden"}, status=403)
        data = ChatSessionSerializer(session).data
        data["messages"] = ChatMessageSerializer(session.messages.all(), many=True).data
        return Response(data)


# ---------------------------------------------------------------------------
# Manager / admin
# ---------------------------------------------------------------------------


class AdminMembersListView(APIView):
    """List school members (managers for grants; teachers for student roster)."""

    permission_classes = [CanListMembers]

    def get(self, request):
        member = request.member
        rows = SchoolMembership.objects.filter(
            school=member.school, is_active=True
        ).select_related("user")
        role = (request.query_params.get("role") or "").strip().lower()
        if role:
            rows = rows.filter(role=role)
        # Teachers only need the student roster for provisioning UI.
        if member.role == SchoolMembership.ROLE_TEACHER and not role:
            rows = rows.filter(role=SchoolMembership.ROLE_STUDENT)
        rows = list(rows.order_by("role", "user__username"))
        grant_map: dict[int, list[int]] = {}
        if member.is_manager_or_above and rows:
            for ga in BucketAccess.objects.filter(
                member_id__in=[m.id for m in rows]
            ).values_list("member_id", "bucket_id"):
                grant_map.setdefault(ga[0], []).append(ga[1])
        return Response(
            [
                {
                    "id": m.id,
                    "username": m.user.username,
                    "email": m.user.email,
                    "full_name": m.user.first_name or "",
                    "role": m.role,
                    "role_display": m.get_role_display(),
                    "full_access": m.is_manager_or_above,
                    "bucket_ids": (
                        []
                        if m.is_manager_or_above
                        else grant_map.get(m.id, [])
                    ),
                }
                for m in rows
            ]
        )


def _roles_actor_may_create(actor: SchoolMembership) -> set[str]:
    if actor.role == SchoolMembership.ROLE_ADMIN:
        return {
            SchoolMembership.ROLE_ADMIN,
            SchoolMembership.ROLE_MANAGER,
            SchoolMembership.ROLE_TEACHER,
            SchoolMembership.ROLE_STUDENT,
        }
    if actor.role == SchoolMembership.ROLE_MANAGER:
        return {
            SchoolMembership.ROLE_TEACHER,
            SchoolMembership.ROLE_STUDENT,
        }
    if actor.can_create_students:
        return {SchoolMembership.ROLE_STUDENT}
    return set()


def _create_school_member(actor: SchoolMembership, data: dict):
    """Shared create path for /admin/members/ and /admin/students/."""
    school = actor.school
    role = data["role"]
    allowed = _roles_actor_may_create(actor)
    if role not in allowed:
        return Response(
            {"detail": f"Your role cannot create {role} accounts."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not school.can_add_member():
        return Response(
            {
                "detail": (
                    f"School user seat limit reached ({school.max_users}). "
                    "Upgrade the plan or deactivate unused accounts."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if role == SchoolMembership.ROLE_MANAGER and not school.can_add_manager():
        return Response(
            {
                "detail": (
                    f"Manager seat limit reached ({school.max_managers}). "
                    "Upgrade the plan or deactivate a manager."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    username = data["username"]
    password = data["password"]
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    bucket_ids = list(data.get("bucket_ids") or [])

    if not username:
        return Response(
            {"detail": "Username is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if User.objects.filter(username__iexact=username).exists():
        return Response(
            {"detail": "That username is already taken."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if email and User.objects.filter(email__iexact=email).exists():
        return Response(
            {"detail": "That email is already in use."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Only teacher/student need explicit bucket grants; admin/manager see all.
    grant_buckets: list[SubjectBucket] = []
    if role in {SchoolMembership.ROLE_TEACHER, SchoolMembership.ROLE_STUDENT} and bucket_ids:
        if not actor.is_manager_or_above:
            # Teachers may only grant buckets they themselves can access.
            for bid in bucket_ids:
                bucket = get_object_or_404(SubjectBucket, pk=bid, school=school)
                if not actor.has_bucket_access(bucket):
                    return Response(
                        {"detail": "You do not have access to that AI Bucket."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                grant_buckets.append(bucket)
        else:
            grant_buckets = list(
                SubjectBucket.objects.filter(pk__in=bucket_ids, school=school, is_archived=False)
            )

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=full_name[:150],
        )
        member = SchoolMembership.objects.create(
            school=school,
            user=user,
            role=role,
            is_active=True,
        )
        granted_ids: list[int] = []
        for bucket in grant_buckets:
            BucketAccess.objects.get_or_create(
                member=member,
                bucket=bucket,
                defaults={"granted_by": actor},
            )
            granted_ids.append(bucket.id)

    return Response(
        {
            "id": member.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.first_name or "",
            "role": member.role,
            "role_display": member.get_role_display(),
            "bucket_ids": granted_ids,
            "bucket_granted": granted_ids[0] if len(granted_ids) == 1 else None,
        },
        status=status.HTTP_201_CREATED,
    )


class AdminCreateMemberView(APIView):
    """
    POST /api/admin/members/ — create admin / manager / teacher / student.

    Role rules:
      - Admin: any role
      - Manager: teacher, student
      - Teacher: student only
    """

    permission_classes = [CanCreateStudents]

    def post(self, request):
        serializer = CreateMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _create_school_member(request.member, serializer.validated_data)


class AdminCreateStudentView(APIView):
    """POST /api/admin/students/ — back-compat student-only create."""

    permission_classes = [CanCreateStudents]

    def post(self, request):
        serializer = CreateStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["role"] = SchoolMembership.ROLE_STUDENT
        if data.get("bucket_id") is not None:
            data["bucket_ids"] = [data["bucket_id"]]
        else:
            data["bucket_ids"] = []
        return _create_school_member(request.member, data)


class AdminMemberAccessView(APIView):
    """
    GET/PUT /api/admin/members/<member_id>/access/
    Manage which AI Buckets a teacher/student can use.
    """

    permission_classes = [IsManagerOrAdmin]

    def get(self, request, member_id: int):
        actor = request.member
        target = get_object_or_404(
            SchoolMembership, pk=member_id, school=actor.school, is_active=True
        )
        grants = BucketAccess.objects.filter(member=target).select_related("bucket")
        return Response(
            {
                "member_id": target.id,
                "role": target.role,
                "username": target.user.username,
                "full_access": target.is_manager_or_above,
                "bucket_ids": [g.bucket_id for g in grants],
                "grants": [
                    {
                        "bucket_id": g.bucket_id,
                        "bucket_name": g.bucket.name,
                        "granted_at": g.granted_at,
                    }
                    for g in grants
                ],
            }
        )

    def put(self, request, member_id: int):
        actor = request.member
        target = get_object_or_404(
            SchoolMembership, pk=member_id, school=actor.school, is_active=True
        )
        if target.is_manager_or_above:
            return Response(
                {
                    "detail": (
                        "Admins and managers already have access to every AI Bucket. "
                        "No per-bucket grants needed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MemberAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = set(serializer.validated_data["bucket_ids"])
        valid = set(
            SubjectBucket.objects.filter(
                school=actor.school, is_archived=False, pk__in=wanted
            ).values_list("id", flat=True)
        )
        invalid = wanted - valid
        if invalid:
            return Response(
                {"detail": f"Unknown or archived bucket id(s): {sorted(invalid)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            existing = set(
                BucketAccess.objects.filter(member=target).values_list("bucket_id", flat=True)
            )
            to_add = valid - existing
            to_remove = existing - valid
            if to_remove:
                BucketAccess.objects.filter(member=target, bucket_id__in=to_remove).delete()
            for bid in to_add:
                BucketAccess.objects.get_or_create(
                    member=target,
                    bucket_id=bid,
                    defaults={"granted_by": actor},
                )

        return self.get(request, member_id)


class AdminBucketCreateView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request):
        serializer = SubjectBucketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = request.member
        school = member.school

        existing = SubjectBucket.objects.filter(
            school=school,
            name=serializer.validated_data["name"],
            grade_level=serializer.validated_data.get("grade_level") or "",
        ).first()
        if existing:
            return Response(SubjectBucketSerializer(existing).data)

        active_count = SubjectBucket.objects.filter(school=school, is_archived=False).count()
        if active_count >= school.max_buckets:
            return Response(
                {
                    "detail": (
                        f"Plan limit reached ({school.max_buckets} AI Buckets). "
                        "Upgrade or archive an existing bucket."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        bucket = SubjectBucket.objects.create(
            school=school,
            name=serializer.validated_data["name"],
            grade_level=serializer.validated_data.get("grade_level") or "",
            quota_bytes=school.bucket_quota_bytes,
        )
        return Response(SubjectBucketSerializer(bucket).data, status=status.HTTP_201_CREATED)


class AdminGrantAccessView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def post(self, request, pk):
        admin_member = request.member
        bucket = get_object_or_404(SubjectBucket, pk=pk, school=admin_member.school)

        serializer = GrantAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = get_object_or_404(
            SchoolMembership,
            pk=serializer.validated_data["member_id"],
            school=admin_member.school,
        )
        grant, created = BucketAccess.objects.get_or_create(
            member=target,
            bucket=bucket,
            defaults={"granted_by": admin_member},
        )
        return Response(
            BucketAccessSerializer(grant).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AdminRevokeAccessView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def delete(self, request, pk, member_id):
        admin_member = request.member
        bucket = get_object_or_404(SubjectBucket, pk=pk, school=admin_member.school)
        deleted, _ = BucketAccess.objects.filter(
            bucket=bucket,
            member_id=member_id,
            member__school=admin_member.school,
        ).delete()
        if not deleted:
            return Response({"detail": "Access grant not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminBucketAccessListView(APIView):
    permission_classes = [IsManagerOrAdmin]

    def get(self, request, pk):
        admin_member = request.member
        bucket = get_object_or_404(SubjectBucket, pk=pk, school=admin_member.school)
        grants = BucketAccess.objects.filter(bucket=bucket).select_related(
            "member__user", "granted_by"
        )
        return Response(BucketAccessSerializer(grants, many=True).data)


class SpeechTranscribeView(APIView):
    """
    POST /api/speech/transcribe/ (multipart: audio, language?) — voice question → text.

    Clients record with MediaRecorder (webm/ogg) or native audio (m4a) and put
    the returned text into the chat box (or straight into /api/ask/).
    """

    permission_classes = [IsSchoolMember]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        import tempfile
        from pathlib import Path

        from .services.speech_service import (
            AUDIO_EXTS,
            TranscriptionError,
            max_upload_bytes,
            transcribe_file,
        )

        audio = request.FILES.get("audio") or request.FILES.get("file")
        if audio is None:
            return Response({"detail": "Attach an audio file as 'audio'."}, status=400)
        limit = min(max_upload_bytes(), 10 * 1024 * 1024)
        if audio.size > limit:
            return Response(
                {"detail": "Voice messages must be under 10 MB (about 10 minutes)."},
                status=400,
            )
        suffix = Path(audio.name or "voice.webm").suffix.lower() or ".webm"
        if suffix not in AUDIO_EXTS:
            suffix = ".webm"
        language = request.data.get("language") or None
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            for chunk in audio.chunks():
                tmp.write(chunk)
            tmp.flush()
            try:
                result = transcribe_file(tmp.name, language=language)
            except TranscriptionError as exc:
                return Response({"detail": str(exc)}, status=400)
        return Response(
            {
                "text": result.text,
                "language": result.language,
                "duration_seconds": result.duration_seconds,
            }
        )
