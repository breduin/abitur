from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.admissions.models import AnalyticsSnapshot, ApplicantProfile, SyncJob
from apps.admissions.services.analytics_service import (
    GROUP_LABELS,
    GROUP_MUSCOVITES,
    GROUP_PETERSBURGHERS,
    GROUP_VISITORS,
    save_analytics_snapshot,
)
from apps.admissions.services.consent_modeling_service import (
    get_user_consent_projection,
)
from apps.admissions.services.position_service import PositionService
from apps.admissions.services.sync_service import mark_force_sync_started
from apps.admissions.services.sync_status_service import get_sync_progress_context
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
    sync_context = get_sync_progress_context()
    sync_warnings = MedicalUniversity.objects.filter(
        is_active=True,
    ).exclude(sync_warning="")
    rate_limited_jobs = SyncJob.objects.filter(
        status=SyncJob.Status.RATE_LIMITED,
        next_retry_at__isnull=False,
        next_retry_at__gt=timezone.now(),
    ).select_related("direction__university")

    snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()
    if snapshot is None and ApplicantProfile.objects.exists():
        save_analytics_snapshot()
        snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()

    payload = snapshot.payload if snapshot else None
    if payload and "consent_modeling" not in payload and ApplicantProfile.objects.exists():
        payload = save_analytics_snapshot()
        snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()

    consent_modeling = payload.get("consent_modeling") if payload else None

    return render(
        request,
        "admissions/dashboard.html",
        {
            "current_positions": service.get_current_positions(),
            "forecast_positions": service.get_forecast_positions(),
            "cutoff_scores": (consent_modeling or {}).get("cutoff_scores") or [],
            "consent_projection": get_user_consent_projection(
                request.user,
                consent_modeling,
            ),
            "consent_modeling_computed_at": snapshot.computed_at if snapshot else None,
            "rate_limited_jobs": rate_limited_jobs,
            "sync_warnings": sync_warnings,
            "last_data_update": _get_last_data_update(),
            **sync_context,
        },
    )


@login_required
@require_http_methods(["POST"])
def refresh_data_view(request):
    mark_force_sync_started()
    sync_all_active_universities.delay(force=True)
    sync_context = get_sync_progress_context()
    if request.headers.get("HX-Request"):
        response = render(
            request,
            "admissions/partials/refresh_started.html",
            sync_context,
        )
        return response
    return redirect("dashboard")


@login_required
def refresh_status_partial(request):
    sync_context = get_sync_progress_context()
    sync_context["rate_limited_jobs"] = SyncJob.objects.filter(
        status=SyncJob.Status.RATE_LIMITED,
    ).select_related("direction__university")
    sync_context["sync_warnings"] = MedicalUniversity.objects.filter(
        is_active=True,
    ).exclude(sync_warning="")
    return render(request, "admissions/partials/sync_progress.html", sync_context)


def _build_chart_data(payload: dict | None) -> dict | None:
    if not payload:
        return None

    overall = payload.get("overall") or {}
    return {
        "total": overall.get("total", 0),
        "overallGroups": [
            {
                "key": GROUP_PETERSBURGHERS,
                "label": GROUP_LABELS[GROUP_PETERSBURGHERS],
                "count": (overall.get(GROUP_PETERSBURGHERS) or {}).get("count", 0),
                "percent": (overall.get(GROUP_PETERSBURGHERS) or {}).get("percent", 0),
            },
            {
                "key": GROUP_MUSCOVITES,
                "label": GROUP_LABELS[GROUP_MUSCOVITES],
                "count": (overall.get(GROUP_MUSCOVITES) or {}).get("count", 0),
                "percent": (overall.get(GROUP_MUSCOVITES) or {}).get("percent", 0),
            },
            {
                "key": GROUP_VISITORS,
                "label": GROUP_LABELS[GROUP_VISITORS],
                "count": (overall.get(GROUP_VISITORS) or {}).get("count", 0),
                "percent": (overall.get(GROUP_VISITORS) or {}).get("percent", 0),
            },
        ],
        "directions": payload.get("directions") or [],
        "fullSpbCoverage": (payload.get("full_spb_coverage") or {}).get("directions") or [],
        "spbLechCoverage": (payload.get("spb_lech_coverage") or {}).get("directions") or [],
    }


@login_required
def analytics_view(request):
    snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()
    if snapshot is None and ApplicantProfile.objects.exists():
        save_analytics_snapshot()
        snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()

    payload = snapshot.payload if snapshot else None
    if payload and (
        "full_spb_coverage" not in payload
        or "spb_lech_coverage" not in payload
        or "consent_modeling" not in payload
    ):
        payload = save_analytics_snapshot()
        snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()

    return render(
        request,
        "admissions/analytics.html",
        {
            "analytics": payload,
            "chart_data": _build_chart_data(payload),
            "computed_at": snapshot.computed_at if snapshot else None,
            "group_labels": GROUP_LABELS,
            "last_data_update": _get_last_data_update(),
        },
    )
