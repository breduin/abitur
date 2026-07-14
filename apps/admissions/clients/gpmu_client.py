from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from apps.admissions.clients.field_parsers import parse_gpmu_competition_score
from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError


GPMU_LECH_GROUP_NAME = "Лечебное дело (на основные места в рамках контрольных цифр приёма)"
GPMU_PED_GROUP_NAME = "Педиатрия (на основные места в рамках контрольных цифр приема)"
GPMU_STOM_GROUP_NAME = (
    "Стоматология  (на основные места в рамках контрольных цифр приема)"
)


class GPMUClient(BaseHTTPClient):
    DEFAULT_PAGE_SIZE = 100
    GROUPS_ENDPOINT = "/api/pod/groups"
    GROUPS_REFERER = "https://spiski.gpmu.org/spisok-podavshikh"

    def __init__(self, api_config: dict[str, Any], session=None):
        super().__init__(api_config, session=session)
        self._groups_by_name: dict[str, str] | None = None

    @property
    def hostname(self) -> str:
        return urlparse(self.api_config["base_url"]).hostname or ""

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @staticmethod
    def _is_dns_error(exc: UniversityAPIError) -> bool:
        message = str(exc).lower()
        return "name resolution" in message or "failed to resolve" in message

    @staticmethod
    def _normalize_group_name(name: str) -> str:
        return name.replace("ё", "е").replace("Ё", "Е").strip().lower()

    def _request_groups_once(self, *, use_fallback: bool) -> dict[str, Any]:
        if use_fallback:
            fallback_ip = self.api_config.get("fallback_ip")
            url = f"https://{fallback_ip}{self.GROUPS_ENDPOINT}"
            headers = {
                "Host": self.hostname,
                "Accept": "*/*",
                "Referer": self.GROUPS_REFERER,
            }
            verify = False
        else:
            url = f"{self.base_url}{self.GROUPS_ENDPOINT}"
            headers = {
                "Accept": "*/*",
                "Referer": self.GROUPS_REFERER,
            }
            verify = True

        response = self._request_with_retry("GET", url, headers=headers, verify=verify)
        try:
            data = response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе GPMU groups") from exc

        if not isinstance(data, dict) or "groups" not in data:
            raise UniversityAPIError("Поле groups отсутствует в ответе GPMU")

        return data

    def fetch_groups(self) -> dict[str, Any]:
        try:
            return self._request_groups_once(use_fallback=False)
        except UniversityAPIError as exc:
            fallback_ip = self.api_config.get("fallback_ip")
            if not fallback_ip or not self._is_dns_error(exc):
                raise
            return self._request_groups_once(use_fallback=True)

    def _get_groups_by_name(self) -> dict[str, str]:
        if self._groups_by_name is None:
            data = self.fetch_groups()
            self._groups_by_name = {}
            for group in data.get("groups") or []:
                name = group.get("name")
                group_id = group.get("id")
                if name and group_id:
                    self._groups_by_name[self._normalize_group_name(name)] = group_id
        return self._groups_by_name

    def resolve_group_id(self, filter_params: dict[str, Any]) -> str:
        group_name = filter_params.get("group_name")
        if group_name:
            group_id = self._get_groups_by_name().get(self._normalize_group_name(group_name))
            if not group_id:
                raise UniversityAPIError(f"Группа GPMU не найдена: {group_name}")
            return group_id

        group_id = filter_params.get("group_id")
        if not group_id:
            raise UniversityAPIError("group_name или group_id обязателен для GPMU")
        return group_id

    def fetch_group_page(
        self,
        group_id: str,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        page_size = page_size or self.api_config.get("page_size", self.DEFAULT_PAGE_SIZE)
        try:
            return self._fetch_group_page_once(group_id, page, page_size, use_fallback=False)
        except UniversityAPIError as exc:
            fallback_ip = self.api_config.get("fallback_ip")
            if not fallback_ip or not self._is_dns_error(exc):
                raise
            return self._fetch_group_page_once(
                group_id,
                page,
                page_size,
                use_fallback=True,
            )

    def _fetch_group_page_once(
        self,
        group_id: str,
        page: int,
        page_size: int,
        *,
        use_fallback: bool,
    ) -> dict[str, Any]:
        if use_fallback:
            fallback_ip = self.api_config.get("fallback_ip")
            url = f"https://{fallback_ip}/api/pod/group/{group_id}"
            headers = {"Host": self.hostname}
            verify = False
        else:
            url = f"{self.base_url}/api/pod/group/{group_id}"
            headers = {}
            verify = True

        response = self._request_with_retry(
            "GET",
            url,
            params={"page": page, "page_size": page_size},
            headers=headers,
            verify=verify,
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
        group_id = self.resolve_group_id(filter_params)

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
                score = parse_gpmu_competition_score(row)
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
