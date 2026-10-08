# Agent chat experience: council consensus and implementation plan

Date: 2026-08-27
Status: implementation active; Agent-01 through Agent-07, Agent-08a through Agent-08z, Agent-09a through Agent-09z, Agent-10a through Agent-10t, and MCP Store-01 through MCP Store-04 are complete, with owner-controlled client/model acceptance and guarded third-party MCP installation/routing still open
Scope: the local Agent experience, authored Agent projects/sessions, local-model runtime switching, attachments, generated artifacts, and third-party MCP discovery/management

Governing completion program: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md). That document defines the remaining whole-product workstreams, checkpoint order, and final release gate; this plan remains the detailed Agent-specific design and implementation ledger.

## Council and evidence

The plan combines three completed, privacy-safe repository reviews:

- GPT Sol: product and systems architecture
- GPT Terra: interaction design, responsive behavior, and accessibility
- GPT Luna: validation, privacy, migration, and runtime reliability

Privacy-safe, non-persistent Claude CLI consultations were attempted for Fable 5 and Opus 5. The installed CLI recognized both model aliases but its isolated mode was not authenticated. No provider credential store, session, prompt, or workspace content was accessed to bypass that boundary. Those two consultations are therefore recorded as unavailable, not simulated.

The comparison target is also grounded in the [official OpenAI desktop app documentation](https://learn.chatgpt.com/docs/app) and its [projects and chats guide](https://learn.chatgpt.com/docs/projects): a desktop workspace can keep projects and chats visible, preserve distinct chats under a project, and inspect documents, spreadsheets, images, and other outputs in the same workspace.

## Decision

The Agent becomes a chat-first local coding workspace. The existing safety, workspace, review, approval, change-set, discovery, editor, and streamed-event systems remain the behavioral substrate. They are reorganized around one dominant chat instead of competing with it.

The intended desktop composition is:

```text
+---------------------------+--------------------------------------+---------------------------+
| Projects and sessions     | One dominant Agent chat              | Workspace / Review drawer |
|                           |                                      | (closed by default)       |
| + New chat                | Session title · workspace · policy   |                           |
| Search                    | Model/runtime state · Stop            | Files                     |
|                           |                                      | Changes                   |
| Projects                  | Transcript                            | Discovery                 |
|   Project A               |  user / agent messages               | Team folders              |
|     Session 1             |  progress and tool activity          | Artifact inspector        |
|     Session 2             |  artifact cards                      |                           |
|   Project B               |                                      |                           |
|                           | Pending approval tray, when required  |                           |
| Model                     |                                      |                           |
| Context: known / unknown  | Sticky multimodal composer            |                           |
| GPU · GPU+CPU · CPU       |                                      |                           |
+---------------------------+--------------------------------------+---------------------------+
```

At narrow widths, Projects/Sessions and Workspace/Review become mutually managed sheets. Chat remains the only primary surface and the composer stays visible.

## Product truths that the UI must never fake

1. **Reasoning:** show model-authored reasoning summaries, plans, progress, tool facts, and verification results. Never claim to expose a model's hidden chain of thought.
2. **Model state:** selected, requested, loading, served, draining, unloading, ready, failed, unknown, and quarantined are distinct states.
3. **VRAM release:** process exit alone is not proof of GPU-memory release. Report measured release or `cleanup unknown`; never report a false success.
4. **Context:** show `used / limit` only when the runtime and tokenizer provide sufficient evidence. Otherwise show `estimated` or `unknown`; missing values never become zero.
5. **Hugging Face support:** advertise probe-confirmed compatibility with supported adapters, not arbitrary repository compatibility.
6. **Capabilities:** text, tools, vision, audio, recording, structured output, and placement options come from an activated-runtime handshake and a fixture request. Model names are not capability evidence.
7. **Persistence:** label exactly what is durable. No existing provider transcript is imported. No missing conversation is silently represented as an empty successful session.
8. **Artifacts:** an assistant saying it created a document is not proof. An artifact requires a typed record, bounded path/captured version, provenance, revision/hash, MIME, and verification state.
9. **Approvals:** an approval remains exact, revision-bound, single-use, and natively confirmed. It is never restored as reusable authority after restart.

## Architecture boundary

Keep a modular monolith and introduce an authored-Agent bounded context that is separate from analytics/provider-ingestion records.

Core durable records:

- `AgentProject`
- `AgentSession`
- append-only `AgentEvent`
- `Turn`
- `ToolActivity`
- `ApprovalReceipt` and `ChangeReceipt`
- `Attachment`
- `Artifact` and `ArtifactVersion`
- immutable served-model/runtime/tokenizer/placement provenance per turn

Sensitive content and metadata use separate local retention tiers. Pending approvals and active workspace capabilities are intentionally ephemeral. After restart, the app may restore navigation and reviewed history, but mutation remains unavailable until workspace identity and native ownership are re-established.

Application services are separated into:

- project catalog and session lifecycle
- turn runner and event projection
- global runtime coordinator
- capability resolver
- attachment ingestion
- artifact catalog and preview service
- workspace inspection
- review and publication

The current local-Agent safety services remain the only file/command/network mutation lane.

## Runtime and compatibility contract

One server-side `RuntimeCoordinator` owns a single global runtime lease:

```text
idle -> loading -> ready -> draining -> unloading -> idle
                       \-> failed / cleanup-unknown / quarantined
```

Switching model or device placement must:

1. retain the user's draft;
2. stop admitting new turns;
3. drain or cancel the current generation safely;
4. finish or quarantine tool cleanup;
5. unload the old runtime;
6. verify process/handle cleanup and measure GPU release when available;
7. load the requested model with the requested `GPU`, `GPU+CPU`, or `CPU` placement;
8. run the capability handshake;
9. enable Send only when the actual served runtime matches the visible selection.

If cleanup cannot be verified, the replacement does not start.

Model backends implement a narrow adapter interface:

```text
probe -> plan -> activate -> capability handshake -> stream/cancel -> unload
```

The first production adapter remains llama.cpp/GGUF. Additional Transformers or ONNX families are admitted architecture by architecture with pinned revisions, licenses, safetensors/ONNX preference, `trust_remote_code` disabled, and the same contract suite.

## Checkpoint trajectory

Every checkpoint ends with automated gates, a protected app reload, a short handoff note, and a bounded owner checklist. A failed gate stops advancement; it does not trigger an unbounded repair loop.

### Agent-00 — Native single-instance and cleanup containment

Implemented:

- one per-Windows-session named-mutex lease covers both the GUI shortcut and
  `prompt-enhancer agent-desktop`;
- a duplicate launch performs one bounded exact-title focus attempt and exits;
  it cannot reserve an ephemeral listener, create a WebView, start runtime
  workers or touch the lifecycle marker;
- primary failures still release the lease, while unconfirmed lease release is
  never reported as a clean exit;
- native errors retain only the fixed application vocabulary;
- unit, cross-process, entry-point, worker, command-tree, loopback and hidden
  native-engine tests cover primary, duplicate, race, focus-failure, cleanup and
  resource-release paths.
- after the first visible check exposed terminal-window creation, every Windows
  `llama-server` spawn now uses `CREATE_NO_WINDOW` and `shell=False`;
- model overview/status and initial Agent-page rendering are regression-tested
  as read-only: they cannot activate a stopped model without the explicit
  start/open action.

Current gate: automated tests are green and owned resources are absent. The
owner-visible recheck is deliberately deferred; no native window is relaunched
automatically after the reported cascade. Non-native, model-free persistence
work may proceed, but no later checkpoint may claim the native visible gate has
passed until that bounded recheck is accepted.

Handoff: [checkpoint-agent-00-handoff.md](checkpoint-agent-00-handoff.md).

### Agent-01 — Durable authored navigation foundation

Implemented:

- a separate versioned SQLite catalog for owner-authored Agent projects and
  session navigation metadata;
- project create, list, get, rename, search, pin, archive, restore and guarded
  deletion contracts;
- session metadata list, get, rename, search, pin, archive, restore, project
  move and guarded deletion contracts;
- optimistic revisions, deterministic ordering, bounded queries, fixed-name
  storage, schema ledger/newer-schema refusal, symlink/reparse refusal and
  repeated two-instance concurrency tests;
- live Agent session creation registers against a real project, while closing a
  live session leaves a truthful unavailable-history stub after restart;
- strict generated HTTP/TypeScript contracts, closed failure codes and private
  no-store enforcement for every catalog response.

Truthful limit: this stores navigation metadata only. Conversation messages,
events, approvals, tools and capabilities remain memory-only. A restarted chat
is labelled `memory_only` with `conversation_available=false`; the app does not
invent an empty restored conversation.

Owner-visible result: none yet. The durable catalog is an internal foundation
for the left rail and was deliberately completed without relaunching the native
app or loading a model.

Go gate: catalog restart, migration refusal, concurrency, strict transport,
Agent/API regression, complete frontend, privacy and Windows inventory suites
pass. Handoff: [checkpoint-agent-01-handoff.md](checkpoint-agent-01-handoff.md).

### Agent-02 — Chat-first shell

Implemented:

- collapsible durable Projects/Chats rail with create, select, search, rename,
  pin, archive, restore, move and delete behavior;
- one dominant conversation surface with model/runtime truth, Stop, streamed
  events, tool activity, model-provided reasoning and the existing approval
  tray;
- Workspace, Changes, Discovery, editor and Team Folders preserved in a
  closed-by-default, 352–760 px resizable Files & Review drawer;
- New Chat side/bottom sheet with focus restoration and advanced parameters
  kept subordinate to the current chat;
- explicit live-conversation versus durable metadata-only restart states;
- responsive no-overflow behavior validated at 360 px and 1,440 px;
- provider-neutral loopback orchestration manifest with native-presence and
  privacy boundaries made explicit.

Its first internal step extracts the current page orchestration into bounded
catalog/session, event, approval, workspace and draft controllers without
changing the established safety behavior.

The rail uses the Agent-01 project/session catalog and distinguishes a live
conversation from a persisted metadata-only stub. The latter is non-sendable
and never visually implies that missing message history exists.

Owner checklist after reload:

1. create/select a temporary session from the left rail;
2. send and stop a streamed response;
3. open and close Workspace/Review without losing draft, focus, transcript scroll, or approval visibility;
4. repeat at desktop and narrow width.

Automated go gate: 1,905 frontend tests, 93 focused Agent/rail tests and two
responsive Chromium acceptance runs pass. The native owner checklist remains
deferred with Agent-00's visible recheck. Handoff:
[checkpoint-agent-02-handoff.md](checkpoint-agent-02-handoff.md).

### Agent-03 — Global runtime coordinator and truthful model switcher

Implement:

- one server-side runtime lease across model aliases;
- serialized unload-before-load transitions;
- bottom-left model, placement, runtime status, and context control;
- requested-versus-served provenance;
- draft retention through transitions;
- cleanup measurement/unknown/quarantine state;
- one verified text-only capability handshake.

Owner checklist after reload:

1. load model A on one placement;
2. begin a response, retain a draft, and request model B or another placement;
3. observe draining -> unloading -> loading -> ready;
4. verify A is gone before B becomes sendable;
5. test Stop and a failed/unsupported load.

Go gate: concurrent switch requests cannot start two runtimes; crash/restart at every phase leaves no falsely sendable or orphan-owned runtime; GPU cleanup is measured or visibly unknown.

### Agent-04 — Durable authored projects and sessions

Implement:

- versioned SQLite repositories for authored Agent projects, sessions, events, turns, and receipts;
- explicit retention choice and local deletion/export semantics;
- project/session create, rename, pin, search, archive, and restore;
- write-through append-only event journal and deterministic projections;
- migration that creates metadata stubs only where appropriate and labels unavailable history;
- no provider transcript import and no reusable approval restoration;
- crash recovery and stale/concurrent-tab protection.

Owner checklist after reload:

1. create two projects and multiple sessions;
2. restart the app and verify navigation/history according to the chosen retention policy;
3. verify each project remains isolated;
4. confirm recovered mutation is read-only until workspace/native revalidation.

Go gate: no duplicate/rewound turns, cross-project reads, stale writes, invented status/content, approval replay, or sensitive content outside the declared local tier.

### Agent-05 — Artifact cards and safe viewers

Implement:

- `Artifact` and immutable `ArtifactVersion` lineage;
- provenance states: reviewed write, generated-unverified, verified output, external effect unknown, stale, or missing;
- file/diff/test/report/image/document cards in the transcript;
- authenticated no-store byte/range endpoints with workspace revision revalidation;
- inert text and image viewers with explicit load/decode/failure states;
- a locally bundled PDF-to-canvas viewer with no iframe, external fetch, active
  annotation layer, or interactive document features;
- bounded in-process inert text/table projections for admitted DOCX, PPTX,
  XLSX, and ODT containers; legacy office formats remain download-only;
- clear Open, Reveal, Review changes, and Download actions.

Owner checklist after reload: create synthetic text, image, and PDF artifacts; open them from cards; mutate one behind the app and verify it becomes stale instead of silently showing changed content.

Go gate: path traversal, arbitrary-file read, XSS, active HTML/SVG/PDF content, external fetch, stale revision, oversized file, and malformed parser fixtures all fail safely.

### Agent-06 — Capability-gated images and audio — complete

Implement:

- attachment vault with explicit selection, bounded count/bytes, strict format-structure validation, hashes, retention, and deletion;
- image input only for probe-confirmed vision models;
- audio file input and microphone recording only for probe-confirmed audio models;
- per-model MIME/rate/duration/dimension limits;
- composer controls absent or disabled with an explanation when unsupported;
- attachment provenance and context-cost reporting when known.

Owner checklist after reload: compare text-only, vision, and audio synthetic capability profiles; verify controls and admission match the active runtime exactly.

Go gate: traversal, reparse/symlink, MIME confusion, decode bomb, interrupted upload, unsupported modality, retention expiry, and canary-leak suites pass.

Completion receipt (2026-08-27): `agent-attachment.v1` supplies the private
bounded vault, payload-free event identity, exact-model/capability recheck,
single-use settlement, metadata-only deletion and opt-in durable recovery. The
composer supports verified image/WAV admission, local preview/removal,
attachment-only sends and local PCM-WAV recording. Runtime capability probing
is fail-closed and tied to an explicitly registered `mmproj_path`; no model
name implies multimodal support. PNG/JPEG admission is strict structural
validation, not a claim that a general-purpose image decoder ran. Context cost
remains visibly unknown because the runtime did not report it. See the
[Agent-06 handoff](checkpoint-agent-06-handoff.md) for exact limits, synthetic
evidence and the deferred native/model owner checks.

### Agent-07 — Broader Hugging Face compatibility and truthful context — complete

Implement:

- catalog discovery separated from executable compatibility;
- `supported`, `unsupported`, and `unknown` results with reason codes;
- pinned model/runtime/tokenizer/license manifest;
- additional adapters admitted one architecture family at a time;
- exact server-side context admission, compaction/truncation policy, and known/estimated/unknown UI;
- public compatibility matrix generated from the contract suite.

Owner checklist after reload: inspect supported, unsupported, and unknown repositories; install an admitted model; verify plain chat, Stop, Unicode, context overflow, usage reporting, and placement modes.

Go gate: no model is marked usable without an actual fixture request; missing usage/tokenizer/context data remains unknown; safety/system/tool constraints are never silently truncated.

Completion receipt (2026-08-27): `local-model-compatibility.v1` separates
registered/catalog identity from live executable support. The first versioned
adapter, `llama.cpp-openai-gguf.v1`, reports supported only after the exact
served alias completes a live text probe; stopped models remain unknown and
failed/missing artifacts use closed reason codes. Bounded GGUF metadata exposes
architecture, tokenizer family, layer count and training context only when the
file supplies them. Runtime/model digests, versions, revisions and licence stay
nullable rather than being inferred from names.

Exact request admission uses llama.cpp's chat-template-aware
`/v1/chat/completions/input_tokens` response. Agent compaction removes and
recounts whole older conversation units, protects leading system instructions,
tool schemas and the current request, and refuses before inference when the
protected minimum cannot fit. If the counter is absent or malformed, context
use remains unknown and the runtime is the final enforcer; no character/token
estimate is substituted. The Models and Agent surfaces show these states, and
the generated [compatibility matrix](local-model-compatibility-matrix.md)
records the public synthetic contract. The
[Agent-07 handoff](checkpoint-agent-07-handoff.md) contains the bounded evidence
and deferred real-runtime owner checks.

### Agent-08 — Release hardening and legacy retirement

Implement:

- full responsive and accessibility pass;
- repeated load/unload and long-stream soak;
- crash recovery during load, stream, approval, file preview/apply, command, artifact render, and migration;
- bounded local, opt-in, content-free diagnostics;
- complete retention/delete/export verification;
- remove the legacy layout only after parity evidence is recorded.

Progress receipts (2026-08-27):

- **Agent-08a** completed the strict provider-neutral controller contract. The
  v4 manifest has exact parity with all 52 Agent routes plus five required local
  runtime routes, fixes all ten native-only operations, exposes its live state
  under **Connections & controller API**, and is covered by a complete synthetic
  project/chat/workspace lifecycle.
- **Agent-08b** added the token-free `prompt-enhancer agent-controller` stdio
  bridge. It provides strict discovery, one manifest-declared JSON invocation,
  and a finite one-message turn runner with monotonic cursors, ambiguity
  reconciliation without retry, native-approval handoff, one deadline Stop and
  bounded drain. Redirects, environment proxies, remote origins, token output,
  native applies, binary/SSE bridging and unacknowledged sensitive context are
  refused. It starts no process or model.
- **Agent-08c** added an authenticated, owner-invoked, content-free hardening
  snapshot outside the controller authority surface. Fixed aggregate queries
  report only bounded schema, integrity, retention, recovery and live-cleanup
  facts. Strict backend and frontend validators reject additional fields or
  incoherent states. A non-spawning harness now covers long streamed histories,
  restart recovery, interrupted approvals and commands, stale edit previews,
  stale artifact bytes, repeated fake runtime activation/deactivation, migration
  rollback, delete cascades and redacted history export. No real model, native
  app, browser server or child command is required by this slice. See the
  [Agent-08c handoff](checkpoint-agent-08c-handoff.md).
- **Agent-08d** completed the synthetic responsive/accessibility acceptance pass
  for the chat shell and hardening card. Health work remains opt-in and now has
  a persistent atomic live announcement, truthful partial catalog/live results,
  safe recovery explanations and container-driven fact layout. Team Folders is
  an independent collapsed disclosure, a chat skip link bypasses projects and
  settings, key Agent controls meet a 44 px floor, and forced-colors focus plus
  zero page overflow pass at desktop and an explicit 320 px resize. See the
  [Agent-08d handoff](checkpoint-agent-08d-handoff.md).
- **Agent-08e** added a native-presence-gated, page-local acceptance harness
  that is inert by default and has no runtime/chat/workspace mutation methods.
  Its strict start receipt proves the gate requested no model execution,
  process spawn, workspace access, or content persistence. The guided state
  machine separately observes a clean baseline, verified startup, completed
  and stopped turns, Files & review, context truth, unload, process exit, and
  CPU or measured-GPU cleanup. The frozen
  [legacy parity ledger](agent-legacy-parity-ledger.md) records fourteen of
  sixteen capability groups complete at that checkpoint, with session
  branching/forking missing and the separate native-window lifecycle still
  partial. See the
  [Agent-08e handoff](checkpoint-agent-08e-handoff.md).
- **Agent-08f** completed durable, revision-safe session branching. A caller can
  fork the latest settled history, one exact completed turn, or an explicit
  empty boundary with an idempotent request identity. The child preserves
  content-free lineage across restart and parent deletion, while approval
  authority, mutation authority, pending tool state, staged attachments,
  artifacts, processes, and live state remain uncopied. Attached private media
  is digest-verified and identity-remapped. The v5 controller manifest now has
  exact parity with all 54 Agent routes plus five runtime routes, and the typed
  UI exposes branch controls in retained history and chat menus. The parity
  ledger is now fifteen of sixteen implemented groups. See the
  [Agent-08f handoff](checkpoint-agent-08f-handoff.md).
- **Agent-08g** completed the separate-window implementation with one native
  application owner and at most one same-process child WebView. Duplicate and
  concurrent opens focus the existing child; the child creates no listener,
  worker, process, runtime owner, or cleanup path. A fresh opaque key crosses
  the native bridge, while selected chat identity stays in a strict same-origin,
  memory-only rendezvous channel. The dedicated window now carries the full
  project/chat rail, shared model/context controls, conversation, and on-demand
  file review. Process-free native tests and synthetic 360 px/1440 px browser
  tests cover lifecycle, shutdown, navigation, model switching, draft retention,
  durable-history browsing, and layout. The parity ledger is now sixteen of
  sixteen implemented groups. See the
  [Agent-08g handoff](checkpoint-agent-08g-handoff.md).
- **Agent-08h** hardened the document-output handoff. A settled turn with no
  verified write now says **no reviewed file writes** without expansion and
  explains that model text is not file evidence. Real artifact cards move to
  the active end of live and retained conversations, while empty artifact
  furniture is omitted. The artifact projector and provider-neutral controller
  create-project/create-chat/bounded-turn lifecycle were revalidated with
  synthetic backend tests. See the
  [Agent-08h handoff](checkpoint-agent-08h-handoff.md).
- **Agent-08i** completed safe controller continuation and rich Markdown
  artifact review. `local-agent-orchestration.v7` adds the exact
  cleanup-confirmed terminal condition, cursor continuation after native
  review, and a cleanup-quarantine invariant. The token-free `wait` command
  resumes bounded observation without submitting a message or requesting Stop;
  `cleanup_unconfirmed` can never be reported as settled. Markdown artifacts
  now default to a rendered document with Preview/Source switching while raw
  HTML, every link, and remote images remain inert. The Controller card reports
  the discovered contract rather than a stale hard-coded version. See the
  [Agent-08i handoff](checkpoint-agent-08i-handoff.md).
- **Agent-08j** aligned the direct private SSE relay with the same v6 terminal
  truth. `closing` and `stopping` can no longer make the relay end as if the
  turn settled. A newly attached controller receives an exact final JSON page
  for settled success or cleanup quarantine, and EOF alone is explicitly not a
  success receipt. Adversarial lifecycle tests cover closing, stopping,
  quarantine, and the complete Agent/controller regression group. See the
  [Agent-08j handoff](checkpoint-agent-08j-handoff.md).
- **Agent-08k** added a controller-native project/chat bootstrap instead of
  requiring an orchestrator to improvise multiple raw manifest calls.
  `agent-controller open` validates either one existing project or one newly
  created project plus the complete Agent settings, injects the exact project
  identity, and returns the validated live session. Creation is never retried;
  ambiguous session creation preserves the known project for reconciliation,
  while a trustworthy 4xx rejection rolls back only a newly created empty
  project and reports cleanup uncertainty if that rollback cannot be proven.
  See the [Agent-08k handoff](checkpoint-agent-08k-handoff.md).
- **Agent-08l** closed a reviewed-change-set finality race. Files & review can
  now claim complete coverage only while the session is idle, open, free of a
  pending approval, and outside both session-local and process-wide command
  cleanup quarantine. Turn admission and lifecycle transitions remain locked
  through the point-in-time snapshot, so closing cannot slip between the
  settled decision and file inspection. The partial-state UI no longer assumes
  every unsettled snapshot is caused by an active turn. See the
  [Agent-08l handoff](checkpoint-agent-08l-handoff.md).
- **Agent-08m** completed safe external runtime coordination. The v4 stdio
  bridge adds one typed `runtime` action that can ensure an exact registered
  alias and CPU/GPU/split placement is ready, or stop that exact alias. It reads
  the coordinator first, binds at most one mutation to the observed revision,
  validates the returned served/cleanup evidence, and performs one read-only
  reconciliation after an ambiguous response without repeating the mutation.
  Cleanup uncertainty blocks progress, stopping refuses a different served
  alias, raw runtime mutation is removed from generic `invoke`, and the command
  requires a separate model-lifecycle acknowledgement. See the
  [Agent-08m handoff](checkpoint-agent-08m-handoff.md).
- **Agent-08n** made immutable artifact lineage directly reviewable. The
  conversation viewer now selects an exact recorded version, displays its
  provenance, size, and digest identity, and requests preview/download bytes
  by that version ID. Historical bytes remain in the workspace rather than
  being copied into application storage; a nonmatching revision fails closed,
  disables download, and cannot expose **Open current file**. Synthetic
  component, backend, Chromium, and in-app-browser checks cover latest and
  stale historical revisions. See the
  [Agent-08n handoff](checkpoint-agent-08n-handoff.md).
- **Agent-08o** added the missing standard external-agent integration. Codex,
  Claude Code, and other MCP clients can now discover and call the validated
  project/chat/invoke/turn/wait controller operations through a dedicated
  token-private stdio server. Sensitive calls require per-call authorization,
  generic mutations and deletes are gated, native approvals remain
  unavailable, and model lifecycle is omitted unless explicitly enabled at
  setup and authorized again per call. See the
  [Agent-08o handoff](checkpoint-agent-08o-handoff.md).
- **Agent-08p** proved the bridge as a real composition rather than only an
  in-process contract. A synthetic MCP stdio client crossed an authenticated
  ephemeral TCP listener and the production controller, created one durable
  fictional project/chat, and observed that catalog from a second MCP process
  while the runtime stayed idle. A disposable installed console launcher also
  generated valid Codex and Claude configuration without creating private app
  state. The Agent setup card now keeps recommended MCP setup visible and
  nests lower-level scripts/direct HTTP under **Advanced**. See the
  [Agent-08p handoff](checkpoint-agent-08p-handoff.md).
- **Agent-08q** removed the stdio process from the recommended integration
  path. The running app now serves stateless Streamable HTTP MCP at
  `/mcp/agent`; each client receives a scoped, expiring, revocable credential
  whose secret is derived rather than stored. Create, rotate, and revoke stay
  behind one-shot native confirmation. The Agent card lists connection
  metadata and exposes private values only through one-time copy actions;
  direct HTTP starts no bridge process or terminal. The old stdio bridge stays
  available only as an advanced fallback. A real-listener test re-enters the
  same production server through the controller without deadlock or process
  spawn. See the [Agent-08q handoff](checkpoint-agent-08q-handoff.md).
- **Agent-08r** made the chat-first hierarchy concrete. Projects and chats stay
  in the persistent rail; New chat setup and Connections/Owner checks/Team
  folders now open in separate keyboard-accessible drawers instead of nesting
  setup cards through the primary workbench. Live browser validation repaired
  tab/content overlap, drawer insets, touch-target sizing, saved-chat overlay
  cleanup and safe inspection during command cleanup. The final gates are 115
  focused component/layout passes, 66 responsive Chromium passes and a
  536-module production build. See the
  [Agent-08r handoff](checkpoint-agent-08r-handoff.md).
- **Agent-08s** completed the fictional native lifecycle and restart pass for
  durable projects and chats. It repaired model-free durable creation,
  chat-title project search, clipped action menus, cross-window title sync, a
  stale resume-closing marker and a self-echoing catalog invalidation race that
  could replace authoritative mutation results with stale lists. A clean native
  restart preserved the fictional project/chat and restored no protected
  authority. Final gates are 121 focused frontend tests, 94 backend lifecycle
  and boundary tests, 66 responsive Chromium workflows and a 536-module build.
  See the [Agent-08s handoff](checkpoint-agent-08s-handoff.md).
- **Agent-08t** repaired returning-chat startup and finished the conversation-to-
  workspace handoff. Existing durable catalogs now reopen the newest retained
  chat without a setup overlay and visibly select its project/chat rows; empty
  catalogs still receive onboarding. Strict `workspace:` links open reviewed
  relative files while absolute and traversal links remain inert. Direct MCP
  client configs now reference a client-process environment variable instead
  of embedding the one-time bearer. Final gates include 101 Agent page tests,
  23 focused renderer/catalog/MCP tests, 74 backend MCP/local-Agent tests, a
  536-module build and a content-free live browser reload. See the
  [Agent-08t handoff](checkpoint-agent-08t-handoff.md).
- **Agent-08u** added a dedicated strict `agent_workspace` MCP tool for bounded
  workspace discovery, tree listing, UTF-8 file reads, reviewed change sets and
  exact diffs. Unsafe or incoherent paths fail before controller I/O, response
  session/path identity is revalidated, and no workspace mutation, approval,
  command, fetch or model lifecycle can cross this tool. The Agent Connections
  drawer explains that edits remain `agent_turn` requests reviewed in the native
  window. Final gates include 83 backend tests, 9 frontend contract tests, a
  536-module build and a clean live native/browser reload with one listener and
  no provider or model child. See the
  [Agent-08u handoff](checkpoint-agent-08u-handoff.md).
- **Agent-08v** adds a dedicated strict `agent_catalog` MCP tool for seven
  durable project/chat metadata actions. It validates identities, project
  scope, declared fields, requested mutation postconditions, and exact revision
  increments. Create/update actions require literal mutation authorization;
  permanent deletion is absent from the tool and now refused through generic
  MCP invocation, so connected agents cannot grant themselves destructive
  authority over projects, chats, or retained history. See the
  [Agent-08v handoff](checkpoint-agent-08v-handoff.md).
- **Agent-08w** adds read-only `agent_history` and `agent_artifacts` MCP tools.
  Retained pages are bounded and reject live approval/raw-tool fields,
  cross-session identity, and cursor incoherence. Artifact list/detail responses
  are project/chat/artifact-bound immutable lineage metadata only; binary
  content, capture, export, deletion, and approval authority stay outside MCP.
  See the [Agent-08w handoff](checkpoint-agent-08w-handoff.md).
- **Agent-08x** adds a dedicated read-only `agent_context` MCP tool. Its
  `runtime` action reports path-free installed-model compatibility, requested
  and served placement, the runtime's exact last-measured request-context
  evidence and verified
  image/audio/recording support. Its `chat` action adds exact live-chat model,
  sampling, permission, recovery and staged-attachment metadata. The snapshot
  is explicitly sequential/non-atomic and omits workspace paths, standing
  instructions, approval IDs, process IDs, attachment digests and bytes. It
  performs no token counting, staging, runtime lifecycle or chat mutation. The
  context receipt is marked global and never misrepresented as selected-chat
  usage; binding exact context evidence to a chat remains a later slice.
  See the [Agent-08x handoff](checkpoint-agent-08x-handoff.md).
- **Agent-08y** adds the strict in-memory `agent-session-context.v1` receipt.
  Exact chat-template preflight is now bound to one live session, turn, and
  model; new, recovered, model-switched, unavailable, and failed-preflight
  states remain explicitly unmeasured. Private HTTP, the Agent runtime card,
  and `agent_context` consume that same identity-checked receipt. Runtime-wide
  last-request evidence stays separately labelled and cannot substitute for a
  selected chat. See the
  [Agent-08y handoff](checkpoint-agent-08y-handoff.md).
- **Agent-08z** closes the external-agent media-ingress gap. The v8 controller
  adds one exact project/chat JSON staging route, and MCP v7 exposes it only as
  `agent_stage_attachment` with literal mutation authorization. Caller-supplied
  PNG/JPEG/PCM-WAV data is base64-length-, digest-, structure-, capability-,
  quota-, and identity-checked; no filesystem path or URL is accepted and no
  attachment bytes or digest are returned by the tool. SQLite schema v7 records
  `external_agent` provenance without losing older attachment rows. The native
  composer can refresh staged media and visibly identifies its source. See the
  [Agent-08z handoff](checkpoint-agent-08z-handoff.md).
- **Agent-09a** closes the native owner-shutdown gap. Owner exit now removes
  the same-process chat child without a second confirmation, while the
  automation worker propagates cooperative shutdown through ingestion, hidden
  Codex app-server waits, and Claude transcript scanning/parsing. A real
  owner-plus-child close left zero Agent, diagnostic, or terminal windows,
  listener, and model process. See the
  [Agent-09a handoff](checkpoint-agent-09a-handoff.md).
- **Agent-09b** proves the recommended direct Streamable HTTP MCP composition
  with two independent clients and immediate revoked-credential rejection,
  without a bridge process, terminal, model lifecycle, provider configuration
  change, or exposed bearer. Its native walkthrough also repairs the short-
  desktop Agent rail: Projects/Chats keep the flexible space, Agent settings is
  always reachable, and expanded runtime details stay in a bounded internal
  scroller. The complete 67-case responsive workflow matrix, 123 focused Agent
  component tests, generated API check, production build, and a live 1,268 px
  reload pass. Issuing the real one-time client credential remains an explicit
  owner action. See the
  [Agent-09b handoff](checkpoint-agent-09b-handoff.md).
- **Agent-09c** adds a dedicated evidence-bound `agent_stop` MCP tool. It
  requires literal mutation authority and an exact chat/cursor, sends Stop at
  most once, never duplicates an already-stopping request, and never upgrades
  an ambiguous response to success without terminal event and cleanup proof.
  Generic `stop_turn` invocation is refused. Focused controller, MCP,
  disposable-listener, and two-direct-client coverage passes without loading a
  model or creating a real connection credential. A graceful native reload
  retained the fictional chat with one listener, zero model processes, and no
  visible terminal window. See the
  [Agent-09c handoff](checkpoint-agent-09c-handoff.md).
- **Agent-09d** adds a dedicated revision-bound `agent_resume` MCP tool for
  durable chats that are no longer live. It requires exact project/chat,
  catalog-revision, and history-revision identity plus literal mutation
  authority; refuses stale, archived, metadata-only, unavailable, and
  cross-project records before mutation; and performs no mutation when the
  exact chat is already live. Resume is attempted at most once, ambiguous
  delivery receives one read-only reconciliation, and every recovered session
  starts with write, command, and web authority disabled. Generic resume route
  composition is refused. See the
  [Agent-09d handoff](checkpoint-agent-09d-handoff.md).
- **Agent-09e** adds a dedicated idempotency-bound `agent_fork` MCP tool. It
  requires literal mutation authority, exact source identity and revisions,
  plus a caller-owned request ID that also binds destination, branch point,
  and title. Trusted 4xx results are not retried; an ambiguous first response
  receives at most one byte-identical retry with the same key. The result must
  prove exact lineage and that approvals, mutation authority, pending tool
  state, staged attachments, and artifacts were not copied. Generic fork route
  composition is refused. See the
  [Agent-09e handoff](checkpoint-agent-09e-handoff.md).
- **Agent-09f** adds a dedicated exact-revision `agent_export` MCP tool. It
  requires exact project/chat, catalog revision, history revision, and a
  caller-selected event ceiling. The HTTP route now rejects stale revisions
  before returning content, while the controller validates complete contiguous
  event coverage and turn counts. The MCP projection omits workspace paths,
  attachment bytes, live approvals, raw tool payloads/previews, and mutation
  authority. Generic export route composition is refused. See the
  [Agent-09f handoff](checkpoint-agent-09f-handoff.md).
- **Agent-09g** adds a dedicated exact-revision `agent_close` MCP tool for one
  idle live chat. The route atomically checks project/chat identity plus the
  current catalog and history revisions, closes only the live runtime, and
  retains the durable record and history. A close is never automatically
  repeated; one read-only reconciliation may settle ambiguous delivery.
  Active turns, pending approvals, stale state, cleanup uncertainty, generic
  close composition, and every durable delete fail closed. See the
  [Agent-09g handoff](checkpoint-agent-09g-handoff.md).
- **Agent-09h** repairs the native connection-setup drift exposed by 09c–09g.
  The compact Direct app connections card now states the real sixteen-core-tool
  lifecycle and keeps the complete grouped tool inventory in one collapsed,
  keyboard-reachable disclosure. The advanced controller bridge now exposes
  copyable `invoke`, `turn`, and live-only `close` commands alongside open,
  runtime, and wait, and explains at-most-once close plus durable-history
  retention. Stale copy claiming retained history cannot be exported was
  removed. See the [Agent-09h handoff](checkpoint-agent-09h-handoff.md).
- **Agent-09i** closes the image/PDF evidence gap in the artifact viewer.
  Returned bytes must now match the selected immutable version's exact media
  type, byte count, and safe generated filename before preview or download.
  Images expose truthful loading, ready, decode-failure, fit, and zoom states;
  local object URLs are revoked on close, version change, scope change, and
  unmount. PDFs are parsed from the verified in-memory bytes by a lazy-loaded,
  pinned local PDF.js worker and rendered page-by-page to canvas with XFA,
  annotations, worker fetch, range, stream, auto-fetch, and WASM paths disabled.
  No iframe or interactive PDF layer remains. See the
  [Agent-09i handoff](checkpoint-agent-09i-handoff.md).
- **Agent-09j** closes the modern Office and artifact-action gap. DOCX, PPTX,
  XLSX, and ODT previews are server-derived, digest-bound, bounded inert
  projections; no Office application, converter process, macro, embedded
  object, relationship target, or network service runs. Unsafe containers,
  active XML declarations, malformed selected XML, compression bombs, and
  stale identities fail closed. Artifact actions now reveal even non-editable
  files in the owned workspace tree without opening them and route reviewed
  writes to the exact retained net diff. Legacy office files remain explicit
  download-only content. See the
  [Agent-09j handoff](checkpoint-agent-09j-handoff.md).
- **Agent-09k** closes the native external-orchestrator onboarding gap. The
  direct-connection card now exposes the actual Streamable HTTP path, shows the
  exact loopback endpoint after credential creation, supplies a credential-free
  provider-neutral delegation starter, and distinguishes a never-used
  connection from a recorded authenticated MCP request. The evidence is
  intentionally narrow: last use proves credential arrival, not turn or file
  success. See the [Agent-09k handoff](checkpoint-agent-09k-handoff.md).
- **Agent-09l** adds a durable, content-free MCP tool-activity receipt. After an
  explicit refresh, each connection can show the last validated tool name,
  `succeeded`/`failed` protocol outcome, and time. Unknown or malformed names
  collapse to the fixed `unknown_tool` label, and receipt-storage failure never
  changes a settled MCP response into retry ambiguity. No arguments, result,
  prompt, path, identity, token, or exception is persisted. See the
  [Agent-09l handoff](checkpoint-agent-09l-handoff.md).
- **Agent-09m** closes the externally authored write dead end. The dedicated
  `agent_propose` tool accepts only an exact target-absent create or an
  exact-revision edit, performs no publication itself, and returns a bounded
  idempotent receipt. The live Agent timeline and approval card identify the
  controller proposal and show its diff; only native approval can apply it.
  Denial, Stop, timeout, replay conflict, stale revision, and verification
  failure are covered, while proposal content and lifecycle stay out of
  retained history. See the
  [Agent-09m handoff](checkpoint-agent-09m-handoff.md).
  Its native reload also exposed and repaired a scheduler shutdown regression:
  cooperative cancellation was being classified as an ordinary provider
  failure, allowing the worker to continue through later grants beyond the
  desktop cleanup deadline. Cancellation now exits the poll immediately, and
  a warmed native close completes without a diagnostic or terminal window.
- **Agent-09r** closes the manual-workspace parity gap left after the shared
  transaction engine gained mixed operations. The Files & review card now
  stages target-absent creations alongside exact-revision edits, reopens and
  updates staged new-file drafts, labels every operation, blocks duplicate
  case-insensitive paths, and reports restored edits separately from removed
  same-transaction creations. The combined review and native approval remain
  the v2 failure-atomic service boundary; the UI gains no delete authority.
  See the [Agent-09r handoff](checkpoint-agent-09r-handoff.md).
- **Agent-09s** closes the first-class workspace search gap. Files & review and
  the scoped Agent MCP now share one bounded, root-confined UTF-8 search lane
  with literal/regex queries, root-relative globs, canonical path/line matches,
  inert previews, and explicit coverage/count evidence. Workspace replacement,
  traversal, link/reparse entries, binary text, deadlines, invalid patterns,
  stale UI results, and cross-session responses fail closed. See the
  [Agent-09s handoff](checkpoint-agent-09s-handoff.md).
- **Agent-09t** closes the chat-first responsive-review gap. Files and reviewed
  changes now share one explicitly tabbed, keyboard-operable review drawer.
  Below 1,380 px it becomes a viewport-bounded modal sheet instead of stacking
  below or displacing the conversation; desktop retains a resizable third
  column. The workspace pane stays mounted while its tabs switch so staged and
  manual drafts survive. Closing a dirty drawer requires explicit discard
  confirmation, receipt-opened files focus and scroll into view, and the chat
  regains focus after a clean close. See the
  [Agent-09t handoff](checkpoint-agent-09t-handoff.md).
- **Agent-09u** closes the external-orchestrator handshake-truth gap. The MCP
  initialize guidance now teaches the bounded discover → open → context → turn
  → wait/stop flow, directs clients to verified workspace/artifact evidence,
  and makes native review, egress receipts, opt-in runtime authority, and
  retained-history close semantics explicit within 512 characters. The owned
  endpoint self-test fails closed when that guidance is absent, incomplete, or
  oversized, so **Handshake + workflow passed** cannot mean protocol shape
  alone. See the [Agent-09u handoff](checkpoint-agent-09u-handoff.md).
- **Agent-09v** closes a cross-chat composer privacy gap. Unsent text and staged
  media are now keyed to one exact live session, restore only in that chat, and
  never enter browser storage or durable history. Exact successful admission
  clears only the unchanged sent snapshot, so late completion cannot erase a
  newer draft; stale media results cannot cross a chat switch. The rail exposes
  only a content-free in-window draft marker, and permanent catalog deletion
  purges the owning draft only after deletion succeeds. See the
  [Agent-09v handoff](checkpoint-agent-09v-handoff.md).
- **Agent-09w** closes a contradictory model-recovery path. When the coordinated
  runtime and installed choices are present, stopped and model-less chats now
  reveal and focus the existing in-Agent **Model & context** selector instead
  of routing users to the Models page. Empty catalogues and legacy backends keep
  that external fallback, so no dead selector is advertised. Session status,
  first-message guidance, and the disabled composer now name the same recovery
  location. See the [Agent-09w handoff](checkpoint-agent-09w-handoff.md).
- **Agent-09x** closes a blocking workspace-draft confirmation path. Cancelling
  a new file, opening another file or folder, removing or clearing staged work,
  discarding a manual edit, and hiding the workspace now use the shared
  non-blocking modal with focus trapping, Escape-to-keep, focus return, and an
  explicit destructive action. Removing the currently open staged edit also
  restores its staged text as the promised unsaved editor draft instead of
  silently leaving disk text there. See the
  [Agent-09x handoff](checkpoint-agent-09x-handoff.md).
- **Agent-09y** closes the remaining page-level blocking confirmation paths.
  Dirty drawer close, live or retained chat selection, dedicated-window
  handoff, replacement-chat creation, and live-chat close now share one
  non-blocking modal. Keep is initially focused, Escape keeps state, focus
  returns, clean transitions remain immediate, and a window handoff is not
  acknowledged until the user accepts. Closing the active chat combines its
  retention consequence with any dirty-workspace consequence instead of
  opening two prompts. See the
  [Agent-09y handoff](checkpoint-agent-09y-handoff.md).
- **Agent-09z** hardens the explicit artifact-download boundary. A download is
  now owned by one exact project, chat, artifact version, viewer lifetime, and
  transport. Viewer close, version or artifact selection, unmount, and scope or
  transport replacement abort it; a late result cannot create a Blob URL or
  click a download link. Digest conflict, missing content, malformed media, or
  response-contract mismatch invalidates the matching preview and disables
  download, while retryable failures remain retryable. The adjacent Open,
  Reveal, and Review actions were revalidated end to end. See the
  [Agent-09z handoff](checkpoint-agent-09z-handoff.md).
- **Agent-10a** hardens the capability-gated media composer as one owned
  lifecycle. Microphone permission, recording, WAV encoding, staged-media
  refresh, upload, removal, and Send now cancel or serialize at exact
  chat/runtime/transport boundaries. Late grants release their tracks, partial
  audio setup releases its graph, stale list results cannot overwrite newer
  mutations, failed refresh keeps known identities, and media staged for a
  different model blocks Send with explicit recovery. See the
  [Agent-10a handoff](checkpoint-agent-10a-handoff.md).
- **Agent-10b** hardens shared-runtime and context ownership. Runtime and
  chat-context reads now cancel predecessors and accept only their exact
  transport, chat, model, and newest revision. Start/Switch, chat binding, and
  Stop carry abort ownership; transport replacement or unmount cannot apply a
  late result. Pending context is labelled as checking, cross-model receipts
  fail unknown, and transition, cleanup-unconfirmed, and quarantine states are
  disabled before mutation. See the
  [Agent-10b handoff](checkpoint-agent-10b-handoff.md).
- **Agent-10c** hardens durable project/chat lifecycle and controller parity.
  Destructive catalog operations now require exact project, catalog, and
  retained-history revisions; resume, delete, update, binding, and authority
  revalidation are serialized against live-session state. Native rail
  mutations and branches are abort-owned, late results cannot cross a view,
  and every New-chat entry point restores keyboard focus. Whole-suite testing
  also reduced local model-child control checks to 250 ms so cancellation keeps
  a bounded Windows tree-cleanup margin. See the
  [Agent-10c handoff](checkpoint-agent-10c-handoff.md).
- **Agent-10d** hardens conversation fidelity and rich rendering. Safe GFM and
  fenced code retain explicit link/image containment; completed messages,
  model-provided reasoning, code, and tool output have truthful copy feedback;
  reasoning never claims hidden chain of thought; transcript DOM is bounded to
  the latest activity with explicit earlier-event batches; long live streams
  remain visible; and frontend/backend event kinds reject borrowed authority or
  incomplete tool/approval receipts. See the
  [Agent-10d handoff](checkpoint-agent-10d-handoff.md).
- **Agent-10e** makes final parity and acceptance readiness visible in the
  product. Agent settings opens on a 15-row readiness checklist mapped to the
  16 frozen implementation groups, with automated evidence and 10 owner gates
  reported separately. Desktop/320 px, forced-colors, hostile Markdown,
  loopback controller/MCP, generated-schema, and legacy-route boundaries pass
  without starting a model or granting authority. See the
  [Agent-10e handoff](checkpoint-agent-10e-handoff.md).
- **Agent-10f** closes the external-client setup and reviewed-file acceptance
  gap. The one-time connection card now copies current token-free Codex and
  Claude Code registration commands as well as the validated config snippets,
  while Prompt Enhancer still executes neither. A real-loopback synthetic MCP
  run opens a durable project/chat, stages one edit plus one create, proves both
  remain unchanged before one-shot native review, waits to settlement, and
  reads both verified revisions back through `agent_workspace` without loading
  a model or spawning a child process. See the
  [Agent-10f handoff](checkpoint-agent-10f-handoff.md).
- **Agent-10g** makes exact external-client setup inspectable before authority.
  An authenticated, read-only endpoint returns the canonical loopback URL,
  Codex TOML, Claude JSON, and both current token-free add commands while
  proving that no credential, connection authority, process, terminal, or
  provider edit exists. The Agent card validates that document strictly and
  exposes an explicit disconnected preview at desktop and 320 px even when
  native mutation controls are unavailable. See the
  [Agent-10g handoff](checkpoint-agent-10g-handoff.md).
- **Agent-10h** closes the generated-output capture gap. A retained chat can
  inspect an existing workspace file without returning its bytes, review its
  exact path/type/viewer/size/digest, and then capture only that exact revision
  after a separate native user-presence confirmation. Binary, PDF, image, and
  Office-style files can now become immutable artifact cards even when they are
  not editable in the UTF-8 workbench. Stale revisions fail closed. See the
  [Agent-10h handoff](checkpoint-agent-10h-handoff.md).
- **Agent-10i** closes the external-orchestrator artifact-review gap. The
  dedicated `agent_artifacts.preview_capture` action exposes only an exact
  candidate's relative path, title, type/viewer, size, and digest. It returns
  no file bytes, creates no artifact or approval, and cannot complete capture;
  the separately confirmed native Agent UI remains the only capture lane.
  Generic invocation is blocked and strict cross-scope, stale-shape, hidden-
  payload, and native-confirmation checks fail closed. See the
  [Agent-10i handoff](checkpoint-agent-10i-handoff.md).
- **Agent-10j** repairs the medium-width chat hierarchy found by the visual
  audit. On the Agent route, the redundant global rail collapses into the
  existing compact header from 861 through 1180 px while the project/chat rail
  remains visible and every global destination stays reachable through Menu.
  At the reproduced 1046 px viewport the conversation grows from about 547 px
  to 761 px with no horizontal overflow. Other routes, the mobile shell, and
  the dedicated Agent window keep their prior layouts. See the
  [Agent-10j handoff](checkpoint-agent-10j-handoff.md).
- **Agent-10k** makes filtered project/chat navigation non-destructive. A
  no-match search no longer clears the selected project or unmounts its active
  conversation, the collapsed rail retains that project's identity, and
  clearing search restores navigation without reselection. Rail/runtime
  controls now meet a 44 px interaction target, while catalog dialogs wrap
  keyboard focus, lock background scrolling, and restore focus on Escape. The
  stopped runtime selection path was verified live without loading a model.
  See the [Agent-10k handoff](checkpoint-agent-10k-handoff.md).
- **Agent-10l** upgrades the active streaming conversation. Text drafting stays
  available while the response runs or stops, Stop remains the only active-run
  action, and the exact draft unlocks Send only after terminal output. A sticky,
  keyboard-reachable Jump-to-latest control now recovers paused transcript
  follow, composer shortcut/state guidance remains visible, and reasoning/tool
  disclosures meet a 44 px target. Real Chromium checks pass at 390 and 1046
  px. See the [Agent-10l handoff](checkpoint-agent-10l-handoff.md).
- **Agent-10m** makes Files & Review a coding workbench instead of a diagnostics
  wall. The file tree/editor remain primary while discovery, content search,
  Git metadata, and safety detail live in a collapsed 44 px disclosure whose
  root-replacement lock stays mounted. A missing text-input type and a narrow
  regex override were repaired after Chromium measured 21 px and 19 px targets.
  The affected workspace matrix passes at 360, 390, 1046, and 1440 px. See the
  [Agent-10m handoff](checkpoint-agent-10m-handoff.md).
- **Agent-10n** compacts capability-gated media behind one keyboard-safe Attach
  media picker, raises composer and artifact/viewer controls to a 44 px target,
  and keeps an explicit verified-output empty state after completed durable
  turns. A model's file-creation claim still never becomes an artifact without
  a reviewed write or exact native capture. See the
  [Agent-10n handoff](checkpoint-agent-10n-handoff.md).
- **Agent-10o** makes the detached native chat an exact, reload-safe view of the
  selected session. The primary renderer retains only an in-memory
  window-key/session mapping, the child acknowledges only after resolving the
  exact session, child-local navigation updates the reload target, repeated
  opens refocus one child, and close ordering leaves the primary listener
  alive. See the
  [Agent-10o handoff](checkpoint-agent-10o-handoff.md).
- **Agent-10p** completes the external-controller onboarding and recovery
  audit. Codex, Claude Code, and generic Streamable HTTP clients have exact
  setup paths; the credential-bound endpoint check has an eight-second bound;
  rejected authority and contract failures produce content-free recovery; and
  expired or revoked records can prepare, but never silently create, a fresh
  native-confirmed replacement. See the
  [Agent-10p handoff](checkpoint-agent-10p-handoff.md).
- **Agent-10q** makes external-controller acceptance evidence truthful. Tool
  receipts now distinguish the app's own self-test from an external MCP
  client, exact inactive credentials produce only a content-free rejected-auth
  timestamp, and a memory-only four-step card requires fresh external
  discovery, explicit native revocation, and a strictly later rejected retry.
  The flow never creates or mutates authority automatically. See the
  [Agent-10q handoff](checkpoint-agent-10q-handoff.md).
- **Agent-10r** closes the remaining external reviewed-file lifecycle gap.
  Connected controllers can now submit directory creation, no-overwrite
  directory/file moves, and revision-bound recoverable file removal through
  `agent_propose_lifecycle`. Acceptance never changes the workspace; the exact
  operation enters the existing native approval card, the short-lived
  capability is rebound after the decision, and only a verified native effect
  becomes `applied`. See the
  [Agent-10r handoff](checkpoint-agent-10r-handoff.md).
- **Agent-10s** closes the external reviewed-write artifact gap. In a **Save
  locally** chat, a native-approved and verified controller create/edit now
  retains only its bounded write receipt and projects it into the same durable
  immutable output-card lineage as a native reviewed write. Repeated edits add
  versions, restart recovery preserves the lineage, and proposal text, diffs,
  approval identities, denied/failed/unverified attempts, and metadata-only
  chats remain live-only. See the
  [Agent-10s handoff](checkpoint-agent-10s-handoff.md).
- **Agent-10t** preserves saved output identity across an exact verified file
  move. The same artifact receives an immutable `reviewed_move` path version,
  prior paths remain auditable, and restart recovery reopens the destination
  bytes under the original artifact ID. Stale source bytes are not associated,
  and an existing target card is never merged or overwritten: the already-
  applied filesystem effect is reported as unverified and review coverage is
  marked partial. Directory moves and recoverable-trash lineage remain
  separate work. See the
  [Agent-10t handoff](checkpoint-agent-10t-handoff.md).
- **MCP Store-01** adds official third-party MCP discovery without pretending
  management exists. The Agent settings drawer searches, filters, pages, and
  inspects strictly normalized Official MCP Registry metadata through bounded
  local routes and an exact restart cache. Trusted raster icons are proxied;
  missing icons use initials. Install remains visibly unavailable because no
  package, remote, credential, client configuration, or process authority is
  implemented yet. The real-browser pass also repaired an app-wide cache-header
  composition defect. See the
  [MCP Store-01 handoff](checkpoint-mcp-store-01-handoff.md).
- **MCP Store-02** adds an exact version-bound, non-executing safety and setup
  review. Server identity and a deterministic future-plan revision are bound
  across route, transport, parser, and UI. Provenance, version history, local
  package/remote options, declared inputs, integrity evidence, risk facts, and
  compatibility unknowns are visible without returning input values, commands,
  endpoint path/query, tool data, or local content. Install remains disabled;
  no package, endpoint, credential, process, project, or tool authority is
  created. See the
  [MCP Store-02 handoff](checkpoint-mcp-store-02-handoff.md).
- **MCP Store-03** adds durable, non-executing management plans. Exact reviewed
  versions/options survive restart; project bindings require every inferred
  future permission but remain host-inactive; and secret values go only to
  Windows Credential Manager while SQLite/API/model context retain content-free
  state. Native-confirmed mutations are revision-bound and idempotent, including
  retry-safe vault failure reconciliation. Installation, connection, process
  hosting and tool routing remain locked. See the
  [MCP Store-03 handoff](checkpoint-mcp-store-03-handoff.md).
- **MCP Store-04** adds a guarded compatibility host without granting tool
  authority. A ready fixed HTTPS remote plan can be checked only after native
  confirmation and exact Registry-plan revalidation. DNS is public-only and
  connection-pinned; proxies and redirects are disabled; MCP negotiation,
  pagination, response bytes, schema complexity and time are bounded. No tool
  is called, and only protocol, tool count, schema digest, duration and closed
  cleanup truth survive. The internal stdio adapter uses atomic process-tree
  ownership and no-window launch, but local package plans cannot reach it until
  guarded installation exists. See the
  [MCP Store-04 handoff](checkpoint-mcp-store-04-handoff.md).

These receipts make external-controller behavior testable, but they do not
complete native acceptance, real-model lifecycle, or legacy-retirement gates.

Final go gate:

- zero native-approval, revision, transaction, cleanup-quarantine, privacy-canary, or cross-session regressions;
- no orphan model process or false runtime/context/capability claim;
- no raw prompt, response, tool argument/result, path, token, attachment, or exception content in telemetry/logging/browser storage;
- every advertised runtime/model family passes the same synthetic CPU/GPU/GPU+CPU compatibility matrix;
- owner walkthrough passes at desktop and 320 px.

## What remains accessible but leaves the default view

Move into drawers/settings:

- workspace path and folder setup;
- model parameters and advanced sampling;
- detailed permission policy;
- file discovery and manual editor;
- change set and turn effects;
- Team Folders;
- raw diagnostics and runtime logs.

Keep always visible:

- current project/session;
- actual model/runtime/placement state;
- context truth (`known`, `estimated`, or `unknown`);
- capability and permission summary;
- transcript, progress/tool activity, Stop, composer;
- pending approval or cleanup uncertainty.

## Explicit non-goals

- exposing hidden chain of thought;
- claiming universal Hugging Face compatibility;
- loading multiple large models concurrently in the first architecture;
- restoring pending approval authority after restart;
- importing provider transcripts into the authored Agent database;
- executing active document content inside a viewer;
- remote listening, remote model fallback, or content telemetry by default.

## Current recommendation

Implementation parity and post-ledger truthfulness/integration hardening are
automatically complete through **Agent-10t**, and third-party MCP discovery,
exact safety/setup-plan review and durable non-executing management are complete
through **MCP Store-04**. The reconciled checklist is now visible under **Agent settings
→ Readiness**. Keep each remaining slice bounded.
The direct two-client/revocation probe, native rail reload, endpoint self-test,
controller/model mixed transaction path, manual mixed create/edit workspace
flow, and a synthetic direct-MCP create/edit/native-review/read-back path pass.
The exact client setup is now reviewable before authority, but creating the
real one-time bearer and approving a real external proposal remain
immediate owner-confirmed actions.
The apparent primary-window close delay observed during 09p was the still-open
native quit confirmation, not a cleanup leak. Accepting that confirmation
released the window in 0.52 seconds with no listener, model, or Python owner
left behind; the confirmation remains as an intentional safety boundary.
Agent-10h supplies the native inspect-then-capture path needed by the bounded
owner artifact walkthrough, and Agent-10i lets a connected Codex, Claude Code,
or other MCP controller inspect the same candidate metadata without receiving
bytes or capture authority. Agent-10j begins the deferred card-by-card visual
walkthrough and removes the redundant global rail that squeezed the 1046 px
Agent conversation. Agent-10k keeps that conversation mounted through filtered
navigation and completes the rail/runtime interaction audit. Agent-10l adds
next-message drafting during streamed work and explicit transcript live-edge
recovery. Agent-10m keeps Files & Review workbench-first while retaining the
full discovery and safety surface on demand. Agent-10n compacts the media
surface and makes the absence of a verified output visible after a completed
turn. Agent-10o makes the one owned detached chat reload-safe, keeps
child-local navigation as its next reload target, and verifies open, refocus,
de-duplicate, reload, and close ordering live without loading a model.
Agent-10p closes generic-client setup fallback, bounds the local MCP self-test,
and makes expired, revoked, rejected, and failed-tool recovery explicit.
Agent-10q separates local-self-test receipts from external traffic and makes
the external discovery → native revoke → rejected retry owner gate directly
observable without creating or revoking a connection on the owner's behalf.
Agent-10r lets the same connected client hand off folder creation,
no-overwrite moves, and revision-bound recoverable removal to the native review
card, with no direct apply or permanent-delete authority.
Agent-10s makes an approved, verified external create/edit reappear after
restart as a durable output card without retaining its proposal payload or
approval identity. Agent-10t lets that same identity follow an exact verified
file move as a new immutable path version after rehashing the destination.
It does not infer continuity for directory moves, stale bytes, target-card
collisions, or recoverable trash.
The next owner gate remains the artifact walkthrough plus
the existing handshake: create synthetic text/image/PDF/Office output, use Add
output, Preview, Reveal, Review changes, and Download, then stale one file and
verify refusal.
After that gate, use the already-verified separate chat window for one
model-backed turn and Stop, review one fictional file write, then unload and
verify process/GPU cleanup.
Record only content-free acceptance receipts. While the owner gates are
deferred, the safe autonomous parity and external client-handoff audit is
complete through external-controller onboarding, recovery, and reviewed file
lifecycle parity. Further
implementation should follow a failed owner observation or the planned card-by-card visual
walkthrough; it must not start a model, request microphone access, or grant
protected authority without an explicit owner action.
No automated step may change provider configuration or launch a real model
without the owner's explicit
choice. If those gates pass, perform the final legacy-surface usage audit and
propose deletion as a separate reviewed change. Agent-01 through Agent-08u stay
separate and reviewable so regressions can be localized without recreating the
earlier loop.
