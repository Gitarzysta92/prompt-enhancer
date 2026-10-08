# Agent checkpoint 10o — detached chat lifecycle

Date: 2026-08-29

## Outcome

The native **Open separate window** path now retains the exact selected chat
across child-window reloads without placing a session identifier in the URL,
native bridge payload, browser storage, or Python window owner. Repeated opens
continue to refocus the one owned child, and closing that child leaves the
primary app, listener, and in-memory session owner running.

## Reproduced defect

The child renderer acknowledged a selection as soon as it received a session
identifier, before proving that the session could be resolved. Its route kept
only the opaque native window key. After a child reload, the transient sender
was gone and a multi-chat catalog could therefore fall back to its first chat
while reporting successful delivery.

A final source audit also found that navigation performed inside the detached
window did not update the primary renderer's reload target, and two different
handoffs could both acknowledge if the older lookup settled last.

## Implemented boundary

- The primary renderer owns one in-memory mapping from the native window key to
  the exact selected session while the Agent page is mounted.
- A child announces readiness after initial load and after reload; the owner
  then re-sends only that window's current session selection.
- A child-local live or durable-chat selection updates that same bounded
  in-memory mapping, so its new active chat becomes the next reload target.
- Opening returns the native owner's actual key before assigning the selection.
  Stale completion feedback is ignored if the user switches chats while the
  native request is pending.
- The child resolves a missing target through the exact session endpoint and
  acknowledges selection only after successful resolution and any required
  dirty-workspace confirmation.
- A missing, aborted, or declined target is not reported as delivered.
- Concurrent handoffs are revision-owned: only the newest accepted lookup can
  update state or emit a successful acknowledgement.
- Session identity remains absent from URLs, native/Python payloads, browser
  storage, logs, and new listener/process ownership.

## Verification

- Window-channel and native-bridge suite: **26/26 passed**.
- Complete Agent page integration suite: **123/123 passed**. This includes a
  two-chat child-local navigation/remount proof.
- Native window/single-instance/desktop lifecycle suite: **88/88 passed**.
- Affected Chromium matrix: **12/12 scenarios passed** across 360 and 1440 px.
  It also reconciles the intentional trigger-focus and app-dialog behavior in
  the existing shell and unsaved-draft tests.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live native application:
  - one selected synthetic chat opened in one detached native child;
  - a repeated open retained the same child window identifier;
  - reloading the child retained the same window and exact project/chat;
  - closing the child left exactly one primary Prompt Enhancer window;
  - zero live browser warnings or errors.
- Final runtime inventory: one loopback listener on `127.0.0.1:8765`, owned by
  the primary `pythonw` process; zero detected local-model server processes;
  zero detached Agent windows; zero visible terminal windows.
- An unauthenticated runtime-status request was correctly rejected instead of
  exposing model state outside the app's authenticated transport.

No model was loaded, no microphone was requested, no protected workspace
authority was granted, and no provider configuration was read or changed.

## Next checkpoint

Agent-10p should audit the external-controller onboarding surface as one
bounded slice: exact Codex/Claude/other-client setup, endpoint health and
content-free self-test receipts, authority expiry/revocation, and clear failure
recovery. Use only synthetic clients and no real bearer, model, or workspace
mutation; keep the real external proposal as an explicit owner gate.
