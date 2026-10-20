from django.contrib import admin

from .models import BankImportJob, PaperItem, PaperSection, QuestionItem, QuestionPaper, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "bucket", "source", "order")
    list_filter = ("source",)
    search_fields = ("name",)


@admin.register(QuestionItem)
class QuestionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "bucket", "topic", "qtype", "difficulty", "source", "times_used")
    list_filter = ("qtype", "difficulty", "source", "is_archived")
    search_fields = ("prompt",)


class PaperSectionInline(admin.TabularInline):
    model = PaperSection
    extra = 0


@admin.register(QuestionPaper)
class QuestionPaperAdmin(admin.ModelAdmin):
    list_display = ("title", "bucket", "status", "created_at")
    inlines = [PaperSectionInline]


admin.site.register(PaperItem)
admin.site.register(BankImportJob)
