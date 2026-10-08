# ADR 0002: Bounded Codex App Server read boundary

- Status: Accepted
- Date: 2026-08-06
- Last updated: 2026-08-07
- Scope: local Codex discovery, display-label enrichment, and metric ingestion

## Decision

Use the documented local Codex App Server over stdio as the only Codex history
surface in this slice. Do not parse provider JSONL, internal SQLite state,
credentials, configuration, logs, or broad cache directories.

Expose three capability levels behind one honest content-bearing source consent:

| Capability | Source calls | Required authorization | Persisted result |
|---|---|---|---|
| Content-discarding index | `initialize`, `initialized`, `thread/list` with `useStateDbOnly: true` | `local-history` consent (`redacted_content`) | pseudonymous installation/project/session IDs, available minimized labels, timestamps, status provenance |
| Selected label enrichment | index calls plus at most 25 `thread/read` calls with `includeTurns: false` for IDs returned by the current list snapshot | the same consent plus an explicit safe project/session selector | only previously missing project-folder basenames and explicit task names, with extractor and adapter provenance |
| Selected operational history | index calls plus `thread/read` with `includeTurns: true` for IDs returned by the current list snapshot | the same consent plus an explicit safe project/session selector | content-free canonical events, usage provenance, and deterministic metrics |

The documented `thread/list` result contains a user-text `preview` and has no
omit-preview option. Every capability therefore requires `local-history` consent
before the process starts. The minimized list DTO omits `preview`, Git metadata,
and every other non-allowlisted field. It accepts the explicit `thread.name` only
as a secret in-memory value, and the mapper derives only the working directory's
final component for local display. Full paths and raw provider IDs are HMACed
before persistence or API exposure; this does not make the source call metadata-only.

Label enrichment and operational history additionally require at least one
persisted project or session pseudonym and a session bound. Label enrichment is a
separate application use case: it reads only fixed, already-indexed identities,
fills provider-label nulls atomically, and never starts ingestion or metric
recomputation. A manual local override has presentation precedence, carries an
optimistic revision, and never invokes a Codex rename or mutation.

## Hexagonal split

```text
Dashboard / API command
        |
        +-- IngestionService ------------------- IngestionRepository --+
        |       |                                                     |
        |       +-- SessionMetricComputer                             |
        |                                                             v
        +-- ProviderDisplayLabelEnrichmentService -- DisplayLabelRepository --> SQLite
        |       |
        |       +-- SourceIdentifierProtector ---- local HMAC adapter
        |
        +-- ManualDisplayLabelService ----------- DisplayLabelRepository

ProviderAdapter port
        |
        v
CodexAppServerAdapter
  -> content-minimizing mapper
  -> allowlisted client
  -> capability-gated, bounded stdio JSONL transport
```

Provider wire DTOs remain inside
`infrastructure/providers/codex_app_server`. Ingestion receives only
`SourceSession`, `SourceSessionSnapshot`, and `SourceEvent`; label enrichment
receives only minimized label observations tied to existing safe identities.
Persistence accepts safe DTOs and applies label writes atomically. The composition
root selects the concrete provider adapter, so a future Claude Code adapter can
reuse the application use cases without importing Codex transport or mapping
rules.

## Read-only protocol rules

The outbound method set is static:

```text
initialize
initialized       (notification)
thread/list
thread/read
```

Every list request forces `useStateDbOnly: true`, uses an explicit source-kind
allowlist, and is page/session bounded. This avoids the provider's JSONL
scan-and-repair list behavior. A detail read is rejected unless its thread was
returned by the active list snapshot. The transport accepts exactly
`threadId` plus a strict Boolean `includeTurns`: `false` in label mode and
`true` in operational mode. Label mode is capped at 25 unique reads per
snapshot, and its parser accepts absent, null, or empty turns but rejects any
non-empty turn payload.

Provider cursors and raw IDs are held only in memory. Server-initiated requests
fail closed. Subprocess arguments are fixed, use `shell=False`, discard stderr,
bound JSON lines and time, and are cleaned up on success or failure. The adapter
constructor performs no provider access. Raw list and summary responses can
contain sensitive plaintext in transport memory; boundary DTOs discard every
non-allowlisted field before any domain object, log, error, or SQLite call exists.

No provider value can choose an RPC method, command argument, filesystem path to
open, SQL statement, or network destination.

## Project and task grouping

Project discovery uses only the thread working-directory field already returned
by App Server:

1. normalize separators, dot segments, and drive-letter case lexically;
2. never resolve the path, traverse the filesystem, inspect a Git remote, or
   read repository files;
3. HMAC the normalized value before persistence or API exposure;
4. derive an optional display label from only the final path component, suppressing
   drive roots and direct user-home roots;
5. group equal pseudonyms within the same provider installation; and
6. when the working directory is absent, derive a session-isolated unknown
   project so unrelated sessions are never merged into one global bucket.

The optional session label comes only from the explicit `thread.name`, never from
`preview` or conversation text. Labels are presentation data and may duplicate
or remain unknown without changing project/session identity. Effective display
precedence is manual local override, then provider observation, then unknown;
clearing an override reveals the latest provider label.

Task discovery then operates within `(provider, installation, project)` and
uses the existing versioned temporal-boundary strategies. Its output is a
reviewable candidate, not an automatic claim that several sessions are one task.
The user can accept, reject, merge, or split candidates before task-level trend
analysis.

## Initial metric semantics

The first operational metric pack is intentionally structural:

- observed session and turn boundaries;
- plan, compaction, tool-category, and verification event counts when present;
- known tool/turn durations and known success observations;
- input, cached-input, cache-creation, output, reasoning, and total token fields;
- event-stream coverage and missing-value coverage; and
- project/session/task trends through existing immutable analysis runs.

Important limits and assumptions:

- thread status describes provider runtime/session state, not proof that the
  engineering task succeeded;
- `updatedAt` is activity recency, not a documented session end, so cycle end
  remains unknown;
- item timestamps may fall back to a turn boundary, recorded in `time_basis`;
- finalized per-turn usage is marked additive `delta`; mutable thread-level
  cumulative snapshots are omitted, and cumulative or unknown records are
  never included in additive metrics;
- absent duration, token, success, verification, or outcome values remain
  unknown rather than zero or failure; and
- objective test/build evidence, when a future documented field identifies it,
  must outrank assistant completion language.

Prompt quality, requirement coverage, contradiction, sentiment, and design-level
judging are not inferred in this slice because those require content consent,
redaction, evaluation datasets, calibrated models, and separate metric versions.

## Alternatives rejected

### Direct cache, JSONL, or internal state-database parsing

Rejected for the primary path because those formats are private compatibility
surfaces, increase credential/configuration exposure, and couple the application
to provider storage migrations. A future fallback would require its own ADR,
exact version fixtures, a selected-file boundary, and no automatic fallback.

### Read every thread during discovery

Rejected because it turns a low-risk catalog action into bulk content access,
increases latency, and prevents meaningful consent and scope selection. The
accepted label workflow is a later explicit action, reads at most 25 selected
summaries, and skips identities whose effective labels are already present.

### Store redacted transcripts in the metrics database

Rejected for this slice. Redaction is fallible, derived text remains sensitive,
and normal dashboard metrics do not require transcript retention. A future
encrypted content vault is a separate port and retention policy.

### OpenTelemetry as the only historical source

Deferred. Telemetry is useful for future content-free live metrics but cannot
backfill sessions that occurred before a collector was configured and may itself
carry identity attributes that require ingress filtering.

## Consequences and fitness checks

Benefits are explicit consent, no direct cache mutation risk, replaceable
provider adapters, deterministic metrics, and a useful project/session catalog
before transcript analysis. Costs are a local App Server subprocess, evolving
wire schemas, and intentionally missing metrics where the provider does not
report exact evidence.

Tests must prove:

1. construction and denied `local-history` consent make no subprocess/client call;
2. index mode never emits `thread/read` and always lists with state DB only;
3. label mode requires a safe selector, emits at most 25 current-snapshot reads
   with `includeTurns: false`, and rejects non-empty turn payloads;
4. operational mode requires a safe selector and uses `includeTurns: true`;
5. preview and other raw content/identity canaries do not enter domain output,
   SQLite, logs, or errors;
6. label enrichment cannot alter project/session identity, overwrite a visible
   manual override, or trigger ingestion and metric recomputation;
7. provider and manual label provenance and optimistic revisions are retained;
8. list, line, time, turn, item, event, and session bounds fail safely;
9. pagination cursors and missing project values cannot merge unrelated data;
10. cumulative usage is excluded from additive metrics; and
11. identical synthetic imports are idempotent and version provenance is retained.

Live wire compatibility is not claimed by synthetic tests. The first real-source
compatibility exercise must be an explicit local user action, start with the
bounded index, show only safe aggregate counts, and never copy its response into
the repository.
