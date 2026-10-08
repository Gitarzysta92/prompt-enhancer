# Checkpoint Agent-08e handoff

Date: 2026-08-27
Status: implementation and synthetic validation complete; native execution deliberately not run

## Outcome

Agent-08e adds a guarded native acceptance harness and freezes the
legacy-retirement parity ledger. It does not start the desktop app, a server, a
model, a terminal, a command worker, or a GPU workload.

The ledger is truthful rather than ceremonial: fourteen of sixteen capability
groups are implemented, session branching/forking is missing, and the separate
native chat window remains partially blocked by its lifecycle issue. Legacy
retirement is therefore still forbidden.

## Native owner gate

`POST /v1/diagnostics/agent-native-acceptance/start` remains outside the
controller authority surface. It requires local authentication, same-origin
CSRF proof, and the owned native user-presence bridge. Its strict no-store
receipt contains no ID, timestamp, model, project, session, path, prompt, or
content. It proves only that native owner presence was confirmed and that the
gate itself requested no model execution, process spawn, workspace access, or
content persistence.

The frontend rejects additional or contradictory receipt fields. A normal
browser cannot arm the guide, and controller/API-token clients cannot use the
native presence credential.

## Acceptance card

The card is nested under **Connections & controller API → Owner acceptance**
and is closed by default. It can only:

- arm the page-local run after native confirmation;
- read the strict shared-runtime coordinator;
- inspect already-delivered strict turn summaries;
- perform one read-only strict change-set check while Files & review is open;
- clear its in-memory receipt.

It cannot start/stop a runtime, send a message, access file content, approve a
mutation, write, run a command, fetch a page, or retry automatically. The clean
baseline, served revision, completed turn, stopped turn, review contract,
context truth, later unload, confirmed process exit, and CPU/measured-GPU
cleanup are separate phases. Unknown cleanup and cross-session evidence fail
closed.

## Evidence

- Backend hardening/OpenAPI: 13 passed.
- Broad Agent, project/session, workspace, model-adapter, artifact, attachment,
  controller, and OpenAPI gate: 520 passed, 1 expected Windows symlink skip.
- Acceptance parser, state machine, layout, page integration, and HTTP transport:
  288 passed.
- Full frontend unit/component gate: 2,021 passed across 152 files.
- Full synthetic browser gate: 113 passed.
- Dedicated lifecycle cases cover inert render, native refusal, clean CPU
  success, measured GPU success, unknown GPU cleanup, interrupted observation,
  cross-session refusal, and page-local clearing.
- Production frontend build: 532 modules transformed.
- Generated OpenAPI export and TypeScript contract check: passed. The final gate
  detected and regenerated one stale schema artifact before closing.
- Python package compilation and `git diff --check`: passed.
- The privacy scanner reports only the pre-existing untracked binary screenshot
  `docs/checkpoint-agent-02-shell.png`; Agent-08e adds no privacy finding. The
  screenshot was not changed, deleted, staged, or allowlisted.
- Final exact inventory: no Prompt Enhancer/model/test process and no listener on
  ports 8765 or 8766.
- No native app, Prompt Enhancer listener, local model, inference process, or
  GPU test was started by this checkpoint.

## Deferred owner checklist

Run this only after the native-window lifecycle repair:

1. Open one existing live Agent chat in the native desktop app.
2. Stop the shared runtime and open Owner acceptance.
3. Begin the guarded run and confirm the clean baseline.
4. Load one selected model using Model & context; check startup evidence.
5. Complete one response, then start another and press Stop response; check.
6. Open Files & review and check the read-only review contract.
7. Stop the shared model and check process/GPU cleanup.
8. Reload the app and verify retained versus metadata-only chat truth.

## Next checkpoint

Agent-08f should implement durable, revision-safe session branching/forking with
retention-aware history copy semantics, no approval or mutation-authority copy,
bounded transactions, controller coverage, and multi-angle tests. The native
separate-window repair follows as its own checkpoint.
