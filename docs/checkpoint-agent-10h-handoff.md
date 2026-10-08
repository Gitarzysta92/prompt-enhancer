# Agent checkpoint 10h — exact generated-output capture

Date: 2026-08-29

## Outcome

Retained Agent chats can now turn an existing workspace file into an immutable
artifact card through one explicit inspect-then-capture flow. This closes the
gap for binary, image, PDF, and Office-style outputs that the UTF-8 workbench
cannot edit.

The review step is read-only and returns metadata only. It shows the exact
workspace-relative path, display title, type/viewer, byte size, and SHA-256
digest. The later capture requires native user-presence confirmation and is
bound to that exact reviewed digest and size. A changed file fails closed and
must be reviewed again.

## Implemented boundary

- `POST /v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/capture-preview`
  returns strict `agent-artifact-capture-preview.v1` metadata with
  `file_content_included: false` and `requires_native_confirmation: true`.
- The existing `POST .../artifacts` route remains the only capture mutation and
  still requires native confirmation.
- The service re-reads and re-hashes the workspace file during capture; a stale,
  missing, oversized, linked, or otherwise inadmissible file is refused.
- **Files & review** exposes **Add output** for retained chats. Non-editable
  workspace-tree files use the same review flow instead of a dead control.
- Successful capture refreshes the existing immutable artifact cards and their
  Markdown, source, image, PDF, Office, inert, and download-only viewers.
- Editing the path or title invalidates the old review. Closing, changing chat,
  changing transport, or an aborted request also discards the pending review.
- Dialog footer actions now meet a 44 px minimum touch target.
- The provider-neutral controller manifest advances to
  `local-agent-orchestration.v13`: 60 Agent routes plus five runtime routes.

## Verification

- Artifact/API/controller/CLI/MCP/OpenAPI backend matrix: **148/148 passed**.
- Agent dialog/workspace/viewer/page/transport/contract frontend matrix:
  **396/396 passed**.
- Responsive Chromium acceptance at 1,440 px and 360 px: **2/2 passed**,
  including exact metadata review, revision-bound capture, artifact-card
  projection, viewport fit, and 44 px actions.
- Production TypeScript/Vite build: **553 modules**, passed after the final CSS
  rebuild.
- Generated OpenAPI/TypeScript drift check, Python compilation, privacy scan,
  and whitespace check: passed. Existing Windows line-ending notices remain
  informational.
- The rebuilt live app reloaded at `http://127.0.0.1:8765/agent`. The retained
  fictional chat resumed without a model, **Files & review → Add output** was
  enabled, the production dialog measured 44 px with no horizontal overflow,
  and browser diagnostics were empty.
- Final runtime inventory: one listener on `127.0.0.1:8765`, no fixture
  listener, no visible terminal, and zero local-model processes.

No model, GPU inference, microphone, command, web fetch, real workspace file,
provider configuration, credential, or protected capture was used.

## Owner check

The Files & review drawer is left open on the live Agent page. For a bounded
manual check, use a fictional retained workspace containing synthetic text,
image, PDF, DOCX, PPTX, XLSX, and ODT files:

1. Choose **Add output** or a non-editable file in the workspace tree.
2. Enter its workspace-relative path and choose **Review output**.
3. Confirm the exact path, viewer, size, and digest, then choose
   **Add verified output** and accept the native confirmation.
4. Open the resulting artifact card and exercise Preview/Source/Download as
   applicable.
5. Change one synthetic file outside the app and confirm that its recorded
   version becomes stale and is refused rather than silently substituted.

## Next checkpoint

After this owner artifact walkthrough, continue the guarded owner handshake:
separate-window open/refocus/close, one fictional model-backed turn and Stop,
one reviewed fictional write, and verified model/process/GPU cleanup. Any failed
observation becomes the next bounded implementation slice; no model or protected
authority should be started automatically.
