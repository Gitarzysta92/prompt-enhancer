# Agent checkpoint 09i — local artifact viewer hardening

Date: 2026-08-28

## Outcome

Image and PDF artifact cards now have a bounded, truthful review path rather
than relying on a browser PDF iframe or treating successful byte retrieval as
successful rendering. The selected immutable version remains the authority:
content that disagrees with its recorded type or size is not displayed or
downloaded.

## Viewer changes

- Preview and download require the response content type, declared byte count,
  Blob byte count, and bounded generated filename to agree with the selected
  artifact version.
- Every artifact card has a title-specific accessible View name.
- Image preview reports loading, ready, and decode-failure states and provides
  fit plus bounded 50–300% zoom controls.
- Image object URLs are revoked on close, version change, project/chat scope
  change, and unmount. Scope changes close the dialog instead of letting an old
  artifact remain visible under a new chat.
- PDF preview is lazy-loaded and parsed from the verified in-memory Blob by the
  pinned `pdfjs-dist` 6.2.108 package and its locally bundled worker.
- PDF pages render to canvas with bounded 75–250% zoom and page navigation.
  XFA, annotations, range, stream, auto-fetch, worker fetch, and WASM paths are
  disabled. Links, forms, scripts, audio, and annotations are not interactive.
- PDF parser/render failures are explicit; the UI never substitutes another
  document or leaves an indefinite browser-plugin spinner.

## Automated verification

- Artifact panel and PDF renderer component slice: **16 passed**.
- Complete Agent component suite, run serially: **263 passed** across 20 files.
- Responsive Chromium workflow matrix: **69 passed**, including image/PDF
  behavior at 360 px and 1440 px, focus restoration, viewport bounds, no real
  external request, and object-URL cleanup.
- Windows distribution, artifact backend, and Agent release hardening:
  **59 passed**.
- Production TypeScript/Vite build passed; the PDF viewer and worker are emitted
  as lazy local assets.
- `npm audit` reported zero known vulnerabilities for the locked frontend tree.
- `git diff --check` passed; line-ending notices are informational and no
  whitespace errors were reported.

## Privacy and packaging boundary

All new fixtures use generated image/PDF bytes and fictional identifiers. No
workspace file, provider transcript, credential, model, GPU, microphone, or
network service is used by the tests. The responsive test rejects every real
non-loopback request while allowing only page-local `blob:`/`data:` resources.

The privacy scanner now treats only the exact ignored generated dashboard
resource tree as generated output, matching the existing build contract. An
explicit-path scan still examines that tree, and adjacent package resources
remain covered; focused exclusion tests pass. The repository-wide scan still
reports the pre-existing untracked `docs/checkpoint-agent-02-shell.png` binary
and is therefore not claimed as green.

## Native reload proof

- Reloaded the existing packaged Agent workspace without opening a shell or
  launching a model.
- The same fictional retained project and chat reopened, the local service
  reported available, and the shared runtime remained **Stopped**.
- Final process state is one Agent window, one listener bound only to
  `127.0.0.1:8765` and owned by `pythonw`, zero `llama-server` processes, and
  zero targetable terminal windows.
- No artifact was created from a real workspace for this code-only gate. The
  native create/open/stale/download walkthrough remains an explicit owner gate.

## Remaining work

The next bounded artifact slice is isolated local conversion/viewing for
admitted office-document formats plus explicit Reveal and Review-changes
actions. The native owner gate for creating, opening, staling, and downloading
synthetic artifacts also remains open, as do real installed-client and
model-backed acceptance.

No commit or push was requested.
