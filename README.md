# SEC Submissions

Download SEC EDGAR submissions data as Parquet files for analysis in R, Python,
or DuckDB. Acceptance timestamps are time-zone-aware and retain their evidence
and unresolved status.

The package is under active development and is not yet published to PyPI.
Readers can download an audited data release without processing the SEC's ZIP
archive or collecting filing headers themselves.

## Install

```bash
python -m pip install 'sec-submissions @ git+https://github.com/iangow/sec_submissions.git'
```

The intended distribution name is `sec-submissions`; import it as
`sec_submissions`. Python 3.12 or later is required.

## Get the data

```bash
sec-submissions fetch-reference
```

For a reproducible snapshot, including companion tables such as tickers:

```bash
sec-submissions fetch-reference --version 2026-09-30 --companions
```

Downloads are verified against release checksums and cached locally. No account,
SEC user agent, or directory configuration is required. `DATA_DIR` can be set
in a local `.env` to use an existing Parquet repository; otherwise the package
uses `~/sec-submissions-data/pq_data`.

The documentation is organized around
[getting the data](https://iangow.github.io/sec_submissions/data/),
[audit results and limitations](https://iangow.github.io/sec_submissions/audit/),
and [how timestamps are fixed](https://iangow.github.io/sec_submissions/timestamps/).
Advanced update commands and maintainer release instructions are separate.
