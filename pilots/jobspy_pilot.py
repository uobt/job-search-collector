"""Пилот JobSpy: LinkedIn + Indeed → наш импорт-формат.

Использование:
  python pilots/jobspy_pilot.py [query] [results_per_site] [location] [days_back]

По умолчанию: "Sales Development Representative", 10, "London, UK", 14.
Выход: data/pilot/jobspy_pilot.csv (замещается каждым запуском; для отдельных
прогонов передавайте --out или переименуйте файл после сбора).

Правовой статус канала: JobSpy обращается к площадкам как гость; для LinkedIn
это противоречит robots/ToS, для Indeed — зона 403. Пилоты выполняются по
явному решению владельца проекта; без прокси и без обхода CAPTCHA.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

from jobspy import scrape_jobs

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "pilot"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def job_id_from_url(source: str, url: str) -> str:
    if source == "linkedin":
        match = re.search(r"/jobs/view/(\d+)", url or "")
        if match:
            return match.group(1)
    else:
        match = re.search(r"(?:jk|currentJobId)=([a-f0-9]+)", url or "", re.I)
        if match:
            return match.group(1)
    return "urlhash-" + hashlib.sha1((url or "").encode()).hexdigest()[:12]


def fetch(source: str, query: str, location: str, results: int,
          hours: int) -> list[dict]:
    kwargs = dict(
        site_name=[source],
        search_term=query,
        location=location,
        results_wanted=results,
        hours_old=hours,
    )
    if source == "linkedin":
        kwargs["linkedin_fetch_description"] = True
    else:
        kwargs["country_indeed"] = "UK"
    try:
        frame = scrape_jobs(**kwargs)
        rows = frame.to_dict("records") if frame is not None else []
        print(f"{source}: получено строк: {len(rows)}")
        return rows
    except Exception as exc:                      # noqa: BLE001 — пилот фиксирует всё
        print(f"{source}: ОШИБКА {type(exc).__name__}: {exc}")
        return []


def _clean(value) -> str | None:
    """pandas NaN/None → None (NaN is truthy и без проверки утекает как 'nan')."""
    if value is None:
        return None
    text = str(value)
    return None if text.strip().lower() in ("nan", "none", "") else text


def map_row(source: str, row: dict) -> dict:
    url = row.get("job_url") or ""
    return {
        "source": source,
        "source_job_id": job_id_from_url(source, url),
        "source_url": url,
        "title": _clean(row.get("title")),
        "company_name": _clean(row.get("company")),
        "company_url": _clean(row.get("company_url")),
        "location_raw": _clean(row.get("location")),
        "posted_raw": _clean(row.get("date_posted")),
        "salary_raw": None,
        "snippet": None,
        "apply_url": _clean(row.get("job_url_direct")) or url,
        "description": _clean(row.get("description")),
    }


def field_stats(rows: list[dict]) -> str:
    if not rows:
        return "нет строк"
    keys = ["title", "company_name", "location_raw", "posted_raw",
            "description", "source_url"]
    parts = []
    for key in keys:
        filled = sum(1 for r in rows if r.get(key))
        parts.append(f"{key}={filled}/{len(rows)}")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="Sales Development Representative")
    parser.add_argument("results", nargs="?", type=int, default=10)
    parser.add_argument("location", nargs="?", default="London, UK")
    parser.add_argument("days_back", nargs="?", type=int, default=14)
    parser.add_argument("--out", default=None, help="имя выходного CSV в data/pilot/")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mapped: list[dict] = []
    for source in ("linkedin", "indeed"):
        mapped.extend(map_row(source, row) for row in fetch(
            source, args.query, args.location, args.results,
            args.days_back * 24))

    if not mapped:
        print("Пилот не дал строк: оба источника пусты/заблокированы.")
        return 2

    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for row in mapped:
        key = (row["source"], row["source_job_id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    stem = args.out or "jobspy_pilot"
    out_csv = OUT_DIR / f"{stem}.csv"
    columns = ["source", "source_job_id", "source_url", "title", "company_name",
               "company_url", "location_raw", "posted_raw", "salary_raw",
               "snippet", "apply_url", "description"]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(unique)

    print(f"\nquery={args.query!r} location={args.location!r} "
          f"days_back={args.days_back}")
    print(f"уникальных строк: {len(unique)} → {out_csv}")
    for source in ("linkedin", "indeed"):
        subset = [r for r in unique if r["source"] == source]
        print(f"{source}: {len(subset)} | {field_stats(subset)}")

    print("\nпервые карточки:")
    for row in unique[:6]:
        print(f"  [{row['source']}] {row['title']} | {row['company_name']} | "
              f"{row['location_raw']} | {row['posted_raw']} | {row['source_url'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
