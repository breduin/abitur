from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.szgmu_html_parser import (
    parse_budget_section,
    rows_to_dicts,
)


class SZGMUClient(BaseHTTPClient):
    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    def fetch_list_html(self, filter_params: dict[str, Any]) -> str:
        list_path = filter_params.get("list_path")
        if not list_path:
            raise UniversityAPIError("list_path обязателен для СЗГМУ")

        url = f"{self.base_url}{list_path}"
        response = self._request_with_retry("GET", url)
        return response.text

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        html = self.fetch_list_html(filter_params)
        section_marker = filter_params.get("section_marker", "общий конкурс")
        seats, headers, rows = parse_budget_section(html, section_marker=section_marker)
        self.last_seats = seats

        for position, row in enumerate(rows_to_dicts(headers, rows), start=1):
            score = self._parse_score(row.get("Сумма конкурсных баллов"))
            if self._should_stop_at_score(score, min_score):
                break
            row["_position"] = position
            yield row
