# Checkpoint Release-01a.3 handoff

Date: 2026-09-02

Status: automated complete; owner click-later review queued

Entry contract: [Release-01a.3 entry](checkpoint-release-01a-3-entry.md)

## Outcome

Prompt Enhancer now has one shared owned-process boundary for model, estimator,
schema, transport, session-link and compatibility helpers. Windows descendants
are placed atomically in a kill-on-close Job Object before execution; POSIX
descendants use an owned process group. Completion requires the root and tree,
pipes, reader threads and native handles to settle.

The checkpoint did not load a real model, occupy model VRAM, read provider
transcripts, inspect credentials, invoke a real MCP server or make a network
request. All command and protocol fixtures are synthetic.

## Implemented lifecycle boundaries

- The shared owner provides bounded stdin/stdout/stderr, finite process counts,
  content-free launch/timeout/cleanup failures and exact tree-exit evidence.
- Estimator runners, ensemble helpers, compatibility probes, evaluation jobs,
  Codex app-server transport/schema probes, session-link workers and short local
  runtime probes use that owner.
- The existing Windows command Job Object exposes cached return-code and
  independent output-capture contracts without keeping native handles open.
- A static source gate allows raw subprocess startup only inside the four
  reviewed ownership adapters and rejects `taskkill.exe` or a new-console flag.

## Automated evidence

- Focused process/model/helper matrix: **349 passed**.
- Desktop, listener, single-instance and liveness matrix: **90 passed**.
- Shared-owner/static-policy matrix: **10 passed**.
- Complete backend gate: **5,232 passed, 9 expected Windows symlink skips,
  0 failed** in 46 minutes 2 seconds.
- Complete frontend gate: **184 files / 2,733 tests passed** in 6 minutes 6
  seconds. A separate isolated Agent suite passed **165 tests**.
- Production frontend build and API compatibility check passed. The existing
  large Agent chunk advisory remains visible and is not reclassified as a
  failure by this lifecycle-only checkpoint.
- Python compilation, privacy scan and diff whitespace checks passed.

## Live reload evidence

- Health: `ok`; cost mode: `offline_only`; data tier: `metadata`.
- Exactly one listener is bound to `127.0.0.1:8765` by one hidden Prompt
  Enhancer server tree.
- A second hidden `serve` attempt exited without creating another listener or a
  visible window.
- The owned server tree had zero recognized model or helper descendants.
- In-app browser reload reached `/agent`, title `Agent · Prompt Enhancer`, a
  complete document, one main landmark, no password input and no horizontal
  overflow. No application content was read.

## Owner review later

1. Start and stop one safe local test model and confirm no console flashes.
2. Cancel one synthetic long-running command and confirm no descendant remains.
3. Launch the installed app twice and confirm only one window/listener remains.
4. Exit the installed app and confirm its exact owned tree disappears.

## Explicit next checkpoint

Release-01b.1 adds the owner-visible sidebar update state/button and safely
checks and stages a newer immutable, signed installer. It will not run `git
pull`, execute code from `master`, or mutate the running application. Reviewed
apply/relaunch/rollback belongs to Release-01b.2, and packaged parity remains
Release-01b.3.
