# Checkpoint Release-01a.3 entry: exact process ownership

Date: 2026-09-02

This checkpoint closes the remaining process-tree and visible-console failure
windows before any updater is allowed to stop or relaunch the application. It
uses only synthetic commands, paths, model stand-ins and protocol messages.

## Frozen lifecycle contract

| Boundary | Required behavior | Forbidden behavior |
| --- | --- | --- |
| Windows child startup | Assign the suspended root process to a kill-on-close Job Object before its first instruction, then resume it | Starting a process first and trying to attach or kill descendants afterward |
| POSIX child startup | Create one owned process group and signal only that exact group | Broad name matching or unrelated process termination |
| Helper inventory | Route every model, estimator, schema, transport, session-link and compatibility helper through a reviewed ownership adapter | Direct unmanaged `Popen`, `taskkill.exe`, or `CREATE_NEW_CONSOLE` in helper code |
| Resource bounds | Apply a finite descendant cap and bounded stdin, stdout and stderr handling | Unbounded output capture, unbounded descendants or pipe deadlock |
| Completion | Claim success only after the root, descendants, pipes, reader threads and native handles are settled | Root-only exit as proof that the tree is gone |
| Failure | Return fixed content-free timeout, launch and cleanup states | Leaking commands, paths, model output or operating-system error prose |
| Listener collision | The second server attempt exits while the original hidden tree remains the sole loopback listener | Recursive windows, a second listener or takeover of the live instance |

## Required evidence

1. Unit tests for output bounds, process caps, start failure, timeout and exact
   cleanup uncertainty.
2. Static AST policy proving every helper uses the shared owner and forbidding
   `taskkill.exe` and `CREATE_NEW_CONSOLE`.
3. Existing command, model, MCP, estimator, schema and transport regressions.
4. Complete backend and frontend suites, API compatibility, production build,
   compilation and privacy scan.
5. A hidden live startup plus listener-collision and owned-tree census without
   loading a real model or reading application content.

## Out of scope

- Release-01b.1 signed update discovery, download and staging.
- Release-01b.2 reviewed installer apply, relaunch and rollback.
- Release-01b.3 packaged install/update/shutdown parity.
- Owner-only native clicks, real model placement and VRAM evidence.
