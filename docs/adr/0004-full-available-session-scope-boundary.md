# ADR 0004: Full-available-session scope is an explicit completeness claim

## Status

Accepted as an ingress seam. Durable full-session incremental publication is
not yet implemented.

## Context

The local text ingress historically selected a bounded recent window using a
message and character ceiling. A complete bounded suffix is useful, but it is
not the same claim as complete available-session coverage. Reusing the suffix's
completeness flag for a full-session UI would make partial evidence look final.

The documented Codex `thread/read` response is decoded through a bounded,
allowlisted compatibility adapter. The current downstream P1 input permits at
most 500 messages and 500,000 redacted characters, while the durable model-watch
schema currently binds publications to at most 100 messages. Raising either
ceiling would not provide incremental ownership, restart safety, or bounded
memory by itself.

## Decision

- Provider-neutral selections now distinguish `bounded_recent` from
  `full_available_session`.
- Existing durable callers remain explicitly compatible with
  `bounded_recent` until the next persistence migration binds scope end to end.
- A caller can request `full_available_session` through the shared selection
  factory. Resource ceilings remain mandatory and do not redefine that scope.
- Every new Codex text result carries content-free scope metadata: requested
  kind, `complete` or `incomplete_source`, source-history completeness, fixed
  resource bounds, and bounded reason codes.
- Full available-session scope is complete only when the provider adapter proves
  complete source history and the selected window contains every eligible
  analyzable message.
- Hitting an adapter, message, or character limit produces
  `incomplete_source`; it never promotes the newest suffix to a complete
  session.
- Scope metadata participates in the ephemeral window fingerprint. No text,
  snippets, model prompts, logits, or explanations are added to persistence.

## Consequences

Small complete sessions can already be evaluated under the exact full-session
scope through the provider-neutral seam. Large sessions are truthfully
incomplete rather than silently partial.

The default durable watch cannot become full-session incremental until a later
append-only migration adds an exact scope identity and source completeness to
the canonical snapshot, lifts the 100-message publication assumption, and
stores only pseudonymous semantic-unit digests/lifecycles plus sufficient
statistics. The worker must then freeze closed units, recompute changed or open
units, and prove full/incremental parity with synthetic fixtures. This ADR does
not authorize storing redacted text or increasing resource ceilings without
those invariants.

## Required follow-up

1. Add a versioned full-session scope identity to durable attempts and snapshot
   seals.
2. Route manual and watch analysis through the explicit full-session selection.
3. Incrementally reconcile semantic units before model chunking; never rebuild a
   full-session model prompt.
4. Publish `incomplete_source` when the provider cannot prove complete history.
5. Add synthetic restart, append-idempotence, supersession, and full/incremental
   parity tests before changing the first-party default.
