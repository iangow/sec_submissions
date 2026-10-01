"""Collect SEC filing-header observations for an explicit accession queue."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import time

import duckdb

from .http import NetworkRateLimiter, fetch_sgml, resolve_user_agent, retryable

SGML_SCHEMA = """accession_number VARCHAR,cik BIGINT,acceptance_datetime TIMESTAMP,
    source_url VARCHAR,retrieved_at TIMESTAMPTZ,elapsed_ms DOUBLE,http_status INTEGER,
    content_sha256 VARCHAR,sgml_header VARCHAR,error VARCHAR,origin VARCHAR"""


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _save(con, relation: str, path: Path) -> None:
    temporary = path.with_suffix(".partial.parquet")
    temporary.unlink(missing_ok=True)
    con.execute(f"COPY {relation} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temporary)])
    temporary.replace(path)


def collect_sgml(queue, output, workers=8, rate=5, max_attempts=2,
                 user_agent=None, resume=False):
    """Fetch SGML headers for a Parquet queue containing CIK and accession columns.

    The queue is frozen as Parquet before any requests. Every HTTP response and
    parse failure is retained in a checkpoint shard; only transient failures
    are retried. The final ``sgml_observations.parquet`` can be used as the
    process command's cache input.
    """
    queue, output = Path(queue).expanduser().resolve(), Path(output).expanduser().resolve()
    user_agent = resolve_user_agent(user_agent)
    if min(workers, rate, max_attempts) <= 0:
        raise ValueError("Workers, request rate, and maximum attempts must be positive")
    existed = output.exists()
    if existed and not resume:
        raise FileExistsError(output)
    if resume and not existed:
        raise FileNotFoundError(output)
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output / "metadata.parquet"

    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=1; SET memory_limit='2GB'")
        queue_hash = _digest(queue)
        parts = sorted(output.glob("sgml-observations-*.parquet"))
        if resume:
            saved = con.execute("SELECT queue_hash,workers,rate,max_attempts FROM read_parquet(?)",
                                [str(metadata_path)]).fetchone()
            if saved != (queue_hash, workers, rate, max_attempts):
                raise ValueError("Resume requires the original queue, worker count, rate, and retry limit")
        else:
            schema = {row[0] for row in con.execute("DESCRIBE SELECT * FROM read_parquet(?)",
                                                    [str(queue)]).fetchall()}
            accession_col = "accession_number" if "accession_number" in schema else "accessionNumber"
            if "cik" not in schema or accession_col not in schema:
                raise ValueError("Queue must contain cik and accession_number (or accessionNumber)")
            con.execute(f"""CREATE OR REPLACE TEMP TABLE targets AS
                SELECT min(try_cast(cik AS BIGINT)) cik,{accession_col} accession_number
                FROM read_parquet(?) WHERE {accession_col} IS NOT NULL
                GROUP BY {accession_col} ORDER BY {accession_col}""", [str(queue)])
            con.execute("COPY targets TO ? (FORMAT PARQUET)", [str(output / "queue.parquet")])
            con.execute("CREATE TABLE metadata(queue_hash VARCHAR,workers INTEGER,rate DOUBLE,max_attempts INTEGER)")
            con.execute("INSERT INTO metadata VALUES (?,?,?,?)", [queue_hash, workers, rate, max_attempts])
            con.execute("COPY metadata TO ? (FORMAT PARQUET)", [str(metadata_path)])

        con.execute("CREATE OR REPLACE TEMP TABLE targets AS SELECT * FROM read_parquet(?)",
                    [str(output / "queue.parquet")])
        attempts = {}
        if parts:
            con.execute("CREATE TEMP TABLE prior_attempts AS SELECT * FROM read_parquet(?)",
                        [[str(p) for p in parts]])
            attempts = dict(con.execute("SELECT accession_number,count(*) FROM prior_attempts GROUP BY 1").fetchall())
            latest = dict(con.execute("""SELECT accession_number,error FROM prior_attempts
                QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY retrieved_at DESC)=1""").fetchall())
        else:
            latest = {}
        targets = con.execute("SELECT cik,accession_number FROM targets ORDER BY accession_number").fetchall()
        pending = [(cik, accession) for cik, accession in targets
                   if accession not in latest or
                   (retryable(latest[accession]) and attempts.get(accession, 0) < max_attempts)]
        print(f"SGML queue: {len(targets):,} unique accessions; pending={len(pending):,}", flush=True)
        limiter = NetworkRateLimiter(rate)
        batch_number = max((int(p.stem.split("-")[-1]) for p in parts), default=0)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            remaining = pending
            while remaining:
                def fetch(row):
                    limiter.wait()
                    return row[0], row[1], fetch_sgml(row[0], row[1], user_agent)

                results = list(pool.map(fetch, remaining))
                con.execute(f"CREATE OR REPLACE TEMP TABLE batch({SGML_SCHEMA})")
                con.executemany("INSERT INTO batch VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                    (accession, cik, result["acceptance"], result["url"], result["retrieved_at"],
                     result["elapsed_ms"], result["status"], result["digest"], result["text"],
                     result["error"], "network")
                    for cik, accession, result in results
                ])
                batch_number += 1
                _save(con, "batch", output / f"sgml-observations-{batch_number:05d}.parquet")
                failed = [(cik, accession) for cik, accession, result in results
                          if retryable(result["error"])
                          and attempts.get(accession, 0) + 1 < max_attempts]
                for _, accession, _ in results:
                    attempts[accession] = attempts.get(accession, 0) + 1
                print(f"SGML fetched: {len(results):,}; retrying={len(failed):,}; elapsed={time.monotonic()-started:.1f}s", flush=True)
                remaining = failed
                if remaining:
                    time.sleep(5)
        parts = sorted(output.glob("sgml-observations-*.parquet"))
        if parts:
            con.execute("CREATE OR REPLACE TEMP TABLE all_observations AS SELECT * FROM read_parquet(?)",
                        [[str(p) for p in parts]])
            con.execute("COPY all_observations TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                        [str(output / "sgml_observations.parquet")])
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rate", type=float, default=5, help="Maximum total SEC requests per second")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--user-agent", help="Defaults to SEC_USER_AGENT")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    from .workflow import collect_sgml as collect_with_defaults
    collect_with_defaults(args.queue, args.output, args.workers, args.rate,
                          args.max_attempts, args.user_agent, args.resume,args.data_dir)
