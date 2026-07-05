from dataclasses import dataclass

from apps.admissions.models import ApplicantProfile
from apps.universities.models import MedicalUniversity, StudyDirection


@dataclass
class PositionResult:
    university_name: str
    direction_name: str
    direction_id: int
    seats: int | None
    position: int | None
    nsummark: int | None
    sstatus_ssp: str | None
    npriority_ssp: int | None
    has_enrollment_consent: bool | None
    is_applied: bool
    is_hypothetical: bool
    user_score: int | None = None


class PositionService:
    NOT_FOUND_STATUS = (
        "ID {abiturient_id} не найден в списке. "
        "Войдите под тем же ID, что указан в списке поступающих."
    )
    NOT_SYNCED_STATUS = (
        "Данные по направлению ещё не загружены. "
        "Нажмите «Обновить данные сейчас» и подождите несколько минут."
    )

    def __init__(self, user):
        self.user = user

    def _get_profile(self, direction: StudyDirection) -> ApplicantProfile | None:
        return ApplicantProfile.objects.filter(
            direction=direction,
            abiturient_id=self.user.abiturient_id,
        ).first()

    def _direction_has_profiles(self, direction: StudyDirection) -> bool:
        return ApplicantProfile.objects.filter(direction=direction).exists()

    def _not_found_status(self, direction: StudyDirection) -> str:
        if not self._direction_has_profiles(direction):
            return self.NOT_SYNCED_STATUS
        return self.NOT_FOUND_STATUS.format(abiturient_id=self.user.abiturient_id)

    def _direction_label(self, direction: StudyDirection) -> str:
        return direction.name

    def _user_score_for_university(self, university: MedicalUniversity) -> int | None:
        if self.user.ege_total_score is None:
            return None
        bonus = university.honors_diploma_points if self.user.has_honors_diploma else 0
        return self.user.ege_total_score + bonus

    def _score_from_profile_or_estimate(
        self,
        university: MedicalUniversity,
        direction: StudyDirection,
        profile: ApplicantProfile | None,
    ) -> int | None:
        if profile:
            return profile.nsummark
        return self._user_score_for_university(university)

    def _hypothetical_position(self, direction: StudyDirection, user_score: int) -> int:
        higher_count = ApplicantProfile.objects.filter(
            direction=direction,
            nsummark__gt=user_score,
        ).count()
        return higher_count + 1

    def _profile_fields(self, profile: ApplicantProfile) -> dict:
        return {
            "sstatus_ssp": profile.sstatus_ssp,
            "npriority_ssp": profile.npriority_ssp,
            "has_enrollment_consent": profile.has_enrollment_consent,
            "nsummark": profile.nsummark,
        }

    def get_current_positions(self) -> list[PositionResult]:
        applied_ids = set(self.user.applied_universities.values_list("id", flat=True))
        results = []

        directions = (
            StudyDirection.objects.filter(university__is_active=True)
            .select_related("university")
            .order_by("university__name", "name")
        )

        for direction in directions:
            university = direction.university
            is_applied = university.id in applied_ids
            profile = self._get_profile(direction)

            if is_applied and profile:
                results.append(
                    PositionResult(
                        university_name=university.name,
                        direction_name=self._direction_label(direction),
                        direction_id=direction.id,
                        seats=direction.seats,
                        position=profile.position,
                        nsummark=profile.nsummark,
                        sstatus_ssp=profile.sstatus_ssp,
                        npriority_ssp=profile.npriority_ssp,
                        has_enrollment_consent=profile.has_enrollment_consent,
                        is_applied=True,
                        is_hypothetical=False,
                        user_score=profile.nsummark,
                    )
                )
                continue

            user_score = self._user_score_for_university(university)
            if profile:
                score_for_position = profile.nsummark if user_score is None else user_score
                position = self._hypothetical_position(direction, score_for_position)
                fields = self._profile_fields(profile)
                results.append(
                    PositionResult(
                        university_name=university.name,
                        direction_name=self._direction_label(direction),
                        direction_id=direction.id,
                        seats=direction.seats,
                        position=position,
                        nsummark=fields["nsummark"],
                        sstatus_ssp=fields["sstatus_ssp"],
                        npriority_ssp=fields["npriority_ssp"],
                        has_enrollment_consent=fields["has_enrollment_consent"],
                        is_applied=is_applied,
                        is_hypothetical=True,
                        user_score=fields["nsummark"],
                    )
                )
                continue

            if is_applied:
                results.append(
                    PositionResult(
                        university_name=university.name,
                        direction_name=self._direction_label(direction),
                        direction_id=direction.id,
                        seats=direction.seats,
                        position=self._hypothetical_position(direction, user_score)
                        if user_score is not None
                        else None,
                        nsummark=user_score,
                        sstatus_ssp=self._not_found_status(direction),
                        npriority_ssp=None,
                        has_enrollment_consent=None,
                        is_applied=True,
                        is_hypothetical=True,
                        user_score=user_score,
                    )
                )
                continue

            results.append(
                PositionResult(
                    university_name=university.name,
                    direction_name=self._direction_label(direction),
                    direction_id=direction.id,
                    seats=direction.seats,
                    position=self._hypothetical_position(direction, user_score)
                    if user_score is not None
                    else None,
                    nsummark=user_score,
                    sstatus_ssp=None,
                    npriority_ssp=None,
                    has_enrollment_consent=None,
                    is_applied=False,
                    is_hypothetical=True,
                    user_score=user_score,
                )
            )

        return results

    def get_forecast_positions(self) -> list[PositionResult]:
        applied_ids = set(self.user.applied_universities.values_list("id", flat=True))
        results = []

        directions = (
            StudyDirection.objects.filter(university__is_active=True)
            .select_related("university")
            .order_by("university__name", "name")
        )

        for direction in directions:
            university = direction.university
            is_applied = university.id in applied_ids
            profile = self._get_profile(direction) if is_applied else None
            user_score = self._score_from_profile_or_estimate(university, direction, profile)

            if user_score is None:
                results.append(
                    PositionResult(
                        university_name=university.name,
                        direction_name=self._direction_label(direction),
                        direction_id=direction.id,
                        seats=direction.seats,
                        position=None,
                        nsummark=None,
                        sstatus_ssp=None,
                        npriority_ssp=None,
                        has_enrollment_consent=None,
                        is_applied=is_applied,
                        is_hypothetical=True,
                    )
                )
                continue

            higher_count = ApplicantProfile.objects.filter(
                direction=direction,
                npriority_ssp=1,
            ).exclude(
                abiturient_id=self.user.abiturient_id,
            ).filter(
                nsummark__gt=user_score,
            ).count()

            results.append(
                PositionResult(
                    university_name=university.name,
                    direction_name=self._direction_label(direction),
                    direction_id=direction.id,
                    seats=direction.seats,
                    position=higher_count + 1,
                    nsummark=user_score,
                    sstatus_ssp="Прогноз (priority=1)",
                    npriority_ssp=None,
                    has_enrollment_consent=profile.has_enrollment_consent if profile else None,
                    is_applied=is_applied,
                    is_hypothetical=profile is None,
                    user_score=user_score,
                )
            )

        return results
