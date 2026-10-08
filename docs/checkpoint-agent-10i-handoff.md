# Agent checkpoint 10i — external generated-output review

Date: 2026-08-29

## Outcome

Codex, Claude Code, and other scoped MCP controllers can now inspect one exact
generated workspace file as a capture candidate before asking the owner to add
it to the Agent chat. The tool returns only project/chat-bound metadata: the
canonical relative path, title, classification, viewer kind, byte size, and
SHA-256 digest.

This is deliberately not a capture operation. It returns no file bytes, creates
no artifact or approval, and grants no reusable authority. The separately
confirmed native Agent UI remains the only artifact-capture lane.

## Implemented boundary

- The Agent MCP contract advances to `prompt-enhancer-agent-mcp.v17`.
- `agent_artifacts` now has strict `list`, `get`, and `preview_capture` actions.
- `preview_capture` accepts one exact project/chat identity, a canonical
  workspace-relative path, and an optional trimmed title.
- Its response is parsed through `agent-artifact-capture-preview.v1` and must
  preserve project, chat, path, title, content-free status, and native-
  confirmation requirements.
- Unsafe, absolute, traversal, backslash, oversized, untrimmed, or undeclared
  request fields fail before controller I/O.
- Cross-scope, path/title-substituted, byte-bearing, or false-confirmation
  responses fail closed.
- Generic `agent_invoke` cannot call `preview_artifact_capture`; callers must
  use the dedicated validated action.
- Both direct HTTP and stdio configuration documents explicitly declare that
  the preview is content-free and capture requires the native Agent UI.
- The Connections quickstart explains the inspect-before-native-capture flow.
- The full frontend sweep also repaired one stale controller-card expectation:
  the v13 manifest has 60 Agent routes after checkpoint 10h, not 59.

## Verification

- Artifact/controller/MCP/backend matrix: **186/186 passed**.
- Real two-client loopback MCP composition: passed. A synthetic Markdown file
  produced exact type/size/digest metadata, returned no content, remained
  unchanged, created no artifact row, and requested no native approval.
- Full frontend suite: **2,220/2,220 passed across 164 files**.
- Focused connection/controller/self-test group: **27/27 passed** after the
  stale route-count repair.
- Production TypeScript/Vite build: **553 modules**, passed.
- Generated OpenAPI/TypeScript drift check, Python compilation, repository
  privacy scan, MCP instruction-size bound, and whitespace check: passed.
- The rebuilt live Agent page shows 60 Agent routes and the new
  `preview_capture` guidance. Browser diagnostics are empty.
- Final runtime inventory: one window, one listener on `127.0.0.1:8765`, zero
  local-model processes, zero leftover Vitest processes, and no terminal
  window.

No model, GPU inference, microphone, command, web fetch, real external client,
provider configuration, new scoped credential, file capture, or protected
approval was used.

## Owner check

When ready to validate a real connected client with fictional data:

1. Create one scoped connection in the owned native Agent window and copy its
   one-time setup into the chosen local client.
2. Open a fictional project/chat and create a synthetic output inside its
   selected workspace.
3. Call `agent_artifacts` with `action: preview_capture` and compare the returned
   path/type/size/digest with **Files & review → Add output**.
4. Confirm that previewing alone creates no artifact. Capture through the native
   UI, then use `list` and `get` to inspect its immutable lineage.
5. Change the synthetic file and verify that native capture refuses the stale
   preview instead of silently substituting new bytes.

## Next checkpoint

The next owner-controlled gate combines that artifact walkthrough with the
existing separate-window, model-backed turn/Stop, reviewed fictional write,
unload, process-exit, and CPU/GPU cleanup checks. If owner interaction remains
deferred, the next autonomous slice is a card-by-card desktop/360 px Agent UX
and accessibility audit; only failed observations become implementation work.
No model, microphone, provider edit, scoped credential, or protected authority
should be started automatically.
