from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.spbu_html_parser import (
    parse_applicant_table,
    parse_seats,
    rows_to_dicts,
)


class SPBUClient(BaseHTTPClient):
    DEFAULT_LIST_ENDPOINT = "/api/reports/priem-list-02/data"

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @property
    def list_endpoint(self) -> str:
        return self.api_config.get("list_endpoint", self.DEFAULT_LIST_ENDPOINT)

    @property
    def referer(self) -> str:
        return self.api_config.get("referer", f"{self.base_url}/reports/PriemList02.php")

    def _build_request_body(self, filter_params: dict[str, Any]) -> dict[str, Any]:
        report_id = filter_params.get("report_priem_list_02_id")
        speciality_ids = filter_params.get("speciality_ids")
        filters = filter_params.get("filters")
        if not report_id or not speciality_ids or not filters:
            raise UniversityAPIError(
                "report_priem_list_02_id, speciality_ids и filters обязательны для СПбГУ"
            )
        return {
            "report_priem_list_02_id": report_id,
            "speciality_ids": speciality_ids,
            "filters": filters,
        }

    def fetch_list_html(self, filter_params: dict[str, Any]) -> str:
        url = f"{self.base_url}{self.list_endpoint}"
        response = self._request_with_retry(
            "POST",
            url,
            json=self._build_request_body(filter_params),
            headers={
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "Referer": self.referer,
                "X-Requested-With": "XMLHttpRequest",
            },
            verify=filter_params.get("verify_ssl", self.api_config.get("verify_ssl", False)),
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе СПбГУ") from exc

        blocks = data.get("blocks") or []
        if not blocks:
            raise UniversityAPIError("Поле blocks пустое в ответе СПбГУ")

        speciality_ids = set(filter_params.get("speciality_ids") or [])
        for block in blocks:
            if block.get("speciality_id") in speciality_ids:
                html = block.get("html")
                if html:
                    return html

        html = blocks[0].get("html")
        if not html:
            raise UniversityAPIError("HTML блок не найден в ответе СПбГУ")
        return html

    @staticmethod
    def _parse_competition_score(value: Any) -> int | None:
        if value is None or value == "":
            return None
        normalized = str(value).strip()
        if normalized.isdigit():
            return int(normalized)
        return None

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        html = self.fetch_list_html(filter_params)
        seats = parse_seats(html)
        self.last_seats = seats

        headers, rows = parse_applicant_table(html)
        for position, row in enumerate(rows_to_dicts(headers, rows), start=1):
            score = self._parse_competition_score(row.get("Сумма конкурсных баллов"))
            if self._should_stop_at_score(score, min_score):
                break
            row["_position"] = position
            yield row
