# Checkpoint 30: bounded workspace inspection and truthful recovery

Status: scoped implementation and automated verification complete. Final
build/resource receipts are recorded below. The single existing privacy-artifact finding
remains open. This checkpoint is not whole-application completion.

## What changed

- Model reads, directory listings, search and editor snapshots use a common
  read-only inspection path. Workspace admission keeps the lexical path rather
  than resolving a junction inserted after the initial check. The admitted root
  identity is rechecked on subsequent inspection.
- Windows opens and holds every component without following reparse points;
  handles are non-inheritable and deny write/delete sharing during inspection.
  Real junction, replacement, cancellation and handle-release tests passed.
  POSIX uses directory-relative descriptors and `O_NOFOLLOW`; this Windows run
  is not a separate Linux/macOS acceptance receipt.
- Reads are bounded before allocation. File identity, size and timestamps are
  checked against the opened handle and after reading. Editor snapshots remain
  strict UTF-8, revision-bound and single-link only. Model text reads reject NUL
  and malformed UTF-8 instead of silently replacing bytes; a valid multibyte
  character cut by a prefix boundary is not invented or corrupted.
- Directory enumeration uses a lazy iterator, not a whole-directory `listdir`.
  Noisy-folder matching is consistently case-insensitive and exclusions are
  applied before descent. Unknown sizes remain unknown. An unreadable folder
  cannot become a successful empty listing.
- Search uses root-anchored glob matching with explicit recursive `**` behavior.
  It does not traverse excluded folders and then filter their results. Entry,
  depth, byte, match, output and cooperative time limits produce explicitly
  incomplete results. Failed reads still consume the byte budget.
- Regex matching has a per-operation timeout. `regex==2026.7.19` is now a core
  dependency; it was already the optional-model transitive version in the lock.
  The lock update adds only that core dependency and its requirement. The
  package declares Apache-2.0 AND CNRI-Python licensing and documents matching
  timeouts and Version 0 compatibility. [Package documentation](https://pypi.org/project/regex/)
- Agent Stop now reaches read/list/search as well as commands. A cancelled
  inspection produces a cancelled tool and stopped turn, with no follow-up
  model request. The versioned `workspace-inspection.v2` policy is included in
  the session prompt, including guidance against treating partial coverage as
  absence or retrying an unchanged refused/timed-out call.
- The file panel no longer calls an incomplete zero-entry response an empty
  folder. Timeouts have a specific retry message. A moved/replaced root retains
  a selectable, read-only draft and blocks further editor mutations until a new
  session/connection. Late old-connection failures cannot lock a replacement
  editor; an already-applied receipt survives a subsequent root/readback error.
- Workspace HTTP calls require private/no-store responses and preserve only
  fixed allowlisted recovery codes. The actual application returns 409 for a
  replaced root and 503 for an inspection timeout. Native per-edit approval,
  same-origin and CSRF requirements remain in force.

The Windows implementation follows the documented no-follow/open/share rules;
no privilege is enabled and no unsafe fallback is attempted. [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

## Inspection limits

| Operation | Bound |
| --- | --- |
| Model file prefix | 96,000 bytes plus one truncation-probe byte; 24,000 returned characters including the notice |
| Editor snapshot | 256,000 bytes; complete strict UTF-8 file required |
| Listing | At most 400 displayed entries, one/two requested levels, 20,000 inspected entries |
| Search | 80 hits, 2,000,000 bytes per file, 16,000,000 total bytes including failed reads, 32 path levels |
| Search/list scan | Five-second cooperative deadline; at most 20,000 inspected entries |
| Regex/query | 50 ms per matching operation; 1,024-character query/glob limits |

Cancellation and scan deadlines are checked between bounded operations. They
are not a promise that a stalled filesystem/kernel call can be forcibly
interrupted. Search covers eligible UTF-8 text; excluded folders, binary data,
link refusal, failures and truncation are not proof of whole-repository absence.

## Verification receipts

- All **16 initial regressions** failed before implementation: false empty/partial
  listings, whole-file reads before truncation, late NUL exposure, inconsistent
  exclusions, unlabelled result limits, missing cancellation, real Windows
  junction traversal and an unbounded pathological regex.
- Additional checks cover admitted-root replacement, actual Windows pinning,
  opened-handle identity, byte/entry/deadline bounds, failed-read accounting,
  glob semantics, invalid patterns, native setup releases and UTF-8 boundaries.
  An initially over-eager display truncation flag was also corrected.
- Current consolidated backend selection: **285 passed / 16 files**, **86.61 s**,
  no skips. Includes all 64 new inspection/service cases, existing Agent/editor,
  command ownership, cancellation, desktop lifecycle, OpenAPI and lock policy.
  The existing Starlette/httpx deprecation warning remains.
- Full frontend: **1,750 passed / 128 files**, **175.14 s**. Includes retained
  drafts, root-change ownership, safe HTTP reasons and private-cache rejection.
- Full synthetic browser suite: **99 passed / 11 files**, about **1.1 min**.
- Full intercepted-HTTP browser suite: **30 passed**, **53.1 s**. The four new
  main/separate cases cover 360/1440 px, incomplete listings, timeout/retry,
  replaced roots, preserved drafts and no editor mutation. Together the two
  browser suites contain **129 distinct cases**; overlapping focused reruns are
  not added to these totals.
- Fixture corrections were kept distinct from product defects: the turn's
  existing terminal label is `stopped` (the tool is `cancelled`); one typed
  fixture needed to allow both complete and incomplete trees; old positive HTTP
  fixtures needed the private response headers the real application supplies.
- Production build, generated API consistency and Python compilation: passed.
  Strict browser TypeScript passed before both full browser suites and again in
  the final unchanged-source recheck. Tracked and new-file whitespace checks pass.
- Privacy scan: **one unchanged finding**, the old synthetic SQLite artifact.
  No exclusion, weakened test, alternate deletion or cleanup bypass was used.

The focused inspection regressions are reproducible with
`pytest tests/test_workspace_read_boundaries.py tests/test_workspace_inspection_service.py -q -p no:cacheprovider --tb=line`
in the project environment. Frontend receipts use `npm test -- --maxWorkers=2 --reporter=dot`,
`npm run test:e2e -- --workers=2` and `npm run test:e2e:local -- --workers=2`
from the frontend directory. Run the two browser suites separately because
they share an output location.

## Review later

1. A genuinely empty folder and an incomplete view with no visible entries must
   have different messages. An unreadable/timed-out folder must offer a truthful
   failure, not an empty success.
2. Retry a temporary folder failure; the file should open normally afterward.
   If the selected root was moved/replaced, copy the draft and create a new
   session. The old editor must remain read-only, not silently follow the new
   directory at the same path.
3. Inspect a large file/search result and check the truncation/incomplete notice.
   Narrow the query or glob when appropriate. `*.py` covers the root;
   `**/*.py` includes eligible nested folders.
4. Stop an inspection. It should finish as stopped/cancelled, not as a completed
   absence claim or a second model request. This checkpoint used no GPU model.

The dev-only `editor-inspection` browser fixture demonstrates the recovery
sequence without real files, models, approvals or network inference. It is not
part of the production bundle or a substitute for native owner acceptance.

## Limits and next work

- This is inspection hardening, not a new command sandbox or certification of
  mutation-phase race safety. Reviewed-write replacement/rollback and the
  editor's mutation lifecycle remain the next bounded audit. Existing approval
  and revision checks must not be mistaken for proof about every filesystem race.
- Conversations/drafts remain memory-only. No retention, model-quality,
  immutable-model-identity, peer-delivery or production-release gap was closed.
- No model was loaded; no real provider content or credentials were used. The
  normal owner app was not restarted. Existing working-tree changes were
  preserved, and no commit or push was performed.
- The historical broad backend snapshot remains 4,070 passes, nine platform
  skips and one known privacy-artifact failure. It is not a current all-green
  full-backend receipt. The original [verification ledger](goal-verification-ledger-2026-08-26.md)
  remains open.

Final in-app review: the complete incomplete → timeout → retry → file-open →
replaced-root sequence passed. All 37 draft characters could be selected while
the editor stayed read-only; mutation buttons remained disabled and the page
did not overflow. A fixture hot reload reset one intermediate review, so that
review was restarted from its observed initial state rather than counted as
an application failure. The owned tab was closed; the viewport was unchanged,
and no screenshot was saved to the repository.

Owned-resource check: zero model-runtime processes and no HTTP-test listener
remained. The pre-existing loopback development listener was preserved. The
normal owner application was not running and was not restarted by this work.
