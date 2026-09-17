"""Indeed: коннектор + чистый парсер поисковой выдачи.

Live-статус: BLOCKED (technical) — robots.txt разрешает `/jobs?q=...&start=N`
(шаг 10, потолок start=90), но www/uk-домены отдают HTTP 403 браузерному UA.
Детальные страницы `/job/`, `/rc/` запрещены robots и не запрашиваются:
описание берём из JSON-LD выдачи, иначе snippet с completeness=truncated.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse

from ..models import JobCard, SearchPage, SearchSpec
from .base import Connector, SourceBlocked

INDEED_POLICY = ("живой доступ: HTTP 403 на www/uk при разрешающем robots; "
                 "детальные страницы запрещены robots (/job/, /rc/)")

ROBOTS_MAX_START = 90   # Allow: /*&start=90& — потолок пагинации для User-agent: *


def _strip(text: str) -> str | None:
    clean = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or None


# Разметка карточек Indeed (serp, data-testid-маркеры)
JK_RX = re.compile(r'data-jk="([a-f0-9]+)"', re.IGNORECASE)
CARD_SPLIT_RX = re.compile(r'class="[^"]*(?:cardOutline|job_seen_beacon|slider_container)[^"]*"')
TITLE_RX = re.compile(
    r'<h2[^>]*class="[^"]*jobTitle[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL)
COMPANY_RX = re.compile(r'data-testid="company-name"[^>]*>(.*?)<', re.IGNORECASE)
LOCATION_RX = re.compile(r'data-testid="text-location"[^>]*>(.*?)<', re.IGNORECASE)
SNIPPET_RX = re.compile(r'data-testid="belowJobSnippet"[^>]*>(.*?)</div>',
                        re.IGNORECASE | re.DOTALL)
SALARY_RX = re.compile(
    r'class="[^"]*metadata[^"]*salary[^"]*"[^>]*>(.*?)<', re.IGNORECASE)
DATE_RX = re.compile(r'data-testid="myTimeStamp"[^>]*>.*?<span[^>]*>(.*?)</span>',
                     re.IGNORECASE | re.DOTALL)
DATE_ATTR_RX = re.compile(r'date-time="([^"]+)"', re.IGNORECASE)


class IndeedConnector(Connector):
    code, label = "indeed", "Indeed"
    live_allowed = False          # 403: transport отдаст blocked, live отключён
    policy_reason = INDEED_POLICY
    page_step = 10
    domain = "www.indeed.com"

    def build_search_url(self, spec: SearchSpec, query: str, location,
                         cursor: str | None) -> str:
        start = int(cursor or 0)
        params = {"q": query, "l": location.city or location.country, "start": str(start)}
        if spec.posted_within_days:
            params["fromage"] = str(spec.posted_within_days)
        return f"https://{self.domain}/jobs?" + urllib.parse.urlencode(params)

    def search(self, spec: SearchSpec, query: str, location, cursor: str | None):
        """Live-попытка не выполняется: оба домена отдали 403 в пилоте.
        Оставлено для будущего канала; транспорт вернул бы blocked."""
        raise SourceBlocked(self.code, self.policy_reason)

    def parse_search(self, html: str) -> SearchPage:
        """Чистый парсер: JSON-LD → карточки; затем разметка data-jk."""
        page = SearchPage()
        cards: dict[str, JobCard] = {}

        for block in _jsonld_blocks(html):
            try:
                data = json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue
            graph = data.get("@graph") if isinstance(data, dict) else None
            items = graph if isinstance(graph, list) else (
                data if isinstance(data, list) else [data])
            for item in items:
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                url = item.get("url") or ""
                jk = _jk_from_url(url) or str(item.get("identifier") or "")
                if not jk:
                    continue
                org = item.get("hiringOrganization") or {}
                cards[jk] = JobCard(
                    source=self.code, source_job_id=jk,
                    title=_strip(str(item.get("title") or "")) or "",
                    company_name=(org.get("name") if isinstance(org, dict) else None),
                    company_url=(org.get("sameAs") if isinstance(org, dict) else None),
                    location_raw=_location_from_jsonld(item.get("jobLocation")),
                    posted_raw=item.get("datePosted"),
                    salary_raw=_salary_from_jsonld(
                        item.get("baseSalary") or item.get("estimatedSalary")),
                    snippet=None, url=url,
                    description=item.get("description"),
                    employment_type=item.get("employmentType"),
                    via_jsonld=True)

        if not cards:
            for chunk in _split_cards(html):
                jk_m = JK_RX.search(chunk)
                if not jk_m:
                    continue
                jk = jk_m.group(1)
                if jk in cards:
                    continue
                title_m = TITLE_RX.search(chunk)
                company_m = COMPANY_RX.search(chunk)
                loc_m = LOCATION_RX.search(chunk)
                snippet_m = SNIPPET_RX.search(chunk)
                salary_m = SALARY_RX.search(chunk)
                date_m = DATE_RX.search(chunk)
                date_attr = DATE_ATTR_RX.search(chunk)
                link = None
                link_m = re.search(r'href="(/viewjob\?jk=[^"]+|/rc/clk\?[^"]+)"',
                                   chunk, re.IGNORECASE)
                if link_m:
                    link = "https://" + self.domain + html_lib.unescape(link_m.group(1))
                cards[jk] = JobCard(
                    source=self.code, source_job_id=jk,
                    title=_strip(title_m.group(1)) if title_m else "",
                    company_name=_strip(company_m.group(1)) if company_m else None,
                    location_raw=_strip(loc_m.group(1)) if loc_m else None,
                    posted_raw=(_strip(date_m.group(1)) if date_m
                                else (date_attr.group(1) if date_attr else None)),
                    salary_raw=_strip(salary_m.group(1)) if salary_m else None,
                    snippet=_strip(snippet_m.group(1)) if snippet_m else None,
                    url=link or f"https://{self.domain}/viewjob?jk={jk}",
                    apply_url=None)

        page.cards = list(cards.values())
        start_next = _next_start(html, cards and len(page.cards) or 0)
        page.next_cursor = start_next
        return page

    def parse_detail(self, html: str):
        return None  # /job/ и /viewjob запрещены robots; карточек из выдачи достаточно


def _jk_from_url(url: str) -> str | None:
    match = re.search(r"[?&]jk=([a-f0-9]+)", url, re.IGNORECASE)
    return match.group(1) if match else None


def _split_cards(html: str) -> list[str]:
    chunks = CARD_SPLIT_RX.split(html)
    return chunks[1:] if len(chunks) > 1 else ([html] if JK_RX.search(html) else [])


def _jsonld_blocks(html: str):
    for match in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.IGNORECASE | re.DOTALL):
        yield match.group(1).strip()


def _location_from_jsonld(job_location) -> str | None:
    if not job_location:
        return None
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else None
    address = (job_location or {}).get("address") or {}
    parts = [address.get(key) for key in
             ("addressLocality", "addressRegion", "addressCountry")]
    return ", ".join(str(p) for p in parts if p) or None


def _salary_from_jsonld(base) -> str | None:
    if not isinstance(base, dict):
        return None
    value = base.get("value") or {}
    cur = (base.get("currency") or "")
    minimum, maximum = value.get("minValue"), value.get("maxValue")
    unit = (value.get("unitText") or "").lower()
    period = {"year": "a year", "month": "a month", "week": "a week",
              "day": "a day", "hour": "an hour"}.get(unit, "")
    if minimum and maximum:
        return f"{cur}{minimum}-{cur}{maximum} {period}".strip()
    return None


def _next_start(html: str, cards_found: int) -> str | None:
    """Курсор следующей страницы: приоритет — ссылка Next, иначе current+10.
    Потолок start=90 — по robots (Allow: /*&start=90&)."""
    next_link = re.search(
        r'<a[^>]*href="[^"]*?start=(\d+)[^"]*"[^>]*>\s*(?:Next|›|»)', html,
        re.IGNORECASE)
    if next_link:
        nxt = int(next_link.group(1))
        return str(nxt) if nxt <= ROBOTS_MAX_START else None
    if not cards_found:
        return None
    match = re.search(r'start=(\d+)', html)
    current = int(match.group(1)) if match else 0
    nxt = current + 10
    return str(nxt) if nxt <= ROBOTS_MAX_START else None
