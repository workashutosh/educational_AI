from __future__ import annotations

from django.db import models
from django.utils import timezone

from ingestion.models import School, SchoolMembership, SubjectBucket


class Lecture(models.Model):
    """
    A live / scheduled lecture tied to an AI Bucket.

    Teams meeting is created via Microsoft Graph when configured; otherwise
    teachers can paste a join URL manually.
    """

    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_ENDED = "ended"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_LIVE, "Live"),
        (STATUS_ENDED, "Ended"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="lectures")
    bucket = models.ForeignKey(
        SubjectBucket, on_delete=models.CASCADE, related_name="lectures"
    )
    created_by = models.ForeignKey(
        SchoolMembership,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_lectures",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    # Microsoft Teams / Graph
    teams_meeting_id = models.CharField(max_length=255, blank=True)
    teams_join_url = models.URLField(max_length=1000, blank=True)
    teams_organizer_upn = models.CharField(max_length=255, blank=True)
    teams_created = models.BooleanField(default=False)
    teams_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["bucket", "starts_at"]),
        ]

    def __str__(self):
        return f"{self.title} [{self.status}]"

    def mark_live(self):
        self.status = self.STATUS_LIVE
        self.save(update_fields=["status", "updated_at"])

    def mark_ended(self):
        self.status = self.STATUS_ENDED
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "ended_at", "updated_at"])


class MicrosoftAccountLink(models.Model):
    """
    Delegated Microsoft Graph tokens for a teacher/manager.
    Used to create Teams meetings as that user (/me/onlineMeetings).
    """

    member = models.OneToOneField(
        SchoolMembership,
        on_delete=models.CASCADE,
        related_name="microsoft_account",
    )
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    ms_user_id = models.CharField(max_length=64, blank=True)
    ms_upn = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"MS link for {self.member_id} ({self.ms_upn or 'unknown'})"
