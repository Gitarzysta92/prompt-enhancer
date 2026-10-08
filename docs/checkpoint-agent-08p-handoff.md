# Agent checkpoint 08p handoff: packaged MCP composition proof

Date: 2026-08-28
State: source, package-entry, loopback-composition, and responsive-UI validation complete; installed provider and native/model owner acceptance remain pending

## Outcome

Agent-08p turns the Agent MCP bridge from a unit-tested interface into a tested
composition. A synthetic MCP client now crosses the real stdio protocol, an
authenticated ephemeral loopback listener, the production HTTP/controller
surface, and the durable Agent catalog. It creates one fictional local-history
project/chat, starts a second independent MCP process, and proves that the
project remains browseable. The same run verifies that the shared model runtime
stays idle and that listener cleanup is complete.

The packaged `prompt-enhancer` console declaration and generated Codex/Claude
configuration are also covered by a reusable, content-free probe. A disposable
isolated installation successfully executed the real console launcher and was
removed afterward. The ordinary development shell still has no global
`prompt-enhancer` command on `PATH`; this checkpoint did not install the
application globally or edit either provider's configuration.

In the Agent UI, **Connection & setup** now keeps the recommended MCP setup
visible and moves lower-level script/direct-HTTP commands into a nested
**Advanced** disclosure. No integration option was removed. The disclosure is
keyboard reachable, touch-sized, responsive, and visible in forced-colors mode.

## What the composition test proves

- MCP initialization and tool discovery use the real JSON-RPC stdio server.
- The default tool list omits model lifecycle.
- The MCP process authenticates to an actual loopback TCP listener.
- Controller discovery returns the complete v6 contract.
- Project listing, runtime inspection, project creation, and chat creation
  cross the production HTTP/controller path.
- Durable catalog state survives the first MCP process and is visible to a
  second MCP process.
- The model runtime remains idle; no model or GPU workload is needed.
- The owned listener closes and its server thread finishes.

This is not a real Codex or Claude model handshake. No provider session,
credential, account file, or owner configuration was read or changed. It also
does not replace the native owner walkthrough for live streaming, Stop,
protected file review, model unload, process exit, or GPU cleanup.

## Verification receipts

- Agent MCP/package/full-composition focused gate: **20 passed**.
- Broad backend `test_agent_*` gate: **199 passed**.
- Complete Agent component gate: **240 passed across 18 files**.
- Agent API-contract gate: **214 passed across 16 files**.
- Focused controller component/layout gate: **12 passed**.
- Chromium controller flow: **2 passed** at 360 px and 1,440 px.
- Production build: **533 modules transformed**.
- Python compilation: passed.
- `git diff --check`: passed; Git emitted only existing line-ending notices.
- Cleanup receipt: zero `llama-server` processes and no listener on ports 8765
  or 8766.

The unchanged privacy scanner reports exactly one known pre-existing finding:
the untracked binary screenshot `docs/checkpoint-agent-02-shell.png`. Agent-08p
introduced no additional finding and did not weaken the scanner.

The isolated packaged-command probe emitted this content-free result:

```text
PACKAGED_AGENT_MCP_PROBE={"claude_config_valid":true,"codex_config_valid":true,"config_exit_code":0,"contract":"packaged-agent-mcp-probe.v1","entry_present":true,"entry_target_verified":true,"error_code":null,"lifecycle_default_off":true,"private_state_created":false,"temporary_state_removed":true}
```

## Remaining gate and next slice

The next meaningful gate is an owner-approved installed-client acceptance, not
another synthetic claim. Rebuild/install Prompt Enhancer, add the default
token-free MCP configuration to one selected provider, and verify discovery,
project/chat browsing, one fictional project/chat, and one finite turn. Model
lifecycle must remain disabled for that first pass. Enabling external
load/switch/stop requires a separate explicit owner choice.

After that handshake, the existing native acceptance checklist remains: open
and refocus the dedicated window, run one live model turn, exercise Stop,
review one fictional file effect, inspect context truth, unload the model, and
verify owned process/GPU cleanup. Until those owner gates pass, installed
provider usability and native/model behavior remain pending rather than
inferred from automated tests.
