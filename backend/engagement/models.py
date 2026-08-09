"""Habit-loop models: streaks, micro-quizzes, mastery, nudges, impact, leaderboards."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from ingestion.models import School, SchoolMembership, SubjectBucket


class StudentStreak(models.Model):
    member = models.OneToOneField(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="streak",
    )
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_activity_date = models.DateField(null=True, blank=True)
    weekly_count = models.PositiveIntegerField(default=0)
    week_start = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Streak {self.member_id}: {self.current_streak}"


class EngagementActivity(models.Model):
    KIND_ASK = "ask"
    KIND_MICRO_QUIZ = "micro_quiz"
    KIND_MOCK_SUBMIT = "mock_submit"
    KIND_LECTURE_JOIN = "lecture_join"
    KIND_CHOICES = [
        (KIND_ASK, "Ask"),
        (KIND_MICRO_QUIZ, "Micro quiz"),
        (KIND_MOCK_SUBMIT, "Mock submit"),
        (KIND_LECTURE_JOIN, "Lecture join"),
    ]

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="engagement_activities"
    )
    member = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="engagement_activities",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    bucket = models.ForeignKey(
        SubjectBucket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    ref_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school", "kind", "created_at"]),
            models.Index(fields=["member", "created_at"]),
        ]


class MicroQuiz(models.Model):
    SOURCE_DOCUMENT = "document"
    SOURCE_LECTURE = "lecture"
    SOURCE_CHOICES = [
        (SOURCE_DOCUMENT, "Document"),
        (SOURCE_LECTURE, "Lecture"),
    ]
    STATUS_DRAFT = "draft"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="micro_quizzes"
    )
    bucket = models.ForeignKey(
        SubjectBucket, on_delete=models.CASCADE, related_name="micro_quizzes"
    )
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    source_id = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["bucket", "status"]),
            models.Index(fields=["school", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id"],
                name="uniq_microquiz_source",
            )
        ]

    def __str__(self):
        return self.title


class MicroQuestion(models.Model):
    quiz = models.ForeignKey(
        MicroQuiz, on_delete=models.CASCADE, related_name="questions"
    )
    order = models.PositiveSmallIntegerField(default=0)
    prompt = models.TextField()
    options = models.JSONField(default=list)  # list[str] length 4
    correct_index = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class MicroAttempt(models.Model):
    quiz = models.ForeignKey(
        MicroQuiz, on_delete=models.CASCADE, related_name="attempts"
    )
    student = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="micro_attempts",
        limit_choices_to={"role": SchoolMembership.ROLE_STUDENT},
    )
    answers = models.JSONField(default=dict)  # {qid: option_index}
    score = models.PositiveSmallIntegerField(default=0)
    max_score = models.PositiveSmallIntegerField(default=3)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["quiz", "student"], name="uniq_micro_attempt"
            )
        ]


class SubjectMastery(models.Model):
    member = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="subject_mastery",
    )
    bucket = models.ForeignKey(
        SubjectBucket, on_delete=models.CASCADE, related_name="subject_mastery"
    )
    score_0_100 = models.PositiveSmallIntegerField(default=0)
    tests_taken = models.PositiveIntegerField(default=0)
    micro_taken = models.PositiveIntegerField(default=0)
    chat_turns = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "bucket"], name="uniq_subject_mastery"
            )
        ]
        indexes = [models.Index(fields=["member", "bucket"])]


class TeacherImpactEvent(models.Model):
    KIND_PPT = "ppt"
    KIND_MOCK_GENERATE = "mock_generate"
    KIND_MICRO_AUTO = "micro_auto"
    KIND_CHOICES = [
        (KIND_PPT, "PPT"),
        (KIND_MOCK_GENERATE, "Mock generate"),
        (KIND_MICRO_AUTO, "Micro quiz auto"),
    ]

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="teacher_impact_events"
    )
    member = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="impact_events",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    minutes_saved = models.PositiveIntegerField(default=0)
    ref_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["member", "created_at"]),
            models.Index(fields=["school", "created_at"]),
        ]


class Notification(models.Model):
    KIND_NEW_NOTES = "new_notes"
    KIND_LECTURE_ENDED = "lecture_ended"
    KIND_TEST_ASSIGNED = "test_assigned"
    KIND_STUDENTS_PENDING = "students_pending"
    KIND_MICRO_READY = "micro_ready"
    KIND_STREAK = "streak"
    KIND_DIGEST = "digest"
    KIND_GENERIC = "generic"
    KIND_CHOICES = [
        (KIND_NEW_NOTES, "New notes"),
        (KIND_LECTURE_ENDED, "Lecture ended"),
        (KIND_TEST_ASSIGNED, "Test assigned"),
        (KIND_STUDENTS_PENDING, "Students pending"),
        (KIND_MICRO_READY, "Micro quiz ready"),
        (KIND_STREAK, "Streak"),
        (KIND_DIGEST, "Digest"),
        (KIND_GENERIC, "Generic"),
    ]

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_GENERIC)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    link_path = models.CharField(max_length=512, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=128, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    email_queued_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["school", "kind", "created_at"]),
            models.Index(fields=["recipient", "kind", "dedupe_key"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])


class NotificationPreference(models.Model):
    member = models.OneToOneField(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="notification_prefs",
    )
    email_digests = models.BooleanField(default=True)
    leaderboard_visible = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class LeaderboardSetting(models.Model):
    """Opt-in class leaderboard for a mock test (default off)."""

    mock_test = models.OneToOneField(
        "mock_tests.MockTest",
        on_delete=models.CASCADE,
        related_name="leaderboard_setting",
    )
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
