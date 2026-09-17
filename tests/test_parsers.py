"""Тесты чистых парсеров LinkedIn/Indeed на fixtures + политика live."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobcollector.models import SearchSpec
from jobcollector.quality import classify_search_page
from jobcollector.sources.base import SourceBlocked
from jobcollector.sources.indeed import IndeedConnector
from jobcollector.sources.linkedin import LinkedInConnector

FIX = Path(__file__).parent / "fixtures"


class TestLinkedInParser(unittest.TestCase):
    def setUp(self):
        self.connector = LinkedInConnector()
        self.page = self.connector.parse_search(
            (FIX / "linkedin_search.html").read_text(encoding="utf-8"))

    def test_cards_and_ids(self):
        self.assertEqual(len(self.page.cards), 3)
        ids = {c.source_job_id for c in self.page.cards}
        self.assertEqual(ids, {"4001", "4002", "4003"})

    def test_fields(self):
        card = next(c for c in self.page.cards if c.source_job_id == "4001")
        self.assertEqual(card.title, "Sales Development Representative")
        self.assertEqual(card.company_name, "Acme Revenue Ltd")
        self.assertEqual(card.company_url,
                         "https://www.linkedin.com/company/acme-revenue")
        self.assertIn("London", card.location_raw or "")
        self.assertEqual(card.posted_raw, "Posted 3 days ago")

    def test_live_blocked_by_policy(self):
        spec = SearchSpec(sources=["linkedin"], queries=["q"],
                          locations=[__import__("jobcollector.models",
                                                fromlist=["LocationSpec"])
                                     .LocationSpec(country="GB", city="London")])
        with self.assertRaises(SourceBlocked) as ctx:
            self.connector.search(spec, "q", spec.locations[0], None)
        self.assertIn("Disallow: /", str(ctx.exception))


class TestIndeedParser(unittest.TestCase):
    def setUp(self):
        self.connector = IndeedConnector()
        self.page = self.connector.parse_search(
            (FIX / "indeed_search.html").read_text(encoding="utf-8"))

    def test_cards_and_jk(self):
        self.assertEqual(len(self.page.cards), 2)
        ids = {c.source_job_id for c in self.page.cards}
        self.assertEqual(ids, {"aa11bb22cc33dd44", "bb22cc33dd44ee55"})

    def test_fields(self):
        card = next(c for c in self.page.cards
                    if c.source_job_id == "aa11bb22cc33dd44")
        self.assertEqual(card.title, "Sales Development Representative")
        self.assertEqual(card.company_name, "Vertex Cloud Ltd")
        self.assertEqual(card.location_raw, "London")
        self.assertEqual(card.salary_raw, "£38,000 - £45,000 a year")
        self.assertIn("jk=aa11bb22cc33dd44", card.url)

    def test_next_cursor_from_pagination(self):
        self.assertEqual(self.page.next_cursor, "10")

    def test_robots_pagination_cap(self):
        # start=90 ещё разрешён robots (Allow: /*&start=90&) — это последняя страница
        html = '<a href="/jobs?q=x&amp;start=90">Next</a><div data-jk="aa"></div>'
        page = self.connector.parse_search(html)
        self.assertEqual(page.next_cursor, "90")
        # start=100 запрещён robots → курсора нет
        html = '<a href="/jobs?q=x&amp;start=100">Next</a><div data-jk="aa"></div>'
        page = self.connector.parse_search(html)
        self.assertIsNone(page.next_cursor)

    def test_detail_pages_not_requested(self):
        self.assertIsNone(self.connector.parse_detail("<html/>"))

    def test_blocked_classification(self):
        html = (FIX / "blocked_page.html").read_text(encoding="utf-8")
        status, stop = classify_search_page(html, 0)
        self.assertEqual((status, stop), ("blocked", "blocked"))

    def test_no_results_with_markup(self):
        status, stop = classify_search_page(
            '<html><body data-jk-marker="x"></body></html>', 0)
        self.assertEqual(stop, "no_results")


if __name__ == "__main__":
    unittest.main()
