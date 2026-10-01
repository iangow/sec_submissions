# Get the data

The package downloads dated releases from the
[public data repository](https://github.com/iangow/sec_submissions_data).
The data files are not bundled into the Python package.

## Download a release

After [installing the package](index.md#get-the-data), run:

```sh
sec-submissions fetch-reference
```

This downloads the current corrected `filings.parquet`, supporting timestamp
observations, source metadata, and audit artifacts. It prints the local file
path. No GitHub login or SEC user agent is needed. Existing verified downloads
are reused; interrupted transfers resume automatically. Every file is checked
against the release's size and SHA-256 checksum.

The current release is resolved once, and all file URLs are then pinned to
that dated release. A new release appearing during the download cannot mix
files from two snapshots. For an analysis that should remain reproducible,
specify the version:

```sh
sec-submissions fetch-reference --version 2026-09-30 --companions
```

`--companions` adds the other five Parquet tables. You do not need to run the
processor, collect SEC evidence, or publish a local candidate after downloading.
The cached `filings.parquet` is ready for analysis, subject to the timestamp
limitations described below.

## What is included?

| File | Contents |
| --- | --- |
| `filings.parquet` | Filing records, time-zone-aware acceptance timestamps, and timestamp provenance |
| `companies.parquet` | Company metadata at the source snapshot |
| `addresses.parquet` | Business and mailing addresses |
| `tickers.parquet` | Tickers and exchanges at the source snapshot |
| `former_names.parquet` | Former names and their date ranges |
| `files.parquet` | References to historical filing files |

The last five files require `--companions`. The download also includes reusable
SGML and live-JSON observations, source metadata, and the sample identifiers,
row-level outcomes, and summary of the release's audit. The manifest records
checksums, the SEC source snapshot, and supported and unresolved row counts.

The data retain repeated appearances of an accession under different CIKs.
Company details and ticker mappings describe the downloaded snapshot, not
necessarily the company on each historical filing date. Date-only fields are
Parquet dates; `acceptanceDateTime` is a time-zone-aware instant.

### Timestamp status

Use `timestamp_provenance`, `timestamp_interpretation`, and
`timestamp_reference_id` to distinguish direct evidence, inferred conventions,
and unsupported timestamps. Rows marked `unresolved_raw_as_eastern` retain a
New York interpretation as a compatibility fallback; they are **not verified**.
Other unresolved categories are also not confirmations.

The [audit results](audit.md) describe what was checked for the September 30
release and what remains uncertain. The [timestamp explanation](timestamps.md)
describes the evidence behind each correction.

## Use the files

### R and DuckDB

The command above stores the pinned release under
`DATA_DIR/submissions/references/2026-09-30/`. With the default directories,
load it using `farr::load_parquet()`:

```r
library(DBI)
library(duckdb)
library(farr)

data_dir <- path.expand(Sys.getenv(
  "DATA_DIR", unset = "~/sec-submissions-data/pq_data"
))
reference_dir <- file.path(data_dir, "submissions", "references", "2026-09-30")
db <- dbConnect(duckdb())
dbExecute(db, "SET TimeZone = 'America/New_York'")
filings <- load_parquet(db, table = "filings", data_dir = reference_dir)
tickers <- load_parquet(db, table = "tickers", data_dir = reference_dir)
```

If you configured `DATA_DIR` in a `.env`, load that setting in R too, for
example with `readRenviron(".env")` before this code. Changing DuckDB's display
time zone does not change the stored instants. The
[dates-and-times note](https://iangow.github.io/notes/published/datetimes.html)
uses these two tables for an extended R example.

### Python

```python
from sec_submissions import fetch_reference

reference = fetch_reference(version="2026-09-30", companions=True)
print(reference.filings)
print(reference.directory / "tickers.parquet")
```

Use these local paths with DuckDB, Arrow, or another Parquet reader. The
function uses the same checked cache as the command-line interface.

## Local directories

No directory configuration is required. To check the resolved paths, run:

```sh
sec-submissions paths
```

| Setting | Contents | Default when unset |
| --- | --- | --- |
| `DATA_DIR` | Parquet tables, downloaded references, evidence, and audits | `~/sec-submissions-data/pq_data` |
| `RAW_DATA_DIR` | Original ZIP snapshots and download manifests, when preparing an update | `~/sec-submissions-data/raw_data` |

Each root contains a `submissions/` subdirectory. Downloaded references are kept
in `DATA_DIR/submissions/references/<release-version>/`.

To use existing data directories, set the roots in the working directory's
`.env`:

```dotenv
DATA_DIR=~/data/pq_data
RAW_DATA_DIR=~/data/raw_data
```

The package preserves values already set in the process environment. Explicit
path arguments take precedence. `--data-dir` overrides the Parquet root, and
`fetch-reference --output` selects a separate reference cache. Python functions
also accept `data_dir`; `data_directory()` exposes the resolved root.

SEC identification is needed only when downloading a new SEC snapshot or
collecting evidence, not when downloading the hosted release. Those operations
are described in the [advanced update workflow](workflow.md).
