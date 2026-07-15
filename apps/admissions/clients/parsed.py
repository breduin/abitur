from dataclasses import dataclass
from typing import Any

from apps.admissions.clients.field_parsers import (
    parse_almazov_enrollment_consent,
    is_almazov_bvi,
    parse_cpk_msu_enrollment_consent,
    parse_first_med_enrollment_consent,
    parse_gpmu_competition_status,
    parse_gpmu_enrollment_consent,
    is_gpmu_bvi,
    is_sechenov_bvi,
    parse_priority,
    parse_rsmu_enrollment_consent,
    parse_rosunimed_enrollment_consent,
    parse_spbu_enrollment_consent,
    parse_sechenov_enrollment_consent,
    parse_szgmu_enrollment_consent,
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

        if is_gpmu_bvi(row):
            nsummark = 0
        else:
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
    def from_sechenov_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("УИД", "")).strip()
        if not abiturient_id:
            return None

        if is_sechenov_bvi(row):
            nsummark = 0
        else:
            try:
                nsummark = int(row.get("Сумма конкурсных баллов") or 0)
            except (TypeError, ValueError):
                return None

        status = str(row.get("Статус", "")).strip() or "На рассмотрении"
        raw_data = dict(row)
        if is_sechenov_bvi(row):
            raw_data["_is_bvi"] = True

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("Приоритет зачисления")),
            has_enrollment_consent=parse_sechenov_enrollment_consent(row),
            raw_data=raw_data,
        )

    @classmethod
    def from_szgmu_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("Уникальный код поступающего", "")).strip()
        if not abiturient_id:
            return None

        try:
            nsummark = int(row.get("Сумма конкурсных баллов") or 0)
        except (TypeError, ValueError):
            return None

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp="Участвует в конкурсе",
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("Приоритет")),
            has_enrollment_consent=parse_szgmu_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_almazov_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("Уникальный код", "")).strip()
        if not abiturient_id:
            return None

        if is_almazov_bvi(row):
            nsummark = 0
        else:
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
    def from_cpk_msu_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("ID абитуриента", "")).strip()
        if not abiturient_id:
            return None

        if row.get("_is_bvi"):
            nsummark = 0
        else:
            try:
                nsummark = int(row.get("Сумма конкурсных баллов") or 0)
            except (TypeError, ValueError):
                return None

        status = str(row.get("Статус заявления", "")).strip() or "На рассмотрении"

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("Приоритет")),
            has_enrollment_consent=parse_cpk_msu_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_spbu_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("Уникальный код поступающего", "")).strip()
        if not abiturient_id:
            return None

        score_raw = str(row.get("Сумма конкурсных баллов", "")).strip()
        if score_raw.isdigit():
            nsummark = int(score_raw)
        else:
            nsummark = 0

        status = str(row.get("Статус", "")).strip() or "На рассмотрении"
        priority_key = "Приоритет зачисления, указанный поступающим по данной КГ"

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get(priority_key)),
            has_enrollment_consent=parse_spbu_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_rosunimed_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("uniqueId", "")).strip()
        if not abiturient_id:
            return None

        if row.get("reasonWithoutAdmission"):
            nsummark = 0
        else:
            rating_total = row.get("ratingTotal")
            if rating_total is None or str(rating_total).strip() == "":
                return None
            try:
                nsummark = int(str(rating_total).strip())
            except (TypeError, ValueError):
                return None

        status = str(row.get("status", "")).strip() or "На рассмотрении"

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("priority")),
            has_enrollment_consent=parse_rosunimed_enrollment_consent(row),
            raw_data=row,
        )

    @classmethod
    def from_rsmu_row(cls, row: dict[str, Any], position: int) -> "ParsedApplicantRow | None":
        abiturient_id = str(row.get("title", "")).strip()
        if not abiturient_id:
            return None

        try:
            nsummark = int(row.get("total") or 0)
        except (TypeError, ValueError):
            return None

        status = str(row.get("state", "")).strip() or "На рассмотрении"

        return cls(
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp=status,
            nsummark=nsummark,
            npriority_ssp=parse_priority(row.get("priority")),
            has_enrollment_consent=parse_rsmu_enrollment_consent(row),
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
