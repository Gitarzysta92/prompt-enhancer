# Artifact-01a checkpoint handoff

Status: automated implementation and protected live gate complete; owner click
review pending

## Outcome

Reviewed generated files now retain a usable connection to the conversation
that produced them. A user can open the exact source turn, compare immutable
artifact versions without a false content-diff claim, and rely on conservative
PDF admission that refuses encrypted, truncated and spoofed payloads before the
local renderer.

This checkpoint does not complete the entire Artifact-01 workstream. Durable
artifact lifecycle and capability-aware document/media input remain separate
bounded slices.

## Producing-turn linkage

- An artifact with `source_turn_id` exposes a 44-pixel **Source turn** action.
- Navigation first confirms the exact producing turn exists in retained loaded
  history.
- Bounded transcript batches expand as needed; the exact `<details>` element is
  opened, scrolled into view and focused through a stable turn identifier.
- A recorded source that is absent is reported truthfully instead of navigating
  to an arbitrary nearby turn.
- Focus indication and forced-colors behavior remain visible.

## Version-comparison truth contract

- Artifact lineages with at least two versions expose **Compare versions**.
- The comparison selector excludes the currently selected version and swaps
  coherently when the selected artifact version changes.
- The comparison contains only recorded path, byte size and delta, source
  evidence, provenance, digest prefixes and same/changed digest status.
- The UI explicitly labels this as metadata-only. It does not fetch historical
  bytes or describe the result as a content diff.
- A stale historical version remains non-previewable and non-downloadable and
  cannot expose **Open current file**.

## PDF admission safety

Before a payload can enter the local PDF.js renderer, the server now requires:

1. a supported `%PDF-1.0` through `%PDF-1.7` or `%PDF-2.0` header followed by a
   line break;
2. terminal `%%EOF` within the final 1,024 bytes;
3. only whitespace after the terminal marker;
4. at least one terminated indirect object; and
5. no conservative `/Encrypt` token.

Encrypted, truncated, header-spoofed and trailing-payload-spoofed `.pdf` files
are returned as opaque `application/octet-stream` binary artifacts with
download-only handling. Their bytes are not interpreted or executed by the
viewer.

## Adjacent repairs found by end-to-end validation

- Runtime placement records are treated as optional evidence. Missing placement
  data now fails closed, disables Apply and explains how to recover instead of
  crashing the Agent route.
- The saved-history E2E fixture now links its synthetic artifact to the exact
  retained producing turn and a matching verified write receipt. The fictional
  path, size and digest agree across the fixture.

## Validation ledger

- Backend artifact, attachment and document-preview tests: **53 passed**.
- Full Agent frontend suite: **453 passed across 27 files**.
- Saved-history browser E2E: **2 passed**, at **360 px** and **1,440 px**.
- Production frontend build: **passed**, **563 modules transformed**. The
  existing non-fatal chunk-size advisory remains.
- Generated API-contract check: **passed**.
- Repository privacy scan: **passed**.
- Patch whitespace check: **passed**; only existing line-ending notices were
  emitted.

The E2E acceptance proves exact source-turn opening/focus, version-selection
swapping, truthful metadata comparison, stale-version locking, Escape focus
restoration and viewport fit.

## Protected live-app gate

The production frontend was rebuilt and the loopback application was restarted
with a hidden process. The final protected census observed:

- `/health`: HTTP 200;
- exactly one loopback listener;
- zero `llama-server` model workers;
- zero visible terminal windows;
- no browser console errors on `/agent`;
- the runtime region and compiled artifact-comparison styles present.

The retained local catalog was not mutated for a live artifact demonstration.
Artifact interactions use deterministic synthetic unit and E2E fixtures so no
private project, chat or workspace data is inspected or altered.

## Privacy and safety

- Tests use fictional paths, turns, digests and messages only.
- No provider history, credential file or unrelated local content was read.
- No artifact bytes, prompt content or derived transcript data were sent over a
  network.
- The service remains loopback-bound and the checkpoint adds no execution or
  approval authority.

## Click later

1. In a retained chat with a reviewed output, click **Source turn** and confirm
   the exact producing turn expands and receives focus.
2. Open an artifact with at least two versions, enable **Compare versions**, and
   change versions; confirm path, size, digest and provenance update and the
   metadata-only warning stays visible.
3. Select a stale historical version and confirm preview/download and **Open
   current file** remain unavailable.
4. In a disposable synthetic workspace, review an encrypted or truncated PDF
   and confirm it is download-only, not opened by the PDF viewer.
5. Repeat the artifact card at phone width and, if used, Windows high-contrast
   mode.

## Deliberately remaining

- **Artifact-01b:** durable artifact rename, archive, restore and explicit
  recover/remove lifecycle within the exact owning project and chat.
- **Artifact-01c:** capability-aware image, audio and document input routing,
  upload/record previews, cancellation and size/type admission.
- **Artifact-01d:** full supported-viewer/export/linkage acceptance across text,
  code, image, PDF and inert Office projections.

The next implementation checkpoint is Artifact-01b. No commit or push was made
as part of this checkpoint.
