# SEC Submissions

`sec-submissions` turns SEC EDGAR's submissions archive into raw and corrected
Parquet files. The original `acceptanceDateTime` text is preserved in the raw
file; the corrected file records a time-zone-aware instant and the provenance
used to establish it.

Timestamp meaning is not assumed from the trailing `Z`, a filing's time of day,
or a CIK-wide convention. Corrections are attached to accession numbers and
require supported comparisons or observations. Unsupported rows remain labelled
as unresolved; they are not silently promoted to evidence.

## Install

The package has not yet been published to PyPI. Install the current GitHub
version with:

```sh
python -m pip install 'sec-submissions[audit] @ git+https://github.com/iangow/sec_submissions.git'
```

From a local clone, install the development tools with:

```sh
python -m pip install -e '.[dev,docs,audit]'
```

After a PyPI release, the intended end-user installation is:

```sh
python -m pip install 'sec-submissions[audit]'
```

The `audit` extra installs SciPy for the one-sided confidence bound. Core
extraction and correction do not require it.

## Process outline

Start with `sec-submissions fetch-reference` to download the current corrected
Parquet, supporting observations, and audit results. The [data and directory
guide](data.md) documents downloads, versions, `RAW_DATA_DIR`, `DATA_DIR`, and
local `.env` configuration. Defaults work without configuring either directory.

1. Download a dated `submissions.zip` and extract the JSON files into raw Parquet
   tables.
2. Start with a corrected prior Parquet release. For an initial update, create
   the 2024 Eastern-clock bootstrap reference once.
3. Apply accession-pair evidence, then collect live JSON observations for
   unresolved blocks and SGML observations for a deliberately selected queue.
4. Re-run the processor to write a new candidate and diagnostics.
5. Freeze and audit a probability sample against SGML before publishing.

The [update workflow](workflow.md) documents the commands and the evidence
boundaries. All work files and network observations are explicit local paths;
the package does not assume Dropbox or modify an existing release except when
the user explicitly runs `publish`.

## SEC identification

SEC requests use an identifying user agent containing a contact email. Values
are resolved from an explicit argument, `SEC_USER_AGENT`, `HTTP_USER_AGENT`, a
project `.env`, or the user configuration file, in that order. If no valid
value is found in a terminal, the command prompts and offers to store it for the
project, for the user, or only for that run. See [configuration](workflow.md#sec-request-identification).
