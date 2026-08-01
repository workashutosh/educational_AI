from django.contrib import admin

from .models import (
    BucketAccess,
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    PendingOnboard,
    School,
    SchoolMembership,
    SubjectBucket,
)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "join_code",
        "max_buckets",
        "bucket_quota_bytes",
        "onboarding_complete",
        "is_active",
        "created_at",
    )
    search_fields = ("name", "join_code", "contact_phone", "country_region")
    list_filter = ("is_active", "onboarding_complete", "country_region")
    readonly_fields = ("join_code",)


@admin.register(PendingOnboard)
class PendingOnboardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "email",
        "organization_name",
        "email_verified",
        "expires_at",
        "created_at",
    )
    search_fields = ("email", "organization_name")
    list_filter = ("email_verified",)
    readonly_fields = ("password_hash", "otp_hash", "setup_token", "created_at")


@admin.register(SchoolMembership)
class SchoolMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "school", "role", "is_active", "created_at")
    list_filter = ("role", "school", "is_active")
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)


@admin.register(SubjectBucket)
class SubjectBucketAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "grade_level", "school", "quota_bytes", "is_archived", "created_at")
    list_filter = ("school", "grade_level", "is_archived")
    search_fields = ("name",)


@admin.register(BucketAccess)
class BucketAccessAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "bucket", "granted_by", "granted_at")
    list_filter = ("bucket__school",)
    raw_id_fields = ("member", "bucket", "granted_by")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "bucket",
        "status",
        "file_hash",
        "page_count",
        "deleted_at",
        "created_at",
        "processed_at",
    )
    list_filter = ("status", "bucket")
    search_fields = ("original_filename", "file_hash")
    readonly_fields = ("file_hash", "pageindex_tree", "created_at", "processed_at")
    raw_id_fields = ("bucket", "uploaded_by", "duplicate_of")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "order_index",
        "heading_path",
        "page_start",
        "page_end",
        "char_count",
        "embedding_model",
    )
    list_filter = ("bucket", "embedding_model")
    search_fields = ("text",)
    readonly_fields = ("embedding", "embedding_model", "embedding_dim", "created_at")
    raw_id_fields = ("document", "bucket")


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "sources", "retrieval_query", "model", "created_at")
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "bucket", "member", "created_at", "updated_at")
    list_filter = ("bucket__school",)
    search_fields = ("title", "member__user__username")
    raw_id_fields = ("bucket", "member")
    inlines = [ChatMessageInline]
