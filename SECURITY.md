# Security policy

Prompt Enhancer is experimental and is not ready to retain real transcripts, handle secrets, or support production use.

## Current support status

There are no supported releases yet. The repository contains a runnable synthetic stack and an opt-in, bounded Codex reader whose live wire compatibility is not yet claimed.

## Reporting a vulnerability

A private security-reporting channel has not yet been configured. Do not post credentials, transcripts, private source code, exploit payloads containing real data, or personal information in a public issue.

Before the first runnable release, the maintainers must enable GitHub private vulnerability reporting and document expected response times here. Until then, a public issue may report only that a security contact is needed, without vulnerability details.

## Threat model priorities

1. Accidental publication of transcripts, databases, credentials, personal Git metadata, or model caches.
2. Ingesting credential/configuration files while scanning provider state.
3. Secret or PII leakage through logs, embeddings, summaries, crash reports, exports, MCP responses, or remote LLM calls.
4. Localhost attacks through CSRF, DNS rebinding, permissive CORS, or an externally bound dashboard/collector.
5. Parser attacks from malformed or adversarial JSONL/tool output, including oversized records and path traversal.
6. Model supply-chain risk from unpinned revisions, unsafe serialization, remote code, or incompatible licenses.
7. Prompt injection inside stored conversations influencing analysis models or tools.
8. Misleading people analytics, hidden surveillance, or decisions based on uncalibrated scores.

## Controls in the current Codex experiment

- Adapter construction and consent changes do not access provider state.
- Content-discarding indexing and selected operational history use separate adapter modes under the same explicit content-bearing consent; detail reads additionally require safe selectors.
- App Server RPC is read-only, statically allowlisted, bounded, and scoped to IDs returned by the current list snapshot.
- Provider cache files, credentials, configuration, logs, and internal databases are not read directly.
- Preview text, transcript content, tool payloads, and full working-directory paths are discarded before persistence.
- After consent, only a bounded final folder name and explicit Codex task title may cross as sensitive local display labels; they never replace pseudonymous identity.
- Persistent identifiers are domain-separated HMAC pseudonyms; missing values remain unknown.
- Tests use handcrafted fictional responses and must never launch the installed Codex executable.
- The integrated dashboard and API share one loopback origin with no CORS.
- Every `/v1/*` route requires either the persistent private API token or an ephemeral HttpOnly, SameSite browser cookie.
- Cookie-authenticated mutations also require an exact same-origin request and an in-memory CSRF token.
- Unauthenticated health, static-file, and session-bootstrap routes expose no stored metrics or provider data.

## Required controls before transcript retention or content analysis

- Ingress size limits, schema validation, unknown-event preservation, and parser fuzz tests.
- Deterministic secret scanning plus PII redaction before any persistence.
- Synthetic leakage canaries for prompts, paths, emails, tokens, and identifiers.
- Separate encrypted raw-content vault with a key outside the database.
- Loopback binding, private session credentials, strict Host/Origin/CSRF checks, no CORS, and no unauthenticated sensitive-data route.
- Parameterized, allowlisted MCP tools; no arbitrary SQL or raw transcript reads.
- Model manifest with immutable revision, hash, license, base-model provenance, and `trust_remote_code=false`.
- Complete deletion and export tests.
- Secret scanning in local hooks and CI, plus GitHub secret scanning/push protection.

## Commit metadata

Commit author names and email addresses become public. Contributors should use a deliberate public identity or a GitHub-provided noreply email and inspect it before the first commit.
