from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from apps.admissions.models import ApplicantProfile, SyncJob
from apps.universities.models import MedicalUniversity, StudyDirection

GROUP_PETERSBURGHERS = "petersburgers"
GROUP_MUSCOVITES = "moscovites"
GROUP_VISITORS = "visitors"

GROUP_LABELS = {
    GROUP_PETERSBURGHERS: "Петербуржцы",
    GROUP_MUSCOVITES: "Москвичи",
    GROUP_VISITORS: "Приезжие",
}


@dataclass
class GroupStat:
    count: int
    percent: float

    def as_dict(self) -> dict[str, Any]:
        return {"count": self.count, "percent": self.percent}


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count * 100 / total, 1)


def _classify_abiturient_cities(cities: set[str]) -> str | None:
    has_spb = MedicalUniversity.City.SPB in cities
    has_msk = MedicalUniversity.City.MSK in cities
    if has_spb and has_msk:
        return GROUP_VISITORS
    if has_spb:
        return GROUP_PETERSBURGHERS
    if has_msk:
        return GROUP_MUSCOVITES
    return None


def _build_abiturient_groups() -> tuple[dict[str, str], dict[str, GroupStat]]:
    abiturient_cities: dict[str, set[str]] = defaultdict(set)
    for abiturient_id, city in ApplicantProfile.objects.filter(
        direction__university__is_active=True,
        direction__university__city__in=[
            MedicalUniversity.City.SPB,
            MedicalUniversity.City.MSK,
        ],
    ).values_list("abiturient_id", "direction__university__city"):
        abiturient_cities[abiturient_id].add(city)

    abiturient_group: dict[str, str] = {}
    overall_counts = {
        GROUP_PETERSBURGHERS: 0,
        GROUP_MUSCOVITES: 0,
        GROUP_VISITORS: 0,
    }
    for abiturient_id, cities in abiturient_cities.items():
        group = _classify_abiturient_cities(cities)
        if not group:
            continue
        abiturient_group[abiturient_id] = group
        overall_counts[group] += 1

    total = len(abiturient_group)
    overall = {
        key: GroupStat(count=overall_counts[key], percent=_percent(overall_counts[key], total))
        for key in overall_counts
    }
    return abiturient_group, {
        "total": total,
        GROUP_PETERSBURGHERS: overall[GROUP_PETERSBURGHERS],
        GROUP_MUSCOVITES: overall[GROUP_MUSCOVITES],
        GROUP_VISITORS: overall[GROUP_VISITORS],
    }


def _groups_for_direction(
    city: str,
    abiturient_ids: set[str],
    abiturient_group: dict[str, str],
) -> dict[str, GroupStat]:
    total = len(abiturient_ids)
    counts = {
        GROUP_PETERSBURGHERS: 0,
        GROUP_MUSCOVITES: 0,
        GROUP_VISITORS: 0,
    }
    for abiturient_id in abiturient_ids:
        group = abiturient_group.get(abiturient_id)
        if group:
            counts[group] += 1

    if city == MedicalUniversity.City.SPB:
        relevant = (GROUP_PETERSBURGHERS, GROUP_VISITORS)
    elif city == MedicalUniversity.City.MSK:
        relevant = (GROUP_MUSCOVITES, GROUP_VISITORS)
    else:
        relevant = ()

    return {
        key: GroupStat(count=counts[key], percent=_percent(counts[key], total))
        for key in relevant
    }


def compute_analytics() -> dict[str, Any]:
    abiturient_group, overall = _build_abiturient_groups()

    applications_by_direction = {
        job.direction_id: job.records_fetched
        for job in SyncJob.objects.select_related("direction")
    }

    profiles_by_direction: dict[int, set[str]] = defaultdict(set)
    for direction_id, abiturient_id in ApplicantProfile.objects.filter(
        direction__university__is_active=True,
    ).values_list("direction_id", "abiturient_id"):
        profiles_by_direction[direction_id].add(abiturient_id)

    directions_payload = []
    for direction in StudyDirection.objects.filter(
        university__is_active=True,
    ).select_related("university").order_by("university__name", "name"):
        university = direction.university
        abiturient_ids = profiles_by_direction.get(direction.id, set())
        groups = _groups_for_direction(university.city, abiturient_ids, abiturient_group)
        directions_payload.append(
            {
                "university_name": university.name,
                "city": university.city,
                "city_label": university.get_city_display() if university.city else "—",
                "direction_name": direction.name,
                "seats": direction.seats,
                "applications_count": applications_by_direction.get(direction.id),
                "direction_total": len(abiturient_ids),
                "groups": [
                    {
                        "key": key,
                        "label": GROUP_LABELS[key],
                        **groups[key].as_dict(),
                    }
                    for key in groups
                ],
            }
        )

    return {
        "computed_at": timezone.now().isoformat(),
        "overall": {
            "total": overall["total"],
            GROUP_PETERSBURGHERS: overall[GROUP_PETERSBURGHERS].as_dict(),
            GROUP_MUSCOVITES: overall[GROUP_MUSCOVITES].as_dict(),
            GROUP_VISITORS: overall[GROUP_VISITORS].as_dict(),
        },
        "directions": directions_payload,
    }


def save_analytics_snapshot() -> dict[str, Any]:
    from apps.admissions.models import AnalyticsSnapshot

    payload = compute_analytics()
    snapshot = AnalyticsSnapshot.objects.create(payload=payload)
    AnalyticsSnapshot.objects.filter(pk__lt=snapshot.pk).delete()
    return payload


def get_latest_analytics() -> dict[str, Any] | None:
    from apps.admissions.models import AnalyticsSnapshot

    snapshot = AnalyticsSnapshot.objects.order_by("-computed_at").first()
    if snapshot:
        return snapshot.payload
    return None
