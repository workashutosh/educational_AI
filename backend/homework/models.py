"""Homework: assignments, student submissions (text / photos / files), AI + teacher grading."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from ingestion.models import School, SchoolMembership, SubjectBucket


def attachment_upload_to(instance, filename: str) -> str:
    safe = filename.replace("..", "_").replace("/", "_")
    return f"schools/{instance.school_id}/homework/{instance.id or 'new'}/brief/{safe}"


def submission_upload_to(instance, filename: str) -> str:
    safe = filename.replace("..", "_").replace("/", "_")
    sub = instance.submission
    return f"schools/{sub.assignment.school_id}/homework/{sub.assignment_id}/submissions/{sub.id}/{safe}"


class Assignment(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_CLOSED, "Closed"),
    ]
    RESULTS_IMMEDIATE = "immediate"
    RESULTS_AFTER_REVIEW = "after_review"
    RESULTS_CHOICES = [
        (RESULTS_IMMEDIATE, "Show AI feedback right after submitting"),
        (RESULTS_AFTER_REVIEW, "Teacher reviews, then releases"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="assignments")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="assignments")
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_assignments"
    )
    title = models.CharField(max_length=255)
    instructions = models.TextField(blank=True, default="")
    attachment = models.FileField(upload_to=attachment_upload_to, blank=True, max_length=500)
    attachment_name = models.CharField(max_length=500, blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True)
    max_marks = models.PositiveIntegerField(default=10)
    rubric = models.TextField(blank=True, default="", help_text="Marking scheme for AI + teachers.")
    model_answer = models.TextField(blank=True, default="")
    allow_late = models.BooleanField(default=True)
    ai_grading = models.BooleanField(default=True)
    results_mode = models.CharField(max_length=16, choices=RESULTS_CHOICES, default=RESULTS_AFTER_REVIEW)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_at and timezone.now() > self.due_at)


class AssignmentTarget(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="targets")
    student = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="homework_targets")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="uniq_hw_target")]


class Submission(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_GRADED = "graded"
    STATUS_CHOICES = [(STATUS_SUBMITTED, "Submitted"), (STATUS_GRADED, "Graded")]

    AI_PENDING = "pending"
    AI_DONE = "done"
    AI_FAILED = "failed"
    AI_SKIPPED = "skipped"
    AI_CHOICES = [
        (AI_PENDING, "Pending"),
        (AI_DONE, "Done"),
        (AI_FAILED, "Failed"),
        (AI_SKIPPED, "Skipped"),
    ]

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="homework_submissions")
    text_answer = models.TextField(blank=True, default="")
    extracted_text = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    is_late = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(default=timezone.now)
    ai_status = models.CharField(max_length=16, choices=AI_CHOICES, default=AI_PENDING)
    ai_score = models.FloatField(null=True, blank=True)
    ai_feedback = models.TextField(blank=True, default="")
    teacher_score = models.FloatField(null=True, blank=True)
    teacher_feedback = models.TextField(blank=True, default="")
    graded_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    graded_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="uniq_hw_submission")]

    @property
    def final_score(self) -> float | None:
        return self.teacher_score if self.teacher_score is not None else None

    def student_can_see_result(self) -> bool:
        if self.released_at:
            return True
        return self.assignment.results_mode == Assignment.RESULTS_IMMEDIATE and self.ai_status == self.AI_DONE


class SubmissionFile(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=submission_upload_to, max_length=500)
    original_filename = models.CharField(max_length=500)
    content_type = models.CharField(max_length=120, blank=True, default="")
    byte_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
