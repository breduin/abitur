from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps.universities.models import MedicalUniversity, StudyDirection


NOT_ENROLLED_LABEL = "Не зачислен по модели"
NO_MODELING_LABEL = "Моделирование не рассчитано"

# appearance index entry: (university_name, direction_name, direction_id, university_id, city)
AppearanceEntry = tuple[str, str, int, int, str]


@dataclass
class ApplicantOverlapRow:
    abiturient_id: str
    position: int
    nsummark: int | None
    other_applications: str
    modeling_result: str
    has_enrollment_consent: bool


@dataclass
class OverlapStat:
    count: int
    percent: float

    def as_dict(self) -> dict[str, Any]:
        return {"count": self.count, "percent": self.percent}


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count * 100 / total, 1)


def empty_overlap_stats() -> dict[str, Any]:
    zero = OverlapStat(count=0, percent=0.0).as_dict()
    return {
        "total": 0,
        "only_this_university": zero,
        "only_spb": zero,
        "spb_and_msk": zero,
    }


def get_user_applied_directions(user) -> list[StudyDirection]:
    university_ids = user.applied_universities.filter(is_active=True).values_list("id", flat=True)
    return list(
        StudyDirection.objects.filter(
            university_id__in=university_ids,
            university__is_active=True,
        )
        .select_related("university")
        .order_by("university__name", "name")
    )


def build_appearance_index() -> dict[str, list[AppearanceEntry]]:
    from apps.admissions.models import ApplicantProfile

    index: dict[str, list[AppearanceEntry]] = defaultdict(list)
    for (
        abiturient_id,
        direction_id,
        direction_name,
        university_name,
        university_id,
        city,
    ) in ApplicantProfile.objects.filter(
        direction__university__is_active=True,
    ).values_list(
        "abiturient_id",
        "direction_id",
        "direction__name",
        "direction__university__name",
        "direction__university_id",
        "direction__university__city",
    ):
        index[abiturient_id].append(
            (university_name, direction_name, direction_id, university_id, city or "")
        )
    return index


def build_enrollment_labels_by_abiturient(
    consent_modeling: dict[str, Any] | None,
) -> dict[str, str]:
    if not consent_modeling:
        return {}

    from apps.universities.models import StudyDirection

    direction_ids = [
        int(direction_id)
        for direction_id in (consent_modeling.get("enrollment_by_direction") or {})
    ]
    directions_by_id = {
        direction.id: direction
        for direction in StudyDirection.objects.filter(id__in=direction_ids).select_related(
            "university"
        )
    }

    labels: dict[str, str] = {}
    for direction_id_str, abiturient_ids in (
        consent_modeling.get("enrollment_by_direction") or {}
    ).items():
        direction = directions_by_id.get(int(direction_id_str))
        if not direction:
            continue
        label = f"{direction.university.name} — {direction.name}"
        for abiturient_id in abiturient_ids:
            labels[abiturient_id] = label
    return labels


def get_enrolled_abiturient_ids_for_direction(
    consent_modeling: dict[str, Any] | None,
    direction_id: int,
) -> set[str]:
    if not consent_modeling:
        return set()
    enrollment = consent_modeling.get("enrollment_by_direction") or {}
    return set(enrollment.get(str(direction_id)) or [])


def compute_overlap_stats(
    rows: list[ApplicantOverlapRow],
    *,
    selected_university_id: int,
    appearance_index: dict[str, list[AppearanceEntry]],
) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return empty_overlap_stats()

    only_this_university = 0
    only_spb = 0
    spb_and_msk = 0

    for row in rows:
        appearances = appearance_index.get(row.abiturient_id, [])
        university_ids = {entry[3] for entry in appearances}
        cities = {entry[4] for entry in appearances if entry[4]}

        if university_ids == {selected_university_id}:
            only_this_university += 1

        has_spb = MedicalUniversity.City.SPB in cities
        has_msk = MedicalUniversity.City.MSK in cities
        if has_spb and not has_msk:
            only_spb += 1
        if has_spb and has_msk:
            spb_and_msk += 1

    return {
        "total": total,
        "only_this_university": OverlapStat(
            count=only_this_university,
            percent=_percent(only_this_university, total),
        ).as_dict(),
        "only_spb": OverlapStat(
            count=only_spb,
            percent=_percent(only_spb, total),
        ).as_dict(),
        "spb_and_msk": OverlapStat(
            count=spb_and_msk,
            percent=_percent(spb_and_msk, total),
        ).as_dict(),
    }


def get_applicant_overlap_rows(
    direction_id: int,
    *,
    limit: int = 50,
    appearance_index: dict[str, list[AppearanceEntry]] | None = None,
    enrollment_labels: dict[str, str] | None = None,
    modeling_available: bool = True,
    enrolled_only: bool = False,
    consent_modeling: dict[str, Any] | None = None,
) -> list[ApplicantOverlapRow]:
    from apps.admissions.models import ApplicantProfile

    limit = max(1, min(limit, 500))
    index = appearance_index if appearance_index is not None else build_appearance_index()
    labels = enrollment_labels if enrollment_labels is not None else {}

    profiles_qs = ApplicantProfile.objects.filter(direction_id=direction_id)
    if enrolled_only:
        enrolled_ids = get_enrolled_abiturient_ids_for_direction(consent_modeling, direction_id)
        if not enrolled_ids:
            return []
        profiles_qs = profiles_qs.filter(abiturient_id__in=enrolled_ids)

    profiles = profiles_qs.order_by("position")[:limit]

    rows: list[ApplicantOverlapRow] = []
    for profile in profiles:
        other_labels = sorted(
            {
                f"{university_name} — {direction_name}"
                for university_name, direction_name, other_direction_id, _university_id, _city in index.get(
                    profile.abiturient_id, []
                )
                if other_direction_id != direction_id
            }
        )
        if other_labels:
            other_text = "; ".join(other_labels)
        else:
            other_text = "Только в выбранном списке"

        if not modeling_available:
            modeling_result = NO_MODELING_LABEL
        else:
            modeling_result = labels.get(profile.abiturient_id, NOT_ENROLLED_LABEL)

        rows.append(
            ApplicantOverlapRow(
                abiturient_id=profile.abiturient_id,
                position=profile.position,
                nsummark=profile.nsummark,
                other_applications=other_text,
                modeling_result=modeling_result,
                has_enrollment_consent=profile.has_enrollment_consent,
            )
        )
    return rows


def build_overlap_context(
    user,
    *,
    direction_id: int | None,
    limit: int,
    consent_modeling: dict[str, Any] | None = None,
    enrolled_only: bool = False,
) -> dict[str, Any]:
    directions = get_user_applied_directions(user)
    selected_direction = None
    if directions:
        if direction_id is not None:
            selected_direction = next(
                (direction for direction in directions if direction.id == direction_id),
                None,
            )
        if selected_direction is None:
            selected_direction = directions[0]

    rows: list[ApplicantOverlapRow] = []
    stats = empty_overlap_stats()
    enrollment_labels = build_enrollment_labels_by_abiturient(consent_modeling)
    if selected_direction is not None:
        appearance_index = build_appearance_index()
        rows = get_applicant_overlap_rows(
            selected_direction.id,
            limit=limit,
            appearance_index=appearance_index,
            enrollment_labels=enrollment_labels,
            modeling_available=consent_modeling is not None,
            enrolled_only=enrolled_only,
            consent_modeling=consent_modeling,
        )
        stats = compute_overlap_stats(
            rows,
            selected_university_id=selected_direction.university_id,
            appearance_index=appearance_index,
        )

    return {
        "overlap_directions": directions,
        "overlap_selected_direction": selected_direction,
        "overlap_limit": limit,
        "overlap_enrolled_only": enrolled_only,
        "overlap_rows": rows,
        "overlap_stats": stats,
    }
