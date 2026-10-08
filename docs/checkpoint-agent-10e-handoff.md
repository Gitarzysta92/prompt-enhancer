# Agent checkpoint 10e — final parity and acceptance readiness

Date: 2026-08-29

## Outcome

The old Agent capability list is no longer a stale external snapshot. Agent
settings now opens on a first-class **Readiness** tab that reconciles the 15
requested Codex/Claude-style capabilities against the 16 frozen implementation
groups. The page reports implementation evidence separately from the 10
remaining owner checks, so synthetic coverage cannot be mistaken for a real
model, microphone, native-window, confirmation, or GPU-cleanup result.

## Repaired behavior

- **Agent settings** opens on Readiness. The four settings tabs use the shared
  roving-focus keyboard contract and remain touch-sized at 320 px.
- The readiness card reports 16/16 implementation groups complete, zero missing
  groups, zero platform implementation blockers, and 10 pending owner checks.
  Each of the 15 user-facing capabilities has its own evidence status.
- The card explains that Agent projects/chats live in the Agent rail, while the
  global Projects and Sessions routes remain analytics catalogues. A permanent
  route-boundary test prevents Agent production modules from importing those
  catalogues or the legacy Models chat.
- The loopback controller and MCP endpoint are named explicitly. The card does
  not claim Codex or Claude is connected: creating a scoped bearer remains a
  native-confirmed action, and Prompt Enhancer does not edit provider config.
- Safe Markdown received additional hostile-input coverage. `data:`, `file:`,
  protocol-relative links, encoded workspace traversal, encoded drive paths,
  control bytes, raw event handlers, and remote images remain inert. Uppercase
  HTTP/HTTPS links now receive the same new-window isolation as lowercase URLs.
- The populated Agent fixture validates the readiness card, all 15 rows,
  desktop and 320 px containment, 44 px settings controls, keyboard navigation,
  forced-colors focus, and the transition into Connections.

No real model, microphone, protected approval, workspace mutation, provider
configuration, external connection, or remote service was used.

## Verification

- Complete frontend: **163/163 files and 2,206/2,206 tests passed**.
- Focused settings/readiness navigation: **138/138 tests passed**.
- Focused hostile Markdown/readiness layout: **18/18 tests passed**.
- Frontend Agent route, controller, and MCP contracts: **38/38 tests passed**.
- Loopback orchestration, client-config, MCP surface/HTTP, and controller HTTP:
  **68/68 tests passed**.
- OpenAPI export and privacy regression: **9/9 tests passed**. The gate caught a
  stale generated schema; `docs/openapi.json` and the generated TypeScript
  client were regenerated, then byte-exact parity passed.
- Populated browser fixture at 1,440 px and 360→320 px, including forced colors:
  **2/2 Playwright tests passed**.
- TypeScript and production build: **551 transformed modules**, passed.
- OpenAPI TypeScript client check, privacy scanner, and `git diff --check`:
  passed.
- The stale running listener was replaced once with the same hidden-console
  Agent launcher. A fresh `http://127.0.0.1:8765/agent` reload opened Readiness
  by default, showed all 15 rows plus the 16/16 and 10-pending summaries, and
  emitted zero browser console errors.
- Cleanup inventory: exactly one listener on `127.0.0.1:8765`, zero listeners
  on the Playwright fixture port, zero Vitest/pytest/Playwright workers, zero
  `llama-server` processes, and no surviving old listener.

## Exact remaining owner gate

Implementation parity is complete, but these native observations still require
the owner and must produce only content-free receipts:

1. reload Agent and reopen a saved project/chat;
2. open/refocus and close the separate Agent window;
3. select one probe-verified local model and confirm the served model/runtime;
4. send one fictional streamed turn and issue Stop during another turn;
5. review and approve one fictional workspace change;
6. create and inspect synthetic text, image, PDF, and Office artifacts;
7. exercise image input and, only with explicit permission, microphone input;
8. switch placement/model, then unload the runtime;
9. confirm child-process exit and CPU/GPU cleanup;
10. create, self-test, rotate, and revoke one scoped external Agent connection.

Unknown or failed cleanup is not a pass. Provider configuration is never
changed automatically. The owner can run these checks from **Agent settings →
Owner checks** and **Connections** when ready.

## Next checkpoint

There is no further honest autonomous feature-parity claim to make before the
native owner gate. The next implementation slice should be driven by any failed
owner observation or the subsequent card-by-card visual-polish walkthrough.
