# Checkpoint Store-07b entry

Status: implementation active
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Previous evidence: [Store-07a handoff](checkpoint-mcp-store-07a-handoff.md)

## Frozen user outcome

A reviewed remote MCP option must never inherit machine proxy settings, follow a
redirect, connect to a private/reserved or changed address, drift to another TLS
origin, hang indefinitely or retain an unauthorized connection. Every refused,
cancelled, timed-out or oversized exchange settles truthfully with bounded,
content-free evidence while Agent chat and other projects remain usable.

## Evidence at entry

- Store-07a binds catalog cards and exact reviews to coherent public identities
  and refuses ambiguous presentation data before remote lifecycle begins.
- The current official Registry adapter already uses an explicit no-proxy,
  no-redirect opener with bounded JSON/icon reads and a fixed HTTPS origin.
- The managed remote path already separates review, compatibility probing,
  native-confirmed activation, project admission and per-call approval.
- Store-07b must prove those boundaries under resolver, socket, TLS, HTTP/SSE,
  cancellation and response-size hostility rather than relying on intent.

## In scope

1. Reject inherited HTTP(S)/ALL proxy behavior for Registry, remote probe and
   managed Streamable HTTP/SSE traffic.
2. Reject every redirect status and any final URL/origin disagreement.
3. Resolve exact public-only addresses; reject loopback, link-local, private,
   multicast, reserved, unspecified and mixed public/private answers.
4. Pin the admitted address/origin for the bounded connection and fail closed on
   DNS rebinding or resolution drift before reuse.
5. Require supported TLS verification and exact reviewed hostname/origin; never
   downgrade HTTPS or accept credential-bearing URLs.
6. Bound connect, header, body, event, idle and total-operation time as well as
   response/event counts and byte volume.
7. Make cancellation and Stop close the owned connection deterministically;
   late data cannot revive or complete a cancelled operation.
8. Keep errors and receipts content-free: no URL query, header, response body,
   resolver answer or certificate detail enters ordinary UI, logs or storage.

## Explicit exclusions

- Local package processes, hidden windows, child escape, stderr flood and Stop
  races belong to Store-07c.
- Recursive tool schemas, malformed arguments/results, output floods and
  approval replay belong to Store-07d.
- Vault values, log canaries and cross-project/chat/client isolation belong to
  Store-07e.
- No real hostile endpoint, real credential, public package install, model or
  protected remote activation is authorized by this checkpoint.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Proxy variables configured | Transport still uses no proxy; no proxy request is observed. |
| Redirect or origin drift | Refused before following; reviewed authority remains unchanged. |
| Private/reserved/mixed DNS | Refused before socket connection with a stable safe reason. |
| DNS rebinding | Address/origin mismatch closes the attempt and cannot be reused. |
| TLS downgrade or mismatch | Refused; no insecure fallback or certificate detail disclosure. |
| Header/body/event flood | Bounded termination; no unbounded allocation or raw payload retention. |
| Connect/idle/total hang | Timeout or cancellation settles once and closes the owned connection. |
| Late response after Stop | Ignored; cannot produce success, tool authority or durable raw data. |
| UI recovery | One truthful retry/review path is keyboard reachable without disabling Agent chat. |

## Expected touched surfaces

- official Registry and managed remote transport/network-policy adapters;
- remote compatibility and runtime cancellation state machines;
- safe reason-code, OpenAPI and frontend recovery contracts where required;
- synthetic resolver/socket/TLS/HTTP/SSE failure fixtures and bounded browser
  recovery states;
- Store-07b handoff and the master milestone board.
