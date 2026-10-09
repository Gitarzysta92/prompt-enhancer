# Reviewed inference through an owner-managed LiteLLM gateway

The proposed provider boundary supports Prompt Check, chat, explicitly selected
session interpretation/judging and Agent model requests. See [ADR 0022](adr/0022-inference-provider-boundary.md)
for owner-review status and hosting tradeoffs. Deterministic metrics and automatic
session analysis retain local behavior. `/v1/capabilities` distinguishes reviewed
external inference from automatic session-text egress, which remains disabled.

Set runtime variables in the deployment controller, never in source control:

| Variable | Meaning |
| --- | --- |
| `PROMPT_ENHANCER_LITELLM_BASE_URL` | HTTPS gateway URL, optionally ending in `/v1` |
| `PROMPT_ENHANCER_LITELLM_CONNECT_ADDRESS` | Optional private IP to dial while retaining the URL hostname for TLS verification and routing |
| `PROMPT_ENHANCER_LITELLM_API_KEY` | Dedicated virtual key restricted to the chosen model |
| `PROMPT_ENHANCER_LITELLM_MODEL` | Exact model alias registered in LiteLLM |
| `PROMPT_ENHANCER_LITELLM_REASONING_EFFORT` | Optional reasoning control supported by the selected gateway/model |
| `PROMPT_ENHANCER_LITELLM_MODEL_REVISION` | Operator-verified upstream model revision or digest |
| `PROMPT_ENHANCER_LITELLM_MODEL_LICENSE` | Upstream model license identifier |
| `PROMPT_ENHANCER_LITELLM_TLS_CERT_BASE64` | Optional trusted private-origin PEM leaf certificate, encoded as one base64 line |

Leave every variable absent to retain local-model behavior. Partial or invalid
configuration fails closed. Credentials are passed only to the application
backend, not the browser or authentication gateway. Keep the upstream model
revision pinned in the gateway/model server; a declared revision is provenance,
not independent verification of a remote server's weights.

For a private cluster route, set `CONNECT_ADDRESS` to the private gateway address
(or configure private DNS) and restrict the ingress to the application node.
The optional certificate setting verifies the chain, expiry, DNS hostname and
exact leaf fingerprint before sending authorization. Certificate replacement
requires updating the configured public certificate. Never disable TLS checks.

In Prompt Check, request commentary and select **Check prompt**. Review the
redacted prompt, earlier turns, deterministic findings and expandable system
instructions. **Send reviewed text to LiteLLM** sends precisely those model
messages. Editing the draft invalidates the preview; approvals expire after ten
minutes and application restarts. Redaction is best effort, not anonymization.
Prompt Check session IDs cannot supply context to remote inference. Callers without a matching
preview approval receive HTTP 428 before any model call or history write.

The API sequence is `GET /v1/prompt-checks/configuration`, then
`POST /v1/prompt-checks/preview` with the ordinary request, then
`POST /v1/prompt-checks` with that request plus `remote_approval` from the preview.
Preview generation performs no inference and stores no text. All routes retain
the existing authentication and CSRF requirements.

Chat and Agent use bounded streaming; Prompt Check and analysis use complete
responses. The adapter sends LiteLLM's `no-log` flag and message-redaction header,
rejects redirects, limits response size and returns sanitized errors.
The gateway operator must keep content logging disabled; these flags cannot
control an independently configured downstream provider's retention. See
[LiteLLM logging controls](https://docs.litellm.ai/docs/proxy/logging) and
[virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys).
Model errors produce an explicit unavailable commentary state alongside the
local deterministic results. Prompt Enhancer stores metrics and model identity,
not prompts, previews, or generated rewrites.

## Other inference features

The Agent composer’s inline **Review prompt** action uses the same Prompt Check
preview before sending to the gateway; accepting a rewrite does not send an
Agent message.

On **Models**, choose a gateway model, enter chat or supplied session text, and
select **Review request**. Inspect the full redacted request before selecting
**Send reviewed request**. Changing text, task or model invalidates that preview.
Manual analysis does not ingest or persist a session. Stop cancels the outgoing
chat connection; incomplete replies do not enter subsequent chat context.

Indexed session analysis offers an explicit gateway explanation/judgment control.
It uses the existing consented, redacted session window. Each execution requires
a fresh preview; a changed window cannot reuse the old approval. The ordinary
local buttons and automatic analysis do not switch to the gateway.

An Agent chat can select the external model without starting a local runtime.
Every model step pauses for review, including requests containing new tool
results. Decline or Stop releases the pending request. File and command approvals
remain separate; selecting a model never enables protected operations.

The new API starts with `GET /v1/inference/models`. Chat uses
`POST /v1/inference/chat/preview`, then `/chat` with the same body plus `approval`.
Supplied-text analysis uses `/analysis/preview`, then `/analysis`. Indexed session
analysis uses `/v1/model-judge/sessions/{id}/preview`, then its existing judge or
interpret route with the selected `model_id` and `approval`. Agent reviews are
scoped under `/v1/inference/agent/{session_id}/reviews`. They are in-memory,
bounded and cleared on completion, stop or expiry. Authentication, same-origin
CSRF checks and no-store responses apply to every surface.

The `prompt_check_litellm` settings field name remains for backward compatibility;
the environment variables above configure the shared adapter. Gateway model IDs
are opaque application aliases, not local model-registry entries. API keys,
connection addresses and certificates never appear in the browser catalog.
`configured` means configuration exists, not that a request or tool call succeeded.
Keep model revision/license pinned at the gateway; omitted provenance is unknown.

For user-local analytics and tools, run the application locally and use the shared
gateway for compute. A hosted dashboard sees server workspaces and supplied text,
not a visitor's device. This feature does not implement multi-user isolation or
remote native approval. It does not change service listen addresses.
