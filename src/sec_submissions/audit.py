"""Freeze a probability sample and assess corrected timestamps against SGML."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time

import duckdb

from ._util import digest, sql_string
from .http import NetworkRateLimiter, fetch_sgml, resolve_user_agent, retryable

OBSERVATION_SCHEMA = """accession_number VARCHAR,cik BIGINT,acceptance_datetime TIMESTAMP,
    source_url VARCHAR,retrieved_at TIMESTAMPTZ,elapsed_ms DOUBLE,http_status INTEGER,
    content_sha256 VARCHAR,sgml_header VARCHAR,error VARCHAR,origin VARCHAR"""


def _save_batch(con, directory, number, results, origin):
    con.execute(f"CREATE OR REPLACE TEMP TABLE batch({OBSERVATION_SCHEMA})")
    con.executemany("INSERT INTO batch VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (accession, cik, result["acceptance"], result["url"], result["retrieved_at"],
         result["elapsed_ms"], result["status"], result["digest"], result["text"],
         result["error"], origin)
        for cik, accession, result in results
    ])
    path = directory / f"observations-{number:05d}.parquet"
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(".partial.parquet")
    con.execute("COPY batch TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temporary)])
    temporary.replace(path)


def _freeze(con, filings, output, sample_size, seed):
    population = con.execute("SELECT count(*) FROM read_parquet(?)", [str(filings)]).fetchone()[0]
    if not 0 < sample_size <= population:
        raise ValueError("Sample size must be positive and no larger than the filing population")
    con.execute(f"""CREATE TABLE sample AS
        SELECT file_row_number sample_row,cik,accessionNumber,source_file,form,
               acceptanceDateTime predicted,timestamp_provenance
        FROM read_parquet({sql_string(filings)},file_row_number=true)
        USING SAMPLE reservoir({sample_size} ROWS) REPEATABLE({seed})""")
    con.execute("COPY sample TO ? (FORMAT PARQUET)", [str(output / "sample.parquet")])
    con.execute("COPY sample TO ? (FORMAT CSV, HEADER)", [str(output / "sample_identifiers.csv")])
    stat = filings.stat()
    con.execute("""CREATE TABLE metadata(filings VARCHAR,size_bytes BIGINT,mtime_ns BIGINT,
        sha256 VARCHAR,population_n BIGINT,sample_n BIGINT,seed BIGINT,frozen_at TIMESTAMPTZ,
        policy VARCHAR)""")
    con.execute("INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?)", [
        str(filings), stat.st_size, stat.st_mtime_ns, digest(filings), population,
        sample_size, seed, datetime.now(timezone.utc),
        "Simple random filing-row sample; predictions frozen before SGML lookup; no repairs",
    ])
    con.execute("COPY metadata TO ? (FORMAT PARQUET)", [str(output / "metadata.parquet")])


def _report(con, output):
    paths = sorted(str(p) for p in output.glob("observations-*.parquet")
                   if ".partial." not in p.name)
    if not paths:
        raise ValueError("No SGML observations are available to report")
    con.execute("""CREATE OR REPLACE TEMP TABLE observations AS
        SELECT * FROM read_parquet(?)
        QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY retrieved_at DESC)=1""",
        [paths])
    con.execute("""CREATE OR REPLACE TABLE outcomes AS
        SELECT p.*,o.* EXCLUDE(accession_number,cik),
            o.acceptance_datetime AT TIME ZONE 'America/New_York' sgml_instant,
            coalesce(o.acceptance_datetime IS NOT NULL AND o.error IS NULL,false) verifiable,
            CASE WHEN o.acceptance_datetime IS NOT NULL AND o.error IS NULL
                 THEN p.predicted IS DISTINCT FROM o.acceptance_datetime AT TIME ZONE 'America/New_York' END is_error
        FROM sample p LEFT JOIN observations o ON o.accession_number=p.accessionNumber""")
    sampled, verified, errors = con.execute("""SELECT count(*),count(*) FILTER(WHERE verifiable),
        count(*) FILTER(WHERE is_error) FROM outcomes""").fetchone()
    if verified:
        try:
            from scipy.stats import beta
        except ImportError as exc:
            raise RuntimeError("Install sec-submissions[audit] to calculate the confidence bound") from exc
        upper = 1.0 if errors == verified else float(beta.ppf(.95, errors + 1, verified - errors))
    else:
        upper = None
    con.execute("""CREATE OR REPLACE TABLE summary AS SELECT ?::BIGINT sampled_rows,
        ?::BIGINT verified_rows,?::BIGINT errors,?::BIGINT unavailable_rows,
        ?::DOUBLE error_upper_95_among_verifiable""",
        [sampled, verified, errors, sampled - verified, upper])
    for name in ("outcomes", "summary"):
        con.execute(f"COPY {name} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(output / f"{name}.parquet")])
    print("Audit summary:", con.execute("SELECT * FROM summary").fetchone(), flush=True)
    print("Unavailable:", con.execute(
        "SELECT error,count(*) FROM outcomes WHERE NOT verifiable GROUP BY 1").fetchall(), flush=True)
    print("Methods:", con.execute("""SELECT timestamp_provenance,count(*),
        count(*) FILTER(WHERE verifiable),count(*) FILTER(WHERE is_error)
        FROM outcomes GROUP BY 1""").fetchall(), flush=True)
    print("The bound is conditional on verifiable headers; predictions were not changed.", flush=True)


def audit(filings, output, sample_size=10_000, seed=20261001, cache=None,
          workers=8, rate=5, user_agent=None, resume=False):
    filings, output = Path(filings).expanduser().resolve(), Path(output).expanduser().resolve()
    cache = None if cache is None else Path(cache).expanduser().resolve()
    user_agent = resolve_user_agent(user_agent)
    if min(sample_size, workers, rate) <= 0:
        raise ValueError("Sample size, workers, and request rate must be positive")
    existed = output.exists()
    if existed and not resume:
        raise FileExistsError(output)
    if resume and not existed:
        raise FileNotFoundError(output)
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=1; SET memory_limit='2GB'")
        if existed:
            metadata = con.execute("SELECT sha256,sample_n,seed FROM read_parquet(?)",
                                   [str(output / "metadata.parquet")]).fetchone()
            if metadata != (digest(filings), sample_size, seed):
                raise ValueError("Resume requires the original candidate, sample size, and seed")
            con.execute("CREATE TABLE sample AS SELECT * FROM read_parquet(?)",
                        [str(output / "sample.parquet")])
        else:
            _freeze(con, filings, output, sample_size, seed)

        paths = sorted(output.glob("observations-*.parquet"))
        number = max((int(p.stem.split("-")[-1]) for p in paths), default=0)
        attempts = {}
        cached = set()
        if paths:
            con.execute("CREATE TEMP TABLE saved AS SELECT * FROM read_parquet(?)",
                        [[str(p) for p in paths]])
            attempts = dict(con.execute("SELECT accession_number,count(*) FILTER(WHERE origin LIKE 'audit_%') FROM saved GROUP BY 1").fetchall())
            for accession, error in con.execute("""SELECT accession_number,error FROM saved
                QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY retrieved_at DESC)=1""").fetchall():
                if not retryable(error) or attempts.get(accession, 0) >= 2:
                    cached.add(accession)
        if cache is not None and cache.is_file():
            con.execute("""CREATE TEMP TABLE cached AS SELECT * FROM read_parquet(?)
                WHERE accession_number IN (SELECT accessionNumber FROM sample)
                  AND ((acceptance_datetime IS NOT NULL AND error IS NULL)
                    OR error LIKE '%ACCEPTANCE-DATETIME tag not found%')""", [str(cache)])
            rows = con.execute("SELECT * FROM cached").fetchall()
            names = [row[0] for row in con.execute("DESCRIBE cached").fetchall()]
            cache_results = []
            for values in rows:
                row = dict(zip(names, values, strict=True))
                if row["accession_number"] in cached:
                    continue
                cached.add(row["accession_number"])
                cache_results.append((row["cik"], row["accession_number"], {
                    "acceptance": row["acceptance_datetime"], "url": row["source_url"],
                    "retrieved_at": row["retrieved_at"], "elapsed_ms": row["elapsed_ms"],
                    "status": row["http_status"], "digest": row["content_sha256"],
                    "text": row["sgml_header"], "error": row["error"],
                }))
            if cache_results:
                number += 1
                _save_batch(con, output, number, cache_results, "existing_cache")
        pending = [row for row in con.execute(
            "SELECT min(cik),accessionNumber FROM sample GROUP BY accessionNumber ORDER BY accessionNumber"
        ).fetchall() if row[1] not in cached]
        print(f"Frozen sample: {sample_size:,}; cached: {len(cached):,}; fetching: {len(pending):,}", flush=True)
        limiter = NetworkRateLimiter(rate)

        def fetch(row):
            cik, accession = row
            limiter.wait()
            return cik, accession, fetch_sgml(cik, accession, user_agent)

        started = time.monotonic()
        retry = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for offset in range(0, len(pending), 50):
                results = list(pool.map(fetch, pending[offset:offset + 50]))
                number += 1
                _save_batch(con, output, number, results, "audit_fetch")
                for cik, accession, result in results:
                    attempts[accession] = attempts.get(accession, 0) + 1
                    if retryable(result["error"]) and attempts[accession] < 2:
                        retry.append((cik, accession))
                print(f"Audit fetches {offset + len(results):,}/{len(pending):,}; elapsed={time.monotonic()-started:.1f}s", flush=True)
            if retry:
                time.sleep(5)
                print(f"Retrying {len(retry):,} transient failures", flush=True)
                for offset in range(0, len(retry), 50):
                    results = list(pool.map(fetch, retry[offset:offset + 50]))
                    number += 1
                    _save_batch(con, output, number, results, "audit_retry")
        _report(con, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--cache", type=Path, help="Optional SGML observation Parquet")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rate", type=float, default=5)
    parser.add_argument("--user-agent", help="Defaults to SEC_USER_AGENT")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    audit(args.filings, args.output, args.sample_size, args.seed, args.cache,
          args.workers, args.rate, args.user_agent, args.resume)
