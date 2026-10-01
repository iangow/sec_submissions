"""Prepare immutable data-release assets from an audited candidate and its inputs."""

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import shutil

import duckdb

from sec_submissions.reference_data import validate_manifest
from sec_submissions._util import sql_string


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def serializable(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def row_dict(con, path):
    cursor = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
    names = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one metadata row: {path}")
    return {key: serializable(value) for key, value in zip(names, rows[0], strict=True)}


def prepare(args):
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("Choose a fresh release staging directory")
    candidate_checksum = checksum(args.filings)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=2; SET memory_limit='4GB'")
        audit_metadata = row_dict(con, args.audit_dir / "metadata.parquet")
        if audit_metadata["sha256"] != candidate_checksum:
            raise ValueError("The audit does not describe the candidate's bytes")
        audit_metadata.pop("filings", None)
        audit_metadata.pop("mtime_ns", None)
        audit_summary = row_dict(con, args.audit_dir / "summary.parquet")
        source = row_dict(con, args.source_manifest)
        schema = dict((row[0], row[1]) for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(args.filings)]).fetchall())
        if schema.get("acceptanceDateTime") != "TIMESTAMP WITH TIME ZONE" or "timestamp_provenance" not in schema:
            raise ValueError("Release requires timezone-aware timestamps and provenance")
        rows, unresolved, missing_provenance = con.execute("""SELECT count(*),
            count(*) FILTER(WHERE starts_with(timestamp_provenance,'unresolved')),
            count(*) FILTER(WHERE timestamp_provenance IS NULL)
            FROM read_parquet(?)""", [str(args.filings)]).fetchone()
        if missing_provenance or rows != audit_metadata["population_n"]:
            raise ValueError("Candidate population/provenance does not match the audit")
        inputs = con.execute("SELECT role,path,size_bytes,mtime_ns FROM read_parquet(?)",
                             [str(args.checks_dir / "inputs.parquet")]).fetchall()
        sgml, live = set(), set()
        for role, filename, size, modified in inputs:
            path = Path(filename)
            stat = path.stat()
            if stat.st_size != size or stat.st_mtime_ns != modified:
                raise ValueError(f"An input changed since processing: {path}")
            if role == "sgml_observations.parquet" or role.startswith("sgml:"):
                sgml.add(path)
            if role == "live_json_timestamp_observations.parquet" or role.startswith("live:"):
                live.add(path)
        # The independent audit remains a separate outcome artifact. Its fresh
        # observations may now also be carried forward as evidence for future updates.
        sgml.update(args.audit_dir.glob("observations-*.parquet"))
        output.mkdir(parents=True)
        con.execute(f"SET temp_directory={sql_string(output / '.work')}")
        assets = []

        def register(name, role, optional=False):
            path = output / name
            size = path.stat().st_size
            if size >= 2 * 1024**3:
                raise ValueError(f"Asset exceeds GitHub's per-file limit: {name}")
            assets.append({"name": name, "role": role, "optional": optional,
                           "size_bytes": size, "sha256": checksum(path)})
            print(f"Prepared {name}: {size / 1024**2:,.1f} MiB", flush=True)

        shutil.copyfile(args.filings, output / "filings.parquet")
        register("filings.parquet", "filings")
        if assets[-1]["sha256"] != candidate_checksum:
            raise ValueError("Staged candidate checksum changed")
        for name, role, sources, projection in (
            ("sgml_observations.parquet", "sgml", sgml,
             "accession_number,acceptance_datetime,error,source_url,retrieved_at"),
            ("live_json_timestamp_observations.parquet", "live", live,
             "source_url,accession_number,acceptance_datetime_text,retrieved_at"),
        ):
            if not sources:
                continue
            con.execute(f"CREATE OR REPLACE TEMP TABLE observations AS SELECT DISTINCT {projection} FROM read_parquet(?,union_by_name=true)",
                        [[str(p) for p in sorted(sources)]])
            con.execute("COPY observations TO ? (FORMAT PARQUET,COMPRESSION ZSTD)", [str(output / name)])
            register(name, role)
        for source_name, target_name, role in (
            ("sample_identifiers.csv", "audit_sample.csv", "audit_sample"),
            ("outcomes.parquet", "audit_outcomes.parquet", "audit_outcomes"),
            ("summary.parquet", "audit_summary.parquet", "audit_summary"),
        ):
            shutil.copyfile(args.audit_dir / source_name, output / target_name)
            register(target_name, role)
        shutil.copyfile(args.source_manifest, output / "source_manifest.parquet")
        register("source_manifest.parquet", "source")
        if args.companions_dir is not None:
            for table in ("companies", "addresses", "tickers", "former_names", "files"):
                name = table + ".parquet"
                shutil.copyfile(args.companions_dir / name, output / name)
                register(name, "companion", optional=True)
        manifest = {
            "schema_version": 1, "version": args.version,
            "snapshot_date": args.snapshot_date, "license": args.license,
            "description": "Corrected SEC submissions metadata with explicit timestamp provenance",
            "population": {"rows": rows, "supported_rows": rows - unresolved, "unresolved_rows": unresolved},
            "source": source, "audit": {**audit_metadata, **audit_summary},
            "evidence_note": "Audit observations were collected after freezing this candidate and are supplied for future updates. Unavailable headers are not confirmations.",
            "files": assets,
        }
        validate_manifest(manifest)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Release {args.version}: {rows:,} rows; {unresolved:,} unresolved; {output}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("filings", "checks-dir", "audit-dir", "source-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--companions-dir", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--license", default="CC-BY-4.0")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
