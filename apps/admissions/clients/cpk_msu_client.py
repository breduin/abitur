from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.cpk_msu_html_parser import parse_concourse_section


class CPKMSUClient(BaseHTTPClient):
    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    def fetch_list_html(self, filter_params: dict[str, Any]) -> str:
        list_path = filter_params.get("list_path")
        if not list_path:
            raise UniversityAPIError("list_path обязателен для МГУ")

        url = f"{self.base_url}{list_path}"
        response = self._request_with_retry(
            "GET",
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            },
            verify=filter_params.get("verify_ssl", self.api_config.get("verify_ssl", False)),
        )
        return response.text

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        program_name = filter_params.get("program_name")
        concourse_title = filter_params.get("concourse_title", "Основные места в рамках КЦП")
        if not program_name:
            raise UniversityAPIError("program_name обязателен для МГУ")

        html = self.fetch_list_html(filter_params)
        seats, bvi_rows, main_rows = parse_concourse_section(
            html,
            program_name=program_name,
            concourse_title=concourse_title,
        )
        self.last_seats = seats

        position = 0
        for row in bvi_rows:
            position += 1
            row["_position"] = position
            row["_is_bvi"] = True
            yield row

        for row in main_rows:
            score = self._parse_score(row.get("Сумма конкурсных баллов"))
            if self._should_stop_at_score(score, min_score):
                break
            position += 1
            row["_position"] = position
            row["_is_bvi"] = False
            yield row
