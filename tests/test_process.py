from pathlib import Path
import tempfile
import unittest

import duckdb

from sec_submissions import make_previous, process


class ProcessTests(unittest.TestCase):
    def test_prior_instants_and_duplicate_pairs_produce_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_raw, previous = root / "old_raw.parquet", root / "filings_previous.parquet"
            raw, output = root / "raw.parquet", root / "candidate.parquet"
            with duckdb.connect() as con:
                con.execute("""COPY (SELECT * FROM (VALUES
                    (1,'known','old.json','10-K','2025-07-01T12:00:00Z'))
                    AS t(cik,accessionNumber,source_file,form,acceptanceDateTime))
                    TO ? (FORMAT PARQUET)""", [str(old_raw)])
                con.execute("""COPY (SELECT * FROM (VALUES
                    (1,'known','new.json','10-K','2025-07-01T16:00:00Z'),
                    (2,'pair','new.json','10-K','2025-07-01T12:00:00Z'),
                    (3,'pair','other.json','10-K','2025-07-01T16:00:00Z'))
                    AS t(cik,accessionNumber,source_file,form,acceptanceDateTime))
                    TO ? (FORMAT PARQUET)""", [str(raw)])
            make_previous(old_raw, previous)
            process(raw, previous, output, memory_limit="1GB")
            with duckdb.connect() as con:
                con.execute("SET TimeZone='UTC'")
                rows = con.execute("""SELECT accessionNumber,hour(acceptanceDateTime),
                    timestamp_provenance FROM read_parquet(?) ORDER BY accessionNumber,cik""",
                    [str(output)]).fetchall()
            self.assertEqual(rows, [
                ("known", 16, "trusted_snapshot_eastern"),
                ("pair", 16, "cross_cik_pair"),
                ("pair", 16, "cross_cik_pair"),
            ])
            self.assertTrue((root / "candidate_checks" / "summary.parquet").is_file())


if __name__ == "__main__":
    unittest.main()
