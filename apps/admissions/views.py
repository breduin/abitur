from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.admissions.models import SyncJob
from apps.admissions.services.position_service import PositionService
from apps.admissions.tasks import sync_all_active_universities
from apps.universities.models import MedicalUniversity


def _get_last_data_update():
    return MedicalUniversity.objects.filter(
        is_active=True,
        last_synced_at__isnull=False,
    ).aggregate(last=Max("last_synced_at"))["last"]


@login_required
def dashboard_view(request):
    service = PositionService(request.user)
    rate_limited_jobs = SyncJob.objects.filter(
        status=SyncJob.Status.RATE_LIMITED,
        next_retry_at__isnull=False,
        next_retry_at__gt=timezone.now(),
    ).select_related("direction__university")

    return render(
        request,
        "admissions/dashboard.html",
        {
            "current_positions": service.get_current_positions(),
            "forecast_positions": service.get_forecast_positions(),
            "rate_limited_jobs": rate_limited_jobs,
            "last_data_update": _get_last_data_update(),
        },
    )


@login_required
@require_http_methods(["POST"])
def refresh_data_view(request):
    sync_all_active_universities.delay(force=True)
    if request.headers.get("HX-Request"):
        return HttpResponse(
            '<div class="alert alert-info">Обновление запущено. Данные появятся через несколько минут.</div>'
        )
    return redirect("dashboard")


@login_required
def refresh_status_partial(request):
    jobs = SyncJob.objects.filter(
        status=SyncJob.Status.RATE_LIMITED,
    ).select_related("direction__university")
    return render(request, "admissions/partials/sync_status.html", {"rate_limited_jobs": jobs})
