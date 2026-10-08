# Agent checkpoint 09z — request-owned artifact downloads

Date: 2026-08-28

## Outcome

Artifact downloads now belong to one exact project, chat, artifact version,
viewer lifetime, and transport instance. A late response cannot create a
browser download after the viewer closes, the selected version changes, the
viewer opens another artifact, the component unmounts, or project/chat scope is
replaced.

This slice also audited the adjacent artifact actions. **Open current file**
enters the bounded UTF-8 editor, **Reveal in files** selects the recorded path
without opening or executing it, and **Review changes** requests the exact
reviewed-path net diff. Binary and Office artifacts therefore do not get
misrepresented as editable text.

## Repaired contracts

- Every explicit download receives an `AbortSignal` and is cancelled at all
  viewer, version, transport, project, chat, and unmount boundaries.
- A cancelled or superseded response is ignored before Blob URL creation or an
  anchor click, even if the old transport resolves after cancellation.
- A retryable preparation failure keeps the verified preview and permits an
  explicit retry.
- A digest conflict, missing file, malformed media response, or content
  metadata mismatch invalidates the matching preview, removes its rendered
  bytes, and disables download. A stale file is labelled **stale**, not as a
  generic unavailable preview.
- Successful downloads still require the exact immutable version size, media
  contract, safe generated filename, and server-side workspace digest check.

No file was written, moved, deleted, executed, or uploaded by this checkpoint.
It grants no approval, model, command, web, controller, MCP, or reusable
mutation authority.

## Verification

- Artifact component: **20/20 tests passed**. Coverage includes successful
  explicit download, retryable failure, stale invalidation, project/chat scope
  replacement, viewer-close cancellation, inert Markdown, image/PDF/Office
  previews, version selection, and URL cleanup.
- Artifact backend: **27/27 tests passed** across artifact lineage/content and
  bounded document-preview contracts.
- Complete Agent surface: **41/41 files and 570/570 tests passed**.
- Complete frontend: **160/160 files and 2,172/2,172 tests passed**.
- TypeScript and production build: **547 transformed modules**, passed.
- Repository privacy scan: passed.
- `git diff --check` for the changed artifact files: passed.

## Live and process evidence

A fresh temporary in-app tab loaded the rebuilt
`http://127.0.0.1:8765/agent`. The durable fictional project/chat rail and
shared runtime card were visible, the runtime truthfully reported **Stopped**,
the composer remained disabled until a model is chosen, and no unexpected
dialog appeared. The temporary tab was closed.

The retained fictional chat contains no verified artifact, so the owner-only
Preview/Reveal/Review/Download walkthrough was not simulated with a false
artifact. No native approval, download, workspace write, or model start was
requested.

After validation there was exactly one loopback listener on
`127.0.0.1:8765` (`pythonw`), zero matching model workers, zero matching model
GPU workers, and zero Vite, Vitest, or Playwright test workers.

## Next checkpoint

The next autonomous slice is **Agent-10a: image, audio, and recording lifecycle
hardening**. It will audit attachment ownership across chat switches, model
changes, cancellation, removal, failed decoding, and reload, then add or repair
the corresponding tests without loading a real model.

The owner artifact walkthrough remains a separate acceptance gate: create
fictional text/image/PDF/Office output, exercise Preview, Reveal, Review
changes, and Download, then stale one file and verify fail-closed refusal. The
real model-backed turn, Stop, reviewed write, unload, and CPU/GPU cleanup gate
also remains owner-confirmed.
