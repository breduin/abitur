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

CONSENT_PROBABILITY_ONE_UNIVERSITY = env.float(
    "CONSENT_PROBABILITY_ONE_UNIVERSITY",
    default=0.25,
)
CONSENT_PROBABILITY_TWO_UNIVERSITIES = env.float(
    "CONSENT_PROBABILITY_TWO_UNIVERSITIES",
    default=0.50,
)
CONSENT_PROBABILITY_THREE_UNIVERSITIES = env.float(
    "CONSENT_PROBABILITY_THREE_UNIVERSITIES",
    default=0.75,
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
