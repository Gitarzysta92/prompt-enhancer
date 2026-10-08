# WP-16 — Complete multi-project quality aggregation

## Status

Backend first slice implemented. Frontend selection and presentation are out of
scope for this work package.

## Purpose

Allow a local user to select multiple already-indexed projects and calculate
one compatibility-safe quality projection without reading a provider or
copying project/session identifiers into the response.

## Closed first-slice contract

- Endpoint: `POST /v1/quality-analysis/aggregate-projects`.
- Selection: 1–25 unique installation-local 64-hex project identifiers.
- Selection mode: `all_analyzed_work` only.
- Estimand: `per_eligible_opportunity`.
- Aggregation method: `ratio_of_sums`.
- Scope: every indexed session belonging to every selected project.
- Bound: at most 100 sessions across the complete selection.

Other estimands or weighting modes are rejected. The API does not approximate
equal-session, equal-project, standardized, ranked, or universal quality
scores.

## Fail-closed behavior

Project resolution is one bounded SQLite read. A 101-session sentinel detects
an oversized scope without counting or returning the complete match set, so the
application rejects:

- a missing selected project;
- a selected project with no indexed sessions;
- duplicate or malformed selectors;
- a selection containing more than 100 sessions; and
- any resolver or aggregate result that does not exactly match the complete
  selected scope.

There is no pagination or truncation fallback. No catalog/navigation route
invokes project aggregation or a provider adapter. Resolution and immutable-run
aggregation share one read transaction, and an internal selection fingerprint
must match before the result can leave the application service.

## Privacy boundary

The response exposes only:

- the selected project count;
- the closed selection mode, estimand, and aggregation method; and
- a strict public mirror of the content-free `SessionQualityAggregate`.

It contains no project/session identifiers, labels, evidence identifiers,
prompts, responses, excerpts, paths, or tool output. Raw provider/model/version
provenance is used by the core but replaced in the public mirror by a
deterministic 64-hex compatibility fingerprint. Compatibility, applicability,
missingness, `Unknown`, `Abstained`, and `Not applicable` behavior remain owned
by the existing session aggregation core. A missing analysis run remains
missing and is never converted to zero.

## Verification gates

- application contract and complete-scope invariant tests;
- SQLite bounded-query count and no-pagination tests;
- API authentication, fixed-error, canary, and identifier-absence tests;
- navigation non-execution test;
- OpenAPI bounds and response-surface tests; and
- repository privacy scan and full backend suite.
