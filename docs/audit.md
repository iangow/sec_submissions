# Audit results

This page reports the assessment of the **September 30, 2026 data release**.
Readers can use these results without collecting filing headers themselves.
They describe a fixed file, not every subsequent SEC snapshot or package run.

## Results at a glance

| Measure | Result |
| --- | ---: |
| Released filing rows | 27,272,863 |
| Evidence-supported timestamps | 25,584,390 |
| Explicitly unresolved timestamps | 1,688,473 |
| Randomly sampled filing rows | 10,000 |
| Verifiable SGML references | 9,230 |
| Timestamp disagreements | **0** |
| Missing SGML timestamp tags | 770 |
| Remaining request failures | 0 |

Among verifiable rows, the one-sided 95% upper confidence bound on the error
rate is **0.0325%**. This is not a claim that all timestamps in the release
are verified or that unavailable references are correct.

All 770 unavailable references were filings dated 1994 through 2002 whose
headers lacked `<ACCEPTANCE-DATETIME>`. No missing tags were observed for 2003
onward in this sample. Crucially, **none of the 596 sampled unresolved
fallbacks was verifiable**, so the audit does not validate those rows.

For analysis that depends on precise acceptance times, keep this limitation
visible and distinguish unresolved rows using `timestamp_provenance`.
The [data guide](data.md#timestamp-status) explains the status columns.

## Results by evidence group

| Candidate evidence group | Sample rows | Verifiable | Disagreements |
| --- | ---: | ---: | ---: |
| Trusted 2024 snapshot | 6,702 | 6,695 | 0 |
| ZIP/live-JSON clock pairs | 1,446 | 1,445 | 0 |
| Live-file inference | 953 | 862 | 0 |
| Cross-CIK accession pairs | 173 | 99 | 0 |
| Direct SGML evidence | 129 | 129 | 0 |
| Snapshot-pair inference | 1 | 0 | n/a |
| Unresolved Eastern fallback | 596 | 0 | n/a |
| **Total** | **10,000** | **9,230** | **0** |

The [timestamp explanation](timestamps.md) describes these evidence groups.
Their sample sizes differ substantially; the overall confidence bound should
not be applied separately to each group.

## What was tested?

The audit drew a simple random sample of rows from the frozen corrected
candidate, using seeded reservoir sampling with seed `202609304`. It saved the
sample identifiers and predicted instants before fetching fresh SGML headers.
The population includes repeated appearances of an accession under different
CIKs; an accession-level accuracy estimate would answer a different question.
All form types were eligible.

The fetch queue deduplicated accessions, but the sample retained their sampled
row appearances. Predictions were compared with the header's timestamp
interpreted as a New York local clock, using `America/New_York` to convert it
to an instant. The audit did not change the candidate or its predictions.
Unavailable rows were not replaced by other draws, and request failures were
distinguished from missing tags and timestamp disagreements.

This tests agreement with SGML under that interpretation, not the independent
truth of every SEC source. Where an SGML observation already supported a
prediction, a fresh matching header checks application of that evidence rather
than independently proving the header's timezone convention. Consistent
live-file inference also relies on an assumption described in the
[timestamp explanation](timestamps.md#live-file-inference).

### Interpreting the confidence bound

With zero disagreements among $n$ verifiable observations, the one-sided 95%
binomial upper bound is

$$
p_U = 1 - 0.05^{1/n}.
$$

For $n = 9{,}230$, this is 0.0325%. For the small sampling fraction here,
the binomial bound is a conservative approximation for sampling rows without
replacement. The familiar approximation $3/n$ gives similar values: about
0.5% for 600 verifiable observations and 0.1% for 3,000.
With observed disagreements, an appropriate interval is needed rather than
only the sample percentage; [NIST describes exact binomial confidence
limits](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm).

The bound is conditional on having a verifiable reference. Missing references
are not randomly distributed over filing years and evidence groups, so this
result must not be presented as an error bound for the whole file.
Targeted checks of recent filings, suspicious clocks, or particular forms are
useful diagnostics but are not a substitute for the probability sample.

## Reproducibility artifacts

Download the fixed release with the package:

```sh
sec-submissions fetch-reference --version 2026-09-30
```

The reference directory includes `audit_sample.csv` (identifiers and frozen
predictions), `audit_outcomes.parquet` (row-level results),
`audit_summary.parquet`, and the release manifest. The manifest records the
candidate checksum and audit metadata. A seed alone is not sufficient to
reproduce this sample from a different candidate.

The [dated release](https://github.com/iangow/sec_submissions_data/releases/tag/2026-09-30)
also exposes the [sample identifiers](https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/audit_sample.csv)
and [row-level outcomes](https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/audit_outcomes.parquet)
for inspection. Later releases should carry their own independent audits,
while these dated artifacts remain available.

Readers preparing their own candidate can use the [update workflow](workflow.md#audit-the-candidate)
to repeat the assessment. If audit evidence is used to repair a candidate,
the revised candidate needs a new independent assessment.
