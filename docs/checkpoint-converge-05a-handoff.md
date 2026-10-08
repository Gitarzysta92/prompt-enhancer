# Converge-05a handoff — trusted MCP lifecycle evidence

Status: automated acceptance instrumentation complete on 2026-09-04; packaged
trusted-MCP execution pending; Converge-05 is not complete

## Outcome

The managed MCP plan now contains a page-owned, fail-closed acceptance ledger
for one exact trusted local MCPB lifecycle. It observes receipts from the normal
Store, project-tool, runtime and Agent-chat controls; it never performs a
protected action itself.

One run is bound to the exact managed server, project, live chat, plan and server
revisions, reviewed tool snapshot, admitted tool identities and started host
instance. It requires this ordered sequence:

1. clean, reviewed and install-ready MCPB baseline with no current or rollback
   package evidence;
2. exact package install plus isolated probe and verified process cleanup;
3. exact project permission and reviewed-tool admission;
4. hidden local host ready with project-scoped, fresh-per-call approval;
5. one post-host-start model-requested MCP call in the same chat, with native
   approval, successful content-free receipt and verified cleanup;
6. host stop with process, lease and routing cleanup verified;
7. exact Registry update with one verified rollback generation retained;
8. no-process rollback to the original reviewed plan;
9. verified removal of the now-superseded rollback generation; and
10. uninstall with no installed or rollback package, host, routing, snapshot,
    connection or tool authority remaining.

The ninth step is intentional. An update and rollback retain a second verified
generation by design. Uninstalling the current package alone is not proof that
the retained generation was removed, so the ledger cannot skip its separate
cleanup receipt.

Old events cannot satisfy the tool-call step: a successful host start raises the
event floor to the current chat head. Cross-project, cross-chat and different-
server evidence is ignored. A future action on the bound server, malformed
receipt, denied call, unverified cleanup, changed plan/snapshot or incomplete
authority release invalidates the run instead of silently reordering it.

The receipt remains available when Agent settings or the Store view closes,
because it is owned by the Agent page rather than the settings panel. It remains
memory-only and clears on application reload. It stores no prompt, arguments,
results, credentials, paths, package bytes, endpoint material or process output.

## Current automated evidence

- Focused MCP acceptance, Store, managed-plan, runtime, project-tool and activity
  components: **77/77 passed** across seven files.
- Complete Agent feature suite: **569/569 passed** across 34 files with one
  worker.
- Responsive Agent/workspace/MCP browser matrix: **89/89 passed** with one
  worker; the final acceptance-panel layout was also rerun at 360 and 1440 px.
- Intercepted frontend/HTTP contract matrix: **41/41 passed** with one worker.
- Production-built, zero-interception real-loopback matrix: **16/16 passed**.
  Shutdown released its disposable listener, removed temporary state, confirmed
  runtime cleanup and left **0 model runtimes**.
- Desktop lifecycle, native-window, folder-picker, local-model, command,
  artifact and owned-process backend group: **145/145 passed** through the
  locked project environment.
- TypeScript project check, production build, generated API drift check,
  repository privacy scan and whitespace check: passed.
- Final content-free local census: **0** known local-model processes, **1**
  pre-existing loopback listener on port 8765 and **0** on 8766. The open owner
  application was not restarted or modified.

The browser and real-loopback runs use reserved-example synthetic data. They did
not install an MCP package, load a model, call a real tool or touch the owner's
open application.

The production build still reports its existing chunk-size warning: the Agent
page bundle is about 626 kB minified. This does not invalidate lifecycle
correctness, but code splitting remains explicit performance debt for the final
release gate rather than being relabelled as complete here.

## Still owner-gated and unproven

Converge-05a is not owner-accepted until a deliberately chosen trusted package
is exercised in the packaged native application. The package must be an exact
checksum-pinned MCPB release whose reviewed current version has a newer exact
Registry version available; otherwise the update step truthfully cannot run.

The following remain unproven on the owner machine:

- native review and approval dialogs for every authority-increasing action;
- real install/probe/start/call/stop behavior for the selected third-party MCPB;
- real package update, rollback-generation cleanup, rollback and uninstall;
- no visible terminal window and no orphan process, listener or route after
  stop/uninstall/application close;
- objective confirmation that the selected tool did only the reviewed bounded
  action; and
- packaged restart behavior after the final authority-free state.

Unsupported Registry package types remain browse/plan information only. This
checkpoint does not authorize installing a real package or transmitting private
workspace or conversation content.

## Owner click-later checklist

1. Use a disposable project and chat in the packaged native application.
2. Select a trusted checksum-pinned MCPB release with an exact newer version in
   the Registry; review its provenance, permissions and declared configuration.
3. In the managed plan, choose `Begin trusted MCP proof` from a clean uninstalled
   baseline.
4. Install through the normal control and native confirmation. Confirm the
   compatibility process is gone before continuing.
5. Admit only the required reviewed tool or tools to the active project.
6. Start the project host and confirm it reports ready without a visible terminal.
7. In the same chat, let the model request one admitted tool. Inspect and approve
   that call only, then confirm its terminal success receipt.
8. Stop the host and require verified process, lease and routing cleanup.
9. Review and apply the exact update, then roll back to the original generation.
10. Remove the retained superseded generation with the separate cleanup control.
11. Uninstall the restored current package and confirm the ledger reports
    `Complete` only after every row passes.
12. Close and reopen the package; confirm no unexpected process, listener,
    route, tool authority or visible terminal remains.

Record only content-free state codes and booleans. Do not copy tool arguments,
results, credentials, package contents or private paths into the handoff.

## Next boundary

Converge-05b was subsequently implemented as the equivalent page-owned evidence
ledger for one external controller: connect, exact project/chat discovery,
atomic ownership, streaming, Stop, reconnect without resubmission,
revision-bound two-party handoff, revoke, post-revocation rejection and final
ownership cleanup. Its automated instrumentation is complete; current
external-client owner execution remains pending. See the
[Converge-05b handoff](checkpoint-converge-05b-handoff.md). Existing synthetic
controller state machines remain useful contract evidence, but they do not by
themselves prove a current Codex, Claude or provider-neutral external client.
