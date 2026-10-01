# Data release maintenance

These notes are for maintainers of the public data repository, not readers
who want to download and analyse the files. The normal reader workflow ends
with [downloading a release](data.md).

## Review the candidate

Use the [advanced workflow](workflow.md) to extract, correct, and independently
audit a new snapshot. Retain the source manifest, candidate diagnostics,
observation inputs, and frozen audit artifacts. Review row counts, schema,
unresolved coverage, disagreements, and unavailable references before release.

An audit used to change the candidate cannot also serve as the independent
assessment of the revised candidate. Freeze and audit the revised file again.
Do not modify processing inputs while staging a release.

## Stage public assets

The repository's
[release preparation script](https://github.com/iangow/sec_submissions/blob/main/maintainers/prepare_data_release.py)
creates the checksum manifest and assets for the separate
[data repository](https://github.com/iangow/sec_submissions_data). It is a
maintainer tool, not part of the installed command-line interface. For example,
from a package repository checkout:

```sh
python maintainers/prepare_data_release.py \
  --filings data/filings_candidate_02.parquet \
  --checks-dir data/filings_candidate_02_checks \
  --audit-dir data/audits/2026-10-01 \
  --source-manifest data/submissions-2026-10-01.manifest.parquet \
  --companions-dir data/2026-10-01 \
  --version 2026-10-01 --snapshot-date 2026-10-01 \
  --output data/release-2026-10-01
```

Choose a fresh staging directory. The source manifest sits beside the ZIP,
with its `.zip` suffix replaced by `.manifest.parquet`. The script checks that
the audit describes the candidate's bytes and population, that timestamps are time-zone-aware and
have provenance, and that processing inputs have not changed. It combines
reusable observations, retains audit outcomes separately, and checks asset
sizes and the manifest. Audit observations are supplied as evidence for future
updates, not retroactively applied to the frozen candidate they assessed.

## Publish to GitHub Releases

1. Create a dated **draft** release in `iangow/sec_submissions_data`.
2. Upload the complete staged asset set, including `manifest.json` and the
   companion tables from the same snapshot.
3. Check asset names, sizes, checksums, source identity, and audit metadata
   against the staging directory. Check the release's licensing information.
4. Make the validated release public, then test
   `sec-submissions fetch-reference --version <version> --companions` from a
   clean cache without GitHub authentication. Check the current-release route
   too, and update the release-specific audit documentation.

Keep dated releases available for reproducible analysis. `fetch-reference`
resolves the current release once and downloads from that dated version, so
an update during collection cannot mix assets from two releases. Publishing
data here does not publish the Python package to PyPI.

## Install a local current file

The package command named `publish` **does not upload a GitHub release**. It
installs a reviewed candidate as a local current Parquet file. This is useful
for maintaining a local pipeline but is not a prerequisite for using downloaded
data or an explicit candidate path.

```sh
sec-submissions publish \
  --candidate data/filings_candidate_02.parquet \
  --current data/filings.parquet
```

The first installation creates the current file. On later installations the
command backs up the current file as `filings_previous.parquet`, archives an
older previous file, validates the copied bytes, and restores the current
bytes if a write fails. It preserves the existing file's local identity.
The in-place write is not atomic for concurrent readers; wait for completion
before opening the updated file.

## Documentation and development

From a local checkout, install the development, documentation, and audit tools:

```sh
python -m pip install -e '.[dev,docs,audit]'
pytest
mkdocs build --strict
```

Documentation changes on the package's main branch deploy to GitHub Pages.
Package distribution and data publication are separate operations.
