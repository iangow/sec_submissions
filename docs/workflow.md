# Prepare an update

This workflow is for readers who want to create a new corrected snapshot.
If you only need the published data, [download the release](data.md) and stop
there. The [timestamp explanation](timestamps.md) describes the evidence and
assumptions; the [audit page](audit.md) reports the assessment of the published
September 30 release.

Commands have defaults based on `RAW_DATA_DIR` and `DATA_DIR`, loaded from the
working directory's `.env` when present. Start with the [data and directory
guide](data.md) to download a reference and run an update without
path arguments. The explicit paths below show how each stage fits together.

Use separate, dated inputs and outputs. The processor never overwrites a
candidate or its diagnostics. SEC collection commands require a contact-bearing
user agent and save observations as Parquet, so a later run can reuse the same
evidence without refetching it.

## SEC request identification

Commands accept
`--user-agent`; otherwise they check `SEC_USER_AGENT`, `HTTP_USER_AGENT`, the
current project's `.env`, and `~/.config/sec-submissions/config.toml`. A
first-use terminal prompt asks for an identifying value containing an email
address and offers project, user, or session-only storage.

To configure the value ahead of time:

```sh
sec-submissions configure-user-agent
```

For non-interactive use, set `SEC_USER_AGENT` in the process environment or pass
`--user-agent 'Your Name your.email@example.org'` to a collection command. The
request-rate option is a maximum across concurrent workers; workers do not
override it.

## Download and extract

```sh
sec-submissions download data/submissions-2026-10-01.zip
sec-submissions extract data/submissions-2026-10-01.zip data/2026-10-01/filings_raw.parquet
```

Downloads are immutable: choose a new filename for each snapshot. Extraction
checkpoints automatically after about 150 seconds. Repeat the same command to
resume, or use `--max-seconds 0` to let extraction finish in one run. Companion
tables such as `companies.parquet` and `former_names.parquet` are written beside
the filings output, so use a separate extraction directory for each snapshot.
Their date fields are Parquet dates; the raw
`acceptanceDateTime` remains text.

## Create an initial candidate

Use the published corrected reference rather than repeating the historical
2024 bootstrap. In this explicit-path example, first download it into a
reference cache:

```sh
sec-submissions fetch-reference --version 2026-09-30 --output data/references
```

Process the new snapshot to create a baseline candidate:

```sh
sec-submissions process \
  --raw data/2026-10-01/filings_raw.parquet \
  --previous data/references/2026-09-30/filings.parquet \
  --sgml-observations data/references/2026-09-30/sgml_observations.parquet \
  --live-observations data/references/2026-09-30/live_json_timestamp_observations.parquet \
  --output data/filings_candidate_01.parquet
```

This compares current clocks with the previous corrected file and within-snapshot
duplicate accession clocks. It also creates a `filings_candidate_01_checks/`
directory containing diagnostics. The processor uses a temporary DuckDB
database and removes it at the end. Explicit `--previous` inputs require
explicit observation paths if those observations are to be reused.

With the default layout, the shorter `sec-submissions process` chooses the
latest extracted raw file, uses the local current Parquet when present or the
downloaded reference otherwise, and includes saved reference and collection
observations. It never fetches new SEC evidence by itself.

## Collect live JSON evidence

The live collector chooses blocks containing recent unresolved rows from the
candidate and fetches all matching raw filing rows in each chosen block. Those
additional rows provide anchors for checking whether a live response has one
consistent interpretation. Use `--sample-blocks` for a trial; omit it to
collect all qualifying blocks. The selected block set is frozen in the output
directory, and `--resume` continues an interrupted run using the same inputs
and settings.

```sh
sec-submissions collect-live-json \
  --filings data/filings_candidate_01.parquet \
  --raw data/2026-10-01/filings_raw.parquet \
  --output data/evidence/live-json \
  --since-date 2024-01-01 \
  --sample-blocks 200 \
  --workers 8 --rate 5
```

`--rate` limits total HTTP requests per second across workers. The collector
also searches linked historical JSON when the selected CIK file lacks an
accession. It writes `live_json_timestamp_observations.parquet` and fetch
diagnostics. Do not interpret an unchanged ZIP/live clock as timezone evidence.

## Collect exact SGML observations

SGML fetching accepts an explicit queue with `cik` and `accession_number`
columns. Build that queue from the unresolved cases you have chosen to check;
this makes the scope of requests visible before collection. For example, an
analysis can first produce `sgml_queue.parquet`, then run:

```sh
sec-submissions collect-sgml \
  --queue data/sgml_queue.parquet \
  --output data/evidence/sgml \
  --workers 8 --rate 5
```

Every response, including missing timestamp tags and errors, is recorded. Only
transient errors are retried. The command produces
`sgml_observations.parquet`, which can be passed to the correction run. An SGML
`ACCEPTANCE-DATETIME` value is treated as a New York local clock only when
interpreting that observation; it remains provenance-bearing evidence, not an
unqualified string replacement.

## Reprocess with evidence

Use a fresh output path for each iteration:

```sh
sec-submissions process \
  --raw data/2026-10-01/filings_raw.parquet \
  --previous data/references/2026-09-30/filings.parquet \
  --output data/filings_candidate_02.parquet \
  --live-observations data/references/2026-09-30/live_json_timestamp_observations.parquet \
  --sgml-observations data/references/2026-09-30/sgml_observations.parquet \
  --live-observations data/evidence/live-json/live_json_timestamp_observations.parquet \
  --sgml-observations data/evidence/sgml/sgml_observations.parquet
```

The processor retains disagreements in diagnostics, gives exact SGML evidence
priority over file-level inference, and writes a separate candidate. Remaining
fallback rows are still marked `unresolved_raw_as_eastern`; inspect the
diagnostics and targeted queues before treating those as accepted timestamps.

## Audit the candidate

An audit freezes a random sample before fetching headers and never changes
predictions. Its output includes the sample identifiers, row-level outcomes,
unavailable cases, and a one-sided 95% upper error bound among verifiable rows.
Missing tags and request failures are reported separately from timestamp
disagreements. Install the `audit` extra to calculate the bound:

```sh
python -m pip install 'sec-submissions[audit] @ git+https://github.com/iangow/sec_submissions.git'
```

```sh
sec-submissions audit \
  --filings data/filings_candidate_02.parquet \
  --output data/audits/2026-10-01 \
  --sample-size 10000 --seed 20261001 \
  --workers 8 --rate 5
```

Use `--resume` only with the same candidate, sample size, and seed. The sample
identifier CSV is retained as a separate reproducibility artifact. Do not use
the audit to repair the candidate and then report the same sample as an
independent assessment. The [audit page](audit.md) explains the interpretation
of unavailable cases and confidence bounds.

The candidate itself is ready to load into a Parquet reader after review; no
publication command is required to analyse it. Local current-file installation
and preparation of public GitHub data releases are described in the
[maintainer notes](releases.md).
