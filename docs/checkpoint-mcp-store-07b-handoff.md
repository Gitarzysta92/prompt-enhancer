# MCP Store checkpoint 07b handoff

Date: 2026-08-31
Status: automated implementation complete; owner recovery-message review pending
Runtime effect of the automated gate: synthetic resolver, socket, TLS, HTTP,
SSE, timeout and browser fixtures plus one read-only reload of the rebuilt Agent
route. No real Registry browse, remote MCP endpoint, model, protected action or
GPU workload was started.

## Outcome

A reviewed remote MCP option can no longer inherit proxy settings, follow a
redirect, connect to a private or changed address, drift to another TLS origin,
accept compressed or unbounded traffic, hang indefinitely or return success
after cancellation. Failures settle through bounded, allowlisted,
content-free reasons and cannot retain or revive an unauthorized connection.

## Changed

- Registry, compatibility probe, Streamable HTTP and SSE production traffic now
  use explicit no-proxy, no-redirect transports with HTTP/1.1, identity encoding
  and finite connection pools.
- Resolution rejects loopback, link-local, private, multicast, reserved,
  unspecified, site-local, non-global and mixed answer sets. The admitted public
  address is pinned to the exact reviewed HTTPS hostname for the connection.
- Both asynchronous managed traffic and synchronous Registry traffic require
  hostname verification, a trusted certificate and TLS 1.2 or newer. Userinfo,
  fragments, origin drift, HTTPS downgrade and nonstandard Registry icon ports
  are refused.
- Request configuration can no longer override framing or content-encoding
  headers. Response headers, declared lengths, aggregate bytes, response counts
  and SSE event counts are validated before or while consuming a stream.
- Every redirect and non-identity response encoding is refused. Oversized,
  contradictory or malformed response metadata never reaches projection.
- Managed-host start now has one total deadline across connect and tool-contract
  discovery. Call timeout, cancellation and Stop tombstone the host before
  returning, close it on unsafe outcomes and prevent late results from reviving
  authority.
- Cancellation-resistant cleanup is itself bounded. If closure cannot be
  confirmed, the result says cleanup is required rather than hanging or claiming
  success.
- HTTP and frontend recovery contracts expose only allowlisted safe reason codes.
  Raw endpoints, queries, resolver answers, certificate details, headers and
  response bodies are not surfaced.
- Agent recovery copy distinguishes address-policy, origin/TLS, response-limit
  and timeout refusal while preserving one keyboard-reachable review/retry path.

## Automated evidence

- Focused guarded-host, Registry and managed-runtime adversarial suite:
  **121 passed**.
- Core Store-07b backend matrix including server management: **202 passed**.
- Complete MCP and Agent-MCP backend regression: **364 passed**.
- API/bootstrap/privacy/OpenAPI matrix: **32 passed**.
- Focused Agent recovery and transport frontend matrix: **214 passed**.
- Complete Agent frontend feature regression: **515 passed / 31 files**.
- Shared MCP contract and transport regression: **77 passed / 6 files**.
- TypeScript project build, production Vite build, generated API check, Python
  compile check and repository privacy scan passed.
- The rebuilt live `/agent` route loaded its durable project/chat workspace with
  **0 browser warnings or errors**.

The matrix includes synthetic proxy variables, redirect responses, private,
multicast and changed resolver answers, strict SNI/TLS inspection, response and
event floods, compression, late data, cancellation-resistant tasks and bounded
cleanup. All fixtures use reserved fictional identities and content. No
credential store, provider transcript, private workspace content or real remote
service was read or invoked.

## Process, network and cleanup evidence

- Final state retained exactly **1** listener at `127.0.0.1:8765`.
- **0** additional Agent, MCP, model or test workers remained.
- **0** established non-loopback connections were owned by Prompt Enhancer.
- **0** Prompt Enhancer-owned GPU compute contexts remained.
- The service processes had no visible top-level window. One persistent hidden
  Windows console-host child was observed; it did not create a visible terminal
  during the bounded monitor and was not terminated because its ownership and
  shutdown contract belong to Store-07c.

The hidden console-host observation is not declared harmless or solved. It joins
the earlier transient console-host observation as an explicit Store-07c target.

## Still bounded

- Local package startup, visible or hidden windows, child escape, stderr flood,
  crash, restart and Stop races belong to Store-07c.
- Recursive tool schemas, malformed arguments/results, output floods and
  approval replay belong to Store-07d.
- Vault values, log canaries and cross-project/chat/client isolation belong to
  Store-07e.
- Real protected lifecycle actions and subjective recovery-copy review remain
  owner acceptance work; automation did not manufacture that authority.

## Owner click-later ledger

1. Reload `/agent`, open **Agent settings → MCP Store**, and open a reviewed
   remote plan without activating it.
2. Confirm a safe network refusal names the category without exposing an
   endpoint, query, address, certificate or response content.
3. Confirm **Review connection** and **Try again** remain keyboard reachable and
   the rest of Agent chat stays usable after refusal.
4. Confirm Stop or leaving the plan cannot later replace the refusal with a
   delayed success card.

## Next checkpoint

Store-07c is active next: make local MCP startup, crashes, output floods,
process-tree behavior, timeout, Stop, restart and cleanup fail closed with no
visible terminal storm and no orphan owned descendant.
