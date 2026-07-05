from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from apps.admissions.models import ApplicantProfile
from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import (
    ALMAZOV_NAME,
    FIRST_MED_NAME,
    MSU_NAME,
    PEDIATRIC_NAME,
    PIROGOV_NAME,
    SECHENOV_NAME,
    SPBU_NAME,
    SZGMU_NAME,
)

LECH_DIRECTION_NAME = "Лечебное дело"
PED_DIRECTION_NAME = "Педиатрия"

UNIVERSITY_RANK: dict[str, int] = {
    SECHENOV_NAME: 100,
    PIROGOV_NAME: 101,
    MSU_NAME: 102,
    FIRST_MED_NAME: 200,
    ALMAZOV_NAME: 201,
    SZGMU_NAME: 202,
    PEDIATRIC_NAME: 203,
    SPBU_NAME: 204,
}


@dataclass
class ApplicationEntry:
    abiturient_id: str
    direction_id: int
    university_id: int
    university_name: str
    direction_name: str
    position: int
    nsummark: int
    npriority_ssp: int
    is_olympiad: bool
    seats: int | None


@dataclass
class ConsentProjectionResult:
    university_name: str
    direction_name: str
    direction_id: int
    seats: int | None
    submission_position: int | None
    competitive_position: int | None
    enrollment_position: int | None
    nsummark: int | None
    npriority_ssp: int | None
    cutoff_score: int | None
    is_admitted: bool
    is_applied: bool
    status: str
    status_label: str
    consent_university_name: str | None = None
    enrolled_direction_name: str | None = None

    @property
    def position(self) -> int | None:
        if self.enrollment_position is not None:
            return self.enrollment_position
        if self.competitive_position is not None:
            return self.competitive_position
        return self.submission_position

    @property
    def position_label(self) -> str:
        if self.enrollment_position is not None:
            return "зачисление"
        if self.competitive_position is not None:
            return "конкурсный"
        if self.submission_position is not None:
            return "поданные заявления"
        return ""


def _is_olympiad(profile: ApplicantProfile) -> bool:
    if profile.nsummark == 0:
        return True
    raw_data = profile.raw_data or {}
    if raw_data.get("_is_bvi"):
        return True
    if raw_data.get("noExam"):
        return True
    return False


def _university_rank(university_name: str) -> int:
    return UNIVERSITY_RANK.get(university_name, 9999)


def _competitive_sort_key(entry: ApplicationEntry) -> tuple[int, int, int]:
    return (
        0 if entry.is_olympiad else 1,
        -entry.nsummark,
        entry.position,
    )


def _load_applications() -> tuple[
    dict[str, list[ApplicationEntry]],
    dict[int, StudyDirection],
    dict[int, MedicalUniversity],
]:
    directions = {
        direction.id: direction
        for direction in StudyDirection.objects.filter(
            university__is_active=True,
        ).select_related("university")
    }
    universities = {direction.university_id: direction.university for direction in directions.values()}

    by_abiturient: dict[str, list[ApplicationEntry]] = defaultdict(list)
    for profile in ApplicantProfile.objects.filter(
        direction__university__is_active=True,
    ).select_related("direction__university"):
        direction = directions[profile.direction_id]
        university = direction.university
        by_abiturient[profile.abiturient_id].append(
            ApplicationEntry(
                abiturient_id=profile.abiturient_id,
                direction_id=direction.id,
                university_id=university.id,
                university_name=university.name,
                direction_name=direction.name,
                position=profile.position,
                nsummark=profile.nsummark,
                npriority_ssp=profile.npriority_ssp,
                is_olympiad=_is_olympiad(profile),
                seats=direction.seats,
            )
        )

    return by_abiturient, directions, universities


def _is_passing(entry: ApplicationEntry) -> bool:
    if entry.seats is None or entry.seats <= 0:
        return False
    return entry.position <= entry.seats


def _passing_gap(entry: ApplicationEntry) -> int:
    seats = entry.seats or 0
    return entry.position - seats


def _choose_consent_university(applications: list[ApplicationEntry]) -> int | None:
    if not applications:
        return None

    priority_one = [entry for entry in applications if entry.npriority_ssp == 1]
    if not priority_one:
        priority_one = applications

    passing = [entry for entry in priority_one if _is_passing(entry)]
    if passing:
        best = min(
            passing,
            key=lambda entry: (_university_rank(entry.university_name), entry.position),
        )
        return best.university_id

    best = min(
        priority_one,
        key=lambda entry: (_passing_gap(entry), _university_rank(entry.university_name)),
    )
    return best.university_id


def _build_competitive_lists(
    by_abiturient: dict[str, list[ApplicationEntry]],
    consent_by_abiturient: dict[str, int],
) -> dict[int, list[ApplicationEntry]]:
    competitive: dict[int, list[ApplicationEntry]] = defaultdict(list)
    for abiturient_id, applications in by_abiturient.items():
        consent_university_id = consent_by_abiturient.get(abiturient_id)
        if consent_university_id is None:
            continue
        for entry in applications:
            if entry.university_id == consent_university_id:
                competitive[entry.direction_id].append(entry)

    for direction_id, entries in competitive.items():
        competitive[direction_id] = sorted(entries, key=_competitive_sort_key)

    return competitive


def _active_competitive_list(
    entries: list[ApplicationEntry],
    enrolled_ids: set[str],
) -> list[ApplicationEntry]:
    return [entry for entry in entries if entry.abiturient_id not in enrolled_ids]


def _try_enroll_on_pediatrics(
    applicant: ApplicationEntry,
    ped_list: list[ApplicationEntry],
    enrolled_ped: list[ApplicationEntry],
    enrolled_ids: set[str],
    seats_ped: int,
) -> bool:
    active_ped = _active_competitive_list(ped_list, enrolled_ids)
    ped_rank = None
    for index, entry in enumerate(active_ped, start=1):
        if entry.abiturient_id == applicant.abiturient_id:
            ped_rank = index
            break

    if ped_rank is None:
        return False

    temp_enrolled_ped = list(enrolled_ped)
    temp_enrolled_ids = set(enrolled_ids)

    for entry in active_ped:
        if len(temp_enrolled_ped) >= seats_ped:
            break
        if entry.abiturient_id == applicant.abiturient_id:
            temp_enrolled_ped.append(entry)
            temp_enrolled_ids.add(entry.abiturient_id)
            enrolled_ped[:] = temp_enrolled_ped
            enrolled_ids.update(temp_enrolled_ids)
            return True
        if entry.abiturient_id not in temp_enrolled_ids:
            temp_enrolled_ped.append(entry)
            temp_enrolled_ids.add(entry.abiturient_id)

    return False


def _enroll_university_directions(
    lech_direction: StudyDirection | None,
    ped_direction: StudyDirection | None,
    competitive: dict[int, list[ApplicationEntry]],
) -> dict[int, list[ApplicationEntry]]:
    enrolled_by_direction: dict[int, list[ApplicationEntry]] = defaultdict(list)

    if lech_direction and ped_direction:
        lech_list = competitive.get(lech_direction.id, [])
        ped_list = competitive.get(ped_direction.id, [])
        seats_lech = lech_direction.seats or 0
        seats_ped = ped_direction.seats or 0
        enrolled_lech: list[ApplicationEntry] = []
        enrolled_ped: list[ApplicationEntry] = []
        enrolled_ids: set[str] = set()

        for applicant in lech_list:
            if len(enrolled_lech) >= seats_lech:
                break
            if applicant.abiturient_id in enrolled_ids:
                continue

            if applicant.npriority_ssp == 1:
                enrolled_lech.append(applicant)
                enrolled_ids.add(applicant.abiturient_id)
                continue

            enrolled_on_ped = _try_enroll_on_pediatrics(
                applicant,
                ped_list,
                enrolled_ped,
                enrolled_ids,
                seats_ped,
            )
            if not enrolled_on_ped and len(enrolled_lech) < seats_lech:
                enrolled_lech.append(applicant)
                enrolled_ids.add(applicant.abiturient_id)

        for applicant in ped_list:
            if len(enrolled_ped) >= seats_ped:
                break
            if applicant.abiturient_id in enrolled_ids:
                continue
            if applicant.npriority_ssp == 2:
                enrolled_ped.append(applicant)
                enrolled_ids.add(applicant.abiturient_id)

        enrolled_by_direction[lech_direction.id] = enrolled_lech
        enrolled_by_direction[ped_direction.id] = enrolled_ped
        return enrolled_by_direction

    single_direction = lech_direction or ped_direction
    if not single_direction:
        return enrolled_by_direction

    entries = competitive.get(single_direction.id, [])
    seats = single_direction.seats or 0
    enrolled = entries[:seats]
    enrolled_by_direction[single_direction.id] = enrolled
    return enrolled_by_direction


def _serialize_enrollment_lists(
    enrolled_by_direction: dict[int, list[ApplicationEntry]],
) -> dict[str, list[str]]:
    return {
        str(direction_id): [entry.abiturient_id for entry in entries]
        for direction_id, entries in enrolled_by_direction.items()
    }


def _serialize_competitive_lists(
    competitive: dict[int, list[ApplicationEntry]],
) -> dict[str, list[str]]:
    return {
        str(direction_id): [entry.abiturient_id for entry in entries]
        for direction_id, entries in competitive.items()
    }


def compute_consent_model() -> dict[str, Any]:
    by_abiturient, directions, universities = _load_applications()

    consent_by_abiturient: dict[str, int] = {}
    for abiturient_id, applications in by_abiturient.items():
        consent_university_id = _choose_consent_university(applications)
        if consent_university_id is not None:
            consent_by_abiturient[abiturient_id] = consent_university_id

    competitive = _build_competitive_lists(by_abiturient, consent_by_abiturient)

    directions_by_university: dict[int, list[StudyDirection]] = defaultdict(list)
    for direction in directions.values():
        directions_by_university[direction.university_id].append(direction)

    enrolled_by_direction: dict[int, list[ApplicationEntry]] = defaultdict(list)
    for university_id, university_directions in directions_by_university.items():
        lech_direction = next(
            (direction for direction in university_directions if direction.name == LECH_DIRECTION_NAME),
            None,
        )
        ped_direction = next(
            (direction for direction in university_directions if direction.name == PED_DIRECTION_NAME),
            None,
        )
        university_enrollment = _enroll_university_directions(
            lech_direction,
            ped_direction,
            competitive,
        )
        for direction_id, entries in university_enrollment.items():
            enrolled_by_direction[direction_id] = entries

    cutoff_scores = []
    for direction in sorted(directions.values(), key=lambda item: (item.university.name, item.name)):
        enrolled = enrolled_by_direction.get(direction.id, [])
        competitive_list = competitive.get(direction.id, [])
        cutoff_score = enrolled[-1].nsummark if enrolled else None
        cutoff_scores.append(
            {
                "direction_id": direction.id,
                "university_name": direction.university.name,
                "direction_name": direction.name,
                "seats": direction.seats,
                "cutoff_score": cutoff_score,
                "enrolled_count": len(enrolled),
                "competitive_count": len(competitive_list),
            }
        )

    return {
        "university_rank_order": sorted(UNIVERSITY_RANK, key=UNIVERSITY_RANK.get),
        "consent_by_abiturient": consent_by_abiturient,
        "cutoff_scores": cutoff_scores,
        "enrollment_by_direction": _serialize_enrollment_lists(enrolled_by_direction),
        "competitive_by_direction": _serialize_competitive_lists(competitive),
    }


def _find_rank(abiturient_id: str, ordered_ids: list[str]) -> int | None:
    try:
        return ordered_ids.index(abiturient_id) + 1
    except ValueError:
        return None


def get_user_consent_projection(
    user,
    consent_modeling: dict[str, Any] | None,
) -> list[ConsentProjectionResult]:
    if not consent_modeling:
        return []

    applied_ids = set(user.applied_universities.values_list("id", flat=True))
    enrollment_by_direction = consent_modeling.get("enrollment_by_direction") or {}
    competitive_by_direction = consent_modeling.get("competitive_by_direction") or {}
    consent_by_abiturient = consent_modeling.get("consent_by_abiturient") or {}
    cutoff_by_direction = {
        item["direction_id"]: item.get("cutoff_score")
        for item in consent_modeling.get("cutoff_scores") or []
    }

    universities = {
        university.id: university.name
        for university in MedicalUniversity.objects.filter(is_active=True)
    }
    user_consent_university_id = consent_by_abiturient.get(user.abiturient_id)
    user_consent_university_name = universities.get(user_consent_university_id)

    directions = list(
        StudyDirection.objects.filter(university__is_active=True)
        .select_related("university")
        .order_by("university__name", "name")
    )
    directions_by_university: dict[int, list[StudyDirection]] = defaultdict(list)
    for direction in directions:
        directions_by_university[direction.university_id].append(direction)

    enrolled_direction_name_by_university: dict[int, str] = {}
    for direction in directions:
        enrolled_ids = enrollment_by_direction.get(str(direction.id), [])
        if user.abiturient_id in enrolled_ids:
            enrolled_direction_name_by_university[direction.university_id] = direction.name

    results: list[ConsentProjectionResult] = []
    for direction in directions:
        university = direction.university
        if university.id not in applied_ids:
            continue

        profile = ApplicantProfile.objects.filter(
            direction=direction,
            abiturient_id=user.abiturient_id,
        ).first()

        direction_key = str(direction.id)
        enrolled_position = _find_rank(
            user.abiturient_id,
            enrollment_by_direction.get(direction_key, []),
        )
        competitive_position = _find_rank(
            user.abiturient_id,
            competitive_by_direction.get(direction_key, []),
        )
        submission_position = profile.position if profile else None
        is_admitted = enrolled_position is not None
        enrolled_elsewhere_name = enrolled_direction_name_by_university.get(university.id)

        if is_admitted:
            status = "admitted"
            status_label = "Проходит"
        elif (
            enrolled_elsewhere_name
            and enrolled_elsewhere_name != direction.name
            and university.id == user_consent_university_id
        ):
            status = "admitted_other_direction"
            status_label = f"Зачисление: {enrolled_elsewhere_name}"
        elif profile and user_consent_university_id != university.id:
            status = "consent_other_university"
            status_label = f"Согласие в {user_consent_university_name or 'другом вузе'}"
        elif competitive_position is not None:
            status = "not_admitted"
            status_label = "Не проходит"
        elif profile:
            status = "not_in_competitive"
            status_label = "Вне конкурсного списка"
        else:
            status = "not_in_submission"
            status_label = "Нет в списке поступающих"

        results.append(
            ConsentProjectionResult(
                university_name=university.name,
                direction_name=direction.name,
                direction_id=direction.id,
                seats=direction.seats,
                submission_position=submission_position,
                competitive_position=competitive_position,
                enrollment_position=enrolled_position,
                nsummark=profile.nsummark if profile else None,
                npriority_ssp=profile.npriority_ssp if profile else None,
                cutoff_score=cutoff_by_direction.get(direction.id),
                is_admitted=is_admitted,
                is_applied=True,
                status=status,
                status_label=status_label,
                consent_university_name=user_consent_university_name,
                enrolled_direction_name=enrolled_elsewhere_name,
            )
        )

    return results
