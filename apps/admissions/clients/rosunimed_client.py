from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError


class RosunimedClient(BaseHTTPClient):
    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    def fetch_group(self, group_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/admission/competitive/groups/{group_id}"
        response = self._request_with_retry(
            "GET",
            url,
            params={"listType": "applicants"},
            headers={"Accept": "application/json, text/plain, */*"},
            verify=self.api_config.get("verify_ssl", False),
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе Росунимед") from exc

        if "incoming" not in data:
            raise UniversityAPIError("Поле incoming отсутствует в ответе Росунимед")

        count = data.get("count")
        if count is not None:
            try:
                self.last_seats = int(count)
            except (TypeError, ValueError):
                pass

        return data

    @staticmethod
    def _parse_competition_score(row: dict[str, Any]) -> int | None:
        if row.get("reasonWithoutAdmission"):
            return 0

        rating_total = row.get("ratingTotal")
        if rating_total is None or str(rating_total).strip() == "":
            return None

        try:
            return int(str(rating_total).strip())
        except (TypeError, ValueError):
            return None

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        group_id = filter_params.get("group_id")
        if not group_id:
            raise UniversityAPIError("group_id обязателен для Росунимед")

        data = self.fetch_group(group_id)
        incoming = data.get("incoming") or []

        for position, row in enumerate(incoming, start=1):
            score = self._parse_competition_score(row)
            if score is None:
                break
            if self._should_stop_at_score(score, min_score):
                break
            row["_position"] = position
            yield row
