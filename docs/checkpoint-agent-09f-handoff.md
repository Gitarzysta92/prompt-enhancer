# Agent checkpoint 09f — exact-revision path-free history export

Date: 2026-08-28

## Outcome

External Codex-, Claude-, and MCP-compatible controllers now have a dedicated
`agent_export` tool for one exact retained Agent chat revision. The default MCP
contract advances to `prompt-enhancer-agent-mcp.v11` and advertises exactly
fifteen tools. The generic invocation path refuses retained-history export, so
callers cannot bypass the export-specific revision, size, egress, or projection
rules.

## Export contract

- The request names one exact project and chat, the current catalog and history
  revisions, and a caller-selected maximum event count.
- The catalog record is checked before content is requested. Stale revisions,
  cross-project identities, metadata-only chats, and oversized histories fail
  before the export endpoint is called.
- The HTTP export endpoint independently enforces the same exact catalog and
  history revisions and rejects stale requests with a conflict response.
- A successful result contains the complete contiguous retained event prefix,
  its title, saved model alias, revision, turn count, interruption state, and
  export timestamp.
- The external projection omits the workspace path, attachment bytes, live
  approval state, raw tool arguments/output, and mutation authority. Literal
  safety facts in the result make those omissions machine-checkable.
- The bounded retained-event schema rejects non-contiguous sequences, hidden
  raw fields, inconsistent counts, and any metadata mismatch. Export is
  read-only and has no automatic retry or mutation authority.

## Verification

- Focused history, controller, MCP, disposable-loopback integration, and
  direct-client probe slice: **103 passed**.
- Generated OpenAPI contract verification: **6 passed**.
- Expanded controller CLI/HTTP, MCP authentication/connections/packaging,
  orchestration, durable catalog/history/forking, artifact/attachment,
  cancellation, release-hardening, and privacy-canary slice: **227 passed**.
- Adversarial cases covered stale catalog/history revisions, metadata-only and
  cross-project records, an oversized history, mismatched identity/title/
  workspace/model/counts, non-contiguous events, and forbidden raw arguments.
- Two independent direct HTTP MCP clients exercised the fifteen-tool surface;
  the second exported the exact retained prefix and verified that the local
  workspace path was absent from the serialized result.
- Python compilation, the 512-character MCP-instruction cap, exact v11 tool
  count/order, and OpenAPI byte-for-byte generation checks passed. The only
  test warning was the repository's existing Starlette/httpx deprecation
  notice.
- The aggregate privacy scanner passed two of three checks and reproduced only
  the previously recorded `docs/checkpoint-agent-02-shell.png` binary finding;
  no scanner rule or exclusion was changed.
- A graceful native close and headless reload reopened exactly one Agent
  workspace, retained the fictional durable project and chat, exposed Resume,
  Fork, and Export JSON controls, and showed the shared model runtime stopped.
  The final host snapshot had one `127.0.0.1` listener owned by `pythonw`, zero
  model-server processes, and zero visible terminal windows.

## Privacy and process boundary

All controller and UI acceptance data was fictional and locally retained. No
provider session, credential, account data, provider configuration, or
unrelated home content was read. No model was loaded, no GPU/VRAM state was
touched, and the controller path launched no shell, bridge, provider, or
visible terminal.

## Remaining work and owner gates

The next code-only step is a fresh capability re-audit of the external Agent
surface and native project/chat experience, followed by the smallest remaining
gap with a falsifiable acceptance test. Real installed-client and model-backed
acceptance remain deliberately owner-gated:

1. explicitly authorize creation of one temporary scoped direct MCP
   credential and probe one selected installed client;
2. separately authorize revocation and prove the same bearer receives 401;
3. choose one installed local model and placement, run one real turn and Stop,
   review one fictional file write/diff, unload, and verify exact process plus
   CPU/GPU cleanup evidence.

No commit or push was requested.

> Historical note: Agent-09g subsequently advances the default MCP contract to
> v12 with sixteen tools by adding the exact-revision live-only `agent_close`
> action. The v11/fifteen-tool statements above remain the exact evidence
> recorded at this checkpoint.
