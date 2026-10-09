# CI quality gate

Checkpoint 9A keeps the repository's synthetic release checks reproducible on
pull requests and pushes. The workflow has read-only repository permission,
does not receive repository secrets, and does not upload test or runtime
artifacts. Tests remain subject to the suite-wide non-loopback socket guard.

## CI ownership

| Job | Platform | Required commands and evidence |
| --- | --- | --- |
| Repository integrity | Ubuntu | `python scripts/privacy_scan.py`; `python scripts/render_architecture_atlas.py --check`; event-range `git diff --check` |
| Backend | Ubuntu and Windows | `uv lock --check`; `uv sync --frozen --extra dev`; frozen `uv run` compilation, platform security preflight, and full pytest |
| Frontend | Ubuntu, Node.js 24 | `npm ci`; `npm test`; `npm run check:api`; `npm run build`; `npx playwright install --with-deps chromium`; `npm run test:e2e` |

Every external GitHub action is pinned to an immutable commit SHA. Adjacent
comments retain the reviewed release tag so dependency updates remain explicit
and auditable instead of following a mutable major-version ref. Checkout also
sets `persist-credentials: false` in every job. Backend dependency caching and
installation are keyed by the committed `uv.lock`; uv 0.10.4 refuses lock drift
through `uv lock --check`, then `--frozen` prevents any gate command from
updating the lock.

The workflow does not pin test totals or platform skip totals. Tests may grow,
but every command must exit successfully. The explicit security preflights also
parse their synthetic JUnit summaries and fail if an owned test is skipped:

- Ubuntu owns the file-link, directory-link, hard-link, state-root, model-cache,
  quarantine, social-database, and privacy-scanner link boundaries in
  `test_database_symlink.py`, `test_local_model_provenance.py`,
  `test_local_text_model_evaluation.py`,
  `test_quarantined_local_file_reader.py`, `test_scanner_symlink.py`,
  `test_social_sqlite_boundary.py`, and `test_symlink_home.py`.
- Windows owns the subprocess-tree cleanup contracts in
  `test_windows_tree_cleanup_requires_successful_taskkill_and_root_exit` and
  `test_windows_accelerator_cleanup_does_not_bless_a_surviving_descendant`.

This division ensures that a capability skip on one operating system does not
silently remove the security contract from the checkpoint.

## Local parity

The architecture check verifies the generated catalog, SVGs and layout data
against the reviewed atlas. PNG bytes remain covered by exact privacy-scanner
hash pins. It does not infer feature readiness or replace application tests.

From the repository root, use a supported Python runtime and run:

```console
uv lock --check
uv sync --frozen --extra dev
uv run --frozen --extra dev python -m compileall -q src tests scripts
uv run --frozen --extra dev python -m pytest
python scripts/privacy_scan.py
git diff --check
git diff --cached --check
```

Then run the locked frontend gate:

```console
cd frontend
npm ci
npm test
npm run check:api
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

Linux parity for the link-boundary preflight is:

```console
uv run --frozen --extra dev python -m pytest -q tests/test_database_symlink.py tests/test_local_model_provenance.py tests/test_local_text_model_evaluation.py tests/test_quarantined_local_file_reader.py tests/test_scanner_symlink.py tests/test_social_sqlite_boundary.py tests/test_symlink_home.py
```

Windows parity for the taskkill preflight is:

```console
uv run --frozen --extra dev python -m pytest -q "tests/test_chunked_model_ensemble.py::test_windows_tree_cleanup_requires_successful_taskkill_and_root_exit" "tests/test_model_compatibility_catalog.py::test_windows_accelerator_cleanup_does_not_bless_a_surviving_descendant"
```

All fixtures and output must remain fictional and synthetic. These gates do not
authorize reading provider sessions, transcripts, credentials, local
configuration, or unrelated machine state.

## Outside this checkpoint

Live-provider/browser validation, dependency auditing, SBOM/signing, installer
production, and owner-led UI card review remain separate checkpoints.
