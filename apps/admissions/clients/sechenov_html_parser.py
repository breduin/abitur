import re
import time
from html import unescape

from apps.admissions.clients.base import UniversityAPIError

DATA_ROW_START_RE = re.compile(r'<tr\s+data-app="[^"]*">', re.IGNORECASE)
INNER_TABLE_RE = re.compile(
    r'<table class="table-competition-lists__inner-table">.*?</table>',
    re.DOTALL | re.IGNORECASE,
)
FLOAT_TD_RE = re.compile(
    r'<td class="table-competition-lists__float">\s*'
    r'<table class="table-competition-lists__inner-table">.*?</table>\s*</td>',
    re.DOTALL | re.IGNORECASE,
)
TOOLTIP_RE = re.compile(r'<div class="tooltip">.*?</div>', re.DOTALL | re.IGNORECASE)
TABLE_CLOSE_RE = re.compile(r"</table>\s*</div>", re.IGNORECASE)
POSITION_UID_RE = re.compile(
    r"<td>\s*(\d+)\s*</td>\s*<td>\s*(\d+)",
    re.DOTALL | re.IGNORECASE,
)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)


def _clean_cell(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(text.split())


def iter_data_row_blocks(html: str):
    starts = [match.start() for match in DATA_ROW_START_RE.finditer(html)]
    if not starts:
        return

    for index, start in enumerate(starts):
        if index + 1 < len(starts):
            next_start = starts[index + 1]
        else:
            slice_html = html[start:]
            main_close = TABLE_CLOSE_RE.search(slice_html)
            if main_close:
                last_tr = slice_html[: main_close.start()].rfind("</tr>")
                next_start = start + last_tr + len("</tr>") if last_tr != -1 else len(html)
            else:
                next_start = len(html)
        yield html[start:next_start]


def parse_page_rows(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for block in iter_data_row_blocks(html):
        inner_match = INNER_TABLE_RE.search(block)
        if not inner_match:
            continue

        position_uid = POSITION_UID_RE.search(inner_match.group(0))
        if not position_uid:
            continue

        position, abiturient_id = position_uid.groups()
        rest = FLOAT_TD_RE.sub("", block)
        rest = TOOLTIP_RE.sub("", rest)
        cells = [_clean_cell(cell) for cell in CELL_RE.findall(rest)]

        if len(cells) < 8:
            continue

        rows.append(
            {
                "№": position,
                "УИД": abiturient_id,
                "Основание приема без ВИ": cells[0],
                "Сумма конкурсных баллов": cells[1],
                "Сумма баллов за ВИ": cells[2],
                "Сумма баллов за ИД": cells[4] if len(cells) > 4 else "",
                "Преим. право": cells[6] if len(cells) > 6 else "",
                "Подано согласие": cells[7] if len(cells) > 7 else "",
                "Приоритет зачисления": cells[8] if len(cells) > 8 else "",
                "Статус": cells[9] if len(cells) > 9 else cells[-1],
            }
        )

    return rows


def sleep_between_pages(delay_seconds: float) -> None:
    if delay_seconds > 0:
        time.sleep(delay_seconds)
