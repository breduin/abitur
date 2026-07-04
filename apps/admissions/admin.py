from django.contrib import admin

from .models import ApplicantProfile, SyncJob


@admin.register(ApplicantProfile)
class ApplicantProfileAdmin(admin.ModelAdmin):
    list_display = (
        "abiturient_id",
        "direction",
        "position",
        "nsummark",
        "npriority_ssp",
        "has_enrollment_consent",
        "fetched_at",
    )
    list_filter = ("direction__university", "direction")
    search_fields = ("abiturient_id",)


@admin.register(SyncJob)
class SyncJobAdmin(admin.ModelAdmin):
    list_display = ("direction", "status", "records_fetched", "next_retry_at", "updated_at")
    list_filter = ("status",)
