"""Контракты данных: задание поиска, карточка выдачи, нормализованная вакансия."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceStatus(str, Enum):
    LIVE_VERIFIED = "LIVE_VERIFIED"
    IMPORT_ONLY = "IMPORT_ONLY"
    FIXTURE_ONLY = "FIXTURE_ONLY"
    BLOCKED = "BLOCKED"


class Availability(str, Enum):
    OBSERVED_OPEN = "observed_open"
    EXPLICITLY_CLOSED = "explicitly_closed"
    UNKNOWN = "unknown"


class DatePrecision(str, Enum):
    EXACT = "exact"        # полная дата-время или дата
    DAY = "day"            # дата без времени
    RELATIVE = "relative"  # «Posted N days ago» → день-точность по опорному времени
    RANGE = "range"        # «30+ days ago» — нижняя граница, точность нет
    NONE = "none"


class StopReason(str, Enum):
    COMPLETED = "completed"
    NO_RESULTS = "no_results"
    EXHAUSTED = "exhausted"          # источник сообщил конец выдачи
    CAPPED_RESULTS = "capped_results"
    CAPPED_PAGES = "capped_pages"
    CAPPED_ROBOTS = "capped_robots"  # потолок пагинации по robots (Indeed start<=90)
    REPEATED_PAGE = "repeated_page"  # тот же cursor/контент второй раз
    BLOCKED = "blocked"
    FAILED = "failed"
    POLICY = "policy"                # прямой сбор запрещён политикой проекта


@dataclass
class LocationSpec:
    country: str
    city: str | None = None
    radius_km: int | None = None


@dataclass
class TransportConfig:
    request_delay_seconds: float = 2.0
    timeout_seconds: float = 30.0
    max_retries: int = 2
    indeed_domain: str = "www.indeed.com"


@dataclass
class SearchSpec:
    sources: list[str]
    queries: list[str]
    locations: list[LocationSpec]
    posted_within_days: int | None = 14
    exclude_titles: list[str] = field(default_factory=list)
    max_results_per_search: int = 100
    max_pages_per_search: int = 3
    max_detail_requests_per_run: int = 20
    fetch_descriptions: bool = True
    transport: TransportConfig = field(default_factory=TransportConfig)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.sources:
            errors.append("sources пуст")
        unknown = [s for s in self.sources if s not in ("linkedin", "indeed")]
        if unknown:
            errors.append(f"неизвестные источники: {unknown}")
        if not self.queries:
            errors.append("queries пуст")
        if not self.locations:
            errors.append("locations пуст")
        if self.max_results_per_search < 1:
            errors.append("max_results_per_search < 1")
        if self.max_pages_per_search < 1:
            errors.append("max_pages_per_search < 1")
        return errors


@dataclass
class RawDocument:
    """Сохранённый ответ до любого разбора."""

    request_id: str
    url: str                    # без секретов
    fetched_at: str             # UTC ISO
    status: int | None
    mime: str | None
    content: str
    transport: str = "http"


@dataclass
class JobCard:
    """Карточка из поисковой выдачи (до нормализации)."""

    source: str
    source_job_id: str
    title: str
    company_name: str | None = None
    company_url: str | None = None
    company_website: str | None = None
    location_raw: str | None = None
    posted_raw: str | None = None      # исходная строка даты
    salary_raw: str | None = None
    snippet: str | None = None
    url: str | None = None
    apply_url: str | None = None
    description: str | None = None     # если источник дал полный текст в выдаче
    employment_type: str | None = None
    via_jsonld: bool = False

    def key(self) -> tuple[str, str]:
        return (self.source, self.source_job_id)


@dataclass
class SearchPage:
    cards: list[JobCard] = field(default_factory=list)
    next_cursor: str | None = None
    reported_total: int | None = None
    status: str = "success"             # success | partial | blocked | failed
    exhausted: bool | None = None
    applied_filters: dict[str, Any] = field(default_factory=dict)
    unsupported_filters: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    raw_ref: str | None = None
    note: str | None = None


@dataclass
class JobRecord:
    """Нормализованная вакансия — текущее состояние в БД."""

    source: str
    source_job_id: str
    source_url: str | None = None
    title: str | None = None
    company_name: str | None = None
    company_source_id: str | None = None
    company_url: str | None = None
    company_website: str | None = None
    location_raw: str | None = None
    country: str | None = None
    city: str | None = None
    workplace_type: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_origin: str | None = None       # source | estimate
    apply_url: str | None = None
    description: str | None = None
    description_completeness: str | None = None   # full | truncated | none
    posted_raw: str | None = None
    published_at: str | None = None        # UTC ISO
    published_precision: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    last_detail_checked_at: str | None = None
    availability: str = Availability.OBSERVED_OPEN.value
    acquisition_method: str | None = None  # live_search | import | provider
    content_hash: str | None = None
    raw_ref: str | None = None
    parser_version: str | None = None

    def key(self) -> tuple[str, str]:
        return (self.source, self.source_job_id)

    def as_row(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


PARSER_VERSION = "0.1.0"
