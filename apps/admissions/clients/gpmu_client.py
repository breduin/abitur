from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.parsed import ParsedApplicantRow


class GPMUClient(BaseHTTPClient):
    DEFAULT_PAGE_SIZE = 100

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    def fetch_group_page(
        self,
        group_id: str,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        page_size = page_size or self.api_config.get("page_size", self.DEFAULT_PAGE_SIZE)
        url = f"{self.base_url}/api/pod/group/{group_id}"
        response = self._request_with_retry(
            "GET",
            url,
            params={"page": page, "page_size": page_size},
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе GPMU") from exc

        if "rows" not in data:
            raise UniversityAPIError("Поле rows отсутствует в ответе GPMU")

        seats = data.get("seats") or {}
        total = seats.get("total")
        if total is not None:
            try:
                self.last_seats = int(total)
            except (TypeError, ValueError):
                pass

        return data

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        group_id = filter_params.get("group_id")
        if not group_id:
            raise UniversityAPIError("group_id обязателен для GPMU")

        page_size = page_size or self.api_config.get("page_size", self.DEFAULT_PAGE_SIZE)
        page = 1
        position = 0

        while True:
            data = self.fetch_group_page(group_id, page=page, page_size=page_size)
            rows = data.get("rows") or []
            if not rows:
                break

            stop = False
            for row in rows:
                position += 1
                score = self._parse_score(row.get("Сумма конкурсных баллов"))
                if self._should_stop_at_score(score, min_score):
                    stop = True
                    break
                row["_position"] = position
                yield row

            if stop:
                break
            if len(rows) < page_size:
                break
            page += 1
