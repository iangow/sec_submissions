# Data and local directories

The [public data repository](https://github.com/iangow/sec_submissions_data)
provides dated releases of corrected filings, reusable timestamp observations,
and audit results. The files are release assets; they are downloaded on demand
and are not included in the Python package.

## Start with the current reference

```sh
sec-submissions fetch-reference
```

This command downloads the current corrected `filings.parquet`, its SGML and
live-JSON observations, source metadata, and audit artifacts. It prints the
local reference path. No GitHub login or SEC user agent is needed. Existing
verified downloads are reused; interrupted transfers resume automatically.
Every file is checked against the release's size and SHA-256 checksum.

The current release is resolved once, and all file URLs are then pinned to
that dated release. Files from two snapshots cannot be mixed by a release
changing during the download. To reproduce a particular snapshot, use:

```sh
sec-submissions fetch-reference --version 2026-09-30
```

Add `--companions` to download `companies.parquet`, `addresses.parquet`,
`tickers.parquet`, `former_names.parquet`, and `files.parquet` as well. The
manifest records the SEC source snapshot, supported and unresolved row counts,
and the independent audit results. Unresolved timestamps remain explicitly
labelled; a successful download does not make those rows verified.

For analysis without the package, use the [current Parquet download](https://github.com/iangow/sec_submissions_data/releases/latest/download/filings.parquet)
or the [September 30, 2026 version](https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/filings.parquet).

## Directory conventions

The package follows the same repository-root convention as `dera.pq`:

| Setting | Contents | Default when unset |
| --- | --- | --- |
| `RAW_DATA_DIR` | Original ZIP snapshots and download manifests | `~/sec-submissions-data/raw_data` |
| `DATA_DIR` | Parquet tables, downloaded references, evidence, and audits | `~/sec-submissions-data/pq_data` |

Each root contains a `submissions/` subdirectory. Explicit path arguments take
precedence. Otherwise the package loads the working directory's `.env`, while
preserving any values already set in the process environment. For example:

```dotenv
RAW_DATA_DIR=~/data/raw_data
DATA_DIR=~/data/pq_data
SEC_USER_AGENT="Your Name your.email@example.org"
```

No `.env` is needed to use the default directories. To check the actual paths:

```sh
sec-submissions paths
```

Downloaded references are kept in
`DATA_DIR/submissions/references/<release-version>/`. ZIP files are stored as
`RAW_DATA_DIR/submissions/submissions-<retrieval-time>.zip`. Extracted tables,
candidates, and diagnostics are kept together under
`DATA_DIR/submissions/snapshots/<snapshot-name>/`. This keeps repeated updates
separate and lets extraction resume against the same ZIP.

The CLI options `--data-dir` and `--raw-data-dir` override the corresponding
roots. `fetch-reference --output` can also select a separate reference cache;
use explicit processor inputs for a cache outside the configured `DATA_DIR`.

## Update with defaults

After fetching a reference, these commands choose the latest local inputs and
create a fresh candidate on every processing run:

```sh
sec-submissions download
sec-submissions extract --max-seconds 0
sec-submissions process
```

SEC requests require an identifying user agent; the first terminal request
prompts if it has not already been configured. Downloading the hosted
reference does not contact the SEC.

`process` uses your local `DATA_DIR/submissions/filings.parquet` as the previous
release when it exists. Otherwise it uses the downloaded reference. It also
reuses the reference's observations and locally collected JSON/SGML evidence.
Independent audit observations are not automatically reused to process the
same candidate. Explicit `--previous`, `--cache-dir`, and observation paths
remain available for controlled runs.

The [update workflow](workflow.md) explains how to collect evidence for new
coverage and audit a candidate. To inspect the latest candidate with a fresh
sample, run `sec-submissions audit`; to install it after review, run
`sec-submissions publish`. The first publication creates
`DATA_DIR/submissions/filings.parquet`; later publications preserve the
existing file's identity and archive the preceding releases.

## Python

```python
from sec_submissions import fetch_reference, process

reference = fetch_reference()
print(reference.filings)

# After downloading and extracting a new SEC snapshot:
process()
```

Functions accept `data_dir` and, for ZIP operations, `raw_data_dir` overrides.
`data_directory()` and `raw_data_directory()` expose the resolved roots.
