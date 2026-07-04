from apps.admissions.clients.parsed import ParsedApplicantRow


def parse_applicant_row(row: dict, provider: str) -> ParsedApplicantRow | None:
    if provider == "gpmu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_gpmu_row(row, position=position)
    return ParsedApplicantRow.from_first_med_row(row)
