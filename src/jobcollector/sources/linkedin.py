"""LinkedIn Jobs: коннектор + чистый парсер guest-выдачи.

Live-статус: BLOCKED (policy) — robots.txt `User-agent: * → Disallow: /`,
User Agreement запрещает автоматический доступ. Live-запросы не выполняются;
парсер работает на сохранённых/import-страницах.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse

from ..models import JobCard, SearchPage, SearchSpec
from .base import Connector, SourceBlocked

LINKEDIN_POLICY = ("robots.txt: User-agent: * → Disallow: /; "
                   "User Agreement запрещает автоматический доступ без разрешения")

# guest-разметка карточек LinkedIn (base-search-card): режем по data-entity-urn
URN_SPLIT = 'data-entity-urn="urn:li:jobPosting:'
TITLE_RX = re.compile(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>',
                      re.IGNORECASE | re.DOTALL)
SHOW_MORE_RX = re.compile(r"<span[^>]*>\s*Show more\s*</span>", re.IGNORECASE)
COMPANY_RX = re.compile(
    r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL)
COMPANY_NOLINK_RX = re.compile(
    r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*(?:<a[^>]*>)?(.*?)(?:</a>)?\s*</h4>',
    re.IGNORECASE | re.DOTALL)
LOCATION_RX = re.compile(
    r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL)
LINK_RX = re.compile(r'<a[^>]*href="(https://[^"]*\/jobs\/view\/[^"]+)"',
                     re.IGNORECASE)
TIME_RX = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>',
                     re.IGNORECASE | re.DOTALL)
TIME_NODT_RX = re.compile(r'<time[^>]*>(.*?)</time>', re.IGNORECASE | re.DOTALL)
SNIPPET_RX = re.compile(
    r'<p[^>]*class="[^"]*job-search-card__snippet[^"]*"[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL)
SALARY_RX = re.compile(
    r'<span[^>]*class="[^"]*job-search-card__salary-info[^"]*"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL)


def _strip(text: str) -> str | None:
    clean = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or None


class LinkedInConnector(Connector):
    code, label = "linkedin", "LinkedIn Jobs"
    live_allowed = False
    policy_reason = LINKEDIN_POLICY

    def build_search_url(self, spec: SearchSpec, query: str, location,
                         cursor: str | None) -> str:
        start = int(cursor or 0)
        params: dict[str, str] = {
            "keywords": query,
            "location": location.city or location.country,
        }
        if spec.posted_within_days:
            params["f_TPR"] = f"r{60 * 60 * 24 * spec.posted_within_days}"
        if start:
            params["start"] = str(start)
        return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)

    def search(self, spec: SearchSpec, query: str, location, cursor: str | None):
        raise SourceBlocked(self.code, self.policy_reason)

    def parse_search(self, html: str) -> SearchPage:
        """Чистый парсер guest-выдачи LinkedIn: JSON-LD приоритет, затем разметка."""
        page = SearchPage()
        cards: dict[str, JobCard] = {}

        for block in _jsonld_blocks(html):
            try:
                data = json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue
            for item in (data if isinstance(data, list) else [data]):
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                url = item.get("url") or ""
                job_id = str(item.get("identifier") or
                             (url.rstrip("/").split("/")[-1] if url else "") or "")
                if not job_id:
                    continue
                org = item.get("hiringOrganization") or {}
                cards[job_id] = JobCard(
                    source=self.code, source_job_id=job_id,
                    title=_strip(str(item.get("title") or "")) or "",
                    company_name=(org.get("name") if isinstance(org, dict) else None),
                    company_url=(org.get("sameAs") if isinstance(org, dict) else None),
                    location_raw=_location_from_jsonld(item.get("jobLocation")),
                    posted_raw=item.get("datePosted"),
                    salary_raw=None, snippet=None, url=url,
                    description=item.get("description"),
                    employment_type=item.get("employmentType"),
                    via_jsonld=True)

        pieces = html.split(URN_SPLIT)
        for piece in pieces[1:]:
            job_id, _, body = piece.partition('"')
            if not job_id.isdigit():
                continue
            if job_id in cards:
                continue
            title_m = TITLE_RX.search(body)
            company_m = COMPANY_RX.search(body)
            company_n = COMPANY_NOLINK_RX.search(body) if not company_m else None
            link_m = LINK_RX.search(body)
            time_m = TIME_RX.search(body)
            time_n = TIME_NODT_RX.search(body) if not time_m else None
            loc_m = LOCATION_RX.search(body)
            snippet_m = SNIPPET_RX.search(body)
            salary_m = SALARY_RX.search(body)
            raw_title = title_m.group(1) if title_m else ""
            raw_title = SHOW_MORE_RX.sub("", raw_title)
            cards[job_id] = JobCard(
                source=self.code, source_job_id=job_id,
                title=_strip(raw_title) or "",
                company_name=_strip(company_m.group(2)) if company_m
                else (_strip(company_n.group(1)) if company_n else None),
                company_url=html_lib.unescape(company_m.group(1)) if company_m else None,
                location_raw=_strip(loc_m.group(1)) if loc_m else None,
                posted_raw=(_strip(time_m.group(2)) if time_m
                            else (_strip(time_n.group(1)) if time_n else None)),
                salary_raw=_strip(salary_m.group(1)) if salary_m else None,
                snippet=_strip(snippet_m.group(1)) if snippet_m else None,
                url=html_lib.unescape(link_m.group(1)) if link_m else None)

        page.cards = list(cards.values())
        page.next_cursor = str(len(page.cards)) if page.cards else None
        return page


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
