from typing import Any

from apps.admissions.clients.almazov_client import AlmazovClient
from apps.admissions.clients.base import UniversityAPIError
from apps.admissions.clients.gpmu_client import GPMUClient
from apps.admissions.clients.university_client import UniversityAPIClient


def get_university_client(api_config: dict[str, Any]):
    if not api_config:
        raise UniversityAPIError("Пустой api_config")

    provider = api_config.get("provider", "1spbgmu")
    if provider == "gpmu":
        return GPMUClient(api_config)
    if provider == "almazov":
        return AlmazovClient(api_config)
    if provider == "1spbgmu":
        return UniversityAPIClient(api_config)

    raise UniversityAPIError(f"Неизвестный provider: {provider}")
