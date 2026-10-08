# Collaboration workflow

How invited contributors and the owner work together. The owner keeps final
control: contributors propose changes on feature branches, and only the owner
merges to `main`. This page is a working guide, not a status ledger; progress
and approvals live in GitHub issues and pull requests.

Read [CONTRIBUTING.md](../CONTRIBUTING.md) and `AGENTS.md` first. The privacy
rules there apply to every branch, commit, issue, comment, and pull request.

## Read this before starting: the baseline

`main` may not contain all of the latest reviewed pilot work. Do not assume a
partial `main` includes every recent feature, fix, or test. Before you begin a
task, the task card names the baseline it depends on; if that baseline is not
yet on `main`, stop and ask the owner. Do not copy files from anywhere other
than the task card's baseline.

## Roles

| Role | Owns | Does not do |
| --- | --- | --- |
| Owner and supervisor | Core metrics, model runtime, approval and security behavior, schema and release decisions, task assignment, review, merge | Delegate merge or approval decisions |
| UI contributor | Frontend: radar, session selection, menus, accessibility, using synthetic API fixtures | Change backend metrics, schema, or approval behavior |
| Persistence and testing contributor | Project and chat create/read/update/delete, restart recovery regressions, isolated fixes | Add migrations without owner review |

People are assigned to roles in GitHub issue metadata by the owner. Do not
write names, handles, or account identifiers in code, tests, docs, branch names,
or commit messages.

## Start workflow

1. Work in your own clone (or fork). Never work directly on `main`.
2. Fetch `main` and branch from it: `feature/<task-slug>`.
3. Make small, scoped commits. Do not reformat files unrelated to the task.
4. Open a draft pull request early if drafts are available. If they are not on
   the current plan, open a normal pull request marked WIP (in the description,
   so the title still passes the title check) and do not merge it. Draft
   availability is not guaranteed.
5. Add tests as proof, using only synthetic fixtures (see below).
6. Mark the pull request ready only after the owner has accepted the work
   against the acceptance criteria.
7. The owner reviews and squash-merges. Address review comments with new
   commits on the same branch.
8. After the merge, sync your clone with `main` and delete the finished branch.

Reference the task in the pull request as `Refs #<issue number>`. Do not use
closing keywords; the owner updates status and closes the task.

## Branch and title rules

The `Collaboration policy` check validates only metadata, never content:

- the pull request targets `main`;
- the branch is `<prefix>/<slug>` with prefix `feature`, `fix`, `docs`, `test`,
  `refactor`, `chore`, `ci`, or `release`, and a lowercase slug of letters,
  digits, `-`, and `.` (no spaces, leading dash, or shell characters). The
  legacy `codex/` prefix is accepted for existing campaign work only;
- the title is a single line of at most 200 characters in Conventional Commits
  form: `type(optional-scope)!: description`, with type `feat`, `fix`, `docs`,
  `test`, `refactor`, `chore`, `ci`, `build`, `perf`, or `style`.

Pull requests from forks are checked the same way. The check reports only fixed
error codes, never the title or branch text. It does not read the description,
decide whether a task was approved, or judge quality; those are human decisions.

## Hard limits for every contributor

- Keep the pull request narrow: one task, only the files the task allows.
- Do not force-push `main`, and do not rewrite history others have fetched.
- Do not change tests, golden files, unknown/missing-value handling, approval
  behavior, or model budgets unless the task card says so. A failing test is a
  finding to report, not something to loosen.
- Never run tests that use private sessions or provider data. Use synthetic
  fixtures, temporary databases, and test processes your test itself starts and
  owns.
- No real transcripts, prompts, source snippets, screenshots, paths, hostnames,
  emails, tokens, or account identifiers anywhere.
- No auto-merge, no personal or account tokens in workflows, no secrets in the
  repository.
- AI coding agents follow `AGENTS.md`, the same branch naming, and the same
  scope as human contributors, and do not merge their own work.

## Evidence levels

State the highest level actually reached on every task card and pull request,
and do not claim a higher level than you ran. Every level uses synthetic data:

- **Not verified**: nothing was run.
- **Static review only**: read and reasoned, no automated proof.
- **Unit**: automated unit tests with synthetic fixtures pass.
- **Integration**: automated tests across components with synthetic fixtures
  and temporary databases or test processes that the test starts and owns.
- **Browser**: the frontend was run in an actual browser (automated or manual)
  against synthetic data only. Browser-like, jsdom, component, or mock-based
  tests are not browser evidence; record them as Unit or Integration evidence.
- **Packaged**: a built or packaged artifact was run against synthetic data.
- **Native/real-model**: a native app journey or an actual model load, run only
  by the owner as a separate bounded, authorized qualification.
- **Clean-machine**: an install and first run on a clean machine, run only by
  the owner.

The last two levels are owner-run. Contributors do not need, and may not use,
private provider sessions, real transcripts, or personal models to reach any
level, and are never expected to reach the owner-run levels. Owner inspection of
private data is not a substitute for native or install acceptance.

An assistant's statement that work is complete is not evidence.

## First task cards

These are the starting points. The owner creates the actual issues from the
task template, assigns people, and may adjust scope.

### Task 1: Model memory allocation diagnostics (owner)

- **Observed blocker:** a genuine 8B model load ended `resource_exhausted`
  under a 6 GiB framework CUDA budget. The exact cause (CPU RAM, GPU VRAM, or
  the framework's own reason) is still unverified.
- **Result:** safe, read-only classification and provenance diagnostics for
  model memory allocation, with synthetic regression tests. Observed memory is
  kept distinct from estimates, each value carries its source, and anything
  not measured stays unknown, never zero.
- **Allowed files:** set by the owner after confirming the exact code paths
  against the approved baseline. Candidates, not blanket permission, are
  `src/prompt_enhancer/infrastructure/text_models/loader.py`,
  `transformers_backends.py` in the same directory, and `run_control.py`.
- **Unchanged:** metric definitions, stored values, missing-data behavior,
  model budgets, and any personal model, which is never stopped by this work.
  This is not a token or metric allocation task and has no owner-input blocker.
- **Acceptance:** synthetic tests for classification and provenance. No model
  is loaded or run for this task. Any actual load needs a separate bounded,
  authorized qualification by the owner.
- **Dependencies and stops:** depends on the shared reviewed baseline. Stop if
  the work would change a budget, a metric definition, or load a model.

### Task 2: Radar missing/stale state, viewport, and session selector (UI contributor)

- **Result:** the radar shows a clear "no data" or "stale" state instead of an
  empty or zero-filled chart, lays out correctly across viewport sizes, and the
  session selector keeps the chosen session across refresh.
- **Allowed files:** may include `frontend/src/features/live-window/`,
  `frontend/src/features/session-radar/`, and
  `frontend/src/features/session-catalog/` plus their frontend tests and
  synthetic API fixtures, subject to the exact files the owner approves.
- **Unchanged:** API contracts, generated client, backend behavior, and how
  unknown values are represented.
- **Acceptance:** a frontend test per state (missing, stale, resized,
  selection kept) using synthetic data, and the existing frontend suite passes.
- **Dependencies and stops:** the shared reviewed baseline. Stop if a fix needs
  an API or schema change.

### Task 3: Synthetic chat and project CRUD, restart, archive, restore (persistence and testing contributor, to be assigned)

- **Result:** synthetic-fixture tests covering project and chat create, read,
  rename, delete, archive, restore, and survival across an application restart,
  plus isolated fixes only for failures those tests expose.
- **Allowed files:** new test files and fixtures, plus the narrowest code change
  that fixes a proven failure. The owner confirms the exact list.
- **Unchanged:** database schema and migrations, existing tests, and stored
  data formats.
- **Acceptance:** each operation has a test against a temporary database that
  the test creates and removes. Reopening a synthetic database is integration
  evidence only. It is not proof of an actual app restart or native journey,
  which is owner-run, and no real user data is touched.
- **Dependencies and stops:** the shared reviewed baseline. Stop and ask before
  any change that would need a migration.

## Owner configuration

The repository is private and personal. GitHub Free is enough for ordinary
feature branches and pull requests. Private-repository protections need a
personal Pro plan or an organization Team plan. The branch protection and
ruleset interfaces currently refuse these settings on the free plan, so **no
remote protection is active today**. The workflow files here run as normal CI,
but on a private repository without protection they are advisory: a branch can
edit a workflow and push to `main` directly. Nothing in this repository
enforces owner-only merge until the settings below are applied.

Prerequisite (currently blocked): a plan or repository arrangement that
supports enforced branch rules for this repository. Purchasing a plan, changing
repository visibility, or transferring the repository is the owner's deliberate
decision. Agents never do any of these.

When the prerequisite is met, the intended settings for `main` are:

- require a pull request, with at least one approving review;
- dismiss stale approvals on new commits, and require review of the most recent
  push;
- require conversation resolution before merge;
- require these successful checks: `Repository integrity`,
  `Backend (ubuntu-latest)`, `Backend (windows-latest)`, `Frontend`, and
  `Collaboration policy`;
- block force pushes and deletion; leave auto-merge off;
- protect release tags, and keep signing material and publishing credentials in
  an owner-controlled, separate location rather than this repository.

Keep two rules apart:

1. **Owner-only merge**: a restriction on who may merge, enforced through a
   repository ruleset that grants the merge permission to the administrator
   role only.
2. **Quality checks with no bypass**: the required checks and review rules
   above must not list any bypass actor, so being allowed to merge does not let
   the owner skip a failing check.

### Bootstrap limitation for the first pull request

`Collaboration policy` runs the validator from the pull request's base commit,
never from the pull request's own code. The base-only validator does not yet
exist in `main`, so for the first pull request that introduces it this check
cannot be green. It is expected to be blocked or failing, and is reported as
unverified, not passed. Do not add a skip-as-success path, do not run code from
the pull request head to make it pass, do not weaken these trust boundaries, and
do not enable auto-merge.

The owner reviews and merges the bootstrap deliberately. Only after the workflow
and validator are on `main` does the owner add `Collaboration policy` as a
required check. Enabling it earlier would block every pull request.

Limits to keep in mind:

- Code review assignment by file ownership is a review routing aid, not a folder
  access control, and this repository does not configure it.
- Contributors who can open pull requests can read the source they clone. Nothing
  here prevents copying readable source; do not rely on these settings to
  protect it.
- The exact settings and API calls are applied and read back by the supervisor
  after checking the actual plan. They are not recorded here as active until that
  has been verified.
