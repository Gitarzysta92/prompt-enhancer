# Claude Code hooks r7 provider checkpoint

- Status: **PARTIAL — not release-operable**
- Provider surface: documented Claude Code command hooks plus documented
  loopback OTLP/HTTP JSON telemetry
- Hook contract: `claude-code-hooks.v1`
- Receiver: `claude-code-hook-receiver-1`
- Adapter: `claude-code-hooks-adapter-1`
- Source schema: `claude-code-hooks.receipt-clock.v1`
- Admitted-read boundary: `claude-code-hooks.admitted-read-boundary.v1`
- Readiness receipt: `claude-code-hooks.r7-readiness.v1`

## Outcome

This checkpoint closes the stable-read and provenance-routing gaps that can be
closed truthfully. One explicit SQLite read transaction now captures the hook
session, every admitted hook event, the joined telemetry session, and every
admitted telemetry request. Dense sequence, count, identity, session ownership,
and a content-free boundary commitment are revalidated before use. The adapter
consumes that atomic snapshot instead of mixing separate hook and telemetry
reads.

The checkpoint does **not** promote
`logic.requirement_action_traceability`. The operability partition remains
16 shipped conditional paths, 0 task-profile gaps, and 4 provider/extractor
gaps.

Joined hook/OTLP rows also require the telemetry summary and its nested
counters to carry the exact hook session and project identities. OTLP's
documented missing-cwd project placeholder is recognizable after restart and
may be replaced only for the same pseudonymized provider session by that hook
session's project identity. Unrelated sessions and conflicting
non-placeholder project identities are never reconciled.

## Release-invariant matrix

| R7 release invariant | Result | Evidence / blocker |
|---|---|---|
| Stable source boundary | Proven for locally admitted rows | One SQLite read transaction plus `claude-code-hooks.admitted-read-boundary.v1` commitment |
| Stable source order | Proven for locally admitted rows | Exact dense `0..N-1` hook and telemetry-request sequences; duplicate, gap, reorder, or cross-session rows fail closed |
| Complete provider-event delivery | **Not proven** | Owner-pasted hook configuration is not attested; fail-silent receiver contention can drop an invocation; sequence numbers cover received calls only |
| Complete safe-action enumeration | **Not proven for the provider session** | Exact admitted action enumeration is available, but it cannot establish the provider denominator while delivery is unproven |
| Same-read content-free candidate metadata | Implemented for the atomic admitted snapshot | Metadata fingerprints bind event identity, sequence, kind, tool category, receiver time, duration, family, and state |
| Bounded ephemeral redacted invocation/effect descriptors | Validator implemented; production source unavailable | Process-only batches are bounded, non-persistable, exact-boundary checked, and fail on metadata drift, truncation, controls, or redactor drift. The command receiver exits after each event and supplies no long-lived batch to native review |
| Descriptor survival across restart | Correctly unavailable | Descriptor strings are never reconstructed from SQLite; restart therefore removes authority instead of manufacturing it |
| Clock authority | Receiver-clock provenance retained, ambiguity named | Sequence is authoritative admitted order; equal or inverted receiver timestamps set `receiver_clock_ambiguous` and never get sorted into apparent certainty |
| Provider/adapter/schema provenance | Exact | Hook sessions resolve the hook safe-event descriptor; transcript sessions retain the isolated transcript descriptor; an unregistered combination fails closed |
| Capability reporting | Honest downgrade | Missing OTLP capture reports `TOKEN_USAGE=unknown`; compatibility names `complete_delivery_unproven` and `ephemeral_descriptors_unavailable` |
| Raw content persistence or logging | None added | Readiness and descriptor-validation results contain only closed states, counts, versions, pseudonyms, and content-free fingerprints |

## Why the ceiling is partial

The documented command-hook integration has no objective signal proving that
the exact complete hook configuration was installed and invoked for every
eligible provider event. The receiver must also remain fail-silent to avoid
disturbing Claude Code, so a lock timeout is an unknowable missing invocation,
not a visible sequence gap. A loopback in-memory descriptor endpoint could
solve descriptor lifetime, but by itself it would not prove complete delivery.

Promotion therefore requires a documented provider boundary that objectively
attests complete event coverage, or another reviewed mechanism that proves the
installed configuration and every delivery without blocking the provider
session. Until that exists, both mandatory blockers remain in every production
readiness receipt:

- `complete_delivery_unproven`
- `ephemeral_descriptors_unavailable`

## Adversarial synthetic coverage

The checkpoint tests only reserved synthetic identities and content. It covers:

- duplicate, reordered, missing, and cross-boundary admitted rows;
- corrupt source commitment and stale cursor/boundary identity;
- foreign telemetry-summary and nested-counter session/project identities;
- hook-first and telemetry-first placeholder reconciliation, restart,
  unrelated-session isolation, and conflicting non-placeholder refusal;
- receiver-clock inversion and unknown hook variants;
- descriptor/candidate metadata drift and descriptor snapshot drift;
- restart loss, incomplete descriptor sets, redactor drift, control characters,
  and truncation refusal;
- candidate overflow without partial output;
- unknown and unsupported provider versions;
- telemetry absence and capability downgrade;
- exact hook-versus-transcript descriptor routing and unregistered-provenance
  failure;
- absence of raw invocation/effect content in receipts, logs, and SQLite; and
- unchanged 16/0/4 operability with no r7 promotion.

## Validation

The synthetic provider gate passed with no failures:

- focused hook-readiness, adapter, receiver, and telemetry gate:
  **62 passed**;
- broader affected provider, receiver, telemetry, ensemble, registry,
  compatibility, and operability gate: **141 passed**;
- full source-tree Python compilation: passed;
- repository privacy scan: passed; and
- diff whitespace check: passed.

These checks prove the code behavior and its fail-closed adversarial cases.
They do not establish production provider delivery completeness, and this
document does not infer production-source truth from synthetic tests.
