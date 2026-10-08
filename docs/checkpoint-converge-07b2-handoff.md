# Converge-07b.2 handoff — deterministic public build-manifest boundaries

Status: **C07b.2 offline manifest-verification slice complete after the owning
gates.** This checkpoint remains separate from C07b.1 update-root security and
does not claim publisher verification, package installation or release-ready
artifacts.

## What this slice closes

- Public build manifests reject duplicate paths, case-insensitive collisions and
  file/directory prefix conflicts instead of silently losing entries during
  comparison.
- Staged names must be normalized portable relative paths. Dot segments,
  duplicate separators, backslashes, alternate data streams, trailing
  dot/space names and other Windows-ambiguous components are refused.
  The path policy follows Microsoft's [Windows file and directory naming
  guidance](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).
- Tree inspection rejects hardlinked leaves and other non-ordinary entries,
  checks bounded collection sizes and metadata, and hashes each accepted source
  leaf once while checking observed pre/post file and directory metadata. This
  is not an atomic filesystem snapshot or proof against a same-user attacker
  race. Rejected trees remain untouched.
- Canonical output remains deterministic and host-path free. The CLI emits only
  the generic `build_manifest_failed` error for invalid synthetic input.

All fixtures use temporary directories, reserved synthetic names and bytes. The
acceptance tests and tools under validation made no network egress and did not
use a restart, relaunch, install, process kill, model, provider, real
home/configuration or release publishing.

## Focused evidence

`tests/test_build_manifest_07b2_acceptance.py` passes **17/17**:

```text
uv run pytest tests/test_build_manifest_07b2_acceptance.py -q --tb=short -p no:cacheprovider
17 passed
```

The suite covers deterministic equivalent trees, duplicate/casefold/prefix
ambiguity, normalized and Windows-ambiguous names, hardlink rejection without
source mutation, bounded source reads, collection and required-metadata bounds,
and content-free direct CLI failure. The owning C07b.2 gate is **172 passed,
1 skipped** (the explicit Windows symlink-fixture capability skip) in 10.68s
across the selected build/distribution/private-root/updater/replay/config,
privacy and scanner files. This focused file is an overlapping subset, not an
additional count.

No frontend, browser, API-contract, build-output or app-reload gate was rerun
for this isolated offline tool change under the active remote-session
restriction. Privacy scanning and `git diff --check` passed.

## Explicit non-claims and next gate

This is not Windows publisher or signing evidence and does not make an artifact
distributable. Native package publisher/MSIX handoff, installation, exact
process handoff, relaunch/recovery, rollback, power-loss protection and owner
acceptance remain open under C07. The active remote-session restriction also
continues to prohibit PC/app restart or install until explicit owner approval.
