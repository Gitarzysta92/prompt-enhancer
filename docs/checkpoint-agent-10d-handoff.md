# Agent checkpoint 10d — conversation fidelity and rich rendering

Date: 2026-08-29

## Outcome

The Agent conversation now has a bounded, explicit coding-agent transcript
surface. Completed user and assistant messages, model-exposed reasoning, tool
requests, tool outcomes, status/errors, streamed output, turn receipts, and
retained history keep distinct semantics instead of being flattened into an
unbounded chat log.

This checkpoint does not expose or invent hidden chain of thought. It labels
only reasoning text explicitly returned by the selected model and explains that
boundary in the expanded reasoning panel.

## Repaired behavior

- GFM Markdown, headings, lists, task lists, tables, quotes, inline code, and
  fenced code remain rendered through the owned safe renderer. Raw HTML is
  skipped, remote images never mount, unsafe schemes are blocked, external
  links are isolated, and workspace links accept only bounded relative paths.
- Code blocks, completed user messages, completed assistant responses,
  model-provided reasoning, and included tool output have explicit copy
  controls. Clipboard success, rejection, and API unavailability are visible;
  status timers are cancelled on unmount instead of silently updating a stale
  view.
- Reasoning is labelled **Model reasoning** and **model-provided**. The UI states
  that hidden chain of thought is not reconstructed. A model that exposes no
  separate reasoning retains an honest unavailable message.
- Tool requests keep their bounded action/path summary. Tool results retain
  exact known/unknown/succeeded/failed/not-approved/cancelled/unverified labels,
  keep raw output collapsed, and say when raw output was deliberately absent
  from retained history.
- A transcript initially mounts at most the latest 200 events plus a nearby
  50-event turn-boundary allowance. Earlier events are revealed in explicit
  batches, while the complete in-memory history still drives receipts,
  approvals, artifacts, and state. A long live stream remains visible even
  when its first delta is outside the mounted window.
- Expanding earlier history preserves that read position as new events arrive;
  a default unexpanded transcript continues following the newest activity.
- Frontend and backend event models now reject fields borrowed from another
  event kind. Status cannot carry approval identity, assistant text cannot
  carry tool authority, tool results require an exact call identity and
  outcome, and approval events require their exact tool/approval fields.
- Approval preview admission now matches the bounded multi-file transaction
  surface instead of applying the smaller single-file limit in the frontend.

No real model, microphone, protected approval, workspace mutation, provider
session, external endpoint, or remote service was used.

## Verification

- Complete frontend: **161/161 files and 2,199/2,199 tests passed**.
- Agent history, local-agent service, completion, turn details, controller HTTP,
  MCP HTTP, and release hardening: **139/139 tests passed**.
- Event/turn contract regression after exact call correlation: **54/54 tests
  passed**.
- TypeScript and production build: **549 transformed modules**, passed.
- Generated OpenAPI and TypeScript client parity: passed.
- The rebuilt `http://127.0.0.1:8765/agent` loaded in a fresh in-app tab with
  one conversation log, project/chat navigation, and a truthful model-stopped
  composer. No message was sent and the temporary tab was closed.
- Cleanup inventory: exactly one listener on `127.0.0.1:8765`, **0** Vitest or
  pytest workers, and **0** local-model workers.

## Remaining owner gate

Automated conversation fidelity is complete, but native behavior cannot be
claimed from synthetic tests alone. The owner still needs to choose one
probe-verified local model and perform the bounded streamed-turn, Stop,
file/artifact review, separate-window, unload, process-exit, and CPU/GPU cleanup
walkthrough. Only content-free receipts should be recorded.

## Next checkpoint

The next autonomous slice is **Agent-10e: final parity and acceptance-readiness
audit**. It will reconcile the old capability list with the implemented
surface, run the rich transcript through synthetic desktop/320 px and
forced-colors fixtures, fuzz Markdown/event boundaries, verify that no legacy
route is still required by the Agent workflow, and produce the exact bounded
owner checklist. It will not start a model, request microphone access, or grant
protected authority.
