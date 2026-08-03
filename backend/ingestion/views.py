"""
DRF views for school-scoped notes: buckets, documents, query/ask, chat.
"""
from __future__ import annotations

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
    CreateStudentSerializer,
    DocumentSerializer,
    DocumentStatusSerializer,
    DocumentUploadSerializer,
    DownloadPptxRequestSerializer,
    GeneratePptxRequestSerializer,
    GrantAccessSerializer,
    QueryRequestSerializer,
    SubjectBucketCreateSerializer,
    SubjectBucketSerializer,
)

User = get_user_model()
from .services import find_indexed_duplicate, sha256_of_uploaded_file
from .services.answer_service import answer_question
from .services.page_image_service import render_document_page
from .services.pptx_service import (
    PptxGenerationError,
    generate_pptx_outline,
    pptx_from_outline,
)
from .services.retrieval_service import search_bucket
from .tasks import process_document


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

        try:
            result = answer_question(
                bucket.id, question=question, top_k=top_k, history=history
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

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
        member = getattr(request, "member", None) or get_membership(request.user)
        if member and session_id:
            session = get_object_or_404(
                ChatSession, pk=session_id, member=member, bucket=bucket
            )
            ChatMessage.objects.create(
                session=session, role=ChatMessage.ROLE_USER, content=question
            )
            ChatMessage.objects.create(
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

        return Response(
            {
                "question": question,
                "bucket_id": bucket.id,
                "answer": result.answer,
                "model": result.model,
                "retrieval_query": result.retrieval_query,
                "sources": sources,
                "session": session_payload,
            }
        )


class GeneratePptxView(APIView):
    """POST /api/generate-pptx/ — RAG + Groq → JSON outline for in-app preview."""

    permission_classes = [IsSchoolMember, HasBucketAccess]

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

        try:
            result = generate_pptx_outline(
                bucket.id, prompt=prompt, slide_count=slide_count
            )
        except PptxGenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "bucket_id": bucket.id,
                "prompt": result.prompt,
                "title": result.title,
                "model": result.model,
                "slide_count": len(result.slides),
                "slides": result.slides,
            }
        )


class DownloadPptxView(APIView):
    """POST /api/generate-pptx/download/ — build .pptx from a previewed outline."""

    permission_classes = [IsSchoolMember, HasBucketAccess]

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
        rows = rows.order_by("role", "user__username")
        return Response(
            [
                {
                    "id": m.id,
                    "username": m.user.username,
                    "email": m.user.email,
                    "full_name": m.user.first_name or "",
                    "role": m.role,
                    "role_display": m.get_role_display(),
                }
                for m in rows
            ]
        )


class AdminCreateStudentView(APIView):
    """
    POST /api/admin/students/ — admin/manager/teacher creates a student login.

    Body: {username, password, full_name?, email?, bucket_id?}
    Students sign in via /api/auth/login/ with those credentials.
    """

    permission_classes = [CanCreateStudents]

    def post(self, request):
        serializer = CreateStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = request.member
        school = actor.school

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

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        full_name = (serializer.validated_data.get("full_name") or "").strip()
        email = (serializer.validated_data.get("email") or "").strip().lower()
        bucket_id = serializer.validated_data.get("bucket_id")

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

        bucket = None
        if bucket_id is not None:
            bucket = get_object_or_404(SubjectBucket, pk=bucket_id, school=school)
            if not actor.has_bucket_access(bucket):
                return Response(
                    {"detail": "You do not have access to that AI Bucket."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name[:150],
            )
            student = SchoolMembership.objects.create(
                school=school,
                user=user,
                role=SchoolMembership.ROLE_STUDENT,
                is_active=True,
            )
            granted = False
            if bucket is not None:
                BucketAccess.objects.get_or_create(
                    member=student,
                    bucket=bucket,
                    defaults={"granted_by": actor},
                )
                granted = True

        return Response(
            {
                "id": student.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.first_name or "",
                "role": student.role,
                "role_display": student.get_role_display(),
                "bucket_granted": bucket.id if granted else None,
            },
            status=status.HTTP_201_CREATED,
        )


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
