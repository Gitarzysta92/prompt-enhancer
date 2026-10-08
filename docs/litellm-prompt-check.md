# Prompt Check through an owner-managed LiteLLM gateway

Prompt Check can use a configured LiteLLM model for commentary and rewrites.
Deterministic metrics still run in the application. This opt-in does not enable
network inference for session ingestion, automatic session analysis, or Agent.
The existing analytics cost profile remains offline; `/v1/capabilities` reports
network inference separately, with its scope limited to Prompt Check.

Set runtime variables in the deployment controller, never in source control:

| Variable | Meaning |
| --- | --- |
| `PROMPT_ENHANCER_LITELLM_BASE_URL` | HTTPS gateway URL, optionally ending in `/v1` |
| `PROMPT_ENHANCER_LITELLM_CONNECT_ADDRESS` | Optional private IP to dial while retaining the URL hostname for TLS verification and routing |
| `PROMPT_ENHANCER_LITELLM_API_KEY` | Dedicated virtual key restricted to the chosen model |
| `PROMPT_ENHANCER_LITELLM_MODEL` | Exact model alias registered in LiteLLM |
| `PROMPT_ENHANCER_LITELLM_REASONING_EFFORT` | Optional gateway reasoning control; `none` disables thinking for Qwen through Ollama’s chat API |
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
Session IDs cannot supply context to remote inference. Callers without a matching
preview approval receive HTTP 428 before any model call or history write.

The API sequence is `GET /v1/prompt-checks/configuration`, then
`POST /v1/prompt-checks/preview` with the ordinary request, then
`POST /v1/prompt-checks` with that request plus `remote_approval` from the preview.
Preview generation performs no inference and stores no text. All routes retain
the existing authentication and CSRF requirements.

The adapter sends LiteLLM's `no-log` flag and message-redaction header, disables
streaming, rejects redirects, limits response size, and returns sanitized errors.
The gateway operator must keep content logging disabled; these flags cannot
control an independently configured downstream provider's retention. See
[LiteLLM logging controls](https://docs.litellm.ai/docs/proxy/logging) and
[virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys).
Model errors produce an explicit unavailable commentary state alongside the
local deterministic results. Prompt Enhancer stores metrics and model identity,
not prompts, previews, or generated rewrites.
