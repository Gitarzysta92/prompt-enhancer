# Local Agent controller API

Prompt Enhancer exposes the same Agent project, chat, turn, event, and artifact
lifecycles used by its browser UI through an authenticated **loopback-only**
HTTP API. A locally running Codex, Claude Code, or another controller can use
this surface to coordinate a Prompt Enhancer local-model chat without gaining
the ability to silently approve file writes, commands, web fetches, recovered
authority, or manual artifact capture.

The machine-readable discovery document is:

```text
GET /v1/agent/orchestration
```

It currently reports `local-agent-orchestration.v22`. The document contains no
token, workspace path, prompt, transcript, or account data. The full request
and response schemas are available from `GET /openapi.json`.

In the Agent window, expand **Connection & setup** to verify the live contract,
route counts, and native-review boundary. **Direct app connections** is the
recommended MCP path. Token-free templates, the stdio fallback, and lower-level
scripts stay under **Advanced**. The card never renders a connection secret.

## Authentication and privacy boundary

- Connect only to the loopback listener owned by the running Prompt Enhancer
  instance. Remote listeners are unsupported.
- Raw `/v1` controller clients use the private application API token as either
  `Authorization: Bearer <token>` or `X-Prompt-Enhancer-Token: <token>`.
  `/mcp/agent` deliberately rejects that broad token and accepts only a scoped
  connection bearer created in the native Agent window. Never put either
  credential in a prompt, repository, log, screenshot, or command transcript.
- Project names, relative artifact paths, retained messages, event streams,
  summaries, and derived data are sensitive local data. A controller must not
  relay them to a remote model without a task-specific instruction and a
  redaction preview.
- Token-authenticated controllers cannot approve protected effects. A pending
  approval must be surfaced in the native Agent window for a human decision.
- The read-only analytics MCP still has no raw-transcript tool. The separate
  Agent MCP bridge below can return only the project/chat/event data selected
  by an explicitly authorized tool call; it is an overt sensitive-context
  boundary, not a covert analytics export.

## Recommended direct Agent MCP connection

Codex, Claude Code, and any other Streamable HTTP MCP client can call the
controller as standard tools without a console bridge. Before granting any
authority, Agent settings loads an authenticated, read-only setup preview from:

```text
GET /v1/integrations/agent-mcp/setup
```

The response is bound to the exact loopback origin of the running app and
contains the canonical Codex TOML, Claude JSON, and both token-free add
commands. It contains no credential and explicitly reports that connection
authority is not granted, native connection creation is still required, no
process or terminal starts, and no provider configuration changes. The
frontend rejects any drift in those values before rendering the preview.

In the owned native Agent window:

1. open **Connection & setup** and inspect the disconnected exact-client preview;
2. choose a label, client kind, expiry, and whether model lifecycle requests
   are permitted;
3. approve **Create direct connection** in the native confirmation dialog;
4. optionally run the bounded local endpoint self-test;
5. copy the one-time token, then either copy the token-free client install
   command or the matching Codex/Claude configuration document;
6. verify the named server, send the orchestration starter, and then clear the
   private setup box.

The setup card shows the protocol path as `POST /mcp/agent`. After creation it
shows and can copy the exact loopback URL returned by the running app, which is
the value an arbitrary Streamable HTTP MCP client should use. A copyable,
provider-neutral orchestration starter describes the normal `agent_discover` →
`agent_open` → `agent_context` → `agent_turn` flow, native-review pause, exact
workspace/artifact inspection, and live-only close. Existing connection cards
report either **Never connected** or the server-recorded last authenticated MCP
request after an explicit refresh. That request may come from the optional
in-app endpoint self-test or an external client; the receipt deliberately does
not infer which. For completed tool calls they also report the last validated
tool name, `succeeded`/`failed` protocol outcome, and time. Management contract
`agent-mcp-management.v2` additionally carries a random current-process epoch
and one monotonic, credential-revision-bound tool-admission cursor per listed
connection. The cursor exposes only the tool name/source, start/completion
times, and protocol outcome; it can therefore identify an in-flight call and a
missed sequence without retaining arguments or results. It resets under a new
epoch on service restart. This
receipt is deliberately content-free: no tool arguments, result, prompt, path,
project/chat identity, token, or exception is stored. The authenticated-request
timestamp proves only that the scoped credential reached this app, while the
tool receipt proves only that the named MCP call settled at the protocol
boundary; neither claims that a turn, reviewed write, artifact, or cleanup
completed.

The copied configurations and install commands do not embed the bearer. Set the
separately copied one-time value as `PROMPT_ENHANCER_AGENT_MCP_TOKEN` in the
environment that launches Codex or Claude Code. Codex reads it through
`bearer_token_env_var`; Claude expands the same variable inside its
`Authorization` header. Prompt Enhancer copies but never runs either command:

```text
codex mcp add prompt-enhancer-agent --url http://127.0.0.1:8765/mcp/agent --bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN
claude mcp add --transport http --scope local --header 'Authorization: Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' prompt-enhancer-agent http://127.0.0.1:8765/mcp/agent
```

The exact port follows the running app. The Claude one-liner is generated for
PowerShell or a POSIX shell so the single-quoted `${...}` placeholder remains a
literal environment reference. The config document remains the portable
fallback for other shells and managed client installations.

The create/rotate response and `agent-mcp-config` command use one canonical
generator. Before either snippet is returned, Prompt Enhancer parses the Codex
TOML and Claude JSON and requires the exact loopback URL, environment-variable
reference, Streamable HTTP transport, 330-second tool timeout, and prompt-mode
Codex tool approval policy. A malformed or non-loopback endpoint fails before
creating or rotating durable connection authority. The shapes follow the
official [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
and [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)
contracts.

The client connects directly to:

```text
POST http://127.0.0.1:8765/mcp/agent
```

The exact port follows the running app. Direct HTTP starts no bridge process,
shell, terminal, model, Agent, worker, or second listener. The app stores the
connection identity, label, expiry, lifecycle scope, revision, and revocation
state plus the bounded last-request and content-free last-completed-tool
receipt, but not the bearer secret or tool content. Rotation invalidates the
previous credential immediately; expiry, revocation, and the completed receipt
survive restart. The admission cursor is deliberately process-bound and starts
under a fresh epoch after restart so page-only acceptance cannot combine calls
from different app runs. The general
application API token and browser session are not accepted at the MCP endpoint.

Create, rotate, and revoke require an exact, one-shot native user-presence
confirmation. The credential appears only in the private create/rotate response
and is kept in page memory for explicit copy actions; it is not placed in the
DOM, browser storage, logs, or the connection list. Prompt Enhancer never edits
Codex or Claude configuration itself.

The one-time private setup is a three-step client-specific guide rather than an
unstructured button list: copy the hidden token; copy either the token-free
install command or exact Codex/Claude configuration; then copy a read-only
client verification command and the orchestration starter. Its preflight
distinguishes four facts: the endpoint is
an exact loopback address, the selected configuration shape passed local
parsing, whether the optional local protocol self-test passed, and whether this
server has observed any authenticated MCP request. The self-test performs only
`initialize`, `notifications/initialized`, exact `tools/list`, and
`agent_discover` with the hidden token held in page memory. It rejects a
non-loopback, credential-bearing, queried, fragmented, wrong-path, or
cross-origin URL before sending the bearer. It starts no model, process,
terminal, project, chat, or file action. A pass proves this app endpoint and
the exact nineteen-core-tool surface; it does not prove that Codex or Claude
Code is configured. Use the read-only client verification command, make one
external tool call, and then **Refresh connection status** for that owner gate.

For a token-free environment-variable template, run:

```text
prompt-enhancer agent-mcp-config
```

The command reads no credential and creates no private state. Codex uses
`bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"`; the Claude JSON
uses the equivalent header placeholder. It also prints the same token-free
Codex and Claude Code registration commands shown by the native connection
card. The emitted JSON/TOML shapes remain canonical and locally parsed.

The automated acceptance suite also exercises this boundary through a real
disposable loopback listener. A synthetic MCP client opens a durable Agent
project/chat, submits one revision-bound edit plus one absence-bound create,
observes that neither file changes before review, crosses one one-shot
browser/native approval, waits for settlement, replays the idempotent proposal,
and reads both exact verified revisions through `agent_workspace`. It then
submits a revision-bound file move through `agent_propose_lifecycle`, crosses a
second native approval, and reads the verified destination back. For a **Save
locally** chat it also proves that the destination remains the same artifact
ID with a new immutable `reviewed_move` version and no file content in MCP
metadata. The run
forbids child-process creation and never calls a model. This proves the app
workflow; it does not claim that an owner's Codex or Claude installation has
connected or that a real protected change was approved.

Each project-scoped direct connection advertises nineteen tools. The scoped
surface omits generic `agent_invoke` and adds `agent_control`; the unscoped
stdio fallback retains `agent_invoke` and has no ownership-control tool:

| Tool | Finite operation |
|---|---|
| `agent_discover` | verify the complete content-free v19 controller manifest |
| `agent_control` | inspect durable controller ownership or perform a revision-bound two-party handoff without transferring native approval authority |
| `agent_open` | create/select one durable project and open one validated chat |
| `agent_resume` | revision-bound resume of one retained chat without restoring protected authority |
| `agent_fork` | idempotently branch one exact retained-history prefix without copying authority |
| `agent_export` | export one complete exact-revision retained history without a workspace path or protected state |
| `agent_close` | close one exact idle live chat without deleting its durable record or retained history |
| `agent_catalog` | strictly list/get projects and chats or explicitly create, rename, pin, move, archive, and restore their metadata |
| `agent_history` | page through one exact locally retained visible conversation without live authority or raw tool payloads |
| `agent_artifacts` | list/get immutable artifact lineage, export one exact-readback metadata record, or preview one exact workspace capture candidate without returning file bytes or capture authority |
| `agent_stage_attachment` | stage an integrity-bound caller-supplied image, audio clip, or supported document for one exact project/chat without local path authority or byte-return capability |
| `agent_context` | read sanitized runtime/context/model/attachment truth and optionally one exact live-chat/attachment-metadata snapshot |
| `agent_workspace` | inspect, search, or read one bounded workspace view without changing a file |
| `agent_propose` | submit one exact create or revision-bound edit to the native diff card without applying it |
| `agent_propose_transaction` | submit two to eight exact absent-bound creates or revision-bound edits for one native review and rollback-capable publication without direct apply authority |
| `agent_propose_lifecycle` | submit one exact directory create, no-overwrite directory/file move, or revision-bound recoverable file removal for native review without direct apply authority |
| `agent_turn` | submit one message and observe one bounded turn |
| `agent_stop` | explicitly stop one exact live turn at most once and require bounded terminal cleanup evidence |
| `agent_wait` | continue from a returned cursor without resubmitting or stopping |

Model lifecycle is absent unless the owner enables it on that exact connection.
That scope adds `agent_runtime`; each runtime call must still carry
`model_lifecycle_authorized: true`. The mutation is attempted at most once and
ambiguous results are reconciled read-only.

Every sensitive tool input carries the same strict `egress` receipt shown
below. Generic `agent_invoke` additionally requires
`mutation_authorized: true` for POST or PATCH. Generic DELETE operations are
refused through MCP. The dedicated `agent_close` tool can remove only a live
runtime; permanent project/chat/history deletion remains an explicit Agent UI
action. The bridge also refuses native-only approvals,
binary responses, SSE responses, and raw runtime mutation. Protected file,
command, and web actions stay pending for native review.

Turn cancellation is available only through `agent_stop`, not generic
`agent_invoke`. It requires literal `mutation_authorized: true`, an exact chat
identity and event cursor, and a drain timeout from 0.1 to 30 seconds. An idle
chat is observed without mutation; an already-stopping chat is never sent a
duplicate request. Otherwise Stop is attempted once. A lost or malformed
response is reconciled only by bounded event reads and is never retried.
`stopped` requires complete terminal evidence; delivery without that evidence
remains `stop_uncertain` or `incomplete`, and cleanup quarantine remains
`cleanup_unconfirmed`.

Retained-chat continuation is available only through `agent_resume`, not
generic `agent_invoke`. It requires literal `mutation_authorized: true`, exact
project/chat identity, and the exact current catalog and history revisions.
Archived, metadata-only, unavailable, stale, or cross-project records fail
before mutation. An already-live exact chat returns without mutation;
otherwise resume is attempted once. A lost or malformed response is reconciled
with one read of the exact live chat and is never retried. Every recovered chat
must report `recovered: true`, `authority_revalidated: false`, and write,
command, and web permissions disabled. Native review is required before any
protected authority can be granted again.

Retained-history branching is available only through `agent_fork`, not generic
`agent_invoke`. It requires literal `mutation_authorized: true`, exact source
project/chat identity, exact catalog and history revisions, and a caller-owned
32-hex request ID. The optional destination project, completed-turn event
sequence, and title are part of that immutable idempotency binding. A trusted
4xx is not retried. A transport-ambiguous or schema-invalid first response may
receive exactly one byte-identical retry with the same request ID; a new key is
never generated automatically. The validated receipt must preserve exact
source/destination lineage and report approvals, mutation authority, pending
tool state, staged attachments, and artifacts as not copied. Missing or
mismatched proof remains `fork_uncertain`.

Complete retained-history export is available only through `agent_export`, not
generic `agent_invoke`. It requires exact project/chat identity and exact
catalog and history revisions plus a caller-selected event ceiling from 0 to
4,000. The HTTP endpoint receives both revisions and rejects stale state before
returning content. The controller then validates contiguous complete coverage,
turn counts, title/model identity, the response-size boundary, and the event
ceiling. The MCP projection omits the workspace path, attachment bytes, live
approval state, raw tool arguments/results, previews, and mutation authority.
Every call still requires its task-specific authorization and redaction
receipt because visible conversation text enters the connected model context.

Live-chat close is available only through `agent_close`, not generic
`agent_invoke`. It requires literal `mutation_authorized: true`, exact
project/chat identity, and the exact catalog and history revisions. The live
chat must be idle with no pending approval or cleanup uncertainty; use
`agent_stop` first when a turn is active. The endpoint atomically rechecks the
same identity before closing only the memory-backed runtime. A trustworthy
close is attempted once. Ambiguous delivery receives one read-only live/chat
catalog reconciliation and is never followed by another DELETE. Settled
results prove the live chat is absent while the durable catalog record remains;
permanent deletion, retained-history deletion, and protected-authority grants
are literal false safety facts.

Prefer `agent_catalog` over generic route composition for durable metadata. Its
seven actions are `list_projects`, `get_project`, `create_project`,
`update_project`, `list_chats`, `get_chat`, and `update_chat`. Mutation actions
require literal `mutation_authorized: true`; updates require the exact current
revision. Responses are parsed through strict catalog schemas, must preserve
the requested project/chat identity and revision transition, and cannot carry
undeclared fields. There is deliberately no delete action. Use `agent_open` to
create or focus a live chat.

`agent_history` accepts one exact project/chat identity, an exclusive event
cursor, and a limit of at most 500 events. It revalidates ordered sequence
numbers and rejects any response that claims a live/closing turn, pending
approval, raw tool arguments, approval identifiers, or preview payloads. It
does not resume, fork, export, edit, or delete the chat.

`agent_artifacts` has `list`, `get`, `export`, and `preview_capture` actions. Lists are
capped at 200 and every returned artifact must preserve the requested
project/chat identity; details must preserve the exact artifact identity and
complete immutable version lineage. `preview_capture` accepts one exact
project/chat identity, a canonical workspace-relative path, and an optional
trimmed title. It returns only the validated path, title, kind, media type,
viewer kind, byte size, and SHA-256 digest with
`requires_native_confirmation: true` and `file_content_included: false`.

`export` requires the exact artifact revision and immutable version ID. The
server re-reads that version from the admitted workspace, verifies byte count
and SHA-256, then rechecks that the artifact metadata did not change during the
request. It returns a portable lineage JSON record marked
`sensitive_local_metadata`; `content_included` and `absolute_path_included` are
literal `false`. This is distinct from the native viewer's explicitly labelled
raw-byte **Download** action. Stale bytes, missing versions, removed records,
cross-scope identities, revision races, and contradictory privacy flags fail
closed.

Previewing does not create an artifact, request an approval, or grant capture
authority. Only the owned native Agent UI can perform the separately confirmed,
revision-bound capture. Generic `agent_invoke` cannot call the preview route;
the dedicated action revalidates project, chat, path, title, and the strict
content-free response. File bytes never cross this tool. A connected agent may
use `agent_workspace` for a returned UTF-8 relative path; image, PDF, and
download-only content remains in the native artifact viewer.

`agent_stage_attachment` accepts one exact `project_id` and `session_id`,
literal `mutation_authorized: true`, and a nested attachment containing only a
safe display name, admitted media type, declared byte count, SHA-256 digest,
and standard base64 data. It has no path, URL, file-browser, attachment-read,
delete, approval, or model-lifecycle field. The server verifies base64 length,
digest, decoded structure, current live-model capability, chat identity,
and storage limits before committing once. PNG, JPEG and PCM WAV remain native
multimodal inputs. UTF-8 text/data and supported Office/ODT documents become a
bounded inert local text projection; PDF input is refused and original Office
bytes never enter the model. Its response is a sanitized staged
metadata view: neither the base64 value nor digest is returned. Use the
returned attachment ID in `agent_turn.message.attachment_ids`; the native
composer's **Refresh staged** action makes externally staged attachments visible for
review before send.

`agent_context` has `runtime` and `chat` actions. Both return the coordinator
revision and state, requested/served placement without the runtime PID, the
runtime's exact last-measured request-context evidence, path-free model and
adapter compatibility, and only capabilities verified by the served runtime.
The chat action additionally
returns one exact live chat's model selection, sampling budget, permission
summary, recovery state, session-and-turn-bound context receipt, and staged
image/audio/document metadata. Workspace paths,
standing instructions, approval identifiers, attachment digests/bytes, and
process IDs are omitted. The snapshot is explicitly sequential and non-atomic;
the runtime context receipt remains marked global while the chat receipt is
explicitly bound or explicitly unmeasured. The tool never calls token counting, stages attachments, or
loads/switches/stops a model. Model lists are deterministic and transparently
capped at 200 entries.

For ordinary coding-agent work, prefer `agent_workspace` over generic
`agent_invoke` when reading a workspace. Its six actions are `inspect`,
`list`, `search`, `read`, `changes`, and `diff`; every result is validated
against the expected workspace contract, exact chat identity and requested
relative path. `search` accepts one literal or regular-expression query plus a
root-relative glob. It returns canonical path/line matches, inert single-line
previews, exact scanned/skipped/byte counts, and explicit complete or partial
coverage. The shared search lane is limited to 1,024 query characters, 20,000
entries, 16 MB of inspected UTF-8 text, 80 matches, bounded per-file and total
deadlines, and never follows a link or reparse point.
The tool rejects absolute, drive-qualified, backslash, query/fragment and
traversal paths before making an HTTP request. It has no create, edit, move,
trash, apply, command, web, model or approval action. Ask for changes through
`agent_turn` when the selected local model should author them. If the connected
controller already authored exact UTF-8 content, use `agent_propose`: creates
are bound to target absence and edits to the exact current SHA-256 revision.
Proposal acceptance changes no file and exposes an external-controller diff in
the native Agent window. Only that native decision can apply it. Continue from
the returned cursor with `agent_wait`; never infer success from acceptance.
Raw proposed content, diffs, approval identities, and denied, failed, or
unverified attempts are not appended to durable conversation history. In a
**Save locally** chat, only a verified create/edit write receipt is retained.
That bounded receipt drives the same immutable artifact lineage and output card
used by native reviewed writes, so approved external output survives restart
without retaining the controller-authored payload. Metadata-only chats retain
neither the proposal nor its receipt.
For two to eight file changes that must land together, use
`agent_propose_transaction`. Every member declares `operation`: a create is
bound to target absence and carries no source revision, while an edit is bound
to the exact current SHA-256 revision. Each also carries an explicit
line-ending policy. Acceptance presents one combined native review and changes
nothing. After approval the app reconstructs the complete preview, requires it
to be byte-for-byte equivalent to what was reviewed, then uses the
failure-atomic transaction lane. A later-file failure restores earlier edits
and removes only a created file whose exact same-transaction publication
identity is still present. A replaced path is preserved and reported as
unverified. The controller sees bounded per-file operation and verification
receipts and may observe settlement with `agent_wait`, but it never receives
native apply, delete, or approval authority.

Use `agent_propose_lifecycle` when the controller has already authored an exact
path operation. It accepts one directory create, directory move, file move, or
file removal. Moves never overwrite; file move/removal requires the exact
current SHA-256 source revision; removal is explicitly non-permanent and uses
the Windows Recycle Bin. Acceptance changes nothing. The native Agent card
shows the exact paths, revision, and recovery semantics. After the decision the
app rebuilds the short-lived capability and requires the reviewed identity to
remain unchanged. Stop, denial, timeout, a changed source, a newly occupied
destination, or an altered replay fails closed. The scoped MCP credential still
has no apply, approval, shell, or permanent-delete authority.

For a **Save locally** chat, a verified file move also rehashes the destination
and advances a matching artifact under the same ID with an immutable
`reviewed_move` path version. Earlier paths remain in the audit lineage. If the
artifact's latest digest/size no longer matches the moved bytes, no identity is
inferred. If another artifact card already owns the destination, neither
lineage is merged or overwritten and the post-filesystem metadata outcome is
reported as unverified. Directory moves and recoverable trash do not currently
project artifact lineage. This metadata projection is not a power-loss-atomic
filesystem transaction.

MCP calls are bounded to 300 seconds; the generated Codex configuration sets
`tool_timeout_sec = 330` so the server can return its terminal or incomplete
receipt, and keeps tool approval in `prompt` mode. Inspect the operation and
arguments before approving a generic mutation. Closed failures
expose only an error code, optional HTTP status, and a retryability flag. The
direct transport does not launch Prompt Enhancer, Codex, Claude, a local model,
a shell, subprocess, or terminal, and its internal controller transport does
not follow redirects or environment proxies.

Clients without Streamable HTTP support may use the advanced stdio fallback:

```text
prompt-enhancer agent-mcp-config --transport stdio
prompt-enhancer agent-mcp-config --transport stdio --with-model-lifecycle
```

That fallback owns one client-managed MCP bridge subprocess. It is retained for
compatibility, not used by the default Windows setup, and still cannot grant a
native approval.

## Single-request controller bridge

The bundled v5 controller command keeps the API token out of prompts, process
arguments, configuration snippets, and stdout. It reads the already-existing
private token, connects directly to the configured loopback listener, disables
environment proxies and redirects, performs one bounded action, emits one JSON
result, and exits. It does **not** start Prompt Enhancer, Codex, Claude, another
agent, or a terminal window. The explicit `runtime` action can ask the already-
running Prompt Enhancer owner to load, switch, or stop its one model runtime.

Inspect the machine-readable command contract and verify the running API with:

```text
prompt-enhancer agent-controller-config
prompt-enhancer agent-controller discover
```

`discover` returns only the content-free v14 manifest. `invoke` exposes one
manifest-declared JSON operation except runtime mutations, live-chat close, and
inline attachment staging or file proposals, which require their specialized
controller paths.
`open` safely creates or selects one durable project and opens one validated live
chat, `close` removes only one exact idle live runtime while retaining its
catalog/history, `turn`
supplies the specialized finite send/poll/Stop loop, and `wait` resumes bounded
observation after native review without submitting or stopping anything. All
sensitive commands read one strict JSON object from stdin and require the
explicit command-line acknowledgement:

```text
--acknowledge-sensitive-context-egress
```

Each stdin object must also carry a per-request receipt. A controller sets these
values only after the owner authorized that task and reviewed the exact data that
will enter the selected local controller or model context:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "model_context"
  },
  "request": {
    "operation": "list_projects",
    "path_parameters": {},
    "query": {},
    "body": null
  }
}
```

To make one registered model ready on an explicit placement, use:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "local_controller"
  },
  "request": {
    "desired_state": "ready",
    "alias": "example-model",
    "device": "split",
    "gpu_layers": 24,
    "context_size": 8192
  }
}
```

Pipe it to `prompt-enhancer agent-controller runtime
--acknowledge-sensitive-context-egress --acknowledge-model-lifecycle`. To stop
that exact model, set `desired_state` to `stopped` and omit `device`,
`gpu_layers`, and `context_size`.

`runtime` first validates the v14 manifest and current v2 coordinator status. If
the requested state already exists, it returns without mutation. Otherwise it
sends exactly one revision-bound switch or stop. If the response is lost or
malformed after that attempt, it performs one status read and never repeats the
mutation. Results distinguish `ready`, `ready_reconciled`, `stopped`,
`stopped_reconciled`, `activation_uncertain`, `stop_uncertain`, and
`cleanup_unconfirmed`. An uncertain result must be reconciled explicitly;
cleanup uncertainty blocks further model or Agent work. Stopping refuses to
target an alias different from the requested or served model.

For a new project and chat, use the validated bootstrap form:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "local_controller"
  },
  "request": {
    "project_id": null,
    "project_name": "Example project",
    "settings": {
      "workspace": "D:\\example-workspace",
      "model_alias": "example-model",
      "title": "Example chat",
      "retention_policy": "local_history",
      "allow_writes": true,
      "allow_commands": true,
      "allow_web": false
    }
  }
}
```

Pipe it to `prompt-enhancer agent-controller open
--acknowledge-sensitive-context-egress`. Supply an existing `project_id`
instead of `project_name` to open a chat under one exact project. `open` never
retries a creation request. Its `ready` result contains the validated project
and live session. `session_creation_uncertain` preserves the known project for
an explicit chat-list reconciliation; `project_cleanup_unconfirmed` preserves
the project record when rollback of a definitely rejected new chat cannot be
confirmed. Ambiguous project creation returns the closed
`controller_project_creation_uncertain` error and must be reconciled through
project listing or search rather than blindly repeated.

To close that exact idle live chat without deleting its durable record or
retained history, supply the current catalog and history revisions:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "local_controller"
  },
  "mutation_authorized": true,
  "request": {
    "project_id": "<32 lowercase hex characters>",
    "session_id": "<32 lowercase hex characters>",
    "expected_catalog_revision": 2,
    "expected_history_revision": 4
  }
}
```

Pipe it to `prompt-enhancer agent-controller close
--acknowledge-sensitive-context-egress`. The authorization value must be the
JSON literal `true`; boolean-like numbers and strings fail before dispatch. A
running, stopping, closing, approval-blocked, cleanup-uncertain, stale, or
cross-project chat is not mutated. The controller sends at most one DELETE and,
after an ambiguous response, performs one read-only live/catalog reconciliation
without retrying the mutation. Settled results prove that the live runtime is
absent and the durable chat remains available.

The turn form is:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "local_controller"
  },
  "request": {
    "session_id": "<32 lowercase hex characters>",
    "message": {
      "text": "<selected message>",
      "attachment_ids": []
    }
  }
}
```

Pipe that object to `prompt-enhancer agent-controller turn
--acknowledge-sensitive-context-egress`. The JSON result distinguishes
`settled`, `needs_native_approval`, `submission_uncertain`, `stopped`,
`cleanup_unconfirmed`, and `incomplete`. An ambiguous message submission is inspected once and never
automatically repeated. A deadline sends Stop at most once and performs only a
bounded terminal drain.

If the result is `needs_native_approval`, retain its `cursor`, let the owner
decide the pending action in the native Agent window, and continue with:

```json
{
  "egress": {
    "task_authorized": true,
    "redaction_previewed": true,
    "destination": "local_controller"
  },
  "request": {
    "session_id": "<same 32 lowercase hex characters>",
    "after": 7
  }
}
```

Pipe this object to `prompt-enhancer agent-controller wait
--acknowledge-sensitive-context-egress`. `wait` never submits a message and
never requests Stop, including on deadline. An `incomplete` result carries the
next cursor and can be passed to another explicit bounded `wait`. A
`cleanup_unconfirmed` result is terminal for controller progress: inspect the
owned native process state before any further Agent or model work.

The generic bridge refuses native-only operations before making an HTTP request.
It also refuses raw runtime switch/stop, SSE, and binary responses; use
`agent-controller runtime` for model lifecycle and the documented direct
loopback API only when a deliberately selected controller needs streaming or
binary modes. All server-side workspace admission and native review checks
still apply.

## Correct turn lifecycle

Use this finite state machine. It avoids duplicate prompts and unbounded polling:

1. Discover the v14 manifest and verify its boundary fields and complete route
   coverage marker.
2. Use `agent-controller runtime` to ensure the selected model and placement are
   exactly ready. Treat cleanup or activation uncertainty as a stop condition.
3. Use `agent-controller open` to select or create a project and open one chat,
   or explicitly revision-resume an existing retained chat.
4. Read the session and send exactly one message only while it is idle.
5. Treat message submission as non-idempotent. If the `202` response is
   ambiguous, read the session/events before deciding what happened; do not
   automatically submit the message again.
6. Poll events with `after=<last_seen_sequence>` or consume the SSE endpoint.
   Advance the cursor only to a validated returned sequence.
   The SSE relay always emits a JSON page before it closes for settled success
   or cleanup quarantine. EOF by itself is never evidence of success.
7. If `pending_approval_id` is non-null, stop controller progress and surface
   the pending action in the native UI. Never try to approve it with the API
   token. After the owner decides it, resume from the returned cursor with
   `agent-controller wait`; never resubmit the message.
8. `cleanup_unconfirmed` is never a successful terminal state. Stop controller
   progress and inspect the owned process tree.
9. The turn is settled only when `running`, `closing`, `stopping`, and
   `cleanup_unconfirmed` are all false, `pending_approval_id` is null, and the
   cursor has reached `last_seq`.
10. Use a bounded `turn` deadline. On expiry, request `stop` once, drain the
   terminal events, and report an incomplete turn rather than starting a loop.
   A `wait` deadline never requests Stop.
11. When finished, close or retain the chat intentionally, then use
    `agent-controller runtime` with `desired_state: stopped` and require a clean
    idle coordinator receipt before claiming process/GPU cleanup.

Conceptual controller pseudocode:

```text
session = GET /v1/agent/sessions/{session_id}
assert session.running == false and session.pending_approval_id == null

POST /v1/agent/sessions/{session_id}/messages  {"text": "..."}
cursor = session.last_seq

until deadline:
    page = GET /v1/agent/sessions/{session_id}/events?after={cursor}
    validate page.session_id and strictly increasing event sequences
    cursor = last returned sequence, or keep the prior cursor
    if page.pending_approval_id != null: return NEEDS_NATIVE_APPROVAL
    if page.cleanup_unconfirmed: return CLEANUP_UNCONFIRMED
    if !page.running and !page.closing and !page.stopping
       and cursor >= page.last_seq: return SETTLED

POST /v1/agent/sessions/{session_id}/stop
drain events once to a terminal state
return INCOMPLETE
```

## Project, chat, and model lifecycle

The v22 manifest enumerates all 72 Agent routes plus five controller-relevant
model-runtime routes. Its groups cover:

- project create/read/update/delete and project-scoped chat browsing;
- cross-project chat search, rename, pin, archive, restore, move, and delete;
- live chat create/read/close, messages, bounded polling, SSE, Stop,
  revision-bound resume/export, and idempotent retained-history branching;
- workspace discovery, bounded UTF-8 text search, tree and UTF-8 file reads, externally authored
  native-reviewed write proposals, diffs, artifacts, and
  capability-bound image/audio/document attachments, including path-free
  external staging and bounded no-store document-preview endpoints;
- file edit/create/move/trash, directory create/move, atomic multi-file
  transaction previews, and inverse reviewed-path restore previews whose apply
  route remains native-confirmed; and
- shared local-model runtime status, compatibility, input-token counting,
  revision-bound switch, and verified Stop.

Important identities and
boundaries are:

- Durable navigation uses `project_id` plus `session_id`; never infer a project
  from a session title.
- A metadata-only chat cannot be reconstructed after it closes.
- A local-history chat can be revision-resumed, but it returns read-only. The
  native user must separately revalidate protected capabilities.
- The local model runtime is shared. Switch or stop it only through the
  revision-bound runtime endpoints, then verify the reported served model and
  cleanup state before continuing.
- Closing a live chat does not delete its durable navigation/history record.
  Catalog deletion is a separate explicit operation.
- Token-authenticated controllers can prepare workspace previews, but every
  apply route is marked `native_user_presence_only`. A token alone can never
  turn a preview into a file-system effect.

## Retained-session branching

Branch one durable chat through its latest settled turn, or through one exact
completed-turn event, with:

```text
POST /v1/agent/projects/{project_id}/sessions/{session_id}/forks
```

The strict JSON body carries a caller-generated 32-character lowercase-hex
`request_id`, the exact catalog and history revisions observed by the caller,
an optional active destination project, an optional completed `done` event
sequence, and an optional title. Omit `through_event_seq` to use the latest
completed turn; use `0` only to create an intentionally empty branch.

The operation is idempotent. If the HTTP result is ambiguous, repeat the exact
same request with the same `request_id`; never generate a new key until the
previous outcome is known. Reusing a key with different input fails closed.
Stale revisions, metadata-only history, archived destinations, and non-settled
branch points are rejected atomically.

The child is a new inert local-history chat with persistent lineage. It copies
only the selected retained event prefix and its already-attached private media,
remapping attachment identities. It never copies pending approvals, mutation
authority, live tool state, staged attachments, artifacts, active processes,
or a live model session. The receipt exposes each of those authority-copy facts
as literal `false`. Deleting the parent does not erase the child's history or
content-free source lineage.

## Artifact lifecycle

Reviewed Agent file writes automatically project into immutable artifact
lineage for local-history chats. The artifact endpoints let a controller:

- list artifact metadata for one exact project/chat;
- read the complete immutable version lineage and current availability;
- export one exact revision/version lineage record only after current workspace
  byte read-back, without file bytes or an absolute workspace path;
- fetch one exact version after its current workspace bytes are re-hashed; and
- preview a candidate workspace file as content-free path, classification,
  byte-count, and SHA-256 metadata; then request a capture bound to that exact
  reviewed digest and size, which still requires native user presence.

The preview route is
`POST /v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/capture-preview`.
It returns no file bytes and grants no write or capture authority. The later
`POST .../artifacts` request must repeat the reviewed path, title, digest, and
size. If the file changes between those requests, capture fails closed and the
client must request a fresh preview.

Artifact metadata is not a byte-availability claim. Content reads fail closed
when the file is stale, missing, malformed, too large, outside the admitted
workspace, or reached through a link/reparse point. Text is served as inert
`text/plain`; HTML, SVG, XML, legacy Office documents, and unknown binary data
are download-only. Image and PDF previews require validated byte signatures.
Admitted DOCX, PPTX, XLSX, and ODT files use bounded, digest-bound inert
text/table projections; macros, objects, relationship targets, and external
resources are never executed or fetched. Preview responses remain private and
no-store.

## What “agent communication” means here

An external controller and the Prompt Enhancer local model communicate through
one selected chat and its monotonic event journal. Prompt Enhancer does not
spawn Codex or Claude processes, discover their credentials, or create an
autonomous agent-to-agent loop. The external controller owns its own process
lifecycle and passes only the deliberately selected message. Prompt Enhancer
owns workspace admission, model/tool execution, durable chat state, event
receipts, and native approval boundaries.

This separation is intentional: it makes orchestration usable while keeping
human approval and local privacy truthful.

The native card's orchestration starter is deliberately a workflow prompt, not
a credential or standing grant. It contains no token, workspace path, project
identity, or model choice. The owner supplies those task-specific values and
authority when asking the connected controller to delegate work.
