"""Тесты экспорта: BOM, formula-injection guard, JSONL."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobcollector.export import export_csv, export_jsonl
from jobcollector.models import JobCard
from jobcollector.normalize import normalize_card


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        card = JobCard(source="linkedin", source_job_id="1", title="=SUM(A1)",
                       company_name="+REF", snippet="line1\nline2, with comma",
                       location_raw="London, UK")
        self.record = normalize_card(card)
        self.rows = [self.record.as_row()]

    def tearDown(self):
        self.tmp.cleanup()

    def test_csv_bom_and_formula_guard(self):
        out = Path(self.tmp.name) / "jobs.csv"
        written = export_csv(self.rows, out)
        self.assertEqual(written, 1)
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))       # UTF-8 BOM
        with out.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][0], "source")
        title_cell = rows[1][rows[0].index("title")]
        company_cell = rows[1][rows[0].index("company_name")]
        self.assertTrue(title_cell.startswith("'="))
        self.assertTrue(company_cell.startswith("'+"))
        # многострочный snippet корректно закавычен csv-модулем
        desc_cell = rows[1][rows[0].index("description")]
        self.assertIn("line1", desc_cell)

    def test_jsonl_roundtrip(self):
        out = Path(self.tmp.name) / "jobs.jsonl"
        written = export_jsonl(self.rows, out)
        self.assertEqual(written, 1)
        line = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(line["source_job_id"], "1")


if __name__ == "__main__":
    unittest.main()
