import time
from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError
from apps.admissions.clients.sechenov_html_parser import parse_page_rows, sleep_between_pages


class SechenovClient(BaseHTTPClient):
    DEFAULT_PAGE_DELAY = 0.35
    DEFAULT_LIST_PATH = (
        "/local/components/firstbit/competition.list/templates/.default/applications.php"
    )

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @property
    def list_path(self) -> str:
        return self.api_config.get("list_path", self.DEFAULT_LIST_PATH)

    @property
    def referer(self) -> str:
        return self.api_config.get(
            "referer",
            f"{self.base_url}/submitted-applicants/",
        )

    @property
    def page_delay(self) -> float:
        return float(self.api_config.get("page_delay", self.DEFAULT_PAGE_DELAY))

    def _build_params(self, competitive_group_id: str, page: int) -> dict[str, str]:
        page_key = f"appPage_{competitive_group_id}"
        return {
            "COMPETITIVE_GROUP_ID": competitive_group_id,
            page_key: f"page-{page}",
            "ADMISSION_LISTS": "N",
            "CONTRACT_IS_PAID": "N",
            "ORIGINAL_DOCUMENT": "N",
            "lang": "ru",
            "search": "",
            "highest_passing_priority": "",
            "highest_primary_priority": "",
            "header_consent": "",
        }

    def fetch_page_html(self, filter_params: dict[str, Any], page: int) -> str:
        competitive_group_id = filter_params.get("competitive_group_id")
        if not competitive_group_id:
            raise UniversityAPIError("competitive_group_id обязателен для Сеченова")

        url = f"{self.base_url}{self.list_path}"
        response = self._request_with_retry(
            "GET",
            url,
            params=self._build_params(str(competitive_group_id), page),
            headers={
                "Accept": "*/*",
                "Referer": self.referer,
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
        seats = filter_params.get("seats")
        if seats is not None:
            try:
                self.last_seats = int(seats)
            except (TypeError, ValueError):
                self.last_seats = None
        else:
            self.last_seats = None

        page = 1
        position = 0
        previous_first_uid: str | None = None

        while True:
            html = self.fetch_page_html(filter_params, page=page)
            rows = parse_page_rows(html)
            if not rows:
                break

            first_uid = rows[0].get("УИД")
            if page > 1 and first_uid and first_uid == previous_first_uid:
                break
            previous_first_uid = first_uid

            stop = False
            for row in rows:
                score = self._parse_score(row.get("Сумма конкурсных баллов"))
                if self._should_stop_at_score(score, min_score):
                    stop = True
                    break
                position += 1
                row["_position"] = position
                yield row

            if stop:
                break

            page += 1
            sleep_between_pages(self.page_delay)
