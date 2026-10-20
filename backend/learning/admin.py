from django.contrib import admin

from .models import CardState, ChatFeedback, Doubt, Flashcard, FlashcardDeck, ReviewLog


@admin.register(FlashcardDeck)
class FlashcardDeckAdmin(admin.ModelAdmin):
    list_display = ("title", "bucket", "owner", "visibility", "created_at")


@admin.register(Doubt)
class DoubtAdmin(admin.ModelAdmin):
    list_display = ("id", "bucket", "student", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("question",)


@admin.register(ChatFeedback)
class ChatFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "bucket", "member", "rating", "reason", "top_score", "created_at")
    list_filter = ("rating", "reason")


admin.site.register(Flashcard)
admin.site.register(CardState)
admin.site.register(ReviewLog)
