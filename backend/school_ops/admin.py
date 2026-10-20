from django.contrib import admin

from .models import AttendanceRecord, ParentLink, ParentProfile


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("lecture", "student", "status", "source", "updated_at")
    list_filter = ("status", "source")


class ParentLinkInline(admin.TabularInline):
    model = ParentLink
    extra = 0


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "is_active", "created_at")
    inlines = [ParentLinkInline]
