# Local models and agent access

How to use the models installed on the Models page from other tools, and how
to let a coding agent ask the app about your metrics. Everything stays on the
machine: the model runtime listens on loopback only, the app proxies it under
the app token, and the MCP server speaks over stdio.

## Where things live

- App token: `api.token` in the app home (`%LOCALAPPDATA%\PromptEnhancer` on
  Windows). The dashboard uses a browser session instead; other programs send
  the token.
- Model storage root: `PROMPT_ENHANCER_LOCAL_MODELS_DIR`, or the
  `local-models.path` file in the app home, or `<app home>/local-models`.
  Weights land under `weights/<repo>/`, the llama.cpp runtime under
  `runtimes/llama.cpp/llama-server(.exe)`, the registry in `registry.json`.

## Chat with an active model

Any model shown as *running* on the Models page answers on three equivalent
routes (all OpenAI chat format, `stream: true` supported):

```text
POST /v1/local-models/{alias}/chat/completions
POST /v1/local-models/{alias}/v1/chat/completions      # base URL style, per model
POST /v1/local-models/openai/v1/chat/completions       # one base URL, routed by "model"
GET  /v1/local-models/{alias}/v1/models
GET  /v1/local-models/openai/v1/models                  # every running alias
```

Authentication: `X-Prompt-Enhancer-Token: <token>` or
`Authorization: Bearer <token>`. The second form is what OpenAI clients send,
so they work unchanged with:

```text
base_url = http://127.0.0.1:8765/v1/local-models/openai/v1
api_key  = <placeholder: the contents of api.token>
model    = <alias>          # for example orca27b-iq3m
```

curl, streaming, thinking switched off for a quick answer:

```bash
curl -N -H "Authorization: Bearer $(cat "$LOCALAPPDATA/PromptEnhancer/api.token")" \
  -H "Content-Type: application/json" \
  -d '{"model":"orca27b-iq3m","stream":true,"chat_template_kwargs":{"enable_thinking":false},"messages":[{"role":"user","content":"One sentence: what does git rebase do?"}]}' \
  http://127.0.0.1:8765/v1/local-models/openai/v1/chat/completions
```

Python (`openai` package):

```python
from openai import OpenAI
token = open(TOKEN_PATH).read().strip()  # the app token; never commit it
client = OpenAI(base_url="http://127.0.0.1:8765/v1/local-models/openai/v1", api_key=token)
reply = client.chat.completions.create(
    model="orca27b-iq3m",
    messages=[{"role": "user", "content": "Write a conventional commit message for: fix retry loop"}],
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
print(reply.choices[0].message.content)
```

Notes:

- Qwen3-family models think before answering unless `enable_thinking` is
  false; the Models page chat box has it off by default and a toggle.
- Streamed replies are relayed as server-sent events unchanged and capped at
  16 MB; a context overflow comes back as the runtime's HTTP 400 JSON.
- The aliases `openai`, `downloads` and `remote-files` are reserved.
- The runtime port itself is never exposed; only the app's loopback API is.

## Multimodal input in the Agent workspace

A local GGUF is text-only unless its registry record names an explicit local
multimodal projector in `mmproj_path`. Activation passes that path to
`llama-server` as `--mmproj`. Folder scans deliberately skip projector files
and never guess which projector belongs to which model.

The shared runtime reports `local-runtime-multimodal-probe.v2`. Vision, audio,
and microphone eligibility become available only when the exact served alias
passes the live runtime probe; names, model-card claims, file suffixes, and a
registered projector path are not sufficient. A failed or unavailable probe
leaves the controls disabled. Audio input remains experimental in llama.cpp.

The Agent composer admits only locally structure-validated PNG/JPEG images and
PCM WAV audio. It supports file selection, local previews, explicit removal,
attachment-only messages, and—in browser/native windows with microphone
permission—local mono PCM-WAV recording. The current limits are four
attachments and 16 MiB per message, 16 staged attachments and 64 MiB per chat,
8 MiB per image, 12 MiB per WAV, 8,192 pixels per image dimension, 33,554,432
pixels, and five minutes per admitted WAV. The recorder stops at two minutes.
Staged items expire after one hour.

Private attachment routes are:

```text
GET    /v1/agent/sessions/{session_id}/attachments
POST   /v1/agent/sessions/{session_id}/attachments?name={display_name}&source={file|microphone}
POST   /v1/agent/projects/{project_id}/sessions/{session_id}/attachments/stage-inline
GET    /v1/agent/sessions/{session_id}/attachments/{attachment_id}/content
DELETE /v1/agent/sessions/{session_id}/attachments/{attachment_id}
```

The upload body is the media bytes with an admitted `Content-Type`. Sending a
turn uses `{"text":"...","attachment_ids":["..."]}`. The server rechecks
session ownership, exact model alias, live capabilities, expiry, digest, size,
count, and single-use state immediately before inference. Image content is
forwarded as OpenAI `image_url`; WAV is forwarded as `input_audio`. Event and
history records contain payload-free identity only. Metadata-only chats delete
sent payloads; Save locally chats retain their private payload for exact restart
recovery until the chat is deleted. Responses use private/no-store headers.

The project-scoped `stage-inline` route is reserved for authenticated local
controllers. Its strict JSON body contains a safe display name, media type,
declared byte count, SHA-256 digest, and standard base64 data—never a path or
URL. It validates integrity and media structure, records
`source=external_agent`, and returns metadata without echoing bytes.

llama.cpp does not currently report per-attachment context tokens through this
path, so the UI says **context cost unknown**. It does not invent a token count
or silently subtract media from the displayed context limit.

## Orchestrate the authored Agent workspace from a local controller

Codex, Claude Code, or another local HTTP-capable controller can discover the
provider-neutral Agent contract at:

```text
GET /v1/agent/orchestration
```

The route currently returns `local-agent-orchestration.v22` and uses the same
Bearer or `X-Prompt-Enhancer-Token` authentication as
local-model chat. It returns paths and safety boundaries only: never the token,
a workspace path, a transcript, or provider credentials. The published schemas
remain available at `GET /openapi.json`.

A controller flow is:

1. Read the orchestration manifest.
2. Ensure the selected model and CPU/GPU/split placement are ready through the
   revision-bound `agent-controller runtime` command. Stop on activation or
   cleanup uncertainty rather than repeating the mutation.
3. Create or select a durable project under `/v1/agent/projects`.
4. Optionally branch a retained chat through its latest or one exact completed
   turn with `POST /v1/agent/projects/{project_id}/sessions/{session_id}/forks`.
   Reuse the exact request id after an ambiguous result; the child receives no
   approval or mutation authority.
5. Open a live chat with `POST /v1/agent/sessions`, including the project id,
   admitted absolute workspace path, and installed local-model alias.
6. Send one turn to `/v1/agent/sessions/{session_id}/messages` only while the
   chat is idle. This submission is non-idempotent; do not blindly retry an
   ambiguous response.
7. Poll `/events?after={sequence}` or consume `/events/stream` until the turn is
   drained. Use the returned sequence as the next cursor and stop only when
   running/closing/stopping/cleanup are all false, no approval is pending, and
   the cursor reached `last_seq`. If native review is required, continue with
   `agent-controller wait` from the returned cursor instead of sending again.
   The SSE relay emits the final JSON state for either settlement or cleanup
   quarantine; a closed stream without a validated final page proves nothing.
8. Call `/stop` to cancel only the turn, or delete the live session to close it.
   When the model is no longer needed, use `agent-controller runtime` with
   `desired_state: stopped` and require clean idle/process-exit evidence.

The recommended integration is a scoped direct MCP connection created in the
Agent window under **Connection & setup**. It returns one-time private Codex and
Claude Code configuration, edits no provider file, and connects to the already-
running loopback app without launching a bridge process or terminal. The
server stores only bounded connection metadata and a credential revision; the
bearer secret is derived, can be rotated, expires, and stops working immediately
after revocation.

The setup card separates configuration readiness, local endpoint evidence, and
external-client evidence. It parses both generated provider snippets against
one canonical contract and guides the owner through token, config, and
verify/delegate steps for the chosen client. An optional in-app self-test uses
the hidden one-time token only from page memory to perform the real MCP
handshake, verify the exact scoped tool surface, and call `agent_discover`.
It refuses non-loopback or cross-origin destinations before sending the bearer
and starts no model, process, terminal, project, chat, or workspace effect.
The resulting request receipt proves the app endpoint, not that Codex or Claude
is configured; that remains a separate read-only client verification plus
external tool call. Prompt Enhancer never runs the copied client command or
edits provider settings. Invalid endpoint data still fails before any
connection row or credential revision is created.

For a token-free environment-variable template, use:

```text
prompt-enhancer agent-mcp-config
```

The template targets Streamable HTTP at `/mcp/agent`, starts no subprocess, and
expects `PROMPT_ENHANCER_AGENT_MCP_TOKEN` in the client environment. Its
default tools are `agent_discover`, `agent_invoke`, `agent_open`,
`agent_resume`, `agent_fork`, `agent_export`, `agent_close`, `agent_catalog`, `agent_history`, `agent_artifacts`, `agent_stage_attachment`,
`agent_context`, `agent_workspace`, `agent_propose`, `agent_propose_transaction`, `agent_propose_lifecycle`,
`agent_turn`, `agent_stop`, and `agent_wait`.
`agent_catalog` strictly browses durable project/chat metadata and permits only
explicit revision-bound create, rename, pin, move, archive, and restore
mutations. It exposes no permanent delete action. `agent_history` reads bounded
locally retained visible events without live approval or raw tool payloads.
`agent_artifacts` lists or gets immutable document lineage metadata and can
preview one exact generated-output candidate as path/type/size/digest metadata,
but never returns file bytes or captures the file. Capture remains a separate
native-confirmed Agent UI action. `agent_context` reports sanitized current
runtime, exact session-and-turn-bound request-context evidence for a selected chat, model/adapter
compatibility, placement vocabulary,
verified image/audio/document/recording support and optional exact live-chat plus staged
attachment metadata. It omits workspace paths, standing instructions, process
IDs, digests and attachment bytes and performs no token counting or lifecycle
change. New, recovered, model-switched, or not-yet-preflighted chats stay
explicitly unmeasured. `agent_workspace` is a strictly read-only shortcut for
bounded inventory, tree, UTF-8 file, reviewed-change and diff inspection; file
effects still require native review. Use `agent_turn` to delegate authorship to
the selected local model, or `agent_propose` to offer caller-authored exact
UTF-8 content. The latter accepts only target-absent creates or exact-revision
edits, applies nothing on acceptance, and settles only after the native diff is
approved, denied, stopped, or timed out. For two to eight mixed file changes,
`agent_propose_transaction` provides one combined native review and the same
rollback-capable failure-atomic publication used by local-model write batches.
Each member is explicitly an absence-bound `create` or an exact-revision-bound
`edit`. If a later member fails, earlier edits are restored and only an exact
same-transaction create may be removed; a replaced path becomes unverified.
The controller still has no direct apply, delete, or approval authority. Model lifecycle
is selected when the scoped connection is created and is never inferred from
the template.

For **Save locally** chats, an approved and independently verified external
create/edit retains only its bounded write receipt. That receipt projects to
the same durable, immutable artifact card as a native reviewed write and is
available again after restart. Proposal content, diffs, approval identities,
denied/failed/unverified attempts, and all metadata-only chat proposals remain
live-only.

`agent_propose_lifecycle` covers the remaining reviewed path operations without
expanding controller authority: directory create, no-overwrite directory or
file move, and exact-revision file removal to the Windows Recycle Bin. It is
idempotent by request id, changes nothing on acceptance, presents one native
review, and settles through `agent_wait`. A stale source, changed review,
occupied target, denial, timeout, or Stop cannot become a success receipt.
For a **Save locally** chat, a verified file move rehashes its destination and
advances a digest-matching artifact under the same ID as an immutable path
version. A stale artifact is left at its prior path, an existing destination
artifact is never merged or overwritten, and uncertainty is surfaced instead
of reported as success. Directory moves and recoverable trash do not yet move
artifact lineage.

`agent_stage_attachment` is the only MCP attachment-ingress path. It requires
literal mutation authorization, exact project/chat identity, caller-supplied
integrity declarations, and inline PNG/JPEG/PCM-WAV or supported document data.
Documents are locally projected to bounded inert text; PDFs fail closed and
original Office bytes do not reach the model. The tool cannot browse a
filesystem, accept a path or URL, read another attachment, return bytes, or
approve a send. Review the admitted item with **Refresh staged** in the native
composer, then reference its ID in `agent_turn`.

`agent_stop` is the dedicated external cancellation path. It requires literal
mutation authorization, targets one exact live chat and event cursor, sends at
most one Stop request, and then drains only bounded event evidence. Idle and
already-stopping chats are not mutated again. Ambiguous delivery is never
retried and cannot be reported as stopped without terminal cleanup evidence.

The Models page may refresh dynamic GPU/RAM and runtime facts every five
seconds. The `llama-server --version` identity probe is not repeated on each
poll: its result is cached against the executable's exact resolved path, byte
size and modification time and is invalidated when that revision changes. On
Windows both the initial version probe and runtime launch retain the
console-free process policy.

`agent_resume` is the dedicated retained-chat continuation path. It requires
literal mutation authorization plus the exact current catalog and history
revisions. It refuses stale, archived, metadata-only, unavailable, or
cross-project records before mutation, does not mutate an already-live chat,
and attempts an actual resume at most once. Ambiguous delivery receives one
read-only live-chat reconciliation. A recovered chat always returns with
writes, commands, and web disabled and with native authority explicitly not
revalidated.

`agent_fork` is the dedicated retained-history branching path. It requires
literal mutation authorization, exact source identity and revisions, and a
caller-owned idempotency key. A trusted client rejection is not retried; an
ambiguous first result may receive one byte-identical retry with that same key.
The child is inert and durable, and the strict receipt must prove that no
approval, mutation authority, pending tool state, staged attachment, or
artifact was copied.

`agent_export` returns one complete retained-history projection only when the
project/chat identity, catalog revision, history revision, and caller-selected
event ceiling all match. It is read-only, but still requires the per-call
authorization/redaction receipt because visible conversation text enters the
connected context. The returned projection omits the workspace path,
attachment bytes, live approvals, raw tool payloads/previews, and mutation
authority. Use paginated `agent_history` instead when a chat exceeds the chosen
export ceiling.

`agent_close` is the only MCP live-chat close path. It requires literal
mutation authorization and exact project/chat, catalog-revision, and
history-revision identity. It accepts only an idle chat, closes the live
runtime once, and preserves the durable chat record plus any retained history.
Ambiguous delivery is observed through one read-only live/catalog check and is
never retried. Permanent deletion remains available only in the native Agent
UI.

For a client that cannot speak Streamable HTTP, the old stdio server remains an
advanced fallback:

```text
prompt-enhancer agent-mcp-config --transport stdio
prompt-enhancer agent-mcp-config --transport stdio --with-model-lifecycle
```

Every sensitive MCP call requires a task-specific authorization and redaction
receipt. Generic POST/PATCH mutations require explicit authorization; generic
DELETE and every durable delete stay refused. Only the dedicated live-runtime
`agent_close` is admitted. Native approvals remain
impossible through MCP. Prompt Enhancer must already be running. Direct HTTP
launches no app, agent, model, shell, subprocess, or terminal. The stdio
fallback owns one client-managed bridge subprocess and is not the recommended
Windows setup.

For a controller that does not speak MCP, the lower-level bridge performs one
bounded stdio JSON exchange per action:

```text
prompt-enhancer agent-controller-config
prompt-enhancer agent-controller discover
prompt-enhancer agent-controller runtime --acknowledge-sensitive-context-egress --acknowledge-model-lifecycle
prompt-enhancer agent-controller open --acknowledge-sensitive-context-egress
prompt-enhancer agent-controller close --acknowledge-sensitive-context-egress
```

Codex, Claude Code, or another controller can invoke the declared `invoke`,
safe `runtime`, safe `open`, exact live-only `close`, finite `turn`, and
non-mutating `wait` commands as explicit local tools. `runtime` performs at most one revision-bound model
switch or stop and one read-only ambiguity reconciliation; it never repeats a
lost mutation. `open` validates one existing or newly created project plus one
live chat, never retries ambiguous creation, and returns a known project for
explicit reconciliation when session creation is uncertain. `close` requires
literal mutation authorization plus the current project/chat, catalog-revision,
and history-revision identity; it sends at most one live close request and
retains the durable catalog/history record. The bridge reads
the existing private token itself, never places it in arguments or output,
disables redirects and environment proxies, and never launches the app,
another agent, or a terminal. Only the explicitly acknowledged `runtime`
command may ask the running app to load or unload its owned model. Sensitive
commands require both the command-line context-egress acknowledgement and a
task-specific authorization/redaction receipt in their stdin envelope. See the
complete examples and result states in
[the controller API guide](agent-controller-api.md).

PowerShell discovery with placeholders (do not print or commit the real token):

```powershell
$controllerBase = "http://127.0.0.1:8765"
$controllerHeaders = @{ Authorization = "Bearer <token supplied as a secret>" }
Invoke-RestMethod -Uri "$controllerBase/v1/agent/orchestration" -Headers $controllerHeaders
```

Token-authenticated controllers cannot approve a write, command, web fetch, or
reviewed workspace apply. Those decisions remain in the owned native Agent UI
and require a fresh user-presence confirmation. A controller may cause the
local model to *propose* such an action, then wait while the user reviews it.

Event pages can contain prompts, replies, tool arguments, results, and workspace
content. Before a network-backed controller reads them into provider context,
the user must explicitly authorize that task-specific egress and receive a
redaction preview. Do not log event pages or put the app token in a prompt.

See the [local Agent controller API](agent-controller-api.md) for the complete
finite-state protocol, restart/model rules, immutable artifact endpoints, and
the exact boundary between an external controller and native human approval.

## Discover third-party MCP servers

**Agent settings → MCP Store** searches the public Official MCP Registry. The
Store can currently search, filter local packages versus remote servers, page
through results, inspect normalized publisher/version/transport/package
metadata, and open an exact version-bound safety/setup-plan review. It uses a
bounded exact-query fallback cache and safe local raster icon proxy; entries
with no trustworthy declared icon use initials.

Discovery, review and prepared plans remain non-executing. After native
confirmation, an exact reviewed option can be retained as a **Prepared plan**
with revision-bound future permissions for one Agent project. Secret values can
be stored in Windows Credential Manager; SQLite and API responses retain only
content-free state, and project plans remain `inactive_host_unavailable`.
Non-secret custom values are not collected yet.

A ready fixed HTTPS remote plan can now run one native-confirmed compatibility
check. Immediately before connecting, the service re-fetches the exact Registry
record, recomputes its plan digest and reads any configured secret from the OS
vault. The guarded client accepts only public DNS answers pinned to the reviewed
origin, ignores proxies, refuses redirects, bounds negotiation, pagination,
response bytes and schema complexity, and never calls a tool. The connection is
closed before a receipt is returned. Only protocol version, tool count, a
schema digest, duration and cleanup truth are stored; endpoint path/query,
headers, credentials, tool names/schemas and results are not stored or shown.

Prompt Enhancer still does not install a package, persistently host a third-
party server, update or uninstall one, edit Codex/Claude settings, or route a
third-party tool to the local model. Local package plans therefore cannot start
their already-tested hidden stdio adapter until guarded installation supplies
an exact executable. Every plan still keeps **Install unavailable** disabled.
See the [MCP Store-04 handoff](checkpoint-mcp-store-04-handoff.md) for the exact
compatibility boundary and install/tool-routing trajectory.

The Store and `/mcp/agent` solve opposite directions:

- `/mcp/agent` lets Codex, Claude Code, or another authorized client control
  Prompt Enhancer's existing Agent capabilities;
- the Store will eventually let Prompt Enhancer act as a client of explicitly
  installed third-party MCP servers.

They must not share credentials or silently inherit one another's authority.

## Let Codex or Claude Code query your metrics (MCP)

```bash
prompt-enhancer mcp-config
```

prints the snippets for Claude Code (`.mcp.json` / `~/.claude.json`, or the
`claude mcp add` one-liner) and Codex (`~/.codex/config.toml`). The server is
started by the agent itself as a stdio child:

```text
python -m prompt_enhancer mcp --acknowledge-context-egress
```

Without the flag (or `PROMPT_ENHANCER_MCP_ACKNOWLEDGE_CONTEXT_EGRESS=1`) it
prints why it refused and exits with status 2: every value a tool returns
enters the connected model's context and may leave the device through that
model's provider. The tools are read-only and bounded ([ADR 0014](adr/0014-read-only-agent-surface.md)):

| Tool | Returns |
|---|---|
| `list_metric_definitions` | metric key, dimension, name, description, unit, source |
| `list_sessions` | up to 50 sessions per page: ids, provider, project and session names you show in the dashboard, timestamps, terminal state |
| `get_session_metrics` | stored metric results for one session (values or states, coverage, confidence) |
| `summarize_period` | last N days (≤ 365): sessions per provider, top projects, sessions with a known value per metric (≤ 300 most recent, `truncated` flagged) |
| `explain_metric` | the definition and how to read known / unknown / not applicable |
| `get_calibration_status` | rating progress and the local judge's agreement per model (labels only) |

No tool returns transcript text, raw events, file paths, tokens, or model
replies, and there is no generic query.

## Check a prompt before acting on it

The same check the *Prompt check* page runs is available to agents:

- `check_prompt` MCP tool (above) - the agent sends the prompt and, if it has
  them, the earlier turns as `prior_messages`; it gets the cues, the context
  inference, the local model's commentary and a reformulated prompt. When the
  dashboard server is running the MCP process forwards to it so the active
  model answers; otherwise the deterministic cues come back alone.
- `POST /v1/prompt-checks` with the app token - body `{"prompt": "...",
  "prior_messages": [{"role": "user", "content": "..."}], "provider":
  "claude_code", "want_commentary": true}`.
- Claude Code hook: `prompt-enhancer claude-prompt-check-config` prints the
  `UserPromptSubmit` snippet; once merged into `~/.claude/settings.json`, every
  prompt of four words or more is checked and the advice reaches the model as
  additional context. `PROMPT_ENHANCER_PROMPT_CHECK_HOOK=0` switches it off,
  `PROMPT_ENHANCER_PROMPT_CHECK_COMMENTARY=0` keeps it deterministic-only
  (sub-second), `PROMPT_ENHANCER_PROMPT_CHECK_TIMEOUT_SECONDS` bounds the wait.

Nothing but metrics is stored; the prompt text never leaves 127.0.0.1.
