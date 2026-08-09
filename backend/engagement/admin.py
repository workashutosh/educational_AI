from django.contrib import admin

from .models import (
    EngagementActivity,
    LeaderboardSetting,
    MicroAttempt,
    MicroQuiz,
    Notification,
    NotificationPreference,
    StudentStreak,
    SubjectMastery,
    TeacherImpactEvent,
)


@admin.register(StudentStreak)
class StudentStreakAdmin(admin.ModelAdmin):
    list_display = ("member", "current_streak", "longest_streak", "last_activity_date")


@admin.register(EngagementActivity)
class EngagementActivityAdmin(admin.ModelAdmin):
    list_display = ("member", "kind", "bucket", "created_at")
    list_filter = ("kind",)


@admin.register(MicroQuiz)
class MicroQuizAdmin(admin.ModelAdmin):
    list_display = ("title", "bucket", "source_type", "status", "created_at")
    list_filter = ("status", "source_type")


@admin.register(MicroAttempt)
class MicroAttemptAdmin(admin.ModelAdmin):
    list_display = ("quiz", "student", "score", "max_score", "submitted_at")


@admin.register(SubjectMastery)
class SubjectMasteryAdmin(admin.ModelAdmin):
    list_display = ("member", "bucket", "score_0_100", "updated_at")


@admin.register(TeacherImpactEvent)
class TeacherImpactEventAdmin(admin.ModelAdmin):
    list_display = ("member", "kind", "minutes_saved", "created_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "kind", "title", "read_at", "created_at")
    list_filter = ("kind",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("member", "email_digests", "leaderboard_visible")


@admin.register(LeaderboardSetting)
class LeaderboardSettingAdmin(admin.ModelAdmin):
    list_display = ("mock_test", "enabled", "updated_at")
