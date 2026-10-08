# MCP Store checkpoint 06e.3 handoff

Date: 2026-08-31
Status: automated implementation complete; owner visual/protected review pending
Runtime effect of the automated gate: synthetic in-memory MCP fixtures and a
read-only live Store reload only; no plan was changed, no host or model was
started, no MCP tool was called, and no protected authority was granted

## Outcome

An active Agent chat now has a compact **Project tools** card that reconciles
its exact durable project admission with current app-run MCP host state. The
card distinguishes admitted-but-stopped plans from actually ready tools and
fails closed when project identity, tool counts, binding revision or reviewed
tool identity disagree.

Opening the MCP Store from that card keeps the exact chat project selected.
Project and reviewed-tool reads have explicit retry paths, large tool sets can
be filtered and selected deliberately, and an unchanged admission cannot be
submitted again. Store lifecycle, binding and runtime mutations invalidate the
chat projection so last-confirmed status is re-read.

## Changed

- Added a compact, responsive active-chat MCP projection with admitted-plan,
  ready-host, ready-tool and stopped-plan counts plus at most six exact aliases.
- The projection never starts a host and labels itself as last-confirmed state;
  every message/call still revalidates current project and exact authority.
- Wrong-project tools, contradictory runtime counts, unknown projections and
  durable/runtime drift hide ready tools rather than presenting stale access.
- **Manage in MCP Store** opens the focused Store workspace and carries the
  active chat's project identity into project admission.
- Project admission no longer falls back to the first project. A missing active
  project leaves the selector empty and explains the mismatch.
- Failed project and reviewed-tool reads expose bounded retry controls.
- Reviewed tools can be searched, selected by the visible subset and cleared;
  controls remain disabled without an explicit project.
- Exact no-op admissions are disabled as **Admission already current**.
- Managed host status, preview and runtime reads now reject wrong-scope or
  contradictory payloads at the component boundary in addition to strict
  transport parsing.
- Late start/stop responses cannot overwrite a newly selected project; start,
  stop and ambiguous failures still invalidate the global chat projection.
- Unhealthy and cleanup-required hosts remain truthful and cannot be mistaken
  for ready tool authority.
- Stabilized one unrelated model-ensemble authority-reset test discovered by
  the broad gate by flushing its existing React review-reset effect before the
  acknowledgement assertion. Production behavior was not changed.

## Automated evidence

- Focused Store, project-admission, managed-runtime and chat-projection suites:
  **47 passed / 4 files**.
- Complete Agent frontend feature suite: **497 passed / 30 files**.
- Agent layout contracts: **13 passed**.
- Strict managed MCP contracts/transports: **48 passed / 3 files**.
- Backend managed-runtime and management state machines: **92 passed**.
- Rendered active-chat-to-Store journeys at **360 px and 1440 px**: **2 passed**.
- Full frontend regression after repairing the discovered test race:
  **2,528 passed / 177 files**.
- Production TypeScript/Vite build: passed. The existing large-chunk advisory
  remains a non-failing Sweep-01c performance item.
- Repository privacy scanner: passed after final edits.

The first backend command used the system Python and stopped during collection
because that interpreter does not contain the repository's `mcp` dependency.
No test executed in that attempt. The exact suite was rerun with the workspace
virtual environment and passed 92/92.

All new fixtures use reserved fictional identities, paths, hosts and tool data.
No provider transcript, credential store, real workspace content, real MCP
package, model or GPU workload was read or invoked.

## Live read-only evidence

- The rebuilt Agent route reloaded at `127.0.0.1:8765` without restarting the
  service or opening a terminal.
- Agent settings opened directly into the rebuilt MCP Store; **24** live public
  Registry entries rendered with no protected interaction.
- Final process census: **1** listener at `127.0.0.1:8765`, loopback only,
  **0** listener descendants and **0** numeric GPU compute-memory contexts.

## Explicit red-evidence ledger

No Store-06e.3 automated gate remains red. The first full frontend run exposed
one timing-sensitive off-scope test; the missing effect flush was added, its
39-test file passed, and the full 2,528-test rerun passed.

The earlier broad legacy workflow ledger remains explicitly unresolved at
**66 passed / 16 failed** across unrelated duplicated non-Store scenarios at
two widths. It was not rerun or relabelled here. Its assertion reconciliation
remains assigned to Sweep-01a; the dedicated Store-06e.3 journeys and current
unit/integration gates are green.

## Still bounded

- Actual in-chat MCP call approval, ordered activity, cancellation and bounded
  result cards belong to Store-06e.4.
- Registry, icon, transport, process, schema, secret and cross-scope hostility
  belongs to Store-07.
- Real start/stop/tool-call clicks remain owner acceptance. Automation did not
  manufacture an admitted real host or native approval.
- A retained metadata-only chat has no live runtime card until it is resumed;
  the Store still receives that retained chat's project for management.

## Owner click-later ledger

1. Open or resume a durable project chat and expand **Project tools**.
2. Confirm admitted, ready and stopped counts match the trusted managed plans.
3. Select **Manage in MCP Store** and confirm the active project is preselected.
4. If separately trusted, start/stop one admitted host and verify chat status
   refreshes without a terminal window.
5. Switch to another project/chat and confirm no prior tool alias follows it.

## Next checkpoint

Store-06e.4 is active: finish the in-chat MCP call experience with concise
availability, exact per-call approval/activity/result cards, ordering,
cancellation, bounded evidence, accessibility and no chat overcrowding.
