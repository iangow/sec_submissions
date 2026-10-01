"""Write corrected filings from frozen accession-level evidence."""

from pathlib import Path

import duckdb

from ._util import sql_string


def materialize_workflow(args, raw: Path, output: Path) -> None:
    """Materialize timezone-aware timestamps without legacy block rules."""
    with duckdb.connect(str(args.workflow_database), read_only=True) as con:
        con.execute(f"SET threads={args.threads}")
        con.execute(f"SET memory_limit={sql_string(args.memory_limit)}")
        con.execute("SET TimeZone='UTC'; SET enable_progress_bar=false")
        identity = con.execute("SELECT size_bytes,mtime_ns FROM inputs WHERE role='current'").fetchone()
        if identity != (raw.stat().st_size, raw.stat().st_mtime_ns):
            raise ValueError("Raw input differs from the frozen workflow input")
        limit = "" if args.limit is None else f"LIMIT {args.limit}"
        con.execute(f"CREATE TEMP VIEW raw AS SELECT * FROM read_parquet({sql_string(raw)}) {limit}")
        unresolved = con.execute("""SELECT count(*) FROM raw r LEFT JOIN resolved_accessions a
            ON a.accession_number=r.accessionNumber WHERE a.accession_number IS NULL
            AND r.acceptanceDateTime IS NOT NULL AND r.acceptanceDateTime<>'' """).fetchone()[0]
        if unresolved and not args.allow_unresolved:
            raise ValueError(
                f"{unresolved:,} unresolved rows; pass --allow-unresolved for labelled Eastern fallback"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.parquet")
        if temporary.exists():
            raise FileExistsError(temporary)
        con.execute(f"""
            COPY (
              SELECT r.* REPLACE (
                coalesce(a.corrected_instant,try_cast(r.acceptanceDateTime AS TIMESTAMP) AT TIME ZONE 'America/New_York') AS acceptanceDateTime
              ),
              CASE WHEN a.accession_number IS NOT NULL THEN a.provenance
                   WHEN r.acceptanceDateTime IS NULL OR r.acceptanceDateTime='' THEN 'raw_missing'
                   ELSE 'unresolved_raw_as_eastern' END timestamp_provenance,
              a.accession_number timestamp_reference_id,
              CASE WHEN a.accession_number IS NULL THEN 'unresolved'
                   WHEN (try_cast(r.acceptanceDateTime AS TIMESTAMP) AT TIME ZONE 'UTC')=a.corrected_instant THEN 'utc'
                   WHEN (try_cast(r.acceptanceDateTime AS TIMESTAMP) AT TIME ZONE 'America/New_York')=a.corrected_instant THEN 'eastern'
                   ELSE 'anomalous' END timestamp_interpretation
              FROM raw r LEFT JOIN resolved_accessions a ON a.accession_number=r.accessionNumber
            ) TO {sql_string(temporary)} (FORMAT PARQUET)
        """)
        count = con.execute(f"SELECT count(*) FROM read_parquet({sql_string(temporary)})").fetchone()[0]
        if count != con.execute("SELECT count(*) FROM raw").fetchone()[0]:
            raise ValueError("Materialization changed the row count")
        temporary.replace(output)
        print(f"Wrote {output}: {count:,} rows; {unresolved:,} unresolved; accession-only workflow")
