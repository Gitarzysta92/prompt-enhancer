# Agent legacy-retirement parity ledger

Date: 2026-08-27
Contract owner: Agent-08g
Retirement state: **blocked**

This ledger freezes the capabilities that must survive any removal of the old
Agent/model-chat surfaces. `Complete` means implementation plus automated
evidence exists. It does not substitute for a native owner check where that
column is pending. Missing, partial, pending, and blocked are intentionally not
collapsed into a pass.

| Capability | Implementation | Automated evidence | Native owner gate | Retirement impact |
|---|---|---:|---|---|
| Project create, browse, search, rename, pin, archive, restore, delete | Complete | Yes | Not required | Preserved |
| Chat create, browse, switch, move, close, archive, restore, delete, and session-scoped drafts | Complete | Yes | Not required | Preserved |
| Retained history across restart without restored mutation authority | Complete | Yes | Pending | Blocks retirement |
| Text chat, streaming, and bounded Stop | Complete | Yes | Pending | Blocks retirement |
| Model-provided reasoning, progress, tools, and turn receipts | Complete | Yes | Pending | Blocks retirement |
| Workspace files, reviewed edits, transactions, change sets, and diffs | Complete | Yes | Pending | Blocks retirement |
| Revision-bound native approvals and cleanup quarantine | Complete | Yes | Pending | Blocks retirement |
| Typed artifact cards, immutable versions, viewers, and download | Complete | Yes | Pending | Blocks retirement |
| Capability-gated images, audio files, and local recording | Complete | Yes | Pending | Blocks retirement |
| Shared runtime, switching, CPU/GPU placement, process and GPU cleanup truth | Complete | Yes | Pending | Blocks retirement |
| Exact-or-unknown context usage | Complete | Yes | Pending | Blocks retirement |
| Provider-neutral controller discovery and finite turn runner | Complete | Yes | Not required | Preserved |
| Retention choice, deletion cascades, and bounded history export | Complete | Yes | Not required | Preserved |
| Desktop, 320 px, keyboard, focus, and forced-colors behavior | Complete | Yes | Not required | Preserved |
| Session branching and forking | Complete | Yes | Not required | Preserved |
| Separate native chat window without duplicated lifecycle resources | Complete | Yes | Pending | Blocks retirement |

## Separate-window automated evidence

Agent-08g replaces the raw popup/native-process ambiguity with one application-
owned child-window coordinator:

- the existing native process, loopback listener, user-presence manager, command
  ownership tree, and model runtime remain the only owners;
- the first request creates at most one child WebView in the existing GUI loop;
  concurrent and repeated requests focus that child instead of creating another;
- the native bridge accepts only a version and a fresh opaque window key. No
  session identifier or conversation content enters the native URL or Python
  bridge;
- the desired chat is selected through a strict, same-origin, memory-only
  rendezvous channel. Browser fallback uses one fixed popup name and the same
  opaque URL contract;
- closing the child releases only the child. Closing the primary owner destroys
  the child once before the one application cleanup path runs;
- process-free native lifecycle tests assert one listener, one GUI start, no
  worker/runtime/process spawn, deterministic concurrent open/focus/close, and
  bounded owner shutdown. Browser tests cover the full project/chat rail,
  shared runtime controls, file review, draft retention, durable-history
  browsing, and zero horizontal overflow at 360 px and 1440 px.

This is automated evidence, not a native owner acceptance result.

## Post-ledger output truthfulness hardening

Agent-08h leaves the frozen sixteen-item parity decision unchanged while making
its artifact evidence visible at the point of use. A settled turn with no
verified write now says **no reviewed file writes** in the collapsed receipt;
model prose alone cannot look like a created document. Verified artifact cards
render after the active conversation and remain backed by the existing
reviewed-write event, immutable version, digest, and workspace revalidation.
See [checkpoint-agent-08h-handoff.md](checkpoint-agent-08h-handoff.md).

Agent-08y further hardens the already-complete controller group. The v7
protocol cannot call a quarantined cleanup state settled, and its token-free
`wait` continuation resumes from an observed cursor after native review without
submitting the message again or requesting Stop. Markdown artifact cards now
offer a readable rendered view plus exact source while keeping HTML, links, and
remote images inert. See
[checkpoint-agent-08i-handoff.md](checkpoint-agent-08i-handoff.md).

Agent-08j closes a direct-SSE truth gap without changing the frozen capability
count. The relay no longer ends under the obsolete running-only condition:
`closing` and `stopping` remain nonterminal, and both settlement and cleanup
quarantine emit their exact final JSON state before EOF. A controller must
validate that page because stream closure alone is not a success receipt. See
[checkpoint-agent-08j-handoff.md](checkpoint-agent-08j-handoff.md).

Agent-08k makes the complete controller group directly usable from an external
orchestrator. The v3 stdio bridge adds a strict `open` operation for one durable
project and one validated live chat, with no automatic creation retry and
explicit reconciliation/cleanup-uncertain outcomes. This is orchestration
ergonomics and ambiguity safety, not new mutation authority. See
[checkpoint-agent-08k-handoff.md](checkpoint-agent-08k-handoff.md).

Agent-08l hardens the already-complete workspace-review group. A reviewed-path
snapshot is final only when the session is idle and open, no approval is
pending, and neither session-local nor process-wide command cleanup is
uncertain. Session closing is linearized against snapshot construction, and
the UI describes this lifecycle uncertainty without falsely reducing it to an
active turn. See
[checkpoint-agent-08l-handoff.md](checkpoint-agent-08l-handoff.md).

Agent-08m makes the complete shared-runtime/controller groups usable together
without asking an external orchestrator to improvise revision and ambiguity
logic. The v4 stdio bridge's typed `runtime` action observes first, submits one
revision-bound switch or stop at most, validates exact alias/placement or clean
idle evidence, and reconciles one lost response without retrying the mutation.
It blocks on cleanup uncertainty, refuses alias-unsafe Stop, requires explicit
model-lifecycle authorization, and removes raw runtime mutation from generic
`invoke`. See
[checkpoint-agent-08m-handoff.md](checkpoint-agent-08m-handoff.md).

Agent-08n hardens the already-complete artifact group. The viewer no longer
shows a version count while silently opening only the head: users can select
the exact immutable version, inspect provenance and digest identity, and
preview or download only after workspace-byte revalidation. Historical
revisions are never substituted with current bytes; stale history fails closed
and cannot expose the current-file action. See
[checkpoint-agent-08n-handoff.md](checkpoint-agent-08n-handoff.md).

Agent-08o makes the complete controller group directly discoverable by Codex,
Claude Code, and other MCP clients. The dedicated Agent MCP server mirrors the
validated finite controller operations, requires per-call sensitive-egress
receipts, double-gates generic deletion, omits runtime lifecycle by default,
and cannot approve native work. Its generated configuration is token-free and
starts no application, model, agent, shell, or visible terminal. See
[checkpoint-agent-08o-handoff.md](checkpoint-agent-08o-handoff.md).

Agent-08p adds full-composition and packaged-entry evidence without changing
the frozen capability count. A synthetic client crossed the real MCP stdio
protocol, authenticated loopback TCP listener, production controller, and
durable catalog; a second MCP process observed the retained fictional project.
The shared runtime stayed idle and cleanup released the listener. A disposable
installed console probe validated both generated provider configurations, but
no real provider config or session was touched. See
[checkpoint-agent-08p-handoff.md](checkpoint-agent-08p-handoff.md).

Agent-08z closes the remaining external-agent media-ingress gap without
changing the frozen capability count. The dedicated MCP operation stages only
caller-supplied, integrity-bound inline PNG/JPEG/PCM-WAV data for one exact
project/chat; it has no path, URL, byte-read, delete, approval, or runtime
authority. The native composer refreshes and labels external provenance before
send. See [checkpoint-agent-08z-handoff.md](checkpoint-agent-08z-handoff.md).

Agent-09a converts the separate native chat window's owner-shutdown item from
automated-only evidence to a live Windows lifecycle pass. The owner removes its
child without a second confirmation, and cooperative automation/provider
cancellation prevents the previously observed `automation_grant_worker`
cleanup failure. The live owner-plus-child close left no Agent or diagnostic
window, listener, terminal, or model process. Model-backed Stop, reviewed write,
and CPU/GPU cleanup acceptance remain pending. See
[checkpoint-agent-09a-handoff.md](checkpoint-agent-09a-handoff.md).

Agent-09b validates the recommended direct Streamable HTTP MCP path with two
independent clients against one disposable owned listener, durable fictional
catalog visibility, and immediate 401 rejection after credential revocation.
No bridge process, terminal, model, provider configuration, or response-content
logging is involved. The same slice repairs short-desktop rail starvation so
Projects/Chats, Agent settings, and bounded runtime controls remain reachable;
the 360 px/1,440 px matrix and live 1,268 px native reload pass. Creating a real
one-time client bearer still requires immediate owner confirmation and is not
claimed by the automated receipt. See
[checkpoint-agent-09b-handoff.md](checkpoint-agent-09b-handoff.md).

Agent-09c closes the external turn-cancellation ergonomics and truthfulness
gap. The default MCP v8 surface exposes a dedicated, exact-identity
`agent_stop` tool with literal mutation authority, at-most-once delivery,
bounded read-only reconciliation, and terminal cleanup evidence. Idle and
already-stopping chats are not mutated again; uncertain delivery, incomplete
drain, and cleanup quarantine remain distinct. Generic `stop_turn` invocation
is refused. The native reload retained the fictional chat with one listener,
zero model processes, and no visible terminal window. See
[checkpoint-agent-09c-handoff.md](checkpoint-agent-09c-handoff.md).

Agent-09d closes the external durable-chat continuation gap. The default MCP
v9 surface exposes a dedicated `agent_resume` tool with exact project/chat,
catalog-revision, and history-revision identity, literal mutation authority,
at-most-once delivery, and one read-only reconciliation after an ambiguous
response. Stale, archived, metadata-only, unavailable, and cross-project
records fail before mutation; already-live chats are not mutated. Recovered
chats restore no write, command, or web authority, and generic resume-route
composition is refused. See
[checkpoint-agent-09d-handoff.md](checkpoint-agent-09d-handoff.md).

Agent-09e closes the external retained-history branching gap. The default MCP
v10 surface exposes a dedicated `agent_fork` tool with literal mutation
authority, exact source identity and revisions, and a caller-owned idempotency
key that also binds every optional branch field. Trusted client rejections are
not retried; ambiguous first results receive at most one byte-identical retry.
Validated receipts prove exact source/destination lineage and no copied
approval, mutation authority, pending tool state, staged attachment, or
artifact. Generic fork-route composition is refused. See
[checkpoint-agent-09e-handoff.md](checkpoint-agent-09e-handoff.md).

Agent-09f closes the external retained-history export gap. The default MCP v11
surface exposes a dedicated `agent_export` tool with exact project/chat,
catalog revision, history revision, and caller event ceiling. The underlying
route can reject stale revisions before returning content, and the controller
requires complete contiguous coverage and coherent turn counts. Its projection
omits workspace paths, attachment bytes, live approvals, raw tool
payloads/previews, and mutation authority. Generic export-route composition is
refused. See [checkpoint-agent-09f-handoff.md](checkpoint-agent-09f-handoff.md).

Agent-09g closes the external live-chat shutdown gap. The default MCP v12
surface exposes a dedicated `agent_close` tool that requires literal mutation
authority plus exact project/chat and catalog/history revisions. External
close is idle-only and atomically revalidated; active, pending-approval, stale,
cross-project, and cleanup-uncertain states fail before the live runtime is
removed. Ambiguous delivery receives one read-only live/catalog
reconciliation and no second DELETE. Durable chat metadata and retained
history are never deletion targets. See
[checkpoint-agent-09g-handoff.md](checkpoint-agent-09g-handoff.md).

Agent-09h closes the operator-guidance gap between the MCP v12/controller-CLI
v5 implementation and the owned native Agent window. Direct connection setup
now presents the real sixteen core tools as a compact grouped disclosure and a
correct open → turn → stop/wait → live-close lifecycle. The advanced CLI card
includes the previously missing generic invoke, finite turn, and dedicated
live-close commands, and explicitly states that close is at-most-once and keeps
the durable chat. Responsive Chromium and component coverage make this visible
contract part of the release evidence. See
[checkpoint-agent-09h-handoff.md](checkpoint-agent-09h-handoff.md).

Agent-09i hardens the completed artifact group at the byte-to-view boundary.
Preview and download now require exact agreement between the response metadata,
Blob size, safe generated filename, and the selected immutable version. Image
decode state and URL cleanup are explicit. PDF bytes never enter an iframe:
the pinned local renderer draws one page at a time to canvas without an
interactive annotation layer or external fetch path. Parser/decode failures,
project/chat scope changes, mobile bounds, and resource cleanup have focused
component and Chromium evidence. The native artifact owner gate remains
pending. See [checkpoint-agent-09i-handoff.md](checkpoint-agent-09i-handoff.md).

Agent-09j completes the code-only modern Office viewer and artifact-action
slice without changing the frozen capability count. DOCX, PPTX, XLSX, and ODT
use bounded, digest-bound, server-derived text/table projections; no Office
runtime, conversion process, macro, embedded object, link target, or network
service is invoked. Legacy formats stay download-only. Artifact cards can
reveal non-editable current files in the bounded owned tree without reading
them, and reviewed-write cards route to the exact retained net diff. See
[checkpoint-agent-09j-handoff.md](checkpoint-agent-09j-handoff.md).

Agent-09k closes the discoverability gap between the complete MCP/controller
surface and the owned native connection card. It makes `POST /mcp/agent`
visible, exposes the exact current loopback endpoint only in the one-time
private setup, provides a credential-free orchestration starter, and reports
never-used versus last-authenticated-request state after explicit refresh. The
timestamp is not promoted to evidence of a completed turn, write, or artifact.
See [checkpoint-agent-09k-handoff.md](checkpoint-agent-09k-handoff.md).

Agent-09l adds content-free evidence that a connected orchestrator invoked an
MCP tool, without changing the frozen capability count. Each connection can
retain only the last validated tool name, protocol outcome, and time. Malformed
or unknown names become the fixed `unknown_tool` label; arguments, results,
prompts, paths, project/chat identities, tokens, and exceptions are never
stored. Receipt persistence is observational and cannot turn a settled tool
response into retry ambiguity. See
[checkpoint-agent-09l-handoff.md](checkpoint-agent-09l-handoff.md).

Agent-09m closes the external exact-file handoff gap without bypassing the
completed workspace-review group. `agent_propose` accepts only exact UTF-8
creates or revision-bound edits, creates one idempotent live proposal, and
leaves publication exclusively to the existing native diff approval. Stale,
no-op, replay-conflicting, denied, stopped, timed-out, and unverified outcomes
remain separate and cannot become success claims. See
[checkpoint-agent-09m-handoff.md](checkpoint-agent-09m-handoff.md).

Agent-09n hardens the final client-setup handoff. The native credential path
and token-free CLI template now share one canonical generator that parses and
exactly validates both Codex TOML and Claude Code JSON before returning them.
Invalid or non-loopback endpoints fail before durable connection creation or
rotation. The one-time private card guides token, config, and verify/delegate
steps for one selected client and keeps endpoint/config readiness separate from
server-observed authenticated-request proof. Provider configuration remains an
explicit owner action and Prompt Enhancer starts no terminal or client. See
[checkpoint-agent-09n-handoff.md](checkpoint-agent-09n-handoff.md).

Agent-09o adds an in-window, credential-bound endpoint self-test without
weakening the external-client owner gate. From the one-time private card it
performs the real Streamable HTTP initialize/initialized handshake, validates
the exact seventeen core tools plus scoped `agent_runtime` presence or absence,
and calls only `agent_discover`. It refuses unsafe or cross-origin endpoints
before the bearer is sent, keeps the bearer out of rendering/storage/results,
and starts no model, process, terminal, project, chat, or file action. The UI
labels its receipt as local endpoint evidence rather than proof that Codex or
Claude connected. See
[checkpoint-agent-09o-handoff.md](checkpoint-agent-09o-handoff.md).

Agent-09p closes the external multi-file publication gap without broadening
approval authority. The MCP v14 surface adds `agent_propose_transaction` for
two to eight exact existing-file edits, one combined native review, exact
post-review revalidation, and failure-atomic publication with verified rollback
or explicit unverified state. It also removes the preview-TTL race from
model-authored change sets. See
[checkpoint-agent-09p-handoff.md](checkpoint-agent-09p-handoff.md).

Agent-09q removes the existing-file-only limitation from that atomic lane. The
workspace transaction v2, controller v11, and MCP v15 contracts distinguish
absence-bound creates from revision-bound edits all the way through native
review, apply, per-file receipts, HTTP/MCP validation, and the strict browser
parser. Rollback restores edits and removes only the exact created identity
published by the same transaction; replacement races become unverified and
are preserved. Model-authored consecutive `write_file` calls use the same
mixed operation contract. See
[checkpoint-agent-09q-handoff.md](checkpoint-agent-09q-handoff.md).

Agent-09r brings that mixed-operation lane into the manual Files & review card.
Users can stage new UTF-8 files with existing-file edits, reopen or rename a
staged creation before review, see explicit create/edit counts and labels, and
approve one combined transaction. Case-insensitive duplicate paths are refused
before preview. A failed mixed apply reports restored edits and removed
same-transaction creations separately while preserving every draft; an
unverified result still locks further mutation. The UI exposes no general
delete operation. See
[checkpoint-agent-09r-handoff.md](checkpoint-agent-09r-handoff.md).

Agent-09s adds the missing first-class content-search lane shared by the native
Files & review card and the external Agent MCP. Literal or bounded-regex queries
operate only on admitted UTF-8 text under a root-relative glob; generated
folders, binary or oversized files, links/reparse points, entry/byte/match
limits, and deadlines remain excluded or explicitly partial. Results carry
canonical relative path/line identities, inert excerpts, and exact coverage
counts. The controller advances to v12 with 59 Agent routes and the MCP to v16
without adding a tool or any mutation/approval authority. See
[checkpoint-agent-09s-handoff.md](checkpoint-agent-09s-handoff.md).

Agent-09t makes the completed Files & review capabilities subordinate to chat
at every supported viewport. Files and Changes are persistent tab panels in one
review drawer; medium and narrow layouts use a modal sheet rather than adding a
second workbench row, while wide layouts retain the reviewed resizable column.
Draft-discard confirmation, background blocking, tab keyboard navigation,
receipt-file focus/visibility, and chat-focus restoration are covered in main
and dedicated views at 360 px, 1,024 px, and 1,440 px. No workspace, approval,
model, controller, or MCP authority changed. See
[checkpoint-agent-09t-handoff.md](checkpoint-agent-09t-handoff.md).

Agent-09u makes the external-client readiness claim end-to-end truthful. The
server's bounded MCP instructions now teach the exact normal orchestration
sequence and its native-review/evidence boundaries. The owned endpoint
self-test rejects missing, incomplete, or oversized guidance before reporting
**Handshake + workflow passed**. It still does not claim Codex or Claude Code is
configured until a real scoped request produces the durable, content-free
activity receipt. See
[checkpoint-agent-09u-handoff.md](checkpoint-agent-09u-handoff.md).

Agent-09v hardens the complete chat-navigation group at the unsent-content
boundary. Text and staged media now follow their exact live session across
switches without entering browser storage or another chat. Exact send
completion cannot erase a newer draft, late media responses cannot cross the
selection boundary, and permanent deletion purges the owning draft only after
the catalog mutation succeeds. The rail's draft receipt is content-free. See
[checkpoint-agent-09v-handoff.md](checkpoint-agent-09v-handoff.md).

Agent-09w hardens the complete shared-runtime and chat-navigation groups at
their recovery boundary. A stopped or model-less chat now keeps the user in
Agent when coordinated runtime controls and installed choices exist, expands a
collapsed rail, and focuses the exact selector. Empty catalogues and legacy
backends retain the truthful Models-page path. The action itself requests no
runtime mutation and the state copy, first-message guidance, and composer agree
on the same next step. See
[checkpoint-agent-09w-handoff.md](checkpoint-agent-09w-handoff.md).

Agent-09x hardens the complete Files & review group at its unsaved-work
boundary. Internal workspace draft transitions no longer call the synchronous
browser confirmation API: the shared modal traps focus, keeps drafts on Escape
or cancellation, restores focus to the initiating control, and names the exact
draft scope before an explicit destructive action. Staged-edit removal now
preserves the staged text as an unsaved editor draft when the UI promises that
outcome. No file write, delete, model, approval, controller, or MCP authority
changed. See
[checkpoint-agent-09x-handoff.md](checkpoint-agent-09x-handoff.md).

Agent-09y hardens the complete Agent-page navigation group at the same
unsaved-work boundary. Drawer close, live and retained chat switching,
dedicated-window selection, replacement-chat creation, and live-session close
now use the shared non-blocking dialog rather than `window.confirm`. Clean
navigation remains synchronous; dirty navigation fails closed, keeps state on
Escape/cancel, and restores focus. Dedicated-window selection is acknowledged
only after acceptance, and closing the active chat presents one combined
retention/workspace consequence. No workspace file, project, durable catalog
entry, runtime, approval, controller, or MCP authority changed. See
[checkpoint-agent-09y-handoff.md](checkpoint-agent-09y-handoff.md).

Agent-09z hardens the complete artifact group at its explicit-download
boundary. Each request is owned by one exact project, chat, artifact version,
viewer lifetime, and transport; replacement or close aborts it, and late bytes
cannot create a Blob URL or click a download link. Terminal digest, missing,
malformed, and response-contract failures invalidate the matching preview and
disable download, while transient preparation failures remain retryable. Open,
Reveal, and Review retain distinct editor, tree-selection, and bounded-diff
semantics. No workspace, runtime, approval, controller, MCP, or reusable
mutation authority changed. See
[checkpoint-agent-09z-handoff.md](checkpoint-agent-09z-handoff.md).

Agent-10a hardens the complete capability-gated media group at its local
lifecycle boundaries. Microphone permission, capture, encoding, list, stage,
remove, and Send are now serialized or cancelled by exact
session/runtime/transport ownership. Late microphone grants release tracks,
partial audio setup cleans its graph, stale list results cannot overwrite a
newer mutation, failed refresh preserves known identities, and attachments
from a different model visibly block Send until re-staged. No capability is
inferred from a model name, and no model, approval, workspace, controller, or
MCP authority changed. See
[checkpoint-agent-10a-handoff.md](checkpoint-agent-10a-handoff.md).

Agent-10b hardens the shared runtime and context-truth group across asynchronous
ownership boundaries. Runtime and chat-context reads are newest-request owned;
bound context must match the exact chat and model; Start/Switch, chat binding,
and Stop are abortable and transport-owned; and late operation results cannot
cross a replacement view. Loading, draining, unloading, cleanup-unconfirmed,
and quarantined states fail closed before mutation. No model, approval,
workspace, controller, MCP, or reusable authority changed. See
[checkpoint-agent-10b-handoff.md](checkpoint-agent-10b-handoff.md).

Agent-10c hardens the durable project/chat navigation group across persistence,
concurrency, and external-controller boundaries. Project deletion is
project-revision bound; chat deletion is catalog- and history-revision bound;
resume, deletion, update, model binding, and recovered-authority revalidation
serialize against live-session state. Rail mutations and branching are
abort-owned and ignore stale results, while New-chat and catalog dialogs return
focus to their exact triggers. Whole-suite validation also shortened model
child control polling so cancellation retains a bounded Windows tree-cleanup
margin. No model, approval, workspace, or remote authority was added. See
[checkpoint-agent-10c-handoff.md](checkpoint-agent-10c-handoff.md).

Agent-10d hardens the conversation-fidelity group at its rendering and scale
boundaries. Safe GFM/code rendering keeps HTML, remote images, unsafe schemes,
and unbounded workspace links inert; copy controls report success, failure, or
unavailability; model reasoning is explicitly model-provided and never
reconstructed; tool results retain truthful known/unknown semantics; and the
transcript mounts only a bounded latest window with explicit earlier-event
batches while preserving full receipt logic. Frontend and backend event kinds
now reject cross-kind authority and incomplete tool/approval correlation. No
runtime, workspace, approval, controller, MCP, or reusable authority was added.
See [checkpoint-agent-10d-handoff.md](checkpoint-agent-10d-handoff.md).

Agent-10e reconciles the old user-facing capability list with the completed
implementation ledger and makes that truth visible in Agent settings. Fifteen
requested capabilities map to the sixteen frozen groups; automated evidence,
platform blockers, and ten pending owner checks remain separate. Route
ownership, hostile Markdown, loopback controller/MCP, desktop/320 px,
forced-colors, generated-schema, and privacy boundaries pass without starting
a model or acquiring new authority. See
[checkpoint-agent-10e-handoff.md](checkpoint-agent-10e-handoff.md).

Agent-10f closes the external-client handoff proof without expanding authority.
The private connection card copies exact token-free Codex and Claude Code add
commands alongside its parsed config documents, but never executes a command or
edits provider settings. A real-loopback synthetic MCP acceptance run now
proves durable project/chat creation, a failure-atomic edit-plus-create proposal,
no publication before native review, one-shot browser/native approval, settled
verified receipts, and exact workspace read-back. No model, command, web fetch,
microphone, provider configuration, or child process is used. See
[checkpoint-agent-10f-handoff.md](checkpoint-agent-10f-handoff.md).

Agent-10g closes the pre-authorization setup-visibility gap. The authenticated
`GET /v1/integrations/agent-mcp/setup` response contains only the exact
loopback endpoint, canonical Codex/Claude configuration documents, and their
token-free add commands. Its strict backend and frontend contracts require no
credential, no granted authority, native creation before use, no process or
terminal start, and no provider configuration change. The Agent card exposes
that disconnected preview independently of native mutation availability and
keeps the private one-time setup unchanged. No connection, provider setting,
model, workspace, approval, or reusable authority is created. See
[checkpoint-agent-10g-handoff.md](checkpoint-agent-10g-handoff.md).

Agent-10h closes the remaining generated-output capture gap. Retained chats can
now inspect an existing workspace file through a content-free metadata preview
and bind a later native-confirmed capture to its exact path, title, SHA-256, and
byte size. Non-editable binary, image, PDF, and Office-style tree entries open
the same review instead of presenting a dead control. Changed files fail closed
and require a fresh preview; successful captures become immutable artifact
cards with the existing bounded viewers. See
[checkpoint-agent-10h-handoff.md](checkpoint-agent-10h-handoff.md).

Agent-10i closes the controller-to-artifact-review gap without expanding
authority. The strict MCP `agent_artifacts` tool now has a `preview_capture`
action that returns only the exact project/chat-bound relative path, title,
classification, viewer kind, byte size, and SHA-256 digest of an existing
workspace file. It returns no bytes, creates no artifact or approval, and
cannot perform capture; the owned native Agent UI remains the only confirmed
capture lane. Generic invocation, unsafe paths, cross-scope responses, hidden
payloads, and false confirmation claims fail closed. See
[checkpoint-agent-10i-handoff.md](checkpoint-agent-10i-handoff.md).

Agent-10j begins the final card-by-card visual audit with a reproduced shell
defect. At medium desktop widths, the global application rail and the Agent
project/chat rail were both permanent, leaving only about 547 px for chat at
the owner's 1046 px viewport. The Agent route now collapses only the redundant
global rail into the existing compact header from 861 through 1180 px; Menu
retains the complete application navigation, while other routes and the mobile
and dedicated-window shells remain unchanged. Live chat width is 761 px with
no horizontal overflow or browser diagnostic. See
[checkpoint-agent-10j-handoff.md](checkpoint-agent-10j-handoff.md).

Agent-10k completes the project/chat rail and shared-runtime interaction slice.
A filtered catalog response can no longer clear the selected project or
unmount its still-valid conversation; clearing search restores navigation
without reselection, and the collapsed rail keeps a bounded selected-project
identity. Rail/runtime targets measure at least 44 px, catalog dialogs trap and
restore keyboard focus while locking background scroll, and the stopped model
selection path was verified without loading a model. See
[checkpoint-agent-10k-handoff.md](checkpoint-agent-10k-handoff.md).

Agent-10l completes the conversation/composer/activity slice. A next-message
text draft remains editable through streaming and Stop transitions without
being silently queued, then unlocks Send after the response settles. Paused
auto-follow exposes a sticky, keyboard-reachable Jump-to-latest action, and
reasoning/tool disclosures have 44 px targets. The existing model-provided-only
reasoning boundary, Stop ownership, per-chat draft isolation, Markdown/code
rendering, and tool-result truth states remain intact. See
[checkpoint-agent-10l-handoff.md](checkpoint-agent-10l-handoff.md).

Agent-10m completes the Files & Review hierarchy audit. The file tree/editor is
now primary while discovery, bounded search, Git metadata, and safety detail
remain mounted behind a collapsed 44 px disclosure. File-pattern and narrow
regex controls now meet the same target, and multi-file diff summaries remain
keyboard-accessible at 44 px. Existing browse, edit, create, move, recoverable
removal, transaction, root-replacement, and change-set behavior is retained and
revalidated. See
[checkpoint-agent-10m-handoff.md](checkpoint-agent-10m-handoff.md).

Agent-10n completes the generated-output and attachment presentation audit.
Capability-gated image, WAV, and microphone choices now live behind one compact
Attach media picker with exact focus dismissal and 44 px controls. Artifact
cards and viewers share the same target, while completed durable turns retain a
truthful empty-output receipt when no reviewed write exists. A model statement
alone still cannot create an artifact, and all prior attachment cancellation,
model-match, private staging, revision, inert-viewer, and download boundaries
remain intact. See
[checkpoint-agent-10n-handoff.md](checkpoint-agent-10n-handoff.md).

Agent-10o completes the detached-chat lifecycle audit. One primary-renderer
memory mapping binds the native owner key to the selected session; child reload
announces readiness and receives that exact session again. Missing, aborted, or
declined targets are never acknowledged as delivered, older concurrent lookups
cannot win late, and child-local navigation becomes the next reload target.
Duplicate opens refocus one child, child close preserves the primary listener,
and the rebuilt live cycle finishes with no model or terminal process. See
[checkpoint-agent-10o-handoff.md](checkpoint-agent-10o-handoff.md).

Agent-10p completes the external-controller onboarding and recovery audit.
Codex, Claude Code, and generic Streamable HTTP clients now retain exact setup
paths after scoped connection creation. The credential-bound endpoint check
has an eight-second whole-workflow bound and reports rejected authority or
contract mismatches through content-free recovery. Active credentials can be
rotated; expired and revoked records can only prepare a separately confirmed
replacement and cannot be reactivated. Live desktop and 390 px checks finish
with no browser diagnostic, model server, or visible terminal. See
[checkpoint-agent-10p-handoff.md](checkpoint-agent-10p-handoff.md).

Agent-10q makes the remaining external-controller owner gate measurable rather
than inferential. Durable tool receipts now label native endpoint self-tests
separately from external MCP traffic, and exact inactive credentials retain a
content-free rejection timestamp. A memory-only Connections card binds one
credential revision to a fresh external `agent_discover`, explicit native
revocation, and a strictly later rejected retry. It never creates, rotates, or
revokes authority automatically and stores no token, content, path, provider
configuration, or error body. See
[checkpoint-agent-10q-handoff.md](checkpoint-agent-10q-handoff.md).

Agent-10r closes the controller/native lifecycle asymmetry without granting an
external apply lane. The strict `agent_propose_lifecycle` tool accepts one
directory create, no-overwrite directory/file move, or exact-revision
recoverable file removal, then waits in the existing native approval card.
Post-decision rebinding rejects stale sources and occupied destinations;
idempotent replays, denial, Stop, timeout, failure, and unverified effects stay
content-free and fail closed. A real loopback MCP test completes a reviewed
file move and reads the verified destination back without loading a model or
spawning a child process. See
[checkpoint-agent-10r-handoff.md](checkpoint-agent-10r-handoff.md).

Agent-10s closes the external reviewed-write artifact asymmetry without
retaining controller content. For owner-selected **Save locally** chats, only
an approved, verified create/edit receipt enters durable history and projects
to the same immutable artifact lineage used by native reviewed writes. A fresh
catalog/artifact service rebuilds the cards and every version after restart.
Proposal payloads, diffs, approval identities, denied/failed/unverified
attempts, and metadata-only chats remain live-only. The orchestration contract
advances to v15 and MCP to v19 without adding a route, tool, approval, or byte-
capture authority. See
[checkpoint-agent-10s-handoff.md](checkpoint-agent-10s-handoff.md).

Agent-10t closes exact file-move continuity for saved artifact cards. After a
verified manual, local-model, or externally proposed file move, the app
rehashes the destination and appends an immutable `reviewed_move` version to a
matching source artifact while preserving its ID and prior versions across
restart. Stale source identity is not inferred; a pre-existing destination
card is never merged or overwritten and instead makes the metadata outcome
explicitly unverified with partial review coverage. Orchestration advances to
v16, MCP to v20, and the artifact contract to v2 without adding a route, tool,
approval, byte-return, or direct-apply capability. Directory moves and
recoverable-trash lineage remain outside this slice. See
[checkpoint-agent-10t-handoff.md](checkpoint-agent-10t-handoff.md).

## Guarded owner acceptance

The Agent page now contains **Connections & controller API → Owner acceptance**.
It is collapsed and inert by default. Beginning it requires the owned native
user-presence bridge. The start receipt is exact and content-free and proves
that the gate itself:

- did not start model execution;
- did not request a process spawn;
- did not request workspace access;
- persisted no content;
- expires when the page reloads.

After the gate, **Check current evidence** performs only bounded reads of the
existing runtime, turn-summary, and change-set contracts. The card has no Start,
Stop, Send, write, approval, command, or fetch method. It never retries on its
own.

The guided run requires these observations in one live chat:

1. a clean idle runtime baseline with no active request and confirmed cleanup;
2. a later revision with a capability-verified served runtime;
3. one completed streamed turn;
4. one `stop_requested` turn receipt;
5. the Files & review drawer plus a successful strict change-set read;
6. truthful known-or-unknown context state;
7. a later idle runtime revision with confirmed process exit;
8. `not_required` GPU cleanup for CPU, or a measured GPU-memory delta for a
   GPU-backed run.

Unknown or failed cleanup never completes the run. Evidence from two sessions
cannot be combined. An interrupted read retains prior evidence and does not
trigger a retry.

## Retirement decision

Do not remove a legacy surface yet. All sixteen capability groups now have
implementation and automated evidence, and no platform implementation blocker
remains in this ledger. The owner must still run the guarded native reload,
window, model, Stop, file-review, unload, process-exit, and CPU/GPU cleanup
acceptance and record its content-free receipt before any legacy deletion.
