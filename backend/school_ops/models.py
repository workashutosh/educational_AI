"""
Attendance (per lecture) and the parent portal.

Parents are deliberately NOT SchoolMembership rows: every existing endpoint
gates on IsSchoolMember, so a parent account can only ever reach the
read-only /api/parent/ endpoints that check ParentLink explicitly.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from ingestion.models import School, SchoolMembership


class AttendanceRecord(models.Model):
    STATUS_PRESENT = "present"
    STATUS_LATE = "late"
    STATUS_ABSENT = "absent"
    STATUS_EXCUSED = "excused"
    STATUS_CHOICES = [
        (STATUS_PRESENT, "Present"),
        (STATUS_LATE, "Late"),
        (STATUS_ABSENT, "Absent"),
        (STATUS_EXCUSED, "Excused"),
    ]
    ATTENDED = {STATUS_PRESENT, STATUS_LATE}

    SOURCE_AUTO = "auto"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [(SOURCE_AUTO, "Joined lecture room"), (SOURCE_MANUAL, "Marked by teacher")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="attendance_records")
    lecture = models.ForeignKey(
        "lectures.Lecture", on_delete=models.CASCADE, related_name="attendance_records"
    )
    student = models.ForeignKey(
        SchoolMembership, on_delete=models.CASCADE, related_name="attendance_records"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_AUTO)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    marked_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lecture", "student"], name="uniq_attendance_per_lecture")
        ]
        indexes = [models.Index(fields=["student", "updated_at"])]


class ParentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parent_profile"
    )
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="parents")
    phone = models.CharField(max_length=32, blank=True, default="")
    weekly_email = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Parent {self.user.username} ({self.school.name})"


class ParentLink(models.Model):
    RELATION_CHOICES = [
        ("mother", "Mother"),
        ("father", "Father"),
        ("guardian", "Guardian"),
        ("other", "Other"),
    ]

    parent = models.ForeignKey(ParentProfile, on_delete=models.CASCADE, related_name="links")
    student = models.ForeignKey(
        SchoolMembership, on_delete=models.CASCADE, related_name="parent_links"
    )
    relationship = models.CharField(max_length=16, choices=RELATION_CHOICES, default="guardian")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["parent", "student"], name="uniq_parent_student")]
