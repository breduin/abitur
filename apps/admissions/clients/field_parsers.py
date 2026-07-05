from typing import Any


def is_checkmark(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in {"✓", "✔", "v", "1", "true", "yes", "да"}


def parse_priority(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parse_gpmu_competition_status(row: dict[str, Any]) -> str:
    if is_checkmark(row.get("Участвует в конкурсе")):
        return "Участвует в конкурсе"
    return "На рассмотрении"


def parse_gpmu_enrollment_consent(row: dict[str, Any]) -> bool:
    return is_checkmark(row.get("Состояние договора")) or is_checkmark(
        row.get("Согласие на зачисление")
    )


def parse_szgmu_enrollment_consent(row: dict[str, Any]) -> bool:
    value = str(row.get("Согласие на зачисление", "")).strip().lower()
    return value in {"да", "✓", "✔", "yes", "true", "1"}


def parse_almazov_enrollment_consent(row: dict[str, Any]) -> bool:
    return is_checkmark(row.get("Согласие на зачисление")) or is_checkmark(
        row.get("Состояние договора")
    )


def parse_first_med_enrollment_consent(row: dict[str, Any]) -> bool:
    value = row.get("ncons4enr")
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    normalized = str(value).strip().lower()
    return normalized in {"true", "1", "yes", "да"}
