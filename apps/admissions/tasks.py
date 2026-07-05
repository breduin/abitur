from celery import shared_task

from apps.admissions.services.analytics_service import save_analytics_snapshot
from apps.admissions.services.sync_service import mark_force_sync_started, sync_all_active, sync_direction, sync_university


@shared_task
def compute_analytics():
    return save_analytics_snapshot()


@shared_task
def sync_all_active_universities(force: bool = False):
    if force:
        mark_force_sync_started()
    results = sync_all_active(force=force)
    had_success = any(item.get("status") == "success" for item in results)
    if had_success:
        compute_analytics.delay()
    return results


@shared_task
def sync_direction_task(direction_id: int, force: bool = False):
    return sync_direction(direction_id, force=force)


@shared_task
def sync_university_task(university_id: int, force: bool = False):
    return sync_university(university_id, force=force)
