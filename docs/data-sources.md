# Источники данных о поступающих

Документ описывает, как приложение получает списки абитуриентов из медицинских университетов.

## Общая схема

```mermaid
flowchart LR
    Beat[Celery Beat 1ч] --> Sync[sync_all_active]
    Manual[Кнопка Обновить] --> Sync
    Sync --> Factory[get_university_client]
    Factory --> Client1[1spbgmu POST]
    Factory --> Client2[gpmu GET]
    Factory --> Client3[almazov POST HTML]
    Factory --> Client4[szgmu GET HTML]
    Factory --> Client5[sechenov GET HTML paged]
    Factory --> Client6[rsmu GET JSON chain]
    Factory --> Client7[cpk_msu GET HTML]
    Factory --> Client8[spbu POST JSON+HTML]
    Client1 --> API1[abit.1spbgmu.ru]
    Client2 --> API2[spiski.gpmu.org]
    Client3 --> API3[abit.almazovcentre.ru]
    Client4 --> API4[szgmu.ru]
    Client5 --> API5[priem.sechenov.ru]
    Client6 --> API6[submitted.rsmu.ru]
    Client7 --> API7[cpk.msu.ru]
    Client8 --> API8[enrollelists.spbu.ru]
    Sync --> DB[(ApplicantProfile)]
```

Каждый **медицинский университет** хранит `api_config` с полем `provider`, определяющим клиент.

Каждое **направление** хранит:
- `filter_params` — параметры запроса (уникальны для provider)
- `min_fetch_score` — порог остановки пагинации (по умолчанию 200)
- `seats` — количество бюджетных мест (из API или seed)

## Пороговая пагинация

Списки отсортированы по конкурсным баллам по убыванию. Приложение **не скачивает весь список**, а останавливается, когда встречает абитуриента с баллом **строго ниже** `min_fetch_score` направления.

**Исключение для нулевых баллов:** абитуриенты с `0` баллов в начале списка (олимпиадники, БВИ) **не вызывают остановку**. Они всегда сохраняются. Остановка срабатывает только на первом абитуриенте с баллом `> 0` и `< min_fetch_score`.

Пример (порог 200):

| Позиция | Баллы | Действие |
|---------|-------|----------|
| 1–3     | 0     | Сохранить (олимпиадники) |
| 4–500   | 310…200 | Сохранить |
| 501     | 199   | **Остановка**, дальше не качаем |

---

## Provider: `1spbgmu` — Первый мед (СПб)

**URL:** `https://abit.1spbgmu.ru`

### api_config

```json
{
  "provider": "1spbgmu",
  "base_url": "https://abit.1spbgmu.ru",
  "csrf_page": "/hod-priema/spiski-postupayushih/",
  "list_endpoint": "/applcompetlist/page/",
  "referer": "https://abit.1spbgmu.ru/hod-priema/spiski-postupayushih/"
}
```

### Алгоритм

1. **GET** `csrf_page` → извлечь `csrftoken` из cookie или HTML
2. **POST** `list_endpoint` с JSON-телом:

```json
{
  "limit": 100,
  "offset": 0,
  "csrfmiddlewaretoken": "<token>",
  "sedprofile_name": "Педиатрия",
  "sfaculty_name": "Педиатрический факультет",
  "splacekindname": "Бюджет (Общий конкурс)",
  "srecruitment": "ВПО-2026"
}
```

3. Пагинация: `offset += 100`, пока не сработает порог или `rows` пустой
4. Заголовки: `X-CSRFToken`, `Referer`, `User-Agent`

### Направления (seed)

| Направление    | filter_params |
|----------------|---------------|
| Педиатрия      | `sedprofile_name`, `sfaculty_name`, `splacekindname`, `srecruitment` |
| Лечебное дело  | аналогично, другой факультет/профиль |

**Места:** Лечебное дело — 135, Педиатрия — 15 (задаётся в seed, API не возвращает)

### Маппинг полей ответа

| API поле       | ApplicantProfile |
|----------------|------------------|
| `suniqcode` / `_code` | `abiturient_id` |
| `_position`    | `position` |
| `nsummark`     | `nsummark` |
| `npriority_ssp`| `npriority_ssp` (строка → int) |
| `sstatus_ssp`  | `sstatus_ssp` |
| `ncons4enr`    | `has_enrollment_consent` |

### Пример curl

```bash
# 1. CSRF
curl -c cookies.txt \
  -H "User-Agent: Mozilla/5.0 ..." \
  -H "Referer: https://abit.1spbgmu.ru/hod-priema/spiski-postupayushih/" \
  "https://abit.1spbgmu.ru/hod-priema/spiski-postupayushih/"

# 2. Список
curl -X POST https://abit.1spbgmu.ru/applcompetlist/page/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <token>" \
  -b "csrftoken=<token>" \
  -d '{"limit":100,"offset":0,"sedprofile_name":"Педиатрия",...}'
```

---

## Provider: `gpmu` — Педиатрический (СПб)

**URL:** `https://spiski.gpmu.org`

### api_config

```json
{
  "provider": "gpmu",
  "base_url": "https://spiski.gpmu.org",
  "page_size": 100
}
```

### Алгоритм

1. **GET** `/api/pod/group/{group_id}?page={n}&page_size=100`
2. Пагинация: `page += 1`, пока не сработает порог или страница неполная
3. CSRF не требуется

### Направления (seed)

| Направление    | group_id | URL |
|----------------|----------|-----|
| Лечебное дело  | `kg_4`   | `/api/pod/group/kg_4?page=1&page_size=100` |
| Педиатрия      | `kg_16`  | `/api/pod/group/kg_16?page=1&page_size=100` |

**Места:** берутся из `seats.total` в ответе API при каждой синхронизации

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `Уникальный код` | `abiturient_id` |
| (порядок в списке) | `position` |
| `Сумма конкурсных баллов` | `nsummark` |
| `Приоритет` | `npriority_ssp` (строка → int) |
| `Участвует в конкурсе` | `sstatus_ssp`: `✓` → «Участвует в конкурсе», иначе «На рассмотрении» |
| `Состояние договора` / `Согласие на зачисление` | `has_enrollment_consent`: `✓` → true |

### Структура ответа

```json
{
  "kg_id": "kg_4",
  "name": "Лечебное дело (...)",
  "seats": { "total": 52, "enrolled": 0, "available": 52 },
  "columns": ["Уникальный код", "Сумма конкурсных баллов", ...],
  "rows": [
    {
      "Уникальный код": "1255996",
      "Сумма конкурсных баллов": "0",
      "Приоритет": "1",
      "Состояние заявления": "Принято"
    }
  ]
}
```

### Особенность: олимпиадники с 0 баллов

Первые строки могут иметь `"Сумма конкурсных баллов": "0"` при основании приёма БВИ. Они остаются в списке и **не прерывают** загрузку по порогу.

### Пример curl

```bash
curl "https://spiski.gpmu.org/api/pod/group/kg_4?page=1&page_size=100"
curl "https://spiski.gpmu.org/api/pod/group/kg_16?page=1&page_size=100"
```

---

## Provider: `almazov` — Центр Алмазова

**URL:** `https://abit.almazovcentre.ru`

### api_config

```json
{
  "provider": "almazov",
  "base_url": "https://abit.almazovcentre.ru",
  "list_endpoint": "/wp-content/themes/new-imo-2025/returnNewRanged.php",
  "referer": "https://abit.almazovcentre.ru/specialty/spec-course/spec-lists/"
}
```

### Алгоритм

1. **POST** `list_endpoint` с form-data: `dir`, `file`
2. Ответ — HTML с таблицей и блоком `Всего мест: N`
3. Пагинации нет: весь список в одном ответе, порог применяется при обходе строк
4. CSRF не требуется

### Направления (seed)

| Направление    | file (filter_params) | Места (seed) |
|----------------|----------------------|--------------|
| Лечебное дело  | `000000060_31.05.01 Lechebnoe delo (...)_B.txt` | 162 |
| Педиатрия      | `000000060_31.05.02 Pediatriya (...)_B.txt` | 16 |

**Места:** задаются в seed, при синхронизации обновляются из `<p class='number-places'>Всего мест: N</p>`

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `Уникальный код` | `abiturient_id` |
| (порядок в списке) | `position` |
| `Сумма баллов` | `nsummark` |
| `Приоритет` | `npriority_ssp` |
| `Текущий статус конкурса` | `sstatus_ssp` |
| `Согласие на зачисление` / `Состояние договора` | `has_enrollment_consent`: `✓` → true |

### Пример curl

```bash
curl -X POST "https://abit.almazovcentre.ru/wp-content/themes/new-imo-2025/returnNewRanged.php" \
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" \
  -H "Referer: https://abit.almazovcentre.ru/specialty/spec-course/spec-lists/" \
  -H "Origin: https://abit.almazovcentre.ru" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d "dir=/one_s/spec26/&file=000000060_31.05.01%20Lechebnoe%20delo%20(Osnovnye%20mesta%20v%20ramkakh%20KTsP)_B.txt"
```

---

## Provider: `szgmu` — СЗГМУ Мечникова (СПб)

**URL:** `https://szgmu.ru`

### api_config

```json
{
  "provider": "szgmu",
  "base_url": "https://szgmu.ru"
}
```

### Алгоритм

1. **GET** `/priem2026/spec/stage1/html/lech_budget.php`
2. Ответ — HTML с несколькими `<tbody>`; берётся `tbody#Бюджет` с секцией «В рамках КЦП, общий конкурс»
3. Места из текста `(Количество мест - 97, ...)`
4. Пагинации нет; порог применяется при обходе строк
5. CSRF не требуется

### Направления (seed)

| Направление    | list_path | Места (seed) |
|----------------|-----------|--------------|
| Лечебное дело  | `/priem2026/spec/stage1/html/lech_budget.php` | 97 |

**Места:** задаются в seed, при синхронизации обновляются из HTML секции

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `Уникальный код поступающего` | `abiturient_id` |
| (порядок в списке) | `position` |
| `Сумма конкурсных баллов` | `nsummark` |
| `Приоритет` | `npriority_ssp` |
| (в списке) | `sstatus_ssp`: «Участвует в конкурсе» |
| `Согласие на зачисление` | `has_enrollment_consent`: «Да» → true |

### Пример curl

```bash
curl -s "https://szgmu.ru/priem2026/spec/stage1/html/lech_budget.php" \
  -H "User-Agent: Mozilla/5.0 ..."
```

---

## Provider: `sechenov` — Сеченовский университет (Мск)

**URL:** `https://priem.sechenov.ru`

### api_config

```json
{
  "provider": "sechenov",
  "base_url": "https://priem.sechenov.ru",
  "verify_ssl": false,
  "page_delay": 0.35
}
```

### Алгоритм

1. **GET** `applications.php` с `COMPETITIVE_GROUP_ID` и `appPage_{id}=1,2,3...`
2. На странице 5 заявлений; между запросами пауза `page_delay` (0.35 с)
3. Парсинг HTML-таблицы по `tr[data-app]`
4. Остановка по порогу `min_fetch_score` или при пустой странице
5. CSRF не требуется; SSL-сертификат может быть невалидным (`verify_ssl: false`)

### Направления (seed)

| Направление    | competitive_group_id | Места (seed) |
|----------------|----------------------|--------------|
| Лечебное дело  | `19488`              | 495          |
| Педиатрия      | `19486`              | 31           |

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `УИД` | `abiturient_id` |
| (порядок в списке) | `position` |
| `Сумма конкурсных баллов` | `nsummark` |
| `Приоритет зачисления` | `npriority_ssp` |
| `Статус` | `sstatus_ssp` |
| `Подано согласие` | `has_enrollment_consent`: «Да» → true |

### Пример curl

```bash
curl -k -s "https://priem.sechenov.ru/local/components/firstbit/competition.list/templates/.default/applications.php?COMPETITIVE_GROUP_ID=19488&appPage_19488=1&ADMISSION_LISTS=N&CONTRACT_IS_PAID=N&ORIGINAL_DOCUMENT=N&lang=ru" \
  -H "Referer: https://priem.sechenov.ru/submitted-applicants/"
```

---

## Provider: `rsmu` — Пироговский университет (Мск)

**URL:** `https://submitted.rsmu.ru`

### api_config

```json
{
  "provider": "rsmu",
  "base_url": "https://submitted.rsmu.ru",
  "referer": "https://submitted.rsmu.ru/",
  "admission_title": "Прием на обучение на специалитет - 2026"
}
```

### Алгоритм (цепочка из 4 запросов)

1. **GET** `/data/root.json?v={ts}&_={ts+offset}` → выбрать элемент с `admission_title` (специалитет), взять `file`
2. **GET** `/data/{file}?v=...&_=...` → список дат публикации. Если элементов **больше одного** — предупреждение на главном экране (`MedicalUniversity.sync_warning`), по умолчанию берётся **первый**
3. **GET** `/data/{date_file}?v=...&_=...` → список программ/конкурсов. Для направления выбирается элемент по `program_title` из `filter_params`
4. **GET** `/data/{program_file}?v=...&_=...` → JSON с `plan`, `count`, `applicants[]`

Таймстампы: `v` — текущее время в миллисекундах, `_` — смещение ~3 с от `v`.

Шаги 1–3 кэшируются в памяти процесса на 1 час (общие для всех направлений одного МУ).

Пагинации нет — весь список в одном ответе. Порог `min_fetch_score` применяется при обходе `applicants`.

**Позиция** = порядковый номер в массиве `applicants` (с 1), поле `order` из API **не используется**.

### Направления (seed)

| Направление    | program_title | Места (seed) |
|----------------|---------------|--------------|
| Лечебное дело  | `Лечебное дело (Лечебное дело) Общий конкурс 2026` | 426 |
| Педиатрия      | `Педиатрия Общий конкурс 2026` | 283 |

**Места:** из поля `plan` ответа шага 4; seed задаёт начальные значения.

### Маппинг полей ответа

| API поле | ApplicantProfile |
|----------|------------------|
| `title` | `abiturient_id` |
| (порядок в `applicants`) | `position` |
| `total` | `nsummark` |
| `priority` | `npriority_ssp` |
| `state` | `sstatus_ssp` |
| `approval` | `has_enrollment_consent` |

### Пример curl (шаг 1)

```bash
TS=$(date +%s%3N)
curl -s "https://submitted.rsmu.ru/data/root.json?v=${TS}&_=$((TS+3000))" \
  -H "User-Agent: Mozilla/5.0 ..." \
  -H "Accept: */*" \
  -H "Referer: https://submitted.rsmu.ru/"
```

---

## Provider: `cpk_msu` — МГУ Ломоносова (Мск)

**URL:** `https://cpk.msu.ru`

### api_config

```json
{
  "provider": "cpk_msu",
  "base_url": "https://cpk.msu.ru",
  "verify_ssl": false
}
```

**Баллы за аттестат с отличием:** `honors_diploma_points = 0` (в seed).

### Алгоритм

1. **GET** `/submitted/bachelor/dep_10` (путь задаётся в `filter_params.list_path`)
2. HTML содержит несколько программ и конкурсов. Выбирается секция по `program_name` и `concourse_title`
3. Внутри конкурса две таблицы:
   - **БВИ** («Лица, имеющие право на прием без вступительных испытаний») — в начале общего списка, всегда полностью
   - **Основная** («Лица, не имеющие право…») — с порогом `min_fetch_score`
4. Пагинации нет; места из текста `Всего мест: N.`

### Направления (seed)

| Направление    | list_path | concourse_title | Места (seed) |
|----------------|-----------|-----------------|--------------|
| Лечебное дело  | `/submitted/bachelor/dep_10` | Основные места в рамках КЦП | 46 |

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `ID абитуриента` | `abiturient_id` |
| (порядок: БВИ, затем основная) | `position` |
| `Сумма конкурсных баллов` | `nsummark` (для БВИ — 0) |
| `Приоритет` | `npriority_ssp` |
| `Статус заявления` | `sstatus_ssp` |
| `Наличие согласия на зачисление в МГУ` | `has_enrollment_consent`: «Да» → true |

### Пример curl

```bash
curl -k -s "https://cpk.msu.ru/submitted/bachelor/dep_10" \
  -H "User-Agent: Mozilla/5.0 ..." \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
```

---

## Provider: `spbu` — СПбГУ (СПб)

**URL:** `https://enrollelists.spbu.ru`

### api_config

```json
{
  "provider": "spbu",
  "base_url": "https://enrollelists.spbu.ru",
  "list_endpoint": "/api/reports/priem-list-02/data",
  "referer": "https://enrollelists.spbu.ru/reports/PriemList02.php?...",
  "verify_ssl": false
}
```

### Алгоритм

1. **POST** `/api/reports/priem-list-02/data` с JSON-телом из `filter_params`:
   - `report_priem_list_02_id`
   - `speciality_ids`
   - `filters` (факультет, программа, специальность, форма, финансирование и т.д.)
2. Ответ — JSON с `blocks[]`, в каждом блоке поле `html` с таблицей абитуриентов
3. Места из информационной таблицы: `Количество бюджетных мест: N`
4. Парсинг HTML-таблицы `.table-data table` (заголовки в `<thead>`, строки в `<tbody>`)
5. Пагинации нет; порог `min_fetch_score` при обходе строк

**Олимпиадники/БВИ** в начале списка имеют в колонке «Сумма конкурсных баллов» текст (`БВИ (Победитель ОШ)` и т.п.) — трактуются как 0 баллов и **не останавливают** загрузку по порогу.

### Направления (seed)

| Направление    | speciality_id | Места (seed) |
|----------------|---------------|--------------|
| Лечебное дело  | `7dd29c4f-9a88-47e3-afa8-571940bf95fa` | 21 |

### Маппинг полей ответа

| API колонка (рус.) | ApplicantProfile |
|--------------------|------------------|
| `Уникальный код поступающего` | `abiturient_id` |
| (порядок в таблице) | `position` |
| `Сумма конкурсных баллов` | `nsummark` (нечисловое → 0) |
| `Приоритет зачисления, указанный поступающим по данной КГ` | `npriority_ssp` |
| `Статус` | `sstatus_ssp` |
| `Согласие на зачисление` | `has_enrollment_consent`: «Да» → true |

### Пример curl

```bash
curl -k -s -X POST "https://enrollelists.spbu.ru/api/reports/priem-list-02/data" \
  -H "Content-Type: application/json" \
  -H "Origin: https://enrollelists.spbu.ru" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d '{"report_priem_list_02_id":"...","speciality_ids":["..."],"filters":{...}}'
```

---

## Обработка ошибок (общая)

| Ситуация | Поведение |
|----------|-----------|
| Сеть, timeout, SSL | Retry ×3, exponential backoff |
| HTTP 429 | Читать `Retry-After`, записать в `SyncJob.next_retry_at` |
| HTTP 5xx | Retry ×3 |
| HTTP 4xx (кроме 429) | Fail без retry |

## Rate limit

- **Внутренний:** `sync_interval_seconds` (по умолчанию 3600). Celery Beat раз в час. Кнопка «Обновить сейчас» обходит через `force=True`.
- **Внешний (429):** уважается всегда, даже при `force=True`.

## Seed при запуске

Команда `ensure_seed_data` (вызывается в Docker entrypoint после migrate):

1. **Первый мед (СПб)** — 2 направления (135 и 15 мест)
2. **Педиатрический (СПб)** — 2 направления, provider gpmu
3. **Центр Алмазова** — 2 направления (162 и 16 мест), provider almazov
4. **СЗГМУ Мечникова (СПб)** — Лечебное дело (97 мест), provider szgmu
5. **Сеченовский университет (Мск)** — Лечебное дело (495) и Педиатрия (31), provider sechenov
6. **Пироговский университет (Мск)** — Лечебное дело (426) и Педиатрия (283), provider rsmu
7. **МГУ Ломоносова (Мск)** — Лечебное дело (46), provider cpk_msu, `honors_diploma_points=0`
8. **СПбГУ (СПб)** — Лечебное дело (21), provider spbu

Идемпотентна: `get_or_create` + обновление `filter_params` / `seats` при расхождении.

## Файлы кода

| Файл | Назначение |
|------|------------|
| `apps/admissions/clients/university_client.py` | Клиент 1spbgmu |
| `apps/admissions/clients/gpmu_client.py` | Клиент GPMU |
| `apps/admissions/clients/almazov_client.py` | Клиент Almazov |
| `apps/admissions/clients/almazov_html_parser.py` | Парсер HTML-таблицы Almazov |
| `apps/admissions/clients/szgmu_client.py` | Клиент СЗГМУ |
| `apps/admissions/clients/szgmu_html_parser.py` | Парсер HTML-таблицы СЗГМУ |
| `apps/admissions/clients/sechenov_client.py` | Клиент Сеченова |
| `apps/admissions/clients/sechenov_html_parser.py` | Парсер HTML-таблицы Сеченова |
| `apps/admissions/clients/rsmu_client.py` | Клиент Пироговского (RSMU) |
| `apps/admissions/clients/cpk_msu_client.py` | Клиент МГУ |
| `apps/admissions/clients/cpk_msu_html_parser.py` | Парсер HTML-таблиц МГУ |
| `apps/admissions/clients/spbu_client.py` | Клиент СПбГУ |
| `apps/admissions/clients/spbu_html_parser.py` | Парсер HTML из JSON-ответа СПбГУ |
| `apps/admissions/clients/factory.py` | Выбор клиента по provider |
| `apps/admissions/clients/parsers.py` | Парсинг row → ApplicantProfile |
| `apps/admissions/services/sync_service.py` | Оркестрация синхронизации |
| `apps/universities/seed.py` | Начальные МУ и направления |
