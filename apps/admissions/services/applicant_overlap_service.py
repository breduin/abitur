from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps.universities.models import StudyDirection


@dataclass
class ApplicantOverlapRow:
    abiturient_id: str
    other_applications: str


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


def get_applicant_overlap_rows(
    direction_id: int,
    *,
    limit: int = 50,
    appearance_index: dict[str, list[tuple[str, str, int]]] | None = None,
) -> list[ApplicantOverlapRow]:
    from apps.admissions.models import ApplicantProfile

    limit = max(1, min(limit, 500))
    index = appearance_index if appearance_index is not None else build_appearance_index()
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

        rows.append(
            ApplicantOverlapRow(
                abiturient_id=profile.abiturient_id,
                other_applications=other_text,
            )
        )
    return rows


def build_overlap_context(
    user,
    *,
    direction_id: int | None,
    limit: int,
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
    if selected_direction is not None:
        rows = get_applicant_overlap_rows(selected_direction.id, limit=limit)

    return {
        "overlap_directions": directions,
        "overlap_selected_direction": selected_direction,
        "overlap_limit": limit,
        "overlap_rows": rows,
    }
