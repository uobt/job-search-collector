"""Контроль качества: детекция заблокированных/пустых страниц, полнота."""

from __future__ import annotations

import re

BLOCKED_MARKERS = [
    "enable javascript", "just a moment", "checking your browser",
    "attention required", "verify you are a human", "captcha",
    "sign in to continue", "authwall", "access denied", "forbidden",
    "cf-chl", "challenge-platform", "let's confirm it's really you",
]


def looks_blocked(html: str) -> bool:
    """HTTP 200, но страница — challenge/логин, а не выдача."""
    if not html:
        return False
    head = html[:20000].lower()
    return any(marker in head for marker in BLOCKED_MARKERS)


def has_job_markup(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in (
        "jobposting", "data-jk", "base-search-card", "job_seen_beacon"))


def classify_search_page(html: str, cards_found: int) -> tuple[str, str | None]:
    """(status, stop_reason) для страницы поиска."""
    if looks_blocked(html):
        return "blocked", "blocked"
    if cards_found == 0:
        if has_job_markup(html):
            return "success", "no_results"
        return "failed", "no_results_no_markup"
    return "success", None


def completeness_flags(record) -> dict:
    """Честные флаги полноты для экспорта/отчёта."""
    precise_date = (bool(record.published_at)
                    and record.published_precision not in (None, "range"))
    return {
        "has_publish_date": precise_date,
        "date_is_range": record.published_precision == "range",
        "has_description": record.description_completeness == "full",
        "description_truncated": record.description_completeness == "truncated",
        "has_salary": bool(record.salary_min or record.salary_max),
        "salary_is_estimate": record.salary_origin == "estimate",
        "has_company_website": bool(record.company_website),
    }
