"""Collect live submissions JSON observations for unresolved recent blocks."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import time

import duckdb
import pyarrow as pa

from .http import NetworkRateLimiter, fetch_json, resolve_user_agent

BASE_URL = "https://data.sec.gov/submissions/"
UNRESOLVED = ("unresolved_raw_as_eastern", "special_form_unresolved_raw_as_eastern")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _save(con, relation: str, path: Path) -> None:
    temporary = path.with_suffix(".partial.parquet")
    temporary.unlink(missing_ok=True)
    con.execute(f"COPY {relation} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temporary)])
    temporary.replace(path)


def fetch_block(item, user_agent: str, limiter: NetworkRateLimiter, follow_history=True):
    block, cik, rows = item
    live = {}
    locations = {}
    requests = 0
    try:
        if Path(block).name != block or not block.startswith("CIK") or not block.endswith(".json"):
            raise ValueError(f"Invalid SEC submissions filename: {block}")

        def get(url):
            nonlocal requests
            limiter.wait()
            requests += 1
            return fetch_json(url, user_agent)

        url = BASE_URL + block
        data, _ = get(url)
        recent = data.get("filings", {}).get("recent", data)
        accessions = recent.get("accessionNumber", [])
        clocks = recent.get("acceptanceDateTime", [])
        if len(accessions) != len(clocks):
            raise ValueError(f"Mismatched accession/timestamp arrays in {block}")
        live.update(zip(accessions, clocks, strict=True))
        locations.update({accession: url for accession in accessions})

        missing = {accession for _, accession, _ in rows if accession not in live}
        if follow_history and missing:
            root_url = f"{BASE_URL}CIK{cik:010d}.json"
            if root_url != url:
                root, _ = get(root_url)
                root_recent = root.get("filings", {}).get("recent", {})
                root_accessions = root_recent.get("accessionNumber", [])
                root_clocks = root_recent.get("acceptanceDateTime", [])
                if len(root_accessions) != len(root_clocks):
                    raise ValueError(f"Mismatched accession/timestamp arrays in {root_url}")
                for accession, clock in zip(root_accessions, root_clocks, strict=True):
                    if accession in missing:
                        live[accession] = clock
                        locations[accession] = root_url
                        missing.remove(accession)
                root_data = root
            else:
                root_data = data

            for reference in root_data.get("filings", {}).get("files", []):
                if not missing:
                    break
                name = reference.get("name", "")
                if Path(name).name != name or not name.startswith("CIK") or not name.endswith(".json"):
                    continue
                history_url = BASE_URL + name
                if history_url == url:
                    continue
                history, _ = get(history_url)
                history_accessions = history.get("accessionNumber", [])
                history_clocks = history.get("acceptanceDateTime", [])
                if len(history_accessions) != len(history_clocks):
                    continue
                for accession, clock in zip(history_accessions, history_clocks, strict=True):
                    if accession in missing:
                        live[accession] = clock
                        locations[accession] = history_url
                        missing.remove(accession)

        observations = [
            (locations[accession], accession, live[accession], cik, zip_text, block)
            for row_cik, accession, zip_text in rows
            if row_cik == cik and accession in live
        ]
        return observations, (block, len(observations), len(rows) - len(observations), None, requests)
    except Exception as exc:
        observations = [
            (locations[accession], accession, live[accession], cik, zip_text, block)
            for row_cik, accession, zip_text in rows
            if row_cik == cik and accession in live
        ]
        return observations, (block, len(observations), len(rows) - len(observations),
                               f"{type(exc).__name__}: {exc}", requests)


def collect_live_json(filings, raw, output, since_date=date(2024, 1, 1),
                      sample_blocks=None, seed=20261001, workers=8, rate=5,
                      user_agent=None, resume=False):
    """Collect live JSON for candidate-unresolved blocks and save Parquet evidence.

    The block sample, if requested, is frozen in ``selection.parquet``. Each
    selected block contributes all matching raw filings, not only unresolved
    rows, so consistent accessions can anchor file-level inference.
    """
    filings, raw, output = (Path(p).expanduser().resolve() for p in (filings, raw, output))
    user_agent = resolve_user_agent(user_agent)
    if min(workers, rate) <= 0 or (sample_blocks is not None and sample_blocks <= 0):
        raise ValueError("Workers, rate, and an optional block sample must be positive")
    existed = output.exists()
    if existed and not resume:
        raise FileExistsError(output)
    if resume and not existed:
        raise FileNotFoundError(output)
    output.mkdir(parents=True, exist_ok=True)

    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=1; SET memory_limit='2GB'")
        metadata = output / "metadata.parquet"
        identity = (_digest(filings), _digest(raw), since_date, sample_blocks, seed, workers, rate)
        if resume:
            saved = con.execute("SELECT * FROM read_parquet(?)", [str(metadata)]).fetchone()
            if saved is None or tuple(saved) != identity:
                raise ValueError("Resume requires the original inputs, cutoff, sample, seed, workers, and rate")
            con.execute("CREATE TABLE selected_blocks AS SELECT * FROM read_parquet(?)",
                        [str(output / "selection.parquet")])
        else:
            con.execute("""CREATE TABLE unresolved AS
                SELECT DISTINCT source_file FROM read_parquet(?)
                WHERE timestamp_provenance IN (SELECT unnest(?))
                  AND acceptanceDateTime AT TIME ZONE 'America/New_York' >= ?
                  AND source_file IS NOT NULL""", [str(filings), list(UNRESOLVED), since_date])
            con.execute("""CREATE TABLE blocks AS
                SELECT r.source_file, min(r.cik)::BIGINT cik, count(*)::BIGINT rows_n
                FROM read_parquet(?) r JOIN unresolved u USING(source_file)
                GROUP BY r.source_file ORDER BY r.source_file""", [str(raw)])
            population = con.execute("SELECT count(*) FROM blocks").fetchone()[0]
            if population == 0:
                raise ValueError("No recent unresolved blocks meet the cutoff")
            if sample_blocks is not None:
                con.execute(f"CREATE TABLE selected_blocks AS SELECT * FROM blocks "
                            f"USING SAMPLE reservoir({min(sample_blocks, population)} ROWS) "
                            f"REPEATABLE({seed})")
            else:
                con.execute("CREATE TABLE selected_blocks AS SELECT * FROM blocks")
            con.execute("COPY selected_blocks TO ? (FORMAT PARQUET)", [str(output / "selection.parquet")])
            con.execute("CREATE TABLE metadata(input_hash VARCHAR,raw_hash VARCHAR,cutoff DATE,sample_blocks BIGINT,seed BIGINT,workers INTEGER,rate DOUBLE)")
            con.execute("INSERT INTO metadata VALUES (?,?,?,?,?,?,?)", [*identity])
            con.execute("COPY metadata TO ? (FORMAT PARQUET)", [str(metadata)])

        con.execute("""CREATE TABLE comparison_rows AS
            SELECT r.cik::BIGINT cik, r.accessionNumber accession_number,
                   r.acceptanceDateTime zip_text, r.source_file
            FROM read_parquet(?) r JOIN selected_blocks b ON r.source_file=b.source_file""", [str(raw)])
        items = []
        for block, cik in con.execute("SELECT source_file,cik FROM selected_blocks ORDER BY source_file").fetchall():
            rows = con.execute("""SELECT cik,accession_number,zip_text FROM comparison_rows
                WHERE source_file=? AND cik=? ORDER BY accession_number""", [block, cik]).fetchall()
            items.append((block, cik, rows))
        existing = sorted(output.glob("fetch_results-*.parquet"))
        observations_parts = sorted(output.glob("observations-*.parquet"))
        previous = {}
        if existing:
            rows = con.execute("""SELECT block_name,count(*),arg_max(error,retrieved_at)
                FROM read_parquet(?) GROUP BY block_name""",
                [[str(p) for p in existing]]).fetchall()
            previous = {block: (attempts, error) for block, attempts, error in rows}
        pending = [item for item in items if item[0] not in previous or
                   (previous[item[0]][1] is not None and previous[item[0]][0] < 2)]
        limiter = NetworkRateLimiter(rate)
        number = max((int(p.stem.split("-")[-1]) for p in existing + observations_parts), default=0)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            queue = pending
            round_number = 0
            while queue:
                round_number += 1
                results = list(pool.map(lambda item: fetch_block(item, user_agent, limiter), queue))
                obs_rows = [row for observations, _ in results for row in observations]
                report_rows = [report for _, report in results]
                if obs_rows:
                    table = pa.table({
                        "source_url": [r[0] for r in obs_rows],
                        "accession_number": [r[1] for r in obs_rows],
                        "acceptance_datetime_text": [r[2] for r in obs_rows],
                        "retrieved_at": pa.array([datetime.now(timezone.utc)] * len(obs_rows), type=pa.timestamp("us", tz="UTC")),
                        "cik": [r[3] for r in obs_rows], "zip_text": [r[4] for r in obs_rows],
                        "source_file": [r[5] for r in obs_rows],
                    })
                    con.register("batch_observations", table)
                    number += 1
                    _save(con, "batch_observations", output / f"observations-{number:05d}.parquet")
                    con.unregister("batch_observations")
                con.execute("CREATE OR REPLACE TEMP TABLE batch_results(block_name VARCHAR,matched BIGINT,missing BIGINT,error VARCHAR,requests BIGINT,retrieved_at TIMESTAMPTZ)")
                con.executemany("INSERT INTO batch_results VALUES (?,?,?,?,?,?)",
                                [(*r, datetime.now(timezone.utc)) for r in report_rows])
                number += 1
                _save(con, "batch_results", output / f"fetch_results-{number:05d}.parquet")
                print(f"Live JSON attempt {round_number}: {len(results):,} blocks; elapsed={time.monotonic()-started:.1f}s", flush=True)
                queue = [item for item, (_, report) in zip(queue, results, strict=True)
                         if report[3] is not None
                         and previous.get(item[0], (0, None))[0] + round_number < 2]
                if queue:
                    time.sleep(5)

        parts = sorted(output.glob("observations-*.parquet"))
        if parts:
            con.execute("CREATE OR REPLACE TEMP TABLE all_observations AS SELECT * FROM read_parquet(?)",
                        [[str(p) for p in parts]])
            con.execute("COPY all_observations TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                        [str(output / "live_json_timestamp_observations.parquet")])
        reports = sorted(output.glob("fetch_results-*.parquet"))
        if reports:
            con.execute("""CREATE OR REPLACE TEMP TABLE all_fetch_results AS
                SELECT * FROM read_parquet(?)
                QUALIFY row_number() OVER(PARTITION BY block_name ORDER BY retrieved_at DESC)=1""",
                [[str(p) for p in reports]])
            con.execute("COPY all_fetch_results TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                        [str(output / "fetch_results.parquet")])
        print(f"Live JSON collection complete: {len(items):,} selected blocks; {len(parts):,} observation batches", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings", type=Path, required=True, help="Unresolved candidate Parquet")
    parser.add_argument("--raw", type=Path, required=True, help="Raw Parquet for the same ZIP snapshot")
    parser.add_argument("--output", type=Path, required=True, help="New observation directory; use --resume to continue")
    parser.add_argument("--since-date", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--sample-blocks", type=int, help="Optional reproducible block sample; default collects all")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rate", type=float, default=5, help="Maximum total SEC requests per second")
    parser.add_argument("--user-agent", help="Defaults to SEC_USER_AGENT")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    collect_live_json(args.filings, args.raw, args.output, args.since_date, args.sample_blocks,
                      args.seed, args.workers, args.rate, args.user_agent, args.resume)
