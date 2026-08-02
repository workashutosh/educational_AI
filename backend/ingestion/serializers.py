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
            "status",
            "error_message",
            "page_count",
            "duplicate_of",
            "created_at",
            "processed_at",
        )
        read_only_fields = fields


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    bucket_id = serializers.IntegerField()


class DocumentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ("id", "status", "error_message", "duplicate_of")
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


class PptxSlideSerializer(serializers.Serializer):
    heading = serializers.CharField(max_length=200)
    bullets = serializers.ListField(
        child=serializers.CharField(max_length=500),
        allow_empty=False,
        max_length=10,
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")


class DownloadPptxRequestSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=200)
    slides = PptxSlideSerializer(many=True)

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
