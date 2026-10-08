# Agent checkpoint 09g — exact-revision live-chat close

Date: 2026-08-28

## Outcome

External Codex-, Claude-, CLI-, and MCP-compatible controllers now have one
dedicated way to close an exact idle Agent chat runtime without deleting its
durable project, catalog record, or retained conversation history. The default
MCP contract advances to `prompt-enhancer-agent-mcp.v12` with exactly sixteen
tools, and the lower-level controller CLI advances to
`prompt-enhancer-agent-controller-cli.v5` with a dedicated `close` action.

Generic controller invocation and generic MCP DELETE remain unable to close a
chat. This prevents callers from bypassing the close-specific identity,
revision, authorization, idle-state, and retention checks.

## Close contract

- The request names one exact project and chat plus the current catalog and
  history revisions. Partial identity is rejected.
- MCP and controller-CLI callers must provide JSON literal
  `mutation_authorized: true`; `false`, numeric `1`, strings, and omitted
  authorization fail before dispatch.
- The live chat must be idle, with no pending native approval, Stop/close in
  progress, or cleanup uncertainty. An active turn must first use the dedicated
  Stop flow and then refresh its revisions.
- The application route atomically rechecks the live mapping, project identity,
  catalog revision, history revision, and idle state before changing memory.
- A trustworthy close is sent once. A lost or malformed response receives one
  read-only live/catalog reconciliation and never a second DELETE.
- Settled receipts prove that the live runtime is absent and the durable catalog
  chat remains. Permanent delete, retained-history delete, and protected
  authority grant are literal `false` safety facts.
- The native application keeps its backwards-compatible close behavior; the
  exact query contract is required only by the dedicated external path.

## Verification

- Expanded exact-close, controller client/HTTP/CLI, MCP stdio/HTTP/authentication/
  packaging/two-client integration, catalog/history/forking/artifact/attachment,
  cancellation, release-hardening, and privacy-boundary slice: **243 passed**.
- The complete controller CLI file, including rejected `false` and numeric
  authorization values: **14 passed**.
- Generated OpenAPI byte-for-byte contract verification: **6 passed**.
- Python compilation passed. Static inspection confirmed MCP v12, sixteen
  default tools, `agent_close` in stable position 7, 438 instruction characters
  under the 512-character cap, exact-revision close enabled, retained deletion
  disabled, and no subprocess in the default direct-HTTP setup.
- Adversarial coverage includes partial and stale identities, cross-project
  identities, mismatched live history, running/stopping/closing sessions,
  pending approval, cleanup uncertainty, trusted 4xx responses, ambiguous
  delivery that reconciles, ambiguous delivery that remains uncertain, and
  attempts to use the generic invocation path.
- Two independent direct HTTP MCP clients close and then resume one fictional
  retained chat. The close client emits one DELETE; the second client proves
  the durable record and history remain available.
- The aggregate privacy scanner passed two of three checks and reproduced only
  the previously recorded `docs/checkpoint-agent-02-shell.png` binary finding.
  No scanner rule, safety test, or exclusion was changed.
- A graceful native close and headless reload reopened exactly one Agent
  workspace with the fictional durable project/chat retained, Resume, Fork,
  and Export JSON controls available, and the shared runtime still stopped. The
  final host snapshot had one `127.0.0.1` listener owned by `pythonw`, zero
  model-server processes, and zero visible terminal windows.

## Privacy and process boundary

All tests use fictional IDs, paths, messages, and projects. No provider session,
credential, account data, provider configuration, or unrelated home content was
read. The checkpoint loaded no local model and did not touch GPU/VRAM. Its
controller and direct-MCP paths launch no app, model, shell, bridge, provider, or
visible terminal.

## Remaining work and owner gates

The next code-only step is a fresh parity re-audit against the requested
Codex/Claude-style project-and-chat experience, followed by the smallest
remaining falsifiable slice. Real installed-client and model-backed acceptance
remain owner-gated:

1. authorize one temporary scoped direct-MCP credential and probe one selected
   installed client, then separately revoke it and prove the bearer is rejected;
2. choose one installed local model and placement, run one real turn and Stop;
3. review one fictional proposed file write/diff in the native UI; and
4. unload the model and verify exact process plus CPU/GPU cleanup evidence.
