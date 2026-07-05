import re
from html import unescape

from apps.admissions.clients.base import UniversityAPIError

SEATS_RE = re.compile(
    r"class=['\"]number-places['\"][^>]*>\s*Всего мест:\s*(\d+)",
    re.IGNORECASE,
)
TABLE_RE = re.compile(
    r"id=['\"]table-list['\"][^>]*>(.*)",
    re.DOTALL | re.IGNORECASE,
)
HEADER_ROW_RE = re.compile(
    r"<tr[^>]*class=['\"]original['\"][^>]*>(.*?)</tr>",
    re.DOTALL | re.IGNORECASE,
)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)


def _clean_cell(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(text.split())


def parse_seats(html: str) -> int | None:
    match = SEATS_RE.search(html)
    if not match:
        return None
    return int(match.group(1))


def parse_table(html: str) -> tuple[list[str], list[list[str]]]:
    table_match = TABLE_RE.search(html)
    if not table_match:
        raise UniversityAPIError("Таблица списка не найдена в ответе Almazov")

    table_content = table_match.group(1)
    header_match = HEADER_ROW_RE.search(table_content)
    if not header_match:
        raise UniversityAPIError("Заголовки таблицы не найдены в ответе Almazov")

    headers = [_clean_cell(cell) for cell in CELL_RE.findall(header_match.group(1))]
    if not headers:
        raise UniversityAPIError("Пустой заголовок таблицы Almazov")

    after_header = table_content.split(header_match.group(0), 1)[1]
    cells = [_clean_cell(cell) for cell in CELL_RE.findall(after_header)]

    col_count = len(headers)
    rows = []
    for index in range(0, len(cells), col_count):
        chunk = cells[index : index + col_count]
        if len(chunk) == col_count:
            rows.append(chunk)

    if not rows:
        raise UniversityAPIError("Строки абитуриентов не найдены в ответе Almazov")

    return headers, rows


def rows_to_dicts(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    return [dict(zip(headers, row, strict=True)) for row in rows]
