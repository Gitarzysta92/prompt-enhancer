# Phase 1: private local metadata infrastructure

Phase 1 is a zero-cost, local-first foundation for reproducible coding-agent
analytics. It stores content-free event metadata plus consented private display labels in SQLite, exposes allowlisted local
queries, and supports deterministic task-review and analysis commands through an
authenticated loopback API. Synthetic data remains the default. An explicitly
invoked Codex App Server reader can now build a metadata index and derive
structural metrics for selected sessions. It does not call an inference API,
download model weights, retain transcript text, or send analytics to a remote
analysis service.

## Safety boundary

The runnable profile is deliberately narrow:

- storage tier: content-free metadata plus bounded, consented local display labels;
- inference cost mode: `offline_only`;
- listener: loopback addresses only;
- API: random private token or ephemeral HttpOnly browser session, strict Host/Origin/CSRF checks, no CORS;
- provider access: one explicit content-bearing `local-history` consent, with detail reads additionally selector-gated and no mutation methods;
- persistence: keyed, domain-separated HMAC identifiers rather than source IDs;
- metrics: deterministic values with explicit coverage and unknown values;
- tests and demo data: fictional, deterministic synthetic sessions only.

Pseudonyms, private display labels, and aggregate metrics remain sensitive data. Keep the local
state directory private and do not commit its database, keys, or token.

POSIX file modes are enforced where the operating system exposes them. Windows
`chmod` is not a substitute for reviewed ACLs or encryption, which is another
reason raw transcript persistence remains disabled.

## Local quickstart

Python 3.11 or newer is required. The Python dependencies are open-source and the
Phase 1 workflow has no paid API calls.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m prompt_enhancer init
python -m prompt_enhancer demo
python -m prompt_enhancer status
cd frontend
npm install
npm run build
cd ..
python -m prompt_enhancer serve
```

The `demo` command is safe to repeat: ingestion is idempotent. The server does not
enable interactive API documentation and does not expose arbitrary SQL, raw text,
provider mutation, or general-purpose write endpoints. Every `/v1/*` request
requires either the token stored in private local application state or an
ephemeral HttpOnly browser cookie; mutations made with the cookie also require a
same-origin CSRF token held only in memory. The CLI never prints the persistent
token. The health response, static dashboard, and browser-session bootstrap are
unauthenticated and expose no stored metrics or source data.

## Explicit Codex workflow

Provider reads are never triggered by installation, server startup, dashboard
page load, consent changes, or tests. They run only after an explicit dashboard
index, label-enrichment, or analysis action, or one of the CLI commands below.
Granting consent changes only the local consent record; it does not access Codex.

```powershell
# 1. Allow local Codex history access. This command does not read it.
python -m prompt_enhancer codex-consent-grant local-history

# 2. Build the content-discarding local catalog.
python -m prompt_enhancer codex-index --max-sessions 500

# 3. In the dashboard, select safe pseudonyms and explicitly run Find missing
#    labels (at most 25 summary reads). Optionally add a Prompt Enhancer-only
#    manual label; this never renames the Codex project or task.

# 4. Analyze only an explicit safe selection.
python -m prompt_enhancer codex-analyze --project-id <safe-project-pseudonym> --max-sessions 25

# 5. Revoke local-history access when finished.
python -m prompt_enhancer codex-consent-revoke local-history
```


The equivalent dashboard workflow is: open **Local sources**, grant the
content-bearing scope, run a bounded content-discarding index, and select displayed
projects or sessions. **Find missing labels** performs a separately bounded summary
read only for unresolved labels; **Edit label** creates a local override and does
not rename Codex. Bounded analysis remains a separate explicit action. Stable
pseudonyms remain the selectors. Use `serve` after `npm run build`; `npm run dev`
intentionally remains a fictional fixture preview.

The documented `thread/list` response itself can contain user preview text, so
indexing is not authorized as metadata-only source access. Every list forces
`useStateDbOnly: true`, and the boundary DTO immediately discards preview text,
tool arguments, tool output, account fields, Git metadata, and full paths. With
consent, it maps the working directory only to its final component and retains
only the explicit `thread.name` as a bounded sensitive display label.

The index emits no `thread/read`. Label enrichment reads at most 25 selected IDs
from the current list snapshot with `includeTurns: false`; the parser rejects
non-empty turns and persistence fills provider-label nulls with versioned
provenance. Operational analysis uses `includeTurns: true` for its selected IDs.
Manual labels are a separate local-only layer with optimistic revisions and
presentation precedence. CLI and dashboard responses expose only private labels,
safe aggregate counts, and pseudonymous metadata. See
[ADR 0002](adr/0002-codex-app-server-read-boundary.md) for exact assumptions and
limits.

## Verification

```powershell
python -m pytest
python scripts\privacy_scan.py
```

The tests verify loopback binding, authentication, same-origin handling,
content-free adapters, HMAC separation, consent enforcement, task discovery and
review idempotency, immutable analysis provenance, missing-value semantics, and
absence of network access in the synthetic demo. The privacy scanner uses only
the Python standard library and reports repository-relative paths so a finding
does not echo a private checkout location.

## What is intentionally not implemented

Claude Code ingestion, raw-cache parsing, transcript storage/search, prompt text
scoring, and neural analysis are not implemented. The Codex adapter's synthetic
contract is tested, but live wire compatibility is intentionally not claimed
until a user explicitly runs the bounded index command on an installed Codex
version. Real responses must never be copied into fixtures, logs, documentation,
issues, or commits.

Local neural models and optional remote analysis also come later. A future remote
analysis path must name the destination and model, redact locally, show an egress
preview, and obtain explicit approval for that run. Nothing in Phase 1 requires a
Codex API key, an Anthropic API key, a Claude Code subscription, or hosted Hugging
Face inference.
