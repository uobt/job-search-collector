"""SQLite-хранилище: прогоны, попадания, вакансии, история, задачи, попытки.

Правила ТЗ, зашитые в схему и методы:
- upsert идемпотентен по (source, source_job_id);
- пропажа из выдачи НЕ закрывает вакансию (availability не трогаем);
- изменения фиксируются только при смене content_hash;
- межплощадочные кандидаты-дубли — отдельная таблица, без слияния.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import JobRecord, utcnow

SCHEMA = """
create table if not exists search_runs (
    id              integer primary key autoincrement,
    started_at      text not null,
    finished_at     text,
    kind            text not null default 'collect',   -- collect | import
    spec            text,
    source          text,
    status          text not null default 'running',
    stop_reason     text,
    requests        integer default 0,
    cards           integer default 0,
    new_jobs        integer default 0,
    updated_jobs    integer default 0,
    note            text
);
create table if not exists search_hits (
    run_id          integer not null,
    source          text not null,
    source_job_id   text not null,
    query           text,
    location        text,
    page            integer,
    rank            integer,
    seen_at         text not null,
    primary key (run_id, source, source_job_id, query, location, page, rank)
);
create table if not exists jobs (
    source              text not null,
    source_job_id       text not null,
    source_url          text,
    title               text,
    company_name        text,
    company_source_id   text,
    company_url         text,
    company_website     text,
    location_raw        text,
    country             text,
    city                text,
    workplace_type      text,
    employment_type     text,
    seniority           text,
    salary_min          integer,
    salary_max          integer,
    salary_currency     text,
    salary_period       text,
    salary_origin       text,
    apply_url           text,
    description         text,
    description_completeness text,
    posted_raw          text,
    published_at        text,
    published_precision text,
    first_seen_at       text not null,
    last_seen_at        text not null,
    last_detail_checked_at text,
    availability        text not null default 'observed_open',
    acquisition_method  text,
    content_hash        text,
    raw_ref             text,
    parser_version      text,
    primary key (source, source_job_id)
);
create index if not exists jobs_company_idx on jobs(company_name);
create index if not exists jobs_published_idx on jobs(published_at);
create table if not exists job_observations (
    id              integer primary key autoincrement,
    source          text not null,
    source_job_id   text not null,
    observed_at     text not null,
    event           text not null,     -- first_seen | updated | unchanged
    content_hash    text,
    changed_fields  text,
    raw_ref         text
);
create index if not exists job_obs_job_idx on job_observations(source, source_job_id);
create table if not exists tasks (
    id              integer primary key autoincrement,
    source          text not null,
    kind            text not null,     -- search_page | detail
    payload         text not null,     -- json: query/location/page или job ref
    status          text not null default 'pending',  -- pending|running|done|blocked|failed
    attempts        integer default 0,
    lease_expires   text,
    last_error      text,
    created_at      text not null,
    updated_at      text not null
);
create table if not exists request_attempts (
    id              integer primary key autoincrement,
    run_id          integer,
    source          text,
    url             text,
    status          integer,
    transport       text,
    duration_ms     integer,
    error           text,
    at              text not null
);
create table if not exists duplicate_links (
    source_a        text not null,
    job_id_a        text not null,
    source_b        text not null,
    job_id_b        text not null,
    basis           text not null,     -- strong:* | weak:*
    created_at      text not null,
    primary key (source_a, job_id_a, source_b, job_id_b)
);
"""

JOB_FIELDS = [
    "source", "source_job_id", "source_url", "title", "company_name",
    "company_source_id", "company_url", "company_website", "location_raw",
    "country", "city", "workplace_type", "employment_type", "seniority",
    "salary_min", "salary_max", "salary_currency", "salary_period",
    "salary_origin", "apply_url", "description", "description_completeness",
    "posted_raw", "published_at", "published_precision", "first_seen_at",
    "last_seen_at", "last_detail_checked_at", "availability",
    "acquisition_method", "content_hash", "raw_ref", "parser_version",
]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=WAL")
        self.conn.execute("pragma busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- прогоны -------------------------------------------------------------

    def start_run(self, kind: str, spec: str | None, source: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "insert into search_runs (started_at, kind, spec, source) "
                "values (?,?,?,?)", (utcnow(), kind, spec, source))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stop_reason: str | None = None,
                   **counters: int) -> None:
        sets = ", ".join(f"{k}=?" for k in counters)
        params: list[Any] = list(counters.values())
        sql = (f"update search_runs set finished_at=?, status=?, stop_reason=?"
               f"{', ' + sets if sets else ''} where id=?")
        with self.conn:
            self.conn.execute(sql, [utcnow(), status, stop_reason, *params, run_id])

    def note_run(self, run_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(f"update search_runs set {sets} where id=?",
                              [*fields.values(), run_id])

    # --- вакансии ------------------------------------------------------------

    def upsert_job(self, record: JobRecord) -> str:
        """Идемпотентный upsert. Возвращает 'first_seen' | 'updated' | 'unchanged'."""
        fields = record.as_row()
        with closing(self.conn.execute(
                "select content_hash from jobs where source=? and source_job_id=?",
                (record.source, record.source_job_id))) as cur:
            row = cur.fetchone()
        now = utcnow()
        if row is None:
            columns = ", ".join(fields)
            placeholders = ", ".join("?" for _ in fields)
            with self.conn:
                self.conn.execute(
                    f"insert into jobs ({columns}) values ({placeholders})",
                    list(fields.values()))
                self.conn.execute(
                    "insert into job_observations (source, source_job_id, "
                    "observed_at, event, content_hash, raw_ref) values (?,?,?,?,?,?)",
                    (record.source, record.source_job_id, now, "first_seen",
                     record.content_hash, record.raw_ref))
            return "first_seen"

        if row["content_hash"] != record.content_hash:
            update_fields = {k: v for k, v in fields.items()
                             if k not in ("source", "source_job_id", "first_seen_at")}
            update_fields["last_seen_at"] = now
            sets = ", ".join(f"{k}=?" for k in update_fields)
            with self.conn:
                self.conn.execute(
                    f"update jobs set {sets} where source=? and source_job_id=?",
                    [*update_fields.values(), record.source, record.source_job_id])
                self.conn.execute(
                    "insert into job_observations (source, source_job_id, "
                    "observed_at, event, content_hash, raw_ref) values (?,?,?,?,?,?)",
                    (record.source, record.source_job_id, now, "updated",
                     record.content_hash, record.raw_ref))
            return "updated"

        with self.conn:
            self.conn.execute(
                "update jobs set last_seen_at=? where source=? and source_job_id=?",
                (now, record.source, record.source_job_id))
        return "unchanged"

    def record_hit(self, run_id: int, record: JobRecord, query: str | None,
                   location: str | None, page: int, rank: int) -> None:
        with self.conn:
            self.conn.execute(
                "insert or ignore into search_hits (run_id, source, source_job_id, "
                "query, location, page, rank, seen_at) values (?,?,?,?,?,?,?,?)",
                (run_id, record.source, record.source_job_id, query, location,
                 page, rank, utcnow()))

    def link_duplicates(self, links: Iterable[tuple[str, str, str, str, str]]) -> int:
        count = 0
        with self.conn:
            for source_a, id_a, source_b, id_b, basis in links:
                if (source_a, id_a) == (source_b, id_b):
                    continue
                pair = sorted([(source_a, id_a), (source_b, id_b)])
                cur = self.conn.execute(
                    "insert or ignore into duplicate_links (source_a, job_id_a, "
                    "source_b, job_id_b, basis, created_at) values (?,?,?,?,?,?)",
                    (pair[0][0], pair[0][1], pair[1][0], pair[1][1], basis, utcnow()))
                count += max(cur.rowcount, 0)
        return count

    # --- задачи --------------------------------------------------------------

    def push_task(self, source: str, kind: str, payload: dict) -> None:
        import json
        with self.conn:
            self.conn.execute(
                "insert into tasks (source, kind, payload, created_at, updated_at) "
                "values (?,?,?,?,?)",
                (source, kind, json.dumps(payload, ensure_ascii=False),
                 utcnow(), utcnow()))

    def log_attempt(self, run_id: int | None, source: str | None, url: str,
                    status: int | None, transport: str, duration_ms: int,
                    error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "insert into request_attempts (run_id, source, url, status, "
                "transport, duration_ms, error, at) values (?,?,?,?,?,?,?,?)",
                (run_id, source, url, status, transport, duration_ms, error, utcnow()))

    # --- чтение --------------------------------------------------------------

    def jobs(self, sources: Sequence[str] | None = None,
             availability: str | None = "observed_open") -> list[sqlite3.Row]:
        where, params = [], []
        if sources:
            where.append(f"source in ({','.join('?' * len(sources))})")
            params.extend(sources)
        if availability:
            where.append("availability = ?")
            params.append(availability)
        clause = ("where " + " and ".join(where)) if where else ""
        with closing(self.conn.execute(
                f"select * from jobs {clause} order by first_seen_at desc",
                params)) as cur:
            return cur.fetchall()

    def summary(self) -> dict:
        def one(sql: str, *params) -> Any:
            with closing(self.conn.execute(sql, params)) as cur:
                return cur.fetchone()[0]
        by_source = {}
        with closing(self.conn.execute(
                "select source, count(*) n, sum(content_hash is not null) hashed "
                "from jobs group by source")) as cur:
            for row in cur.fetchall():
                by_source[row["source"]] = row["n"]
        return {
            "jobs_total": one("select count(*) from jobs"),
            "jobs_by_source": by_source,
            "observations": one("select count(*) from job_observations"),
            "duplicate_links": one("select count(*) from duplicate_links"),
            "runs": one("select count(*) from search_runs"),
            "last_runs": [dict(row) for row in self.conn.execute(
                "select * from search_runs order by id desc limit 5")],
        }
