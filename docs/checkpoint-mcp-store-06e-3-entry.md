# MCP Store checkpoint 06e.3 entry snapshot

Date: 2026-08-30
Status at entry: implementation active
Scope: project admission, permission, host-health and selected-tool
reconciliation between managed Store state and the active Agent chat

## Frozen user outcome

The active chat names its exact project MCP state without assuming authority:
which reviewed plans are admitted, which hosts are ready, and which exact tools
are currently available. Opening Store from that summary lands on the same
project. Project changes, tool-snapshot drift, host failure, unavailable reads
and cross-project switches remove stale tool claims immediately and provide a
clear recovery path.

## Authoritative entry findings

- The backend already persists exact project bindings and revalidates server,
  binding and tool-snapshot revisions before host start, runtime projection,
  model schema registration and every tool call.
- `project_tools()` omits any host whose durable authority changed. It never
  auto-starts a host or grants remembered call approval.
- Strict frontend contracts already reject malformed bindings, host status and
  project runtime projections.
- Runtime transport methods are missing from the narrowed `AgentPage` and
  `AgentMcpStorePanel` transport types even though the production HTTP transport
  implements them.
- Project admission exists only deep inside one managed plan. The active chat
  has no compact project-tool state or Store escape hatch.
- Store currently selects the first returned project implicitly. It does not
  prefer or identify the active chat project, and a missing project can silently
  fall through to another project.
- Project-list and exact-tool failures have no local retry. Tool selection has
  no filter or bounded bulk controls for a large reviewed snapshot.
- Saved binding and host start/stop mutations update the managed view but do not
  invalidate any active-chat MCP projection.
- The runtime panel cancels replaced reads, but its three focused tests do not
  cover project switches, late responses, binding revision drift, projection
  mismatch, unhealthy/cleanup states or recovery.

## Bounded implementation

- Add every existing managed-runtime method to the Agent and Store transport
  slices; do not invent a second authority path.
- Pass the active chat project into Store and never select a different project
  implicitly. Mark the exact active project and explain unavailable/archived
  context.
- Add retryable project and tool-snapshot reads, exact selection-change state,
  tool filtering and safe select-visible/clear controls.
- Add a compact active-chat project-tools surface that combines durable
  admissions with the current runtime projection, exposes only entries that
  still match an admitted tool ID, and treats any disagreement as stale.
- Refresh the chat projection after managed binding/lifecycle/host mutations and
  when the active project changes. Keep a manual retry for cross-window changes.
- Improve host-health/revision language without starting, stopping, probing or
  granting anything during reads.

## Explicit exclusions

- Actual in-chat MCP call approval, streaming activity and result cards belong
  to Store-06e.4.
- Registry, network, process, schema and secret hostility belongs to Store-07.
- No real project permission, host start, package, endpoint, model, tool call,
  credential or owner file is used by automated acceptance.

## Acceptance matrix

- active project present, absent, changed, archived/missing and cross-project;
- no plan, review-required, install-required, admitted/stopped and ready states;
- exact permission/tool selection, no-change state, filter and bulk controls;
- project/tool/runtime unavailable reads with local retry;
- aborted/late list and runtime responses after project or mutation changes;
- runtime tool not present in the current admitted binding is hidden and marks
  the projection stale;
- host ready, unhealthy, binding-changed and cleanup-required presentation;
- Store mutation invalidates the active-chat projection without granting tool
  authority;
- keyboard behavior and 360/1440 px rendered Store/chat journey;
- affected backend/frontend regression, strict contracts, production build,
  privacy scan, live loopback reload and zero-surprise-process census.
