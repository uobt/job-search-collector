# DEPLOY — развёртывание job-search-collector на сервере

Для технического специалиста. Проверено на Python 3.12 (Windows + uv);
ядро — чистый stdlib, live-сбор — библиотека python-jobspy.

## 1. Требования

- Python **3.12+** (обязательно: JobSpy требует 3.10+, тестировано на 3.12.14)
- Linux x86_64 или Windows; ~200 МБ диска под venv
- Исходящий HTTPS (linkedin.com, uk.indeed.com)

## 2. Установка

Вариант A — uv (рекомендован, сам ставит Python):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # если uv нет
cd job-search-collector
uv sync
uv run python -m unittest discover -s tests   # должно быть: Ran 38 tests ... OK
```

Вариант B — pip:

```bash
cd job-search-collector
python3.12 -m venv .venv
source .venv/bin/activate
pip install .
python -m unittest discover -s tests
```

## 3. Проверка окружения

```bash
uv run python -m jobcollector doctor
uv run python -m jobcollector status
```

`doctor` покажет план сбора и статусы источников. Переменные окружения
не требуются (FIRECRAWL_*/JOB_PROVIDER_* в `.env.example` — заготовки).

## 4. Регулярный сбор (основной сценарий)

Одна команда — collect.sh — делает полный цикл: JobSpy → CSV → импорт в
SQLite → экспорт:

```bash
chmod +x bin/collect.sh
./bin/collect.sh "Data Scientist" 25 "London, UK" 14 ds_london
# параметры: query results_per_site location days_back [stem]
```

Cron — раз в два дня в 07:00:

```cron
0 7 */2 * * cd /opt/job-search-collector && ./bin/collect.sh "Data Scientist" 25 "London, UK" 14 >> data/logs/collect.log 2>&1
```

Разовые команды без скрипта:

```bash
uv run python pilots/jobspy_pilot.py "Query" 25 "City, CC" 14 --out stem
uv run python -m jobcollector import --source linkedin --file data/pilot/stem.csv
uv run python -m jobcollector import --source indeed   --file data/pilot/stem.csv
uv run python -m jobcollector export --format csv --out data/export/stem.csv
uv run python -m jobcollector status
```

## 5. Каталоги данных

| Путь | Что там |
|---|---|
| `data/collector.db` | SQLite (WAL): вакансии, история, прогоны. Один writer |
| `data/pilot/*.csv` | сырые выдачи JobSpy по прогонам |
| `data/export/*.csv` | экспорт после нормализации (UTF-8 BOM) |
| `data/raw/` | gzipped raw-ответы прямого транспорта (если включится) |

Бэкап = копия `data/collector.db` (+ wal при активной записи).

## 6. Лимиты и настройки

- `results_wanted` держать ≤ 50 на площадку за прогон; `hours_old` ≤ 14 дней.
- Интервал между прогонами ≥ 24 ч: обе площадки чувствительны к частоте
  (LinkedIn может отдавать пустую выдачу, Indeed — 403).
- При признаках блокировки (0 строк, CAPTCHA в логах) — пауза 24–48 ч,
  снижение объёма. Скрипт честно пишет `blocked`/`0 строк`, не маскирует.
- Конфиг поиска: `config/searches.example.json` (для прямого `collect`).

## 7. Правовая заметка (важно)

JobSpy обращается к LinkedIn/Indeed как гость с браузерным TLS-отпечатком.
Для LinkedIn это противоречит их robots/ToS, для Indeed — зона периодических
403. Решение о регулярном использовании принято владельцем проекта
(см. `reports/access-feasibility.md`, `reports/acceptance.md`).
Альтернатива без ToS-риска — SerpApi Google Jobs (от $25/мес) или
TheirStack (от $49/мес); коннекторы подключаются в `src/jobcollector/
transports/` без изменения ядра.

## 8. Что уже проверено

- 38/38 юнит-тестов (без сети).
- Live-пилоты: SDR London 20/20, Data Scientist London 50/50 (LinkedIn 25 +
  Indeed 25), 100% заполненность полей, ручная сверка карточек.
- Идемпотентный повторный импорт; межплощадочная дедупликация.

## 9. Структура

```
src/jobcollector/    ядро: CLI, модели, SQLite, нормализация, дедуп, экспорт
pilots/              jobspy_pilot.py (параметризованный live-сбор)
bin/collect.sh       полный цикл одной командой
config/              примеры конфигурации поиска
tests/ + fixtures    38 тестов без сети
reports/             доступность источников, отчёт приёмки
examples/            demo-CSV для проверки импорта
```
