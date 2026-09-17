"""CLI: doctor / collect / import / status / export."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_spec
from .models import JobCard
from .normalize import normalize_card
from .scheduler import link_cross_source_duplicates, plan, run_source
from .sources.indeed import IndeedConnector
from .sources.linkedin import LinkedInConnector
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "collector.db"

CONNECTORS = {
    "linkedin": LinkedInConnector,
    "indeed": IndeedConnector,
}

SOURCE_LIVE_STATUS = {
    "linkedin": ("BLOCKED", "policy: robots Disallow: / + User Agreement"),
    "indeed": ("BLOCKED", "technical: HTTP 403 при разрешающем robots; /job/ закрыт"),
}


def _store(path: Path | None) -> Store:
    return Store(Path(path) if path else DEFAULT_DB)


def cmd_doctor(args) -> int:
    print(f"job-search-collector {__version__}")
    print(f"python: {sys.version.split()[0]}")
    if args.config:
        spec = load_spec(Path(args.config))
        errors = spec.validate()
        tasks = plan(spec)
        print(f"config: {args.config} — {'OK' if not errors else 'ОШИБКИ: ' + '; '.join(errors)}")
        print(f"план: {len(tasks)} страниц поиска "
              f"({len(spec.sources)} источн. × {len(spec.queries)} запросов "
              f"× {len(spec.locations)} локаций × ≤{spec.max_pages_per_search} стр.)")
    for code, (status, reason) in SOURCE_LIVE_STATUS.items():
        print(f"{code}: live={status} ({reason})")
    try:
        import yaml  # noqa: F401
        print("pyyaml: доступен (yaml-конфиги поддерживаются)")
    except ImportError:
        print("pyyaml: нет (yaml-конфиг требует установки; json работает)")
    print(f"база: {DEFAULT_DB}")
    return 0


def cmd_collect(args) -> int:
    spec = load_spec(Path(args.config))
    errors = spec.validate()
    if errors:
        print("Ошибки конфигурации:", "; ".join(errors))
        return 2
    if args.dry_run:
        tasks = plan(spec)
        print(f"DRY-RUN: {len(tasks)} страниц, сетевых запросов не будет")
        for task in tasks[:10]:
            print(f"  {task['source']:9s} {task['query'][:40]:42s} "
                  f"{task['location']:16s} стр.{task['page']}")
        if len(tasks) > 10:
            print(f"  … и ещё {len(tasks) - 10}")
        return 0

    store = _store(args.db)
    any_live = False
    try:
        for code in spec.sources:
            run_id = store.start_run("collect", json.dumps({
                "config": str(args.config), "source": code,
                "queries": spec.queries}, ensure_ascii=False), code)
            connector = CONNECTORS[code]()
            report = run_source(spec, code, connector, store, run_id)
            print(f"{code}: status={report.status} stop={report.stop_reason} "
                  f"requests={report.requests} cards={report.cards} "
                  f"new={report.new_jobs} upd={report.updated_jobs} "
                  f"unchanged={report.unchanged}")
            if report.note:
                print(f"  причина: {report.note}")
            if report.status not in ("blocked", "failed"):
                any_live = True
        linked = link_cross_source_duplicates(store)
        print(f"межплощадочных связей: {linked}")
    finally:
        store.close()
    return 0 if any_live else 2


def cmd_import(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"файл не найден: {path}")
        return 2
    rows: list[dict] = []
    if path.suffix.lower() == ".json":
        rows = _read_json(path)
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        print("поддерживаются .csv и .json")
        return 2

    store = _store(args.db)
    run_id = store.start_run("import", json.dumps(
        {"file": str(path), "source": args.source}, ensure_ascii=False), args.source)
    new = updated = unchanged = skipped_foreign = 0
    try:
        for row in rows:
            # один файл может содержать несколько площадок; import
            # вызывается на одну площадку — строки чужого source пропускаем
            if (row.get("source") or args.source) != args.source:
                skipped_foreign += 1
                continue
            card = _card_from_row(args.source, row)
            if not card.source_job_id or not card.title:
                continue
            record = normalize_card(card, acquisition="import")
            event = store.upsert_job(record)
            if event == "first_seen":
                new += 1
            elif event == "updated":
                updated += 1
            else:
                unchanged += 1
        linked = link_cross_source_duplicates(store)
        store.finish_run(run_id, "completed", stop_reason=None,
                         cards=len(rows), new_jobs=new, updated_jobs=updated)
        print(f"импорт {args.source}: строк={len(rows)} new={new} "
              f"upd={updated} unchanged={unchanged} "
              f"чужой-source={skipped_foreign} связей={linked}")
    finally:
        store.close()
    return 0


def _read_json(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        # пробуем JSONL
        return [json.loads(line) for line in text.splitlines()
                if line.strip()]


def _card_from_row(source: str, row: dict) -> JobCard:
    get = lambda *keys: next((row[k] for k in keys if row.get(k)), None)
    return JobCard(
        source=source,
        source_job_id=str(get("source_job_id", "job_id", "id") or ""),
        title=get("title", "job_title") or "",
        company_name=get("company_name", "company"),
        company_url=get("company_url"),
        company_website=get("company_website"),
        location_raw=get("location_raw", "location"),
        posted_raw=get("posted_raw", "posted", "published_at"),
        salary_raw=get("salary_raw", "salary"),
        snippet=get("snippet"),
        url=get("source_url", "url"),
        apply_url=get("apply_url"),
        description=get("description"),
        employment_type=get("employment_type"))


def cmd_status(args) -> int:
    store = _store(args.db)
    try:
        info = store.summary()
        print(f"вакансий: {info['jobs_total']}  по источникам: {info['jobs_by_source']}")
        print(f"наблюдений: {info['observations']}  связей-дублей: {info['duplicate_links']}")
        for run in info["last_runs"]:
            print(f"  run#{run['id']} {run['kind']:8s} {run['source'] or '-':9s} "
                  f"{run['status']:10s} stop={run['stop_reason']} "
                  f"new={run['new_jobs']} upd={run['updated_jobs']}")
    finally:
        store.close()
    return 0


def cmd_export(args) -> int:
    store = _store(args.db)
    try:
        rows = store.jobs(availability=None)
        out = Path(args.out)
        if args.format == "jsonl":
            written = __import__("jobcollector.export", fromlist=["x"]).export_jsonl(rows, out)
        else:
            written = __import__("jobcollector.export", fromlist=["x"]).export_csv(rows, out)
        print(f"экспортировано {written} строк → {out}")
    finally:
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="jobcollector")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor")
    p.add_argument("--config")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("collect")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("import")
    p.add_argument("--source", required=True, choices=list(CONNECTORS))
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("export")
    p.add_argument("--format", default="csv", choices=["csv", "jsonl"])
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
