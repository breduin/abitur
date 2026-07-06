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
ROSUNIMED_LIST_URL = "https://contest.rosunimed.ru/"

FIRST_MED_NAME = "Первый мед (СПб)"
PEDIATRIC_NAME = "Педиатрический (СПб)"
ALMAZOV_NAME = "Центр Алмазова"
SZGMU_NAME = "СЗГМУ Мечникова (СПб)"
SECHENOV_NAME = "Сеченовский университет (Мск)"
PIROGOV_NAME = "Пироговский университет (Мск)"
MSU_NAME = "МГУ Ломоносова (Мск)"
SPBU_NAME = "СПбГУ (СПб)"
ROSUNIMED_NAME = "Росунимед (Мск)"

FIRST_MED_API_CONFIG = {
    "provider": "1spbgmu",
    "base_url": "https://abit.1spbgmu.ru",
    "csrf_page": "/hod-priema/spiski-postupayushih/",
    "list_endpoint": "/applcompetlist/page/",
    "referer": "https://abit.1spbgmu.ru/hod-priema/spiski-postupayushih/",
}

FIRST_MED_DIRECTIONS = [
    {
        "name": "Педиатрия",
        "seats": 15,
        "filter_params": {
            "sedprofile_name": "Педиатрия",
            "sfaculty_name": "Педиатрический факультет",
            "splacekindname": "Бюджет (Общий конкурс)",
            "srecruitment": "ВПО-2026",
            "source_url": FIRST_MED_LIST_URL,
        },
    },
    {
        "name": "Лечебное дело",
        "seats": 135,
        "filter_params": {
            "srecruitment": "ВПО-2026",
            "sfaculty_name": "Лечебный факультет",
            "sedprofile_name": "Лечебное дело",
            "splacekindname": "Бюджет (Общий конкурс)",
            "source_url": FIRST_MED_LIST_URL,
        },
    },
]

PEDIATRIC_API_CONFIG = {
    "provider": "gpmu",
    "base_url": "https://spiski.gpmu.org",
    "page_size": 100,
    "fallback_ip": "89.169.170.237",
}

PEDIATRIC_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "filter_params": {"group_id": "kg_4", "source_url": PEDIATRIC_LIST_URL},
    },
    {
        "name": "Педиатрия",
        "filter_params": {"group_id": "kg_16", "source_url": PEDIATRIC_LIST_URL},
    },
]

ALMAZOV_API_CONFIG = {
    "provider": "almazov",
    "base_url": "https://abit.almazovcentre.ru",
    "list_endpoint": "/wp-content/themes/new-imo-2025/returnNewRanged.php",
    "referer": "https://abit.almazovcentre.ru/specialty/spec-course/spec-lists/",
}

ALMAZOV_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 162,
        "filter_params": {
            "dir": "/one_s/spec26/",
            "file": "000000060_31.05.01 Lechebnoe delo (Osnovnye mesta v ramkakh KTsP)_B.txt",
            "source_url": ALMAZOV_LIST_URL,
        },
    },
    {
        "name": "Педиатрия",
        "seats": 16,
        "filter_params": {
            "dir": "/one_s/spec26/",
            "file": "000000060_31.05.02 Pediatriya (Osnovnye mesta v ramkakh KTsP)_B.txt",
            "source_url": ALMAZOV_LIST_URL,
        },
    },
]


def _ensure_university_directions(university, api_config, directions, *, city=None):
    from apps.universities.models import MedicalUniversity, StudyDirection

    university_updates = {}
    merged_api_config = {**(university.api_config or {}), **api_config}
    if university.api_config != merged_api_config:
        university_updates["api_config"] = merged_api_config
    if city and university.city != city:
        university_updates["city"] = city
    if university_updates:
        for field, value in university_updates.items():
            setattr(university, field, value)
        university.save(update_fields=list(university_updates.keys()))

    for direction_data in directions:
        direction, created = StudyDirection.objects.get_or_create(
            university=university,
            name=direction_data["name"],
            defaults={
                "filter_params": direction_data["filter_params"],
                "seats": direction_data.get("seats"),
            },
        )
        updates = {}
        merged_filter_params = {
            **(direction.filter_params or {}),
            **direction_data["filter_params"],
        }
        if direction.filter_params != merged_filter_params:
            updates["filter_params"] = merged_filter_params
        if "seats" in direction_data and direction.seats != direction_data["seats"]:
            updates["seats"] = direction_data["seats"]
        if updates:
            for field, value in updates.items():
                setattr(direction, field, value)
            direction.save(update_fields=list(updates.keys()))


def ensure_first_med_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=FIRST_MED_NAME,
        defaults={"api_config": FIRST_MED_API_CONFIG},
    )
    _ensure_university_directions(
        university, FIRST_MED_API_CONFIG, FIRST_MED_DIRECTIONS, city="spb"
    )


def ensure_pediatric_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=PEDIATRIC_NAME,
        defaults={"api_config": PEDIATRIC_API_CONFIG},
    )
    _ensure_university_directions(
        university, PEDIATRIC_API_CONFIG, PEDIATRIC_DIRECTIONS, city="spb"
    )


SZGMU_API_CONFIG = {
    "provider": "szgmu",
    "base_url": "https://szgmu.ru",
}

SZGMU_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 97,
        "filter_params": {
            "list_path": "/priem2026/spec/stage1/html/lech_budget.php",
            "section_marker": "общий конкурс",
            "source_url": SZGMU_LECH_LIST_URL,
        },
    },
]


def ensure_almazov_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=ALMAZOV_NAME,
        defaults={"api_config": ALMAZOV_API_CONFIG},
    )
    _ensure_university_directions(
        university, ALMAZOV_API_CONFIG, ALMAZOV_DIRECTIONS, city="spb"
    )


SECHENOV_API_CONFIG = {
    "provider": "sechenov",
    "base_url": "https://priem.sechenov.ru",
    "verify_ssl": False,
    "page_delay": 0.35,
}

SECHENOV_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 495,
        "filter_params": {
            "competitive_group_id": "19488",
            "seats": 495,
            "source_url": SECHENOV_LIST_URL,
        },
    },
    {
        "name": "Педиатрия",
        "seats": 31,
        "filter_params": {
            "competitive_group_id": "19486",
            "seats": 31,
            "source_url": SECHENOV_LIST_URL,
        },
    },
]


def ensure_szgmu_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=SZGMU_NAME,
        defaults={"api_config": SZGMU_API_CONFIG},
    )
    _ensure_university_directions(university, SZGMU_API_CONFIG, SZGMU_DIRECTIONS, city="spb")


def ensure_sechenov_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=SECHENOV_NAME,
        defaults={"api_config": SECHENOV_API_CONFIG},
    )
    _ensure_university_directions(
        university, SECHENOV_API_CONFIG, SECHENOV_DIRECTIONS, city="msk"
    )


PIROGOV_API_CONFIG = {
    "provider": "rsmu",
    "base_url": "https://submitted.rsmu.ru",
    "referer": "https://submitted.rsmu.ru/",
    "admission_title": "Прием на обучение на специалитет - 2026",
    "timeout": 120,
}

PIROGOV_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 426,
        "filter_params": {
            "program_title": "Лечебное дело (Лечебное дело) Общий конкурс 2026",
            "seats": 426,
            "source_url": PIROGOV_LIST_URL,
        },
    },
    {
        "name": "Педиатрия",
        "seats": 283,
        "filter_params": {
            "program_title": "Педиатрия Общий конкурс 2026",
            "seats": 283,
            "source_url": PIROGOV_LIST_URL,
        },
    },
]


def ensure_pirogov_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=PIROGOV_NAME,
        defaults={"api_config": PIROGOV_API_CONFIG},
    )
    _ensure_university_directions(
        university, PIROGOV_API_CONFIG, PIROGOV_DIRECTIONS, city="msk"
    )


MSU_API_CONFIG = {
    "provider": "cpk_msu",
    "base_url": "https://cpk.msu.ru",
    "verify_ssl": False,
}

MSU_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 46,
        "filter_params": {
            "list_path": "/submitted/bachelor/dep_10",
            "program_name": "Лечебное дело",
            "concourse_title": "Основные места в рамках КЦП",
            "seats": 46,
            "source_url": MSU_LECH_LIST_URL,
        },
    },
]


def ensure_msu_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=MSU_NAME,
        defaults={"api_config": MSU_API_CONFIG, "honors_diploma_points": 0},
    )
    if university.honors_diploma_points != 0:
        university.honors_diploma_points = 0
        university.save(update_fields=["honors_diploma_points"])
    _ensure_university_directions(university, MSU_API_CONFIG, MSU_DIRECTIONS, city="msk")


SPBU_API_CONFIG = {
    "provider": "spbu",
    "base_url": "https://enrollelists.spbu.ru",
    "list_endpoint": "/api/reports/priem-list-02/data",
    "referer": SPBU_LECH_LIST_URL,
    "verify_ssl": False,
}

SPBU_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 21,
        "filter_params": {
            "report_priem_list_02_id": "019f360a-157c-7148-8c9c-1954a37747d2",
            "speciality_ids": ["43934249-e370-4cf5-a035-e012ad199977"],
            "report_page_url": SPBU_LECH_LIST_URL,
            "filters": {
                "education_level_sort_order": "1",
                "report_upload_id": "",
                "faculty_name": "СПбГУ",
                "program_name": "Лечебное дело",
                "speciality": "31.05.01|Лечебное дело",
                "applicant_code": "",
                "education_form_name": "очная",
                "fin_source_name": "Бюджет",
                "contract_status": "",
                "consent_status": "",
                "priority": "",
                "status": "",
                "is_foreign": "0",
            },
            "seats": 21,
            "source_url": SPBU_LECH_LIST_URL,
        },
    },
]


ROSUNIMED_API_CONFIG = {
    "provider": "rosunimed",
    "base_url": "https://contest.rosunimed.ru",
    "verify_ssl": False,
}

ROSUNIMED_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "seats": 98,
        "filter_params": {
            "group_id": "000002336",
            "source_url": ROSUNIMED_LIST_URL,
        },
    },
    {
        "name": "Педиатрия",
        "seats": 4,
        "filter_params": {
            "group_id": "000002368",
            "source_url": ROSUNIMED_LIST_URL,
        },
    },
]


def ensure_spbu_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=SPBU_NAME,
        defaults={"api_config": SPBU_API_CONFIG},
    )
    _ensure_university_directions(university, SPBU_API_CONFIG, SPBU_DIRECTIONS, city="spb")


def ensure_rosunimed_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=ROSUNIMED_NAME,
        defaults={"api_config": ROSUNIMED_API_CONFIG},
    )
    _ensure_university_directions(
        university, ROSUNIMED_API_CONFIG, ROSUNIMED_DIRECTIONS, city="msk"
    )


def ensure_seed_data():
    ensure_first_med_seed()
    ensure_pediatric_seed()
    ensure_almazov_seed()
    ensure_szgmu_seed()
    ensure_sechenov_seed()
    ensure_pirogov_seed()
    ensure_msu_seed()
    ensure_spbu_seed()
    ensure_rosunimed_seed()
