import logging
from datetime import timedelta

from django.utils import timezone

from apps.admissions.clients.base import RateLimitError, UniversityAPIError
from apps.admissions.clients.factory import get_university_client
from apps.admissions.clients.parsers import parse_applicant_row
from apps.admissions.models import ApplicantProfile, SyncJob
from apps.universities.models import MedicalUniversity, StudyDirection

logger = logging.getLogger(__name__)


def get_or_create_sync_job(direction: StudyDirection) -> SyncJob:
    job, _ = SyncJob.objects.get_or_create(direction=direction)
    return job


def should_skip_sync(university: MedicalUniversity, force: bool) -> bool:
    if not university.api_config:
        return True
    if force:
        return False
    if not university.last_synced_at:
        return False
    next_allowed = university.last_synced_at + timedelta(seconds=university.sync_interval_seconds)
    return timezone.now() < next_allowed


def sync_direction(
    direction_id: int,
    force: bool = False,
    check_interval: bool = True,
) -> dict:
    direction = StudyDirection.objects.select_related("university").get(pk=direction_id)
    university = direction.university
    job = get_or_create_sync_job(direction)

    if not university.is_active or not university.api_config:
        return {"status": "skipped", "reason": "no_api"}

    if job.next_retry_at and job.next_retry_at > timezone.now():
        return {"status": "skipped", "reason": "rate_limited", "retry_at": job.next_retry_at}

    if check_interval and should_skip_sync(university, force):
        return {"status": "skipped", "reason": "interval"}

    job.status = SyncJob.Status.RUNNING
    job.last_error = ""
    job.save(update_fields=["status", "last_error", "updated_at"])

    provider = university.api_config.get("provider", "1spbgmu")
    client = get_university_client(university.api_config)
    records = 0

    try:
        if provider == "1spbgmu":
            client.fetch_csrf_token()

        for row in client.fetch_all_above_threshold(
            direction.filter_params,
            min_score=direction.min_fetch_score,
        ):
            parsed = parse_applicant_row(row, provider)
            if not parsed:
                continue
            ApplicantProfile.objects.update_or_create(
                direction=direction,
                abiturient_id=parsed.abiturient_id,
                defaults={
                    "position": parsed.position,
                    "sstatus_ssp": parsed.sstatus_ssp,
                    "nsummark": parsed.nsummark,
                    "npriority_ssp": parsed.npriority_ssp,
                    "has_enrollment_consent": parsed.has_enrollment_consent,
                    "raw_data": parsed.raw_data,
                },
            )
            records += 1

        if client.last_seats is not None:
            direction.seats = client.last_seats
            direction.save(update_fields=["seats"])

        if provider == "rsmu":
            warning = getattr(client, "sync_warning", "") or ""
            if university.sync_warning != warning:
                university.sync_warning = warning
                university.save(update_fields=["sync_warning"])

        job.status = SyncJob.Status.SUCCESS
        job.records_fetched = records
        job.next_retry_at = None
        job.save(update_fields=["status", "records_fetched", "next_retry_at", "updated_at"])

        return {"status": "success", "records": records}

    except RateLimitError as exc:
        retry_after = exc.retry_after or 3600
        job.status = SyncJob.Status.RATE_LIMITED
        job.next_retry_at = timezone.now() + timedelta(seconds=retry_after)
        job.last_error = str(exc)
        job.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
        return {"status": "rate_limited", "retry_after": retry_after}

    except UniversityAPIError as exc:
        job.status = SyncJob.Status.ERROR
        job.last_error = str(exc)
        job.save(update_fields=["status", "last_error", "updated_at"])
        logger.exception("Sync failed for direction %s", direction_id)
        return {"status": "error", "error": str(exc)}


def sync_university(university_id: int, force: bool = False) -> list[dict]:
    university = MedicalUniversity.objects.get(pk=university_id)
    if not university.is_active or not university.api_config:
        return [{"university_id": university_id, "status": "skipped", "reason": "no_api"}]

    if should_skip_sync(university, force):
        return [{"university_id": university_id, "status": "skipped", "reason": "interval"}]

    results = []
    had_success = False
    for direction in university.directions.all():
        result = sync_direction(direction.id, force=force, check_interval=False)
        results.append({"direction_id": direction.id, **result})
        if result.get("status") == "success":
            had_success = True

    if had_success:
        university.last_synced_at = timezone.now()
        university.save(update_fields=["last_synced_at"])

    return results


def sync_all_active(force: bool = False) -> list[dict]:
    results = []
    universities = MedicalUniversity.objects.filter(is_active=True).exclude(api_config={})
    for university in universities:
        results.extend(sync_university(university.id, force=force))
    return results
