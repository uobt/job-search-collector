"""Тесты хранилища: идемпотентность, дедупликация, отсутствие ложных закрытий."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobcollector.deduplicate import (cross_source_candidate, normalize_url_key)
from jobcollector.models import JobCard
from jobcollector.normalize import normalize_card
from jobcollector.storage import Store


def make_card(source="linkedin", job_id="1", title="SDR",
              company="Acme", city_hint="London, England, United Kingdom",
              apply_url=None, posted="Posted 2 days ago"):
    return JobCard(source=source, source_job_id=job_id, title=title,
                   company_name=company, location_raw=city_hint,
                   posted_raw=posted, url=f"https://x/{job_id}",
                   apply_url=apply_url, snippet="pipeline")


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_idempotent(self):
        record = normalize_card(make_card())
        self.assertEqual(self.store.upsert_job(record), "first_seen")
        self.assertEqual(self.store.upsert_job(record), "unchanged")

    def test_rerun_same_card_no_fake_update(self):
        """Повторная нормализация той же карточки (относительная дата
        пересчиталась) не создаёт ложного события изменения."""
        self.store.upsert_job(normalize_card(make_card()))
        second = normalize_card(make_card())   # новый published_at от relative
        self.assertEqual(self.store.upsert_job(second), "unchanged")

    def test_change_detected_by_hash(self):
        first = normalize_card(make_card(title="SDR"))
        self.store.upsert_job(first)
        changed = normalize_card(make_card(title="Senior SDR"))
        self.assertEqual(self.store.upsert_job(changed), "updated")
        rows = self.store.jobs(availability=None)
        self.assertEqual(rows[0]["title"], "Senior SDR")

    def test_disappearance_does_not_close(self):
        record = normalize_card(make_card())
        self.store.upsert_job(record)
        # «повторный прогон не увидел вакансию» — никто не вызывает close;
        # availability остаётся observed_open
        rows = self.store.jobs(availability="observed_open")
        self.assertEqual(len(rows), 1)

    def test_same_job_two_queries_one_record(self):
        record = normalize_card(make_card(job_id="77"))
        run = self.store.start_run("collect", "{}", "linkedin")
        self.store.upsert_job(record)
        self.store.record_hit(run, record, "query A", "London/GB", 0, 0)
        self.store.record_hit(run, record, "query B", "London/GB", 0, 1)
        self.assertEqual(len(self.store.jobs(availability=None)), 1)
        info = self.store.summary()
        self.assertEqual(info["jobs_total"], 1)

    def test_cross_query_dedup_by_key(self):
        for _ in range(3):
            self.store.upsert_job(normalize_card(make_card(job_id="5")))
        self.assertEqual(self.store.summary()["jobs_total"], 1)


class TestDeduplication(unittest.TestCase):
    def test_url_key_normalization(self):
        a = normalize_url_key(
            "https://www.linkedin.com/jobs/view/4001/?utm_source=x&trk=y")
        b = normalize_url_key("https://www.linkedin.com/jobs/view/4001/")
        self.assertEqual(a, b)

    def test_weak_candidate_same_company_title_city(self):
        a = normalize_card(make_card(source="linkedin", job_id="L1",
                                     company="Vertex Cloud Ltd",
                                     apply_url="https://linkedin.com/jobs/view/1"))
        b = normalize_card(make_card(source="indeed", job_id="I1",
                                     company="Vertex Cloud Ltd",
                                     apply_url="https://indeed.com/viewjob?jk=1"))
        self.assertIsNotNone(cross_source_candidate(a, b))

    def test_no_candidate_different_company(self):
        a = normalize_card(make_card(source="linkedin", job_id="L2",
                                     company="Acme"))
        b = normalize_card(make_card(source="indeed", job_id="I2",
                                     company="Othercorp"))
        self.assertIsNone(cross_source_candidate(a, b))


if __name__ == "__main__":
    unittest.main()
