# job-search-collector

Самостоятельный сборщик вакансий LinkedIn Jobs и Indeed: поиск, карточки,
история наблюдений, экспорт. Ядро — чистый stdlib, без внешних сервисов.

## Статус источников (проверено 2026-09-17)

| Источник | Статус | Причина |
|---|---|---|
| LinkedIn | `BLOCKED (policy)` | robots.txt: `User-agent: * → Disallow: /`; User Agreement запрещает автоматический доступ без разрешения LinkedIn |
| Indeed | `BLOCKED (technical)` | robots.txt разрешает поисковые страницы `/jobs?q=...&start=N`, но www/uk-домены отдают HTTP 403 браузерному запросу |

Рабочие пути для данных: импорт CSV/JSON (`import`), лицензированный
провайдер (транспорт `provider`, добавляется при появлении доступа).
Прямой live-сбор включён в код, но остановится с записью `blocked` в отчёт
прогона — без попыток обхода (см. `reports/access-feasibility.md`).

## Запуск

Основной сценарий — JobSpy live-сбор + импорт + экспорт:

```powershell
uv sync                                                        # ставит python-jobspy
uv run python -m unittest discover -s tests                    # 38/38 OK

uv run python pilots/jobspy_pilot.py "Data Scientist" 25 "London, UK" 14 --out ds
uv run python -m jobcollector import --source linkedin --file data/pilot/ds.csv
uv run python -m jobcollector import --source indeed   --file data/pilot/ds.csv
uv run python -m jobcollector export --format csv --out data/export/ds.csv
uv run python -m jobcollector status
```

Развёртывание на сервере (Linux, cron, лимиты) — `DEPLOY.md`.

## Отклонения от ТЗ (осознанные)

- Внешние зависимости (httpx, bs4, pydantic, pyyaml, pytest) заменены на stdlib
  (urllib, html.parser, dataclasses, unittest, json/csv/gzip): первая версия
  не имеет live-канала, и главное требование — воспроизводимая проверка
  всей цепочки в этой среде без установки пакетов.
- Конфиг: JSON — нативно; YAML — при установленном PyYAML, иначе понятная
  ошибка (примеры обоих форматов в `config/`).

## Структура

```
src/jobcollector/
  cli.py           doctor/collect/import/status/export
  scheduler.py     задачи поиска, курсоры, бюджеты
  models.py        SearchSpec, JobCard, JobRecord
  config.py        загрузка конфигурации
  transports/http  urllib: throttle, retry, Retry-After, SSRF-guard
  sources/         linkedin.py, indeed.py: parse_search/parse_detail
  storage.py       SQLite: runs, hits, jobs, observations, tasks
  rawstore.py      gzip raw-ответы без секретов
  normalize.py     даты (относительные/точные), зарплаты, локации
  quality.py       blocked-page, completeness
  deduplicate.py   url-key, сильные/слабые связи площадок
  export.py        CSV UTF-8 BOM + formula-injection guard, JSONL
tests/             unittest, fixtures без сети
```

## Правила сбора

- 403/captcha/auth-wall → статус `blocked`, без эскалации и обхода.
- Пропажа вакансии из выдачи не закрывает её (`availability=observed_open`).
- `first_seen_at` ≠ дата публикации; «30+ days ago» — диапазон, не дата.
- Raw-ответ сохраняется до нормализации; секреты в raw не попадают.

## GDPR & responsible use

**Что собирает инструмент:** вакансии LinkedIn/Indeed (названия, компании,
локации, зарплаты, даты, описания) — данные **об организациях**. Персональные
контакты не извлекаются и не хранятся как поля.

**Нюанс:** в текстах описаний изредка встречаются контакты рекрутеров —
они хранятся как публичный контент источника, только для provenance.

**Минимизация и хранение (Art. 5 GDPR):**
- каждая запись несёт `first_seen_at` / `last_seen_at` (включены в экспорт);
- данные локальны (`data/collector.db`, raw в `data/raw/`);
- retention: удаляйте `data/` или строки, когда список отработан; удаление
  по запросу = удаление строк + реэкспорт;
- SSRF-guard в транспорте; никаких cookies/учёток площадок.

**Граница ответственности:** использование выгрузки для писем людям —
зона оператора (legitimate interest assessment, opt-out, suppression).
Отдельно см. правовой статус JobSpy-канала в `reports/access-feasibility.md`.
