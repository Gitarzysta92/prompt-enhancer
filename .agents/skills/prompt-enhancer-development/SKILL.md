---
name: prompt-enhancer-development
description: Navigate and change Prompt Enhancer using its component atlas, evidence gates, privacy boundaries, and owner-reviewed Git workflow. Use for feature work, architecture review, metrics, Agent tooling, workflows, tests, or release preparation in this repository.
---

# Prompt Enhancer development

Read repository-root `AGENTS.md` first. Full paths beginning `src/`, `frontend/`,
`docs/`, `.agents/` or `.github/` resolve from the repository root. Short backend
paths in the routing list resolve under `src/prompt_enhancer/`. This skill supplies routing;
it does not authorize provider access, model downloads, execution, publication,
installation, signing, or a new product decision.

## Find the correct baseline and component

1. Inspect branch, HEAD and status without resetting or cleaning user changes.
2. Read `docs/architecture/README.md`, then the relevant rows in
   `docs/architecture/feature-catalog.md` and `atlas.json`.
3. Check the row's source-publication binding. The development observation may
   contain unpublished files absent from your checkout. Resolve the task's
   approved baseline before implementing; do not invent those dependencies.
4. Read the corresponding accepted ADR and gate in
   `docs/product-readiness-matrix-2026-09-12.md` and
   `docs/beta-acceptance-gates.md`. The atlas is a dated map, not a second ledger.

## Route the work

- Backend wiring: `src/prompt_enhancer/bootstrap.py` and HTTP composition.
- Provider/privacy: `infrastructure/providers/`, application ingestion,
  `privacy.py`; external provider sessions remain read-only and uninspected by
  development agents. Use synthetic fixtures.
- Metrics: `application/analysis/`, `metrics.py`, contracts, aggregation and
  evidence routes. Trace source → safe storage → calculation → API → rendered
  value. Keep unknown, zero, ineligible and failed distinct.
- Agent: `application/local_agent.py`, related extracted contracts/services,
  SQLite persistence, Agent routes and `frontend/src/features/agent/`.
  Native approval is not browser/API consent; artifacts require file evidence.
- Models/processes: local model and text-model infrastructure plus owned-process
  helpers. Catalog presence is not qualified inference or cleanup evidence.
- Workflows: consult W00–W08/WP01–WP08 and the atlas before assuming an engine
  exists. The metric DAG, project automation scheduler and prompt-check hook are
  different systems. Required workflows must share one engine across UI/headless.
- Updates/distribution: application/infrastructure updates, package scripts and
  native lifecycle. Verified metadata is not execution authority.
- UI: app route manifest → feature slice → shared API/platform/chart adapters.
  Read `docs/architecture/change-recipes.md` for cross-layer test obligations.

## Execute a bounded change

Use the existing task-card format in `docs/architecture/change-recipes.md`.
Inspect/reproduce the specific defect, implement the smallest coherent change,
and use the existing tests before introducing helpers. Preserve unrelated work.
Respect the task's process/time/resource limits and correction history.

Use tests with fictional data, isolated databases and owned processes. Keep
receipts outside the repository; report only content-free outcomes. Run targeted
checks then relevant integration. Do not repeat an unchanged timed-out suite or
raise its timeout without diagnosing it; preserve incremental outcomes.

The quality commands and platform responsibilities live in
`docs/ci-quality-gate.md` and `.github/workflows/quality-gate.yml`; verify them in
the selected baseline. Full release tests do not run after every documentation
change. Source/mock tests cannot satisfy native, real-model or clean-machine
gates. Do not loosen a failing gate.

## Review, record and collaborate

Use a feature branch and the PR conventions in `docs/collaboration-workflow.md`.
Before committing, inspect the actual staged diff, check public/noreply identity,
and run relevant tests plus `scripts/privacy_scan.py`. Stage only reviewed files.
Push only when authorized; never self-merge or force-push the primary branch.
The owner is the final reviewer and merge authority. Written policy and CI
metadata checks do not themselves enforce repository permissions.

Any collaborator may propose an architecture change with a new ADR. Record
context, options, consequences, affected atlas nodes and migration/tests. Keep
the proposal pending until owner acceptance; do not silently reverse an accepted
decision. Update the readiness ledger, journal, atlas and affected documentation
with exact evidence scope. A status color is never a release certificate.
