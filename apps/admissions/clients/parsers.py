from apps.admissions.clients.parsed import ParsedApplicantRow


def parse_applicant_row(row: dict, provider: str) -> ParsedApplicantRow | None:
    if provider == "gpmu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_gpmu_row(row, position=position)
    if provider == "almazov":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_almazov_row(row, position=position)
    if provider == "szgmu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_szgmu_row(row, position=position)
    if provider == "sechenov":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_sechenov_row(row, position=position)
    if provider == "rsmu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_rsmu_row(row, position=position)
    if provider == "cpk_msu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_cpk_msu_row(row, position=position)
    if provider == "spbu":
        position = int(row.get("_position", 0))
        return ParsedApplicantRow.from_spbu_row(row, position=position)
    return ParsedApplicantRow.from_first_med_row(row)
