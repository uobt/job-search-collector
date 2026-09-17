# Отчёт о доступности источников (live-пилот)

Дата: 2026-09-17. Зонды: robots.txt обеих площадок, поисковые URL,
браузерный User-Agent, без cookies/прокси/stealth.

## LinkedIn Jobs

- robots.txt (200): шапка — «The use of robots or other automated means to
  access LinkedIn without the express permission of LinkedIn is strictly
  prohibited». Секция `User-agent: *` → `Disallow: /` (полный запрет).
  Для Googlebot дополнительно закрыты `/jobs-guest/`, `/jsearch*`,
  `/api/jobPostings/*`.
- User Agreement прямо запрещает crawlers/scrapers.
- Вывод: **BLOCKED (policy)**. Разрешённые пути: партнёрский доступ
  (Apply Connect / Talent Solutions), лицензированный поставщик, импорт.

## Indeed

- robots.txt www/uk (200): `User-agent: * → Allow: /` с исключениями.
  Разрешены поисковые страницы с пагинацией `start=0..90` (шаг 10).
  Запрещены карточки `/job/`, `/rc/`, `/m/viewjob?`, `/*rt=nc`, RSS.
- ToS Indeed: ползти можно «solely as outlined in our robots.txt» —
  то есть поисковые страницы формально разрешены, карточки — нет.
- Живые запросы `https://www.indeed.com/jobs?q=...&l=London&start=0`
  и `https://uk.indeed.com/jobs?...` с браузерным UA → **HTTP 403** (WAF).
- Вывод: **BLOCKED (technical)**. Повторные попытки/смена транспорта
  для обхода 403 не выполняются (ТЗ, п.6: Firecrawl не применяется
  для повторного захода после отказа источника).
- Следствие для схемы данных: описания берутся из JSON-LD поисковой
  страницы, если он есть; иначе snippet с `completeness=truncated`.
  Детальные страницы Indeed не запрашиваются (robots).

## Решение

- Live-сбор обеих площадок выключен политикой безопасности проекта:
  коннекторы существуют, но `collect` фиксирует `blocked` с причиной.
- Рабочий сквозной путь — `import` (CSV/JSON/JSONL) → SQLite → экспорт.
- Для LIVE_VERIFIED требуется: партнёрский ключ LinkedIn, лицензированный
  job-data провайдер или периодические выгрузки от владельца аккаунта.
