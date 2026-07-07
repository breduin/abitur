from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.admissions.models import AnalyticsSnapshot, ApplicantProfile, SyncJob
from apps.admissions.services.analytics_service import (
    GROUP_COLORS,
    GROUP_LABELS,
    GROUP_MUSCOVITES,
    GROUP_PETERSBURGHERS,
    GROUP_VISITORS,
    save_analytics_snapshot,
)
from apps.admissions.services.applicant_overlap_service import build_overlap_context
from apps.admissions.services.consent_modeling_service import (
    get_user_consent_projection,
    get_user_hypothetical_consent_projection,
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


def _sync_page_context() -> dict:
    sync_context = get_sync_progress_context()
    sync_context["rate_limited_jobs"] = SyncJob.objects.filter(
        status=SyncJob.Status.RATE_LIMITED,
        next_retry_at__isnull=False,
        next_retry_at__gt=timezone.now(),
    ).select_related("direction__university")
    sync_context["sync_warnings"] = MedicalUniversity.objects.filter(
        is_active=True,
    ).exclude(sync_warning="")
    sync_context["last_data_update"] = _get_last_data_update()
    return sync_context


@login_required
def dashboard_view(request):
    service = PositionService(request.user)

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
            "cutoff_scores": (consent_modeling or {}).get("cutoff_scores") or [],
            "consent_projection": get_user_consent_projection(
                request.user,
                consent_modeling,
            ),
            "hypothetical_consent_projection": get_user_hypothetical_consent_projection(
                request.user,
                consent_modeling,
            ),
            "consent_modeling_computed_at": snapshot.computed_at if snapshot else None,
            "last_data_update": _get_last_data_update(),
        },
    )


@login_required
def sync_status_view(request):
    return render(
        request,
        "admissions/sync_status.html",
        _sync_page_context(),
    )


@login_required
@require_http_methods(["POST"])
def refresh_data_view(request):
    mark_force_sync_started()
    sync_all_active_universities.delay(force=True)
    sync_context = _sync_page_context()
    if request.headers.get("HX-Request"):
        response = render(
            request,
            "admissions/partials/refresh_started.html",
            sync_context,
        )
        return response
    return redirect("sync_status")


@login_required
def refresh_status_partial(request):
    return render(request, "admissions/partials/sync_progress.html", _sync_page_context())


def _build_overall_groups(payload: dict | None) -> list[dict]:
    if not payload:
        return []
    overall = payload.get("overall") or {}
    groups = []
    for key in (GROUP_PETERSBURGHERS, GROUP_MUSCOVITES, GROUP_VISITORS):
        stat = overall.get(key) or {}
        groups.append(
            {
                "key": key,
                "label": GROUP_LABELS[key],
                "count": stat.get("count", 0),
                "percent": stat.get("percent", 0),
                "color": GROUP_COLORS[key],
            }
        )
    return groups


def _build_chart_data(payload: dict | None) -> dict | None:
    if not payload:
        return None

    overall_groups = _build_overall_groups(payload)
    return {
        "total": overall_groups and payload.get("overall", {}).get("total", 0) or 0,
        "overallGroups": overall_groups,
        "directions": payload.get("directions") or [],
        "fullSpbCoverage": (payload.get("full_spb_coverage") or {}).get("directions") or [],
        "spbLechCoverage": (payload.get("spb_lech_coverage") or {}).get("directions") or [],
    }


def _ensure_analytics_payload():
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

    return payload, snapshot


def _parse_overlap_params(request) -> tuple[int | None, int, bool]:
    try:
        overlap_limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        overlap_limit = 50

    selected_direction_id = request.GET.get("direction_id")
    try:
        direction_id = int(selected_direction_id) if selected_direction_id else None
    except (TypeError, ValueError):
        direction_id = None

    enrolled_only = request.GET.get("enrolled_only") in ("1", "true", "on")
    return direction_id, overlap_limit, enrolled_only


def _build_overlap_response_context(user, request) -> dict:
    payload, _snapshot = _ensure_analytics_payload()
    direction_id, overlap_limit, enrolled_only = _parse_overlap_params(request)
    return build_overlap_context(
        user,
        direction_id=direction_id,
        limit=overlap_limit,
        consent_modeling=(payload or {}).get("consent_modeling"),
        enrolled_only=enrolled_only,
    )


@login_required
def analytics_view(request):
    payload, snapshot = _ensure_analytics_payload()
    overlap_context = _build_overlap_response_context(request.user, request)

    return render(
        request,
        "admissions/analytics.html",
        {
            "analytics": payload,
            "chart_data": _build_chart_data(payload),
            "overall_groups": _build_overall_groups(payload),
            "computed_at": snapshot.computed_at if snapshot else None,
            "last_data_update": _get_last_data_update(),
            **overlap_context,
        },
    )


@login_required
def overlap_partial_view(request):
    return render(
        request,
        "admissions/partials/overlap_content.html",
        _build_overlap_response_context(request.user, request),
    )
