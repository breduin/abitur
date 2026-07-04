from django.contrib import admin

from .models import MedicalUniversity, StudyDirection


class StudyDirectionInline(admin.TabularInline):
    model = StudyDirection
    extra = 0


@admin.register(MedicalUniversity)
class MedicalUniversityAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "last_synced_at", "honors_diploma_points")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [StudyDirectionInline]


@admin.register(StudyDirection)
class StudyDirectionAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "seats", "min_fetch_score")
    list_filter = ("university",)
    search_fields = ("name", "university__name")
