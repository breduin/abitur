from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps.universities.models import StudyDirection


NOT_ENROLLED_LABEL = "Не зачислен по модели"
NO_MODELING_LABEL = "Моделирование не рассчитано"


@dataclass
class ApplicantOverlapRow:
    abiturient_id: str
    position: int
    nsummark: int | None
    other_applications: str
    modeling_result: str


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


def build_appearance_index() -> dict[str, list[tuple[str, str, int]]]:
    from apps.admissions.models import ApplicantProfile

    index: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for abiturient_id, direction_id, direction_name, university_name in ApplicantProfile.objects.filter(
        direction__university__is_active=True,
    ).values_list(
        "abiturient_id",
        "direction_id",
        "direction__name",
        "direction__university__name",
    ):
        index[abiturient_id].append((university_name, direction_name, direction_id))
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


def get_applicant_overlap_rows(
    direction_id: int,
    *,
    limit: int = 50,
    appearance_index: dict[str, list[tuple[str, str, int]]] | None = None,
    enrollment_labels: dict[str, str] | None = None,
    modeling_available: bool = True,
) -> list[ApplicantOverlapRow]:
    from apps.admissions.models import ApplicantProfile

    limit = max(1, min(limit, 500))
    index = appearance_index if appearance_index is not None else build_appearance_index()
    labels = enrollment_labels if enrollment_labels is not None else {}
    profiles = ApplicantProfile.objects.filter(direction_id=direction_id).order_by("position")[:limit]

    rows: list[ApplicantOverlapRow] = []
    for profile in profiles:
        other_labels = sorted(
            {
                f"{university_name} — {direction_name}"
                for university_name, direction_name, other_direction_id in index.get(
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
            )
        )
    return rows


def build_overlap_context(
    user,
    *,
    direction_id: int | None,
    limit: int,
    consent_modeling: dict[str, Any] | None = None,
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
    enrollment_labels = build_enrollment_labels_by_abiturient(consent_modeling)
    if selected_direction is not None:
        rows = get_applicant_overlap_rows(
            selected_direction.id,
            limit=limit,
            enrollment_labels=enrollment_labels,
            modeling_available=consent_modeling is not None,
        )

    return {
        "overlap_directions": directions,
        "overlap_selected_direction": selected_direction,
        "overlap_limit": limit,
        "overlap_rows": rows,
    }
