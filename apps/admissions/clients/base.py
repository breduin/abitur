import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests
import urllib3
from django.conf import settings
from django.utils import timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UniversityAPIError(Exception):
    pass


class RateLimitError(UniversityAPIError):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class BaseHTTPClient:
    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0

    def __init__(self, api_config: dict[str, Any], session: requests.Session | None = None):
        self.api_config = api_config
        self.session = session or requests.Session()
        self.last_seats: int | None = None

    @property
    def user_agent(self) -> str:
        return self.api_config.get("user_agent", settings.DEFAULT_USER_AGENT)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", self.user_agent)
        last_exc: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.DEFAULT_TIMEOUT,
                    headers=headers,
                    **kwargs,
                )
            except (requests.ConnectionError, requests.Timeout, requests.SSLError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.BACKOFF_BASE * (2**attempt))
                    continue
                raise UniversityAPIError(f"Сетевая ошибка: {exc}") from exc

            if response.status_code == 429:
                retry_after = self._parse_retry_after(response)
                raise RateLimitError("Превышен лимит запросов", retry_after=retry_after)

            if 500 <= response.status_code < 600:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.BACKOFF_BASE * (2**attempt))
                    continue
                raise UniversityAPIError(f"Сервер вернул {response.status_code}")

            if 400 <= response.status_code < 500:
                raise UniversityAPIError(
                    f"Клиентская ошибка {response.status_code}: {response.text[:200]}"
                )

            return response

        raise UniversityAPIError(f"Запрос не удался: {last_exc}")

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> int | None:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        if header.isdigit():
            return int(header)
        try:
            dt = parsedate_to_datetime(header)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = dt - timezone.now()
            return max(int(delta.total_seconds()), 1)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _parse_score(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _should_stop_at_score(score: int | None, min_score: int) -> bool:
        """Остановка по порогу: нулевые баллы (олимпиадники) не прерывают загрузку."""
        if score is None or score == 0:
            return False
        return score < min_score
