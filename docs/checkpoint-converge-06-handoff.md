# Converge-06 handoff — navigation hierarchy and metric presentation

Status: **Automated implementation complete; owner visual review pending**.
This handoff does not claim release completion, scientific validity or owner
acceptance.

Date: 2026-09-04
Scope: frontend navigation hierarchy, Data sources paging/disclosure and
truthful metric presentation.

## What changed

- Primary navigation now has three product-level groups: **Core** (Agent,
  Overview, Models), **Review** (imported Projects, Sessions, Data sources,
  Discovery, Reviewed tasks, Task flow, Analysis jobs), and **Labs** (Prompt
  check, Calibration, Methods & models, Team analytics preview, Social hub
  demo).
- Labs uses a native accessible disclosure, is collapsed by default, opens for
  an active Labs route, and preserves deliberate collapse plus desktop/mobile
  keyboard focus. Its copy states that Team and Social are previews, not
  released backends. Existing routes, deep links, active state, icons, update
  status and privacy footer remain in scope.
- Metric presentation now keeps the existing **39 operational/task definitions**
  separate from the **20/16/4 canonical presentation** (20 contracts, 16
  shipped paths and 4 provider-adapter gaps) and the **10 historical lexical
  rules**. This is a presentation correction, not new calculators, a
  calibration claim or scientific validation.
- Data sources now uses 12 projects per page, collapsed lazy session lists, 20 rows
  per expanded page, metadata-only search, accurate hidden selections, Clear
  selection, and transport-generation resets. These are bounded presentation
  and selection behaviors; no new calculators, adapters or scientific
  calibration claim is included.

## Evidence recorded

- Root calibration/gate/report/ratings matrix: **140/140 passed**.
- Terra final metric evidence: **69/69 frontend** and **35/35 backend contract**
  tests passed.
- Root LocalSources + ClaudeSource evidence: **26/26 passed**.
- Root's original App run had **117 passed and 3 failures**; those failures were
  resolved by the owning-file rerun at **25/25**. This is not a claim that a
  clean full 120-case rerun occurred.
- Root browser shell/research/metric-context/standalone evidence: **23/23**;
  whole-route accessibility: **20/20** across 320/360/768/1440, light/dark,
  keyboard, forced-colors and reduced-motion. Browser suites total **61
  distinct cases**; earlier Luna 2-case evidence is not counted again.
- Source-maintenance evidence: **2/2** at 360/1440, reported by Luna after
  root reviewed and tested the exact scope. Isolated strict fixture/spec
  TypeScript passed; production build and real-loopback: **16/16** with
  `listener_released=true`, `temporary_state_removed=true`,
  `model_runtimes_remaining=0`, `runtime_cleanup_confirmed=true`. API and
  privacy checks passed, including root's final post-docwrite rescan; normal
  git diff check passed; no listeners remained on the checked ports.

All evidence used synthetic fixtures and content-free diagnostics. No model was
consulted and no real provider data, real transcript, hardware, native client
or external client was used for this checkpoint. Converge-04 physical/native
evidence and Converge-05a/05b trusted-MCP and external-client owner runs remain
unchanged and pending.

## Workflow and boundaries

The user workflow for this checkpoint is explicit: root reads the code, assigns
bounded work, reviews the changes and independently validates the result; Terra
handles harder scoped work, while Luna handles easier scoped changes, tests and
docs. Root does not implement this packet. Existing privacy, scope, synthetic-
fixture, checkpoint and no-commit/push rules remain in force. No app restart or
reload was performed; app on port 8765 was not running when root checked. Nothing
was committed or pushed.

## Owner click-later checks

1. Review the Core / Review / Labs order at desktop width.
2. Open Labs, follow a Labs deep link, and verify the preview boundary copy.
3. Collapse Labs while its route is active, then reopen mobile navigation and
   verify the summary/current-route focus behavior.
4. Review Data sources paging, exact selection and missing metric statuses.
5. Review optional historical metrics only as explicitly non-canonical.

## Next safe checkpoint

Converge-07 — signed Windows updater, package staging/apply/relaunch/rollback
and final release evidence. It remains outstanding; this handoff does not
advance that checkpoint.
