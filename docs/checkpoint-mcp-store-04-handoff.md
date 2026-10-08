# MCP Store checkpoint 04 handoff

## Outcome

The MCP Store can now run one explicitly native-confirmed compatibility check
for an exact, already-reviewed remote MCP plan. The check negotiates MCP,
enumerates bounded tool schemas without calling a tool, closes the connection,
and retains only a content-free receipt: protocol version, tool count, schema
digest, bounded duration, and cleanup truth.

This checkpoint does **not** install a local package, keep a server running,
route a tool into an Agent project, return a tool argument/result, or convert a
Registry listing into trust. Local package plans remain install-gated until
Store-05.

## Guarded host boundary

- Every probe re-fetches and revalidates the exact Official MCP Registry plan,
  version, option, plan revision, and digest immediately before connection.
- Remote transport is restricted to the reviewed HTTPS origin. DNS results are
  resolved just in time, must be public-only, and are pinned for the bounded
  check. Proxies, redirects, origin changes, mixed public/private answers, and
  global-looking names that resolve privately fail closed.
- Streamable HTTP and legacy SSE negotiation are deadline- and size-bounded.
  Pagination has bounded page/tool totals and rejects repeated or incomplete
  cursors.
- `tools/list` schemas are canonicalized into a digest. No discovered tool is
  invoked and no argument or result content is persisted.
- Secrets, when required by a reviewed plan, are retrieved just in time from the
  OS vault and are not added to SQLite, API responses, logs, model context, or
  the compatibility receipt.
- Connection teardown is verified. Ambiguous close or cleanup state is reported
  as failure rather than readiness.

## Windows stdio ownership foundation

- The Store host now has a console-free stdio transport that atomically assigns
  the child to a Windows Job Object at process creation.
- Standard input remains available for JSON-RPC while stdout and stderr are
  drained independently with strict response and diagnostic limits.
- Timeout, cancellation, crash, malformed JSON-RPC, oversized output, stderr
  flood, child-process creation, and cleanup are covered with synthetic fixtures.
- The transport is groundwork for Store-05 local-package lifecycle. Store-04
  still refuses to probe a not-installed local plan.

## Agent experience

- A ready remote prepared plan exposes **Check compatibility** only when native
  user-presence confirmation is available.
- The receipt reports the negotiated protocol, discovered tool count, schema
  digest, duration, and verified closed state, and states explicitly that no
  tool was called.
- Local package cards continue to explain that installation is required; they
  do not present a fake compatibility result.
- Strict frontend parsers reject extra or content-bearing receipt fields.

## Validation

- Guarded-host protocol, egress, pagination, size, failure, hidden-window, and
  cleanup suite: **34 tests passed**.
- Combined guarded host, Windows command ownership, and management regression
  gate: **103 tests passed**.
- OpenAPI export and strict schema tests: **6 tests passed**; generated
  TypeScript drift check passed.
- Complete frontend suite: **170 files / 2,299 tests passed**.
- Production TypeScript/Vite build passed with **559 modules**. Vite reports the
  Agent page at approximately **507 kB minified**, an accepted performance item
  for the later bundle-budget checkpoint rather than a correctness failure.
- Repository privacy scan passed. No real credential, model, Registry mutation,
  third-party MCP package, remote MCP endpoint, owner workspace, or tool call was
  used; all host behavior used synthetic fixtures or an in-process loopback
  server.
- The first complete backend run finished with **4,755 passed / 9 expected
  platform skips / 2 failed**. Both failures were checkpoint integration guards:
  the new MCP Registry cache path was absent from the maintenance inventory and
  the Registry/guarded-host network modules were absent from the exact egress
  classification. After registering those boundaries, the complete Windows
  distribution-hardening file passed **45 tests**, the MCP Registry/host/
  management gate passed **68 tests**, and the privacy scan passed again. A
  fresh whole-repository run remains part of the final release gate after the
  later workstreams, rather than being misreported as clean here.
- The rebuilt native Agent was launched console-free and the live Store loaded
  **24** Official Registry entries with zero browser warnings/errors. The final
  process census found one Agent window, one loopback-only listener on port
  8765, zero visible console windows in the owned tree, and zero known local-
  model processes. No probe or tool call was made during the browser pass.

## Owner click checklist

After the rebuilt native Agent window is reloaded:

1. Open **Agent settings → MCP Store → Prepared plans**.
2. Open a ready fixed-HTTPS plan. Confirm **Check compatibility** requires a
   native confirmation and is never enabled merely because a Registry tile was
   listed.
3. Approve a check only for a disposable endpoint you recognize. Confirm the
   result shows protocol, tool count, digest, duration, **Connection closed**,
   and **No tool called**.
4. Deny one check and confirm no compatibility receipt appears.
5. Open a local package plan and confirm it still says installation is required
   rather than attempting to start anything.

No valuable secret or production endpoint is needed for this visual review.

## Remaining bounded checkpoints

1. **Store-05 — guarded install/update/uninstall.** Add exact previews, native
   confirmation, verified package/endpoint mutation, hidden owned hosts,
   idempotent retry, rollback, and truthful cleanup states.
2. **Store-06 — project tool routing.** Admit exact reviewed tool schemas into
   one selected Agent project, enforce per-tool permissions and consequential
   approvals, and render observable tool activity in chat.
3. **Store-07 — adversarial acceptance.** Exercise malicious metadata, schemas,
   results and credentials; crash/restart/update/uninstall; Stop; project
   isolation; and zero visible-terminal or orphan-process guarantees.

The governing whole-product sequence is maintained in the
[Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md).
