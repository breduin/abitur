import time
from collections.abc import Iterator
from typing import Any

from apps.admissions.clients.base import BaseHTTPClient, UniversityAPIError

_NAV_CACHE: dict[str, tuple[float, list[dict[str, Any]], str]] = {}
_CACHE_TTL_SECONDS = 3600


class RSMUClient(BaseHTTPClient):
    DEFAULT_ADMISSION_TITLE = "Прием на обучение на специалитет - 2026"
    DEFAULT_REFERER = "https://submitted.rsmu.ru/"
    TIMESTAMP_OFFSET_MS = 3000

    def __init__(self, api_config: dict[str, Any], session=None):
        super().__init__(api_config, session=session)
        self.sync_warning = ""

    @property
    def base_url(self) -> str:
        return self.api_config["base_url"].rstrip("/")

    @property
    def referer(self) -> str:
        return self.api_config.get("referer", self.DEFAULT_REFERER)

    @property
    def admission_title(self) -> str:
        return self.api_config.get("admission_title", self.DEFAULT_ADMISSION_TITLE)

    @classmethod
    def get_cached_sync_warning(cls, base_url: str) -> str:
        cached = _NAV_CACHE.get(base_url.rstrip("/"))
        if cached:
            return cached[2]
        return ""

    def _timestamps(self) -> tuple[int, int]:
        version = int(time.time() * 1000)
        return version, version + self.TIMESTAMP_OFFSET_MS

    def _fetch_json(self, filename: str) -> Any:
        version, cache_buster = self._timestamps()
        url = f"{self.base_url}/data/{filename}"
        response = self._request_with_retry(
            "GET",
            url,
            params={"v": version, "_": cache_buster},
            headers={
                "Accept": "*/*",
                "Referer": self.referer,
            },
        )
        try:
            return response.json()
        except ValueError as exc:
            raise UniversityAPIError("Некорректный JSON в ответе RSMU") from exc

    def _get_programs_catalog(self) -> tuple[list[dict[str, Any]], str]:
        cache_key = self.base_url
        now = time.time()
        cached = _NAV_CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1], cached[2]

        root = self._fetch_json("root.json")
        if not isinstance(root, list):
            raise UniversityAPIError("root.json RSMU: ожидался список")

        admission_entry = next(
            (item for item in root if item.get("title") == self.admission_title),
            None,
        )
        if not admission_entry:
            raise UniversityAPIError(
                f"Не найден вид обучения RSMU: {self.admission_title}"
            )

        dates = self._fetch_json(admission_entry["file"])
        if not isinstance(dates, list) or not dates:
            raise UniversityAPIError("Пустой список дат RSMU")

        sync_warning = ""
        if len(dates) > 1:
            titles = ", ".join(str(item.get("title", "?")) for item in dates)
            first_title = dates[0].get("title", "?")
            sync_warning = (
                "Пироговский университет: доступно несколько дат списков "
                f"({titles}). Используется первая: {first_title}."
            )

        programs = self._fetch_json(dates[0]["file"])
        if not isinstance(programs, list):
            raise UniversityAPIError("Список программ RSMU: ожидался массив")

        _NAV_CACHE[cache_key] = (now, programs, sync_warning)
        return programs, sync_warning

    def _resolve_program_file(
        self,
        programs: list[dict[str, Any]],
        program_title: str,
    ) -> str:
        program_entry = next(
            (item for item in programs if item.get("title") == program_title),
            None,
        )
        if not program_entry:
            raise UniversityAPIError(f"Не найдена программа RSMU: {program_title}")
        return program_entry["file"]

    def fetch_all_above_threshold(
        self,
        filter_params: dict[str, Any],
        min_score: int,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        program_title = filter_params.get("program_title")
        if not program_title:
            raise UniversityAPIError("program_title обязателен для RSMU")

        programs, self.sync_warning = self._get_programs_catalog()
        program_file = self._resolve_program_file(programs, program_title)

        data = self._fetch_json(program_file)
        if not isinstance(data, dict):
            raise UniversityAPIError("Ответ программы RSMU: ожидался объект")

        plan = data.get("plan")
        if plan is not None:
            try:
                self.last_seats = int(plan)
            except (TypeError, ValueError):
                self.last_seats = None
        else:
            seats = filter_params.get("seats")
            if seats is not None:
                try:
                    self.last_seats = int(seats)
                except (TypeError, ValueError):
                    self.last_seats = None

        applicants = data.get("applicants") or []
        position = 0
        for applicant in applicants:
            score = self._parse_score(applicant.get("total"))
            if self._should_stop_at_score(score, min_score):
                break
            position += 1
            applicant["_position"] = position
            yield applicant
