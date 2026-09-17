"""Экспорт: CSV UTF-8 BOM с защитой от formula-injection, JSONL."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .quality import completeness_flags

EXPORT_COLUMNS = [
    "source", "source_job_id", "source_url", "title", "company_name",
    "company_url", "company_website", "location_raw", "country", "city",
    "workplace_type", "employment_type", "seniority",
    "salary_min", "salary_max", "salary_currency", "salary_period",
    "apply_url", "description", "description_completeness",
    "posted_raw", "published_at", "published_precision",
    "first_seen_at", "last_seen_at", "availability",
    "acquisition_method", "content_hash",
]

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _guard_cell(value: Any) -> Any:
    """Spreadsheet formula injection: =cmd|..., +REF, -2, @SUM."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def export_csv(rows: Iterable[dict | Any], out_path: Path,
               columns: Sequence[str] = EXPORT_COLUMNS,
               with_quality: bool = True) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    header = list(columns)
    if with_quality:
        header += ["flag_has_publish_date", "flag_date_is_range",
                   "flag_description_truncated", "flag_salary_is_estimate"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            record = row if isinstance(row, dict) else dict(row)
            line = [_guard_cell(record.get(col)) for col in columns]
            if with_quality:
                flags = completeness_flags(_FlagsShim(record))
                line += [flags["has_publish_date"], flags["date_is_range"],
                         flags["description_truncated"], flags["salary_is_estimate"]]
            writer.writerow(line)
            written += 1
    return written


def export_jsonl(rows: Iterable[dict | Any], out_path: Path) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            record = row if isinstance(row, dict) else dict(row)
            handle.write(json.dumps(record, ensure_ascii=False,
                                    default=str) + "\n")
            written += 1
    return written


class _FlagsShim:
    """completeness_flags работает с JobRecord; для sqlite3.Row даём shim."""

    def __init__(self, record: dict):
        self.published_at = record.get("published_at")
        self.published_precision = record.get("published_precision")
        self.description_completeness = record.get("description_completeness")
        self.salary_min = record.get("salary_min")
        self.salary_max = record.get("salary_max")
        self.salary_origin = record.get("salary_origin")
        self.company_website = record.get("company_website")
