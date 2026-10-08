# ADR 0016: Local agent workspace - a local model working in one folder with approvals

- Status: accepted (2026-08-20), streaming, manual-editor, discovery and failure-atomic transaction slices added
- Owner direction: a separate window where the chosen local model works the
  way Codex or Claude Code work - with tools (files, terminal, web), usable
  through the endpoint or inside the app's chat, to write code and documents;
  the elements a code editor needs should live inside this application, built
  on a sound architecture.

## Context

The app already runs a strong local model on the owner's GPU (ADR 0013) and
talks to it through an OpenAI-compatible loopback endpoint; llama.cpp's chat
template engine emits proper `tool_calls` for Qwen3 when started with
`--jinja`. What was missing was a place where that model can *act*: inspect a
folder, change files, run tests, and report - under the same rule as the rest
of the app: nothing happens to the person's machine without their say-so.

## Decision

1. **One folder, one session.** `application/local_agent.py` holds sessions
   in memory. A session is bound to an absolute folder the person chose (not a
   drive root; optionally restricted to allowed roots). Production composition
   refuses any workspace that overlaps the app home, provider homes, local
   model store, or common credential directories. Every path the model names
   must stay inside the workspace; symlink/reparse components and hard-linked
   write targets fail closed. The session records its own event stream (user, assistant,
   tool_call, tool_result, approval_required/resolved, status, error, done),
   bounded and cursor-paged, so any UI can follow it.
2. **Tools with two trust levels.** `read_file`, `list_dir`, `search_text`
   run immediately (bounded output, binaries refused, noisy folders skipped).
   `write_file` (a unified diff is produced first), `run_command` (PowerShell
   on Windows, bash elsewhere, workspace as cwd, timeout, output capped) and
   `fetch_url` (off unless enabled) **pause the run** with an
   `approval_required` event carrying the exact arguments and the diff; the
   person approves or denies that one call through an owned native confirmation
   bridge (the API token and browser cookie are not human-decision credentials);
   standard `serve` and attached-window modes keep these controls unavailable; a denial is
   reported to the model as a tool result so it adapts instead of retrying;
   stop cancels any pending approval. A write preview is bound to the exact
   file hash, file identity and parent identity; a file changed while approval
   is pending is never overwritten.
3. **The loop.** Per user message the service runs at most N model steps:
   the model gets the conversation plus the tool schemas for the permissions
   the session allows; tool calls are executed in order and their results
   appended as tool messages; a plain reply ends the turn. Thinking is off for
   speed; the model's own chat template is used (`--jinja`, on by default in
   the runtime activation together with flash attention and an 8-bit KV
   cache, with a plain retry if the runtime refuses them).
   The agent consumes the runtime's OpenAI-compatible SSE reply directly.
   Bounded `assistant_delta` events carry content (and, only when the person
   enabled thinking, separately labelled reasoning) while tool-call fragments
   are reassembled and validated before the approval loop sees them. A stream
   must end with `[DONE]` or a terminal `finish_reason`; stopped, incomplete,
   malformed and oversized replies get an explicit terminal state and never
   enter model history as completed assistant messages.
   Generation termination is not task verification: token-limit, filtered and
   unrecognized finish reasons remain incomplete even when the stream has a
   terminal marker. A reasoning-only response without an answer or tool request
   is incomplete too. Partial output remains visible but cannot run tools or
   enter completed conversation history. Whole-response fallbacks obey the same
   rules, including a Stop received while waiting for their response. A terminal
   finish receipt releases the response without waiting for a redundant marker.
4. **Surfaces.** `/v1/agent/*` (sessions, messages, events, private SSE event
   stream, approvals, stop, and session-bound workspace tree/file/preview/apply)
   under the app token; the *Agent* page (folder, model, permissions,
   sessions list, transcript with tool cards, approval dialog with diff,
   composer, stop) and an application-owned child at
   `/agent/window?window=<opaque-key>`. A dedicated
   Windows `prompt-enhancer-agent` launcher opens `/agent`, owns the loopback
   server and native confirmation manager together, and refuses to attach to
   an already-running listener. Its listener is atomically reserved before
   application startup; when the configured port is occupied, it owns an
   OS-assigned loopback port instead and leaves the existing listener untouched.
   The first separate-window request creates at most one child WebView inside
   that same process and GUI loop. Repeated or concurrent requests focus the
   existing child. The child owns no listener, server, worker, command tree,
   model runtime, or cleanup path. Its native bridge receives only an exact
   version and fresh opaque key; a strict same-origin, memory-only channel hands
   off the selected session without placing a session identifier in the native
   URL or Python bridge. Closing the child releases only that child; primary
   owner shutdown destroys it once before the existing bounded cleanup.
   The GUI entry and terminal-oriented Agent entry share one fixed Windows-
   session instance lease. A duplicate closes its duplicate handle, makes one
   bounded exact-title focus attempt and exits without creating a listener,
   worker, lifecycle marker or WebView. A focus failure is never authority for
   a fallback instance.
   Its explicit Browse action uses an
   exact-origin native folder dialog on exact `/agent` or the exact opaque child
   route; cancel/unavailable results
   are content-free and the chosen path remains subject to the service's full
   workspace validation. The same page
   now includes a typed file tree and dependency-free UTF-8 text editor beside
   the chat. Manual edits use a server-created diff plus a short-lived,
   single-use, content-free capability and require owned-window native confirmation to
   apply; the model's `allow_writes` switch does not restrict the person's own
   manual edit.
5. **Boundaries.** Nothing is persisted beyond the server's memory (no
   transcript of the agent's work is stored); the agent module itself opens
   no network connection - web fetch is a pluggable callable that is absent
   unless the app composes one, and even then every fetch needs approval;
   the runtime stays on loopback.
6. **Closing is explicit and irreversible.** The `local-agent.v3` session
   and event contracts require a boolean `closing` field. Entering closing
   emits one status event, waking already-connected windows even if a turn
   produces no more output. A surviving turn returns `session_stop_timeout`
   without discarding its session; new messages and late model-action approvals
   are refused. The UI preserves the unsent draft, disables new chat work and
   session-model activation, and offers an explicit close retry. Late snapshots
   cannot reopen that session. Stopping a shared model remains a separate action.
   Successful deletion requires the documented empty HTTP 204 response; an
   already-absent session can be removed from a stale window after HTTP 404.
   Deploy the frontend and backend contract together and reload existing pages;
   older event versions are rejected, not guessed into the new lifecycle.

## Consequences

### Checkpoint 26: memory-only turn and write receipts

The current session/event contract is `local-agent.v4`; the `closing` semantics
introduced in v3 remain mandatory. Each admitted turn binds its events and final
`done` receipt to one turn ID. `agent-turn.v1` records generation termination,
actual requested alias, server-monotonic timing, runtime usage coverage and tool
outcomes. Completion of a response is never task verification.

`agent-token-usage.v1` accepts only coherent runtime-reported integer counts.
Missing, partial and invalid usage remain distinct. A per-field turn sum requires
that field from every issued model request; absent requests are not counted as
zero. No cost, token estimate or GPU-only timing is inferred. A model alias is
not promoted to an immutable model/tokenizer identity.

`agent-write.v1` describes one reviewed `write_file` attempt. Verified byte
readback supplies before/after revisions, created/modified/unchanged status and
versioned line-change counts. Failed readback records an unverified effect;
refusal before writing records no applied change. Commands have explicit unknown
file effects, not inferred inventories. Manual/external edits and net Git state
are outside this receipt. These paths/hashes remain sensitive memory-only data.

Both Agent views expose collapsed turn details and current-file links. The
dedicated view opens a workspace pane on demand. Existing draft-discard
confirmation, request/session ownership, native apply approval and workspace
boundaries remain in force. Effect-remount recovery must retry an initial file
read cancelled by cleanup, without replaying a consumed request on normal
rerenders. Reload pages and restart with matching frontend/backend versions.

The owned runtime adapter may collect one deadline-bounded usage trailer after
the finish chunk. This does not admit later text or tool calls. Actual Windows
HTTP tests cover blocked-read cancellation and chunked/content-length framing;
pre-header cancellation and in-flight command interruption are separate limits.
See [checkpoint 26](../checkpoint-26-handoff.md) for proof and remaining work.

### Checkpoint 27: request-owned Stop and v5 lifecycle state

Agent v5 adds explicit `stopping` state to session views and event pages. Stop
publishes one state transition and signals the current turn's cancellation event
before any response-header wait. Socket connect, upload, partial headers and
body reads observe that event; separate turns and shared models do not. Normal
response closure never sets the shared turn event. Cancellation remains active
through real worker completion, and injected noncooperative work cannot reopen
Send merely because a Stop request was accepted.

The UI coalesces Stop, cancels detached acknowledgment requests and refuses older
acknowledgments/event state that would rewind newer activity. It exposes Stop
from another window and separates a loaded model from a session ready to send.
The [checkpoint 27 handoff](../checkpoint-27-handoff.md) supersedes checkpoint
26's pre-header limitation, while in-flight command interruption, all-runtime
acceptance and durable retention remain separate. Reload matching frontend and
backend versions; the normal owner app is not automatically restarted.

### Checkpoint 29: approved command ownership and v6 cleanup state

Agent v6 requires `cleanup_unconfirmed` on session views and event pages. A
joined turn thread alone does not prove command cleanup. The service retains
uncertainty, stops its other Agent turns, denies pending actions and refuses
new sessions, messages, manual edit previews/applies and session deletion.
Read-only inspection remains available. Shutdown reports incomplete ownership
instead of declaring success. This is an Agent-service quarantine, not proof
that a shared model or an unrelated application has stopped.

An already-approved command inherits its own turn's cancellation event. The
default runner drains both output pipes while checking Stop and the deadline;
it retains at most 96,000 raw bytes per stream and returns bounded text tails.
The combined tool result remains capped at 24,000 characters, with an explicit
truncation notice. Cancellation is not a successful command receipt or an
undo of earlier effects. Commands still have uninventoried file effects.

On Windows 10+, documented
[atomic Job Object admission](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812)
assigns the process to its owned job before it starts. The launcher permits
only its stdio handles to be inherited, does not allow breakaway, and never
falls back to an unowned process. Root exit, zero active job processes, joined
pipe workers and handle release are all checked. Setup/release failures attempt
the remaining cleanup steps and retain a fixed failure reason. This follows
the documented [Job Object lifecycle](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [process attribute interface](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).
POSIX uses an owned process group; that platform was not exercised in this
Windows checkpoint. Neither mechanism is a security sandbox or control over
work delegated to external services.

Both Agent views retain cleanup uncertainty across older status/Stop receipts.
Drafts remain selectable and read-only, and copy-before-restart guidance makes
their memory-only lifetime explicit. The shared model's Stop action is separate
from command cleanup. Strict v6 response parsing rejects missing lifecycle
authority; frontend and backend must be reloaded together. Native confirmation
requirements are unchanged. See [checkpoint 29](../checkpoint-29-handoff.md)
for the scoped tests and limits; this supersedes checkpoint 27's default-runner
command-interruption limitation, not its broader acceptance/retention gaps.

### Checkpoint 30: bounded, no-follow workspace inspection

`workspace-inspection.v2` is recorded in the session prompt. Read/list/search
and editor snapshots use the admitted lexical root and no-follow component
handles. Windows holds component handles without write/delete sharing while
inspecting; POSIX uses directory-relative descriptors. Replaced roots and
changed file identities are rejected. Reads are bounded before allocation;
editor snapshots keep strict UTF-8, single-link and revision requirements.

Search uses root-relative glob matching without traversing excluded directories.
Actual entry/byte/depth/match/output limits and cooperative scan deadlines are
explicit. Case-insensitive exclusions are consistent across editor and model
tools. `regex==2026.7.19` supplies bounded matching in compatibility mode.
Truncation, binary/non-UTF-8 exclusions, link refusal and unreadable entries must
not be presented as proof of absence. Stop reaches the same turn's inspection
and cannot become a successful tool receipt or another model request.

The editor distinguishes complete-empty, incomplete and failed directory reads.
A replaced root retains a copyable, read-only draft and blocks editor changes
until the session/connection is replaced. Workspace transport requires
private/no-store responses and preserves only fixed recovery reasons. Native
approval is unchanged; a reviewed mutation is not implied by a successful read.

The [checkpoint 30 handoff](../checkpoint-30-handoff.md) records precise limits,
real Windows junction/handle tests, HTTP and UI recovery evidence. Cooperative
deadlines cannot forcibly interrupt a hung kernel call. Mutation-phase race
validation, richer editing, retention and native/model acceptance remain
separate requirements; this is not a new command sandbox.

### Checkpoint 31: revision-bound reviewed-write publication

`workspace-publication.v1` is recorded in the Agent prompt. A write remains
bound to the reviewed path, parent identity, prior file identity and revision,
and exact proposed bytes. Cross-session writes are serialized through the final
compare-and-publish boundary. An existing file that already contains the exact
reviewed bytes is a true no-op: its inode and timestamps are not churned.

Windows holds the admitted ancestor chain while mutating the final directory.
It opens the reviewed target and a private same-directory stage without
following reparse points, writes and verifies the complete stage, then checks
Stop before publication. New names use an atomic create-if-absent publication.
Existing names use the documented
[ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)
replacement-with-backup operation. The displaced file and published stage are
both verified. A late concurrent edit is restored from the displaced backup;
if exact restoration cannot be proven, the result is explicitly unverified.
Private cleanup is owned by open handles and uses the documented
[SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)
disposition interface. Cleanup failure never becomes a successful receipt or a
path-bearing error.

POSIX uses a directory-relative private stage and an atomic name exchange
(`renameat2(RENAME_EXCHANGE)` on Linux or `renameatx_np(RENAME_SWAP)` on
macOS), failing closed where exchange is unavailable. That branch is implemented
but was not exercised on this Windows checkpoint. Ownership, ACL, xattr and
filesystem-specific metadata parity on POSIX therefore remain an explicit
acceptance gap rather than an inferred guarantee.

Stop can cancel staging before publication and cannot be reported as a write.
Once an atomic publication call begins, cancellation does not pretend to undo
it. Fixed outcomes distinguish a verified rollback/no-write, pre-publication
cleanup uncertainty and an unverified publication/rollback result. Only a
verified published or unchanged result receives an applied receipt. The manual
editor trusts that receipt directly instead of performing a fallible second
read to decide whether the apply succeeded.

The UI preserves the draft for every failed outcome. A verified rollback keeps
the draft reviewable; cleanup or publication uncertainty locks further review
until reload. Transport allowlists expose only fixed reason codes. Native
user-presence approval, strict UTF-8/size limits and the no-follow inspection
boundary are unchanged. The [checkpoint 31 handoff](../checkpoint-31-handoff.md)
records the Windows race, cancellation, cleanup, HTTP and responsive-browser
evidence. This does not certify POSIX metadata behavior, crash-durable
transcripts, multi-file transactions, hostile-command containment or universal
model quality.

### Checkpoint 32: truthful memory-only session effects

The Agent conversation now derives a session-effects ledger from validated turn
summaries retained by the server. It separates observed action requests,
reviewed write receipts, paths with a verified create/modify effect and
unverified writes. A verified `unchanged` receipt is a reviewed no-op and is not
counted as a changed file. Repeated receipts are grouped by path, and repeated
writes in one turn do not duplicate the displayed turn number.

Coverage is explicit: complete retained history, a running unsummarized turn,
incomplete summaries or partial/conflicting history. Invalid summaries,
duplicate turn identities or duplicate turn numbers cannot produce a complete
label. Expired event history remains a retained suffix rather than an invented
session total. Command attempts are called out separately because their file
effects are not inventoried.

The expanded ledger lives inside the transcript's scroll boundary. This avoids
the responsive overlap reproduced when the same content expanded inside the
fixed-height session header; the composer remains independently visible at
narrow and wide widths. File links retain the existing workspace/session safety
checks.

This ledger is not a net Git diff and does not observe manual edits, external
changes or command-created effects. It remains in server memory only and does
not change the no-persistence rule. Durable Agent conversations remain an
explicit owner decision under the privacy-tiered content-vault proposal. See
the [checkpoint 32 handoff](../checkpoint-32-handoff.md) for that historical
receipt-ledger scope. Checkpoint 34 below supersedes the missing reviewed-path
net view; it does not turn the ledger into a whole-workspace or Git inventory.

### Checkpoint 33: atomic native launch and shutdown evidence

Owned native services now receive a pre-bound, non-inheritable exact-loopback
socket. Uvicorn consumes that socket instead of performing a later bind, closing
the check-then-bind race. The protected Agent still never attaches native
approval authority to another process. If every configured-address bind is
unavailable, it reserves an OS-assigned loopback port and builds the owned
composition against that exact origin. The configured listener remains intact.
The read-only metrics overlay retains its stricter configured-port behavior and
may attach only after the existing identity proof succeeds.

Agent and overlay GUI/terminal entry points now publish separate private
`native-lifecycle.v1` records under the application diagnostics directory.
Phases are fixed (`starting`, `service_ready`, `window_created`,
`window_closed`, `stopped`, `failed`), and writes use same-directory atomic
replacement. A clean terminal record therefore survives a normal close, while
a hard exit leaves the last non-terminal phase. The next launch carries only
that fixed prior outcome/phase as `interrupted`. The record contains no clock,
PID, port, host/path, prompt, session, provider, model or exception text.

Returning from the WebView event loop is not itself a close receipt. The native
window's `closed` event must fire before the launcher records `window_closed`;
otherwise it reports `window_close_unconfirmed`, cleans up its owned service and
exits unsuccessfully. This turns the formerly silent code-zero return path into
fixed evidence without retaining window or operating-system detail.

Failure vocabulary is shared with the native message box; unknown codes and
components are discarded. Failure to publish the initial or final lifecycle
record is itself an unsuccessful launcher outcome. A marker-write failure while
reporting an earlier failure does not replace the primary safe failure. The
[checkpoint 33 handoff](../checkpoint-33-handoff.md) records socket, lifecycle,
native-engine and generated-executable evidence. It does not certify native
approval clicks, folder selection, owner window preferences or signed installer
distribution.

### Checkpoint 34: live reviewed-path change set

Every Agent session now owns a bounded `agent-change-set.v1` tracker in memory.
It observes verified and unverified Agent publications plus manual editor
publications that passed the existing revision-bound preview/apply boundary.
For each admitted path it retains the first reviewed baseline, then re-reads the
live file through the existing no-follow `WorkspaceTools` boundary. Current
effects are therefore `created`, `modified`, `deleted`, `reverted` or `unknown`
rather than a sum of historical write receipts. Empty-file existence changes
remain explicit and line-ending-only changes are kept separate from text diffs.
Windows case aliases share one tracker identity while the first reviewed path
spelling remains the display and diff authority.

The inventory is intentionally scoped to `reviewed_paths_only`. A running turn,
an approved command, an unverified publication, a missing/external revision, a
review-chain gap, an unavailable file, an omitted receipt or a tracker failure
makes coverage partial. Commands never gain file authority merely because they
were approved. External divergence is shown but is not relabelled as a reviewed
write. Historical turn receipts remain available in the separate Session
activity disclosure and are explicitly labelled as history, not current state.

The private loopback routes are:

- `GET /v1/agent/sessions/{session_id}/changes` for the content-free inventory;
- `GET /v1/agent/sessions/{session_id}/changes/diff?path=...` for one explicitly
  requested, bounded net diff.

Both require the existing authenticated local session and private/no-store
response policy. The inventory contains counts, fixed states and relative paths,
not content, revisions or hashes. Baseline text is retained only in the session
tracker, with at most 64 paths, 4,000,000 baseline bytes and eight pending manual
preview baselines. A diff remains capped at 60,000 characters. Closing/deleting
the session releases the tracker with the rest of the memory-only conversation.

The coding-chat workbench renders this authority before historical activity,
refreshes after a settled turn or confirmed manual apply, aborts stale session
and diff reads, and can open the current file or exact net diff. A failed refresh
drops the old result instead of presenting it as current. The
[checkpoint 34 handoff](../checkpoint-34-handoff.md) records the regressions,
contract/browser evidence and remaining limits. This is not durable retention,
a Git status implementation, a whole-workspace scan, a multi-file atomic
transaction or rich IDE editing.

### Checkpoint 35: bounded selected-folder and Git discovery

Each active Agent session now exposes one current
`local-agent-workspace-discovery.v1` snapshot. The application recursively
enumerates representable regular files through the existing no-follow
`WorkspaceIO` boundary, returns only relative paths, byte sizes and editor
eligibility, and caps the scan at 20,000 entries, 32 levels, five seconds and
400 displayed files. Generated/protected directories, links and reparse points
are not followed. Deadline, depth, entry, display, exclusion, unavailable and
unrepresentable conditions make inventory coverage partial; an incomplete
zero-row result is never called an empty folder.

When a real `.git` directory exists exactly at the selected root, the same
snapshot may include a bounded `git status --porcelain=v2 -z` result. Git runs
without a shell, prompt, pager, optional locks, lazy object fetching, external
diffs, renames or submodule recursion. Global and system configuration are
disabled. Gitfile/worktree layouts, common-directory pointers, object
alternates, config includes, `core.worktree` redirects and repository-local
diff/filter/merge helper sections fail closed before process start. Repository
replacement, cleanup uncertainty, another approved command, deadline, output
truncation, missing Git, nonzero exit or invalid porcelain produce fixed
content-free states; stderr and partial output are discarded. At most 400
validated, UTF-8-byte-sorted relative changes are shown.
The response never carries file content, revisions, hashes, branch, commit,
remote, absolute paths or stderr.

The authenticated private/no-store route is:

- `GET /v1/agent/sessions/{session_id}/workspace/discovery`.

The workbench card distinguishes complete, partial, non-repository and
unavailable states, filters mapped paths, opens only an application-readable
editor candidate, refreshes after a settled turn or confirmed manual apply and
aborts stale session/transport requests. A failed refresh removes the prior
snapshot. The card explicitly remains read-only observation: only the separate
revision-bound review/publication flow grants write authority. The
[checkpoint 35 handoff](../checkpoint-35-handoff.md) records the regression,
HTTP, browser and full-suite receipts.

This closes the bounded selected-folder/Git discovery slice. It is not an
unrestricted filesystem index, a security sandbox for arbitrary Git versions,
durable history, a multi-file transaction, rich syntax editing or permission to
persist Agent content.

### Checkpoint 36: failure-atomic reviewed multi-file edits

The manual workspace and the model tool loop now share the strict
`local-agent-workspace-transaction.v1` contract for two to eight changed,
existing UTF-8 text files. Each file keeps the existing 256,000-byte and
60,000-character diff bounds; one plan is capped at 1,024,000 proposed bytes and
240,000 diff characters. A session may hold four 120-second preview capabilities.
The capability contains relative paths, before/after revisions, line-ending,
file/parent identity and mode metadata only. It never retains draft or baseline
content, and closing the session destroys every remaining plan.

Preview reads and prepares every member before creating authority. Apply must
repeat the exact sorted path, content, expected revision, proposed revision and
line-ending set, and requires the native user-presence confirmation
`apply_reviewed_workspace_transaction`. The plan is session-bound, single-use
and consumed before mismatch or publication is reported, so a failed or denied
attempt cannot be replayed. HTTP reads and responses retain the authenticated
private/no-store policy.

Publication holds the existing application write lane, re-preflights all
members, applies the individually atomic exact writes, verifies their receipts
and rereads every final revision. If a later member rejects or the cooperative
Stop signal arrives after an earlier publication, already published members are
restored in reverse order inside a bounded critical cleanup scope. A restored
revision is claimed only after exact readback. Any external race, uncertain
publication, uncertain cleanup or uncertain rollback becomes `unverified` and
does not claim commit or rollback. This provides failure atomicity while the
reviewed workspace stays stable; portable cross-file operations are not
power-loss atomic and cannot exclude writes by another process.

The workbench keeps staged drafts locally, requires at least two files, shows
every file diff under one review, disables the single-file path while a plan is
staged and asks for one native confirmation. A verified commit clears the
drafts and refreshes reviewed-path state; a verified rollback preserves them;
an unverified result preserves copyable drafts and hard-locks all further
writes for that session. Consecutive groups of two to eight valid existing-file
`write_file` calls in one model reply use the same transaction and one approval,
while keeping a distinct tool result and write receipt for each file. New files,
non-consecutive calls and larger groups remain on the existing single-file path.

The [checkpoint 36 handoff](../checkpoint-36-handoff.md) records the rollback,
cancellation, transport, UI and browser evidence. This slice does not add
create/rename/move/delete, conflict merging, a journaled filesystem transaction,
durable Agent content or owner-independent native approval.

### Checkpoint 37: reviewed create and no-overwrite move

The workspace now exposes a separate strict
`local-agent-workspace-lifecycle.v1` contract for creating one UTF-8 text file
and renaming or moving one existing clean UTF-8 text file. Every capability is
memory-only, metadata-only, session-bound, single-use, capped at eight per
session and expires after at most 120 seconds. The exact deadline is expired.
Create apply resubmits the complete normalized content and line-ending choice;
move apply resubmits the exact source, target and reviewed revision. Both
require their own native user-presence confirmation.

Parents must already exist and remain identity-stable. Destinations must remain
absent and are never overwritten. Create reuses the existing atomic
create-if-absent publication. Move binds source identity, hash, size, mode and
both parent identities, then uses an operating-system no-replace rename while
the source handle and directory chains remain pinned. Publication and any
rollback are claimed only after exact path, identity and content readback. An
uncertain result hard-locks later lifecycle changes for the session.

The reviewed change set records create as one write and move as the old-path
deletion plus new-path creation. The workbench exposes complete create and move
reviews, preserves drafts, refreshes the folder/discovery/change views and
rereads the verified file. The [checkpoint 37 handoff](../checkpoint-37-handoff.md)
records native race, rollback, parser, HTTP, component, browser and broad-suite
evidence. Directory creation, deletion, overwrite, directory moves, case-only
Windows renames, power-loss transactions and durable Agent content remain out
of scope.

### Checkpoint 38: reviewed directory creation and model lifecycle tools

The lifecycle contract now includes creation of exactly one ordinary directory
under one already-existing workspace parent. Preview authority contains only the
session, canonical relative path, reviewed parent identity and expiry metadata.
It is memory-only, single-use, bounded with the existing lifecycle capabilities
and applied only after the separate native confirmation
`apply_reviewed_workspace_directory_create`.

The native create primitive never replaces an existing path. The application
reopens the result without following links or reparse points, compares the open
handle and path identity repeatedly, and on POSIX also flushes the pinned parent
before claiming success. Windows mutation parents deny delete sharing while the
operation is active, preventing an external parent rename from redirecting the
absolute-path publication. If publication may have occurred but exact
verification fails, the session is hard-locked and reports `unverified`.
It deliberately does not attempt a path-based cleanup: deleting a name after a
race could remove somebody else's replacement directory. The approved creation
may therefore require owner inspection, but no deletion authority is invented.

The model tool schema now exposes `create_directory` and `move_file` whenever
workspace writes are allowed. Both tools use the same lifecycle preview/apply
service as the manual workbench, wait for exact human approval, revoke denied or
cancelled capability, and never emulate lifecycle changes with shell commands.
File moves continue to update the reviewed old-path/new-path change set. The
Agent UI labels these actions explicitly and the manual workbench adds a
keyboard-labelled **New folder** review card with the existing native-presence
and draft protections.

This addition does not create missing parents recursively, delete files or
directories, move directories, overwrite destinations, persist lifecycle
authority or make empty directories representable in Git history.

### Checkpoint 39: reviewed no-overwrite directory moves

The lifecycle contract now moves one ordinary directory entry to one absent
workspace-relative destination whose parent already exists. Preview authority
binds the canonical source/target paths, the exact source identity and both
parent identities. It is memory-only, metadata-only, session-bound, single-use,
bounded with the existing lifecycle previews and applied only after the distinct
native confirmation `apply_reviewed_workspace_directory_move`. Preview and
result both carry `contents_reviewed: false`: the subtree follows its directory
entry but is never enumerated or admitted as reviewed content.

Root, same/case-only Windows, self-descendant, escaping, link/reparse, missing,
non-directory, missing-parent and existing-target paths fail closed. Apply pins
both parent chains and the source directory, rechecks exact identity and uses a
native no-replace rename. It then verifies the still-open source identity at the
destination. A failed verification rolls back only that exact entry and claims
restoration only after exact path/handle readback. Any unresolved publication or
rollback is `unverified` and hard-locks later lifecycle mutation.

The manual workbench provides the same review/apply flow as the first-class
model `move_directory` tool. Both state that subtree content was not reviewed;
neither grants copy, overwrite, deletion, recursive parent creation or shell
authority. Denied/cancelled model calls discard their preview capability. The
[checkpoint 39 handoff](../checkpoint-39-handoff.md) records source/target race,
rollback, strict-parser, HTTP, component, responsive-browser and broad-suite
evidence. Recoverable deletion and POSIX native acceptance remain separate.

### Checkpoint 40: reviewed recoverable single-file removal

The lifecycle contract now moves one exact reviewed ordinary bounded UTF-8
file to Windows Recycle Bin. Preview authority binds the canonical relative
path, content revision, file and parent identities, byte count, mode and expiry.
It is memory-only, metadata-only, session-bound, single-use and applied only
after the distinct native confirmation
`apply_reviewed_workspace_file_trash`. It does not cover permanent deletion,
directories, recursion or shell emulation.

Apply pins and rechecks the reviewed file and parent, then renames the exact
still-open entry to a private staging name. Windows `IFileOperation` receives
that entry with undo/recycle flags. Success requires the source and staging
names to be absent, exact identity/content/size/mode to remain readable from the
open descriptor and its final path to resolve below the same drive's
`$Recycle.Bin`. A settled native failure rolls back only that exact open entry
and claims rejection only after restored readback. Verification or rollback
uncertainty hard-locks later lifecycle mutation.

The Shell operation runs on a dedicated STA worker with a 15-second caller
deadline. A still-running worker is unverified; the caller deliberately does not
roll back a path while that worker may act late. The manual workbench and model
`trash_file` tool share the same lifecycle service. Review/result contracts
state Windows recovery and `permanent: false`. The UI also discloses that the
Recycle Bin may show the private staging name, so automated restoration to the
original workspace name/path is not promised. The [checkpoint 40
handoff](../checkpoint-40-handoff.md) records native, timeout, rollback, strict
transport, responsive-browser and complete-suite evidence.

### Agent checkpoint 04: opt-in durable projects and chat recovery

Authored Agent navigation is now a dedicated SQLite catalog with projects and
sessions, revision-bound rename/pin/archive/restore/move operations, and an
explicit per-chat retention policy. `metadata_only` keeps navigation metadata
but never claims conversation recovery. `local_history` retains a bounded,
append-only visible event projection and settled receipts; approval identities,
approval decisions, raw tool arguments/results, and reusable mutation authority
are excluded. Restart recovery is revision-bound and always read-only until a
fresh native user-presence revalidation. The [Agent checkpoint 04 handoff](../checkpoint-agent-04-handoff.md)
records persistence, isolation, restart, browser and broad-suite evidence.

### Agent checkpoint 05: rich messages, immutable artifacts and controller v3

Agent message bodies now render bounded GFM Markdown and code blocks without
raw HTML, remote images, executable URLs or `dangerouslySetInnerHTML`. External
links are isolated and code copy remains an explicit local action.

Local-history chats project verified reviewed-write receipts into immutable
`agent-artifact.v1` lineage. Manual capture requires the exact relative path,
digest and byte size plus native user presence. Artifact bytes remain in the
workspace and are reopened through the no-follow boundary on every preview or
download; size and digest must still match. Text is forced to inert
`text/plain`; active document types are download-only; bounded image and PDF
previews require validated signatures. Private content responses use no-store,
no-sniff, sandbox, safe-disposition and single-range contracts. The Agent UI
adds compact artifact cards plus text and image viewers and a local,
non-interactive PDF-to-canvas viewer for live and restart-recovered chats.

`local-agent-orchestration.v8` documents the finite controller lifecycle and
complete Agent/file-workflow route surface for
Codex, Claude Code and other local HTTP clients, including non-idempotent
message admission, monotonic event cursors, the exact terminal condition and
native-only approval behavior. It also enumerates artifact discovery/content
routes. There is still no raw-transcript MCP tool or remote listener. See the
[local Agent controller API](../agent-controller-api.md).

### Agent checkpoint 06: private capability-gated message attachments

`agent-attachment.v1` adds a session-bound private attachment vault for PNG,
JPEG and PCM WAV. Admission verifies the byte structure, media metadata, exact
served model capability, size/count budgets and a sanitized display-only name;
it records a digest and never trusts a suffix. Staged authority expires after
one hour and is rechecked for exact session, model, capability probe, digest,
size and single use immediately before inference.

User events retain payload-free attachment identity. Metadata-only chats delete
sent payloads after the user event is published. Save-locally chats retain exact
private bytes for restart recovery and delete them with the session. Raw bytes
never enter the event journal. Private preview responses are no-store,
no-sniff, same-origin and size/disposition checked. Limits are four attachments
and 16 MiB per message, 16 staged and 64 MiB per session, 8 MiB per image,
12 MiB per WAV, 8,192 pixels per dimension, 33,554,432 pixels and five minutes
of admitted audio.

The composer gates image, WAV and microphone actions from the exact runtime
capability state, preserves admitted drafts on send failure, removes them only
after successful submission, recovers staged identities after remount and
allows attachment-only messages. The recorder is local mono PCM16 WAV with a
two-minute limit and explicit track/context cleanup. PNG/JPEG checks are strict
format-structure validation rather than a claim of full decoder execution;
llama.cpp audio is experimental and media context tokens remain unknown when
the runtime does not report them. See the [Agent-06 handoff](../checkpoint-agent-06-handoff.md).

### Agent checkpoint 08: complete controller contract and bounded client

`local-agent-orchestration.v8` is now exact OpenAPI parity for all 55 Agent
routes plus the five controller-relevant runtime routes. Its strict model fixes
the ten native-only operations, rejects incomplete or path-unsafe manifests,
and distinguishes JSON, binary, SSE and no-content responses.

The v8 addition is a project-and-chat-bound inline attachment-staging route.
Its strict request accepts caller-owned base64 plus exact size/digest declarations
but no path or URL. The dedicated MCP tool requires explicit mutation authority,
returns sanitized metadata only, and cannot read stored attachment bytes. The
native composer refreshes and labels `external_agent` staging provenance before
the media is referenced by a turn.

The provider-neutral `prompt-enhancer agent-controller` client gives an
external Codex, Claude Code or other controller a single-request stdio bridge
without disclosing the local token. `discover` verifies the content-free
manifest; `invoke` resolves one declared JSON operation and refuses native,
binary, SSE, and raw runtime-mutation modes; `runtime` revision-safely ensures
one exact registered model is ready or stopped, requires an additional explicit
model-lifecycle acknowledgement, performs one mutation at most, and reconciles
an ambiguous response with one status read instead of retrying; `open` creates
or selects one durable project and opens one schema-validated live chat without
retrying ambiguous creation; `turn`
implements one-message idle admission, monotonic
event polling, ambiguity reconciliation without resubmission, pending-approval
handoff, one bounded deadline Stop, and a finite terminal drain. `wait` resumes
from the returned cursor after native review without sending or stopping; a
cleanup quarantine returns `cleanup_unconfirmed` and can never be called
settled. The direct SSE relay uses the same truth rule: `closing` and `stopping`
remain nonterminal, while settlement and cleanup quarantine each produce an
explicit final JSON page before EOF. Stream closure alone is not a successful
turn receipt. The transport
accepts one exact loopback HTTP origin, disables environment proxies and
redirects, bounds JSON bodies, and redacts every diagnostic. It owns and spawns
no server, model, terminal, or external-agent process. Only the explicit
`runtime` action may ask the already-running application owner to change its
one model lifecycle.

Sensitive stdio output requires both an explicit command acknowledgement and a
per-request task-authorization/redaction receipt. The Agent window exposes the
token-free setup and discovery commands under **Connections & controller
API**. See the [controller API guide](../agent-controller-api.md) and
[Agent-08b handoff](../checkpoint-agent-08b-handoff.md).

### Agent checkpoint 08o: standard external-agent MCP bridge

The controller is now also available as a dedicated provider-neutral MCP stdio
server. It is separate from the read-only analytics MCP so their privacy claims
cannot be confused. `agent_discover`, `agent_invoke`, `agent_open`,
`agent_catalog`, `agent_history`, `agent_artifacts`, `agent_workspace`, `agent_resume`, `agent_fork`, `agent_export`, `agent_close`,
`agent_context`, `agent_turn`, `agent_stop`, and `agent_wait` mirror the
already-validated controller client.
`agent_catalog` gives coding agents a strict project/chat metadata surface
without destructive deletion authority; `agent_history` exposes only bounded
retained visible events; `agent_artifacts` exposes immutable lineage metadata
without bytes; and `agent_workspace` gives coding agents a strict read-only
inventory/tree/file/change/diff path without asking them to synthesize a
generic route call. These tools cannot apply, trash, approve, or control a
model.
`agent_context` combines the strict local-runtime, compatibility, live-session,
and staged-attachment contracts into a sanitized sequential snapshot. It
returns the runtime's exact last-measured request evidence and verified media
support while explicitly marking that context as global, not selected-chat
evidence, and omitting local paths, standing instructions, process IDs,
attachment digests and bytes. The tool does not count tokens or mutate
runtime/chat state.
`agent_runtime` is not even advertised unless the owner deliberately enables
model lifecycle at server setup, and each runtime call still requires its own
literal authorization.

Sensitive tools require a strict task-authorization/redaction receipt. Generic
POST and PATCH calls require mutation authorization. Generic DELETE is refused
through MCP, and the dedicated catalog tool has no delete action; permanent durable
deletion remains in the Agent UI. Native-only operations, binary/SSE responses,
and raw runtime mutation stay refused. Errors contain only a closed
code, optional HTTP status, and retryability. Generated Codex and Claude Code
configuration contains no token or absolute local path and edits no provider
file. The stdio bridge owns no application, agent, model, shell, terminal, or
listener lifecycle; it can only call the already-running authenticated
loopback service. See the [Agent-08o handoff](../checkpoint-agent-08o-handoff.md).

### Agent checkpoint 09c: evidence-bound external turn Stop

The MCP v8 surface makes turn cancellation a dedicated operation rather than
generic route composition. `agent_stop` requires literal mutation authority,
one exact live-chat identity and an event cursor. It sends Stop at most once,
never duplicates an already-stopping request, and reconciles ambiguous delivery
only through bounded event reads. A successful result requires complete
terminal cleanup evidence; uncertainty and cleanup quarantine remain explicit.
Generic `stop_turn` invocation is refused so callers cannot bypass this
contract. See the [Agent-09c handoff](../checkpoint-agent-09c-handoff.md).

### Agent checkpoint 09d: revision-bound retained-chat resume

The MCP v9 surface adds a dedicated `agent_resume` operation for an exact
durable project/chat pair. The caller must present the current catalog and
history revisions plus literal mutation authority. Stale, archived,
metadata-only, unavailable, and cross-project records fail before mutation;
an already-live chat performs no mutation. A real resume is attempted at most
once, and ambiguous delivery receives one read-only live-chat reconciliation
instead of a second POST. Recovered sessions cannot inherit protected
authority: writes, commands, and web remain disabled and
`authority_revalidated` remains false. Generic `resume_retained_session`
invocation is refused so callers cannot bypass this contract. See the
[Agent-09d handoff](../checkpoint-agent-09d-handoff.md).

### Agent checkpoint 09e: idempotency-bound external chat fork

The MCP v10 surface adds a dedicated `agent_fork` operation for one exact
retained-history prefix. Literal mutation authority, source project/chat,
catalog/history revisions, and a caller-owned 32-hex request ID are mandatory.
Optional destination, branch event, and title fields are bound to that key. A
trusted 4xx is not retried; an ambiguous first result may receive one
byte-identical retry with the same key, never a generated replacement. The
strict result validates complete source/destination lineage and requires all
approval, mutation-authority, live-tool-state, staged-attachment, and artifact
copy claims to remain false. Generic `fork_retained_session` invocation is
refused. See the [Agent-09e handoff](../checkpoint-agent-09e-handoff.md).

### Agent checkpoint 09f: exact-revision path-free external export

The MCP v11 surface adds a dedicated `agent_export` operation for one complete
retained history. Its exact project/chat identity, catalog revision, history
revision, and caller-selected event ceiling are mandatory. The underlying HTTP
export accepts the two optional revisions for native compatibility and rejects
stale controller requests before returning content. The controller verifies
complete contiguous coverage, turn counts, metadata identity, response and
event limits, then returns a projection without the workspace path, attachment
bytes, live approvals, raw tool payloads/previews, or mutation authority.
Generic `export_retained_history` invocation is refused. See the
[Agent-09f handoff](../checkpoint-agent-09f-handoff.md).

### Agent checkpoint 09g: exact-revision live-chat close

The MCP v12 surface adds a dedicated `agent_close` operation for one exact idle
live chat. Literal mutation authority plus the project/chat, catalog revision,
and history revision are mandatory. The HTTP close route keeps its parameter-
free native compatibility path, while controller calls atomically recheck all
four values and reject active turns, pending approvals, stale state, cross-
project identity, and cleanup uncertainty before closing. The DELETE is sent
at most once. Ambiguous delivery receives one read-only live/catalog
reconciliation, never a repeated mutation. Settled results prove only the live
runtime was removed; the durable record and retained history remain and no
protected authority is granted. Generic `close_live_session` invocation stays
refused. See the [Agent-09g handoff](../checkpoint-agent-09g-handoff.md).

### Agent checkpoint 09h: controller onboarding parity

The owned native setup card is part of the external-controller contract, not
decorative documentation. It now presents the MCP v12 sixteen-core-tool set in
a collapsed keyboard-reachable grouping, describes the actual open, turn,
stop/wait, and live-only close lifecycle, and removes the obsolete claim that
retained history cannot be exported. The advanced controller CLI section now
includes copyable invoke, turn, and close commands and states the at-most-once
close plus durable-history retention rules. Desktop and 320 px browser evidence
must verify the disclosure and commands whenever this contract changes. See the
[Agent-09h handoff](../checkpoint-agent-09h-handoff.md).

### Agent checkpoint 09i: local image and PDF viewer hardening

Artifact content is accepted by the UI only when the response content type,
reported byte count, Blob byte count, and bounded generated filename agree with
the exact selected immutable version. A mismatch fails closed before any
object URL, decode, render, or download action. Image previews expose loading,
ready, decode-error, fit, and bounded zoom states and revoke their local object
URL on every viewer/version/scope teardown.

PDF preview no longer delegates to a browser iframe. A lazy-loaded, pinned
local PDF.js worker parses the already verified in-memory Blob and renders one
page at a time to a canvas. XFA, annotations, range/stream/auto-fetch,
worker-side fetch, and WASM are disabled; links, forms, scripts, audio, and
annotations are never interactive. Parser and render failures remain explicit
and download is a separate user action. See the
[Agent-09i handoff](../checkpoint-agent-09i-handoff.md).

### Agent checkpoint 09j: inert Office projections and artifact navigation

Modern office artifacts are never rendered by a browser plugin or external
application inside the Agent viewer. The service validates the exact immutable
artifact version and admitted ZIP container, then derives a bounded text/table
projection from DOCX, PPTX, XLSX, or ODT XML using the standard library. Archive
traversal, link-like members, encryption, unsupported compression, duplicate
names, excessive expansion, active XML declarations, malformed selected XML,
and stale digest identity fail closed. Macros, media, comments, notes, embedded
objects, and external relationships are omitted and reported; relationship
targets are never resolved. Legacy DOC/PPT/XLS remain download-only.

`Reveal in files` is navigation, not execution: it may focus a non-editable
entry in the bounded session-owned workspace tree without fetching file bytes
or discarding an editor draft. `Review changes` resolves only an exact
session/path entry in the retained reviewed-path change set and opens its
bounded net diff. Missing, cross-session, disabled, or unavailable diff
requests stay explicit and cannot fall through to another path. See the
[Agent-09j handoff](../checkpoint-agent-09j-handoff.md).

### Agent checkpoint 08q: direct process-free MCP authority

The recommended external-controller transport is now stateless Streamable HTTP
on the app-owned loopback listener at `/mcp/agent`. It does not start a stdio
bridge, console, shell, model, Agent, worker, or second listener. The same
provider-neutral tool surface and per-call egress/mutation rules apply.

Each client connection has a random 128-bit identity, explicit client label,
expiry, lifecycle scope, credential revision, and durable revoked state. Its
bearer is HMAC-derived from the private app authority and is never stored. A
rotation increments the credential revision and invalidates the old bearer;
revocation and expiry fail closed across restart. The broad application API
token, browser cookie, and CSRF value cannot authenticate this endpoint.

Connection creation, rotation, and revocation require the existing exact-body,
one-shot native user-presence capability. The browser receives a private
no-store credential bundle only for create/rotate and never renders the secret;
explicit copy controls can place a Codex config, Claude config, or bearer on the
clipboard, after which the in-memory bundle can be cleared. The list and revoke
responses contain metadata only. The stdio MCP server remains an advanced
fallback for clients without Streamable HTTP support. See the
[Agent-08q handoff](../checkpoint-agent-08q-handoff.md).

### Agent checkpoint 08v: strict durable catalog MCP

The MCP v3 surface adds `agent_catalog`, a discriminated project/chat metadata
tool. It maps seven finite actions to the existing durable catalog and validates
every response through the strict v2 catalog records. Project/chat identities,
project-scoped lists, requested field changes, archive state, and exact
revision increments are checked again before any result reaches the connected
model context. Incoherent fields and missing literal mutation authorization
fail before controller I/O.

The tool deliberately omits permanent deletion. Generic MCP invocation now
refuses every DELETE operation regardless of caller-provided flags, while the
Agent UI keeps its explicit delete flows. This prevents a connected agent from
granting itself destructive authority over durable chats or retained local
history. See the [Agent-08v handoff](../checkpoint-agent-08v-handoff.md).

### Agent checkpoint 08w: retained history and artifact MCP reads

The MCP v4 surface adds two read-only tools. `agent_history` pages through one
exact retained local conversation while rejecting live state, approvals, raw
tool arguments/results, preview payloads, cross-session responses, and
incoherent cursors. `agent_artifacts` lists or gets exact project/chat-bound
immutable artifact lineage, but has no content, capture, export, or delete
action.

Artifact bytes remain behind the binary controller endpoint and native viewer.
Connected agents can use the already-bounded `agent_workspace` tool only when
an artifact supplies an ordinary UTF-8 relative path. This preserves useful
document awareness without turning MCP into a general binary exfiltration or
mutation channel. See the
[Agent-08w handoff](../checkpoint-agent-08w-handoff.md).

### Agent checkpoint 08x: sanitized runtime/chat/media context MCP

The MCP v5 surface adds `agent_context` with strict `runtime` and `chat`
actions. It composes existing controller reads into a path-free, byte-free
sequential snapshot containing installed-model/runtime-adapter compatibility,
requested and served placement, verified modality support, and the runtime's
exact last-measured request-context receipt. A chat-scoped call also validates
the exact project/live-session identity and returns bounded model settings,
permission/recovery state, and staged attachment metadata.

The projection deliberately excludes workspace paths, standing instructions,
approval identifiers, process IDs, artifact identities, attachment digests and
attachment bytes. It labels the snapshot non-atomic and the context receipt as
global runtime evidence; it does not claim that evidence belongs to the
selected chat. It never counts tokens, stages media, starts/switches/stops a
model, or mutates a chat. See the
[Agent-08x handoff](../checkpoint-agent-08x-handoff.md).

### Agent checkpoint 08f: durable authority-free chat branching

Retained Agent chats can now be forked at the latest settled turn, at one exact
completed-turn sequence, or at an explicit empty boundary. The request is
catalog- and history-revision bound and idempotent by a caller-supplied request
identity. A durable lineage record survives parent deletion while retaining no
source foreign-key authority.

The atomic copy includes only the selected visible retained journal prefix and
already-attached private media with remapped identities. Pending approvals,
mutation authority, pending tool state, staged media, artifact lineage, active
processes, and live-session state never cross the branch. Corrupt event/media
links and byte-digest mismatches fail closed. The controller v6 manifest and
typed browser transport expose the same operation. See the
[Agent-08f handoff](../checkpoint-agent-08f-handoff.md).

### Agent checkpoint 08g: one-owner separate native chat window

The native Agent launcher now coordinates one optional chat child inside its
existing WebView process and GUI loop. One primary owner still owns the
loopback server, confirmation manager, runtime coordinator, command lifecycle,
and shutdown. The child API is deliberately non-spawning, and its exact receipt
asserts that it started no listener, worker, process, or runtime owner.

An opaque 128-bit key identifies the child window only. Session selection uses
a strict same-origin, memory-only rendezvous channel; session identifiers never
cross the Python bridge or appear in the child URL. Reopening focuses the one
child and selects the requested live or durable chat. The child includes the
project/chat rail, shared model/context control, conversation, and on-demand
Files & review surface. Browser fallback reuses one fixed-name popup with the
same opaque route.

Process-free tests cover concurrent opens, duplicate focus, close/reopen,
primary shutdown, route and receipt rejection, one server, and one GUI start.
Synthetic browser tests cover main and dedicated shells at 360 px and 1440 px.
No native application or model was launched for this implementation receipt;
the guarded native owner check remains required. See the
[Agent-08g handoff](../checkpoint-agent-08g-handoff.md).

### Agent checkpoint 09k: visible external-orchestrator handoff

The direct Agent MCP backend remains the provider-neutral controller boundary;
this checkpoint makes that boundary usable without reconstructing it from
documentation. The native connection card visibly names `POST /mcp/agent`,
shows and copies the exact current loopback URL only after one scoped credential
is created, and provides a credential-free starter for the discover, open,
context, turn, native-review wait, workspace/artifact inspection, and live-close
sequence.

The existing durable `last_used_at` value is presented as either never used or
the last authenticated MCP request after an explicit refresh. It is deliberately
not a task-success receipt: only turn events, reviewed diffs, immutable
artifacts, and cleanup evidence can establish those downstream outcomes. No
bearer, provider configuration, workspace path, project identity, prompt, or
model choice enters the starter or the persisted connection list. See the
[Agent-09k handoff](../checkpoint-agent-09k-handoff.md).

### Agent checkpoint 09l: content-free MCP tool activity

The direct-connection catalog now retains a bounded receipt for the last
validated MCP tool call: exact allowlisted tool name (or the fixed
`unknown_tool` label), `succeeded`/`failed` protocol outcome, and server time.
The three fields are all-or-none, survive restart, and are shown only after an
explicit connection-status refresh. Existing or migrated records without a
tool receipt remain unknown rather than becoming zero or failure.

This receipt records no argument, result, prompt, response, workspace path,
project/chat identity, attachment, token, or exception. It proves only that the
named call settled at the MCP boundary. Domain receipts still exclusively
establish turn, write, artifact, approval, runtime, and cleanup outcomes.
Receipt persistence is observational: if it is unavailable, the already-settled
MCP response is returned unchanged so a client is not invited to repeat a
possibly mutating call. See the
[Agent-09l handoff](../checkpoint-agent-09l-handoff.md).

### Agent checkpoint 09m: externally authored native-reviewed file proposals

The controller v9 and MCP v13 surfaces add one dedicated `agent_propose`
operation for exact caller-authored UTF-8 file content. A create is bound to an
absent target; an edit is bound to the exact current SHA-256 revision. The
controller submits once and receives an idempotent, content-free lifecycle
receipt. Generic invocation cannot reach this operation.

Acceptance never changes the workspace. The existing native Agent approval
card displays the external-controller identity and exact diff; only a native
decision may publish it. Denial, Stop, timeout, stale revision, changed replay,
and failed verification all fail closed. Proposal content, paths, approvals,
and lifecycle events stay in live memory and never enter retained conversation
history, so restart recovery and exact history export remain contiguous. See
the [Agent-09m handoff](../checkpoint-agent-09m-handoff.md).

### Agent checkpoint 09p: externally orchestrated atomic change sets

The controller v10 and MCP v14 surfaces add the dedicated
`agent_propose_transaction` operation for two to eight caller-authored edits
to existing UTF-8 files. Every member is bound to its exact source SHA-256 and
line-ending policy. Generic invocation cannot reach the endpoint, and the
controller receives no apply or approval route.

Admission creates one live, non-durable combined diff and one native approval.
After a decision, the application rebuilds the short-lived transaction
capability from the same transient draft and requires the new review to match
the approved review exactly. It then uses the existing preflighted,
rollback-capable transaction lane. A later-file failure restores earlier
publications; uncertainty is reported as unverified rather than committed or
rolled back. Denial, timeout, Stop, stale revisions, changed idempotent replay,
cross-session receipt substitution, and missing/new-file members fail closed. Proposal content,
paths, diffs, and settlement events never enter retained history. The same
post-decision reconstruction also fixes long native-review expiry for
model-generated multi-file write batches. See the
[Agent-09p handoff](../checkpoint-agent-09p-handoff.md).

The native reload for this checkpoint reproduced the historical
`automation_grant_worker` cleanup failure after the scheduler had begun
polling. The provider cancellation signal was correctly raised but then caught
as an ordinary provider error inside `poll_due`, so the scheduler could
continue through later due grants past the desktop cleanup deadline. Runtime
cancellation is now explicit control flow: it propagates immediately, is never
recorded as a provider failure, and lets the owning native process finish its
bounded shutdown without a diagnostic or terminal window.

### Agent checkpoint 09q: mixed create/edit atomic change sets

The workspace transaction contract v2, controller v11, and MCP v15 extend the
same two-to-eight-file review lane to explicit `create` and `edit` members.
Creates are bound to target absence; edits remain bound to an exact source
SHA-256 revision. Both controller-authored proposals and consecutive local-model
`write_file` calls now produce one combined native review with explicit
per-file operation metadata.

Rollback restores an earlier edit only while its exact published identity is
still present. It removes an earlier create only while that exact
same-transaction identity and proposed digest are still present. If another
actor replaces the path—even with identical bytes—the app preserves it and
reports the transaction as unverified. This adds no general delete capability,
does not persist proposal content, and does not give HTTP or MCP clients apply
or approval authority. See the
[Agent-09q handoff](../checkpoint-agent-09q-handoff.md).

### Agent checkpoint 09r: manual mixed-operation staging

The manual Files & review surface now consumes the complete workspace
transaction v2 contract instead of rewriting every staged member as an edit.
The new-file editor can stage an absence-bound creation into the same plan as
revision-bound edits. Staged creations remain transient browser state, can be
reopened and updated before review, and carry explicit operation and
line-ending metadata into the exact combined preview and apply commands.

The UI applies the same case-insensitive path uniqueness rule as the service,
blocks a combined review while either editor contains an unstaged change, and
keeps all drafts after rejection or verified rollback. Rollback copy now names
restored edits and removed creations separately. An unverified result retains
the existing mutation lock. This adds no directory, permanent-delete, or
general removal capability. See the
[Agent-09r handoff](../checkpoint-agent-09r-handoff.md).

### Agent checkpoint 09s: bounded shared workspace search

The existing local-model `search_text` implementation now exposes one
structured `local-agent-workspace-search.v1` result to the manual Files &
review surface, controller v12, and MCP v16. The algorithm remains rooted in
the admitted workspace and uses the same no-follow inspection layer,
root-relative glob grammar, bounded regex engine, UTF-8-only decoding, entry,
depth, per-file, total-byte, match, and deadline limits.

Results contain only canonical relative paths, line numbers, sanitized
single-line previews, and explicit scan/byte/skipped/match evidence. Partial
coverage is never labeled complete. A replaced workspace root is a terminal
conflict, stale UI results are discarded, and MCP request/response validators
reject unsafe paths, globs, fields, cross-session identities, malformed counts,
or non-canonical matches before presenting them. Search is read-only and adds
no file, command, web, model-lifecycle, or approval authority. See the
[Agent-09s handoff](../checkpoint-agent-09s-handoff.md).

### Agent checkpoint 10r: external lifecycle proposals

The controller v14 and MCP v18 surfaces close the reviewed-file parity gap for
external orchestrators. `agent_propose_lifecycle` accepts one directory create,
no-overwrite directory move, exact-revision no-overwrite file move, or
exact-revision file removal to the Windows Recycle Bin. Submission is
idempotent, changes nothing, and creates one transient native approval using
the same lifecycle preview and apply services as the local-model tools and
manual workbench.

The short-lived lifecycle capability is rebuilt after the person's decision
and its public review identity must remain unchanged. File actions stay bound
to the caller-observed SHA-256 revision. Denial, timeout, Stop, changed source,
occupied destination, altered request replay, native failure, and unverified
cleanup fail closed. Tool arguments and paths remain live-only; the durable
history receives no proposal content. The scoped controller still cannot
approve, apply directly, launch a shell, or permanently delete. See the
[Agent-10r handoff](../checkpoint-agent-10r-handoff.md).

### Agent checkpoint 10s: verified external writes become durable artifacts

The controller v15 and MCP v19 contracts refine the external create/edit
retention boundary. Once native review has approved the proposal and the
workspace service has independently verified the resulting file identity, a
**Save locally** chat retains only the bounded terminal write receipt. The
existing artifact projector uses that receipt to create or advance immutable
artifact lineage, so output cards and their safe viewers survive restart just
like native reviewed writes.

Proposal content, diffs, approval identities, pending/denied/failed/unverified
attempts, and metadata-only chats remain live-only. Artifact metadata still
contains no file bytes and the scoped controller gains no preview-capture,
apply, approval, shell, model, or deletion authority. The artifact remains
bound to the reviewed path; continuity across a later lifecycle move is not
claimed by this checkpoint. See the
[Agent-10s handoff](../checkpoint-agent-10s-handoff.md).

### Agent checkpoint 10t: verified file moves preserve artifact identity

The controller v16, MCP v20, and `agent-artifact.v2` contracts define a file
move as a new immutable artifact path version rather than an in-place rewrite
of earlier provenance. After any exact reviewed file move settles, the service
finds a source artifact only if its current digest and byte size match the move
receipt, reopens and rehashes the destination through the bounded no-follow
workspace reader, and atomically advances that artifact's database head under
the same ID with `provenance=reviewed_move`.

Earlier versions keep their original paths. A stale source artifact is not
associated with different bytes. If another artifact already owns the target
path, both lineages remain unchanged and the already-applied filesystem effect
is surfaced as an unverified metadata conflict with partial change-set
coverage; it is never silently merged or overwritten. Proposal content,
approval identity, file bytes, and invented conversation-event provenance are
not stored. The database lineage update is atomic, but it follows the verified
filesystem effect and is not a power-loss-atomic filesystem transaction.
Directory moves and recoverable-trash lineage are not covered. See the
[Agent-10t handoff](../checkpoint-agent-10t-handoff.md).

### MCP Store checkpoint 03: durable plans without execution authority

The Store now persists one exact Registry-reviewed server version and option as
`mcp-managed-server.v1`. The record includes its immutable plan digest, bounded
identity and risk facts, inferred future permissions, declared requirement
state, project bindings, mutation revisions, and explicit non-execution state.
Creation revalidates the exact public review; it does not trust a browser-posted
package identity or endpoint.

All management mutations require local authentication and fresh native user
presence. Request IDs make exact retries idempotent, while changed replays and
stale revisions fail closed. A project binding is durable intent scoped to one
existing Agent project. Even with every inferred permission selected, its
effective state is `inactive_host_unavailable`: no tool, process, network,
filesystem, credential or model authority is activated in this checkpoint.

Secret values cross only the confirmed mutation boundary and are written to an
opaque deterministic Windows Credential Manager target. SQLite, response
models and the UI retain only content-free lifecycle state. Two-phase
store/removal records preserve uncertainty across failures; exact retries can
reconcile an ambiguous prior vault effect without a stale-revision loop. There
is no file-backed fallback when the OS vault is unavailable.

Installation, endpoint connection, host supervision, health/update probing,
tool-schema admission and Agent routing remain absent. The
[MCP Store-03 handoff](../checkpoint-mcp-store-03-handoff.md) records the tests,
owner checklist and next guarded-host gate.

### MCP Store checkpoint 04: compatibility evidence without tool authority

One ready fixed HTTPS remote plan can now be compatibility-checked after fresh
native user presence. The service first reloads the current managed revision,
re-fetches the exact Official Registry record, recomputes the reviewed option
and plan digest, and refuses stale or changed material before network activity.
Configured secrets are read from the OS vault only at connection time and are
never added to the database, response model, log, or model context.

Remote egress is restricted to HTTPS and every DNS answer must be globally
routable. The TCP backend connects only to the pre-resolved addresses while TLS
continues to authenticate the reviewed hostname. Proxies, redirects, cross-
origin follow-ups and transport-controlled authentication are disabled. The
official MCP client negotiates current or legacy protocol, but initialization,
tool pages, cursors, response bytes, time and untrusted JSON Schema are all
bounded. It lists contracts only and never requests a tool result.

The internal stdio transport is also implemented for the post-install boundary.
On Windows, the root enters a kill-on-close Job Object atomically at process
creation with `CREATE_NO_WINDOW`; on POSIX it starts in an owned process group.
Stdout is aggregate-bounded, stderr is drained without retention, and success is
reported only after the root, ordinary descendants and pipes are verified gone.
Prepared local-package plans cannot reach this transport before Store-05 has
installed and verified an exact executable.

Schema-v13 stores only a content-free compatibility receipt: protocol version,
tool count, deterministic schema digest, elapsed time, transport and cleanup
truth. Endpoint path/query, headers, credentials, tool names, schemas and
results are transient and discarded. A compatible receipt is evidence about
one handshake, not trust, persistent health, installation or tool authority.
The [MCP Store-04 handoff](../checkpoint-mcp-store-04-handoff.md) records the
adversarial tests and the still-locked install/update/uninstall/routing gates.

### Workspace checkpoint 01a: truthful terminal action receipts

`local-agent.v9` adds one optional `agent-tool-execution.v1` receipt to a
terminal tool result. New live actions always carry the receipt; retained
legacy events without it remain readable and are labelled as having unavailable
execution details. The receipt is content-free: it stores no argument, output,
path, approval identifier or reusable authority.

Elapsed time comes only from the server monotonic clock and spans the action
request through its terminal result, including native-review wait. An unusable
or backwards clock remains unknown. Approval state distinguishes not required,
not requested, approved, denied, timed out and cancelled before a decision.
Evidence remains separate: read-only observation, verified or unverified
workspace effect, untracked external command/web effect, no effect, or unknown.
Denied, timed-out and pre-decision-cancelled actions cannot claim an effect.

The same receipt boundary covers model-requested tools and scoped controller
write, multi-file and lifecycle proposals. Durable local-history projection
keeps this bounded terminal metadata but still removes raw tool output,
arguments, previews, approval identities and approval event rows. The Agent
timeline renders elapsed, approval and evidence facts on the terminal action
card; it does not infer success from assistant prose.

The checkpoint also closes a Windows two-session race discovered by the full
regression. A receipt-only pre-publication read now participates in the global
reviewed-write serialization boundary, so its intentionally restrictive parent
handle cannot transiently block another reviewed publication. A failed start
re-observes the exact no-follow authority and reports a proven stale revision as
`workspace_revision_changed`; genuinely unobservable failures remain closed as
write failures.

See the [Workspace-01a handoff](../checkpoint-workspace-01a-handoff.md).

### Workspace checkpoint 01b: reviewed-path recovery and artifact handoff

`agent-change-restore.v1` turns the retained first-reviewed baseline into a
short-lived inverse review for one exact live-chat path. A modified file is
revision-bound back to its retained bytes, a missing original file is
recreated only while the destination remains absent, and a file created during
the session is moved to the Windows Recycle Bin rather than permanently
deleted. Preview responses expose only the bounded inverse diff and authority
metadata; the retained baseline itself remains in the session-owned in-memory
tracker.

Apply is single-use and native-confirmed. It rebuilds the restore plan from the
live filesystem, requires the operation and current/restored revisions to match
the preview command, composes the existing edit/create/recoverable-trash
publication lane, and independently reads the resulting path back before
claiming success. A restore-only internal editor seam permits an exact retained
LF/CRLF representation; ordinary manual edit previews still reject a line-
ending change. External drift, expiry, replay, unavailable baseline bytes,
unsafe paths and unverifiable results fail closed.

The reviewed-path card now offers preview/apply recovery beside net-diff and
current-file actions. It can open an already recorded artifact directly, or
route one exact current path into the existing native-confirmed artifact
capture review. Artifact viewer requests are project-, chat-, artifact- and
path-bound. Unsaved workspace drafts block capture rather than being silently
discarded. The controller discovery surface advances to
`local-agent-orchestration.v17`: restore preview is token-authenticated and the
apply route is explicitly one of eleven native-only gates.

Recovery is deliberately not durable undo history. Baseline bytes are bounded
and live-session memory only, command/external effects remain outside reviewed
authority, Recycle Bin recovery is Windows-only, and a successful filesystem
restore can still report partial change-set evidence when an earlier review
chain gap remains. See the
[Workspace-01b handoff](../checkpoint-workspace-01b-handoff.md).

### Workspace checkpoint 01c: structured diff review and recovery discovery

Every file-content review now uses one local `AgentDiffViewer` instead of an
unstructured preformatted block. The same component covers manual edits, new
files, failure-atomic transaction entries, Agent proposals, pending native
write approvals, reviewed net changes and inverse baseline recovery. Standard
unified hunks render old/new line numbers, addition/deletion/context semantics,
derived counts, exact-copy and an explicit long-line wrapping control.

The viewer does not manufacture structure. Raw model previews without hunk
headers are labelled as having unavailable counts. Truncated hunks fall back to
the exact raw review with an explicit warning, and a server count that
contradicts a complete rendered diff remains visible beside the derived count.
Reviews above 2,000 rendered lines also stay complete as bounded
raw text rather than creating thousands of table rows. The transport's 60,000-
character diff bound remains unchanged.

Reviewed-path cards now state whether a recovery review is available and name
the actual likely effect before preview: restore bytes, recreate a missing
baseline, or move a session-created file to the Windows Recycle Bin. Detailed
net-diff and eligible restore reviews can open the exact current file directly.
These are navigation improvements only; they grant no new filesystem authority
and do not bypass native confirmation, preview expiry or revision revalidation.

The rich viewer is keyboard-scrollable, keeps copy and wrapping controls at the
44-pixel target, stacks its toolbar at narrow width, preserves forced-color
borders and bounds both ordinary and compact transaction viewports. See the
[Workspace-01c handoff](../checkpoint-workspace-01c-handoff.md).

### Artifact checkpoint 01a: producing-turn linkage and conservative viewers

Every reviewed artifact with retained source evidence can navigate back to its
exact producing turn. The page first verifies that the recorded turn exists in
the loaded history, expands any bounded transcript batch needed to reveal it,
then opens, scrolls to and focuses the stable turn container. A recorded source
that is no longer present is reported as unavailable rather than redirecting to
another turn.

Version comparison remains metadata-only. It displays the two immutable
versions' paths, recorded sizes, source evidence, provenance and digest
prefixes, and says whether the recorded digests match. Historical artifact
bytes are not copied into application storage and the UI does not claim to
produce a content diff. Selecting a stale historical version does not regain
current-file or download authority.

PDF admission now fails closed before PDF.js. A candidate must have a supported
PDF header, a bounded terminal `%%EOF`, no non-whitespace trailing payload, at
least one terminated indirect object and no conservative `/Encrypt` marker.
Truncated, encrypted and header/trailer-spoofed files are classified as opaque
binary downloads, not rendered documents. The exact bytes remain available only
through the already reviewed explicit download boundary.

The same acceptance pass closed an adjacent runtime-control crash: placement
evidence is optional at the transport boundary, so a missing placement record
now disables Apply with truthful recovery copy instead of dereferencing an
absent object. It also corrected a synthetic E2E artifact fixture so its source
turn and verified write receipt are internally coherent. See the
[Artifact-01a handoff](../checkpoint-artifact-01a-handoff.md).

### Artifact checkpoint 01b: durable, recoverable record lifecycle

Artifact bytes, relative paths and version lineage remain immutable and bound to
one exact project and chat. The `agent-artifact.v3` contract adds a separate
display label, lifecycle state, monotonic revision and coherent lifecycle
timestamps. Rename changes only the display label. Archive and restore move a
record between ordinary views without touching its workspace file or historical
versions.

Removal is deliberately a recoverable metadata transition, not file deletion.
Only an archived record can move to **Removed**, and that action requires native
user-presence confirmation. A removed record remains listed in its own view but
cannot serve details, previews or bytes, accept a new discovered version, or be
silently resurrected by later reviewed-write synchronization. Explicit recovery
returns it to **Archived**; a separate restore returns it to **Active**. Every
mutation supplies the current revision, so stale, replayed, cross-project and
cross-chat commands fail closed.

Catalog schema v21 persists the lifecycle and its indexes and migrates older
lineage without rewriting artifact content. Custom display labels survive later
versions and restart. Updated timestamps never move backwards, including when
older source evidence is projected after a newer lifecycle operation.

The Agent artifact pane exposes keyboard-reachable **Active**, **Archived** and
**Removed** tabs with truthful counts and a focused management dialog. Removed
records have no preview action. Missing, malformed or changed current files are
not treated as their recorded version; the UI routes an exact current path into
the existing reviewed capture workflow. At narrow width the dialog and controls
remain within the viewport with 44-pixel targets and forced-colors boundaries.
See the [Artifact-01b handoff](../checkpoint-artifact-01b-handoff.md).

### Existing product consequences

- Verified on the owner's machine: the 27B unrestricted model listed the
  workspace, read two files, proposed a diff (approved), added a test
  (approved), ran `pytest` (approved, 3 passed) and summarised - about 17 s
  end to end.
- The editor opens bounded strict UTF-8 text files, preserves LF/CRLF style,
  caps files and diffs, and now supports separately reviewed new-file creation
  plus no-overwrite file rename/move and one reviewed directory under an
  existing parent. It can also move one ordinary directory to an absent path
  under an existing parent without enumerating its subtree, and move one exact
  reviewed file recoverably to Windows Recycle Bin. It does not create parents
  recursively, permanently delete files, remove directories, or overwrite
  destinations.
  The reviewed-path change set can aggregate
  several Agent/manual publications, and the discovery card supplies bounded
  selected-folder/Git metadata. The same Files & review card and scoped MCP
  expose bounded literal/regex search over admitted UTF-8 content with explicit
  complete/partial evidence. The transaction slice adds rollback-capable,
  failure-atomic publication for two to eight absence-bound creates or
  revision-bound edits under a stable workspace. The manual editor, local
  model, and scoped external-controller paths all use this mixed-operation
  boundary; it is not power-loss atomic.
  Rich syntax editing, unrestricted
  indexing, lifecycle operations inside multi-file transactions, unbounded
  transcript retention, shell sessions that survive between calls, and general
  web search remain outside this ADR's implemented scope.
- The agent is only as good as the model and the prompts; the app keeps the
  person in the loop at every change, which is the property that matters.
