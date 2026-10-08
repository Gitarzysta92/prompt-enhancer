# Agent checkpoint 09j — Office previews and artifact actions

Date: 2026-08-28

## Outcome

The Agent artifact surface can now inspect admitted modern Office documents as
bounded inert projections and can route the selected artifact back to the exact
workspace file or reviewed change. Legacy Office files and malformed,
oversized, encrypted, unsupported, stale, or mismatched content remain
download-only or fail explicitly; the UI never implies that a failed projection
was rendered successfully.

## Document preview changes

- `.docx`, `.pptx`, `.xlsx`, and `.odt` artifacts receive the `document`
  preview kind only when their extension and modern Office MIME type agree.
- A private, no-store, immutable-version endpoint returns a schema-versioned
  local projection after revalidating project, chat, artifact, version, digest,
  size, type, and MIME metadata.
- ZIP packages are bounded by entry count, expanded size, selected-part size,
  compression ratio, safe member paths, compression method, encryption state,
  and duplicate entries. XML document-type and entity declarations are
  rejected.
- Relationship and ODT link metadata is observed only to report omitted
  external links; no target is fetched or resolved.
- Word/ODT paragraphs and tables, PowerPoint slide text, and Excel values or
  formulas are projected as inert text. Embedded objects, comments, macros,
  media, notes, and external links are omitted and reported truthfully.
- Projection limits cap sections, paragraphs, rows, cells, and characters. The
  viewer exposes truncation and omission warnings instead of silently hiding
  missing material.
- The responsive viewer provides bounded section, slide, or sheet navigation
  and semantic tables. It creates no anchor, script, iframe, raw Office object
  URL, external request, or executable document surface.

## Artifact action changes

- **Open current file** is available only for the latest editable text version.
- **Reveal in files** selects the exact latest workspace entry without reading
  its bytes, including non-editable document artifacts, and preserves an
  unrelated unsaved editor or transaction draft.
- **Review changes** opens the exact latest reviewed-write diff. Missing,
  disabled, stale, unsafe, or cross-chat requests fail explicitly and never
  fall through to a different change.
- **Download** remains tied to the selected immutable version and is still
  available after a document-projection failure when the exact artifact bytes
  remain valid.
- Retained history does not pretend to own live workspace actions. Action
  requests are scoped to the active project, chat, transport, artifact, and
  version.

## Automated verification

- Document projection, artifact service, catalog migration, OpenAPI, release,
  and Windows distribution slice: **93 passed**.
- Complete Agent component suite, run serially: **273 passed** across 20 files.
- Responsive Chromium workflow matrix: **69 passed** at 360 px and 1440 px,
  including Office navigation, omission/truncation warnings, viewport bounds,
  no executable markup, no real external request, and no Office object-URL
  creation.
- Privacy-scanner exclusion contract: **5 passed**.
- Production TypeScript/Vite build passed.
- Generated API drift check passed.
- `npm audit --audit-level=low` reported zero known vulnerabilities.
- Tracked-file `git diff --check` passed; line-ending notices are informational.
  The new checkpoint files contain no trailing whitespace.

## Privacy and runtime boundary

All tests use synthetic packages, fictional identifiers, and reserved example
paths. Preview generation does not invoke Office, a converter process, a remote
service, a provider transcript, a model, the GPU, or the network. The exact 09j
file set passes the privacy scanner. The repository-wide scan still reports the
pre-existing untracked `docs/checkpoint-agent-02-shell.png` binary and is
therefore not claimed as green.

## Native reload proof

- Reloaded the existing packaged Agent workspace in place without opening a
  shell, starting another app instance, or launching a model.
- The retained synthetic project and chat reopened, the local service reported
  available, and the shared runtime remained **Stopped**.
- Final process state is one Agent window, one listener bound only to
  `127.0.0.1:8765` and owned by `pythonw`, zero `llama-server` processes, and
  zero targetable terminal windows.
- The reload confirms the packaged shell is healthy. The document/action owner
  walkthrough below remains intentionally open because this checkpoint does not
  read or manufacture files inside a real owner workspace.

## Owner walkthrough

After reload, the bounded manual check is:

1. Open the Agent workspace and select a synthetic project and chat.
2. Preview one synthetic DOCX, PPTX, XLSX, or ODT artifact and verify its
   navigation plus omission/truncation notice.
3. Use **Reveal in files** and confirm the exact tree item is selected without
   losing an unrelated dirty editor draft.
4. Use **Review changes** on a reviewed-write artifact and confirm the exact
   diff opens.
5. Download the selected immutable version and confirm the filename and type.

## Remaining work

The next step is the owner artifact walkthrough above plus the existing
one-time owner handshake. After that gate, the remaining acceptance work is a
separate-window/model-backed turn, one fictional reviewed write, Stop, and
process/GPU cleanup verification. No automated step may create the bearer or
launch a real model without the owner's explicit choice. If those gates pass,
the final legacy-surface usage audit and any deletion proposal remain separate
reviewed work.

No commit or push was requested.
