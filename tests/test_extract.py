import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import duckdb

from sec_submissions import extract_submissions


class ExtractionTests(unittest.TestCase):
    def test_small_archive_retains_text_timestamps_and_date_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, output = root / "submissions.zip", root / "filings_raw.parquet"
            payload = {
                "cik": 1,
                "filings": {"recent": {
                    "accessionNumber": ["0000000001-25-000001"],
                    "filingDate": ["2025-07-01"],
                    "reportDate": ["2025-06-30"],
                    "acceptanceDateTime": ["2025-07-01T12:34:56.123Z"],
                    "form": ["10-K"],
                }},
            }
            with zipfile.ZipFile(archive, "w") as source:
                source.writestr("CIK0000000001.json", json.dumps(payload))
            self.assertTrue(extract_submissions(archive, output, max_seconds=0))
            with duckdb.connect() as con:
                clock, date_value, date_type = con.execute(
                    "SELECT acceptanceDateTime,filingDate,typeof(filingDate) "
                    "FROM read_parquet(?)", [str(output)]
                ).fetchone()
            self.assertEqual(clock, "2025-07-01T12:34:56.123Z")
            self.assertEqual(str(date_value), "2025-07-01")
            self.assertEqual(date_type, "DATE")


if __name__ == "__main__":
    unittest.main()
