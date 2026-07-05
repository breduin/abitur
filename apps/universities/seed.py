FIRST_MED_NAME = "Первый мед (СПб)"
PEDIATRIC_NAME = "Педиатрический (СПб)"
ALMAZOV_NAME = "Центр Алмазова"
SZGMU_NAME = "СЗГМУ Мечникова (СПб)"

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
        },
    },
]

PEDIATRIC_API_CONFIG = {
    "provider": "gpmu",
    "base_url": "https://spiski.gpmu.org",
    "page_size": 100,
}

PEDIATRIC_DIRECTIONS = [
    {
        "name": "Лечебное дело",
        "filter_params": {"group_id": "kg_4"},
    },
    {
        "name": "Педиатрия",
        "filter_params": {"group_id": "kg_16"},
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
        },
    },
    {
        "name": "Педиатрия",
        "seats": 16,
        "filter_params": {
            "dir": "/one_s/spec26/",
            "file": "000000060_31.05.02 Pediatriya (Osnovnye mesta v ramkakh KTsP)_B.txt",
        },
    },
]


def _ensure_university_directions(university, api_config, directions):
    from apps.universities.models import MedicalUniversity, StudyDirection

    if not university.api_config:
        university.api_config = api_config
        university.save(update_fields=["api_config"])

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
        if direction.filter_params != direction_data["filter_params"]:
            updates["filter_params"] = direction_data["filter_params"]
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
    _ensure_university_directions(university, FIRST_MED_API_CONFIG, FIRST_MED_DIRECTIONS)


def ensure_pediatric_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=PEDIATRIC_NAME,
        defaults={"api_config": PEDIATRIC_API_CONFIG},
    )
    _ensure_university_directions(university, PEDIATRIC_API_CONFIG, PEDIATRIC_DIRECTIONS)


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
        },
    },
]


def ensure_almazov_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=ALMAZOV_NAME,
        defaults={"api_config": ALMAZOV_API_CONFIG},
    )
    _ensure_university_directions(university, ALMAZOV_API_CONFIG, ALMAZOV_DIRECTIONS)


def ensure_szgmu_seed():
    from apps.universities.models import MedicalUniversity

    university, _ = MedicalUniversity.objects.get_or_create(
        name=SZGMU_NAME,
        defaults={"api_config": SZGMU_API_CONFIG},
    )
    _ensure_university_directions(university, SZGMU_API_CONFIG, SZGMU_DIRECTIONS)


def ensure_seed_data():
    ensure_first_med_seed()
    ensure_pediatric_seed()
    ensure_almazov_seed()
    ensure_szgmu_seed()
