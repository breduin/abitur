from apps.universities.models import StudyDirection

FIRST_MED_LIST_URL = "https://abit.1spbgmu.ru/hod-priema/spiski-postupayushih/"
PEDIATRIC_LIST_URL = "https://spiski.gpmu.org/spisok-podavshikh"
ALMAZOV_LIST_URL = "https://abit.almazovcentre.ru/specialty/spec-course/spec-lists/"
SZGMU_LECH_LIST_URL = "https://szgmu.ru/priem2026/spec/stage1/html/lech_budget.php"
SECHENOV_LIST_URL = "https://priem.sechenov.ru/submitted-applicants/"
PIROGOV_LIST_URL = "https://submitted.rsmu.ru/"
MSU_LECH_LIST_URL = "https://cpk.msu.ru/submitted/bachelor/dep_10"
SPBU_LECH_LIST_URL = (
    "https://enrollelists.spbu.ru/reports/PriemList02.php?mode=list"
    "&education_level_sort_order=1"
    "&speciality=31.05.01%7C%D0%9B%D0%B5%D1%87%D0%B5%D0%B1%D0%BD%D0%BE%D0%B5+%D0%B4%D0%B5%D0%BB%D0%BE"
    "&program_name=%D0%9B%D0%B5%D1%87%D0%B5%D0%B1%D0%BD%D0%BE%D0%B5+%D0%B4%D0%B5%D0%BB%D0%BE"
    "&education_form_name=%D0%BE%D1%87%D0%BD%D0%B0%D1%8F"
    "&fin_source_name=%D0%91%D1%8E%D0%B4%D0%B6%D0%B5%D1%82"
    "&faculty_name=%D0%A1%D0%9F%D0%B1%D0%93%D0%A3&is_foreign=0"
)


def get_direction_source_url(direction: StudyDirection) -> str | None:
    params = direction.filter_params or {}
    source_url = params.get("source_url")
    if source_url:
        return source_url

    api_config = direction.university.api_config or {}
    provider = api_config.get("provider")
    base_url = (api_config.get("base_url") or "").rstrip("/")

    if provider == "1spbgmu":
        return api_config.get("referer") or FIRST_MED_LIST_URL
    if provider == "gpmu":
        return PEDIATRIC_LIST_URL
    if provider == "almazov":
        return api_config.get("referer") or ALMAZOV_LIST_URL
    if provider == "szgmu":
        list_path = params.get("list_path", "")
        return f"{base_url}{list_path}" if base_url and list_path else SZGMU_LECH_LIST_URL
    if provider == "sechenov":
        return SECHENOV_LIST_URL
    if provider == "rsmu":
        return api_config.get("referer") or PIROGOV_LIST_URL
    if provider == "cpk_msu":
        list_path = params.get("list_path", "")
        return f"{base_url}{list_path}" if base_url and list_path else MSU_LECH_LIST_URL
    if provider == "spbu":
        return params.get("report_page_url") or api_config.get("referer") or SPBU_LECH_LIST_URL

    return None
