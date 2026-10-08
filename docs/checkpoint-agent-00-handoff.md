# Agent-00 handoff: native single-instance and cleanup containment

Date: 2026-08-27
Status: visible gate failed, contained and repaired; automated re-gate complete; owner-visible rerun deferred

## Outcome

The protected Agent now has one launch authority per Windows desktop session.
Both supported entry paths acquire the same fixed named-mutex lease before they
can start a listener, worker, lifecycle marker or native window.

A repeated launch:

1. receives no runtime authority;
2. closes its duplicate native handle;
3. waits at most two seconds for the exact existing Agent window;
4. restores/focuses that window when available; and
5. exits even when focus is unavailable. It never falls back to creating a
   second backend or WebView.

The primary releases its lease after a clean close and after a safe runtime
failure. An unconfirmed lease release cannot be published as success. Native
failure handling retains only closed reason codes, not native exception text.

The first owner-visible check exposed a second Windows boundary defect: a
`llama-server` child redirected its standard streams but did not use
`CREATE_NO_WINDOW`. Redirects do not suppress a console-subsystem window. The
check was stopped, the exact Agent/model processes and owned listener were
closed, and no second visible launch was attempted.

The runtime spawn now applies `CREATE_NO_WINDOW` on Windows and `shell=False`
on every activation. Read-only registry, status and overview paths remain
incapable of spawning a runtime. The Agent page likewise treats model discovery
as read-only and cannot activate a stopped model until the owner presses the
explicit start/open action.

## Implementation

- `infrastructure/windows_single_instance.py` owns named-mutex acquisition,
  idempotent release and bounded exact-title focus.
- `desktop_overlay.launch_desktop_agent` is the shared production launch
  boundary.
- The installed GUI entry and `prompt-enhancer agent-desktop` both use that
  boundary.
- The underlying protected Agent composition remains separately testable; a
  duplicate never reaches it or changes its lifecycle marker.
- The local-model process boundary owns the Windows console-suppression flag;
  this is tested independently from UI copy and stream redirection.

## Verification

- 85 focused single-instance, desktop host, lifecycle-marker and cleanup tests
  passed.
- 35 worker, runtime-liveness and full loopback lifecycle tests passed.
- 105 local-Agent, completion and Windows command-tree tests passed.
- The focused total is 225 passing tests with zero failures.
- A real cross-process Windows mutex probe proved that a hidden child is denied
  while the primary owns the lease and can acquire after release.
- One disposable hidden native Agent probe created and loaded its document,
  closed, returned success, released its listener and removed its temporary
  state. It used no model, provider data, owner workspace, folder picker or
  protected approval.
- Final resource check: zero Agent launcher processes, zero listeners on 8765,
  zero `llama-server` processes. The pre-existing development listener on 4173
  was preserved.
- After the visible-gate incident, all 32 local-model runtime tests and all 85
  Agent-page tests passed. These include direct assertions that read-only model
  discovery makes no spawn call, page load makes no activation call, and the
  one explicit runtime spawn receives the console-free Windows policy.

## Privacy and safety

The mutex name and window title are fixed application constants. No workspace,
path, account, model, prompt, session, process identifier or exception text is
stored or displayed. Cross-process tests use generated synthetic names and
content-free results. No remote service or provider store is accessed.

## Failed visible-gate evidence and next owner checklist

The single-instance ownership assertions passed during the first visible run,
but the overall checkpoint did not: a model process was observed and the owner
reported a cascade of visible terminal windows. The process was gone after the
bounded close. Page-load attribution could not be proven from retained data,
so the repair closes both relevant boundaries instead of inventing a cause:
page load is tested non-mutating, and any explicit runtime start is tested
console-free.

Do not run this checklist until the owner chooses a convenient time:

1. Open the protected Agent once and confirm one window appears.
2. Launch it again and confirm the same window is focused, with no second
   window or second session/runtime.
3. Close the Agent and confirm no cleanup-error dialog appears.
4. Open it once more and confirm the lease was released and a fresh single
   window can start.

Agent-01 does not begin until this bounded recheck is accepted. A repeat failure
stops the checkpoint again; it does not trigger another automatic launch.
