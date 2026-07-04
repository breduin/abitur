import re
from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError


class UniversityAPIClient(BaseHTTPClient):
    def __init__(self, api_config: dict[str, Any], session=None):
        super().__init__(api_config, session)
        self._csrf_token: str | None = None

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @property
    def referer(self) -> str:
        return self.api_config.get("referer", f"{self.base_url}/")

    def _headers(self, *, with_csrf: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Referer": self.referer,
        }
        if with_csrf and self._csrf_token:
            headers["X-CSRFToken"] = self._csrf_token
        return headers

    def fetch_csrf_token(self) -> str:
        csrf_page = self.api_config.get("csrf_page", "/")
        url = f"{self.base_url}{csrf_page}"
        response = self._request_with_retry("GET", url, headers=self._headers())

        token = self.session.cookies.get("csrftoken")
        if not token:
            match = re.search(r'csrfmiddlewaretoken["\']?\s*value=["\']([^"\']+)', response.text)
            if match:
                token = match.group(1)

        if not token:
            raise UniversityAPIError("CSRF токен не найден")

        self._csrf_token = token
        return token

    def fetch_page(
        self,
        filter_params: dict[str, Any],
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._csrf_token:
            self.fetch_csrf_token()

        list_endpoint = self.api_config.get("list_endpoint", "/applcompetlist/page/")
        url = f"{self.base_url}{list_endpoint}"

        payload = {
            "limit": limit,
            "offset": offset,
            "csrfmiddlewaretoken": self._csrf_token,
            **filter_params,
        }

        response = self._request_with_retry(
            "POST",
            url,
            json=payload,
            headers={**self._headers(with_csrf=True), "Content-Type": "application/json"},
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе") from exc

        rows = data.get("rows")
        if rows is None:
            raise UniversityAPIError("Поле rows отсутствует в ответе")

        if not isinstance(rows, list):
            raise UniversityAPIError("Поле rows должно быть списком")

        return rows

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        limit: int = 100,
    ) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            rows = self.fetch_page(filter_params, offset=offset, limit=limit)
            if not rows:
                break

            stop = False
            for row in rows:
                score = self._parse_score(row.get("nsummark"))
                if self._should_stop_at_score(score, min_score):
                    stop = True
                    break
                yield row

            if stop:
                break
            if len(rows) < limit:
                break
            offset += limit
