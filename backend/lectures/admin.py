from django.contrib import admin

from .models import Lecture


@admin.register(Lecture)
class LectureAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "school",
        "bucket",
        "status",
        "starts_at",
        "teams_created",
        "created_by",
    )
    list_filter = ("status", "teams_created", "school")
    search_fields = ("title", "teams_meeting_id", "teams_join_url")
