# Artifact-01d checkpoint handoff

Status: automated implementation and protected live gate complete; owner viewer
and export review pending

## Outcome

The Agent artifact card now provides one coherent, version-aware experience for
text, code, Markdown, images, PDFs and supported Office/OpenDocument files.
Every preview and raw download is revalidated against the selected recorded
version. A separate lineage JSON export is created only after an exact current
workspace read-back and never contains the artifact bytes or an absolute
workspace path.

This checkpoint preserves the existing attachment admission contract. PDF
*input* remains intentionally refused at the composer even though a
digest-verified generated or captured PDF can now use the inert artifact
viewer.

## Frozen viewer and export contract

- Artifact identity is project-, chat-, artifact-, revision- and version-bound.
  A stale scope, selected version, artifact revision, file size or SHA-256
  digest fails closed.
- Text, code and Markdown render locally as inert content. Text above the 1 MiB
  inline limit stays download-only.
- Valid PNG, JPEG and GIF artifacts use a bounded local image viewer with
  explicit zoom. Dimensions are limited to 8,192 pixels per side and 33,554,432
  pixels in total.
- Bounded, unencrypted PDFs are parsed by the pinned local PDF.js renderer with
  page and zoom controls. Corrupt, truncated and encrypted PDFs are not
  rendered; they remain available only through the explicit verified-download
  lane when their recorded bytes still match.
- DOCX, PPTX, XLSX and ODT use a bounded digest-verified text/table projection.
  Macros, links, media, comments, notes and embedded objects stay inactive and
  omitted features are disclosed. Legacy or malformed documents remain inert
  download-only files.
- **Open current file**, **Reveal in files**, **Review changes**, **Review
  current as new version**, **Download** and **Export lineage** are separate
  controls. Historical versions never pretend to be the current workspace
  file.
- Raw download re-reads the exact selected bytes and uses a generated safe local
  filename. Browser object URLs are released after use or viewer teardown.
- `agent-artifact-export.v1` contains selected lineage metadata plus verified
  size and SHA-256 evidence. It is explicitly labelled sensitive local metadata
  and declares `content_included: false` and
  `absolute_path_included: false`.
- The server performs a second metadata read after the byte read-back. A rename,
  lifecycle change, new version or other revision race cannot produce an export
  from mixed snapshots.
- Export is an additive capability. An older or partial transport keeps
  preview, raw download and lifecycle controls usable; only lineage export is
  disabled with truthful explanatory copy.

## Controller and MCP propagation

- Controller discovery advances to `local-agent-orchestration.v19`: 67 Agent
  operations plus five runtime operations, 72 total. The artifact export route
  is discoverable without inheriting native mutation authority.
- Agent MCP advances to `prompt-enhancer-agent-mcp.v22`. Its strict export
  action validates scope, artifact identity, revision, selected version,
  evidence, privacy flags and the absence of undeclared byte fields.
- The private HTTP export route is no-store and CSRF protected. It does not ask
  for native presence because it creates metadata only and changes neither the
  workspace nor the artifact lifecycle.
- Generated OpenAPI and TypeScript contracts include the exact request,
  response and fixed privacy flags.

## Validation ledger

- Broad affected backend/controller/MCP/OpenAPI suite: **187 passed**.
- Focused lineage race guard: **2 passed**; the metadata mutation after exact
  byte read-back was refused.
- Focused MCP adversarial export matrix: **4 passed**.
- Artifact/controller/parser/HTTP frontend set: **297 passed**. After the
  progressive-transport compatibility repair, the changed artifact panel was
  rechecked independently: **34 passed**.
- Agent page: **146/146 passed** in bounded fresh-worker title shards.
  Two monolithic jsdom runs each reached 141 passing cases and then timed out on
  different late tests; every timed-out case passed alone and the complete
  assertion set passed in fresh workers. This is recorded as Sweep-01c test
  harness/performance debt, not hidden as a standard monolithic green run.
- Responsive browser acceptance: **4 passed** across **360 px** and **1,440 px**
  for the viewer/export and retained-history journeys.
- TypeScript project build: **passed**.
- Production frontend build: **passed**, **563 modules transformed**. The
  existing non-fatal chunk-size advisory remains.
- Generated API-contract drift check: **passed**.
- Repository privacy scan: **passed**.

Adversarial coverage includes malformed and extra response keys, cross-scope
identity, stale artifact revisions, wrong version/digest/size, contradictory
privacy flags, undeclared content, metadata races, stale or removed workspace
bytes, corrupt/encrypted PDF, malformed or oversized document archives,
download-only fallback, late responses after scope changes and object-URL
cleanup.

## Protected live-app gate

The production frontend was rebuilt and the prior exact repository listener was
replaced with one hidden localhost service. The final gate observed:

- `/health`: HTTP 200;
- exactly one listener on `127.0.0.1:8765`;
- zero `llama-server` or `llama-cli` model workers;
- the replacement was launched with a hidden window;
- the existing in-app `/agent` tab reloaded against the rebuilt service;
- one visible project/chat rail, one New chat control and one conversation
  region; and
- zero visible alerts and zero browser console errors.

The live smoke deliberately inspected only fixed shell controls and counts. It
did not read project names, chat titles, messages, workspace files, artifact
content or retained history. No model was loaded and no GPU acceptance was
attempted.

## Privacy and safety

- Tests use only fictional projects, paths, files, bytes, digests and lineage.
- No provider history, credential file, model weight or unrelated local content
  was inspected.
- No prompt, transcript, artifact byte or derived metadata was sent to a
  network service.
- The service remains loopback-bound. Viewer, export and download grant no
  reusable file, command, web, MCP or model-lifecycle authority.

## Click later

1. In a disposable local-history chat, open **Artifacts** and preview one small
   text/Markdown file, image, PDF and Office/OpenDocument file.
2. Exercise image/PDF zoom and page controls; confirm omitted Office features
   are disclosed and a corrupt or encrypted fixture never renders.
3. Compare two versions and use producing-turn navigation; confirm historical
   versions do not offer current-file actions.
4. Choose **Export lineage**, inspect the JSON, and confirm it contains the
   selected revision/version/digest but no artifact bytes or absolute workspace
   path.
5. Separately try **Download**, **Open current file**, **Reveal in files** and
   **Review changes** for an eligible latest version.

## Deliberately remaining

- Composer PDF input remains refused until isolated extraction has enforceable
  process time and memory caps.
- Physical CPU/GPU/split model acceptance, model switching and verified VRAM
  release remain on Acceptance-01; this checkpoint intentionally loaded no
  model.
- The monolithic Agent page jsdom file should be split or restructured under
  Sweep-01c so CI does not depend on late-suite garbage-collection timing.

The next proposed implementation checkpoint is **Orchestration-01a**: scoped,
revocable, terminal-free controller connections with two-client isolation and
zero inherited native approval authority. No commit or push was made for this
checkpoint.
