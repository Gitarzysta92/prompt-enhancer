# Checkpoint Release-01a.2b handoff

Date: 2026-09-01

Status: automated complete; optional owner continuity review queued

Entry contract: [Release-01a.2b entry](checkpoint-release-01a-2b-entry.md)

## Outcome

Interrupted durable work now has an explicit, idempotent restart outcome. The
application no longer presents a published model download, reviewed artifact
projection, managed MCP call, or external-controller row as live or successful
without the evidence required by its subsystem.

This packet uses only synthetic fixtures. It did not load a model, use the GPU,
read provider transcripts, inspect credentials, invoke an MCP server, or make a
network request.

## Implemented recovery boundaries

- A download interrupted after verified registry publication but before ledger
  completion settles `completed` only when the registry record, immutable Hub
  provenance, GGUF metadata and final bytes match exactly.
- A conflicting download alias or final artifact settles `failed` with
  `download_registry_conflict`; the conflicting record and bytes are not
  overwritten or deleted.
- Artifact head/version projection has injectable transaction boundaries. An
  interrupted transaction rolls back; the reviewed history receipt replays the
  projection exactly once after restart. A post-commit interruption also stays
  exactly once.
- MCP package install/update/uninstall/rollback recovery retains its existing
  fail-closed `cleanup_required` behavior. In addition, a prior app run's
  one-use tool-call claim without a receipt receives one terminal content-free
  receipt. An approved call becomes `failed` / `mcp_tool_call_interrupted` with
  cleanup unverified; non-executing denial/timeout/cancellation truth is kept.
- Controller ownership is reconciled during production composition. Exact live
  local sessions may be preserved; every non-live submission state becomes
  `submission_uncertain`, every non-live stop state becomes
  `cleanup_unconfirmed`, and stale native approvals and handoffs are cleared.
- Both MCP-call and controller reconcilers run before a newly composed Agent can
  acquire current-run authority.

## Automated evidence

- Focused recovery gate: **249 passed**.
- Full backend gate: **5,215 passed, 9 expected Windows symlink skips, 0 failed**
  in 42 minutes 18 seconds.
- Frontend gate: **184 files / 2,723 tests passed**.
- Privacy/config gate: **37 passed** and `scripts/privacy_scan.py` passed.
- Production frontend build passed. Its pre-existing large Agent chunk warning
  remains visible and is not reclassified as a failure in this state-only slice.
- Python compilation passed for `src` and `tests`.

The focused interruption matrix covers exact download publication, registry and
byte conflicts, eight artifact transaction boundaries, all nine controller
states, live-session preservation, controller boot wiring, prior/current MCP
run scope, one-use approval outcomes, package lifecycle recovery and repeated
idempotent startup.

## Live reload evidence

- Health: `ok`; cost mode: `offline_only`; data tier: `metadata`.
- Listener census: exactly **1**, bound to `127.0.0.1:8765`.
- Model-process census: **0** `llama-server` processes.
- In-app browser reload: `/agent`, title `Agent · Prompt Enhancer`, document
  complete, one main landmark, no password input.
- No real project title, chat title, prompt, response, path, tool payload or
  credential was read or recorded during the browser check.

## Owner review later

This checkpoint is primarily recovery behavior and needs no destructive owner
click. During a later continuity review:

1. Leave a safe synthetic/local download paused, reload, and confirm it remains
   resumable rather than falsely complete.
2. Confirm an already completed exact download remains complete after reload.
3. Confirm a previously live external controller does not still claim a pending
   native approval after a genuine app restart.

The Models page now explains `download_registry_conflict` instead of presenting
an opaque failure.

## Explicit carry-forward

A direct detached `pythonw -m prompt_enhancer serve` probe exited before
readiness and left no listener or child behind. The normal virtual-environment
server restarted successfully without a visible terminal. Release-01a.3 must
resolve and test the complete detached/desktop process composition, repeated
start/stop/crash behavior and terminal-window census; this packet does not claim
that later boundary complete.

The owner has selected an intervening Agent composer checkpoint next: integrate
model selection, truthful context status, media controls and Send/Stop into the
chat composer, while moving secondary runtime controls out of the conversation
focus. Release-01a.3 remains next in the release-recovery sequence afterward.
