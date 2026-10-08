# Checkpoint 34: live reviewed-path Agent change set

Status: scoped implementation and automated verification complete. The whole
application remains open against the verification ledger. The single existing
privacy-artifact finding remains open.

## What changed

- Each memory-only Agent session now owns an `agent-change-set.v1` tracker. It
  observes verified and unverified Agent file publications and manual editor
  publications admitted through the existing revision-bound review flow.
- The tracker retains the first reviewed baseline for each admitted path and
  re-reads the live file through the existing no-follow workspace boundary. The
  result distinguishes current created, modified, deleted, reverted and unknown
  effects instead of treating historical receipts as current state.
- Coverage is complete only while the session is settled and every retained
  path remains verified. A running turn, approved command, unverified write,
  external revision, review-chain gap, missing/unavailable file, capacity
  omission or tracker failure makes the scoped result partial.
- Inventory responses contain only relative paths, counts and fixed states. They
  carry no file content, revisions or hashes. Exact content is returned only for
  one explicitly requested bounded net diff. Empty-file existence and
  line-ending-only changes remain distinguishable.
- Bounds are fixed at 64 tracked paths, 4,000,000 retained baseline bytes,
  eight pending manual-preview baselines and a 60,000-character diff. All state
  is released with the in-memory session.
- Two authenticated private/no-store loopback reads expose the inventory and
  one path's diff. The frontend strictly validates exact fields, session/path
  ownership, count/coverage coherence, reason vocabulary, diff headers and
  private response headers.
- The Agent transcript now leads with a **Reviewed change set** card. It shows
  live reviewed-path coverage, current/reverted/attention counts, Agent/manual
  sources, fixed warnings, current-file links and lazy net-diff review. Failed
  refreshes discard stale data, and session/refresh changes abort in-flight
  inventory and diff reads.
- The older card is now **Session activity** and explicitly describes historical
  receipts. A sequence that modifies and then restores a file no longer claims
  that the session currently has a changed file.

## Defects reproduced and repaired

- A modify-then-revert sequence still displayed `1 file changed` because the UI
  summed historical receipts. The regression failed before the wording/authority
  split and passes with a live reverted-path result.
- A late diff from session A could resolve after session B replaced it. The
  active diff controller now aborts on every session or refresh transition; the
  stale result cannot reappear. Replacing the transport with one that lacks the
  change-set capability also clears an already-open diff instead of leaving old
  evidence under an unavailable state.
- Windows case aliases could register the same physical file twice (for example,
  `Example.ts` followed by `example.ts`). The tracker now uses one
  case-insensitive Windows identity while retaining the first reviewed display
  path; a differently cased direct diff request fails closed.
- Creating an empty file compared equal to an absent baseline at the text layer
  and could be labelled `no_change`. It now returns an explicit zero-line
  existence diff with `/dev/null` authority.
- Manual publication whose post-write receipt cannot be verified enters the
  inventory as unverified; it never becomes a successful reviewed change. A
  rejected or no-change manual preview enters no change record.
- A nominally successful Agent write with a missing or incoherent verification
  receipt now fails closed as `workspace_verification_failed` and marks coverage
  partial. Tracker bookkeeping failure after a genuinely verified publication
  does not rewrite the successful workspace outcome, but does degrade inventory
  authority.
- Invalid or differently cased direct diff paths now return the fixed
  `change_path_not_found` 404. The reason is transport-allowlisted without
  surfacing arbitrary server detail.

## Verification receipts

- Focused Agent backend/API integration: **168 passed**, including **15 dedicated
  change-set cases**, with the existing Starlette/httpx deprecation warning.
- Adjacent Agent, workspace, command, cancellation and OpenAPI selection:
  **301 passed** with the same warning.
- Focused Agent/frontend/transport selection: **250 passed / 6 files**.
- Production frontend build, generated API consistency, OpenAPI export and
  Python compilation pass.
- Browser acceptance passed **105 synthetic workflows** and **31 intercepted
  loopback/HTTP workflows**. The added flow composes a fictional native approval,
  applies a reviewed edit, refreshes to one current manual change and opens the
  exact net diff. It never reads an owner workspace.
- The frozen full frontend gate passed **1,787 tests / 131 files**. Its first run
  exposed one requirement-action regression that did not await the observable
  confirmation-ready state; the isolated scenario and all 39 cases passed, the
  test now verifies readiness explicitly, and the complete suite then passed.
- The frozen full backend gate covered all **276** `test_*.py` files in four
  disjoint cache-free shards: **4,219 passed, 9 skipped, 1 failed**. Exact shard
  receipts were 1,022 passed / 1 skipped / 1 failed in 482.26 s; 742 passed in
  460.46 s; 1,168 passed / 6 skipped in 544.18 s; and 1,287 passed / 2 skipped in
  784.42 s. The nine skips are unavailable Windows symlink capabilities. The
  sole failure is the unchanged repository privacy assertion for
  `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`.
- The standalone privacy scan independently reports that same one prohibited
  artifact and no other finding. It remains a failure, not a pass; no scanner
  bypass or fixture deletion was used.
- Final cleanup removed only the four checkpoint-owned Playwright output
  directories after exact path/content/reparse validation. Zero test workers
  and zero model runtimes remained; the temporary 4175 listener was closed and
  the pre-existing 4173 development listener was preserved. No model was loaded.

## Explicit limits and next work

- `reviewed_paths_only` is not Git status and does not scan untracked workspace
  paths. Commands and external changes remain outside reviewed authority.
- This is not an atomic multi-file editing transaction. Each approved write
  keeps its existing independent revision/publication boundary.
- The tracker and conversations are memory-only. Durable retention remains an
  owner-gated privacy-vault decision and was not inferred from this checkpoint.
- Rich syntax editing, rename/move/delete controls, durable shell sessions and
  whole-workspace discovery remain separate product slices.
- Native folder selection and a real protected-action click still require owner
  presence. The browser flow validates contract/UI composition with fictional
  input, not the operating-system dialog.
- No provider sessions, credentials, owner configuration or real workspace were
  read. No model or GPU runtime was loaded. The normal owner app was not
  restarted, committed or pushed.
