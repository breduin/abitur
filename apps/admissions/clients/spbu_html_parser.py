import re
from html import unescape

from apps.admissions.clients.base import UniversityAPIError

CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
APPLICANT_TABLE_RE = re.compile(
    r'<div class="table-data[^"]*">\s*<table[^>]*>(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)
SEATS_RE = re.compile(
    r"Количество бюджетных мест:.*?<td[^>]*>\s*(\d+)\s*</td>",
    re.DOTALL | re.IGNORECASE,
)


def _clean_cell(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(text.split())


def parse_seats(html: str) -> int | None:
    match = SEATS_RE.search(html)
    if not match:
        return None
    return int(match.group(1))


def parse_applicant_table(html: str) -> tuple[list[str], list[list[str]]]:
    table_match = APPLICANT_TABLE_RE.search(html)
    if not table_match:
        raise UniversityAPIError("Таблица абитуриентов не найдена в ответе СПбГУ")

    table_html = table_match.group(1)
    thead_match = re.search(r"<thead>(.*?)</thead>", table_html, re.DOTALL | re.IGNORECASE)
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", table_html, re.DOTALL | re.IGNORECASE)
    if not thead_match or not tbody_match:
        raise UniversityAPIError("Заголовки или строки таблицы СПбГУ не найдены")

    headers = [_clean_cell(cell) for cell in CELL_RE.findall(thead_match.group(1))]
    if len(headers) < 3:
        raise UniversityAPIError("Пустой заголовок таблицы СПбГУ")

    rows: list[list[str]] = []
    for tr_match in TR_RE.finditer(tbody_match.group(1)):
        tr_content = tr_match.group(1)
        if "<td" not in tr_content.lower():
            continue
        cells = [_clean_cell(cell) for cell in CELL_RE.findall(tr_content)]
        if len(cells) == len(headers):
            rows.append(cells)

    if not rows:
        raise UniversityAPIError("Строки абитуриентов не найдены в ответе СПбГУ")

    return headers, rows


def rows_to_dicts(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    return [dict(zip(headers, row, strict=True)) for row in rows]
