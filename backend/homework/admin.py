from django.contrib import admin

from .models import Assignment, AssignmentTarget, Submission, SubmissionFile


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "bucket", "status", "due_at", "created_at")
    list_filter = ("status",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "status", "ai_status", "ai_score", "teacher_score", "submitted_at")
    list_filter = ("status", "ai_status")


admin.site.register(AssignmentTarget)
admin.site.register(SubmissionFile)
