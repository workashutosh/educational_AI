"""Flashcards (spaced repetition), doubt escalation, and chat answer feedback."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from ingestion.models import ChatMessage, ChatSession, Document, School, SchoolMembership, SubjectBucket


class FlashcardDeck(models.Model):
    VISIBILITY_BUCKET = "bucket"
    VISIBILITY_PRIVATE = "private"
    VISIBILITY_CHOICES = [
        (VISIBILITY_BUCKET, "Everyone with access to the AI Bucket"),
        (VISIBILITY_PRIVATE, "Only me"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="flashcard_decks")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="flashcard_decks")
    owner = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcard_decks"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    topic = models.ForeignKey(
        "question_bank.Topic", on_delete=models.SET_NULL, null=True, blank=True, related_name="decks"
    )
    source_document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcard_decks"
    )
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES, default=VISIBILITY_BUCKET)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Flashcard(models.Model):
    deck = models.ForeignKey(FlashcardDeck, on_delete=models.CASCADE, related_name="cards")
    order = models.PositiveIntegerField(default=0)
    front = models.TextField()
    back = models.TextField()
    topic = models.ForeignKey(
        "question_bank.Topic", on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcards"
    )
    source_chunk_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]


class CardState(models.Model):
    """Per-learner SM-2 scheduling state for one card."""

    card = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name="states")
    member = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="card_states")
    ease = models.FloatField(default=2.5)
    interval_days = models.FloatField(default=0)
    repetitions = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_grade = models.PositiveSmallIntegerField(null=True, blank=True)
    due_at = models.DateTimeField(default=timezone.now)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["card", "member"], name="uniq_card_state")]
        indexes = [models.Index(fields=["member", "due_at"])]


class ReviewLog(models.Model):
    card = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name="reviews")
    member = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="card_reviews")
    grade = models.PositiveSmallIntegerField()
    interval_days = models.FloatField(default=0)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reviewed_at"]
        indexes = [models.Index(fields=["member", "reviewed_at"])]


class Doubt(models.Model):
    """A student question the AI couldn't answer well, routed to teachers."""

    REASON_NO_ANSWER = "no_answer"
    REASON_LOW_RATING = "low_rating"
    REASON_STUDENT = "student_request"
    REASON_CHOICES = [
        (REASON_NO_ANSWER, "AI found nothing in the notes"),
        (REASON_LOW_RATING, "Student marked the answer unhelpful"),
        (REASON_STUDENT, "Student asked a teacher"),
    ]

    STATUS_OPEN = "open"
    STATUS_ANSWERED = "answered"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_ANSWERED, "Answered"),
        (STATUS_CLOSED, "Closed"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="doubts")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="doubts")
    student = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="doubts")
    question = models.TextField()
    student_note = models.TextField(blank=True, default="")
    ai_answer = models.TextField(blank=True, default="")
    chat_message = models.ForeignKey(
        ChatMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="doubts"
    )
    session = models.ForeignKey(
        ChatSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="doubts"
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default=REASON_STUDENT)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    answer = models.TextField(blank=True, default="")
    answered_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="answered_doubts"
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    published_document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    student_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["bucket", "status", "created_at"]),
            models.Index(fields=["student", "created_at"]),
        ]

    def __str__(self):
        return f"Doubt #{self.pk} [{self.status}] {self.question[:40]}"


class ChatFeedback(models.Model):
    RATING_UP = 1
    RATING_DOWN = -1

    REASON_CHOICES = [
        ("helpful", "Helpful"),
        ("incorrect", "Incorrect"),
        ("incomplete", "Incomplete"),
        ("not_in_notes", "Not from my notes"),
        ("unclear", "Hard to understand"),
        ("other", "Other"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="chat_feedback")
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE, related_name="chat_feedback")
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="feedback")
    member = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="chat_feedback")
    rating = models.SmallIntegerField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    top_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "member"], name="uniq_feedback_per_member")]
        indexes = [models.Index(fields=["bucket", "created_at"])]
