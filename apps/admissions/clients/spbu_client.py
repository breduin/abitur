import json
import re
from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.spbu_html_parser import (
    parse_applicant_table,
    parse_seats,
    rows_to_dicts,
)

REPORT_META_PATTERN = re.compile(
    r'<script type="application/json" id="priem-list-02-report-meta">(.*?)</script>',
    re.S,
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

    def fetch_report_meta(self, page_url: str | None = None) -> dict[str, Any]:
        url = page_url or self.referer
        response = self._request_with_retry(
            "GET",
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": self.base_url,
            },
            verify=self.api_config.get("verify_ssl", False),
        )
        match = REPORT_META_PATTERN.search(response.text)
        if not match:
            raise UniversityAPIError(
                "Не найден priem-list-02-report-meta на странице СПбГУ"
            )
        try:
            return json.loads(match.group(1))
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON meta на странице СПбГУ") from exc

    def _find_speciality_id(
        self,
        meta: dict[str, Any],
        filters: dict[str, Any],
    ) -> str | None:
        program_name = filters.get("program_name")
        speciality = filters.get("speciality", "")
        speciality_code = speciality.split("|", 1)[0] if speciality else ""

        for section in meta.get("sections", []):
            for spec in section.get("specialities", []):
                if program_name and spec.get("name") == program_name:
                    return spec.get("id")
                if speciality_code and spec.get("code") == speciality_code:
                    return spec.get("id")
        return None

    def _build_request_body(self, filter_params: dict[str, Any]) -> dict[str, Any]:
        filters = dict(filter_params.get("filters") or {})
        if not filters:
            raise UniversityAPIError("filters обязательны для СПбГУ")

        meta = self.fetch_report_meta(filter_params.get("report_page_url"))
        report_id = meta.get("id")
        if not report_id:
            raise UniversityAPIError("report_priem_list_02_id не найден в meta СПбГУ")

        speciality_id = self._find_speciality_id(meta, filters)
        if not speciality_id:
            speciality_ids = filter_params.get("speciality_ids") or []
            speciality_id = speciality_ids[0] if speciality_ids else None
        if not speciality_id:
            raise UniversityAPIError(
                "speciality_id не найден в meta СПбГУ для заданных фильтров"
            )

        if not filters.get("report_upload_id") and meta.get("report_upload_id"):
            filters["report_upload_id"] = meta["report_upload_id"]

        return {
            "report_priem_list_02_id": report_id,
            "speciality_ids": [speciality_id],
            "filters": filters,
        }

    def fetch_list_html(self, filter_params: dict[str, Any]) -> str:
        url = f"{self.base_url}{self.list_endpoint}"
        body = self._build_request_body(filter_params)
        response = self._request_with_retry(
            "POST",
            url,
            json=body,
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

        speciality_ids = set(body["speciality_ids"])
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
