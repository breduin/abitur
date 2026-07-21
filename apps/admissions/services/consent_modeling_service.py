from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.admissions.models import ApplicantProfile
from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import (
    ALMAZOV_NAME,
    FIRST_MED_NAME,
    MSU_NAME,
    PEDIATRIC_NAME,
    PIROGOV_NAME,
    ROSUNIMED_NAME,
    SECHENOV_NAME,
    SPBU_NAME,
    SZGMU_NAME,
)

LECH_DIRECTION_NAME = "Лечебное дело"
PED_DIRECTION_NAME = "Педиатрия"
STOM_DIRECTION_NAME = "Стоматология"

DIRECTION_ENROLLMENT_ORDER = (
    LECH_DIRECTION_NAME,
    PED_DIRECTION_NAME,
    STOM_DIRECTION_NAME,
)

UNIVERSITY_RANK: dict[str, int] = {
    SECHENOV_NAME: 100,
    PIROGOV_NAME: 101,
    MSU_NAME: 102,
    ROSUNIMED_NAME: 103,
    FIRST_MED_NAME: 200,
    PEDIATRIC_NAME: 201,
    ALMAZOV_NAME: 203,
    SZGMU_NAME: 202,
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
    passes_enrollment: bool = False
    is_hypothetical_competitive: bool = False
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
            if self.is_hypothetical_competitive:
                return "прогнозный конкурсный"
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


def _load_real_consent_universities(
    universities: dict[int, MedicalUniversity],
) -> dict[str, int]:
    """abiturient_id → university_id по факту поданного согласия.

    Если согласие отмечено в нескольких МУ — берём вуз с лучшим UNIVERSITY_RANK.
    """
    consent_candidates: dict[str, set[int]] = defaultdict(set)
    for abiturient_id, university_id in ApplicantProfile.objects.filter(
        has_enrollment_consent=True,
        direction__university__is_active=True,
    ).values_list("abiturient_id", "direction__university_id"):
        consent_candidates[abiturient_id].add(university_id)

    result: dict[str, int] = {}
    for abiturient_id, university_ids in consent_candidates.items():
        if len(university_ids) == 1:
            result[abiturient_id] = next(iter(university_ids))
            continue
        result[abiturient_id] = min(
            university_ids,
            key=lambda uid: (
                _university_rank(universities[uid].name),
                universities[uid].name,
            ),
        )
    return result


def _consent_probability_by_university_count(university_count: int) -> float:
    if university_count <= 1:
        return settings.CONSENT_PROBABILITY_ONE_UNIVERSITY
    if university_count == 2:
        return settings.CONSENT_PROBABILITY_TWO_UNIVERSITIES
    if university_count == 3:
        return settings.CONSENT_PROBABILITY_THREE_UNIVERSITIES
    return settings.CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES


def _apply_medical_intent_probabilistic_filter(
    by_abiturient: dict[str, list[ApplicationEntry]],
    *,
    real_consent_abiturient_ids: set[str] | None = None,
    rng: random.Random | None = None,
) -> tuple[dict[str, list[ApplicationEntry]], dict[str, Any]]:
    random_generator = rng or random.Random()
    real_consent_ids = real_consent_abiturient_ids or set()
    candidates_by_count: dict[int, list[str]] = defaultdict(list)
    committed: list[str] = []
    excluded: list[str] = []
    for abiturient_id, applications in by_abiturient.items():
        university_count = len({entry.university_id for entry in applications})
        probability = _consent_probability_by_university_count(university_count)
        candidates_by_count[university_count].append(abiturient_id)

        if abiturient_id in real_consent_ids:
            committed.append(abiturient_id)
            continue
        if probability >= 1.0:
            committed.append(abiturient_id)
            continue
        if probability <= 0.0:
            excluded.append(abiturient_id)
            continue
        if random_generator.random() < probability:
            committed.append(abiturient_id)
            continue
        excluded.append(abiturient_id)

    if excluded:
        filtered_by_abiturient = {
            abiturient_id: applications
            for abiturient_id, applications in by_abiturient.items()
            if abiturient_id not in excluded
        }
    else:
        filtered_by_abiturient = by_abiturient

    metadata = {
        "candidate_count": len(by_abiturient),
        "committed_count": len(committed),
        "excluded_count": len(excluded),
        "probabilities": {
            "1": settings.CONSENT_PROBABILITY_ONE_UNIVERSITY,
            "2": settings.CONSENT_PROBABILITY_TWO_UNIVERSITIES,
            "3": settings.CONSENT_PROBABILITY_THREE_UNIVERSITIES,
            "4_or_5": settings.CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES,
        },
        "candidates_by_university_count": {
            str(university_count): sorted(abiturient_ids)
            for university_count, abiturient_ids in sorted(candidates_by_count.items())
        },
        "committed": sorted(committed),
        "excluded": sorted(excluded),
    }
    return filtered_by_abiturient, metadata


def _sorted_universities_by_rank(
    universities: dict[int, MedicalUniversity],
) -> list[MedicalUniversity]:
    return sorted(
        universities.values(),
        key=lambda university: (_university_rank(university.name), university.name),
    )


def _build_university_competitive(
    university_id: int,
    by_abiturient: dict[str, list[ApplicationEntry]],
    locked_abiturient_ids: set[str],
    real_consent_university: dict[str, int] | None = None,
) -> dict[int, list[ApplicationEntry]]:
    consent_by_abiturient = real_consent_university or {}
    competitive: dict[int, list[ApplicationEntry]] = defaultdict(list)
    for abiturient_id, applications in by_abiturient.items():
        if abiturient_id in locked_abiturient_ids:
            continue
        consent_university_id = consent_by_abiturient.get(abiturient_id)
        if (
            consent_university_id is not None
            and consent_university_id != university_id
        ):
            continue
        for entry in applications:
            if entry.university_id == university_id:
                competitive[entry.direction_id].append(entry)

    for direction_id, entries in competitive.items():
        competitive[direction_id] = sorted(entries, key=_competitive_sort_key)

    return competitive


def _active_competitive_list(
    entries: list[ApplicationEntry],
    enrolled_ids: set[str],
) -> list[ApplicationEntry]:
    return [entry for entry in entries if entry.abiturient_id not in enrolled_ids]


def _find_applicant_entry(
    abiturient_id: str,
    entries: list[ApplicationEntry],
) -> ApplicationEntry | None:
    for entry in entries:
        if entry.abiturient_id == abiturient_id:
            return entry
    return None


def _direction_options_for_applicant(
    abiturient_id: str,
    ordered_directions: list[StudyDirection],
    competitive: dict[int, list[ApplicationEntry]],
) -> list[tuple[int, int, StudyDirection, ApplicationEntry]]:
    options: list[tuple[int, int, StudyDirection, ApplicationEntry]] = []
    for direction in ordered_directions:
        entry = _find_applicant_entry(abiturient_id, competitive.get(direction.id, []))
        if entry is not None:
            options.append((entry.npriority_ssp, entry.position, direction, entry))
    options.sort()
    return options


def _would_pass_on_direction(
    entry: ApplicationEntry,
    direction_list: list[ApplicationEntry],
    enrolled_ids: set[str],
    seats: int,
) -> bool:
    active_list = _active_competitive_list(direction_list, enrolled_ids)
    for index, row in enumerate(active_list, start=1):
        if row.abiturient_id == entry.abiturient_id:
            return index <= seats
    return False


def _pick_best_passing_direction(
    abiturient_id: str,
    ordered_directions: list[StudyDirection],
    competitive: dict[int, list[ApplicationEntry]],
    enrolled_ids: set[str],
    seats: dict[int, int],
) -> tuple[StudyDirection, ApplicationEntry] | None:
    best: tuple[int, int, StudyDirection, ApplicationEntry] | None = None
    for npriority, position, direction, entry in _direction_options_for_applicant(
        abiturient_id,
        ordered_directions,
        competitive,
    ):
        direction_list = competitive.get(direction.id, [])
        if not _would_pass_on_direction(
            entry,
            direction_list,
            enrolled_ids,
            seats[direction.id],
        ):
            continue
        if best is None or (npriority, position) < (best[0], best[1]):
            best = (npriority, position, direction, entry)

    if best is None:
        return None
    return best[2], best[3]


def _commit_enrollment_on_direction(
    entry: ApplicationEntry,
    direction: StudyDirection,
    competitive: dict[int, list[ApplicationEntry]],
    enrolled_by_direction: dict[int, list[ApplicationEntry]],
    enrolled_ids: set[str],
    seats: dict[int, int],
) -> bool:
    direction_list = competitive.get(direction.id, [])
    enrolled_list = enrolled_by_direction[direction.id]
    if _try_enroll_on_alternate_direction(
        entry,
        direction_list,
        enrolled_list,
        enrolled_ids,
        seats[direction.id],
    ):
        enrolled_by_direction[direction.id] = enrolled_list
        return True
    return False


def _try_enroll_on_alternate_direction(
    applicant: ApplicationEntry,
    direction_list: list[ApplicationEntry],
    enrolled_direction: list[ApplicationEntry],
    enrolled_ids: set[str],
    seats: int,
) -> bool:
    active_list = _active_competitive_list(direction_list, enrolled_ids)
    applicant_rank = None
    for index, entry in enumerate(active_list, start=1):
        if entry.abiturient_id == applicant.abiturient_id:
            applicant_rank = index
            break

    if applicant_rank is None:
        return False

    temp_enrolled = list(enrolled_direction)
    temp_enrolled_ids = set(enrolled_ids)

    for entry in active_list:
        if len(temp_enrolled) >= seats:
            break
        if entry.abiturient_id == applicant.abiturient_id:
            temp_enrolled.append(entry)
            temp_enrolled_ids.add(entry.abiturient_id)
            enrolled_direction[:] = temp_enrolled
            enrolled_ids.update(temp_enrolled_ids)
            return True
        if entry.abiturient_id not in temp_enrolled_ids:
            temp_enrolled.append(entry)
            temp_enrolled_ids.add(entry.abiturient_id)

    return False


def _try_enroll_on_pediatrics(
    applicant: ApplicationEntry,
    ped_list: list[ApplicationEntry],
    enrolled_ped: list[ApplicationEntry],
    enrolled_ids: set[str],
    seats_ped: int,
) -> bool:
    return _try_enroll_on_alternate_direction(
        applicant,
        ped_list,
        enrolled_ped,
        enrolled_ids,
        seats_ped,
    )


def _ordered_university_directions(
    university_directions: list[StudyDirection],
) -> list[StudyDirection]:
    by_name = {direction.name: direction for direction in university_directions}
    return [
        by_name[direction_name]
        for direction_name in DIRECTION_ENROLLMENT_ORDER
        if direction_name in by_name
    ]


def _enroll_university_directions(
    university_directions: list[StudyDirection],
    competitive: dict[int, list[ApplicationEntry]],
) -> dict[int, list[ApplicationEntry]]:
    enrolled_by_direction: dict[int, list[ApplicationEntry]] = defaultdict(list)
    ordered_directions = _ordered_university_directions(university_directions)
    if not ordered_directions:
        return enrolled_by_direction

    if len(ordered_directions) == 1:
        direction = ordered_directions[0]
        seats = direction.seats or 0
        enrolled_by_direction[direction.id] = competitive.get(direction.id, [])[:seats]
        return enrolled_by_direction

    seats = {direction.id: direction.seats or 0 for direction in ordered_directions}
    enrolled_ids: set[str] = set()
    primary_direction = ordered_directions[0]
    primary_list = competitive.get(primary_direction.id, [])

    for applicant in primary_list:
        if applicant.abiturient_id in enrolled_ids:
            continue

        if applicant.npriority_ssp == 1:
            if _would_pass_on_direction(
                applicant,
                primary_list,
                enrolled_ids,
                seats[primary_direction.id],
            ):
                _commit_enrollment_on_direction(
                    applicant,
                    primary_direction,
                    competitive,
                    enrolled_by_direction,
                    enrolled_ids,
                    seats,
                )
            continue

        picked = _pick_best_passing_direction(
            applicant.abiturient_id,
            ordered_directions,
            competitive,
            enrolled_ids,
            seats,
        )
        if picked is None:
            continue
        direction, entry = picked
        _commit_enrollment_on_direction(
            entry,
            direction,
            competitive,
            enrolled_by_direction,
            enrolled_ids,
            seats,
        )

    for alternate_direction in ordered_directions[1:]:
        direction_list = competitive.get(alternate_direction.id, [])
        for entry in direction_list:
            if entry.abiturient_id in enrolled_ids:
                continue
            if _find_applicant_entry(entry.abiturient_id, primary_list) is not None:
                continue

            picked = _pick_best_passing_direction(
                entry.abiturient_id,
                ordered_directions,
                competitive,
                enrolled_ids,
                seats,
            )
            if picked is None:
                continue
            direction, best_entry = picked
            _commit_enrollment_on_direction(
                best_entry,
                direction,
                competitive,
                enrolled_by_direction,
                enrolled_ids,
                seats,
            )

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


def compute_cascade_consent_model(
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    by_abiturient, directions, universities = _load_applications()
    real_consent_university = _load_real_consent_universities(universities)
    by_abiturient, medical_intent_filter = _apply_medical_intent_probabilistic_filter(
        by_abiturient,
        real_consent_abiturient_ids=set(real_consent_university),
        rng=rng,
    )

    directions_by_university: dict[int, list[StudyDirection]] = defaultdict(list)
    for direction in directions.values():
        directions_by_university[direction.university_id].append(direction)

    locked_abiturient_ids: set[str] = set()
    consent_by_abiturient: dict[str, int] = {}
    competitive: dict[int, list[ApplicationEntry]] = {}
    enrolled_by_direction: dict[int, list[ApplicationEntry]] = defaultdict(list)

    for university in _sorted_universities_by_rank(universities):
        university_competitive = _build_university_competitive(
            university.id,
            by_abiturient,
            locked_abiturient_ids,
            real_consent_university=real_consent_university,
        )
        competitive.update(university_competitive)

        university_directions = directions_by_university[university.id]
        university_enrollment = _enroll_university_directions(
            university_directions,
            university_competitive,
        )

        for direction_id, entries in university_enrollment.items():
            enrolled_by_direction[direction_id] = entries
            for entry in entries:
                if entry.abiturient_id in locked_abiturient_ids:
                    continue
                locked_abiturient_ids.add(entry.abiturient_id)
                consent_by_abiturient[entry.abiturient_id] = university.id

    return {
        "model": "cascade",
        "university_rank_order": sorted(UNIVERSITY_RANK, key=UNIVERSITY_RANK.get),
        "consent_by_abiturient": consent_by_abiturient,
        "cutoff_scores": _build_cutoff_scores(
            directions,
            enrolled_by_direction,
            competitive,
        ),
        "enrollment_by_direction": _serialize_enrollment_lists(enrolled_by_direction),
        "competitive_by_direction": _serialize_competitive_lists(competitive),
        "medical_intent_filter": medical_intent_filter,
    }


@dataclass
class _UniversityChoiceCandidate:
    university_id: int
    university_name: str
    priority: int
    direction: StudyDirection
    entry: ApplicationEntry


def _applicant_global_sort_key(applications: list[ApplicationEntry]) -> tuple:
    return (
        0 if any(entry.is_olympiad for entry in applications) else 1,
        -max(entry.nsummark for entry in applications),
        min(entry.position for entry in applications),
        applications[0].abiturient_id,
    )


def _build_applicant_choice_competitive(
    by_abiturient: dict[str, list[ApplicationEntry]],
    real_consent_university: dict[str, int],
) -> dict[int, list[ApplicationEntry]]:
    competitive: dict[int, list[ApplicationEntry]] = defaultdict(list)
    for abiturient_id, applications in by_abiturient.items():
        consent_university_id = real_consent_university.get(abiturient_id)
        for entry in applications:
            if (
                consent_university_id is not None
                and entry.university_id != consent_university_id
            ):
                continue
            competitive[entry.direction_id].append(entry)

    for direction_id, entries in competitive.items():
        competitive[direction_id] = sorted(entries, key=_competitive_sort_key)
    return competitive


def _pair_base_probability(name_a: str, name_b: str) -> float:
    if name_a not in UNIVERSITY_RANK or name_b not in UNIVERSITY_RANK:
        raise ValueError(
            f"Unknown university for consent choice pair: {name_a!r}, {name_b!r}."
        )
    if name_a == name_b:
        raise ValueError(f"Consent choice pair requires two universities, got {name_a!r}.")
    left, right = sorted(
        (name_a, name_b),
        key=lambda name: (_university_rank(name), name),
    )
    key = f"{left}|{right}"
    probs = settings.CONSENT_CHOICE_PAIR_PROBS
    if key not in probs:
        raise ValueError(f"Missing CONSENT_CHOICE_PAIR_PROBS entry for {key}.")
    return float(probs[key])


def _pairwise_top_probability(
    top_name: str,
    low_name: str,
    pri_top: int,
    pri_low: int,
) -> float:
    base = _pair_base_probability(top_name, low_name)
    if pri_top == pri_low:
        probability = base
    elif pri_top == pri_low + 1:
        probability = 0.50
    elif pri_top >= pri_low + 2:
        probability = 0.30
    elif pri_top == pri_low - 1:
        probability = min(0.95, base + 0.15)
    else:
        probability = min(0.95, base + 0.30)
    return max(0.05, min(0.95, probability))


def _best_passing_option_at_university(
    _abiturient_id: str,
    university_id: int,
    applications: list[ApplicationEntry],
    competitive: dict[int, list[ApplicationEntry]],
    enrolled_ids: set[str],
    enrolled_by_direction: dict[int, list[ApplicationEntry]],
    directions: dict[int, StudyDirection],
) -> _UniversityChoiceCandidate | None:
    best: tuple[int, int, _UniversityChoiceCandidate] | None = None
    for entry in applications:
        if entry.university_id != university_id:
            continue
        direction = directions[entry.direction_id]
        seats = direction.seats or 0
        remaining_seats = seats - len(enrolled_by_direction.get(entry.direction_id, []))
        if remaining_seats <= 0:
            continue
        if not _would_pass_on_direction(
            entry,
            competitive.get(entry.direction_id, []),
            enrolled_ids,
            remaining_seats,
        ):
            continue
        candidate = _UniversityChoiceCandidate(
            university_id=university_id,
            university_name=entry.university_name,
            priority=entry.npriority_ssp,
            direction=direction,
            entry=entry,
        )
        key = (entry.npriority_ssp, entry.position)
        if best is None or key < (best[0], best[1]):
            best = (entry.npriority_ssp, entry.position, candidate)
    if best is None:
        return None
    return best[2]


def _passing_university_candidates(
    abiturient_id: str,
    applications: list[ApplicationEntry],
    competitive: dict[int, list[ApplicationEntry]],
    enrolled_ids: set[str],
    enrolled_by_direction: dict[int, list[ApplicationEntry]],
    directions: dict[int, StudyDirection],
    *,
    only_university_id: int | None = None,
) -> list[_UniversityChoiceCandidate]:
    university_ids: set[int] = set()
    for entry in applications:
        if only_university_id is not None and entry.university_id != only_university_id:
            continue
        university_ids.add(entry.university_id)

    candidates: list[_UniversityChoiceCandidate] = []
    for university_id in university_ids:
        option = _best_passing_option_at_university(
            abiturient_id,
            university_id,
            applications,
            competitive,
            enrolled_ids,
            enrolled_by_direction,
            directions,
        )
        if option is not None:
            candidates.append(option)
    return candidates


def _choose_university_tournament(
    candidates: list[_UniversityChoiceCandidate],
    rng: random.Random,
) -> _UniversityChoiceCandidate:
    ordered = sorted(
        candidates,
        key=lambda item: (_university_rank(item.university_name), item.university_name),
    )
    current = ordered[0]
    for challenger in ordered[1:]:
        probability_keep_top = _pairwise_top_probability(
            current.university_name,
            challenger.university_name,
            current.priority,
            challenger.priority,
        )
        if rng.random() >= probability_keep_top:
            current = challenger
    return current


def _build_cutoff_scores(
    directions: dict[int, StudyDirection],
    enrolled_by_direction: dict[int, list[ApplicationEntry]],
    competitive: dict[int, list[ApplicationEntry]],
) -> list[dict[str, Any]]:
    cutoff_scores = []
    for direction in sorted(
        directions.values(),
        key=lambda item: (item.university.name, item.name),
    ):
        enrolled = enrolled_by_direction.get(direction.id, [])
        competitive_list = competitive.get(direction.id, [])
        if enrolled:
            marginal = sorted(enrolled, key=_competitive_sort_key)[-1]
            cutoff_score = marginal.nsummark
        else:
            cutoff_score = None
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
    return cutoff_scores


def compute_applicant_choice_consent_model(
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    random_generator = rng or random.Random()
    by_abiturient, directions, universities = _load_applications()
    real_consent_university = _load_real_consent_universities(universities)
    by_abiturient, medical_intent_filter = _apply_medical_intent_probabilistic_filter(
        by_abiturient,
        real_consent_abiturient_ids=set(real_consent_university),
        rng=random_generator,
    )

    competitive = _build_applicant_choice_competitive(
        by_abiturient,
        real_consent_university,
    )
    enrolled_by_direction: dict[int, list[ApplicationEntry]] = defaultdict(list)
    enrolled_ids: set[str] = set()
    consent_by_abiturient: dict[str, int] = {}

    ordered_abiturient_ids = sorted(
        by_abiturient,
        key=lambda abiturient_id: _applicant_global_sort_key(by_abiturient[abiturient_id]),
    )

    for abiturient_id in ordered_abiturient_ids:
        if abiturient_id in enrolled_ids:
            continue
        applications = by_abiturient[abiturient_id]
        real_consent_university_id = real_consent_university.get(abiturient_id)

        if real_consent_university_id is not None:
            candidates = _passing_university_candidates(
                abiturient_id,
                applications,
                competitive,
                enrolled_ids,
                enrolled_by_direction,
                directions,
                only_university_id=real_consent_university_id,
            )
            if not candidates:
                continue
            chosen = candidates[0]
        else:
            candidates = _passing_university_candidates(
                abiturient_id,
                applications,
                competitive,
                enrolled_ids,
                enrolled_by_direction,
                directions,
            )
            if not candidates:
                continue
            if len(candidates) == 1:
                chosen = candidates[0]
            else:
                chosen = _choose_university_tournament(candidates, random_generator)

        enrolled_by_direction[chosen.direction.id].append(chosen.entry)
        enrolled_ids.add(abiturient_id)
        consent_by_abiturient[abiturient_id] = chosen.university_id

    return {
        "model": "applicant_choice",
        "university_rank_order": sorted(UNIVERSITY_RANK, key=UNIVERSITY_RANK.get),
        "consent_by_abiturient": consent_by_abiturient,
        "cutoff_scores": _build_cutoff_scores(
            directions,
            enrolled_by_direction,
            competitive,
        ),
        "enrollment_by_direction": _serialize_enrollment_lists(enrolled_by_direction),
        "competitive_by_direction": _serialize_competitive_lists(competitive),
        "medical_intent_filter": medical_intent_filter,
    }


def compute_consent_model(
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    if settings.CONSENT_MODEL == "applicant_choice":
        return compute_applicant_choice_consent_model(rng=rng)
    return compute_cascade_consent_model(rng=rng)


def _find_rank(abiturient_id: str, ordered_ids: list[str]) -> int | None:
    try:
        return ordered_ids.index(abiturient_id) + 1
    except ValueError:
        return None


def _application_entry_from_profile(
    profile: ApplicantProfile,
    direction: StudyDirection,
    university: MedicalUniversity,
) -> ApplicationEntry:
    return ApplicationEntry(
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


def _build_competitive_entries(
    direction: StudyDirection,
    university: MedicalUniversity,
    competitive_ids: list[str],
) -> list[ApplicationEntry]:
    profiles = {
        profile.abiturient_id: profile
        for profile in ApplicantProfile.objects.filter(
            direction_id=direction.id,
            abiturient_id__in=competitive_ids,
        )
    }
    entries: list[ApplicationEntry] = []
    for abiturient_id in competitive_ids:
        profile = profiles.get(abiturient_id)
        if profile is None:
            continue
        entries.append(_application_entry_from_profile(profile, direction, university))
    return entries


def _counterfactual_enrolled_ids_for_direction(
    university_id: int,
    direction_id: int,
    directions_by_university: dict[int, list[StudyDirection]],
    enrollment_by_direction: dict[str, list[str]],
) -> set[str]:
    """Зачисленные на другие направления этого МУ — не конкурируют за места direction_id."""
    enrolled_ids: set[str] = set()
    for uni_direction in directions_by_university.get(university_id, []):
        if uni_direction.id == direction_id:
            continue
        for abiturient_id in enrollment_by_direction.get(str(uni_direction.id), []):
            enrolled_ids.add(abiturient_id)
    return enrolled_ids


def _resolve_counterfactual_competitive_position(
    user_abiturient_id: str,
    user_entry: ApplicationEntry,
    direction_list: list[ApplicationEntry],
    counterfactual_enrolled_ids: set[str],
    seats: int,
) -> tuple[int | None, bool]:
    passes = _would_pass_on_direction(
        user_entry,
        direction_list,
        counterfactual_enrolled_ids,
        seats,
    )
    active_list = _active_competitive_list(direction_list, counterfactual_enrolled_ids)
    for index, row in enumerate(active_list, start=1):
        if row.abiturient_id == user_abiturient_id:
            return index, passes
    return None, False


def _resolve_competitive_position(
    direction: StudyDirection,
    user,
    user_score: int | None,
    competitive_ids: list[str],
) -> tuple[int | None, bool]:
    actual_position = _find_rank(user.abiturient_id, competitive_ids)
    if actual_position is not None:
        return actual_position, False
    if user_score is None:
        return None, False

    hypothetical_position = _hypothetical_competitive_position(
        direction,
        user,
        user_score,
        competitive_ids,
    )
    if hypothetical_position is None:
        return None, False
    return hypothetical_position, True


def _projection_competitive_ids_for_direction(
    direction: StudyDirection,
    competitive_ids: list[str],
    consent_modeling: dict[str, Any],
) -> list[str]:
    """Return active competition ids for projection.

    For applicant_choice we exclude entrants who already chose consent
    in another university; they should not affect hypothetical positions.
    """
    if consent_modeling.get("model") != "applicant_choice":
        return competitive_ids

    consent_by_abiturient = consent_modeling.get("consent_by_abiturient") or {}
    return [
        abiturient_id
        for abiturient_id in competitive_ids
        if (
            consent_by_abiturient.get(abiturient_id) is None
            or consent_by_abiturient.get(abiturient_id) == direction.university_id
        )
    ]


def _marginal_enrolled_abiturient_id(
    enrolled_ids: list[str],
    direction_list: list[ApplicationEntry],
) -> str | None:
    """Worst enrolled entrant by competitive sort — same criterion as cutoff_score."""
    if not enrolled_ids:
        return None
    enrolled_set = set(enrolled_ids)
    enrolled_entries = [
        entry for entry in direction_list if entry.abiturient_id in enrolled_set
    ]
    if not enrolled_entries:
        return None
    marginal = sorted(enrolled_entries, key=_competitive_sort_key)[-1]
    return marginal.abiturient_id


def _rank_in_entries(
    abiturient_id: str,
    entries: list[ApplicationEntry],
) -> int | None:
    ordered = sorted(entries, key=_competitive_sort_key)
    for index, entry in enumerate(ordered, start=1):
        if entry.abiturient_id == abiturient_id:
            return index
    return None


def _ensure_user_in_entries(
    entries: list[ApplicationEntry],
    user_entry: ApplicationEntry | None,
) -> list[ApplicationEntry]:
    if user_entry is None:
        return list(entries)
    if any(entry.abiturient_id == user_entry.abiturient_id for entry in entries):
        return list(entries)
    return [*entries, user_entry]


def _passes_by_cutoff_score(
    user_score: int | None,
    cutoff: int | None,
    user_competitive_position: int | None,
    marginal_competitive_position: int | None,
    *,
    seats: int | None = None,
) -> bool:
    if user_score is None or cutoff is None:
        return False
    # Position and badge must stay consistent: outside seats => does not pass.
    if (
        seats is not None
        and seats > 0
        and user_competitive_position is not None
        and user_competitive_position > seats
    ):
        return False
    if user_score > cutoff:
        return True
    if user_score < cutoff:
        return False
    if user_competitive_position is None or marginal_competitive_position is None:
        return False
    return user_competitive_position < marginal_competitive_position


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
        raw_competitive_ids = competitive_by_direction.get(direction_key, [])
        competitive_ids = _projection_competitive_ids_for_direction(
            direction,
            raw_competitive_ids,
            consent_modeling,
        )
        enrolled_ids = enrollment_by_direction.get(direction_key, [])
        enrolled_position = _find_rank(user.abiturient_id, enrolled_ids)
        submission_position = profile.position if profile else None
        is_admitted = enrolled_position is not None
        enrolled_elsewhere_name = enrolled_direction_name_by_university.get(university.id)
        cutoff_score = cutoff_by_direction.get(direction.id)

        user_score = profile.nsummark if profile else _user_projection_score(user, university)
        user_entry = (
            _application_entry_from_profile(profile, direction, university)
            if profile is not None
            else None
        )
        is_admitted_other_direction = (
            not is_admitted
            and enrolled_elsewhere_name is not None
            and enrolled_elsewhere_name != direction.name
            and university.id == user_consent_university_id
        )

        # Ranking list used both for displayed position and for badge color.
        ranking_entries = _build_competitive_entries(direction, university, competitive_ids)
        ranking_entries = _ensure_user_in_entries(ranking_entries, user_entry)
        if is_admitted_other_direction and profile is not None:
            counterfactual_enrolled_ids = _counterfactual_enrolled_ids_for_direction(
                university.id,
                direction.id,
                directions_by_university,
                enrollment_by_direction,
            )
            counterfactual_enrolled_ids.discard(user.abiturient_id)
            ranking_entries = _active_competitive_list(
                ranking_entries,
                counterfactual_enrolled_ids,
            )
            is_hypothetical_competitive = True
        else:
            is_hypothetical_competitive = (
                profile is not None
                and user.abiturient_id not in competitive_ids
                and user_entry is not None
            )

        competitive_position = (
            _rank_in_entries(user.abiturient_id, ranking_entries)
            if user_entry is not None or user.abiturient_id in {
                entry.abiturient_id for entry in ranking_entries
            }
            else None
        )
        if competitive_position is None and user_score is not None:
            competitive_position, is_hypothetical_competitive = _resolve_competitive_position(
                direction,
                user,
                user_score,
                competitive_ids,
            )

        if is_admitted:
            passes_enrollment = True
        else:
            marginal_id = _marginal_enrolled_abiturient_id(enrolled_ids, ranking_entries)
            if marginal_id is None:
                # Fall back to raw direction entries if enrolled were filtered out.
                raw_direction_list = _build_competitive_entries(
                    direction,
                    university,
                    raw_competitive_ids,
                )
                marginal_id = _marginal_enrolled_abiturient_id(enrolled_ids, raw_direction_list)
                marginal_competitive_position = (
                    _find_rank(marginal_id, raw_competitive_ids) if marginal_id else None
                )
                user_rank_for_cutoff = _find_rank(user.abiturient_id, raw_competitive_ids)
                if user_rank_for_cutoff is None:
                    user_rank_for_cutoff = competitive_position
            else:
                marginal_competitive_position = _rank_in_entries(marginal_id, ranking_entries)
                user_rank_for_cutoff = competitive_position
            passes_enrollment = _passes_by_cutoff_score(
                user_score,
                cutoff_score,
                user_rank_for_cutoff,
                marginal_competitive_position,
                seats=direction.seats,
            )

        if is_admitted:
            status = "admitted"
            status_label = "Проходит"
        elif is_admitted_other_direction:
            status = "admitted_other_direction"
            status_label = f"Зачисление: {enrolled_elsewhere_name}"
        elif (
            user_consent_university_id is not None
            and user_consent_university_id != university.id
            and (profile or competitive_position is not None)
        ):
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
                cutoff_score=cutoff_score,
                is_admitted=is_admitted,
                is_applied=True,
                status=status,
                status_label=status_label,
                passes_enrollment=passes_enrollment,
                is_hypothetical_competitive=is_hypothetical_competitive,
                consent_university_name=user_consent_university_name,
                enrolled_direction_name=enrolled_elsewhere_name,
            )
        )

    return results


def _user_projection_score(user, university: MedicalUniversity) -> int | None:
    profiles = list(
        ApplicantProfile.objects.filter(abiturient_id=user.abiturient_id).only("nsummark")
    )
    if profiles:
        return max(profile.nsummark for profile in profiles)
    if user.ege_total_score is None:
        return None
    bonus = university.honors_diploma_points if user.has_honors_diploma else 0
    return user.ege_total_score + bonus


def _hypothetical_competitive_position(
    direction: StudyDirection,
    user,
    user_score: int,
    competitive_ids: list[str],
) -> int | None:
    if not competitive_ids:
        return 1

    profiles = {
        profile.abiturient_id: profile
        for profile in ApplicantProfile.objects.filter(
            direction_id=direction.id,
            abiturient_id__in=competitive_ids,
        )
    }
    entries: list[ApplicationEntry] = []
    for abiturient_id in competitive_ids:
        profile = profiles.get(abiturient_id)
        if profile is None:
            continue
        entries.append(
            ApplicationEntry(
                abiturient_id=profile.abiturient_id,
                direction_id=direction.id,
                university_id=direction.university_id,
                university_name=direction.university.name,
                direction_name=direction.name,
                position=profile.position,
                nsummark=profile.nsummark,
                npriority_ssp=profile.npriority_ssp,
                is_olympiad=_is_olympiad(profile),
                seats=direction.seats,
            )
        )

    hypothetical = ApplicationEntry(
        abiturient_id=user.abiturient_id,
        direction_id=direction.id,
        university_id=direction.university_id,
        university_name=direction.university.name,
        direction_name=direction.name,
        position=10**9,
        nsummark=user_score,
        npriority_ssp=1,
        is_olympiad=user_score == 0,
        seats=direction.seats,
    )
    entries.append(hypothetical)
    sorted_entries = sorted(entries, key=_competitive_sort_key)
    for index, entry in enumerate(sorted_entries, start=1):
        if entry.abiturient_id == user.abiturient_id:
            return index
    return None


def get_user_hypothetical_consent_projection(
    user,
    consent_modeling: dict[str, Any] | None,
) -> list[ConsentProjectionResult]:
    if not consent_modeling:
        return []

    applied_ids = set(user.applied_universities.values_list("id", flat=True))
    competitive_by_direction = consent_modeling.get("competitive_by_direction") or {}
    cutoff_by_direction = {
        item["direction_id"]: item.get("cutoff_score")
        for item in consent_modeling.get("cutoff_scores") or []
    }

    directions = list(
        StudyDirection.objects.filter(university__is_active=True)
        .select_related("university")
        .order_by("university__name", "name")
    )

    results: list[ConsentProjectionResult] = []
    for direction in directions:
        university = direction.university
        if university.id in applied_ids:
            continue

        user_score = _user_projection_score(user, university)
        direction_key = str(direction.id)
        competitive_ids = _projection_competitive_ids_for_direction(
            direction,
            competitive_by_direction.get(direction_key, []),
            consent_modeling,
        )
        cutoff_score = cutoff_by_direction.get(direction.id)
        direction_list = _build_competitive_entries(direction, university, competitive_ids)
        enrolled_ids = (consent_modeling.get("enrollment_by_direction") or {}).get(
            direction_key,
            [],
        )
        competitive_position = (
            _hypothetical_competitive_position(
                direction,
                user,
                user_score,
                competitive_ids,
            )
            if user_score is not None
            else None
        )
        marginal_id = _marginal_enrolled_abiturient_id(enrolled_ids, direction_list)
        marginal_competitive_position = (
            _find_rank(marginal_id, competitive_ids) if marginal_id else None
        )
        passes_enrollment = _passes_by_cutoff_score(
            user_score,
            cutoff_score,
            competitive_position,
            marginal_competitive_position,
            seats=direction.seats,
        )

        results.append(
            ConsentProjectionResult(
                university_name=university.name,
                direction_name=direction.name,
                direction_id=direction.id,
                seats=direction.seats,
                submission_position=None,
                competitive_position=competitive_position,
                enrollment_position=None,
                nsummark=user_score,
                npriority_ssp=None,
                cutoff_score=cutoff_score,
                is_admitted=False,
                is_applied=False,
                status="hypothetical",
                status_label="Прогноз",
                passes_enrollment=passes_enrollment,
                is_hypothetical_competitive=competitive_position is not None,
            )
        )

    return results
