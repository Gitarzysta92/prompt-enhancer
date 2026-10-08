# Agent checkpoint 10c — durable project/chat lifecycle and controller parity

Date: 2026-08-29

## Outcome

Durable Agent projects and chats now have one revision-bound lifecycle across
the native rail, HTTP controller, provider-neutral controller client, and MCP
manifest. Create, browse, switch, search, rename, pin, move, archive, restore,
resume, branch, close, and permanent deletion no longer rely on an unversioned
last writer or an in-memory-only UI assumption.

The checkpoint also closed two lifecycle defects found by whole-application
validation: local model-child cancellation was sampled too slowly to leave a
reliable Windows cleanup margin, and Escape from the parent-owned New-chat
drawer did not return keyboard focus to its initiating control.

## Repaired behavior

- Permanent project deletion requires the project's exact revision. Permanent
  chat deletion requires both the exact catalog revision and exact retained
  history revision; missing heads fail validation and stale heads conflict.
- Resume, delete, metadata update, model binding, and authority revalidation are
  serialized at the catalog/live-session boundary. Resume cannot resurrect a
  chat deleted concurrently, and delete cannot remove a chat that became live.
- A live chat cannot be archived or have its model alias rewritten through the
  raw catalog endpoint. Rename, pin, and project move remain available and keep
  the live view synchronized.
- The controller manifest declares every required destructive query revision,
  and both Python and TypeScript contract parsers reject incomplete or invented
  endpoint templates.
- Every rail mutation owns one AbortController and one current operation
  identity. Duplicate submit, transport replacement, disconnect, disabled
  state, unmount, or a late response cannot apply side effects to a newer view.
- Branch creation has the same ownership fence and forwards the rail's abort
  signal through the page-level operation.
- Catalog dialogs and action menus close with Escape or backdrop dismissal and
  restore their exact trigger. The parent-owned New-chat drawer now does the
  same for every New-chat entry point.
- Model-child control is sampled every 250 ms instead of every second. Stop or
  cancellation now leaves a deterministic Windows process-tree cleanup margin
  even when child stdin is unread.
- Load-sensitive workbook, New-chat readiness, and audited-member tests wait on
  their actual visible readiness contracts without weakening assertions.

No real model, microphone, protected approval, workspace mutation, provider
session, external endpoint, or remote service was used.

## Verification

- Catalog service, SQLite revision, HTTP validation, and deterministic
  resume/delete/update race coverage: **13/13 passed**.
- Controller and orchestration contracts: **79/79 passed**.
- MCP and MCP integration: **36/36 passed**.
- Retained history, artifacts, attachments, hardening, and forking: **48/48
  passed**.
- Local Agent application service: **47/47 passed**.
- Complete frontend after the final live-focus repair: **160/160 files and
  2,194/2,194 tests passed**.
- Focused post-repair Agent page and catalog rail: **2/2 files and 131/131
  tests passed**, including the new New-chat focus-return regression.
- Complete backend run: **4,664 passed, 9 Windows capability skips, 1 process
  cancellation boundary failed** after 41 minutes. The sole failure was
  isolated to a 1.34-second cancellation path against a 1.5-second contract,
  repaired, then revalidated by **2/2 focused cases**, **10/10 consecutive
  cancellation stress runs**, and **19/19 adjacent process-I/O/tree-cleanup
  cases**.
- TypeScript and production build: **547 transformed modules**, passed.
- Generated OpenAPI parity, offline lock check, privacy scan, and
  `git diff --check`: passed.

## Live and process evidence

A fresh temporary in-app tab loaded the rebuilt
`http://127.0.0.1:8765/agent`. The durable synthetic project and saved chat
reappeared, the shared runtime reported **Stopped**, the chat truthfully showed
**no model**, and recovered protected authority remained disabled. The
composer, Send, media, Start, and Stop controls stayed disabled until a model
is deliberately chosen.

The project/chat search returned zero projects and zero chats after its bounded
140 ms debounce for a no-match query. New-chat setup opened with Workspace
folder focused; Escape closed it and returned focus to the exact New-chat
button. No browser warning or error was recorded. The temporary tab was closed
without creating or changing a project or chat.

After validation there was exactly one listener on `127.0.0.1:8765`, no
non-loopback listener, no Vite, Vitest, Playwright, pytest, model-runtime, or
automation worker, and no listener-owned model child. The coordinated runtime
was stopped and GPU memory was at the ordinary desktop baseline rather than a
loaded-LLM allocation.

## Next checkpoint

The next autonomous slice is **Agent-10d: conversation fidelity and rich
rendering**. It will re-audit streamed text, Stop, Markdown, code blocks,
model-provided reasoning summaries, tool/action activity, copy and keyboard
behavior, transcript virtualization, malformed or hostile Markdown, and exact
known/unknown status labels. Hidden chain of thought remains an explicit
non-goal; only model-provided visible reasoning or bounded activity summaries
may be rendered.

Owner acceptance remains separate: a chosen probe-verified local model must
still complete a fictional streamed turn, Stop, file/artifact review, unload,
process-exit, and CPU/GPU cleanup walkthrough under native confirmation.
