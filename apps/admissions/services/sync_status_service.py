from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.admissions.models import SyncJob
from apps.admissions.services.sync_service import get_or_create_sync_job
from apps.universities.models import StudyDirection

TERMINAL_STATUSES = {
    SyncJob.Status.SUCCESS,
    SyncJob.Status.ERROR,
    SyncJob.Status.RATE_LIMITED,
}

STATUS_LABELS = {
    SyncJob.Status.PENDING: "Ожидание",
    SyncJob.Status.RUNNING: "Загрузка",
    SyncJob.Status.SUCCESS: "Готово",
    SyncJob.Status.ERROR: "Ошибка",
    SyncJob.Status.RATE_LIMITED: "Rate limit",
}


@dataclass
class DirectionSyncStatus:
    university_name: str
    direction_name: str
    status: str
    status_label: str
    records_fetched: int
    seats: int | None
    progress_percent: int | None
    is_indeterminate: bool
    last_error: str
    updated_at: str | None


def _progress_for_job(job: SyncJob, seats: int | None) -> tuple[int | None, bool]:
    if job.status == SyncJob.Status.SUCCESS:
        return 100, False

    if job.status == SyncJob.Status.RUNNING:
        if seats and seats > 0 and job.records_fetched > 0:
            percent = min(99, int(job.records_fetched * 100 / seats))
            return max(percent, 1), False
        return None, True

    if job.status == SyncJob.Status.PENDING:
        return 0, False

    if job.status in TERMINAL_STATUSES:
        if job.status == SyncJob.Status.SUCCESS:
            return 100, False
        return None, False

    return None, False


def get_sync_progress_context() -> dict[str, Any]:
    directions = (
        StudyDirection.objects.filter(
            university__is_active=True,
        )
        .exclude(university__api_config={})
        .select_related("university")
        .order_by("university__name", "name")
    )

    rows: list[DirectionSyncStatus] = []
    running_count = 0
    pending_count = 0
    completed_count = 0

    for direction in directions:
        job = get_or_create_sync_job(direction)
        progress_percent, is_indeterminate = _progress_for_job(job, direction.seats)

        if job.status == SyncJob.Status.RUNNING:
            running_count += 1
        elif job.status == SyncJob.Status.PENDING:
            pending_count += 1
        elif job.status in TERMINAL_STATUSES:
            completed_count += 1

        rows.append(
            DirectionSyncStatus(
                university_name=direction.university.name,
                direction_name=direction.name,
                status=job.status,
                status_label=STATUS_LABELS.get(job.status, job.status),
                records_fetched=job.records_fetched,
                seats=direction.seats,
                progress_percent=progress_percent,
                is_indeterminate=is_indeterminate,
                last_error=job.last_error,
                updated_at=job.updated_at.isoformat() if job.updated_at else None,
            )
        )

    total = len(rows)
    sync_is_active = running_count > 0 or pending_count > 0
    overall_percent = int(completed_count * 100 / total) if total else 0

    return {
        "sync_directions": rows,
        "sync_total": total,
        "sync_completed": completed_count,
        "sync_running": running_count,
        "sync_pending": pending_count,
        "sync_overall_percent": overall_percent,
        "sync_is_active": sync_is_active,
    }
