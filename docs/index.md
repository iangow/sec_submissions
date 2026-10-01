# SEC Submissions

Download SEC EDGAR submissions data as Parquet files for analysis in R, Python,
or DuckDB. The filings table includes time-zone-aware acceptance timestamps
and records the evidence used to interpret them.

You do not need to download the SEC's JSON archive, run timestamp corrections,
or repeat the audit to use the published data.

## Get the data

The package requires Python 3.12 or later and is not yet on PyPI. Install it
from GitHub:

```sh
python -m pip install 'sec-submissions @ git+https://github.com/iangow/sec_submissions.git'
sec-submissions fetch-reference
```

The download command prints the local path to `filings.parquet`. It also
downloads supporting observations and audit artifacts, checks the files
against the release's checksums, and reuses verified files on subsequent runs.
No account, SEC user agent, or directory configuration is needed.

For reproducible analysis, request a dated release and its companion tables:

```sh
sec-submissions fetch-reference --version 2026-09-30 --companions
```

The [data guide](data.md) explains where the files are stored, what they contain,
and how to load them in R or Python. Defaults work without a `.env` file.

## Can I rely on the timestamps?

The September 30, 2026 release contains **27,272,863 filing rows**. A fresh
10,000-row audit found **no disagreements among 9,230 verifiable timestamps**.
However, 770 sampled headers lacked timestamp tags, and the release contains
explicitly unresolved timestamps that the audit does not validate.

Read the [audit results](audit.md) for the evidence, confidence bound, and
limitations. For time-sensitive analysis, distinguish supported timestamps
from the labelled unresolved fallbacks.

## How are the timestamps fixed?

The SEC's submissions JSON can mix UTC and New York local-clock values even
when both end in `Z`. Corrections use comparisons across snapshots, duplicate
accessions, live JSON, and selected filing headers. They are attached to
accession numbers, with their provenance retained in the released file.

The [timestamp explanation](timestamps.md) describes this process and its
assumptions. The [update workflow](workflow.md) and [Python API](api.md) are for
readers who want to prepare their own updates. Preparing and uploading the
public data releases is covered separately in the [maintainer notes](releases.md).
