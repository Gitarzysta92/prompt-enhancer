# ADR 0003: Offline provider-schema compatibility lifecycle

- Status: Accepted
- Date: 2026-08-09
- Scope: Codex, Claude Code, and future provider adapter releases

## Context

Provider wire contracts evolve independently from Prompt Enhancer. Treating one
installed provider version as a universal schema would either break frequently
or, worse, silently create metrics from incomplete evidence. Runtime parser
downloads and automatic decoder generation would add a code-execution and
supply-chain boundary to a privacy-sensitive local application.

Provider wire schemas, the provider-neutral canonical event model, SQLite
migrations, and metric definitions are separate versioned contracts. A provider
release normally changes only its compatibility adapter. Historical metric runs
retain their original adapter, schema-family, and metric provenance.

## Decision

Prompt Enhancer packages a closed, reviewed registry of decoder families. A
compatibility entry identifies a provider, documented source surface, wire-schema
family, exact tested provider versions, adapter and decoder versions, canonical
schema version, synthetic fixture corpus, supported capabilities, and release
evidence. Version ranges and a mutable `latest` alias are not compatibility proof.

Decoder families coexist instead of accumulating version branches inside one
parser. The application never downloads adapter code, discovers plugins, or
generates executable decoders at runtime. An unknown family or untested provider
version disables only the affected capability; existing content-free history and
immutable metrics remain available.

The release workflow is split into two trust zones:

1. A low-privilege acquisition job may obtain a pinned public schema export or
   official SDK artifact. It has no application secrets or user data and records
   upstream provenance through the package/release supply-chain process.
2. Generation, comparison, fixtures, and tests run offline with an empty temporary
   home, no provider credentials, no mounted provider state, no install scripts,
   no remote reference resolution, and bounded input size and depth.

Generated contracts are treated as untrusted review material. Automation may
open a diff but cannot merge it, activate a decoder, or publish a release.
Schema descriptions, defaults, examples, and remote references never become
executable code without review.

`scripts/check_provider_compatibility_manifest.py` is the final content-free
manifest gate. It reads one explicitly named bounded JSON file, accepts only a
closed vocabulary, requires exact versions and release evidence, and emits only
sanitized status codes. It performs no provider discovery, process invocation,
network access, runtime-response hashing, adapter update, or filesystem scan.

## Unknown and changed variants

- Additive fields on a known object are discarded by the provider allowlist.
- Unknown lifecycle or usage values remain unknown; dependent metrics abstain.
- Missing required structure, changed types, identity mismatches, malformed known
  variants, and pagination violations fail closed.
- An unknown tagged conversation variant is never inspected for content. Its
  presence makes extraction incomplete, and metrics requiring complete coverage
  abstain rather than score the remaining fragments as a complete conversation.
- Unknown token categories are never inferred or folded into a total.
- A runtime response is never hashed as a schema fingerprint; it may contain or
  be influenced by sensitive content.

## Provider policy

Codex uses only its documented App Server surface. A documented schema exporter
may supply review input in an isolated empty environment, but private JSONL,
internal databases, credentials, logs, and broad cache discovery are not fallback
sources.

Claude Code uses a pinned official Agent SDK/session-reader contract when that
adapter is implemented. A raw transcript decoder, if ever approved, needs a
separate ADR, exact-version synthetic fixtures, explicit selection, and cannot be
an automatic fallback. OpenTelemetry identity and path fields must be minimized
before persistence.

Cursor is unsupported until a documented, read-only historical or telemetry
surface is selected in its own ADR. This lifecycle does not authorize inspection
of Cursor's internal application databases or caches.

## Release gates

A decoder can be marked verified only when all of these are present:

1. pinned official contract/SDK provenance and license review;
2. deterministic offline generation and a human-reviewed semantic diff;
3. exact tested provider versions and side-by-side previous-family regression;
4. fictional positive, malformed, future-variant, resource-limit, and downgrade
   fixtures;
5. secret, personal-data, path, source-text, error, log, and persistence canaries;
6. property/fuzz tests plus fixed process, time, size, nesting, and pagination bounds;
7. read-only method/argument allowlists and proof of no provider mutation;
8. privacy review and a content-free local smoke attestation; and
9. a signed Prompt Enhancer release with a rollback path.

Synthetic tests prove software behavior, not live compatibility. A smoke
attestation records only the reviewed version/family decision; provider payloads,
paths, identifiers, counts, and examples do not enter the public repository.

## User experience

Unsupported analysis reports that the capability is paused, no score was created,
and provider data was not changed. It shows only safe version/family provenance.
“Update Prompt Enhancer” is offered only when the bundled release information says
a supporting release exists; otherwise the user sees “not supported yet.” There is
no unsafe override.

## Alternatives rejected

- **Runtime adapter downloads or auto-merge:** too much supply-chain authority.
- **Parse whatever fields happen to exist:** creates plausible but incomplete
  metrics.
- **Provider-version ranges without an upstream guarantee:** semantic compatibility
  cannot be inferred from ordering alone.
- **Automatic raw-cache fallback:** private formats are unstable and widen the
  credential and transcript boundary.

## Consequences

New provider releases can temporarily pause a capability. This is preferable to
silent corruption. The compatibility pipeline reduces response time while keeping
activation reviewable, reproducible, local-first, and provider-specific.
