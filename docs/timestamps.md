# How the timestamps are fixed

This page explains the preparation of the published data. Start with
[getting the data](data.md) if you want to analyse the files, or the
[audit results](audit.md) for an assessment of timestamp quality.
You do not need to repeat these corrections to use a downloaded release.

## Why correction is necessary

In [an earlier note](https://iangow.github.io/notes/published/sec_submissions.html),
I described the SEC's submissions JSON and processed it using R. I switched
the bulk processing to Python for efficiency; the resulting Parquet files can
still be analysed using R and DuckDB.

Since that note was written, newer submissions data have been found to mix UTC
and New York local-clock acceptance times, even when both texts end in `Z`.
Neither that suffix nor the apparent time of day reliably identifies the
intended time zone. A UTC clock can fall within ordinary EDGAR hours and still
be misinterpreted as Eastern time.

The extractor therefore preserves the original `acceptanceDateTime` text in
`filings_raw.parquet`. The processor writes interpreted instants to a separate
`filings.parquet`, with columns recording how those instants were established.
Keeping these separate allows the interpretation to improve without losing
the source text or extracting the JSON archive again.

## Use accession-level evidence

The unit of correction is the **accession number**. The same filing may appear
under more than one CIK, but those appearances should represent one acceptance
instant. An accepted correction is joined to every occurrence of that
accession. A rule for an entire archived CIK file is insufficient because its
timestamps can have mixed interpretations.

### Previously established instants

Our original analysis had a useful starting point: the May 2024 archive used
a consistent New York local-clock convention. The first update compared a
Parquet reference derived from that archive with the ZIP downloaded on
September 5, 2026. Duplicate-accession comparisons, live JSON, and selected
SGML headers supplied further evidence. That ZIP contained 27,209,834 filing
rows, with filings dated through September 4.

The second update began with the corrected September 5 Parquet and processed
the September 30 ZIP. The released file has 27,272,863 rows; its source ZIP
was retrieved on September 30 at 13:39 UTC and had an HTTP modification time
of 12:34:49 UTC that day. The release manifest records the source and output
checksums.

Readers can use the corrected September 30 reference for their next update
without repeating either historical preparation. Thereafter their own prior
corrected Parquet can provide the reference; the earlier ZIP need not be
reprocessed to carry established instants forward.

Only supported prior instants can act as anchors. Usable prior rows for an
accession must agree on one instant, and interpreting the new raw clock as
UTC or `America/New_York` must reproduce it. An unresolved fallback is not an
anchor, although its reconstructed source clock may supply one member of a
new exact clock pair. Non-timestamp fields come from the new archive.

### Differing clocks for the same accession

Duplicate rows, prior snapshots, and live JSON may supply two distinct clocks
for one accession. The useful case has exactly two valid clocks that resolve
to one instant when the earlier is interpreted as `America/New_York` and the
later as UTC. For example, 08:01:07 in New York on a December date and
13:01:07 UTC on that date describe the same instant.

The package tests equality using named time zones, accounting for daylight
saving and changes of date. A difference of four or five hours alone is
insufficient. Neither the newer snapshot nor live JSON is assumed to supply
the UTC member. Equal clocks provide no new timezone evidence, and unexplained
differences remain in diagnostics. Outside-hours status is not required.

### Direct SGML observations

A filing header's `<ACCEPTANCE-DATETIME>` provides accession-level evidence,
interpreted here as a New York local clock and converted using
`America/New_York`. Exact SGML observations take priority over weaker
file-level inference; disagreements remain visible in the diagnostics.

Missing timestamp tags and failed requests are retained separately. Transient
failures can be retried; a missing tag is unavailable evidence, not confirmation
of either time zone. Literal midnight is a useful diagnostic, not a sufficient
rule for declaring a timestamp missing.

## Live-file inference

One live JSON response can supply clocks for many accessions. Where direct
comparisons cannot resolve an accession, supported prior instants, exact clock
pairs, and SGML observations can anchor the interpretation of that response.
If all available anchors agree, the processor can apply the inferred convention
to its other observed clocks.

This assumes that the response uses a common convention; it is not direct
evidence for every accession. The processor records its anchors and rejects
contradictory evidence. A response version is identified by source URL and
retrieval time: a later response from the same URL may use a different
convention. The inference is not applied indiscriminately to the archived ZIP
or to future filings that were not observed in that response.

An established accession instant can usually be reused if the new raw clock
reproduces it. This saves work in subsequent updates but does not imply that
all new filings for an earlier CIK use the same time zone.

## Selecting additional checks

The initial candidate identifies gaps in the available evidence. Screening
unresolved recent filings is preferable to looking only outside EDGAR hours,
because an incorrectly interpreted UTC clock need not fall outside that window.
Live JSON comparisons should precede a large SGML queue: one response can
resolve many accessions and provide anchors for further inference.

Remaining questions include missing live matches, contradictory evidence, and
live response versions without anchors. For the September 30 update, the
follow-up checked one accession in single-accession response versions and the
first and last accessions in multi-accession versions. Of 23,906 queued
accessions, 23,905 supplied a timestamp tag and one returned 404. These selected
checks support file-level inference only under its common-convention assumption;
they do not substitute for the independent probability-sample audit.

`EFFECT` was excluded from the outside-hours screen. The targeted anchor
collection also excluded `CORRESP`, `UPLOAD`, and `DRSLTR`. These forms can
still participate in exact clock-pair comparisons and the random audit; their
names or a global date cutoff should not determine their time zone.

## Preserve uncertainty and provenance

The released file records `timestamp_provenance`, `timestamp_reference_id`,
and `timestamp_interpretation`. For example, `sgml` denotes direct header
evidence and `live_file_inferred` an inferred response convention. Rows without
an accepted instant retain an Eastern interpretation labelled
`unresolved_raw_as_eastern`: a compatibility fallback, not a verified timestamp.

The main Parquet carries established instants and their status into a later
update. Separate observations retain source clocks, retrieval versions, failed
attempts, and evidence for accessions absent from a later snapshot. Diagnostics
record inputs, support counts, rejected evidence, and disagreements. A temporary
DuckDB database performs the computation; it is removed after the candidate
and Parquet diagnostics are exported.

Request completion, evidence-supported coverage, and an accuracy estimate are
different things. The [audit results](audit.md) assess a frozen candidate with
a fresh probability sample rather than treating successful collection as
proof of correctness. The [advanced workflow](workflow.md) gives the commands
for readers who want to prepare their own update.
