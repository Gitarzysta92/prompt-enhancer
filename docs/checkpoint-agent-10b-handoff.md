# Agent checkpoint 10b — shared runtime and context ownership

Date: 2026-08-28

## Outcome

The Agent runtime card now owns every status read, chat-context read, model
switch, chat bind, and Stop request across chat changes, focus refreshes,
transport replacement, and unmount. Older or cross-scope responses cannot
replace newer runtime state or claim context evidence for the wrong chat or
model.

The UI continues to report context as exact or unknown. It does not infer usage
from the runtime-wide last request, a model name, or a pending read.

## Repaired behavior

- Runtime and chat-context refreshes cancel their predecessor and accept only
  their exact transport, chat, model, and newest observed revision.
- A pending chat-context read is labelled **checking this chat's context
  evidence** instead of prematurely claiming **not measured**.
- A bound context receipt whose chat or model identity does not match the
  current chat is rejected as **context evidence unavailable**.
- Start/Switch and Stop carry abort signals and lifecycle ownership. Replacing
  the transport or closing the view aborts the operation, releases the busy
  state, and prevents a late result from changing the replacement view.
- Runtime switching captures the original chat identity. If the user changes
  chats while it completes, only that original chat can be rebound and the
  status message says that the current chat was not changed.
- Runtime and chat binding remain separate revision-bound operations. A
  successful runtime switch with a failed binding can still retry only the
  bind, without reloading the model or losing an unsent draft.
- Loading, draining, unloading, cleanup-unconfirmed, and quarantined runtime
  states fail closed in the card. The UI explains the wait or cleanup condition
  before a backend mutation is attempted.
- The two expensive workspace-drawer tests now use bounded asynchronous focus
  assertions and an explicit test timeout, removing load-dependent false
  failures without weakening their behavior checks.

No real model, GPU worker, microphone, provider session, workspace mutation,
approval, external controller, or remote endpoint was used by this checkpoint.

## Verification

- Runtime-control unit and adversarial lifecycle coverage: **15/15 passed**.
- Complete Agent feature folder: **21/21 files and 324/324 tests passed**.
- Complete frontend: **160/160 files and 2,189/2,189 tests passed**.
- Focused backend runtime/context contract matrix: **11/11 passed** using only
  synthetic stub runtimes.
- TypeScript and production build: **547 transformed modules**, passed.
- Repository privacy scan and `git diff --check`: passed.

The first complete-frontend run exposed two pre-existing load-sensitive
workspace-drawer assertions after 2,187 passes. Both passed in isolation, their
timing contracts were hardened, and the complete 2,189-test matrix then passed
in one rerun.

## Live and process evidence

A fresh temporary in-app tab loaded the rebuilt
`http://127.0.0.1:8765/agent`. The durable fictional project/chat rail was
visible. The shared runtime reported **Stopped**, no model was selected,
Requested and Served were **None**, cleanup was **not required**, and this
chat's context was **not measured**. Start, Stop, composer, Send, and media
controls stayed disabled. A read-only runtime Refresh preserved that state and
produced no alert or dialog. The temporary tab was closed.

After validation there was exactly one loopback-only listener on port 8765,
zero non-loopback listeners on that port, zero model workers, zero matching GPU
model workers, and zero Vite, Vitest, or Playwright workers.

## Next checkpoint

The next autonomous slice is **Agent-10c: durable project/chat lifecycle and
controller parity re-audit**. It will revalidate create, browse, switch, search,
rename, pin, move, archive, restore, close/delete, restart restoration, retained
history, and session-scoped drafts across the native rail and provider-neutral
controller/MCP contracts. It will use synthetic fixtures and will not mutate
the owner's current project/chat data.

Owner acceptance remains separate: a chosen probe-verified local model must
still complete a fictional streamed turn, Stop, file/artifact review, unload,
process-exit, and CPU/GPU cleanup walkthrough under native confirmation.
