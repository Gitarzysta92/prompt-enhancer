# Artifact-01b checkpoint handoff

Status: automated implementation and protected live gate complete; owner click
review pending

## Outcome

Generated artifact records now have a durable lifecycle inside their exact
project and chat. A user can rename the display label, archive and restore the
record, move an archived record to recoverable **Removed**, and explicitly
recover it without changing or deleting the workspace file or immutable version
history.

This checkpoint does not complete multimodal input or the complete viewer and
export matrix. Those remain Artifact-01c and Artifact-01d.

## Frozen lifecycle contract

- Artifact bytes, relative paths and historical versions are immutable.
- Rename changes a display label only. A later version keeps that custom label.
- The allowed state path is **Active → Archived → Removed → Archived → Active**.
- Archive and restore are metadata operations and never touch the workspace
  file.
- **Removed** is recoverable record state, not deletion. Moving there requires
  an archived record plus native user-presence confirmation.
- Removed records cannot serve details, previews or bytes and cannot gain a new
  version through background synchronization.
- Recovery is explicit and returns **Removed** to **Archived**. Restoration is a
  separate explicit action.
- Every mutation is exact-project, exact-chat and expected-revision bound.
  Stale, replayed, cross-scope and invalid-transition requests fail closed.

## Persistence and API

- Catalog schema v21 adds lifecycle state, timestamps, revision and supporting
  constraints/indexes without rewriting artifact content.
- Migration from the earlier artifact schema preserves existing active records.
- Lifecycle, labels and revisions survive application/service reconstruction.
- Timestamps are monotonic even if later projection receives older source
  evidence.
- `agent-artifact.v3` is shared by backend models, exported OpenAPI, generated
  frontend types and strict runtime parsing.
- List requests select exactly one lifecycle view and receive truthful bounded
  counts for all views.
- Update and remove routes remain loopback-private and `no-store`; removal uses
  the native-confirmation allowlist.

## Interface behavior

- The artifact pane has **Active**, **Archived** and **Removed** tabs with
  accessible selected state and truthful counts. Unknown counts display `—`,
  not a fabricated zero.
- A shared accessible dialog owns rename and lifecycle actions and restores
  focus when closed.
- Copy explains whether a workspace file is kept and why native confirmation is
  required.
- Removed cards expose management and recovery only; they do not expose
  **Preview**.
- A changed, missing or malformed current file never inherits historical
  artifact authority. Its exact path can enter the existing reviewed capture
  workflow instead.
- Controls retain 44-pixel targets, responsive stacking at 360 px and visible
  forced-colors boundaries.

## Validation ledger

- Focused artifact, MCP and OpenAPI backend tests: **65 passed**.
- Broader affected Agent backend surface: **112 passed**.
- Artifact parser, transport and panel frontend tests: **251 passed**.
- Full affected Agent frontend suite: **408 passed**.
- Artifact capture, lifecycle and viewer browser E2E: **6 passed** across
  **360 px** and **1,440 px**.
- Production frontend build: **passed**, **563 modules transformed**. The
  existing non-fatal chunk-size advisory remains.
- Generated API-contract check: **passed**.
- Repository privacy scan: **passed**.
- Patch whitespace check: **passed**; only existing Windows line-ending notices
  were emitted.

The adversarial coverage includes stale revisions, invalid transitions,
cross-project and cross-chat mutation, restart recovery, older-schema migration,
native-confirmation refusal, removed-record byte/preview refusal, later reviewed
writes that must not resurrect a removed record, and explicit recovery before
resynchronization.

## Protected live-app gate

The production frontend was rebuilt and the old in-memory loopback process was
replaced with one hidden server. The final census observed:

- `/health`: HTTP 200;
- exactly one listener on `127.0.0.1:8765`;
- zero local model workers;
- no visible terminal window spawned by the replacement;
- no artifact read error after reloading `/agent`; and
- no browser console errors.

No model was loaded, no GPU acceptance was attempted and no retained project,
chat or workspace content was opened to prove this checkpoint. Deterministic
synthetic fixtures provide the lifecycle interaction evidence.

## Privacy and safety

- Fixtures use only fictional projects, chats, paths, bytes and digests.
- No provider history, credential file, model weights or unrelated local
  content was inspected.
- No artifact, prompt or transcript content was sent to a network service.
- The service remains loopback-bound and the checkpoint grants no command,
  model, MCP or unreviewed file authority.

## Click later

1. On localhost, select a retained chat with an artifact and inspect the three
   lifecycle tabs and counts.
2. Rename an artifact, reload the page and confirm only its visible label
   changed.
3. Archive and restore it; confirm the record changes tabs while its workspace
   file and versions remain untouched.
4. In the native protected Agent window, archive a disposable synthetic record,
   choose **Move record to Removed**, review the confirmation, and confirm the
   Removed card has no Preview action.
5. Recover it to Archived and then restore it to Active; repeat at phone width
   or Windows high-contrast mode if those layouts matter to you.

## Deliberately remaining

- **Artifact-01c:** capability-aware image, audio and supported-document input,
  upload/record state, cancellation and restart recovery.
- **Artifact-01d:** complete safe viewer/open/download/export and exact-byte
  lineage acceptance across text, code, image, PDF and inert Office formats.

The next proposed implementation checkpoint is Artifact-01c. No commit or push
was made, and no model or GPU worker was started for this checkpoint.
