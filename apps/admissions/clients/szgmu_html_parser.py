import re
from html import unescape

from apps.admissions.clients.base import UniversityAPIError

CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
THEAD_RE = re.compile(r"<thead>(.*?)</thead>", re.DOTALL | re.IGNORECASE)
TBODY_RE = re.compile(
    r"<tbody[^>]*\bid=['\"]Бюджет['\"][^>]*>(.*?)</tbody>",
    re.DOTALL | re.IGNORECASE,
)
SEATS_RE = re.compile(r"Количество мест\s*-\s*(\d+)", re.IGNORECASE)


def _clean_cell(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(text.split())


def parse_headers(html: str) -> list[str]:
    thead_match = THEAD_RE.search(html)
    if not thead_match:
        raise UniversityAPIError("Заголовки таблицы не найдены в ответе СЗГМУ")
    headers = [_clean_cell(cell) for cell in CELL_RE.findall(thead_match.group(1))]
    if len(headers) < 2:
        raise UniversityAPIError("Пустой заголовок таблицы СЗГМУ")
    return headers


def _extract_tbody(html: str, section_marker: str) -> str:
    for tbody_match in TBODY_RE.finditer(html):
        tbody_content = tbody_match.group(1)
        if section_marker.lower() in _clean_cell(tbody_content).lower():
            return tbody_content
    raise UniversityAPIError(
        f"Секция «{section_marker}» в tbody#Бюджет не найдена в ответе СЗГМУ"
    )


def parse_seats(section_html: str) -> int | None:
    match = SEATS_RE.search(section_html)
    if not match:
        return None
    return int(match.group(1))


def parse_budget_section(
    html: str,
    *,
    section_marker: str = "общий конкурс",
) -> tuple[int | None, list[str], list[list[str]]]:
    headers = parse_headers(html)
    data_headers = headers[1:]
    col_count = len(data_headers)

    section_html = _extract_tbody(html, section_marker)
    seats = parse_seats(section_html)

    cells = [_clean_cell(cell) for cell in CELL_RE.findall(section_html)]
    if not cells:
        raise UniversityAPIError("Строки абитуриентов не найдены в ответе СЗГМУ")

    data_cells = cells[1:]
    rows = []
    for index in range(0, len(data_cells), col_count):
        chunk = data_cells[index : index + col_count]
        if len(chunk) == col_count:
            rows.append(chunk)

    if not rows:
        raise UniversityAPIError("Не удалось разобрать строки списка СЗГМУ")

    return seats, data_headers, rows


def rows_to_dicts(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    return [dict(zip(headers, row, strict=True)) for row in rows]
