# Checkpoint 36: failure-atomic reviewed multi-file edits

Status: scoped implementation and automated verification complete. The whole
application remains open against the verification ledger, and the single
existing privacy-artifact finding remains open.

## What changed

- The Agent manual workspace now stages two to eight changed existing UTF-8
  files and turns them into one sorted, revision-bound review. Every diff remains
  visible before one native-confirmed apply.
- The strict `local-agent-workspace-transaction.v1` contract binds the session,
  plan, relative paths, expected and proposed revisions, line endings and exact
  apply content. Server and browser reject extra fields, unsafe/duplicate paths,
  bad ordering, drifted totals and incoherent result states.
- Per-file limits remain 256,000 proposed bytes and 60,000 diff characters. One
  transaction is capped at eight files, 1,024,000 proposed bytes and 240,000
  diff characters. A session retains at most four 120-second plan capabilities.
- Capabilities retain metadata only: paths, revisions, line-ending, identities
  and mode. Draft/baseline content remains request- or session-local, and all
  capabilities are discarded with their session.
- Apply consumes its capability before mismatch or publication is reported,
  re-preflights every member and publishes through the exact existing single-file
  primitive while holding the application write lane.
- Each publication and final file is verified. If a later publication rejects,
  earlier files are restored in reverse order and verified. Cooperative Stop
  remains active for normal work but cannot interrupt the bounded restoration
  cleanup after an earlier file has been published.
- Any publication, verification or rollback that cannot be proved becomes an
  explicit `unverified` transaction. No successful commit or rollback is
  invented. The UI preserves copyable drafts and locks every further write for
  that session.
- Consecutive runs of two to eight valid existing-file `write_file` calls from
  one model response use one combined review and approval while preserving one
  tool result and receipt per call. New-file, non-consecutive and larger runs
  retain the established single-file path.
- Manual committed files refresh the reviewed-path change set individually.
  Verified rollback, mismatch and denial discard transient baseline authority;
  uncertain outcomes mark coverage partial.

## Defects reproduced and repaired

- The previous Agent editor could review only one manual file at a time and the
  model required a separate approval for every `write_file`. There was no
  all-members preflight, shared capability or rollback contract. The new slice
  implements all four as one bounded path.
- A first rollback implementation could observe the already-set cooperative
  Stop signal again while restoring the first published file. The bounded
  critical-cleanup scope now suspends only request cancellation during exact
  restoration and restores the outer signal afterward.
- The first capability deadline check treated the exact deadline as still live.
  Pruning and apply now expire at `deadline <= now`, with a boundary regression.
- Failed or mismatched manual applies could leave transient per-file baseline
  stages behind. Applying now discards the whole plan on every exception and in
  final cleanup.
- An inconsistent low-level result with `ok=True` but no exact verified receipt
  could be classified too softly. Any success/receipt inconsistency now marks
  that member unverified and prevents a commit claim.
- Frontend transport did not initially retain fixed transaction failure codes.
  The allowlist now keeps only documented codes while dropping arbitrary server
  message text; a private canary regression covers the boundary.
- The multi-file card initially lacked a direct unverified-result lock test and
  did not cover navigation back to an already staged draft. Both behaviors are
  now explicit component regressions.
- The complete HTTP browser gate found that a replaced workspace root reused the
  `transactionBlocked` flag, creating a misleading second “unverified
  transaction” alert. Root replacement already owns its own write lock; the two
  states are now separate and all four main/dedicated narrow/desktop cases pass.

## Verification receipts

- Dedicated transaction backend: **16 passed**. Coverage includes metadata-only
  authority, bounded eviction/session cleanup, exact commit, stale all-member
  preflight, later-write rollback, rollback uncertainty, cancellation-safe
  rollback, CRLF byte restoration, limits, session binding, expiry, single-use,
  model batching/denial, manual tracking and native-confirmed private HTTP.
- Focused backend transaction/runtime/OpenAPI gate: **31 passed**, with the
  repository's known Starlette test-client deprecation warning only.
- Focused Agent-page/workspace/parser/transport frontend gate: **260 passed**.
  The final workspace component recheck passes **29 tests** after the integrated
  root-state correction.
- Frozen full frontend: **1,828 tests across 134 files passed**.
- Synthetic browser suite: **105 workflows passed**.
- Intercepted loopback/HTTP browser suite: the first run passed 32 and exposed
  one ambiguous duplicate-alert defect. Its focused four-case regression passed,
  and the fresh complete rerun passed **33 workflows**. The two-file transaction
  commits and rereads both fictional files at 390px and 1440px.
- Python compilation for every changed transaction module passes.
- The frozen backend gate covered all **278** `test_*.py` files in four disjoint,
  cache-free shards: **4,257 passed, nine skipped and one failed**. Exact shard
  receipts were 1,038 passed / one skipped / one failed in 779.02 s; 770 passed
  in 723.63 s; 1,118 passed / six skipped in 878.89 s; and 1,331 passed / two
  skipped in 1,263.80 s. The nine skips are unavailable Windows symlink
  capabilities. The sole failure is the unchanged repository privacy assertion
  for `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`.
- The standalone privacy scanner reports that same one prohibited artifact and
  no new finding. It remains a failure; no exclusion, scanner weakening or old
  fixture deletion was used.
- The production frontend build, generated API/OpenAPI parity, offline lock,
  Python compilation and whitespace gate pass. The known Starlette test-client
  deprecation warning remains non-failing.
- The protected launcher is still owned by `prompt-enhancer agent-desktop` on
  exact loopback. `/agent` returns 200 for an HTML navigation and deliberately
  returns 404 for non-navigation JSON requests. The latest production bundle is
  served on reload. Final inspection found zero test workers and zero model
  runtimes; no model was loaded.
- Five checkpoint-owned Playwright output directories were validated as ordinary
  directories beneath the operating-system temporary root. This execution
  environment denied their exact recursive removal, so those disposable test
  outputs remain outside the repository; no broader delete or workaround was
  attempted.

## Explicit limits and next work

- “Failure-atomic” means that, while the reviewed workspace remains stable,
  application-detected failure restores prior publications or reports an
  unverified outcome. Portable cross-file writes are not power-loss atomic, and
  another process can still race the application.
- Only changed existing UTF-8 text files are admitted. This slice does not
  create, rename, move or delete files, merge conflicts, or provide a journaled
  filesystem transaction.
- Four plans and a 120-second lifetime intentionally bound metadata authority.
  Refreshing or changing a draft requires a new complete review.
- Browser confirmation tests exercise the native-presence transport contract
  with a fictional bridge. They are not proof that the owner clicked an OS
  dialog or accepted the visual design.
- Conversations, staged authority, receipts, reviewed baselines and discovery
  snapshots remain memory-only. Durable retention remains an owner-gated
  privacy-vault decision.
- No provider sessions, credentials, owner configuration or real workspace were
  read. No model/GPU runtime was loaded. The protected Agent launcher remains on
  loopback for the owner's later manual review; no commit or push was performed.
