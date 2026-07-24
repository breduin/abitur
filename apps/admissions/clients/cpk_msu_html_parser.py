import re
from html import unescape

from apps.admissions.clients.base import UniversityAPIError

CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
SECTION_RE = re.compile(
    r'<h4 class="submitted-section-title"[^>]*>\s*Образовательная программа:\s*([^<]+?)\s*</h4>(.*?)(?=<h4 class="submitted-section-title"|\Z)',
    re.DOTALL | re.IGNORECASE,
)
CONCOURSE_RE = re.compile(
    r'<div class="submitted-concourse">.*?<h4 class="submitted-concourse-title"[^>]*>\s*([^<]+?)\s*</h4>(.*?)(?=<div class="submitted-concourse">|\Z)',
    re.DOTALL | re.IGNORECASE,
)
TABLE_RE = re.compile(
    r'<table class="submitted-table">(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)
SEATS_RE = re.compile(r"Всего мест:\s*(\d+)", re.IGNORECASE)
BVI_MARKER = "имеющие право на прием без вступительных испытаний"
MAIN_MARKER = "не имеющие право на прием без вступительных испытаний"
BVI_FLAG_HEADER = "Право БВИ заявлено"


def _clean_cell(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(text.split())


def _normalize_header(value: str) -> str:
    return re.sub(r"\s*\*+$", "", value).strip()


def _flatten_table_headers(header_rows: list[list[str]]) -> list[str]:
    if not header_rows:
        raise UniversityAPIError("Пустые заголовки таблицы МГУ")

    if len(header_rows) == 1:
        return [_normalize_header(cell) for cell in header_rows[0]]

    secondary = [_normalize_header(cell) for cell in header_rows[1] if _normalize_header(cell)]
    names: list[str] = []
    sub_idx = 0
    for cell in header_rows[0]:
        norm = _normalize_header(cell)
        if not norm:
            continue
        if "Баллы за вступительные испытания" in norm:
            while sub_idx < len(secondary):
                names.append(secondary[sub_idx])
                sub_idx += 1
        else:
            names.append(norm)
    return names


def _parse_table(tbody_html: str) -> tuple[list[str], list[list[str]]]:
    header_rows: list[list[str]] = []
    data_rows: list[list[str]] = []

    for tr_match in TR_RE.finditer(tbody_html):
        tr_content = tr_match.group(1)
        cells = [_clean_cell(cell) for cell in CELL_RE.findall(tr_content)]
        if not cells:
            continue
        if "<th" in tr_content.lower():
            header_rows.append(cells)
            continue
        if "<td" in tr_content.lower():
            data_rows.append(cells)

    if not header_rows:
        return [], []

    headers = _flatten_table_headers(header_rows)
    return headers, data_rows


def _rows_to_dicts(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        if len(row) != len(headers):
            continue
        result.append(dict(zip(headers, row, strict=True)))
    return result


def _extract_program_section(html: str, program_name: str) -> str:
    for match in SECTION_RE.finditer(html):
        name = _clean_cell(match.group(1))
        if name == program_name:
            return match.group(2)
    raise UniversityAPIError(f"Программа «{program_name}» не найдена в ответе МГУ")


def _extract_concourse_section(program_html: str, concourse_title: str) -> str:
    for match in CONCOURSE_RE.finditer(program_html):
        title = _clean_cell(match.group(1))
        if title == concourse_title:
            return match.group(2)
    raise UniversityAPIError(
        f"Конкурс «{concourse_title}» не найден в ответе МГУ"
    )


def _split_legacy_tables(concourse_html: str) -> tuple[str | None, str | None] | None:
    """Старый формат: две таблицы с заголовками h5 про БВИ / основную."""
    bvi_pos = concourse_html.lower().find(BVI_MARKER)
    main_pos = concourse_html.lower().find(MAIN_MARKER)
    if main_pos == -1:
        return None

    bvi_html = concourse_html[bvi_pos:main_pos] if bvi_pos != -1 else None
    main_html = concourse_html[main_pos:]
    return bvi_html, main_html


def _parse_table_in_block(block_html: str | None) -> list[dict[str, str]]:
    if not block_html:
        return []

    table_match = TABLE_RE.search(block_html)
    if not table_match:
        return []

    headers, rows = _parse_table(table_match.group(1))
    if not headers:
        return []
    return _rows_to_dicts(headers, rows)


def _is_bvi_flag(value: str) -> bool:
    return value.strip().lower() == "да"


def _split_rows_by_bvi_flag(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Новый формат: одна таблица с колонкой «Право БВИ заявлено»."""
    if not rows:
        return [], []
    if BVI_FLAG_HEADER not in rows[0]:
        return [], rows

    bvi_rows: list[dict[str, str]] = []
    main_rows: list[dict[str, str]] = []
    for row in rows:
        if _is_bvi_flag(row.get(BVI_FLAG_HEADER, "")):
            bvi_rows.append(row)
        else:
            main_rows.append(row)
    return bvi_rows, main_rows


def parse_concourse_section(
    html: str,
    *,
    program_name: str,
    concourse_title: str,
) -> tuple[int | None, list[dict[str, str]], list[dict[str, str]]]:
    program_html = _extract_program_section(html, program_name)
    concourse_html = _extract_concourse_section(program_html, concourse_title)

    seats_match = SEATS_RE.search(concourse_html)
    seats = int(seats_match.group(1)) if seats_match else None

    legacy = _split_legacy_tables(concourse_html)
    if legacy is not None:
        bvi_html, main_html = legacy
        bvi_rows = _parse_table_in_block(bvi_html)
        main_rows = _parse_table_in_block(main_html)
    else:
        bvi_rows, main_rows = _split_rows_by_bvi_flag(
            _parse_table_in_block(concourse_html)
        )

    if not bvi_rows and not main_rows:
        raise UniversityAPIError("Строки абитуриентов не найдены в ответе МГУ")

    return seats, bvi_rows, main_rows