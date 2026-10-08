# MCP Store checkpoint 05b handoff

## Outcome

The MCP Store can now install one exact, checksum-pinned MCPB release package
after an exact revision-bound preview and one native user-presence confirmation.
The artifact is downloaded through a public-DNS-pinned HTTPS boundary, verified
before extraction, staged under the application-owned package root, checked with
one hidden owned stdio process, and atomically published only after the complete
process tree is verified stopped.

Installation still grants no Agent tool authority. It does not retain an MCP
host or connection, call a tool, persist tool names/schemas, or place package
paths, commands, arguments, environment values, or manifest content in the
application database or API. Persistent hosting and project tool admission
remain Store-06.

## Exact supported package boundary

- Only Official MCP Registry options with `registryType: mcpb`, stdio transport,
  a declared lowercase SHA-256 digest, no Registry-declared runtime/package/env
  inputs, and an exact GitHub or GitLab release URL ending in `.mcpb` are
  installable in this checkpoint.
- npm, PyPI, NuGet, OCI and other ecosystems remain explicitly unsupported until
  registry-specific lock, integrity and execution adapters exist. They are not
  silently treated as MCPB files.
- The Registry plan is fetched again immediately before installation. Changed
  plan revision, option identity, checksum or hidden execution material fails
  before download or mutation.
- The implementation follows the official
  [MCPB manifest contract](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
  and [MCPB package format](https://github.com/modelcontextprotocol/mcpb/blob/main/README.md),
  but deliberately supports a narrower execution subset for this first local
  installer.

## Download, archive and runtime isolation

- Downloads are HTTPS-only, proxy-free, bounded to 64 MiB and pinned to public
  DNS answers on every redirect hop. Initial origins are GitHub/GitLab release
  pages; redirects are limited to four and to their release-asset host families.
- SHA-256 is checked before the archive is opened.
- Extraction rejects traversal, absolute paths, backslashes, Windows alternate
  data stream syntax, device names, trailing dot/space names, encrypted members,
  symlinks/reparse points, non-regular files, duplicate/case-colliding paths,
  unsupported compression, compression bombs, excess entries and excess files.
- Expanded data is bounded to 256 MiB, each file to 32 MiB, and the manifest to
  256 KiB.
- MCPB manifest versions 0.3 and 0.4 require a declared license. Packages that
  need `user_config`, platform overrides, UV, unsupported commands, or unbounded
  substitutions remain unavailable rather than being guessed.
- Node, Python and binary entry points are exact and shell-free. Runtime and
  platform constraints are checked before the MCP process is started.
- The compatibility process runs through the existing console-free owned-process
  boundary. It performs only initialize and bounded tool-schema inspection. The
  whole process tree must be verified stopped.
- The staged tree is hashed again after the probe. A package that modifies its
  own staged files is rejected and never published, closing the pre-probe digest
  time-of-check/time-of-use gap.

## Durable state and recovery

- Agent catalog schema 15 adds `mcp_managed_local_packages`, containing only
  request binding, artifact/tree/manifest digests, byte count, manifest/runtime
  identity, content-free probe evidence, cleanup truth and timestamps.
- Successful installation persists the exact plan revision, install time,
  package evidence, closed probe receipt and verified process-tree cleanup in one
  transaction.
- Request IDs are idempotent. Replaying the same completed request returns the
  retained receipt without downloading, probing or publishing again.
- Clean failures remove the pending operation and leave the reviewed plan ready
  to retry. Uncertain process or staging cleanup moves the record to an explicit
  `cleanup_required` state.
- On restart, any crash-left `installing` row becomes `cleanup_required` with an
  `mcp_package_install_interrupted` content-free error. The app does not pretend
  the package is installed or safe to retry.
- If database commit fails after publication, rollback is permitted only when
  the installed tree still matches the exact expected digest.

## Agent experience

- Lifecycle preview shows the exact download, SHA verification, isolated staging,
  compatibility process, process-tree cleanup and atomic publication effects
  before native confirmation.
- Unsupported registry, missing integrity, unsupported transport, missing
  configuration, unavailable installer, cleanup-required and in-progress states
  have distinct reasons and disabled actions.
- Installed MCPB records show path-free artifact, tree and manifest digests,
  artifact size, MCPB manifest version, declared-license state, runtime identity
  and process-tree cleanup evidence.
- The screen explicitly distinguishes an installed package from a running host.
  The host remains `not_started` and tool routing remains `inactive`.
- Local uninstall is intentionally unavailable and labelled as Store-05c work;
  it is never presented as a working button.

## Automated evidence

- Installer, Registry resolution, durable management, guarded host and restart
  matrix: 91/91 passed, including the post-probe tree-integrity regression. The
  dedicated installer suite is 10/10 and the server-management subset is 24/24.
- Strict frontend managed-server parser, HTTP transport and MCP Store UI: 40/40
  tests passed, including a complete synthetic MCPB install transition and
  rejection of incoherent runtime/cleanup evidence.
- The final Store-panel wording regression is 16/16: the live introduction now
  advertises only exact checksum-pinned MCPB stdio installation and no longer
  repeats the obsolete Store-05a claim that every local install is locked.
- Complete frontend suite: 170/170 files and 2,305/2,305 tests passed.
- OpenAPI export suite: 6/6 passed. Generated TypeScript was regenerated from the
  current schema and strict TypeScript project compilation passed.
- Broader Agent catalog/release/OpenAPI/privacy/native-lifecycle regression
  matrix: 77/77 passed, including historical schema migration replay.
- Production TypeScript/Vite build passed with 559 modules. The existing
  approximately 507 kB minified Agent-page chunk remains a later bundle-budget
  advisory, not a failed correctness gate.
- Repository privacy scan and `git diff --check` passed. All package, endpoint
  and process fixtures are synthetic; no real MCP package, credential, owner
  workspace, provider session,
  tool schema/result or tool call was used.

## Live reload and runtime inventory

- The existing protected Agent was closed through its own native quit
  confirmation, and its window and listener were verified absent before one
  console-free replacement was launched. No force-kill or duplicate launcher
  was used.
- The production frontend was rebuilt and reloaded in that native window. The
  live **Agent settings → MCP Store** surface showed 24 Official Registry
  entries plus the corrected exact-MCPB install boundary and verified-local-
  package summary.
- `/health` and the HTML Agent entry returned HTTP 200. Final inventory found
  exactly one Agent window, one listener on `127.0.0.1:8765`, no non-loopback
  listener on that port, no listener on 8766, zero terminal processes in the
  app-owned tree, and zero known local-model workers.
- No model or MCP package was started for this reload, so no checkpoint-owned
  model allocation remains in GPU memory.

## Owner review checklist

After reload, open **Agent settings → MCP Store**:

1. Open a prepared local-package plan and confirm unsupported npm/PyPI-style
   options explain that only checksum-pinned MCPB releases are currently
   installable.
2. If an exact MCPB option is listed, review its lifecycle preview. It must show
   download, SHA-256 verification, staging, one compatibility process, verified
   process-tree stop and atomic publication. Do not approve an unfamiliar
   third-party package merely to exercise the UI.
3. On an installed synthetic/test record, confirm the evidence card shows
   digests, size, manifest/runtime identity and `verified` cleanup while Host is
   `not started` and Tool routing is `inactive`.
4. Confirm installed local-package removal is disabled and names Store-05c,
   while remote activation/deactivation continues to work as before.

## Exact next checkpoint

**Store-05c — update, uninstall, rollback and cleanup recovery.** Add
revision-bound update discovery, digest-bound replacement, safe uninstall,
rollback receipts, application-owned staging cleanup, and recovery actions for
interrupted/uncertain operations. Persistent hosting and tool authority remain
locked until Store-06.
