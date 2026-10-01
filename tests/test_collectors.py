from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from sec_submissions.live_json import collect_live_json
from sec_submissions.sgml import collect_sgml


class CollectorTests(unittest.TestCase):
    def test_live_collector_fetches_all_rows_in_selected_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, raw = root / "candidate.parquet", root / "raw.parquet"
            with duckdb.connect() as con:
                con.execute("""COPY (SELECT * FROM (VALUES
                    (1,'0000000001-26-000001','CIK0000000001.json',
                     TIMESTAMPTZ '2026-09-30 12:00:00+00','unresolved_raw_as_eastern'))
                    AS t(cik,accessionNumber,source_file,acceptanceDateTime,timestamp_provenance))
                    TO ? (FORMAT PARQUET)""", [str(candidate)])
                con.execute("""COPY (SELECT * FROM (VALUES
                    (1,'0000000001-26-000001','CIK0000000001.json','2026-09-30T12:00:00Z'),
                    (1,'0000000001-26-000002','CIK0000000001.json','2026-09-30T13:00:00Z'))
                    AS t(cik,accessionNumber,source_file,acceptanceDateTime))
                    TO ? (FORMAT PARQUET)""", [str(raw)])
            payload = {"filings": {"recent": {
                "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002"],
                "acceptanceDateTime": ["2026-09-30T12:00:00Z", "2026-09-30T13:00:00Z"],
            }}}
            output = root / "live-evidence"
            with patch("sec_submissions.live_json.fetch_json", return_value=(payload, 200)):
                collect_live_json(candidate, raw, output, date(2024, 1, 1), workers=1,
                                  sample_blocks=1, rate=1000,
                                  user_agent="Example User example@example.org")
            with patch("sec_submissions.live_json.fetch_json", side_effect=AssertionError("unexpected refetch")):
                collect_live_json(candidate, raw, output, date(2024, 1, 1), workers=1,
                                  sample_blocks=1, rate=1000,
                                  user_agent="Example User example@example.org", resume=True)
            with duckdb.connect() as con:
                rows = con.execute("SELECT accession_number FROM read_parquet(?) ORDER BY 1",
                    [str(output / "live_json_timestamp_observations.parquet")]).fetchall()
            self.assertEqual(rows, [("0000000001-26-000001",), ("0000000001-26-000002",)])

    def test_sgml_collector_writes_process_compatible_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, output = root / "queue.parquet", root / "sgml-evidence"
            with duckdb.connect() as con:
                con.execute("COPY (SELECT 1::BIGINT cik,'0000000001-26-000001' accession_number) "
                            "TO ? (FORMAT PARQUET)", [str(queue)])
            result = {
                "acceptance": datetime(2026, 9, 30, 12, 34, 56),
                "url": "https://www.sec.gov/example.hdr.sgml",
                "retrieved_at": datetime.now(timezone.utc), "elapsed_ms": 10.0,
                "status": 200, "digest": "abc", "text": "<ACCEPTANCE-DATETIME>20260930123456",
                "error": None,
            }
            with patch("sec_submissions.sgml.fetch_sgml", return_value=result):
                collect_sgml(queue, output, workers=1, rate=1000,
                             user_agent="Example User example@example.org")
            with patch("sec_submissions.sgml.fetch_sgml", side_effect=AssertionError("unexpected refetch")):
                collect_sgml(queue, output, workers=1, rate=1000,
                             user_agent="Example User example@example.org", resume=True)
            with duckdb.connect() as con:
                row = con.execute("SELECT acceptance_datetime,error FROM read_parquet(?)",
                    [str(output / "sgml_observations.parquet")]).fetchone()
            self.assertEqual(row, (datetime(2026, 9, 30, 12, 34, 56), None))


if __name__ == "__main__":
    unittest.main()
