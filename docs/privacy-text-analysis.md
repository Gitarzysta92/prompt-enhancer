# Local Codex text-analysis boundary

This boundary is for an explicit, one-run `text_analysis` command. Standing
local-history consent can make the provider discoverable, but it does **not**
authorize a content read. The application must obtain a fresh per-run
confirmation for one selected pseudonymous session and must pass the user's
selected, named server-owned preset in that command. The public command accepts
only `preset_id` and the exact confirmation literal; it does not accept transcript
text, a client-defined task profile, or client-defined provider-read bounds.

`standard_engineering_v1` is analysis profile `standard_engineering` version 1.
It applies all ten metrics, expects action/target/outcome goal slots, leaves
task-specific constraint and deliverable denominators empty so those calculators
abstain, infers completion denominators conservatively, and fixes the read at 100
messages / 100,000 redacted characters. Codex's unavailable `ACTION` and `DECISION`
kinds still produce explicit abstentions. The profile key and version are stored
as immutable run provenance and participate in aggregation compatibility.

The source port is intentionally narrow:

```python
def read(
    *,
    selection: TextAnalysisSelection,
    grant: TextSourceAccessGrant,
    task_profile: TextTaskProfile,
) -> P1TextAnalysisInput: ...
```

The application-owned `TextAnalysisSelection` contains a provider, a
64-character HMAC session pseudonym, the `text_analysis` purpose, and bounds no
larger than 500 messages or 500,000 redacted characters; the current public preset
uses the smaller 100-message / 100,000-character bounds. The application-owned
`TextSourceAccessGrant` must carry a matching provider, session, and purpose, an
active per-run confirmation, the `redacted_content` tier, `local_only=True`, and
`content_persistence_allowed=False`. Construction of the source is inert; these
checks happen before its provider client is created. Codex is one adapter for
this provider-neutral port; a future Claude Code adapter does not change the
application command.

The provider adapter follows the documented [Codex App Server
`thread/read`](https://developers.openai.com/codex/app-server) surface. It first
resolves the selected HMAC against IDs returned by the current bounded
`thread/list` snapshot. Only that matching raw ID is passed to `thread/read` in
process memory. The raw ID is neither returned by the source nor accepted from
the application/API, and the source has no persistence port.

## Content allowlist

Only these documented `ThreadItem` fields can become analysis text:

- `userMessage.content[]` entries whose type is `text`;
- `agentMessage.text`, with a documented commentary or final-answer phase; and
- `plan.text`.

User image, local-image, `skill`, and `mention` entries are discarded after
inspecting only their type tag. Their URL, path, bytes, names, invocation
metadata, and any other fields are not read into a boundary DTO. Reasoning,
command execution and output, file changes and diffs, tool calls and their
arguments/results, searches, image views, review state, compaction items, and
unknown future item types are discarded. Unknown non-empty string user-input
tags are likewise discarded after their tag; missing, empty, or non-string tags
fail closed. A future item is not admitted merely because it adds a field named
`text`. Malformed allowlisted items, unsupported agent phases, and missing
required text still fail closed. This projection is versioned as Codex text
schema v3 and adapter 0.2.0, so immutable analysis provenance cannot mix it with
the earlier input projection.

Turn, item, fragment, input-character, and aggregate-character limits apply
before analysis. The returned deterministic window independently enforces the
server-owned preset's message and character budgets and focuses on the latest eligible
user request. All private wire text and redacted analysis text use `SecretStr`
and are hidden from normal representations. `SecretStr` is accidental-disclosure
protection, not encryption or memory zeroization.

Every `P1TextAnalysisInput` also declares a versioned
`available_message_kinds` capability. Every observed message kind must be a
member of that set. The Codex v3 text projection declares only `REQUEST`,
`RESPONSE`, and `PLAN`; it cannot silently represent command activity as an
`ACTION` or prose as a `DECISION`.

## Content-free source failures

Provider exceptions never cross the provider-neutral source port. The port
exposes only these bounded reason codes, and the command API maps them to stable
statuses without returning provider messages, paths, identifiers, or content:

| Reason code | HTTP status | Meaning |
| --- | ---: | --- |
| `source_schema_unsupported` | 503 | the allowlisted provider response no longer matches the supported schema |
| `no_analyzable_text` | 422 | the bounded response contains no supported text fragments to analyze |
| `provider_protocol_rejected` | 503 | the live bounded read was rejected or returned a malformed protocol response; schema preflight alone cannot prove that a particular session is readable |
| `selection_snapshot_miss` | 409 | the selected session is absent from the current bounded provider snapshot |
| `source_resource_limit` | 413 | a configured response-frame, turn, item, fragment, or character bound was reached |
| `source_timeout` | 504 | the bounded local provider read timed out |
| `provider_unavailable` | 503 | the local provider process or source implementation is unavailable |

The response shape is `{"detail":{"code":"...","message":"..."}}`, where
both fields come from closed application allowlists. Unknown implementation
failures become `provider_unavailable`; their original exception text is
discarded.

Codex currently returns `thread/read(includeTurns=true)` as one JSONL response
without a documented server-side text or turn projection. Metadata and
operational transports retain a 4 MiB response ceiling. Only an explicitly
confirmed text-analysis read uses a separate 32 MiB ceiling, with a single
buffered frame. The allowlisted parser then discards tool output and other
unsupported fields and applies the smaller content bounds above. Crossing the
transport ceiling returns `source_resource_limit`; it is not reported as a
provider protocol rejection and no partial score is fabricated.

## Redaction limits

The deterministic local redactor masks common credential assignments, bearer
tokens, JWT-like values, recognized provider-key forms, email addresses, URLs,
filesystem paths, IP addresses, international-format phone numbers, long token
strings, and unsupported control characters. It performs no filesystem or
network access.

Redaction is a privacy-reduction layer, **not anonymization**. It cannot reliably
recognize personal names, organization-specific identifiers, business facts,
secrets without recognizable syntax, all source-code literals, or every Polish
and English personal-data form. Redacted text, fingerprints, labels, embeddings,
and metrics remain sensitive derived data. The text output is ephemeral and must
not be logged, persisted, or sent to a remote service.

Language eligibility uses a versioned, deterministic local EN/PL lexical
detector. It returns English or Polish only with multiple discriminative signals,
returns mixed only when both signal thresholds are met, and otherwise marks the
message unknown. Unknown-language messages are excluded from lexical features
and reduce the result's analyzable-message coverage. A metric abstains when its
required observed kind has no supported-language content; an unrelated short
unknown reply does not erase supported prompt evidence. Unknown messages are
never relabeled merely to force a score. The detector version is
composed into `content_schema_version` and therefore into the analysis-window
fingerprint and persisted metric provenance.

Generic `agentMessage` text remains a `RESPONSE`. The ingress adapter does not
infer an observed action, decision, verification, or outcome from assistant
self-report. Metrics requiring an unavailable item kind explicitly abstain until a
separately calibrated and versioned candidate classifier is introduced.

After ingress, metric execution requires a second capability:
`P1LocalAnalysisGrant`, bound to the exact post-redaction window fingerprint.
The source grant cannot authorize metric execution, and the analysis grant
cannot authorize another provider read.
