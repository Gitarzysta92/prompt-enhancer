# Agent checkpoint 08z — bounded external attachment staging

Date: 2026-08-28

## Outcome

Codex, Claude Code, or another explicitly connected local MCP client can now
stage caller-supplied PNG, JPEG, or PCM WAV media into one exact durable Agent
project and chat. The client sends bounded inline bytes with declared size and
SHA-256 identity; Prompt Enhancer validates them before storing the attachment.

The operation grants no filesystem path, URL-fetch, workspace-read, or raw-byte
return authority. It returns sanitized metadata and an attachment ID that a
later `agent_turn` can reference. The native composer can refresh the staged
list and labels externally staged media for owner review.

## Implemented boundary

- Added strict `StageInlineAgentAttachment` validation for media type, encoded
  size, decoded size, SHA-256 digest, safe display name, and standard base64.
- Added private, no-store
  `POST /v1/agent/projects/{project_id}/sessions/{session_id}/attachments/stage-inline`.
- Revalidates the catalog session-to-project relationship before staging;
  cross-project and cross-session requests are refused without disclosure.
- Advanced controller discovery to `local-agent-orchestration.v8`: 55 Agent
  routes plus five controller runtime routes.
- Added the specialized controller operation `stage_attachment_inline`; the
  generic invocation path refuses this larger request shape.
- Advanced the MCP surface to `prompt-enhancer-agent-mcp.v7` and added the
  dedicated `agent_stage_attachment` tool. The default surface now exposes 11
  bounded tools.
- Requires exact sensitive-egress acknowledgement and literal mutation
  authorization for the MCP operation.
- Returns neither base64 payloads nor attachment digests through MCP.
- Migrated the Agent catalog to schema 7 so attachment provenance can record
  `external_agent` while preserving every existing row and trigger invariant.
- Added **Refresh staged** to the composer and a visible **via external agent**
  provenance label.
- Regenerated OpenAPI and the checked TypeScript binding.

## Correctness cases covered

- successful project/chat-exact staging through HTTP, controller, and MCP;
- declared byte-size, digest, base64-alphabet, truncation, and media validation;
- extra path, URL, attachment ID, and authority fields are rejected;
- cross-project, cross-session, and response-identity confusion are rejected;
- the generic MCP/controller invocation cannot bypass the dedicated bound;
- ambiguous creation is not retried;
- MCP output cannot echo bytes or a reusable digest;
- browser contracts accept the new provenance and reject invalid values;
- composer refresh discovers externally staged media and renders provenance;
- schema 6 to 7 migration preserves synthetic attachment bytes, source, digest,
  indexes, and trigger behavior.

## Automated verification

- Expanded backend attachment, catalog, orchestration, controller, MCP, HTTP,
  integration, and OpenAPI slice: **126 passed**; one existing Starlette/httpx
  deprecation warning.
- Additional focused schema-migration preservation check: **1 passed**.
- Frontend contract, transport, composer, connection guidance, and Agent-page
  slice: **200 passed across six files**.
- OpenAPI generated-binding drift check: **passed**.
- Production TypeScript/Vite build: **passed**, 537 modules transformed.
- Python compilation and whitespace validation: **passed**.
- Ruff was unavailable in this environment, so no Ruff result is claimed.
- The unchanged repository privacy scanner reports exactly one known,
  pre-existing binary finding: `docs/checkpoint-agent-02-shell.png`. No new
  finding was introduced and no scanner rule or exclusion was changed.

## Live desktop acceptance

- Reloaded the rebuilt desktop app and the existing `/agent` browser tab.
- Verified the live Controller API is **Ready**, advertises
  `local-agent-orchestration.v8`, 55 Agent routes, and five runtime routes.
- Verified the live connection panel documents `agent_stage_attachment`, exact
  project/chat binding, no path-or-URL authority, and the native refresh step.
- Resumed one retained chat without loading a model; **Refresh staged** and
  **Send** appeared, while **Stop model** did not.
- Exercised **Refresh staged** live; the control remained available and no
  attachment-refresh error appeared.
- Final process state: one Prompt Enhancer window, one loopback listener on
  127.0.0.1:8765, none on 8766 or 4173, zero terminal-like windows, and zero
  local-model runtime processes.

The Windows accessibility bridge did not expose the old WebView process
identity for a clean Alt+F4 close. The reload therefore used only the two exact,
pre-verified Prompt Enhancer Python process IDs; no broad process kill or
terminal launcher was used. The relaunched app remained free of the prior
terminal-window cascade.

## Owner review later

1. Connect the intended local MCP client from **Agent settings → Connections**
   and verify its one-time credential flow.
2. Use `agent_stage_attachment` with a small synthetic PNG, JPEG, or PCM WAV
   bound to one selected project and chat.
3. Click **Refresh staged**. The item should appear with **via external agent**.
4. Attach that ID to a model turn and verify the model/runtime supports the
   media type; unsupported modality must remain an explicit refusal.
5. Repeat with a wrong digest, wrong project, and oversized payload; all must be
   refused without a partial attachment.

## Deliberate limits

- No provider configuration or real Codex/Claude client was modified in this
  checkpoint. Installed-client handshake remains an owner-visible acceptance.
- No model was loaded and no prompt was sent. Real multimodal inference, Stop,
  file-write approval, and native separate-window acceptance remain on the
  broader trajectory.
- Staging accepts caller-owned inline media only. It deliberately does not read
  local paths, fetch URLs, or return stored bytes to the external client.
- No commit or push was requested for this checkpoint.
