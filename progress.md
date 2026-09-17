# job-search-collector progress

## 2026-09-17 — старт

**Цель:** самостоятельный сборщик LinkedIn Jobs / Indeed по ТЗ
(`../linkedin_indeed_parser_GLM53_spec.md`): поиск, карточки, история,
экспорт, без зависимости от ATS-парсера.

**Пилот доступности (reports/access-feasibility.md):**
- LinkedIn: robots `User-agent: * → Disallow: /` + запрет ToS → BLOCKED (policy).
- Indeed: robots разрешает `/jobs?q=...&start=N` (шаг 10, ≤90), запрещает
  `/job/`, `/rc/`, `/m/viewjob`; живые запросы www/uk → HTTP 403 → BLOCKED (technical).
- Firecrawl для повторного захода после 403 не применяется (запрещено ТЗ, п.6).

**Сделано:**
- скелет проекта, stdlib-стек (отклонение от ТЗ зафиксировано в README);
- коннекторы + чистые парсеры LinkedIn/Indeed (fixtures), JSON-LD приоритет;
- SQLite (runs/hits/jobs/observations/tasks/attempts/duplicate_links), raw-store;
- нормализация дат/зарплат, quality (blocked-page, completeness), дедупликация;
- CLI: doctor / collect(dry-run) / import / status / export (UTF-8 в консоли);
- тесты unittest: **38/38 OK** (без сети, fixtures);
- сквозная приёмка: doctor→dry-run→import→status→export;
  повторный импорт идемпотентен (new=0 upd=0 unchanged=5);
  collect фиксирует blocked по обоим источникам, exit 2.

**Статус приёмки (reports/acceptance.md):**
- JobSpy-пилот (решение владельца): **обе площадки LIVE_VERIFIED** —
  LinkedIn 10/10 (ручная сверка карточки Astronomer совпала полностью),
  Indeed 10/10 (косвенная сверка: Spendesk BDR виден в LinkedIn-выдаче
  того же дня; гостевой /viewjob = 401).
- Конвейер: jobspy CSV → import (с фильтром по source) → SQLite → export;
  20 вакансий, идемпотентно, 1 weak-связь Spendesk между площадками.
- Правовой статус JobSpy-канала задокументирован (LinkedIn ToS-риск);
  прод-решение за владельцем; альтернативы: SerpApi от $25/мес,
  TheirStack от $49/мес.

**Следующий шаг:** решение владельца о регулярном прод-сборе через JobSpy
(обёртка: расписание + лимиты + идемпотентный импорт, ядро не меняется)
или переход на SerpApi/TheirStack без ToS-риска.
