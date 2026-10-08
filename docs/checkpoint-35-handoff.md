# Checkpoint 35: bounded selected-folder and Git discovery

Status: scoped implementation and automated verification complete. The whole
application remains open against the verification ledger. The single existing
privacy-artifact finding remains open.

## What changed

- Every active Agent session now exposes one current
  `local-agent-workspace-discovery.v1` snapshot through an authenticated
  private/no-store loopback read.
- The application recursively inventories regular application-readable files
  through the existing no-follow workspace boundary. It returns relative paths,
  byte sizes and editor eligibility only; file content, revisions and hashes do
  not enter this response.
- Inventory is bounded to 20,000 inspected entries, 32 levels, five seconds and
  400 displayed files. Excluded directories, links/reparse points, unavailable
  or unrepresentable entries, depth, deadline and capacity limits are fixed
  partial-coverage reasons. Incomplete zero rows are not labelled empty.
- A supported repository must have a real `.git` directory exactly at the
  selected root. Gitfile/worktree layouts, common-directory pointers, object
  alternates, config includes, `core.worktree` redirects and repository-local
  diff/filter/merge helper sections are refused before Git starts.
- Git status uses direct argv and bounded process-tree cleanup with prompts,
  pagers, optional locks, lazy object fetching, external diffs, renames,
  submodule recursion and global/system config disabled. No fetch, remote or
  shell is involved.
- Porcelain-v2 output is validated into at most 400 unique relative paths and
  fixed change kinds. Branch, commit, object hashes, remotes, absolute paths,
  stderr, invalid output and truncated output are never returned.
- Repository/root replacement, another command, uncertain command cleanup,
  missing Git, deadline, nonzero exit and unsupported layout remain distinct
  content-free states. A replaced selected root retains the existing session
  authority error instead of becoming a harmless non-repository claim.
- The Agent manual-workspace pane now begins with a responsive **Workspace
  discovery** card. It shows exact coverage and counts, fixed warnings, a path
  filter, editor-safe open actions and a separate Git status list. It refreshes
  after settled turns and confirmed manual writes, aborts stale reads and drops
  previous data on failure.
- Discovery remains observational. The reviewed change set and revision-bound
  preview/apply flow remain the only source of reviewed publication authority.

## Defects reproduced and repaired

- The first dedicated test could not import a discovery module or call a
  discovery endpoint. The missing bounded contract/service/route/transport/UI
  slice was implemented rather than inferred from the existing one-folder tree.
- The initial Git check caught `FileNotFoundError` around both root and `.git`
  identity. A removed selected root could therefore be called “not a
  repository.” Root identity and repository identity are now checked
  separately, with a second root check before any non-repository result.
- A root-replacement `workspace_root_changed` error was initially collapsed
  into `repository_layout_unsupported`; repository metadata replacement after
  Git could also surface a lower-level link error. Root authority is preserved,
  while post-command repository uncertainty discards every output byte and
  returns `repository_changed`.
- Rooted Git can normally consult config includes, worktree/common-directory
  pointers and alternate object stores. Those on-disk indirections are now
  conservatively refused, and global/system config plus lazy fetching are
  disabled. Synthetic regressions prove Git is not spawned for each refused
  layout.
- Repository-local clean/process filters and other diff/merge helper sections
  can name external programs. Both current quoted subsections and Git's legacy
  dotted subsection syntax are now refused before process start; dedicated and
  full-gate regressions cover that boundary.
- Duplicate porcelain paths could reach model validation instead of becoming a
  fixed invalid-status state. They are now rejected in the parser and all Git
  output is discarded.
- The first browser contract used locale-sensitive case comparison for path
  ordering, which did not match a portable server order. Both sides now use
  deterministic UTF-8 byte order, reject unpaired surrogates and test a
  non-BMP ordering case.
- Discovery failures originally risked leaving a prior result visible or a late
  session-A result under session B. The card clears first, owns one abort signal,
  validates session identity and tests refresh, retry, transport and session
  replacement.
- A discovery-proven root replacement initially affected only the new card.
  The parent editor now receives that authority signal, clears its tree and
  locks file operations while preserving any copyable draft.
- The first complete browser pass found an ambiguous test locator because both
  the map and folder tree intentionally expose an `example.ts` action. The test
  now selects the exact folder-tree control; the accessible map controls retain
  distinct `Open …` names.

## Verification receipts

- Dedicated backend discovery and HTTP contract: **21 passed**, including a
  real synthetic `git init` repository and fixed failure/race/layout cases.
- Adjacent Agent/workspace/command/runtime/OpenAPI selection: **293 tests** in
  the final generated-schema state. An earlier 292-pass run correctly failed
  only the byte-exact OpenAPI assertion after the last numeric bound changed;
  regeneration and the final gate close that expected drift.
- Focused discovery, workspace, Agent-page and transport frontend checks passed
  **262 tests / 5 files**; the frozen full frontend gate passed **1,810 tests /
  133 files**. One first-run
  unrelated team-analytics timeout passed alone and the unchanged complete suite
  then passed.
- Browser acceptance passed **105 synthetic workflows** and **31 intercepted
  loopback/HTTP workflows**. The HTTP flow filters the map, applies a fictional
  natively confirmed edit, observes the automatic Git refresh from zero to one
  unstaged modification and preserves the separate reviewed-change-set proof.
  Narrow/main/dedicated workspace flows retain draft and overflow assertions.
- The production frontend build, generated API consistency, OpenAPI export,
  Python compilation and whitespace gate pass.
- The frozen backend gate covered all **277** `test_*.py` files in four disjoint
  cache-free shards: **4,240 passed, 9 skipped, 1 failed**. Exact receipts were
  1,036 passed / 1 skipped / 1 failed in 487.01 s; 756 passed in 451.41 s;
  1,118 passed / 6 skipped in 567.17 s; and 1,330 passed / 2 skipped in
  811.84 s. The nine skips are unavailable Windows symlink capabilities. The
  sole failure is the unchanged repository privacy assertion for
  `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`.
- The standalone privacy scanner reports that same one prohibited artifact and
  no new finding. It remains a failure; no exclusion, scanner weakening or old
  fixture deletion was used.
- Final cleanup removes only checkpoint-owned Playwright output after exact
  target/reparse inspection. Zero test workers and zero model runtimes remain;
  the pre-existing 4173 development listener is preserved. No model was loaded.

## Explicit limits and next work

- “Complete” means complete within the documented application-readable bounds,
  not an unrestricted filesystem index. Protected/generated directories and
  links remain excluded and visible as partial coverage.
- The Git view supports an ordinary repository rooted at the selected folder.
  Linked worktrees, submodules as inspected repositories, external object stores
  and config indirections fail closed; this feature is not an OS sandbox for an
  arbitrary Git executable.
- Git observation does not grant reviewed authority. Command-created and
  external changes remain Git changes unless they separately pass the existing
  review/publication boundary.
- This is not an atomic multi-file editing transaction, rename/move/delete UI,
  rich syntax editor, durable shell or durable Agent history.
- Conversations, receipts, reviewed baselines and discovery snapshots remain
  memory-only. Durable retention remains an owner-gated privacy-vault decision.
- Native folder selection and protected-action clicks still need owner presence.
  Browser confirmation is fictional composition evidence, not an OS-dialog
  acceptance result.
- No provider sessions, credentials, owner configuration or real workspace were
  read. No model/GPU runtime was loaded. The owner app was not restarted, and no
  commit or push was performed.
