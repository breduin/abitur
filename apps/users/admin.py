from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("abiturient_id", "is_verified", "ege_total_score", "has_honors_diploma", "date_joined")
    list_filter = ("is_verified", "has_honors_diploma", "is_staff")
    search_fields = ("abiturient_id",)
    filter_horizontal = ("applied_universities",)
    fieldsets = (
        (None, {"fields": ("abiturient_id", "is_verified", "is_active", "is_staff", "is_superuser")}),
        ("Профиль", {"fields": ("ege_total_score", "has_honors_diploma", "applied_universities")}),
    )
