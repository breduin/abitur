import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# nginx terminates TLS and forwards HTTP to gunicorn
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.users",
    "apps.universities",
    "apps.admissions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

db_path = env("DATABASE_PATH", default="data/db.sqlite3")
if not os.path.isabs(db_path):
    db_path = BASE_DIR / db_path

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": db_path,
    }
}

AUTH_PASSWORD_VALIDATORS = []

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = [
    "apps.users.backends.AbiturientIDBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    "sync-all-universities-hourly": {
        "task": "apps.admissions.tasks.sync_all_active_universities",
        "schedule": 3600.0,
        "kwargs": {"force": False},
    },
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT .0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Consent modeling: CONSENT_MODEL=cascade|applicant_choice
# CONSENT_CHOICE_PAIR_PROBS JSON: {"ВузA|ВузB": 0.7, ...} — P(выбрать вуз с
# лучшим UNIVERSITY_RANK) при равных приоритетах. Порядок имён в ключе не важен.
from apps.universities.seed import (  # noqa: E402
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

CONSENT_MODEL = env("CONSENT_MODEL", default="cascade")
if CONSENT_MODEL not in ("cascade", "applicant_choice"):
    raise ValueError(
        "CONSENT_MODEL must be 'cascade' or 'applicant_choice', "
        f"got {CONSENT_MODEL!r}."
    )

CONSENT_PROBABILITY_ONE_UNIVERSITY = env.float(
    "CONSENT_PROBABILITY_ONE_UNIVERSITY",
    default=0.50,
)
CONSENT_PROBABILITY_TWO_UNIVERSITIES = env.float(
    "CONSENT_PROBABILITY_TWO_UNIVERSITIES",
    default=0.75,
)
CONSENT_PROBABILITY_THREE_UNIVERSITIES = env.float(
    "CONSENT_PROBABILITY_THREE_UNIVERSITIES",
    default=0.90,
)
CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES = env.float(
    "CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES",
    default=1.00,
)

for value, setting_name in (
    (CONSENT_PROBABILITY_ONE_UNIVERSITY, "CONSENT_PROBABILITY_ONE_UNIVERSITY"),
    (CONSENT_PROBABILITY_TWO_UNIVERSITIES, "CONSENT_PROBABILITY_TWO_UNIVERSITIES"),
    (CONSENT_PROBABILITY_THREE_UNIVERSITIES, "CONSENT_PROBABILITY_THREE_UNIVERSITIES"),
    (
        CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES,
        "CONSENT_PROBABILITY_FOUR_OR_FIVE_UNIVERSITIES",
    ),
):
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{setting_name} must be between 0.0 and 1.0 inclusive.")

# Ranks mirrored from consent_modeling_service.UNIVERSITY_RANK (avoid circular import).
_CONSENT_CHOICE_UNIVERSITY_RANK: dict[str, int] = {
    SECHENOV_NAME: 100,
    PIROGOV_NAME: 101,
    MSU_NAME: 102,
    ROSUNIMED_NAME: 103,
    FIRST_MED_NAME: 200,
    PEDIATRIC_NAME: 201,
    SZGMU_NAME: 202,
    ALMAZOV_NAME: 203,
    SPBU_NAME: 204,
}


def _consent_choice_pair_key(name_a: str, name_b: str) -> str:
    left, right = sorted(
        (name_a, name_b),
        key=lambda name: (_CONSENT_CHOICE_UNIVERSITY_RANK[name], name),
    )
    return f"{left}|{right}"


def _default_consent_choice_pair_probs() -> dict[str, float]:
    names = sorted(
        _CONSENT_CHOICE_UNIVERSITY_RANK,
        key=lambda name: (_CONSENT_CHOICE_UNIVERSITY_RANK[name], name),
    )
    probs: dict[str, float] = {}
    for index, name_a in enumerate(names):
        for name_b in names[index + 1 :]:
            delta = abs(
                _CONSENT_CHOICE_UNIVERSITY_RANK[name_a]
                - _CONSENT_CHOICE_UNIVERSITY_RANK[name_b]
            )
            # Same city cluster (MSK 100–103, SPB 200–204): ~0.70; cross-city: 0.90
            probs[_consent_choice_pair_key(name_a, name_b)] = (
                0.70 if delta <= 5 else 0.90
            )
    return probs


def _normalize_consent_choice_pair_probs(
    raw: dict[str, float],
) -> dict[str, float]:
    known = set(_CONSENT_CHOICE_UNIVERSITY_RANK)
    normalized: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or "|" not in key:
            raise ValueError(
                f"CONSENT_CHOICE_PAIR_PROBS key must be 'NameA|NameB', got {key!r}."
            )
        name_a, name_b = key.split("|", 1)
        name_a, name_b = name_a.strip(), name_b.strip()
        if name_a not in known or name_b not in known:
            raise ValueError(
                f"CONSENT_CHOICE_PAIR_PROBS unknown university in {key!r}."
            )
        if name_a == name_b:
            raise ValueError(
                f"CONSENT_CHOICE_PAIR_PROBS pair must be two different universities, "
                f"got {key!r}."
            )
        try:
            probability = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CONSENT_CHOICE_PAIR_PROBS[{key!r}] must be a float, got {value!r}."
            ) from exc
        if not 0.0 <= probability <= 1.0:
            raise ValueError(
                f"CONSENT_CHOICE_PAIR_PROBS[{key!r}] must be between 0.0 and 1.0, "
                f"got {probability}."
            )
        pair_key = _consent_choice_pair_key(name_a, name_b)
        normalized[pair_key] = probability

    expected_keys = set(_default_consent_choice_pair_probs())
    missing = expected_keys - set(normalized)
    if missing:
        sample = ", ".join(sorted(missing)[:3])
        raise ValueError(
            f"CONSENT_CHOICE_PAIR_PROBS missing {len(missing)} pair(s), e.g. {sample}."
        )
    extra = set(normalized) - expected_keys
    if extra:
        sample = ", ".join(sorted(extra)[:3])
        raise ValueError(
            f"CONSENT_CHOICE_PAIR_PROBS has unexpected pair(s), e.g. {sample}."
        )
    return normalized


CONSENT_CHOICE_PAIR_PROBS = _normalize_consent_choice_pair_probs(
    env.json(
        "CONSENT_CHOICE_PAIR_PROBS",
        default=_default_consent_choice_pair_probs(),
    )
)
