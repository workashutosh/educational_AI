from django.contrib import admin

from .models import MockAnswerGrade, MockAssignment, MockAttempt, MockQuestion, MockTest


class MockQuestionInline(admin.TabularInline):
    model = MockQuestion
    extra = 0


@admin.register(MockTest)
class MockTestAdmin(admin.ModelAdmin):
    list_display = ("title", "school", "status", "question_count", "created_at")
    list_filter = ("status", "school")
    inlines = [MockQuestionInline]


@admin.register(MockAssignment)
class MockAssignmentAdmin(admin.ModelAdmin):
    list_display = ("test", "student", "assigned_at")


@admin.register(MockAttempt)
class MockAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "test",
        "student",
        "score",
        "max_score",
        "percent",
        "grading_status",
        "submitted_at",
    )


@admin.register(MockAnswerGrade)
class MockAnswerGradeAdmin(admin.ModelAdmin):
    list_display = (
        "attempt",
        "question",
        "ai_score",
        "teacher_score",
        "confirmed_at",
    )
