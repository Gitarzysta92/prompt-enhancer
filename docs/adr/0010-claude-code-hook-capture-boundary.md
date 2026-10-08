# ADR 0010: Claude Code hook-capture boundary

- Status: Accepted prospective capture surface; transcript reading is not accepted
- Date: 2026-08-18
- Contract version: `claude-code-hooks.v1`
- Receiver version: `claude-code-hook-receiver-1`; adapter version: `claude-code-hooks-adapter-1`
- Storage schema: migration 45 (`claude_code_hook_sessions`, `claude_code_hook_events`);
  migration 46 (`claude_code_telemetry_sessions`, `claude_code_telemetry_requests`)
- Telemetry contract: `claude-code-otlp.v1`; decoder version 2 adds `TOKEN_USAGE`
- Extends: ADR 0002's documented-interface rule to a second provider

## Decision

Capture Claude Code sessions **prospectively through its documented hooks
interface only**. Claude Code invokes a local receiver command once per
lifecycle event; the receiver minimizes the payload in-process, appends a
content-free record to an append-only ledger in the local store, and exits.
The ordinary provider adapter, ingestion service, pseudonymizer, and metric
pipeline then read that ledger exactly as they read any other source.

No transcript, JSONL history file, settings file, credential, or any other path
under the provider's private directory is read by any component of this
surface. Historical sessions that predate hook installation are therefore not
captured, and no backfill is offered.

## Why hooks, and why not the alternatives

| Surface | Verdict | Reason |
|---|---|---|
| Hooks | accepted | Documented interface; content-free by construction because the receiver decides what it keeps; each hook fires synchronously at its event, so the receiver's clock orders and times every record - the authoritative per-item timing that the Codex app-server surface lacks |
| OpenTelemetry export | accepted (2026-08-19) | Documented opt-in export of per-request usage and aggregate counters; a loopback OTLP/HTTP JSON receiver with an eleven-key attribute allowlist makes `TOKEN_USAGE` a capability - see the section below |
| Agent SDK session readers | not accepted for now | Reads real session content and would need the full consent, redaction, and preview path before any use |
| Raw JSONL parsing | rejected | Touches exactly the private directory both `AGENTS.md` and `CLAUDE.md` single out; version-gated fallback only if ever authorized |

## Receiver obligations

1. **Never disturb the user's session.** For several hook types Claude Code
   feeds the hook's stdout back to the model or uses it for permission
   decisions, and a non-zero exit surfaces an error. The receiver writes nothing
   to stdout or stderr and always exits `0`, including when it drops the event.
2. **Read only allowlisted keys.** `session_id`, `cwd`, `hook_event_name`,
   `source`, `reason`, `tool_name`, `tool_use_id`, `trigger`. It never accesses
   `prompt`, `tool_input`, `tool_response`, `message`, `custom_instructions`,
   or `transcript_path`. A test scans the receiver source for any other payload
   key name.
3. **Produce only `MinimizedHookEvent`.** Every field is a closed enum, a
   pseudonym, a bounded label, or a non-negative number; there is no field able
   to hold text, a path, or a raw identifier, so a receiver bug cannot smuggle
   content past the type. Migration 45 repeats those bounds as `CHECK`
   constraints, so the schema refuses content even from a future caller.
4. **Never initialize state.** It loads an existing pseudonym key with a
   read-only loader and appends to an existing store already at schema 45. If
   either is absent, or if `claude_code` local-history consent is not active,
   it records nothing.
5. **Fail silent, not blocking.** Sequence numbers are assigned inside one
   `BEGIN IMMEDIATE` transaction with a 250 ms budget; contention drops the
   event rather than delaying the user's tool call. Because of that and because
   a hook configuration cannot prove it covers every event, `events_complete`
   is never claimed and metrics run at bounded confidence.

## What is recorded

`session_id` becomes an HMAC pseudonym under `claude_code:hook-session`. The
working directory is normalized lexically (no filesystem access), HMACed under
`claude_code:hook-project`, and otherwise survives only as a bounded basename
display label that is withheld when the directory names a person's home. Tool
names are reduced to a closed `ToolCategory` and discarded - including every
`mcp__server__tool` name, which can reveal a private server. `tool_use_id` is
HMACed so a `PostToolUse` can close the `PreToolUse` that opened it and record
a duration. `Notification` hooks are skipped entirely: their only
distinguishing field is free text. Unknown hook names are recorded as
`unknown` so a provider that adds a hook leaves an honest trace.

`PostToolUse` is documented to fire after a tool completes successfully, so it
records `success = true`; a `PreToolUse` with no matching `PostToolUse` stays
unknown, never failed. `SessionEnd` maps only what its reason says:
`prompt_input_exit` is a completed session lifecycle, `logout` an interrupted
one, and `clear`, `other`, or no end event at all remain unknown.

## Timing provenance

Hook payloads carry no timestamp. The receiver stamps receipt time at the
moment of the synchronous hook call. Rather than add a new `EventTimeBasis`
member - which would force a rebuild of the checksum-frozen `events` table -
the adapter reports `provider_reported` and names the clock in
`source_schema_version = claude-code-hooks.receipt-clock.v1`, which every
downstream row carries. The descriptor declares `EVENT_TIMING`.

## Capabilities the decoder declares, and does not

Declared: `SESSION_LIST`, `SESSION_LABELS`, `OPERATIONAL_EVENTS`,
`TOOL_EVENTS`, `EVENT_TIMING`, and - since decoder version 2 - `TOKEN_USAGE`
through the OpenTelemetry receiver described below.

Not declared: any `*_opportunities` or `*_links` member, `USER_MESSAGES`,
`AGENT_MESSAGES`, `PLAN_MESSAGES`, `DECISION_EVENTS`, `VERIFICATION_EVENTS`,
`LIVE_UPDATES`. Hooks enumerate no requirements, hypotheses,
or verification tasks, and a tool end categorised as test or build is not a
verification receipt. The five evidence-lane metrics therefore remain
`unknown` for Claude Code, exactly as for Codex, until a reviewed descriptor
or the agent-evidence boundary supplies a denominator.

The compatibility report is `degraded` with `unknown` extraction completeness
and reason `provider_version_unknown` (or `provider_version_untested` once
telemetry has reported an `app.version`): the decoder fully understands every
payload it admits, but hook payloads carry no version and nothing can prove
that the user's hook configuration delivered every event.
The public compatibility DTO reports `capability = operational_events` for this
surface; `session_text_analysis` is reserved for text-window decoders.

## Composition and consent

Consent is a separate `claude_code` grant at the `redacted_content` tier -
the same tier ADR 0002 requires for the Codex list surface, because the hook
payload transits content in memory before minimization even though nothing is
kept. Revoking consent stops the receiver from recording anything further; it
does not delete what was recorded, and the status surface says so by count.

The receiver is `python -m prompt_enhancer claude-hook`. The application
prints a `settings.json` fragment (`claude-hooks-config`) for the user to
paste; it never writes to the user's Claude configuration. The loopback API
gains `/v1/local-sources/claude-code` (status, consent, index) and
`/v1/providers/claude_code/compatibility` now resolves the hook surface. The
compatibility catalog registers both providers' descriptors; the route prefers
a text-window surface where one exists so the Codex contract is unchanged.

## OpenTelemetry token capture (added 2026-08-19)

The same boundary admits Claude Code's documented OpenTelemetry export through
a loopback OTLP/HTTP **JSON** receiver mounted at `/otlp/v1/logs` and
`/otlp/v1/metrics` on the existing local server - outside the
token-authenticated `/v1` tree, because the provider's exporter is the caller.
It requires a separate write-only ingest token (`otlp-ingest.token`), accepts
only `application/json`, bounds the body at 4 MiB and 10 000 records, and
never echoes payload content.

The receiver reads exactly eleven attribute keys (`event.name`, `session.id`,
`app.version`, `model`, `cost_usd`, `duration_ms`, `input_tokens`,
`output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `type`) and
only `api_request` / `api_error` log records plus the six documented cumulative
counters. `user.email`, `user.id`, `user.account_uuid`, `organization.id`,
`terminal.type`, prompt text, `tool_parameters`, error text, and every other
event kind are never read; the only record types it can produce have no field
able to hold them, and migration 46 repeats the bounds as `CHECK` constraints.
`session.id` is HMACed under the hook receiver's namespace, so usage joins the
hook session without either side learning the raw value; a telemetry-only
session (OTEL on, hooks off) is listed with no events and no label.

Per-request usage becomes `USAGE` events with `DELTA` / `REQUEST` counters at
the provider's own event timestamp, in a separate sequence space so hook
sequences stay stable. When only counters were exported, one `CUMULATIVE` /
`THREAD` usage event stands in. `app.version` supplies the provider version the
hook payload lacks; the compatibility report then says
`provider_version_untested` rather than `provider_version_unknown`, and stays
`degraded` because coverage remains unprovable. Cost is stored as the
provider's own estimate in micro-USD and never recomputed.

A consent-inactive or store-unavailable export is answered with HTTP 200 and an
OTLP `partialSuccess` naming the rejected count, so the exporter neither
retries nor surfaces an error to the person using Claude Code, and nothing is
written. Capture requires the local server to be running; a missing batch is a
gap, never a zero. `claude-otel-config` prints the environment variables the
user sets where they launch Claude Code; the application writes no
configuration and keeps `OTEL_LOG_USER_PROMPTS` at 0.

## Session titles (added 2026-08-19)

At the owner's request, hook-captured sessions carry a private title so a
person can find their own session by name, exactly as Codex thread titles
already do. The receiver reads the ``prompt`` field of ``UserPromptSubmit`` for
that one purpose: the first non-empty line, minimized to one bounded line of
at most 160 characters by the same minimizer that refuses absolute paths and
control characters, stored once per session (the first prompt wins) in
migration 47's ``session_display_label`` column, and surfaced through the
ordinary ``session_display_name`` path. Nothing beyond that first line is read
into any record; the second and later lines and every later prompt are never
touched. Setting ``PROMPT_ENHANCER_CLAUDE_SESSION_TITLES=0`` in the environment
that launches Claude Code turns the read off entirely. The receiver source is
still scanned by test: ``prompt`` is read in exactly one place, behind that
switch, and the only string-typed fields on the minimized record remain the
two display labels, the pseudonyms, and the version identifiers.

## Not accepted by this ADR

Reading `~/.claude` through this hook surface (a separate, owner-authorized
read-only transcript reader is recorded in ADR 0011); any telemetry protocol
other than OTLP/HTTP JSON on loopback; a live-update watcher; any inference of task start, finish, or outcome from hook events;
any use of `tool_name` beyond categorization; provider-neutral persistence of
Claude display labels through the migration-5 label tables (a separate
migration is required); and any dashboard claim that a Claude session is
complete, calibrated, or comparable to a Codex one beyond the shared,
provider-tagged catalog.
