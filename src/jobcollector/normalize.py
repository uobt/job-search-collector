"""Нормализация: относительные/точные даты, зарплаты, локации, сеньорити.

Правила ТЗ: нераспознанная дата → (None, None), «30+ days ago» — диапазон,
first_seen никогда не подменяет дату публикации.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from .models import JobCard, JobRecord, PARSER_VERSION, utcnow

_WS = re.compile(r"\s+")

RELATIVE_RX = re.compile(
    r"(?:posted\s+|updated\s+|listed\s+)?(\d+)\+?\s*(second|minute|hour|day|week|month)s?\s+ago",
    re.IGNORECASE)
JUST_NOW_RX = re.compile(r"(just posted|today|moments ago|few seconds ago)",
                         re.IGNORECASE)

UNIT_DAYS = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24,
             "day": 1, "week": 7, "month": 30}

COUNTRY_HINTS = {
    "united kingdom": "gb", "uk": "gb", "england": "gb", "london": "gb",
    "scotland": "gb", "wales": "gb", "manchester": "gb",
    "united states": "us", "usa": "us", "new york": "us", "san francisco": "us",
    "germany": "de", "berlin": "de", "munich": "de", "deutschland": "de",
    "france": "fr", "paris": "fr", "netherlands": "nl", "amsterdam": "nl",
    "spain": "es", "madrid": "es", "italy": "it", "milan": "it",
    "canada": "ca", "toronto": "ca", "australia": "au", "sydney": "au",
    "ireland": "ie", "dublin": "ie",
}

SENIORITY_RULES = [
    ("c_level", re.compile(r"\b(chief|c[teofmr]o|vp|vice president|head of|president)\b", re.I)),
    ("director", re.compile(r"\bdirector\b", re.I)),
    ("manager", re.compile(r"\b(manager|lead)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|staff|principal)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|intern|graduate|trainee)\b", re.I)),
]

# Штаты США и провинции Канады: «Austin, TX» — это US, «Toronto, ON» — CA,
# а не Тайвань/Онтарио-страна. Двухбуквенный хвост — чаще субдивизион.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY", "PR",
}
CA_PROVINCES = {"AB", "BC", "MB", "NB", "NS", "NT", "ON", "QC"}

SALARY_RX = re.compile(
    r"[£$€]?\s*(?P<min>\d[\d.,]*)\s*(?:–|—|-|to)\s*[£$€]?\s*(?P<max>\d[\d.,]*)"
    r"\s*(?:gbp|usd|eur)?\s*(?:/|per\s+|a\s+|an\s+)?\s*"
    r"(?P<per>year|yr|annum|month|mo|week|wk|hour|hr)s?\b",
    re.IGNORECASE)
SALARY_SYMBOL_RX = re.compile(r"[£$€]|gbp|usd|eur", re.IGNORECASE)
CURRENCY_MAP = {"£": "GBP", "gbp": "GBP", "$": "USD", "usd": "USD",
                "€": "EUR", "eur": "EUR"}
PERIOD_MAP = {"year": "year", "yr": "year", "annum": "year", "month": "month",
              "mo": "month", "week": "week", "wk": "week",
              "hour": "hour", "hr": "hour"}

REMOTE_RX = re.compile(r"\b(remote|work from home|anywhere)\b", re.I)
HYBRID_RX = re.compile(r"\bhybrid\b", re.I)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = _WS.sub(" ", value).strip()
    return text or None


def parse_posted(raw: str | None, reference: datetime | None = None
                 ) -> tuple[str | None, str | None, str]:
    """Исходная строка даты → (iso_or_none, precision, kind).

    kind: published (источник заявил дату публикации) | unknown.
    """
    if not raw:
        return None, None, "unknown"
    text = clean_text(raw) or ""
    ref = reference or datetime.now(timezone.utc)

    if JUST_NOW_RX.search(text):
        return (ref.replace(microsecond=0).isoformat(), "day", "published")

    match = RELATIVE_RX.search(text)
    if match:
        count = int(match.group(1))
        plus = "+" in match.group(0)
        unit = match.group(2).lower()
        days = count * UNIT_DAYS[unit]
        moment = ref - timedelta(days=days)
        if plus:
            # «30+ days ago»: нижняя граница, точной даты нет
            return (moment.replace(microsecond=0).isoformat(), "range", "published")
        return (moment.replace(microsecond=0).isoformat(), "relative", "published")

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%d %B %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (dt.isoformat(), "exact", "published")
        except ValueError:
            continue
    return None, None, "unknown"


def parse_salary(raw: str | None) -> dict:
    out = {"salary_min": None, "salary_max": None,
           "salary_currency": None, "salary_period": None}
    if not raw:
        return out
    text = clean_text(raw) or ""
    match = SALARY_RX.search(text)
    if not match:
        return out

    def num(text_value: str) -> int | None:
        digits = re.sub(r"[^\d]", "", text_value)
        return int(digits) if digits else None

    out["salary_min"] = num(match.group("min"))
    out["salary_max"] = num(match.group("max"))
    symbol = SALARY_SYMBOL_RX.search(text)
    if symbol:
        out["salary_currency"] = CURRENCY_MAP.get(symbol.group(0).lower())
    per = (match.group("per") or "").lower()
    out["salary_period"] = PERIOD_MAP.get(per)
    return out


def parse_location(raw: str | None) -> tuple[str | None, str | None]:
    """(country, city) из свободного текста; без выдумок."""
    if not raw:
        return None, None
    text = clean_text(raw) or ""
    lowered = text.lower()
    country = None
    for hint, code in COUNTRY_HINTS.items():
        if hint in lowered:
            country = code
            break
    parts = [p.strip() for p in text.split(",") if p.strip()]
    city = parts[0] if parts else None
    if country is None and len(parts) >= 2:
        tail = parts[-1].strip()
        if tail.upper() in US_STATES:
            country = "us"
        elif tail.upper() in CA_PROVINCES:
            country = "ca"
        else:
            country = COUNTRY_HINTS.get(tail.lower())
    return country, city


def parse_seniority(title: str | None) -> str | None:
    if not title:
        return None
    for level, rx in SENIORITY_RULES:
        if rx.search(title):
            return level
    return None


def parse_workplace(location_raw: str | None, explicit: str | None = None) -> str | None:
    if explicit:
        lowered = explicit.lower()
        if "remote" in lowered:
            return "remote"
        if "hybrid" in lowered:
            return "hybrid"
        if "on" in lowered and "site" in lowered:
            return "onsite"
    if location_raw and REMOTE_RX.search(location_raw):
        return "remote"
    if location_raw and HYBRID_RX.search(location_raw):
        return "hybrid"
    return None


def normalize_card(card: JobCard, acquisition: str = "live_search",
                   raw_ref: str | None = None,
                   reference: datetime | None = None) -> JobRecord:
    """JobCard → JobRecord. Пустое лучше выдумки."""
    country, city = parse_location(card.location_raw)
    published_iso, precision, _kind = parse_posted(card.posted_raw, reference)
    salary = parse_salary(card.salary_raw)
    now = utcnow()
    completeness = "none"
    if card.description:
        completeness = "full"
    elif card.snippet:
        completeness = "truncated"
    record = JobRecord(
        source=card.source,
        source_job_id=card.source_job_id,
        source_url=card.url,
        title=clean_text(card.title),
        company_name=clean_text(card.company_name),
        company_url=card.company_url,
        company_website=card.company_website,
        location_raw=clean_text(card.location_raw),
        country=country, city=city,
        workplace_type=parse_workplace(card.location_raw),
        employment_type=clean_text(card.employment_type),
        seniority=parse_seniority(card.title),
        apply_url=card.apply_url,
        description=clean_text(card.description) or clean_text(card.snippet),
        description_completeness=completeness,
        posted_raw=clean_text(card.posted_raw),
        published_at=published_iso,
        published_precision=precision,
        first_seen_at=now, last_seen_at=now,
        acquisition_method=acquisition,
        raw_ref=raw_ref,
        parser_version=PARSER_VERSION,
        **salary,
    )
    record.content_hash = content_hash(record)
    return record


def content_hash(record: JobRecord) -> str:
    # Относительные/Range даты («3 days ago») дрейфуют между прогонами и не
    # должны порождать ложные события «обновления»: в хеш идёт только точная дата.
    stable_published = (record.published_at
                        if record.published_precision in ("exact", "day")
                        else None)
    basis = "|".join(str(x) for x in (
        record.title, record.company_name, record.location_raw,
        record.description, record.salary_min, record.salary_max,
        stable_published))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
