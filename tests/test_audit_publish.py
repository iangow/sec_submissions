from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from sec_submissions import audit, publish


class AuditPublishTests(unittest.TestCase):
    def test_cached_audit_reports_errors_without_mutating_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filings, cache, output = root / "filings.parquet", root / "sgml.parquet", root / "audit"
            with duckdb.connect() as con:
                con.execute("""COPY (SELECT * FROM (VALUES
                    (1,'a','file.json','10-K',TIMESTAMPTZ '2025-07-01 12:00:00+00','snapshot_pair'),
                    (2,'b','file.json','10-K',TIMESTAMPTZ '2025-07-01 12:00:00+00','snapshot_pair'))
                    AS t(cik,accessionNumber,source_file,form,acceptanceDateTime,timestamp_provenance))
                    TO ? (FORMAT PARQUET)""", [str(filings)])
                con.execute("""COPY (SELECT * FROM (VALUES
                    ('a',1,'2025-07-01 08:00:00'::TIMESTAMP,'https://example/a',now(),1.0,200,'a','header a',NULL),
                    ('b',2,'2025-07-01 09:00:00'::TIMESTAMP,'https://example/b',now(),1.0,200,'b','header b',NULL::VARCHAR))
                    AS t(accession_number,cik,acceptance_datetime,source_url,retrieved_at,elapsed_ms,
                          http_status,content_sha256,sgml_header,error))
                    TO ? (FORMAT PARQUET)""", [str(cache)])
            audit(filings, output, sample_size=2, seed=3, cache=cache, workers=1, rate=1000,
                  user_agent="Example User example@example.org")
            with patch("sec_submissions.audit.fetch_sgml", side_effect=AssertionError("unexpected refetch")):
                audit(filings, output, sample_size=2, seed=3, cache=cache, workers=1, rate=1000,
                      user_agent="Example User example@example.org", resume=True)
            with duckdb.connect() as con:
                sampled, verified, errors = con.execute(
                    "SELECT sampled_rows,verified_rows,errors FROM read_parquet(?)",
                    [str(output / "summary.parquet")],
                ).fetchone()
            self.assertEqual(len((output / "sample_identifiers.csv").read_text().splitlines()), 3)
            self.assertEqual((sampled, verified, errors), (2, 2, 1))

    def test_publish_preserves_current_path_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root / name for name in (
                "filings.parquet", "candidate.parquet", "filings_previous.parquet")]
            with duckdb.connect() as con:
                con.execute("COPY (SELECT TIMESTAMPTZ '2025-01-01 12:00:00+00' acceptanceDateTime) TO ? (FORMAT PARQUET)",
                            [str(current)])
                con.execute("COPY (SELECT TIMESTAMPTZ '2025-01-01 13:00:00+00' acceptanceDateTime) TO ? (FORMAT PARQUET)",
                            [str(candidate)])
            inode = current.stat().st_ino
            rows, archived = publish(candidate, current, previous, root / "archive")
            self.assertEqual(rows, 1)
            self.assertIsNone(archived)
            self.assertEqual(current.stat().st_ino, inode)
            self.assertEqual(current.read_bytes(), candidate.read_bytes())
            self.assertTrue(previous.is_file())


if __name__ == "__main__":
    unittest.main()
