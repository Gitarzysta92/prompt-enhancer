# ADR 0021: Evidence-bound architecture atlas

- Status: proposed documentation maintenance convention; owner review required.
- Date: 2026-10-08

## Context

README prose, early architecture proposals, current dirty source and main have
drifted. Collaborators need to locate features and understand dependencies without
mistaking code presence or test doubles for a completed product.

## Proposed decision

Maintain a structured, dated component atlas with stable IDs, source/test paths,
dependencies, four status colors, scope, evidence, gap and next action. Generate
the readable catalog and diagrams from the same data. Bind observations to
source hashes and the published reference. Keep PNGs for remote/mobile readers
and editable SVG/JSON for contributors.

The readiness matrix remains the sole acceptance ledger. The atlas is a derived
navigation/architecture snapshot; the execution journal is a handoff history.
Do not compute a beta-completion percentage from node colors. A ready pure
helper has a narrower evidence scope than a qualified native user journey.

Use green for bounded-ready, yellow for partial, red for absent and grey only
for deliberate mock/demo implementations. Required/experimental/deferred is a
separate dimension. Planned edges are labeled; dependencies do not assert an
implemented call path. Source-reference existence does not prove execution.

## Alternatives and consequences

A single huge diagram becomes unreadable; separate diagrams retain a small
system map and finer domain views. A hand-maintained README status table alone
duplicates the ledger and drifts. Generated diagrams still need human review of
edge meaning, labels and evidence; automation cannot decide readiness.

Add exact reviewed image hashes through the existing scanner mechanism. Never
add a general image exemption. Future changes update affected atlas nodes,
source bindings and acceptance evidence in the same reviewed PR.
