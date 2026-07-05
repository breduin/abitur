from dataclasses import dataclass
from typing import Any

from apps.admissions.clients.field_parsers import (
    parse_almazov_enrollment_consent,
    parse_first_med_enrollment_consent,
    parse_gpmu_competition_status,
    parse_gpmu_enrollment_consent,
    parse_priority,
)


@dataclass
class ParsedApplicantRow:
    abiturient_id: str
    position: int
    sstatus_ssp: str
    nsummark: int
    npriority_ssp: int
    has_enrollment_consent: bool
    raw_data: dict[str, Any]

    @classmethod
    def from_gpmu_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("Уникальный код", "")).strip()
        if not abiturient_id:
            return None

        try:
            nsummark = int(row.get("Сумма конкурсных баллов") or 0)
        except (TypeError, ValueError):
            return None

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=parse_gpmu_competition_status(row),
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("Приоритет")),
            has_enrollment_consent=parse_gpmu_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_almazov_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("Уникальный код", "")).strip()
        if not abiturient_id:
            return None

        try:
            nsummark = int(row.get("Сумма баллов") or 0)
        except (TypeError, ValueError):
            return None

        status = str(row.get("Текущий статус конкурса", "")).strip() or "На рассмотрении"

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("Приоритет")),
            has_enrollment_consent=parse_almazov_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_first_med_row(cls, row: dict[str, Any]) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("suniqcode") or row.get("_code") or "").strip()
        if not abiturient_id:
            return None

        try:
            position = int(row.get("_position", 0))
            nsummark = int(row.get("nsummark", 0))
        except (TypeError, ValueError):
            return None

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=str(row.get("sstatus_ssp", "")),
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("npriority_ssp")),
            has_enrollment_consent=parse_first_med_enrollment_consent(row),
            raw_data=row,
        )
