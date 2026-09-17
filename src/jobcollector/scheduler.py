"""Планировщик: задачи поиска, курсоры, лимиты ТЗ/robots, сквозной прогон."""

from __future__ import annotations

from dataclasses import dataclass

from .deduplicate import cross_source_basis, cross_source_candidate
from .models import SearchSpec, SearchPage
from .normalize import normalize_card
from .quality import classify_search_page
from .sources.base import Connector, SourceBlocked
from .storage import Store


@dataclass
class RunReport:
    run_id: int
    source: str
    requests: int = 0
    cards: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    unchanged: int = 0
    status: str = "running"
    stop_reason: str | None = None
    note: str | None = None


def plan(spec: SearchSpec) -> list[dict]:
    """Сухой план: какие страницы будет обойти. Без сети."""
    tasks = []
    for source in spec.sources:
        for query in spec.queries:
            for location in spec.locations:
                pages = min(spec.max_pages_per_search, 10)
                for page in range(pages):
                    tasks.append({
                        "source": source, "query": query,
                        "location": f"{location.city or ''}/{location.country}".lstrip("/"),
                        "page": page,
                    })
    return tasks


def excluded(title: str | None, spec: SearchSpec) -> bool:
    if not title or not spec.exclude_titles:
        return False
    lowered = title.lower()
    return any(word.lower() in lowered for word in spec.exclude_titles)


def run_source(spec: SearchSpec, source_code: str, connector: Connector,
               store: Store, run_id: int, dry_run: bool = False) -> RunReport:
    """Прогон одного источника. Live заблокирован → честный отчёт, без обхода."""
    report = RunReport(run_id=run_id, source=source_code)

    if not connector.live_allowed:
        report.status = "blocked"
        report.stop_reason = "policy"
        report.note = connector.policy_reason
        store.note_run(run_id, status="blocked", stop_reason="policy",
                       note=connector.policy_reason)
        return report

    total_for_source = 0
    for query in spec.queries:
        for location in spec.locations:
            cursor: str | None = None
            pages = 0
            while pages < spec.max_pages_per_search and \
                    total_for_source < spec.max_results_per_search:
                url = connector.build_search_url(spec, query, location, cursor)
                if dry_run:
                    report.requests += 1
                    pages += 1
                    cursor = str((int(cursor or 0)) + connector.page_step)
                    continue
                try:
                    from .transports.http import TransportError, HttpTransport
                    transport = HttpTransport(
                        delay_seconds=spec.transport.request_delay_seconds,
                        timeout=spec.transport.timeout_seconds,
                        max_retries=spec.transport.max_retries)
                    doc = transport.get(url)
                except TransportError as exc:
                    report.status = "blocked" if exc.blocked else "failed"
                    report.stop_reason = "blocked" if exc.blocked else "failed"
                    report.note = str(exc)
                    store.log_attempt(run_id, source_code, url, exc.status,
                                      "http", 0, str(exc))
                    store.note_run(run_id, status=report.status,
                                   stop_reason=report.stop_reason,
                                   note=report.note)
                    return report

                from .rawstore import save_raw
                raw_ref = save_raw(_data_root(store), source_code, doc)
                store.log_attempt(run_id, source_code, url, doc.status,
                                  "http", 0, None)

                page: SearchPage = connector.parse_search(doc.content)
                status, stop = classify_search_page(doc.content, len(page.cards))
                if status == "blocked":
                    report.status, report.stop_reason = "blocked", "blocked"
                    report.note = "страница-вызов вместо выдачи (HTTP 200)"
                    store.note_run(run_id, status="blocked", stop_reason="blocked",
                                   note=report.note)
                    return report

                rank = 0
                for card in page.cards:
                    if total_for_source >= spec.max_results_per_search:
                        break
                    if excluded(card.title, spec):
                        continue
                    record = normalize_card(card, acquisition="live_search",
                                            raw_ref=raw_ref)
                    event = store.upsert_job(record)
                    if event == "first_seen":
                        report.new_jobs += 1
                    elif event == "updated":
                        report.updated_jobs += 1
                    else:
                        report.unchanged += 1
                    store.record_hit(run_id, record, query,
                                     f"{location.city or ''}/{location.country}",
                                     pages, rank)
                    rank += 1
                    total_for_source += 1
                    report.cards += 1

                report.requests += 1
                pages += 1
                cursor = page.next_cursor
                if stop == "no_results" or not cursor:
                    report.stop_reason = report.stop_reason or (
                        "no_results" if stop == "no_results" else "exhausted")
                    break

    report.status = "completed"
    report.stop_reason = report.stop_reason or (
        "capped_results" if total_for_source >= spec.max_results_per_search
        else "capped_pages")
    store.note_run(run_id, status="completed", stop_reason=report.stop_reason,
                   requests=report.requests, cards=report.cards,
                   new_jobs=report.new_jobs, updated_jobs=report.updated_jobs)
    return report


def link_cross_source_duplicates(store: Store) -> int:
    """Слабые/сильные связи между LinkedIn и Indeed записями (без слияния)."""
    rows = store.jobs(availability=None)
    shims = [_DedupRow(row) for row in rows]
    links = []
    for i, a in enumerate(shims):
        for b in shims[i + 1:]:
            basis = cross_source_basis(a, b) or cross_source_candidate(a, b)
            if basis:
                links.append((a.source, a.source_job_id,
                              b.source, b.source_job_id, basis))
    return store.link_duplicates(links)


class _DedupRow:
    """Attribute-доступ к sqlite3.Row для функций дедупликации."""

    __slots__ = ("source", "source_job_id", "source_url", "apply_url",
                 "requisition_id", "company_name", "title", "city")

    def __init__(self, row):
        self.source = row["source"]
        self.source_job_id = row["source_job_id"]
        self.source_url = row["source_url"]
        self.apply_url = row["apply_url"]
        self.requisition_id = None
        self.company_name = row["company_name"]
        self.title = row["title"]
        self.city = row["city"]


def _data_root(store: Store):
    from pathlib import Path
    return Path(store.path).parent
