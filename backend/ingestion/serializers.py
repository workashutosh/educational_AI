from rest_framework import serializers

from .models import BucketAccess, ChatMessage, ChatSession, Document, SubjectBucket


class SubjectBucketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectBucket
        fields = ("id", "name", "grade_level", "school", "is_archived")
        read_only_fields = ("id", "school")


class SubjectBucketCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    grade_level = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = (
            "id",
            "bucket",
            "uploaded_by",
            "original_filename",
            "file_hash",
            "byte_size",
            "content_type",
            "kind",
            "status",
            "error_message",
            "progress_message",
            "page_count",
            "duplicate_of",
            "created_at",
            "processed_at",
        )
        read_only_fields = fields


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    bucket_id = serializers.IntegerField()
    kind = serializers.ChoiceField(
        choices=["notes", "question_paper"],
        required=False,
        default="notes",
    )


class DocumentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ("id", "status", "error_message", "progress_message", "duplicate_of")
        read_only_fields = fields


class QueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    bucket_id = serializers.IntegerField()
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=50)


class ChatHistoryItemSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("user", "assistant"))
    content = serializers.CharField(max_length=8000)


class AskRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    bucket_id = serializers.IntegerField()
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=50)
    history = ChatHistoryItemSerializer(many=True, required=False, default=list)
    session_id = serializers.IntegerField(required=False, allow_null=True)


class GeneratePptxRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=2000)
    bucket_id = serializers.IntegerField()
    slide_count = serializers.IntegerField(required=False, default=8, min_value=3, max_value=15)
    style = serializers.ChoiceField(
        choices=["creative", "clean", "bold", "sunset", "ocean"],
        required=False,
        default="creative",
    )


class PptxSlideSerializer(serializers.Serializer):
    heading = serializers.CharField(max_length=200)
    subtitle = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    layout = serializers.ChoiceField(
        choices=["standard", "hook", "compare", "quiz", "quote", "summary"],
        required=False,
        default="standard",
    )
    bullets = serializers.ListField(
        child=serializers.CharField(max_length=500),
        allow_empty=False,
        max_length=10,
    )
    callout = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")


class DownloadPptxRequestSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=200)
    slides = PptxSlideSerializer(many=True)
    style = serializers.ChoiceField(
        choices=["creative", "clean", "bold", "sunset", "ocean"],
        required=False,
        default="creative",
    )

    def validate_slides(self, value):
        if not value:
            raise serializers.ValidationError("At least one slide is required.")
        if len(value) > 20:
            raise serializers.ValidationError("Too many slides (max 20).")
        return value


class GrantAccessSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(required=False)
    teacher_id = serializers.IntegerField(required=False)  # legacy alias

    def validate(self, attrs):
        member_id = attrs.get("member_id") or attrs.get("teacher_id")
        if not member_id:
            raise serializers.ValidationError({"member_id": "This field is required."})
        attrs["member_id"] = member_id
        return attrs


class CreateStudentSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    bucket_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional AI Bucket to grant the student immediately.",
    )

    def validate_username(self, value):
        return (value or "").strip()


class CreateMemberSerializer(serializers.Serializer):
    """Provision any school role (permissions enforced in the view)."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(
        choices=["admin", "manager", "teacher", "student"],
        default="student",
    )
    bucket_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        default=list,
        help_text="Buckets to grant (teachers/students). Ignored for admin/manager.",
    )
    # Back-compat with student create form
    bucket_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_username(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        ids = list(attrs.get("bucket_ids") or [])
        single = attrs.get("bucket_id")
        if single is not None and single not in ids:
            ids.append(int(single))
        attrs["bucket_ids"] = ids
        return attrs


class MemberAccessSerializer(serializers.Serializer):
    bucket_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=True,
    )


class BucketAccessSerializer(serializers.ModelSerializer):
    member_id = serializers.IntegerField(source="member.id", read_only=True)
    teacher_id = serializers.IntegerField(source="member.id", read_only=True)  # legacy
    username = serializers.CharField(source="member.user.username", read_only=True)
    email = serializers.EmailField(source="member.user.email", read_only=True)
    role = serializers.CharField(source="member.role", read_only=True)

    class Meta:
        model = BucketAccess
        fields = (
            "member_id",
            "teacher_id",
            "username",
            "email",
            "role",
            "granted_at",
            "granted_by",
        )


# Legacy name
TeacherAccessSerializer = BucketAccessSerializer


class ChatSessionSerializer(serializers.ModelSerializer):
    bucket_name = serializers.CharField(source="bucket.name", read_only=True)

    class Meta:
        model = ChatSession
        fields = (
            "id",
            "bucket",
            "bucket_name",
            "member",
            "title",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "role",
            "content",
            "sources",
            "retrieval_query",
            "model",
            "created_at",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        sources = data.get("sources") or []
        enriched = []
        for s in sources:
            if not isinstance(s, dict):
                enriched.append(s)
                continue
            row = dict(s)
            page = row.get("page_start")
            doc_id = row.get("document_id")
            if page is not None and doc_id and not row.get("image_url"):
                row["image_url"] = f"/api/documents/{doc_id}/pages/{int(page)}/"
            enriched.append(row)
        data["sources"] = enriched
        return data
