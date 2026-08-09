from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


GB = 1 << 30
DEFAULT_MAX_BUCKETS = 5
DEFAULT_BUCKET_QUOTA_BYTES = GB  # 1 GB per bucket (pilot)
FREE_TRIAL_MAX_USERS = 5  # free trial seat cap (0 elsewhere still means unlimited)


class School(models.Model):
    name = models.CharField(max_length=255)
    join_code = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        help_text="Teachers/students enter this code to join the school.",
    )
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    country_region = models.CharField(max_length=128, blank=True, default="")
    privacy_consent_at = models.DateTimeField(null=True, blank=True)

    max_buckets = models.PositiveIntegerField(default=DEFAULT_MAX_BUCKETS)
    bucket_quota_bytes = models.BigIntegerField(default=DEFAULT_BUCKET_QUOTA_BYTES)
    max_users = models.PositiveIntegerField(default=0)
    max_managers = models.PositiveIntegerField(default=0)
    onboarding_complete = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def ensure_join_code(self) -> str:
        if self.join_code:
            return self.join_code
        import secrets

        for _ in range(20):
            code = secrets.token_hex(4).upper()
            if not School.objects.filter(join_code=code).exists():
                self.join_code = code
                self.save(update_fields=["join_code"])
                return code
        raise RuntimeError("Could not allocate a unique school join code")

    def active_member_count(self) -> int:
        return self.memberships.filter(is_active=True).count()

    def can_add_member(self) -> bool:
        """False when max_users is set (>0) and school is at capacity."""
        if not self.max_users:
            return True
        return self.active_member_count() < int(self.max_users)


class PendingOnboard(models.Model):
    """Ephemeral school-admin signup awaiting Brevo email OTP verification."""

    organization_name = models.CharField(max_length=255)
    contact_phone = models.CharField(max_length=32)
    email = models.EmailField()
    country_region = models.CharField(max_length=128)
    privacy_consent = models.BooleanField(default=False)
    password_hash = models.CharField(max_length=128)

    otp_hash = models.CharField(max_length=128, blank=True, default="")
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    last_otp_sent_at = models.DateTimeField(null=True, blank=True)
    email_verified = models.BooleanField(default=False)

    setup_token = models.UUIDField(null=True, blank=True, unique=True)
    setup_token_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"PendingOnboard<{self.email} / {self.organization_name}>"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def set_password(self, raw_password: str) -> None:
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password_hash)

    def set_otp(self, otp: str) -> None:
        self.otp_hash = make_password(otp)
        self.otp_attempts = 0

    def check_otp(self, otp: str) -> bool:
        if not self.otp_hash:
            return False
        return check_password(otp, self.otp_hash)


class SchoolMembership(models.Model):
    """
    One school-scoped identity per user (pilot: a user belongs to one school).

    Replaces the old Teacher-only model. Role drives capabilities; BucketAccess
    still gates teacher/student bucket visibility.
    """

    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_TEACHER = "teacher"
    ROLE_STUDENT = "student"

    ROLE_CHOICES = [
        (ROLE_ADMIN, "School admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_TEACHER, "Teacher"),
        (ROLE_STUDENT, "Student"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="memberships")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="school_membership"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_TEACHER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["school", "role"])]

    def __str__(self):
        return f"{self.user.get_username()} [{self.role}] ({self.school.name})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager_or_above(self) -> bool:
        return self.role in {self.ROLE_ADMIN, self.ROLE_MANAGER}

    @property
    def can_upload(self) -> bool:
        return self.role in {self.ROLE_ADMIN, self.ROLE_MANAGER, self.ROLE_TEACHER}

    @property
    def can_create_students(self) -> bool:
        """Admins, managers, and teachers may provision student logins."""
        return self.role in {
            self.ROLE_ADMIN,
            self.ROLE_MANAGER,
            self.ROLE_TEACHER,
        }

    def has_bucket_access(self, bucket) -> bool:
        if not self.is_active or bucket.school_id != self.school_id:
            return False
        if self.is_manager_or_above:
            return True
        return BucketAccess.objects.filter(member=self, bucket=bucket).exists()


# Backwards-compatible alias used by older imports/migrations during transition.
Teacher = SchoolMembership


class SubjectBucket(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="buckets")
    name = models.CharField(max_length=200)
    grade_level = models.CharField(max_length=50, blank=True)
    quota_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Per-bucket storage cap; null inherits School.bucket_quota_bytes.",
    )
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def effective_quota_bytes(self) -> int:
        if self.quota_bytes is not None:
            return int(self.quota_bytes)
        return int(self.school.bucket_quota_bytes)

    class Meta:
        unique_together = ("school", "name", "grade_level")

    def __str__(self):
        grade = f" / {self.grade_level}" if self.grade_level else ""
        return f"{self.name}{grade} ({self.school.name})"


def document_upload_to(instance, filename: str) -> str:
    """Stable local (and later S3) key layout — school → bucket → document."""
    school_id = instance.bucket.school_id if instance.bucket_id else "unknown"
    bucket_id = instance.bucket_id or "unknown"
    # Keep original basename; Django storage may collide-suffix.
    safe = filename.replace("..", "_").replace("/", "_")
    return f"schools/{school_id}/buckets/{bucket_id}/documents/{safe}"


class BucketAccess(models.Model):
    """Explicit grant for teachers/students. Admins/managers need no row."""

    member = models.ForeignKey(
        SchoolMembership, on_delete=models.CASCADE, related_name="bucket_grants"
    )
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="access_grants")
    granted_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("member", "bucket")

    def __str__(self):
        return f"{self.member} → {self.bucket}"


# Alias for older code paths during transition.
TeacherBucketAccess = BucketAccess


class Document(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PARSING = "parsing"
    STATUS_INDEXING = "indexing"
    STATUS_INDEXED = "indexed"
    STATUS_DUPLICATE = "duplicate"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_PARSING, "Parsing"),
        (STATUS_INDEXING, "Indexing"),
        (STATUS_INDEXED, "Indexed"),
        (STATUS_DUPLICATE, "Duplicate"),
        (STATUS_FAILED, "Failed"),
    ]

    KIND_NOTES = "notes"
    KIND_QUESTION_PAPER = "question_paper"
    KIND_CHOICES = [
        (KIND_NOTES, "Teaching notes"),
        (KIND_QUESTION_PAPER, "Previous year question paper"),
    ]

    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="documents")
    uploaded_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    file = models.FileField(upload_to=document_upload_to)
    original_filename = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64, db_index=True)
    byte_size = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    kind = models.CharField(
        max_length=32,
        choices=KIND_CHOICES,
        default=KIND_NOTES,
        db_index=True,
        help_text="notes = teaching material; question_paper = past exam papers for mock tests.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    error_message = models.TextField(blank=True)
    page_count = models.IntegerField(null=True, blank=True)
    pageindex_tree = models.JSONField(null=True, blank=True)
    duplicate_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["bucket", "status"]),
            models.Index(fields=["bucket", "kind", "status"]),
        ]

    def __str__(self):
        return f"{self.original_filename} [{self.status}]"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Chunk(models.Model):
    """
    Retrieval-ready slice: hierarchical text + embedding.

    embedding stays JSON for now (works on any Postgres without extensions).
    Swap retrieval_service internals to pgvector later without changing callers.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="chunks")

    order_index = models.PositiveIntegerField()
    heading_path = models.JSONField(default=list, blank=True)
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)

    text = models.TextField()
    char_count = models.PositiveIntegerField(default=0)

    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    embedding_dim = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "order_index"]
        indexes = [models.Index(fields=["bucket", "document"])]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "order_index"], name="unique_chunk_order_per_document"
            )
        ]

    def __str__(self):
        heading = " > ".join(self.heading_path) if self.heading_path else "(root)"
        return f"{self.document.original_filename} #{self.order_index} [{heading}]"


class ChatSession(models.Model):
    """Server-side multi-turn chat scoped to one subject bucket."""

    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="chat_sessions")
    member = models.ForeignKey(
        SchoolMembership, on_delete=models.CASCADE, related_name="chat_sessions"
    )
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Chat #{self.pk} ({self.bucket})"


class ChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    retrieval_query = models.TextField(blank=True)
    model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
