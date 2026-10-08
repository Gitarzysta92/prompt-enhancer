# Workspace checkpoint 01b handoff

## Outcome

The Agent's reviewed change set now provides a bounded recovery path for every
kind of reviewed file publication. A user can inspect the exact inverse review,
apply it through native confirmation, and then open the recovered file as an
existing artifact or begin an exact artifact capture from the same path card.

Recovery remains a live-session feature. Retained first-reviewed baselines are
bounded in memory and are not presented as durable undo history. The restored
filesystem effect is read back objectively before the UI reports success.

## Recovery contract

- Preview is read-only and revision-bound. It returns an inverse diff when one
  can be rendered, or an explicit line-ending-only or oversize state.
- Existing reviewed files use `edit` to restore the retained first-reviewed
  baseline exactly.
- Externally missing original files use `recreate` to restore that baseline.
- Files created by the session use `trash_created` and move to the Windows
  Recycle Bin rather than being permanently deleted.
- Apply is single-use, requires native user-presence confirmation, re-observes
  the reviewed revision, and refuses stale or expired authority.
- Success requires filesystem read-back. Change-set projection failure may
  still be reported separately after the filesystem effect was verified.
- Baseline bytes are never returned as a general content endpoint. They are
  exposed only through the bounded inverse review required for this action.

The public controller contract is now `local-agent-orchestration.v17`: 63 Agent
routes, five runtime routes, and 11 native review gates. Restore preview is a
token-authenticated controller operation; restore apply remains native-only.

## Exact line-ending repair

A new CRLF test exposed an older editor restriction: the ordinary edit preview
correctly rejected line-ending changes, but that also prevented an exact restore
from reconstructing a retained CRLF baseline after an LF edit. The editor now
has a restore-only internal seam for retained line-ending changes. Ordinary
manual and agent edits still reject line-ending conversion, while recovery can
restore the exact retained bytes and verify their digest and size.

## Artifact handoff

- A reviewed path can open the already captured artifact for the exact active
  project and chat.
- If none exists, **Add as artifact** opens the existing exact-capture review
  for that path; it does not silently capture or widen the scope.
- Root drift, loading, unsaved editor work, unsupported transport, and
  cross-chat requests fail closed with explicit UI copy.
- A successful recovery offers the same scoped artifact handoff.

## Validation ledger

- Backend change-set and recovery suite: **21 passed**, including exact edit,
  recreate, Windows Recycle Bin, stale-preview preservation, unavailable and
  already-reverted states, HTTP/native authorization, exact CRLF recovery, and
  the unchanged ordinary edit restriction.
- Controller, client and CLI suites: **94 passed**.
- Focused Agent/controller/MCP matrix: **224 passed**.
- OpenAPI export: **6 passed**; generated frontend transport drift check passed.
- Live MCP integration: **3 passed**.
- Broader workspace, artifact, history, attachment and Agent regression:
  **484 passed**.
- Frontend recovery/workspace/artifact component matrix: **93 passed**.
- Full frontend Agent feature suite: **436 passed** across 26 files.
- Agent API contract suite: **301 passed** across 21 files.
- Selected v17/controller/HTTP suite: **229 passed** across five files.
- Production TypeScript/Vite build passed with **561 transformed modules**. The
  existing large-chunk warning remains non-fatal.
- Repository privacy scan passed. Ruff is not installed in this environment,
  so no Python lint result is claimed.

## Live protected-app smoke check

- The exact old listener was stopped and the protected app relaunched hidden;
  one `pythonw` listener became healthy on `127.0.0.1:8765` and `/health`
  returned HTTP 200.
- The existing Agent tab was reloaded. Project/chat navigation, retained-chat
  recovery, model/context controls, controller readiness, conversation, and
  Files & review all rendered without a fatal boundary or disconnected state.
- **Connections** reports `local-agent-orchestration.v17`, 63 Agent routes, five
  runtime routes and 11 native review gates.
- A retained synthetic chat resumed without loading a model. Its **Changes** tab
  rendered the complete reviewed-path coverage state and the explicit warning
  that it is not a whole-workspace or Git scan.
- The browser observed 12 script and two stylesheet resources and reported zero
  console errors after reload.
- Zero `llama-server` processes and zero visible terminal windows were present
  after restart and live UI inspection.

## Privacy and safety

Only reserved synthetic workspaces and fixtures were used. No provider session,
credential, private transcript, model weight, unrelated home-directory content,
or real workspace file was read. No model was started and no GPU memory was
allocated. The live smoke check did not create, edit, move, or trash a file.

## Click later

Use a disposable folder and the visible native Agent window for these owner
checks:

1. Modify a reviewed existing file, open **Files & review → Changes**, preview
   **Restore baseline**, approve it, and confirm the exact original content is
   restored.
2. Externally remove a reviewed original file, preview `recreate`, approve it,
   and confirm the baseline returns. If an unreviewed chain gap remains, confirm
   the change set still says partial rather than complete.
3. Create a file through the reviewed session, preview `trash_created`, approve
   it, and confirm the file is recoverable from the Windows Recycle Bin.
4. Start with a CRLF file, make a reviewed LF change, restore it, and confirm the
   file returns to exact CRLF bytes.
5. From the changed-path card, open an existing artifact or choose **Add as
   artifact**, complete the exact capture review, and verify the document viewer
   opens in the same project/chat scope.
6. Deny or cancel one restore and confirm no filesystem effect. Then create a
   preview, change the file before apply, and confirm the stale preview cannot
   overwrite the newer content.

## Next

The wider finish goal remains active. The next bounded checkpoint should be
approved separately: Workspace-01c can focus on richer diff/editor ergonomics
and recovery discoverability, while Artifact-01 can focus on broader artifact
viewer formats and review workflows. No next checkpoint is started here.
