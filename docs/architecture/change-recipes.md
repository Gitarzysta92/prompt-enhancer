# Change recipes and ownership

Read `AGENTS.md`, the atlas and the task's accepted baseline before editing.
Paths below are entry points; the catalog resolves their current publication
state. Do not copy an unpublished module piecemeal into a different baseline.

| Change | Start with | Follow through | Required evidence |
| --- | --- | --- | --- |
| Add a provider signal | `infrastructure/providers/`, `application/ingestion/` under `src/prompt_enhancer/` | Consent, supported provider/schema version, normalization, safe storage, API DTO, UI unknown state | Fictional version fixtures; read-only, redaction, duplicate and missing-field tests |
| Change a metric | `application/analysis/`, `metrics.py`, metric contract and definition registries | Opportunity/denominator, authority, provenance, aggregation, API, lens | Hand-computable fixtures, missing/zero distinction, storage/API/rendered agreement |
| Repair the live radar | Ensemble/watch routes and services; frontend `features/live-window/` and shared chart components | Selected-session identity, stale snapshots, cancellation, retry, measured coverage | Synthetic session switch/reconnect and failure cases, then qualified real-model/native evidence |
| Change Agent composition | `frontend/src/features/agent/`, `application/local_agent.py` | Draft/chat identity, runtime selection, streaming, cancel, durable store | Late reply and double-submit races; restart and keyboard/viewport journey |
| Add a workspace effect | Agent service/tool contracts, HTTP routes, `user_presence.py` | Exact reviewed action, workspace identity, current file revision, native authority, verified receipt | Reject/cancel/stale/path-escape tests and actual native approval |
| Add a model profile | Local-model services, provenance manifests, worker adapters | Immutable artifacts/license, preprocessing, placement, load peaks, bounded cleanup | Real inference for each advertised backend; resource measurement and unload |
| Add MCP support | Registry/management services, owned host, Agent MCP grants | Discovery is not trust; review/setup, tool discovery, revoke, outage cache, cleanup | Synthetic host lifecycle followed by declared native/packaged server qualification |
| Implement a workflow node | W01 contracts first, W02 private run engine, W03 adapters | Typed ports, explicit converters, immutable revision, resource lease, ordered events | Positive/negative matrix, reverse branch completion, failure/cancel/restart |
| Add a workflow view | W05 builder/list, Build/Run/Results, shared workflow API | Backend validation remains authoritative; no model execution inside renderers | Keyboard alternative, invalid-connection explanation, supported viewport journey |
| Change persistence | Specific application port + SQLite repository/migration | Schema compatibility, retention, recovery, transactional boundaries | Upgrade/restart/fault injection; no older binary on newer unsupported schema |
| Change update execution | `application/updates/`, `infrastructure/updates/`, update routes | Verified staged state, native consent, quiesce, journal, handoff/relaunch/recovery | Signed N-to-N+1 clean-machine journey, refusal/failure/retention tests |
| Change build/CI | `pyproject.toml`, locks, frontend package scripts, `.github/workflows/` | Dependency provenance, compiled resources, budgets, platform-owned tests | Locked clean build, privacy, relevant Linux/Windows gates; hosted check result |

## Collaborator lanes

The owner assigns an issue and allowed files before implementation. One lane can
work on UI states and accessibility using synthetic API fixtures. Another can
work on persistence/restart regressions. The owner/supervisor retains cross-lane
contracts, metrics authority, runtime ownership, approval, schema and release
decisions. A designer can propose layout and copy changes with synthetic data;
that does not authorize altering a metric's meaning or approval behavior.

Architecture changes are welcome from any collaborator. Include the affected
node IDs, before/after dependencies, evidence and trade-offs in an ADR proposal.
Only owner acceptance changes the architectural default. See
[ADR 0019](../adr/0019-owner-reviewed-architecture-and-contributions.md).

## A complete task card

```text
Task ID / atlas node IDs / beta gate:
Approved source baseline and dependency PRs:
Observable user outcome and current reproduction:
Allowed files and preserved contracts:
Implementation change:
Positive, negative, recovery and privacy checks:
Required evidence level and exact completion criterion:
Process/resource bound and correction attempts used:
Owner decisions still needed:
Result / source commit / artifact digest / cleanup:
```

## Git and CI flow

Fetch the approved baseline; create `feature/`, `fix/`, `docs/`, `test/`,
`refactor/`, `chore/`, `ci/` or `release/` branch. Preserve unrelated changes.
Run targeted checks, then the relevant integration gate. Review the staged diff,
privacy scan and public/noreply commit identity. Push the feature branch and
open a PR targeting `main`, following [collaboration workflow](../collaboration-workflow.md).
The owner reviews and merges. Contributors never self-merge or force-push main.

The current CI declares repository integrity, backend tests on Linux/Windows,
frontend tests/API/build/browser checks, and collaboration metadata validation.
Read the checked-out workflow for exact commands: the development tree includes
unpublished bundle-budget additions. A green local test is not a hosted CI pass.
A push to main does not itself build, sign or deliver a working app update.
Release publication remains a separate owner-controlled operation.
