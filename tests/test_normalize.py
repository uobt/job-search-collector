"""Тесты нормализации: даты, зарплаты, гео, сеньорити, полнота."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobcollector.models import JobCard
from jobcollector.normalize import (normalize_card, parse_location,
                                    parse_posted, parse_salary,
                                    parse_seniority, parse_workplace)
from jobcollector.quality import completeness_flags, looks_blocked


class TestDates(unittest.TestCase):
    def test_relative_days(self):
        ref = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
        iso, precision, kind = parse_posted("Posted 3 days ago", ref)
        self.assertEqual(precision, "relative")
        self.assertEqual(kind, "published")
        self.assertTrue(iso.startswith("2026-09-14"))

    def test_range_30_plus_is_not_exact(self):
        iso, precision, _ = parse_posted("Posted 30+ days ago")
        self.assertEqual(precision, "range")

    def test_just_posted(self):
        iso, precision, _ = parse_posted("Just posted")
        self.assertEqual(precision, "day")
        self.assertIsNotNone(iso)

    def test_iso_date(self):
        iso, precision, _ = parse_posted("2026-09-14")
        self.assertEqual((precision, iso[:10]), ("exact", "2026-09-14"))

    def test_unparsable_is_none(self):
        self.assertEqual(parse_posted("вчера"), (None, None, "unknown"))
        self.assertEqual(parse_posted(None), (None, None, "unknown"))

    def test_first_seen_not_faked(self):
        record = normalize_card(JobCard(source="x", source_job_id="1", title="T"))
        self.assertIsNone(record.published_at)          # нет выдуманной даты
        self.assertIsNotNone(record.first_seen_at)      # но факт наблюдения есть
        self.assertLessEqual(record.first_seen_at, record.last_seen_at)


class TestSalary(unittest.TestCase):
    def test_gbp_year_range(self):
        parsed = parse_salary("£38,000 - £45,000 a year")
        self.assertEqual(parsed["salary_min"], 38000)
        self.assertEqual(parsed["salary_max"], 45000)
        self.assertEqual(parsed["salary_currency"], "GBP")
        self.assertEqual(parsed["salary_period"], "year")

    def test_usd_hour(self):
        parsed = parse_salary("$25-$30 per hour")
        self.assertEqual((parsed["salary_min"], parsed["salary_max"]), (25, 30))
        self.assertEqual(parsed["salary_period"], "hour")

    def test_garbage(self):
        parsed = parse_salary("competitive salary")
        self.assertIsNone(parsed["salary_min"])


class TestGeo(unittest.TestCase):
    def test_uk_location(self):
        self.assertEqual(parse_location("London, England, United Kingdom")[0], "gb")

    def test_us_state_not_country(self):
        self.assertEqual(parse_location("Austin, TX")[0], "us")

    def test_unknown(self):
        self.assertIsNone(parse_location("Середина nowhere")[0])

    def test_seniority(self):
        self.assertEqual(parse_seniority("Head of Sales"), "c_level")
        self.assertEqual(parse_seniority("Senior SDR"), "senior")
        self.assertIsNone(parse_seniority("Account Executive"))

    def test_workplace(self):
        self.assertEqual(parse_workplace("Remote - UK"), "remote")
        self.assertEqual(parse_workplace("London (Hybrid)"), "hybrid")
        self.assertIsNone(parse_workplace("London"))


class TestQuality(unittest.TestCase):
    def test_blocked_page_detected(self):
        fixture = Path(__file__).parent / "fixtures" / "blocked_page.html"
        self.assertTrue(looks_blocked(fixture.read_text(encoding="utf-8")))

    def test_normal_page_not_blocked(self):
        fixture = Path(__file__).parent / "fixtures" / "indeed_search.html"
        self.assertFalse(looks_blocked(fixture.read_text(encoding="utf-8")))

    def test_completeness_flags(self):
        record = normalize_card(JobCard(
            source="x", source_job_id="1", title="SDR",
            posted_raw="Posted 30+ days ago", snippet="only a snippet"))
        flags = completeness_flags(record)
        self.assertFalse(flags["has_publish_date"])
        self.assertTrue(flags["description_truncated"])
        self.assertFalse(flags["has_salary"])


if __name__ == "__main__":
    unittest.main()
