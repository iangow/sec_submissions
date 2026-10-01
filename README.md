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
python -m pip install -e '.[dev,docs,audit]'
```

The intended distribution name is `sec-submissions`; import it as
`sec_submissions`. After a PyPI release, users can install the package with
`python -m pip install 'sec-submissions[audit]'`.

## Workflow

See the [documentation site](https://iangow.github.io/sec_submissions/) for
installation, the update workflow, API reference, and audit interpretation.
