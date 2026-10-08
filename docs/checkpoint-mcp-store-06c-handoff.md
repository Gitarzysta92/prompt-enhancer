# MCP Store checkpoint 06c handoff

Date: 2026-08-30
Status: implementation, automated gates and read-only live gate complete; authority-increasing owner review pending
Runtime effect of the automated gate: synthetic connections only; no downloaded model, real third-party MCP server, visible terminal, or GPU allocation

## Outcome

Store-06c turns an already reviewed, installed and project-admitted MCP plan into
an explicit current-app-run Agent capability. It does not infer one authority
from another:

1. install or activation does not start a host;
2. project admission does not start a host;
3. reading status or the start preview does not start a host;
4. starting a host does not approve any tool call;
5. every tool call receives a new native confirmation that cannot be remembered;
6. Stop, app shutdown, cancellation and unsafe result handling remove runtime
   authority and close the owned connection/process before the settled response.

## Implemented behavior

- One memory-only supervisor owns at most four exact project/server host leases.
  It creates its worker thread lazily only after an explicit confirmed start.
- A start is bound to server revision, project-binding revision, tool snapshot,
  schema digest, admitted tool ids and granted permissions. The preview is exact,
  digest-bound and says whether current-user native code or a reviewed remote
  connection will run.
- Local stdio starts require positive owned-process evidence. No process evidence
  means no invented cleanup claim. Owned Windows process trees stay hidden.
- Readiness requires a fresh MCP tool enumeration that exactly matches the
  reviewed snapshot. Periodic health re-enumerates contracts without calling a
  tool.
- The Agent receives only aliases admitted for its project. A changed durable
  server/binding/snapshot is omitted immediately from model schemas; the call
  boundary revalidates the same authority again after approval.
- One call at a time is allowed per host. Arguments are detached, byte-bounded
  and JSON-Schema validated. Secret-looking preview fields are redacted.
- Denial, approval timeout and cancellation invoke nothing. Call timeout,
  cancellation, unsupported content, malformed/oversized output and contract
  failures revoke and close the host before returning.
- Tool-call output is bounded and projected into the current turn. SQLite keeps
  only ids, revision evidence, argument/result digests and sizes, outcome,
  timestamps and cleanup truth. It cannot store arguments, results, prompt,
  path, endpoint, credential, command or reusable approval.
- The managed-server detail now shows the selected project’s Stopped/Starting/
  Ready/Unhealthy/Stopping/Cleanup-required truth, exact start disclosure,
  current-run warning, process and cleanup evidence, routed aliases, fresh-call
  approval wording, Refresh, Start and Stop controls. Stop is authority-reducing
  and therefore does not ask for a second native confirmation.

## Automated evidence recorded so far

- Backend managed-runtime suite: **14 passed**.
- Local Agent, host contract, guarded-host and runtime-liveness regression:
  **145 passed**.
- OpenAPI export plus managed-runtime backend gate: **20 passed**.
- Focused runtime parser/transport/UI and managed Store UI: **37 passed**.
- Broader Agent page/Store/HTTP transport regression: **362 passed** after one
  deliberately updated stale-copy assertion; no behavioral regression remained.
- Historical migration/catalog/MCP/artifact compatibility regression:
  **129 passed**.
- Production frontend TypeScript/Vite build: passed.
- Generated OpenAPI TypeScript check: passed.
- Repository privacy scan: passed.

All fixtures use reserved fictional identities, hosts, paths and values.

## Read-only live evidence after the protected reload

- The Agent MCP Store loaded **24** registry records and **0** prepared plans.
  Its empty state truthfully said that no persistent host, retained connection
  or tool authority existed. Status inspection did not create one.
- This local profile has no already managed review-safe record. The runtime card
  therefore could not be exercised live without first changing durable state;
  no plan was fabricated, no package was installed and no third-party host was
  started for the gate.
- At **360 x 800** and **1440 x 1000**, the page width matched the viewport,
  all **57** visible Store controls remained inside the viewport and no
  horizontal document overflow appeared. The temporary viewport override was
  reset afterward.
- Browser diagnostics reported **0 warnings** and **0 errors**.
- The process census found exactly **1** listener on `127.0.0.1:8765`, the
  expected two-process Python server tree, **0** managed MCP/model runtimes,
  **0** Prompt Enhancer/local-model GPU compute processes and **0** visible
  terminal processes created since the hidden server restart.

## Owner review ledger after the protected reload

These checks are intentionally recorded for later so none disappear:

1. Open **Agent → MCP Store**, open one already managed synthetic/review-safe
   record, choose an Agent project and find **Project tool host**.
2. Confirm the initial state says **Stopped** and merely opening/refreshing the
   card creates no terminal, process or connection.
3. Expand the exact start effects. Confirm it says current app run only, no
   automatic restart, exact admitted tools and fresh confirmation per call.
4. Confirm **Start for this app run** is the only authority-increasing host
   action and uses the native confirmation surface.
5. When a safe reviewed host is available, confirm **Ready**, project-scoped
   routing and exact aliases appear; do not use an unknown downloaded package.
6. Confirm a tool request creates a separate approval card containing server,
   tool, scope, permissions and redacted arguments—not a remembered toggle.
7. Confirm **Stop host** needs no extra confirmation, returns to **Stopped**, and
   removes routed aliases.
8. Narrow/desktop overflow and visible-control bounds are verified. Still verify
   keyboard focus reaches disclosure/Refresh/Start/Stop once a managed card is
   available, and visually review its status/error copy.
9. The current no-plan reload and process census are verified. After an owner
   explicitly starts a safe reviewed host, repeat close/reload and confirm that
   host is not restarted.

## Deliberately remaining

- Store-06d: durable content-free host-action receipts and cleanup blocks,
  broader secret-safe configuration/editing, transport/version breadth and
  interrupted-operation reconciliation.
- Store-06e: final Store/tool drawer layout, live refresh/reconciliation,
  responsive/accessibility acceptance and complete owner journey.
- Store-07: adversarial Registry, logo, redirect, DNS, proxy, schema bomb,
  output flood, hang, crash, child escape and cross-project isolation matrix.
