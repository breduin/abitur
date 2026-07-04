from celery import shared_task

from apps.admissions.services.sync_service import sync_all_active, sync_direction, sync_university


@shared_task
def sync_all_active_universities(force: bool = False):
    return sync_all_active(force=force)


@shared_task
def sync_direction_task(direction_id: int, force: bool = False):
    return sync_direction(direction_id, force=force)


@shared_task
def sync_university_task(university_id: int, force: bool = False):
    return sync_university(university_id, force=force)
