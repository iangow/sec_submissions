"""Download and record an immutable SEC submissions ZIP snapshot."""

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
import urllib.request
import zipfile

import duckdb

from .http import resolve_user_agent

URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"


def download_submissions(output: str | Path, user_agent: str | None = None) -> Path:
    """Download a new submissions ZIP and write a Parquet source manifest.

    Args:
        output: New path for the ZIP. Existing snapshots are never overwritten.
        user_agent: Identifying SEC User-Agent, usually ``Name email@example.org``.

    Returns:
        The path to the downloaded ZIP.
    """
    output = Path(output).expanduser().resolve()
    user_agent = resolve_user_agent(user_agent)
    manifest = output.with_suffix(".manifest.parquet")
    partial = output.with_suffix(".partial.zip")
    if any(path.exists() for path in (output, manifest, partial)):
        raise FileExistsError("Use a fresh snapshot path; existing downloads are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    retrieved = datetime.now(timezone.utc)
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
    )
    hasher = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as destination:
            length = response.headers.get("Content-Length")
            expected = int(length) if length is not None else None
            modified, etag = response.headers.get("Last-Modified"), response.headers.get("ETag")
            print(f"Downloading {URL}; expected bytes={expected}; Last-Modified={modified}", flush=True)
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
                hasher.update(chunk)
                total += len(chunk)
                if total % (64 * 1024 * 1024) < 1024 * 1024:
                    print(f"{total / 1024**2:,.0f} MiB; {time.monotonic()-started:.1f}s", flush=True)
        if expected is not None and total != expected:
            raise ValueError(f"Incomplete download: {total} bytes; expected {expected}")
        with zipfile.ZipFile(partial) as archive:
            members = len(archive.infolist())
            if not any(name.startswith("CIK") and name.endswith(".json") for name in archive.namelist()):
                raise ValueError("Downloaded ZIP has no CIK JSON files")
        with duckdb.connect() as con:
            con.execute("""CREATE TABLE source(url VARCHAR,retrieved_at TIMESTAMPTZ,
                last_modified VARCHAR,etag VARCHAR,size_bytes BIGINT,sha256 VARCHAR,members BIGINT)""")
            con.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?)",
                        [URL, retrieved, modified, etag, total, hasher.hexdigest(), members])
            con.execute("COPY source TO ? (FORMAT PARQUET)", [str(manifest)])
        partial.rename(output)
        print(f"Saved {output}: {total:,} bytes; {members:,} members; SHA-256={hasher.hexdigest()}", flush=True)
        return output
    except BaseException:
        partial.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--user-agent", help="SEC User-Agent; defaults to SEC_USER_AGENT")
    args = parser.parse_args()
    download_submissions(args.output, args.user_agent)
