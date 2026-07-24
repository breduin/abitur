from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.field_parsers import parse_almazov_competition_score
from apps.admissions.clients.almazov_html_parser import parse_seats, parse_table, rows_to_dicts
from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError


class AlmazovClient(BaseHTTPClient):
    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @property
    def list_endpoint(self) -> str:
        return self.api_config.get(
            "list_endpoint",
            "/wp-content/themes/new-imo-2025/returnNewRanged.php",
        )

    @property
    def referer(self) -> str:
        return self.api_config.get(
            "referer",
            f"{self.base_url}/specialty/spec-course/spec-lists/",
        )

    def fetch_list_html(self, filter_params: dict[str, Any]) -> str:
        dir_path = filter_params.get("dir")
        file_name = filter_params.get("file")
        if not dir_path or not file_name:
            raise UniversityAPIError("dir и file обязательны для Almazov")

        url = f"{self.base_url}{self.list_endpoint}"
        response = self._request_with_retry(
            "POST",
            url,
            data={"dir": dir_path, "file": file_name},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": self.referer,
                "Origin": self.base_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return response.text

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        html = self.fetch_list_html(filter_params)
        self.last_seats = parse_seats(html)
        headers, rows = parse_table(html)

        # У Алмазова после БВИ бывают «дыры»: отозванные/битые строки с низким
        # баллом без галки БВИ. Их нельзя считать концом списка — иначе отрежется
        # весь основной конкурс. Стоп только после первого балла >= min_score.
        seen_qualifying_score = False
        for position, row in enumerate(rows_to_dicts(headers, rows), start=1):
            score = parse_almazov_competition_score(row)
            if score is not None and score >= min_score:
                seen_qualifying_score = True
            if self._should_stop_at_score(score, min_score):
                if seen_qualifying_score:
                    break
                continue
            row["_position"] = position
            yield row
