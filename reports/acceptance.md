# Отчёт приёмки — job-search-collector 0.1.0 (2026-09-17)

## JobSpy-пилот (обновление от 2026-09-17, вечером)

По решению владельца выполнен live-пилот через JobSpy (`python-jobspy` 0.31.0,
`pilots/jobspy_pilot.py`, без прокси, без обхода CAPTCHA):

- **LinkedIn: LIVE_VERIFIED.** 10/10 карточек, все поля 100%
  (title/company/location/дата/description/source_url). Ручная сверка
  карточки 4459053566 (Astronomer, SDR London hybrid) с живой гостевой
  страницей: полное совпадение, включая дату («1 day ago» = 2026-09-16)
  и полный текст описания.
- **Indeed: LIVE_VERIFIED (косвенно).** 10/10 карточек, поля 100%,
  описания полные (Spendesk BDR, 5 889 символов). Прямая гостевая сверка
  /viewjob недоступна (HTTP 401 auth-wall); кросс-проверка: Spendesk BDR
  London параллельно виден в LinkedIn-выдаче того же дня.
- **Конвейер:** jobspy CSV → import (фильтр по source) → SQLite → export.
  20 вакансий (10+10), повторный импорт идемпотентен (unchanged=10),
  найдена 1 weak-связь Spendesk BDR между площадками.
- **Правовой статус канала:** JobSpy обращается к площадкам как гость
  c браузерным TLS-отпечатком (tls-client). Для LinkedIn это противоречит
  robots (Disallow: /) и User Agreement; для Indeed — зона периодических
  403. Пилот выполнен по явному решению владельца; для регулярного
  прод-сбора принятие этого риска остаётся за владельцем.
  Альтернативы без ToS-риска: SerpApi Google Jobs (от $25/мес),
  TheirStack (от $49/мес).

## Статусы источников

| Источник | Прямой доступ | Через JobSpy |
|---|---|---|
| LinkedIn | BLOCKED (policy) | **LIVE_VERIFIED** (пилот 10/10) |
| Indeed | BLOCKED (technical 403) | **LIVE_VERIFIED** (пилот 10/10, сверка косвенная) |

## Что проверено ранее (fixtures + импорт)

- Юнит-тесты: **38/38 OK** (unittest, без сети):
  даты (relative/range/exact/just posted/unparsable), зарплаты (GBP/USD,
  диапазоны, мусор), гео (UK/US-штаты/CA-провинции/unknown), сеньорити,
  blocked-page (challenge при HTTP 200), парсеры LinkedIn (3 карточки,
  все поля) и Indeed (2 карточки, jk-идентификаторы, зарплата, курсор),
  потолок пагинации Indeed start=90/100 по robots, идемпотентность
  upsert, отсутствие ложных закрытий, кросс-запросный дедуп,
  url-key нормализация, слабые межплощадочные кандидаты,
  CSV BOM + formula-injection guard, JSONL roundtrip.
- Сквозной CLI (Windows, uv, Python 3.12.14):
  `doctor` → план 12 страниц, статусы live;
  `collect --dry-run` → план без сети;
  `collect` → оба источника честно зафиксировали `blocked` с причиной,
  exit code 2 (все источники заблокированы), 0 вакансий от live;
  `import` demo-CSV → 5 вакансий; повторный импорт →
  new=0 upd=0 unchanged=5 (идемпотентность, дрейф relative-дат
  не порождает ложных обновлений);
  `export` → CSV UTF-8 BOM и JSONL по 5 строк.
- Raw-store: сохранение gzipped JSON с redaction секретов
  (проверено юнит-покрытием redact-регекса в rawstore).

## Честные ограничения

- Live-сбор не выполнен и не мог быть выполнен: прямой доступ закрыт
  (см. access-feasibility.md). Ни одна вакансия не получена из live-поиска.
- Описания Indeed в схеме — snippet/JSON-LD выдачи; детальные страницы
  не запрашиваются (robots).
- `company_website` не резолвится из названия (нет источника) — пусто.
- Межплощадочные связи: только weak-кандидаты при совпадении
  company+title+city; strong-связи требуют общего apply_url/requisition ID.
- Firecrawl не подключён: по ТЗ не применяется для обхода 403;
  конфигурационная заготовка в .env.example.
- pyyaml не установлен → yaml-конфиг недоступен, json работает
  (doctor это показывает).

## Блокер для LIVE_VERIFIED

Нужен разрешённый канал: партнёрский ключ LinkedIn, лицензированный
job-data провайдер или пользовательские выгрузки. После появления —
транспорты provider/import уже готовы принять данные без изменения ядра.
