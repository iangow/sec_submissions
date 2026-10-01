"""Build the explicitly labeled 2024 Eastern-clock bootstrap reference."""

from pathlib import Path

import duckdb


def make_previous(raw, output):
    """Create ``filings_previous.parquet`` from the 2024 raw reference ZIP.

    This is a one-time bootstrap for the worked workflow, not a general rule
    that later SEC ZIP snapshots use Eastern clock values.
    """
    raw, output = Path(raw).expanduser().resolve(), Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".partial.parquet")
    if temporary.exists():
        raise FileExistsError(temporary)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=4; SET memory_limit='2GB'")
        schema = dict((row[0], row[1]) for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(raw)]).fetchall())
        if schema.get("acceptanceDateTime") != "VARCHAR":
            raise ValueError("Reference input must preserve the original timestamp text")
        con.execute("""CREATE TEMP TABLE previous AS
            SELECT * REPLACE(try_cast(acceptanceDateTime AS TIMESTAMP) AT TIME ZONE 'America/New_York' AS acceptanceDateTime),
                CASE WHEN try_cast(acceptanceDateTime AS TIMESTAMP) IS NULL THEN 'raw_missing'
                     WHEN CAST(try_cast(acceptanceDateTime AS TIMESTAMP) AS TIME)=TIME '00:00:00'
                     THEN 'historical_midnight_unverified' ELSE 'trusted_snapshot_eastern' END timestamp_provenance,
                accessionNumber timestamp_reference_id
            FROM read_parquet(?)""", [str(raw)])
        con.execute("COPY previous TO ? (FORMAT PARQUET,COMPRESSION ZSTD)", [str(temporary)])
        print("2024 reference:", con.execute(
            "SELECT timestamp_provenance,count(*) FROM previous GROUP BY 1").fetchall(), flush=True)
    temporary.rename(output)
    return output
