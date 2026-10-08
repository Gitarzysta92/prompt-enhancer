# Artifact-01c checkpoint handoff

Status: automated implementation and protected live gate complete; owner click
review pending

## Outcome

The Agent composer now admits capability-bound documents alongside the existing
PNG/JPEG, PCM-WAV and microphone paths. Supported documents are validated and
projected locally into bounded inert text, can be previewed before send, remain
recoverable after service reconstruction, and are sent only by their exact
staged identity.

This checkpoint does not claim universal document ingestion. PDF input remains
explicitly unavailable, and the complete generated-file viewer/open/download/
export matrix remains Artifact-01d.

## Frozen attachment contract

- `agent-attachment.v2` distinguishes `image`, `audio` and `document` and makes
  routing explicit: native multimodal bytes or local text projection.
- Native multimodal input remains PNG, JPEG and PCM WAV. A filename or claimed
  MIME type cannot create model capability.
- Supported document formats are UTF-8 plain text, Markdown, JSON, CSV, TSV,
  DOCX, PPTX, XLSX and ODT.
- Suffix, canonical MIME, signature/container structure, byte limits and
  verified runtime text capability must all agree. Malformed, spoofed,
  encrypted, empty, oversized or non-UTF-8 inputs fail closed.
- PDF input is refused before upload and by the backend. It stays locked until
  extraction can be isolated under enforceable process time and memory caps.
- Office/ODT originals never enter a model request or the browser preview
  route. Only bounded locally extracted text is routed to the model.
- Document text is wrapped as untrusted user-provided reference data. It cannot
  become an instruction merely because it came from a file.
- One message may reference at most four exact staged attachments, 16 MiB in
  total, and 200,000 projected document characters. Missing context-token cost
  remains unknown.
- Stage, remove, preview and send remain exact-session and exact-model bound.
  Model/scope changes abort pending UI work and late results are ignored.

## Persistence, preview and recovery

- Catalog schema v22 stores coherent routing, document format, projected
  character count, truncation and omitted-feature metadata.
- Existing retained v1 image/audio metadata upgrades in memory; retained
  history is not silently rewritten.
- Staged local-history documents survive service reconstruction. Recovery
  re-reads the private stored bytes, revalidates digest and projection metadata,
  and fails closed on drift or corruption.
- `agent-attachment-document-preview.v1` returns only a bounded no-store excerpt
  of the server projection. The original document-content route refuses
  document bytes.
- Office comments, embedded objects, external links, macros, media and notes
  are never executed and are reported as omitted when applicable.

## Interface behavior

- **Attach** opens image, audio, document and microphone actions without
  crowding the composer.
- **Add document** normalizes browser MIME omissions from the validated suffix,
  while the backend remains the admission authority.
- Staged document cards show format, size, projected characters, truncation and
  omitted features plus an expandable server-provided **Extracted preview**.
- Reopening a chat reloads staged metadata and obtains a fresh private preview;
  no client-side extraction is trusted for display or send.
- PDF selection produces an explicit refusal instead of silently doing nothing.
- Existing image/audio preview, recording, removal and attachment-only send
  behavior remains intact. Controls retain 44-pixel targets at narrow width.

## Controller and MCP propagation

- Controller discovery advances to `local-agent-orchestration.v18`: 66 Agent
  routes plus five runtime routes. It now includes bounded attachment document
  preview and the previously missing artifact update/remove declarations.
- Native-confirmed artifact removal is correctly marked as a native review gate;
  the manifest reports 12 such gates.
- Agent MCP advances to `prompt-enhancer-agent-mcp.v21` and
  `agent-mcp-context.v3`. Its attachment capability block reports supported
  document formats, local projection routing, explicit PDF refusal and all
  relevant limits.
- MCP document staging returns sanitized metadata only. Base64, digest,
  extracted text, original bytes and reusable path authority do not cross the
  response.

## Validation ledger

- Full Artifact-01c backend boundary set: **147 passed** across attachment,
  controller, MCP, real loopback integration and orchestration tests.
- Focused composer/Agent page/attachment/event/HTTP frontend suite:
  **376 passed** across five files.
- Controller parser/self-test/connections/UI/HTTP propagation suite:
  **234 passed** across five files.
- Exported OpenAPI and controller CLI contract suite: **20 passed**.
- Local runtime/process regression suite: **51 passed**. Hardware polling keeps
  GPU/RAM facts fresh while caching `llama-server --version` against the exact
  executable path, size and modification time.
- Responsive browser acceptance: **4 passed** across **360 px** and **1,440 px**
  for the document/media composer and controller surface.
- TypeScript project build: **passed**.
- Production frontend build: **passed**, **563 modules transformed**. The
  existing non-fatal chunk-size advisory remains.
- Generated API-contract drift check: **passed**.
- Repository privacy scan: **passed**.

Adversarial coverage includes MIME/suffix spoofing, binary magic in text,
malformed ZIP/XML, invalid UTF-8, malformed JSON/JSONL/tabular input, empty
projection, size and projected-character bounds, missing text capability,
cross-session/model identity, restart recovery, projection corruption, raw-byte
route refusal, PDF refusal, duplicate/stale attachment state and private-route
cache headers.

## Protected live-app gate

The production frontend was rebuilt and the prior exact two-process service
tree was replaced with one hidden localhost service. The final gate observed:

- `/health`: HTTP 200;
- exactly one listener on `127.0.0.1:8765`;
- zero local llama model workers;
- zero recurring llama version-probe processes across a 30-second sample
  spanning six open-Models-page poll intervals;
- no visible terminal launched by the replacement;
- the existing in-app `/agent` tab reloaded against the rebuilt service;
- one Agent shell, one Agent settings control and one New chat control; and
- no Agent connection-error banner.

The live gate also repaired a process churn found during its first census: the
open Models page had been launching `llama-server --version` on every five-second
overview poll. Those were short-lived hidden identity probes rather than a
loaded inference model, but the repetition was still incorrect. Version
evidence is now cached until the executable path, size or modification time
changes; dynamic GPU and RAM facts continue to refresh.

The live smoke deliberately did not inspect project names, chat titles,
messages, workspace files or retained content. No model was loaded and no GPU
acceptance was attempted.

## Privacy and safety

- Tests use only fictional projects, paths, documents, bytes and digests.
- No provider history, credential file, model weights or unrelated local
  content was inspected.
- No prompt, transcript, attachment projection or derived data was sent to a
  network service.
- The service remains loopback-bound and this checkpoint grants no unreviewed
  file, command, web, MCP or model-lifecycle authority.

## Click later

1. On localhost, open or create a disposable chat with a text-capable local
   model, choose **Attach → Add document**, and select a small synthetic `.md`
   file.
2. Expand **Extracted preview**, confirm it is the server projection, reload the
   page before sending, and confirm the staged document and preview recover.
3. Send the document with an empty text box and confirm the sent message shows
   document format and projection metadata.
4. Select a `.pdf` and confirm the UI explains that PDF input is intentionally
   unavailable and stages nothing.
5. Optionally repeat with a disposable DOCX/PPTX/XLSX/ODT and review any omitted
   feature disclosure, then check one image, WAV and microphone recording.

## Deliberately remaining

- **Artifact-01d:** complete safe viewer/open/download/export behavior and
  exact-byte lineage acceptance across text, code, image, PDF and inert Office
  formats.
- Physical CPU/GPU/split model acceptance, model switching and verified VRAM
  release remain on Acceptance-01; this checkpoint intentionally loaded no
  model.

The next proposed implementation checkpoint is Artifact-01d. No commit or push
was made for this checkpoint.
