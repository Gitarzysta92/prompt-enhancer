# Whole-application verification ledger

Objective: finish the application work and verify it thoroughly enough to report the actual remaining uncertainty, rather than treating a passing test count as proof of universal correctness.

Status: checkpoint 40's reviewed recoverable single-file removal is implemented across the manual workspace, model tool loop and private HTTP contract within its documented Windows/stable-workspace scope. It grants neither permanent deletion nor directory removal; exact reviewed bytes are verified in Windows Recycle Bin and the UI discloses that safe rollback staging may change the recovery entry's displayed name. The frozen current-tree gates pass **4,308 backend cases across all 279 test files** with nine expected Windows symlink-capability skips, **1,882 frontend tests across 135 files**, **105 synthetic browser workflows** and **35 intercepted loopback/HTTP workflows**. Production build, API/OpenAPI parity, frozen dependency lock, TypeScript and Python compilation, whitespace checks, the unchanged privacy scanner and 19 focused privacy tests pass. The protected launcher serves the final build on loopback in offline/metadata mode. No model was loaded and NVIDIA reported zero compute contexts. The whole product remains open against the requirements and owner decisions below; the [Agent chat experience plan](agent-chat-experience-plan-2026-08-27.md) records the proposed chat-first trajectory without claiming it is implemented. See the [checkpoint 40 handoff](checkpoint-40-handoff.md) for exact receipts and limits; older checkpoint totals are historical evidence, not additional tests to sum.

Continuation on the same date: independent Agent closing/recovery work proceeded despite the cleanup restriction. The **Agent closing recovery** section of the handoff records the newer contract, HTTP deletion and stale-window repairs. Full-suite results below are the earlier integrated baseline unless explicitly updated there; they are not a claim of universal correctness or a newly repeated full backend run.

Agent-08s continuation on 2026-08-28: the durable Agent project/chat hierarchy
now passes a fictional native create, rename, pin, search, archive, restore,
retained close, restart and resume lifecycle without loading a model. Repairs
include model-free durable creation, chat-title project discovery, viewport-safe
action sheets, content-free cross-window title synchronization, clearing a stale
closing marker and preventing catalog invalidation from echoing into its own
page and replaying stale session lists. The final isolated gates are 121/121
focused frontend tests, 94/94 backend lifecycle/boundary tests, 66/66 responsive
Chromium workflows and a 536-module production build. `git diff --check` passes;
the unchanged privacy scanner reports only the pre-existing untracked Agent-02
binary screenshot. One application listener and one Agent window remain, with
zero visible terminal windows and zero model processes; Playwright's exact
temporary 4173 listener was removed after the run. Protected file-write
approval, real-model/GPU lifecycle and a real provider MCP handshake remain
owner acceptance rather than automated claims. See
[checkpoint-agent-08s-handoff.md](checkpoint-agent-08s-handoff.md).

Agent-08r continuation on 2026-08-28: the Agent shell now leaves projects and
chats persistent on the left while placing New chat setup and Connections,
Owner checks and Team folders in separate keyboard-accessible drawers. Live
browser validation repaired overlapping settings content, drawer viewport
insets, a sub-44 px trigger, stale setup overlays after chat selection and
unsafe cleanup-state affordance coupling. The final isolated component gate is
115/115 and the responsive Chromium gate is 66/66 at 360 px and 1440 px. A
deliberately oversubscribed parallel run first produced one Stop-test timeout
and one cascading failure; the clean isolated rerun is recorded without hiding
that event. The 536-module production build, live zero-console-error check and
native refresh pass. One listener and Agent window remain, with zero targetable
visible terminal windows and zero model processes. No model or private provider
data was used. `git diff --check` passes; the unchanged privacy scanner reports
only the pre-existing untracked Agent-02 binary screenshot. See
[checkpoint-agent-08r-handoff.md](checkpoint-agent-08r-handoff.md).

Agent-08q continuation on 2026-08-28: Prompt Enhancer now serves its Agent MCP
surface directly from the owned loopback listener at `/mcp/agent`, using
revocable, rotatable, optionally expiring scoped credentials. The Agent UI
creates one-time Codex and Claude HTTP setup snippets without starting a bridge
or terminal process; stdio remains an explicit advanced fallback. Credential
administration is isolated at `/v1/integrations/agent-mcp/connections`, outside
the controller manifest, and requires browser authentication plus native user
presence for mutations. The final gates include 216 backend Agent tests, 2,061
frontend tests across 155 files followed by 177 focused tests after the final
route isolation, 66 responsive Playwright workflows, a 536-module production
build, API parity, compilation, lock and whitespace checks. The unchanged
privacy scan still reports only the pre-existing untracked binary screenshot.
No provider configuration was read or changed and no model was loaded. Real
provider handshake, native owner acceptance and model/GPU acceptance remain
open. The closing process audit additionally repaired Windows Codex discovery
to prefer native `codex.exe` over the `codex.cmd`/`cmd.exe` path; 87 focused
transport, schema, distribution and desktop-lifecycle tests passed. A clean
native restart left one responsive Agent window, one listener and zero visible
terminal windows, while a duplicate launch focused the existing instance and
exited. See [checkpoint-agent-08q-handoff.md](checkpoint-agent-08q-handoff.md).

Agent-08p continuation on 2026-08-28: the standard Agent MCP bridge now has a
full synthetic composition test across real stdio JSON-RPC, an authenticated
ephemeral loopback TCP listener, the production controller, and the durable
project/chat catalog. A second MCP process observes the retained fictional
project while the shared runtime remains idle. A disposable installed-console
probe validates generated Codex and Claude configuration without reading or
changing either provider's files. Current focused gates are 199 backend Agent
tests, 240 Agent component tests, 214 Agent API-contract tests, 12 controller
component/layout tests, two responsive Chromium flows, and a 533-module
production build. Python compilation and whitespace checks pass; zero
`llama-server` processes and no listener on 8765/8766 remain. The privacy scan
still fails only on the known pre-existing untracked binary screenshot. This
evidence does not claim a real provider-model handshake or native/model owner
acceptance; see [checkpoint-agent-08p-handoff.md](checkpoint-agent-08p-handoff.md).

Checkpoint 21 continuation checks: 1,536 frontend tests across 122 files, 61 focused backend tests, four in-app browser recovery flows, production build, API consistency and explicit browser-fixture TypeScript checks passed. The synthetic server/tab were closed, zero model-runtime processes remained, and the unchanged scanner still rejected the one old synthetic database. This does not complete the whole product or close its existing authorization/integration gaps.

Checkpoint 22 checks: 1,552 frontend tests across 122 files, including 72 Agent tests, and four synthetic in-app browser model-control workflows passed. Production build, API consistency, explicit browser TypeScript and whitespace checks passed. Sixteen component regressions were added; twelve reproduced failures before the repair. No backend source changed or backend suite was rerun. No GPU model was loaded; the owned test listener/tab were closed and zero model-runtime processes were observed. The unchanged privacy scanner still rejects the one old synthetic database. These results are not added to historical test totals or treated as whole-product completion.

Checkpoint 23 checks (prior evidence): 1,589 frontend tests across 123 files, 126 focused backend tests, 77 synthetic browser workflows and 16 intercepted HTTP browser cases passed. Six in-app browser completion/recovery flows were separately inspected. Build, API, strict browser TypeScript, Python compilation and whitespace checks passed; owned test listeners/tab were closed and zero model-runtime processes were observed. No real model was loaded. The unchanged scanner still rejected the single old synthetic database. The full backend baseline was not repeated and remains historical evidence; whole-product completion was not established.

Checkpoint 24 checks (prior evidence): 1,598 frontend tests across 123 files, 342 focused backend tests across 14 files, 79 synthetic browser workflows and 18 intercepted HTTP browser cases passed. Two in-app browser judgment/retry/explanation flows were separately inspected. Production build, generated API consistency, strict browser TypeScript, Python compilation and whitespace checks passed. One initial unrelated frontend timeout passed in its unchanged focused file and in the final full-suite rerun. The owned browser tab was closed, viewport restored, owned HTTP test listener exited and zero model-runtime processes were observed; no GPU model was loaded. The unchanged scanner still reports only the one old synthetic database. No normal owner-app restart or new full-backend baseline is claimed.

## Checkpoint 39: reviewed no-overwrite directory moves

- The Agent workspace can move exactly one ordinary directory entry to an
  absent workspace-relative destination under an already-existing parent.
  Neither preview nor result enumerates the subtree or calls it reviewed;
  `contents_reviewed` is always false.
- Directory-move capability is memory-only, metadata-only, session-bound,
  single-use, bounded and valid for at most 120 seconds. The exact source,
  destination, source identity and both parent identities are bound to a
  distinct native-presence confirmation.
- Root, same/case-only Windows, self-descendant, escaping, link/reparse,
  missing/non-directory source, missing-parent and existing-target paths fail
  closed. Apply pins both parent chains and the source, uses native no-replace
  rename, verifies the exact entry at the destination and rolls back only that
  exact entry. Unresolved publication or rollback hard-locks later lifecycle
  mutation.
- Model-enabled sessions expose first-class `move_directory` and prefer it over
  shell emulation. Denied/cancelled previews leave no retained authority. The
  manual workbench exposes the same **Move folder** review, native-unavailable
  truth, draft protection and uncertainty lock.
- New regressions cover source replacement before apply, target collision,
  Windows source/parent swap, exact rollback, unresolved rollback, invalid
  topology, strict response/request binding and fixed safe recovery reasons.
- Frozen evidence is **4,299 backend passes across 279 files** with nine
  expected platform skips, **1,872 frontend passes across 135 files**, **105
  synthetic browser workflows** and **35 intercepted loopback/HTTP workflows**.
  Build, API parity, compilation, privacy and whitespace gates pass; the
  protected loopback app serves the new Agent bundle.

This closes one bounded directory-move slice. It does not add deletion,
trash/recycle-bin integration, overwrite, recursive parent creation, subtree
content review, power-loss atomicity, durable Agent content, POSIX native
acceptance on this Windows host or owner visual/native-click acceptance.

## Checkpoint 38: reviewed workspace topology

- The Agent workspace can create exactly one ordinary directory below an
  already-existing reviewed parent. Missing parents are not created
  recursively; existing paths are never replaced; deletion and directory moves
  remain outside this authority.
- Directory preview/apply authority is memory-only, metadata-only,
  session-bound, single-use, bounded and expires at or before 120 seconds. A
  distinct native-presence confirmation binds the canonical reviewed path.
- Apply reopens and identity-checks the reviewed parent, uses native
  create-if-absent behavior, then compares opened-directory and path identity.
  Any uncertain publication hard-locks later lifecycle mutations; the app does
  not path-delete a possibly externally replaced directory.
- A reproduced Windows parent-swap race was closed by denying delete sharing on
  the pinned final mutation parent. The same pin now protects reviewed file
  creation, directory creation and no-overwrite file moves.
- Model-enabled Agent sessions expose `create_directory` and `move_file` as
  reviewed first-class tools and prefer them over shell emulation. Denied or
  cancelled calls leave no retained lifecycle capability.
- The manual workbench adds an exact **New folder** review/apply flow with
  missing-parent guidance, native-unavailable truth, uncertainty locking and
  narrow-window coverage. Agent activity names directory creation and file
  moves directly.
- Frozen broad evidence is **4,284 backend passes across 279 files** with nine
  expected Windows symlink-capability skips, **1,858 frontend passes across 135
  files**, **105 synthetic browser workflows** and **35 intercepted
  loopback/HTTP workflows**. Build, API parity, compilation, privacy and
  whitespace gates pass; the protected loopback app serves the new bundle.
- The historical generated SQLite privacy artifact was validated as one
  ordinary generated file and moved recoverably to the Recycle Bin. The
  unchanged scanner and seven focused privacy tests pass.

This closes one bounded directory-create slice and makes the existing reviewed
file lifecycle available to the coding chat. It does not add recursive parent
creation, deletion, directory moves, overwrite, power-loss atomicity, durable
Agent content, unrestricted indexing, a new real-model quality run or owner
visual/native-click acceptance.

## Checkpoint 37: reviewed file creation and no-overwrite moves

- The Agent workspace now creates one bounded UTF-8 text file in an existing
  folder and renames/moves one clean opened UTF-8 text file to another existing
  folder. The target must remain absent; neither operation has overwrite or
  missing-parent authority.
- `local-agent-workspace-lifecycle.v1` capabilities retain only bound path,
  revision, identity, size, mode and line-ending metadata. They are
  session-bound, single-use, capped at eight, expire at or before 120 seconds
  and are discarded with the session. Content is resubmitted at apply.
- Create and move have separate native-presence confirmations and private,
  no-store HTTP routes. Strict frontend parsing binds the response back to the
  exact request/session and rejects extra or contradictory authority.
- Move pins both directory chains and the source handle, uses native no-replace
  rename, verifies identity/content/path after publication and claims rollback
  only after exact restored readback. Any unresolved result hard-locks later
  lifecycle changes for that session.
- A repeated Windows acceptance run exposed an under-allocated native rename
  structure that could report success without either visible name. Correct
  native alignment plus a deterministic regression passed 1,000 native and 500
  complete repeated moves. Create/move target races preserve external files.
- The workbench presents complete create and source/destination move reviews,
  byte and line-ending truth, native-unavailable states, draft protection,
  verified readback, reviewed change-set refresh and responsive/forced-colors
  layout.
- Current frontend/browser evidence is **1,844 frontend tests / 135 files**,
  **105 synthetic workflows** and a clean **35 intercepted loopback/HTTP
  workflows**. The latter creates, rereads, moves and rereads at 390px and
  1,440px.
- The frozen cache-free backend inventory covered all **279** test files and
  initially reported 4,274 passed, nine platform skips and two failures. The
  stale generated OpenAPI failure was corrected and passed exact byte/API
  parity; the final affected workspace/Agent gate passed **180 tests**. The one
  remaining broad failure is the unchanged prohibited SQLite artifact. Exact
  non-overlapping receipts and limitations are in `checkpoint-37-handoff.md`.

This closes the bounded create and no-overwrite file-move slice. It does not add
directory creation/deletion/moves, overwrite, lifecycle operations inside the
multi-file transaction, power-loss atomicity, durable Agent content or owner
visual/native-click acceptance.

## Checkpoint 36: failure-atomic reviewed multi-file edits

- The manual Agent workspace can stage **two to eight changed existing UTF-8
  files**, review every bound diff together and submit one native-confirmed
  transaction. Per-file limits remain 256,000 bytes and 60,000 diff characters;
  a plan is capped at 1,024,000 proposed bytes and 240,000 diff characters.
- Preview authority is session-bound, metadata-only, single-use, valid for at
  most 120 seconds and bounded to four active plans per session. Draft and
  baseline content do not enter the capability. Mismatch, expiry, eviction,
  denial and session deletion leave no reusable publication authority.
- The backend preflights every member before publishing, uses the existing exact
  atomic single-file primitive under one write lane, verifies all final
  revisions and restores earlier publications in reverse order when a later
  write rejects or cancellation arrives. Cleanup temporarily masks cooperative
  cancellation only for the bounded restoration, then restores the outer stop
  state.
- A commit or rollback is claimed only from exact receipts and readback. An
  external race, uncertain publication or uncertain restoration yields an
  explicit `unverified` result, preserves copyable drafts and hard-locks later
  writes for that session. This is stable-workspace failure atomicity, not a
  claim of power-loss or cross-process atomicity.
- Consecutive groups of two to eight valid existing-file `write_file` calls in
  one model reply receive one combined review and approval while retaining
  distinct tool calls, results and write receipts. Manual and model transactions
  both update the separate reviewed-path tracker only from verified outcomes.
- The strict frontend parser rejects response extras, unsafe paths, order,
  request-binding, totals and result-state inconsistencies. The card blocks
  single-file apply while staged, protects drafts on navigation, shows every
  diff, preserves rollback drafts and distinguishes root replacement from an
  unverified transaction lock.
- Current final frontend/browser evidence: **1,828 frontend tests / 134 files**,
  **105 synthetic browser workflows** and **33 intercepted loopback/HTTP
  workflows**. The two-file real-transport fixture verifies one review, one
  native confirmation and exact readback at 390px and 1440px. An integrated run
  reproduced a misleading duplicate transaction alert after root replacement;
  the states were separated and all affected width/view cases pass.
- Focused backend evidence passes **31 checks**, including commit, stale
  all-or-nothing preflight, rollback, rollback uncertainty, cancellation-safe
  restoration, CRLF byte restoration, capability bounds/expiry/single-use,
  model batching, manual tracking, private HTTP and generated OpenAPI contracts.
- The frozen cache-free backend gate covers all **278** `test_*.py` files in four
  disjoint shards: **4,257 passed, nine skipped and one failed**. Exact receipts
  are 1,038 passed / one skipped / one failed; 770 passed; 1,118 passed / six
  skipped; and 1,331 passed / two skipped. The sole failure is the unchanged
  privacy assertion for
  `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`;
  the standalone scanner reports the same one finding and no new artifact.
- Production build, generated API/OpenAPI parity, offline lock, Python
  compilation and whitespace checks pass. No model was loaded. The protected
  Agent launcher remains on exact loopback and serves `/agent` for HTML browser
  navigation.

This closes the bounded failure-atomic existing-file transaction slice. It does
not establish power-loss atomicity, exclusion of external writers,
create/rename/move/delete transactions, durable Agent content, owner visual
acceptance or whole-product completion.

## Checkpoint 35: bounded selected-folder and Git discovery

- One authenticated private/no-store session route now returns a current
  `local-agent-workspace-discovery.v1` snapshot: relative file paths, sizes,
  editor candidacy, bounded inventory counts/reasons and sanitized Git changes.
  It returns no content, revision/hash, branch, commit, remote, absolute path,
  stderr or partial failed-command output.
- Recursive application-readable inventory uses the existing no-follow
  workspace boundary and explicit 20,000-entry, 32-level, five-second and
  400-row bounds. Exclusions, links/reparse points, unavailable names and every
  limit degrade coverage instead of becoming empty or complete claims.
- Git runs only for a real `.git` directory at the selected root, by direct argv
  and the bounded owned-process lane. Gitfile/worktree layouts, common-directory
  pointers, object alternates, config includes, external worktree directives and
  repository-local diff/filter/merge helper sections fail closed. Prompts,
  pagers, optional locks, lazy fetch, external diff, renames, submodule
  recursion and global/system config are disabled.
- Root authority is checked independently from repository presence. Replacement
  during inventory or Git locks the session editor or discards status; a missing
  root cannot be relabelled as “not a repository.” Duplicate/unsafe/nonportable
  porcelain paths and truncated/failed output become fixed unavailable/partial
  states.
- The Agent workspace now leads with a responsive discovery card: exact
  complete/partial/unavailable labels, fixed warnings, path filtering, safe file
  opens and a separate Git list. Session/transport/refresh changes abort stale
  reads, failures remove prior results, and settled turns/manual applies refresh
  automatically.
- Discovery is observation only. It does not promote command-created or external
  changes into the checkpoint-34 reviewed-path authority.
- Current evidence: **21 dedicated backend discovery/API tests**, **293 adjacent
  Agent/workspace/command/runtime/OpenAPI tests**, **262 focused discovery/
  workspace/Agent/transport frontend tests / 5 files**, **1,810 frontend tests / 133
  files**, **105 synthetic browser workflows**, **31 intercepted loopback/HTTP
  workflows**, production build and generated API/OpenAPI parity. The frozen
  backend shards pass **4,240 tests**, skip nine unavailable Windows symlink
  cases and fail only the unchanged privacy-artifact assertion. The standalone
  scanner reports that same one artifact. No model was loaded.

This closes the bounded application-readable selected-folder/Git discovery
slice. It does not establish unrestricted indexing, linked-worktree support,
durable history, multi-file atomic editing or owner visual/native-click
acceptance.

## Checkpoint 34: live reviewed-path Agent change set

- Each memory-only Agent session now tracks the first retained baseline and live
  current state for paths admitted by verified/unverified Agent writes or the
  revision-bound manual editor. Current created, modified, deleted, reverted and
  unknown effects are separate from historical turn receipts.
- Scope remains `reviewed_paths_only`. Commands, external revisions, active
  turns, unverified publications, evidence gaps and capacity/tracker failures
  make coverage partial; none are promoted into reviewed authority.
- The inventory route returns content-free counts, fixed states and relative
  paths. A separate private/no-store request returns one explicit bounded net
  diff. The frontend validates exact session/path authority and aborts stale
  inventory/diff reads.
- The Agent transcript now presents the live Reviewed change set before a
  separately labelled historical Session activity card. Manual apply refreshes
  immediately; settled turns refresh on their final receipt. Empty-file
  existence and line-ending-only changes remain truthful.
- Regressions reproduced the historical-receipt/current-state mismatch, stale
  cross-session and unavailable-transport diffs, an empty-file `no_change`
  result, duplicate Windows case aliases for one physical path, invalid diff
  path error leakage, and missing/incoherent success receipts. All are repaired.
- Current scoped evidence: **168 focused Agent backend tests** including 15
  dedicated change-set cases, **301 adjacent Agent/workspace/command/runtime/
  OpenAPI tests**, **250 focused frontend tests / 6 files**, the
  production build, API/OpenAPI parity, **105 synthetic browser workflows** and
  **31 intercepted loopback/HTTP workflows**. The frozen broad gate passed
  **4,219 backend tests** with nine explicit platform skips and only the known
  privacy-artifact failure; the full frontend passed **1,787 tests / 131 files**.
  The standalone scanner reports the same single finding. Zero model runtimes
  and test workers remained after exact checkpoint-output cleanup; the existing
  4173 development listener was preserved.

This closes the reviewed-path net-inventory gap only. It is not Git status,
whole-workspace discovery, a multi-file atomic transaction, durable conversation
retention or owner visual/native-click acceptance.

## Checkpoint 33: atomic native launch and shutdown evidence

- Native-owned HTTP services now start from an atomically pre-bound,
  non-inheritable exact-loopback socket. Uvicorn no longer performs a later bind
  after a fallible free-port check.
- Protected Agent never attaches the native bridge to another process. When the
  configured address/port cannot be reserved, it owns an OS-assigned loopback
  port and leaves the configured listener untouched. The overlay still attaches
  only after the existing identity proof and otherwise owns the configured port.
- Agent and overlay entry points publish separate private,
  `native-lifecycle.v1` latest-state records. Fixed phases and failure/component
  codes contain no clock, PID, port, host/path, prompt, session, provider, model
  or exception data. Atomic replacement preserves the prior record until the new
  one is synced.
- A clean `stopped` result requires the native `closed` event and confirmed
  owned-service cleanup. A returned GUI loop without that event is
  `window_close_unconfirmed`, not code-zero success. A hard exit leaves its last
  non-terminal phase; the next launch carries only that fixed prior outcome as
  `interrupted`.
- Initial focused evidence: **191 tests** across lifecycle, privacy, desktop
  identity/overlay and Windows distribution boundaries. Both real hidden native
  engines loaded and closed; both installed GUI executables loaded and closed.
  The packaged Agent passed while its configured port was deliberately occupied,
  proving the fallback remained separately owned. All four probes used disposable
  state and no model/provider content.
- Frozen-state broad coverage completed in four disjoint cache-free shards:
  **4,204 backend passes, 9 expected Windows symlink skips and 1 known privacy
  failure**. The frontend passed **1,760 tests / 129 files**; browser coverage
  passed **105 synthetic** plus **30 loopback-backed HTTP** workflows.
- Production frontend build, generated API consistency, offline lock check,
  Python compilation, diff and targeted whitespace gates pass. The scanner still
  rejects exactly the old synthetic SQLite artifact; no bypass was added.
- Cleanup found zero model runtimes, zero native launcher processes and no owned
  test listeners. The pre-existing loopback development listener was preserved.
  Final commands, shard receipts and explicit limits are in the checkpoint 33
  handoff.

The historical unexplained exit is not retrospectively diagnosed. This record
distinguishes clean, failed and interrupted lifecycle evidence; it is not a crash
dump or proof of an operating-system cause. Native approval/folder-picker owner
clicks, signed installer distribution and final visual preferences remain open.

## Checkpoint 32: truthful memory-only Agent session effects

- The Agent workbench now aggregates validated turn receipts into a visible
  session-effects ledger: observed actions, reviewed writes, paths with a
  verified create/modify effect, unverified writes and command attempts whose
  effects are not inventoried.
- Verified no-op writes no longer claim that a file changed. Repeated receipts
  are grouped by path and list unique turn numbers. Invalid, duplicate or
  conflicting turn summaries cannot produce a complete-coverage label; running,
  incomplete, partial and expired-history states remain distinct.
- The ledger explicitly says it is not a net Git diff and excludes manual,
  external and command-created effects. It remains memory-only. Durable content
  storage was not inferred past the owner-gated privacy decision.
- A responsive integration defect was reproduced after the first implementation:
  expanding effects in the fixed session header collapsed the transcript and
  intercepted turn-detail interaction at 1440 px. Moving it into the transcript
  scroll boundary repaired the overlap while keeping the composer visible.
- Evidence: **116 focused backend/API contract tests**; **1,760 frontend tests /
  129 files**; strict browser TypeScript, production build and generated API
  consistency; **105 synthetic browser cases** and **30 loopback HTTP cases**.
  A separate in-app browser pass expanded the card at 1440 and 360 px, found no
  browser warnings/errors and measured a 9.6 px gap between the mobile transcript
  and composer. The temporary tab was closed and the viewport was restored.
- No backend contract or persistence policy changed in checkpoint 32. No GPU
  model was loaded and no normal owner-app restart is claimed. At that checkpoint
  the known one-artifact privacy finding, native owner-presence acceptance, a net
  multi-file inventory, durable content retention and the whole-product goal
  remained open; checkpoint 34 later closes only the reviewed-path net view.

## Checkpoint 31: reviewed-write publication

- Reviewed writes now stage and verify exact bytes before an atomic publication.
  The approved path, parent, file identity, prior revision and proposed digest
  remain bound through publication; cross-session applies cannot both succeed.
  Exact no-ops preserve inode and timestamps.
- Windows existing-file replacement uses `ReplaceFileW` with a displaced backup
  under a pinned ancestor chain. Publication verifies both sides; concurrent
  content is restored rather than silently overwritten. New files are
  create-if-absent. Hard-link insertion, read-only targets, target/folder swaps,
  cancellation after staging, failed staging, failed cleanup and failed
  rollback all have real Windows regressions.
- Cleanup or verification uncertainty produces a fixed unsuccessful outcome and
  no applied receipt. The editor consumes the verified receipt directly. Its
  draft remains reviewable after a verified rollback and becomes read-only with
  Reload enabled after cleanup/publication uncertainty. Private backend detail
  is not rendered.
- Evidence: **304 backend tests / 17 files**, including **14 write-boundary
  cases**; **1,755 frontend tests / 128 files**; **105 synthetic browser cases**
  plus **30 loopback real-server cases**. Six new 360/1440 px recovery workflows
  cover rollback, cleanup uncertainty and unverified publication. A separate
  in-app browser pass confirmed the draft, lock/reload controls and fixed alert.
  Production build, API consistency, strict browser TypeScript and Python
  compilation passed.
- This Windows run does not certify the implemented POSIX exchange branch or
  POSIX ownership/ACL/xattr parity. Native picker/approval click-through, durable
  Agent transcripts, multi-file transactions and owner visual preference review
  remain open. The scanner still rejects exactly the unchanged old synthetic
  SQLite artifact. No GPU model was loaded; zero model runtimes remained, the
  real-test listener exited and the pre-existing loopback development listener
  was preserved. No normal owner-app restart is claimed.

## Checkpoint 30: bounded workspace inspection

- Model read/list/search and editor snapshots share no-follow, bounded inspection.
  The admitted root and opened-file identity are checked; real Windows junction,
  replacement/pinning, cancellation and handle-release cases pass. POSIX uses
  descriptor-relative operations but is not separately certified by this run.
- Listing/search no longer turn unreadable or partially inspected data into
  empty/no-match success. Limits cover actual traversal, bytes including failed
  reads, depth, matches and output. Regex matching has a deadline; strict UTF-8
  and prefix boundaries no longer silently invent replacement characters.
- Read-only Agent tools observe their turn's Stop. The session prompt records
  `workspace-inspection.v2` and distinguishes partial coverage from absence.
- The editor distinguishes complete-empty, incomplete and failed reads. A
  replaced root preserves a selectable draft and blocks editor changes without
  letting a stale old connection disable a new one. Fixed HTTP reasons and
  private/no-store response validation survive the actual frontend transport.
  Native per-action approval remains unchanged.
- Evidence: **285 backend tests / 16 files**, including all **64 new inspection
  and service cases**; **1,750 frontend tests / 128 files**; **99 synthetic browser
  cases plus 30 intercepted-HTTP cases**. Browser review confirmed the full
  37-character draft remained selected, read-only and within the viewport.
  No model was loaded; the owned tab and HTTP-test listener were closed.
- The unchanged one-artifact privacy finding and original product requirements
  remain open. This is not mutation-phase race certification, a command sandbox,
  a new full-backend baseline or a normal owner-app restart. Reviewed-write
  replacement/rollback and editor mutation lifecycle are the next bounded audit.

## Checkpoint 29: approved commands and cleanup quarantine

- The default command runner now observes its turn's cancellation during
  execution and occupied-lane waits. Output is bounded while captured. Windows
  atomic Job Object admission, owned descendants and pipe-worker cleanup are
  checked before a command or turn can claim completion.
- Stop/delete/shutdown, two-command isolation, startup/release failures and
  unconfirmed cleanup have synthetic real-process regressions. Cleanup
  uncertainty cannot become a successful follow-up model reply. Earlier command
  effects are not undone or presented as a verified file inventory.
- Agent v6 requires explicit cleanup authority. Quarantine survives worker exit,
  denies other pending actions, blocks further Agent/manual-edit mutations and
  preserves incomplete shutdown status. Native confirmation is unchanged.
- Main/separate views retain the pause across stale ready pages and fixed HTTP
  refusals. Drafts are selectable but read-only; Send/close/retry remain blocked.
  Copy-before-restart guidance states that drafts are not persisted. The shared
  model's Stop action remains distinct from command cleanup.
- Evidence: **248 backend tests across 15 files**, **1,739 frontend tests across
  128 files** plus the final overlapping **83-test** type-correction recheck,
  **97 synthetic browser tests** plus **26 intercepted-HTTP tests**. The handoff
  records initial reproductions, fixture corrections, final build/API/type and
  compilation checks, and the completed main/separate in-app review. Both drafts
  remained selectable after stale ready pages. The owned tab was closed without
  changing viewport settings; zero model runtimes and no owned test listener
  remained, while the existing development listener was preserved. No new full-backend sweep
  or normal owner-app restart is claimed. The scanner retains its one known
  synthetic-artifact finding; no cleanup workaround or safety-test bypass.

Windows command ownership is not a sandbox for hostile commands or independently
delegated services, universal adapter preemption, POSIX acceptance or proof of
model quality. Native acceptance, owner review, durable retention and the other
original requirements below remain open. Workspace listing/search boundaries
under Windows reparse points are a separate candidate for focused reproduction.

## Checkpoint 28: background model control and retry truth

- Owned subprocess I/O remains cancellable during blocked input and output. Live
  output bounds, strict JSON/exit-status checks and joined worker cleanup keep
  invalid or unfinished work out of completed model receipts.
- Per-run callbacks are released on every exit. Stop signals cannot become
  partial results, CPU retries or deep-model projections; service/publication
  boundaries preserve cooperative cancellation.
- Shared-lane waits renew the lease and observe cancellation before a source
  read. Unconfirmed cleanup quarantines the runner/service instance and the
  scheduler; later requests cannot allocate another model or read more source
  content through that instance.
- A reproduced late-cleanup race no longer loses quarantine when cancellation
  has already released the lease. Exact stopped-claim checks preserve sealed
  cancellations and prior heads without changing a newer job. A joined worker
  retains resource uncertainty instead of announcing clean shutdown/restart.
- UI/API quarantine metadata is explicit. Missing legacy status stays unknown,
  both supported provider families parse, and main/separate views retain Stop
  and the cleanup warning without inventing automatic retries or a saved result.
- Current evidence: a final **162-test backend recheck**, the separate
  overlapping 16-check cleanup/ownership correction and nine application
  lifecycle checks, **1,712 frontend tests**, **93 synthetic browser checks**
  and **22 intercepted-HTTP browser checks**. Production/API/type/compilation and
  whitespace gates pass. In-app narrow/desktop review completed; its owned tab
  was closed and viewport restored. No model was loaded; the final process
  check found zero model runtimes and no owned test listener.

The broad backend run finished: **4,070 passed, nine skipped, one failed** in
2,121.06 seconds. The failure is the known privacy artifact, and the skips are
unavailable Windows symlink capabilities. Its 4,080-test snapshot predates the
last cancellation/cleanup correction; the 162-test final recheck and the
targeted correction receipts passed afterward. These overlap other focused
receipts and are not added to the broad total. The handoff also records the
three corrected Enable-versus-refresh fixture failures. The scanner still reports only
the known synthetic database artifact; no deletion workaround or scanner bypass was used.
These checks do not certify arbitrary injected-adapter preemption, every orphan
process case, installed model quality, native acceptance or whole-product
completion. The original requirement table below remains authoritative.

## Checkpoint 27: cancellation before model response headers

- Request-scoped cancellation covers the owned local HTTP connect/upload/header/body lifecycle. Agent Stop, session deletion and shutdown join that request; another turn using the same model remains unaffected, and the shared runtime is not unloaded.
- Models chat no longer blocks the API event loop waiting for runtime headers. All three proxy URLs own client-disconnect and ASGI cancellation through the response lifetime, retain ordinary upstream error statuses, and close their upstream work.
- Agent v5 exposes `stopping` state. Repeated Stop requests are coalesced, detached acknowledgments are cancelled, stale Stop/event state cannot rewind newer activity, drafts survive, and the UI does not announce a busy session as ready for messages. Noncooperative injected work stays visibly running until it actually ends.
- Current evidence: 312 selected backend checks; the full 1,693-test frontend suite plus final targeted rechecks; 89 synthetic and 22 intercepted-HTTP browser checks. In-app fictional review covered narrow/desktop Stop and recovery. Production/API/type/compilation/whitespace checks passed. No real model was loaded; owned resources were cleaned up.

These receipts establish owned-client cancellation, not universal runtime generation-abort behavior, a new full-backend gate, native acceptance, owner visual approval, durable retention or overall completeness. The unchanged one-artifact privacy finding remains open. The checkpoint 27 handoff records the exact evidence and next bounded candidate.

## Checkpoint 26: Agent turn details and verified file writes

- `local-agent.v4` binds turn events and final metadata to an admitted turn and the actual requested model alias. Generation completion is separate from task verification.
- Runtime usage, coverage and server-observed timings remain unknown when unreported. Invalid or ambiguous counters cannot become numbers; totals never silently omit a model request. No cost or GPU-only metric is invented.
- Reviewed file writes provide verified before/after revisions and line counts, or an explicit unverified attempt. Denied/stale writes and model claims cannot become applied changes. Command effects, manual edits and net Git state are outside that inventory.
- Main and dedicated views expose compact details and safe current-file links. Unsaved drafts, replacement-session ownership and native apply approval remain protected. An actual HTTP-browser regression found and repaired initial file opening under Strict Mode effect remounts.
- Actual loopback HTTP checks found and repaired dropped usage trailers and blocked Windows stream cancellation. Metadata collection is bounded, including slow partial lines; additional output is not admitted after completion. Late errors after a user Stop are marked stopped.
- Final consolidated checks: 285 backend tests across 14 selected files, 1,688 frontend tests across 126 files, 85 synthetic browser checks and 22 intercepted HTTP cases pass. The 285 already includes all 14 actual HTTP transport cases; no overlapping earlier runs are added. Build/API/strict browser TypeScript/Python compilation/whitespace checks pass. The owned browser tab was closed and viewport restored; zero model-runtime processes and no owned HTTP-test listener remained. The pre-existing synthetic development listener was preserved; no normal owner-app restart is claimed.

Conversation data remains memory-only. Aliases are not immutable model identity, and reported usage is not independent billing evidence. Pre-header cancellation, native click-through, representative model quality and the existing retention/peer/release decisions remain separate work. The unchanged scanner still reports one old synthetic database; no cleanup bypass was attempted.

## Checkpoint 25: exact reviewed-case calibration

- Human ratings and model judgments must describe the same bounded redacted evidence, not just the same session. The review card offers standard/short windows, truncation and receipt status, and an explicit acknowledgment before saving. Expiry recovery preserves the draft and requires renewed review.
- Versioned case identity includes provider, session, source-window identity and actual rendered evidence; a model context retry seals the smaller case it really judged. Memory-only review receipts are bounded and expire. Schema 61 preserves historical unbound rows without backfilling or silently upgrading them.
- Rating saves are failure-atomic. Current agreement excludes mismatched/unverified cases and incompatible recorded model identities; `cannot_judge` is an abstention, not a scored pair. Separate unmatched/abstained counts keep unavailable agreement distinct from zero percent.
- Annotation work/results carry case provenance. Partial, duplicate and substituted remote receipts cannot become complete local work. Central SQLite connections close after reads, writes and errors. Explicit annotation/consent gates are unchanged.
- Real frontend transport and real application HTTP checks found and repaired missing JSON/safe-error handling and shared middleware overwriting private/no-store review headers. Browser review/save requires same-origin and CSRF proof; denied requests do not read evidence or store ratings.
- Final frontend: 1,623 tests across 124 files. Final browser suites: 81 synthetic workflows and 20 intercepted HTTP cases. The reviewed-case/comparison/annotation run passed 54 tests, including real cookie/token HTTP checks and known-answer agreement math.
- The full backend sweep covered all 260 test files in two disjoint shards: initially 3,905 passed, 24 failed and 9 skipped. Twenty-two stale schema expectations and one synthetic downgrade fixture were corrected; every corrected case passed. The final combined current-source run passed 107 tests, including all 23 corrections and the affected judgment/calibration/annotation/API paths. The only unresolved failure is the known privacy artifact; the nine Windows symlink skips remain unverified. This is not an all-green full-suite receipt. Exact shard/rerun results are in the handoff, without adding overlapping runs together.
- Final build, API generation/consistency, strict browser TypeScript, Python compilation and whitespace checks passed. Zero model-runtime processes and no owned HTTP-test listeners remained. The pre-existing synthetic development listener was preserved; the normal owner application was not restarted.

Matching case provenance is not proof of human independence, task success, immutable model revision or representative model accuracy. Exports remain sensitive derived data. The owned in-app test tab was closed and the viewport restored; no GPU model or real provider content was used. Privacy sign-off and the named product gaps below remain open.

## Checkpoint 24: structured model-result acceptance

- Local judgment, session interpretation, Prompt Check commentary and central inference now require a completed, unambiguous assistant text reply before accepting structured output. Limited, filtered, tool-request, missing-receipt or malformed responses remain invalid.
- Bounded strict JSON rejects duplicate keys, non-finite values, invalid Unicode, excessive depth and surrounding prose. Commentary/interpretation reject malformed fields rather than inventing defaults, silently clipping text or returning an empty success.
- Invalid generation does not overwrite prior labels or explanations. Deterministic Prompt Check metrics remain unchanged, and a bad central batch item does not prevent a later valid item from succeeding.
- New prompt/acceptance protocol versions separate current results from historical unchecked ones. Old rows remain readable, but older/unknown protocols and missing window identities are excluded from current agreement. Counts and protocol eligibility are visible; no eligible comparison remains unknown, not zero percent.
- Safe invalid-reply transport codes reach the UI. Session and Calibration screens distinguish invalid generation from model availability and retain usable retry actions without changing blind human ratings.

Generation completion and schema validity are not evidence of model accuracy or task success. This checkpoint does not establish representative calibration, exact human/model evidence-window alignment, universal instruction resistance, all-model compatibility or broader product completeness. The review checklist and exact limits are in the checkpoint 24 handoff.

## Checkpoint 23: truthful model completion

- Agent no longer treats token-limited, filtered, unrecognized, missing-receipt or reasoning-only output as a completed answer. Partial text remains visible but cannot enter completed history or admit tool execution. Stop also owns late whole-response fallbacks.
- Models chat validates bounded streaming/JSON replies and releases its response reader after completion, parse failure or abort. It preserves incomplete output with truthful status and keeps it out of follow-up history; explicit retry preserves the next draft.
- New regressions cover generation receipts and action/history authority, malformed fields, byte/text bounds, UTF-8/framing, cancellation, cleanup and recovery through both component and HTTP-browser paths.

Generation completion is not task verification. No metric publication, approval permission, content retention or API schema was changed. Current synthetic evidence does not certify every installed model, native click-through or answer quality. The full scope and remaining requirements below are preserved.

## Checkpoint 22: model-control ordering and recovery

- Delayed model reads can no longer overwrite a later confirmed Start/Stop receipt, and independent refreshes respect request order. Reads superseded by a command are distinct from current read failures.
- Starting/stopping states disable Send and Check & improve for the affected model while preserving the draft. Failed commands leave status explicitly unverified until a fresh observation succeeds.
- Model operations and pending session creation belong to their current connection. Replacement/unmount prevents old follow-up mutations and stale state updates without pretending to cancel a runtime command already issued.
- Regression coverage includes stale success/error responses before and during commands, recovery after command failure, connection replacement, unmount and later fresh observations. Browser checks cover main/dedicated views at 360 and 1440 px, including composer state, retained drafts and horizontal-overflow checks.

This is a frontend correctness repair, not a new model-runtime, native-approval, retention or backend-contract implementation. Matching standalone browser cases were added and typechecked, but the entire historical browser suite was not rerun. See the checkpoint 22 handoff for the current evidence and later owner-review list.

## Requirements and proof required

| Requirement | Authoritative sources | Evidence required | Current goal status |
| --- | --- | --- | --- |
| Reliable local desktop lifecycle | ADR 0016; WP-22; checkpoint 20 | Actual startup/readiness, ownership rejection, bounded and exhaustive shutdown, restart and privacy-safe failure receipts; synthetic regressions for failure paths | Checkpoint 33 adds atomic listener ownership, safe occupied-port fallback, exact close-event authority, content-free persistent lifecycle evidence, real native-engine probes and generated executable probes. The historical exit cause, signed installer and owner click-through remain separate |
| Selected-model Agent and Models workflows | ADR 0013/0016; UI-15/18 | Selected model produces a reply in a disposable workspace; cancellation, session ownership, composer access, activity display, stop/unload and preserved conversation tested; native actions never bypass confirmation | Checkpoint 21 real-model workflow passed; checkpoints 22/23/26/27 add ordering, completion, turn/write receipts, actual HTTP pre-header/body cancellation, proxy responsiveness and cross-request isolation. Checkpoint 32 adds historical receipt aggregation; checkpoint 34 adds the bounded live reviewed-path net view and exact lazy diffs; checkpoint 35 adds separate bounded selected-folder/Git observation; checkpoint 36 adds one-approval failure-atomic batches of existing-file writes; checkpoint 37 adds reviewed create and no-overwrite file moves; checkpoints 38/39 add first-class directory create, file move and directory move through the same denial cleanup/native review boundary; checkpoint 40 adds exact recoverable single-file Recycle Bin removal without permanent or directory-delete authority. This is not a new real-inference run, durable history, unrestricted index or certification of every model |
| All UI-00 through UI-20 surfaces | UI card backlog; checkpoint 19 surface inventory; checkpoint 20 repairs | Requirements mapped to success/loading/empty/error/stale states, keyboard/narrow-window behavior and exact action ownership; untested states explicitly recorded | Existing surface inventory retained; checkpoint 40 passes 105 synthetic workflows and 35 intercepted loopback/HTTP workflows, including create folder, create nested file, move folder, nested-file readback, no-overwrite file move, recoverable file removal and multi-file review/apply at narrow and desktop widths. Checkpoint 33 retains native UI-20 executable/start/close evidence. Owner preferences and the proposed chat-first redesign remain separate |
| Metric correctness and authority | Metrics catalog; metric operability; applicable work packages/ADRs | Known-answer synthetic evidence, exact counts/states and provenance, unknown versus zero, immutable identities, no assistant self-verification, no model promotion without calibration | Checkpoint 25 adds exact reviewed-case binding, abstention/identity-safe agreement and known-answer comparison tests. Current full-tree and corrective-run receipts are recorded above; representative model quality and immutable model identity are not established |
| Privacy and local-only invariants | AGENTS.md; privacy documentation; CI gate | Secret/PII scanner, loopback guard, binding/consent/native-presence tests, platform security preflights and no real session content used | The unchanged scanner and 19 focused privacy tests pass. The historical generated SQLite artifact was moved recoverably to the Recycle Bin after exact path/type validation; no exclusion was added. Checkpoint 35 adds content-free discovery contracts, private headers, no-follow inventory and fail-closed Git indirection/output tests; checkpoints 36-40 keep transaction and lifecycle authority metadata-only, session-bound, private/no-store and memory-only. Directory-move preview/results deny subtree content review; file-trash contracts deny permanence and directory authority. Windows process ownership, native no-overwrite/recycle and reviewed-parent/source races, and real junction/read/write-boundary tests pass; the nine Windows symlink-capability skips and POSIX publication acceptance remain distinct |
| Product completeness and known unfinished capabilities | Product trajectory; work packages; pending owner decisions | Distinguish implemented, verified, unfinished and authorization-gated features; no unsupported production identity, billing, release, retention or remote-delivery claims | Open; memory-only reviewed-path authority, bounded selected-folder/Git observation, stable-workspace failure-atomic existing-file transactions, reviewed file create/move, one-directory create/move and one recoverable Windows file removal are complete only in their stated scopes. Durable authored Agent projects/sessions/artifacts, global runtime arbitration, capability-gated modalities, broader probe-confirmed model adapters, unrestricted indexing, directory/POSIX trash and power-loss atomicity remain unfinished or owner-gated; the Agent experience plan does not relabel them as implemented |
| Integrated regression and handoff | CI quality gate | Current full backend/frontend/browser/build/API checks, skip review, reproducible checkpoint notes, local app readiness and cleanup of owned test resources | Checkpoint 40 records its focused and frozen broad gates in a dedicated handoff: 4,308 backend, 1,882 frontend, 105 synthetic browser and 35 loopback/HTTP passes, plus clean build/API/lock/privacy/compile/whitespace gates. Checkpoints 39/38/37/36/35/34/33 retain directory-move/create, file-lifecycle, transaction, discovery, reviewed-path and native/generated-executable evidence. The protected Agent launcher serves the final build on loopback; no whole-product completion, signed installer acceptance or owner visual approval is claimed |

## Execution rules

- Preserve all existing working-tree changes; no commit or push without a request.
- Use fictional data and isolated app state. Never read provider credentials or real sessions to manufacture a passing integration check.
- Reproduce candidate defects before counting them as repairs. Record regressions and remaining limits.
- Native confirmations remain human-presence boundaries, not test shortcuts.
- Any model used for local inference testing is unloaded in a finally/cleanup path and checked afterward. Unrelated GPU applications are untouched.
- Absolute bug-free certainty is not a testable claim. Completion of a concrete requirement needs matching evidence; missing or indirect evidence stays open.

## Checkpoint 21: desktop lifecycle

Initial observations: the previous loopback service is not reachable. That does not establish whether it crashed or was closed. The owned-server stop method has no final surviving-thread check; GUI startup errors use one generic message; runtime cleanup collapses failures to a generic marker. These are investigation targets, not a diagnosis of the earlier exit.

The following have now been reproduced and repaired:

- Surviving server threads and failed joins cannot report a successful stop. Forced cleanup is attempted and outcomes remain explicit.
- Startup readiness cannot accept an already-dead owned server.
- Application cleanup records only closed component names, separately for startup and shutdown; no exception, traceback or private adapter value is retained in the receipt.
- Normal lifespan and forced-exit fallback share one exhaustive, idempotent cleanup. A closed listener without cleanup evidence is not reported as a clean application shutdown.
- A model service that has shut down rejects later activation, including a request that starts after cleanup. Existing in-flight generation guards remain intact.
- Native messages show safe, specific failure codes. A primary window failure is not overwritten by a secondary cleanup failure. Unchecked Uvicorn tracebacks are not emitted by the desktop host.

Evidence so far: 186 focused lifecycle/model/identity/worker/API tests passed before the additional transport checks below. Three full-composition loopback start/stop/restart cycles, including forced exit, passed. Real owned stub-model processes exited on normal and forced HTTP-server shutdown. Actual Windows Agent and overlay native-engine probes loaded their documents, closed, released their listeners and removed disposable state. These probes deliberately use hidden windows and automatic close without a close-confirmation prompt; they do not certify folder picking, protected native approvals or owner-window interaction. The installed launcher exists and its registered/imported entry target matches; an earlier owner-window exit has not been retrospectively diagnosed.

## Real model and transport verification

- Synthetic tests reproduced that the local inference HTTP client could use system proxies and follow runtime redirects. Health, normal chat and streaming chat now use a proxy-free, no-redirect opener. All three new regressions passed; the non-loopback test guard prevented the attempted redirect during reproduction.
- One installed 27B GGUF was loaded in an isolated registry, without reading owner configuration or sessions. A direct reply, real Agent session, read-only file tool, exact fictional-file answer and active-stream stop within five seconds all passed.
- After unload, the conversation remained and a new send was rejected as model-not-ready. The owned runtime exited and disposable state was removed. A separate process check found zero `llama-server` processes afterward.
- This validates one real local workflow, not all models, license/provenance admission, representative model quality or calibrated metric judgments. The local file is not promoted to a product-certified model.
- Earlier in this goal, the frontend snapshot passed 1,518 tests across 122 files. Additional Agent/research regressions brought the final count to 1,523 below; these are not separate unique tests to add together. Generated API contracts include the shutdown and cancellation states.

## Real browser acceptance and additional repairs

The in-app browser controlled a disposable real-HTTP application, not an intercepted API, with an existing installed local model. The workflow selected a fictional workspace, started the exact selected model, created a read-only Agent session, focused an enabled composer, read a fictional file through the actual tool, and displayed its exact marker. A second response streamed and stopped in 303 ms. Stopping the model retained the conversation and disabled sending. Native protected actions remained unavailable in the ordinary browser.

This acceptance found further defects that the earlier fixture checks had missed:

- A narrow Agent workbench reduced the transcript to a tiny strip. The transcript now keeps a readable minimum height and dedicated windows can grow. Four geometry regressions cover both Agent routes at 390 and 800 px; they failed before the change and pass afterward. A browser screenshot was inspected without storing it in the repository.
- A completed, empty tool-only assistant event produced a misleading empty reply bubble. Only that redundant completion bubble is suppressed; stopped/failed empty replies and the tool activity remain visible. Three status-specific regressions pass.
- Session model controls could remain actionable after a confirmed service disconnect. Both running and stopped-model states now disable the affected action; two regressions pass.
- Shared-folder SQLite connections remained open after their transaction contexts exited, preventing disposable application state from being removed on Windows. Connections now close on success, reads and exceptions, while preserving rollback. The retained-connection regression failed before the repair; a fresh complete app fixture now exits with confirmed listener, model and temporary-state cleanup.

## Background work and shutdown truth

- Agent turn admission is failure-atomic: a thread-start failure no longer consumes a draft or leaves a session running. Shutdown closes admission and denies pending approvals. A session whose thread survives deletion is not silently discarded. Already-approved blocking tools retain their own timeout; a surviving turn is explicitly reported as incomplete cleanup.
- The local model-screen service owns its subprocess/thread, accepts cooperative application cancellation, bounds child output, reaps its child on cancellation, and rejects further work after shutdown or unconfirmed cleanup. Thread-start failure cannot leave an endless busy job. A top-level failed evaluation with no outcomes no longer becomes a successful job. Research UI/API contracts distinguish cancellation and unconfirmed cleanup from accepted results.
- Analysis workers observe shutdown through heartbeat/publication boundaries. Uncommitted cooperative work follows the existing bounded retry policy; a committed publication remains authoritative.
- Ensemble-watch cancellation uses the exact active lease, preserves the last valid head, and does not invent a model failure. The child heartbeat checks cancellation every second. A stale owner cannot cancel another owner's attempt.
- Shared application cleanup now includes Agent and model-screen services. One component's failure does not suppress other cleanup attempts, and only closed component codes are retained.

Focused evidence: 67 Agent/evaluation/lifecycle tests passed together, the active-watch shutdown test passed, and both normal/shutdown lease-bound cancellation cases passed. Separate Windows process-tree preflight: three cases passed without skips. These are focused runs, not additional unique tests to add to the final full-suite total.

## Original integrated gate results

- Current production build, Python compilation, offline lock consistency, generated API contract and whitespace checks pass.
- Current browser suites: 63 synthetic workflows and 12 intercepted local-contract cases pass. These do not replace the separate real-model/browser acceptance above.
- Both actual Windows native-engine probes pass again with the final built assets: document load, automatic hidden-window close, released listener and deleted disposable state. They do not certify native folder picking or protected action approval.
- Full backend verification finished as two non-overlapping sorted-file shards covering all 254 test files: 3,649 passed, 9 skipped and 1 failed. The failure is the repository privacy assertion on the known synthetic fixture below; a focused rerun confirms the exact finding. Shard receipts: 1,820 passed / 6 skipped / 1 failed in 19m36s, and 1,829 passed / 3 skipped in 23m44s. The nine skips are the same Windows symlink-permission gaps across database, model provenance/evaluation, quarantined reader, scanner, social SQLite and home boundaries. The existing test-client deprecation warning appeared in both processes. Skips and the privacy failure are not passes.
- The first current full frontend run reported 1,522 passes and one approval-control lookup failure while several gates ran concurrently. The exact test, all 47 Agent tests and a complete 1,523-test rerun passed. The timing-sensitive test now explicitly awaits its initial synthetic capability/session/event promises and additionally asserts that Approve is enabled; all rejection/retry checks remain. The final standard-worker full suite passed again: 1,523 tests across 122 files in 94.55 seconds. No production approval behavior was changed to satisfy this test.
- Privacy gate remains open: the old synthetic fixture from the reproduced SQLite leak remains under `test-results/browser-workflow-e3rix2kz`. The scanner correctly rejects its SQLite artifact. Automated deletion was blocked; owner cleanup was requested. No scanner exclusion or weakening was added. A fresh fixture with the repaired store removes itself normally.
- After both backend shards ended, their custom pytest `nodeids` caches introduced additional scanner findings from synthetic privacy-test canary parameters. Only those two generated index files were removed after exact path/link validation; the old fixture was not touched or bypassed. Cache-free custom verification uses `-p no:cacheprovider`; assertions and scanner rules remain unchanged.

## Still not claimed complete

- Universal correctness, all-model compatibility, calibrated judgment quality, and owner visual acceptance cannot be inferred from test counts.
- Native picker/approval click-through, a symlink-capable host, real peer delivery and the installed OS launcher still require their respective acceptance environments. Direct native entry success is not proof of the earlier packaged-launcher behavior.
- Agent conversations, transaction capabilities and reviewed baselines remain memory-only. Checkpoint 34 provides current net effects and bounded diffs for reviewed paths; checkpoint 35 separately provides bounded content-free selected-folder/Git observation; checkpoint 36 provides failure-atomic review/publication for two to eight existing files while the workspace stays stable. None establishes durable history, unrestricted indexing, power-loss/cross-process atomicity, create/rename/move/delete transactions, immutable model identity or fully owner-accepted coding-chat design. Durable retention, richer editing, background-inference cancellation acceptance and owner visual acceptance remain explicit work.
- Remote annotation has an uncertain-outcome guard, not an authoritative delivery-reconciliation service. Identity, billing, internet collaboration, signed release/distribution, encrypted retention and remote content destinations retain the requirements and authorization gates in the product trajectory and owner-decision log.
- No real provider sessions, credentials or owner configuration were used. No commit or push was performed. Test-model cleanup is checked separately from unrelated GPU applications.
