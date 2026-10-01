# SEC Submissions

Python tools for downloading, extracting, correcting, auditing, and publishing
SEC EDGAR submissions data. The raw `acceptanceDateTime` text is preserved;
timestamp interpretations are evidence-based and retain provenance.

The package is under active development and is not yet published to PyPI. The
supported path starts with a `submissions.zip`, uses a preceding corrected
Parquet release and saved live-JSON/SGML observations, then creates and audits
a separate candidate. Nothing in the package updates a Dropbox-hosted file
automatically.

## Install

```bash
python -m pip install 'sec-submissions[audit] @ git+https://github.com/iangow/sec_submissions.git'
```

For local development:

```bash
python -m pip install -e '.[dev,docs,audit]'
```

The intended distribution name is `sec-submissions`; import it as
`sec_submissions`. After a PyPI release, users can install the package with
`python -m pip install 'sec-submissions[audit]'`.

## Workflow

```bash
sec-submissions fetch-reference
sec-submissions download
sec-submissions extract --max-seconds 0
sec-submissions process
```

`RAW_DATA_DIR` stores ZIP snapshots; `DATA_DIR` stores Parquet and supporting
evidence. Both can be set in a local `.env`; defaults work when neither is set.
Run `sec-submissions paths` to see the resolved directories. The downloadable
[data releases](https://github.com/iangow/sec_submissions_data/releases) include
checksums, timestamp provenance, and independent audit results.

See the [documentation site](https://iangow.github.io/sec_submissions/) for
installation, the update workflow, API reference, and audit interpretation.
