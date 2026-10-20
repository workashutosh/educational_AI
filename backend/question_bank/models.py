"""Reusable question bank, topics, and exam-style question papers."""
from __future__ import annotations

import hashlib
import re

from django.db import models

from ingestion.models import Document, School, SchoolMembership, SubjectBucket


class Topic(models.Model):
    SOURCE_AUTO = "auto"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [(SOURCE_AUTO, "From notes"), (SOURCE_MANUAL, "Manual")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="topics")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="topics")
    name = models.CharField(max_length=200)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    order = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["bucket", "name"], name="uniq_topic_per_bucket")
        ]

    def __str__(self):
        return f"{self.name} ({self.bucket.name})"


def normalize_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def prompt_hash(text: str) -> str:
    return hashlib.sha256(normalize_prompt(text).encode()).hexdigest()


class QuestionItem(models.Model):
    TYPE_MCQ = "mcq"
    TYPE_MULTI = "multi"
    TYPE_BRIEF = "brief"
    TYPE_LONG = "long"
    TYPE_NUMERIC = "numeric"
    TYPE_CHOICES = [
        (TYPE_MCQ, "Single-correct MCQ"),
        (TYPE_MULTI, "Multi-correct MCQ"),
        (TYPE_BRIEF, "Short answer"),
        (TYPE_LONG, "Long answer"),
        (TYPE_NUMERIC, "Numerical answer"),
    ]
    OBJECTIVE_TYPES = {TYPE_MCQ, TYPE_MULTI}

    DIFFICULTY_EASY = "easy"
    DIFFICULTY_MEDIUM = "medium"
    DIFFICULTY_HARD = "hard"
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, "Easy"),
        (DIFFICULTY_MEDIUM, "Medium"),
        (DIFFICULTY_HARD, "Hard"),
    ]
    DIFFICULTIES = [DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD]

    SOURCE_MANUAL = "manual"
    SOURCE_AI = "ai_generated"
    SOURCE_MOCK = "mock_test"
    SOURCE_PAST_PAPER = "past_paper"
    SOURCE_MICRO = "micro_quiz"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Written by teacher"),
        (SOURCE_AI, "AI generated"),
        (SOURCE_MOCK, "From a mock test"),
        (SOURCE_PAST_PAPER, "Extracted from a past paper"),
        (SOURCE_MICRO, "From a quick check"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="bank_items")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="bank_items")
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    qtype = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_MCQ)
    prompt = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_indices = models.JSONField(default=list, blank=True)
    answer = models.TextField(blank=True, default="", help_text="Model answer / numeric value.")
    explanation = models.TextField(blank=True, default="")
    marks = models.PositiveIntegerField(default=1)
    difficulty = models.CharField(
        max_length=8, choices=DIFFICULTY_CHOICES, default=DIFFICULTY_MEDIUM
    )
    tags = models.JSONField(default=list, blank=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    source_ref = models.CharField(max_length=64, blank=True, default="")
    source_document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="bank_items"
    )
    source_year = models.PositiveSmallIntegerField(null=True, blank=True)
    source_chunk_ids = models.JSONField(default=list, blank=True)

    prompt_hash = models.CharField(max_length=64, db_index=True, blank=True, default="")
    times_used = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["bucket", "qtype", "difficulty"]),
            models.Index(fields=["bucket", "topic"]),
            models.Index(fields=["bucket", "prompt_hash"]),
        ]

    def save(self, *args, **kwargs):
        self.prompt_hash = prompt_hash(self.prompt)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.qtype}/{self.difficulty}] {self.prompt[:50]}"


class BankImportJob(models.Model):
    """Async extraction of questions from a previous-year paper document."""

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="+")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="bank_imports")
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    created_count = models.PositiveIntegerField(default=0)
    skipped_duplicates = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class QuestionPaper(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_FINAL = "final"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_FINAL, "Final")]

    MODE_BANK_ONLY = "bank_only"
    MODE_BANK_THEN_AI = "bank_then_ai"
    MODE_AI_ONLY = "ai_only"
    MODE_CHOICES = [
        (MODE_BANK_ONLY, "Only questions already in the bank"),
        (MODE_BANK_THEN_AI, "Bank first, AI fills gaps"),
        (MODE_AI_ONLY, "Fresh AI questions (saved to bank)"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="question_papers")
    bucket = models.ForeignKey(
        SubjectBucket, on_delete=models.CASCADE, related_name="question_papers"
    )
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.CharField(max_length=255)
    exam_name = models.CharField(max_length=255, blank=True, default="")
    class_label = models.CharField(max_length=100, blank=True, default="")
    instructions = models.TextField(blank=True, default="")
    duration_minutes = models.PositiveIntegerField(default=180)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    source_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_BANK_THEN_AI)
    difficulty_mix = models.JSONField(default=dict, blank=True)
    topic_ids = models.JSONField(default=list, blank=True)
    generation_notes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def total_marks(self) -> int:
        return int(
            PaperItem.objects.filter(section__paper=self).aggregate(s=models.Sum("marks"))["s"]
            or 0
        )


class PaperSection(models.Model):
    paper = models.ForeignKey(QuestionPaper, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True, default="")
    qtype = models.CharField(max_length=16, choices=QuestionItem.TYPE_CHOICES)
    marks_each = models.PositiveIntegerField(default=1)
    requested_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class PaperItem(models.Model):
    """Snapshot of a bank question inside a paper (edits don't touch the bank)."""

    section = models.ForeignKey(PaperSection, on_delete=models.CASCADE, related_name="items")
    order = models.PositiveIntegerField(default=0)
    question = models.ForeignKey(
        QuestionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="paper_uses"
    )
    qtype = models.CharField(max_length=16, choices=QuestionItem.TYPE_CHOICES)
    prompt = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_indices = models.JSONField(default=list, blank=True)
    answer = models.TextField(blank=True, default="")
    explanation = models.TextField(blank=True, default="")
    marks = models.PositiveIntegerField(default=1)
    difficulty = models.CharField(max_length=8, default=QuestionItem.DIFFICULTY_MEDIUM)
    topic_name = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["order", "id"]
