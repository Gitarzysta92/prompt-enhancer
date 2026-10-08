# Checkpoint Agent-08f handoff

Date: 2026-08-27
Status: implementation and synthetic validation complete; native execution deliberately not run

## Outcome

Agent-08f adds durable, revision-safe Agent chat branching. A retained chat can
now be forked before its first turn, after any completed turn, or at the latest
completed turn. The new branch is an inactive local-history chat that can be
browsed immediately and resumed only through the existing recovery flow.

This closes session branching/forking in the legacy-parity ledger. Fifteen of
sixteen capability groups are now complete. The remaining partial capability is
the separate native chat window and its process/lifecycle ownership boundary.

## Durable branch contract

- The fork request binds the source project, source chat, catalog revision,
  history revision, branch point, destination project, title, and a 32-character
  idempotency key.
- A repeated identical request returns the same child. Reusing the key for a
  different request fails closed. Concurrent identical requests create one
  child.
- Branching runs in one bounded SQLite transaction. Stale revisions, invalid
  branch points, corrupt journals, invalid destinations, archived sources, and
  non-retained sources leave no partial chat or lineage row.
- The child receives only retained events through the selected settled turn.
  A later incomplete/interrupted tail is omitted rather than reported as a
  completed turn.
- Immutable attached media referenced by copied events is verified, copied,
  and remapped to the child. Staged media is not copied.
- Approval state, decisions, reusable mutation authority, pending tool state,
  workspace staging, change-set state, and artifact lineage are never copied.
- Lineage remains available after source-chat deletion and is validated against
  the child history counts, revisions, timestamp, and branch point.

## Controller and interface

`POST /v1/agent/projects/{project_id}/sessions/{session_id}/forks` is available
to the local authenticated UI and the provider-neutral controller token. The
response is private/no-store and contains the strict fork receipt plus the new
catalog record. It does not grant native presence or mutation authority.

The retained-history view exposes a labelled branch-point selector and **Fork
chat** action. The created branch opens as inactive retained history, carries a
lineage badge, and stays available in the project/chat rail. Ambiguous transport
failures reuse the exact pending idempotency key; a changed request receives a
new key.

The final browser pass found and repaired a layout regression caused by adding
the branch controls to a fixed-row grid. Retained history now uses one bounded
scroll flow, so branch controls, artifact actions, history, and footer cannot
overlap at desktop or 360 px.

## Verification receipts

- Fork/catalog/attachment backend focus: 28 passed.
- Controller, orchestration, route, and OpenAPI focus: 40 passed.
- Broad bounded backend release gate: 1,130 passed, with 2 expected Windows
  symlink skips.
- Focused retained-history browser gate: 4 passed at 1,440 px and 360 px.
- Complete frontend unit/component gate: 2,031 passed across 152 files.
- Complete synthetic browser gate: 115 passed.
- Production TypeScript/Vite build: 532 modules transformed.
- Generated OpenAPI/TypeScript parity, Python package compilation, and
  `git diff --check`: passed.
- A larger repository-wide Python run was attempted but was externally
  terminated near 26 percent without a pytest completion summary. It is not
  represented as a pass or failure; the bounded 1,130-test release gate above
  is the valid backend receipt.
- The privacy scanner still reports exactly the known pre-existing untracked
  binary `docs/checkpoint-agent-02-shell.png`. Agent-08f adds no privacy
  finding; that file was not changed, deleted, staged, ignored, or allowlisted.
- No native app, Prompt Enhancer listener, real local model, inference process,
  or GPU workload was started for this checkpoint. Browser checks used only the
  fictional synthetic fixture.

## Owner review later

1. Restart Prompt Enhancer normally and open one retained fictional chat.
2. Fork it at **Before the first turn**, then confirm the child has zero turns.
3. Fork it after a completed turn, then confirm later history is absent.
4. Restart again and confirm both branches remain under the project.
5. Resume one branch and confirm protected actions are off until explicitly
   revalidated.
6. Delete the source only after review, then confirm each child and its lineage
   remain readable.

## Next bounded slice

Agent-08g should repair and validate the separate native chat-window lifecycle:
one application owner, no duplicate listener or cleanup worker, deterministic
open/focus/close behavior, shared project/chat state, and clean shutdown without
visible terminal spawning. It must be implemented and tested synthetically
before any owner-run native/model acceptance.
