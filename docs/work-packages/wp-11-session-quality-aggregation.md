# WP-11 selected-session quality aggregation

This slice adds a provider-neutral, application-layer read model for comparing
the latest completed Prompt Quality and Logic snapshots from 1–100 selected
sessions. It is intentionally separate from provider ingestion, HTTP routing,
and persistence.

The product composition exposes this core through authenticated
`POST /v1/quality-analysis/aggregate`. The selection stays in the request body,
not the URL; the response omits the selected identifiers. Project Prompt Quality
and Logic views call it once for the project-scoped indexed page. Projects above
the 100-session boundary are blocked instead of silently truncating a rollup.

## Safety boundary

- Input contains only bounded session pseudonyms.
- The service reads immutable local analysis records through
  `SessionAnalysisRunRepository`; it never reads a provider and never writes.
- Output contains counts, ratios, typed states, and versioned provenance only.
  It contains no selected session IDs, evidence references, labels, excerpts,
  paths, timestamps, request fingerprints, or input fingerprints.
- Missing runs and missing metric results stay explicit and cannot become zero.

## Aggregation semantics

Known fractions use ratio-of-sums:

`sum(fraction numerator) / sum(fraction denominator)`

The implementation never averages per-session percentages. Analysis coverage
uses the same denominator-safe rule over stored coverage counts:

`sum(observed count) / sum(eligible count)`

Fractions combine only when every compatibility field matches. The key covers
the named analysis profile and version, metric pack and version, provider and adapter versions, source/content
schemas, engine, redactor, model plan, persistence schema, metric identity and
semantics, algorithm, pinned model/tokenizer fields, prompt/rubric versions,
and metric schema. If a selection contains multiple keys, the combined metric
is `incompatible`; every cohort remains available as a content-free summary,
and no cohort is chosen as a winner.

When no compatible known fraction exists, a complete uniform set can retain a
defensible `not_applicable`, `abstained`, or `execution_error` state. Sparse or
mixed non-known input remains `unknown`.

## Verification

Focused synthetic tests cover selector bounds and duplicates, sparse and
partial history, typed non-known states, ratio-of-sums properties, summed
coverage, exact compatibility fields, full incompatible-cohort retention,
deterministic ordering, malformed duplicate stored results, and absence of
session/evidence identifiers in serialized output.
