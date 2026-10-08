# WP-23: Verified requirement coverage foundation

Status: **pure application-contract slice implemented; live publication and
operability deliberately unchanged**

## Outcome

This checkpoint establishes the first dependency-safe authority path for
`outcome.verified_requirement_coverage` without adding persistence, a public
route, provider authority, or a new live metric-projection identity.

The path is:

1. an owned-native review confirms every eligible user clause under the frozen
   r6 requirement-plan contract;
2. the application reuses that snapshot's installation-keyed r6 fingerprint
   and issues one content-free verification opportunity for every active
   requirement, preserving its exact identifier, coordinate, and order;
3. a local objective verifier may issue one typed `passed`, `failed`, or
   `unknown` result with a keyed receipt commitment, or an owned-native user
   action may issue a separately typed `accepted`, `rejected`, or `unknown`
   acceptance authority;
4. the append-only objective projector replaces only
   `outcome.verified_requirement_coverage`; the other four objective outputs
   retain their frozen r3 rules.

No action-completion state, assistant completion statement, model judgment, or
untrusted producer claim can inhabit either accepted result authority type.

## Contract identity and privacy

The contract is local-only and content-free. It records opaque installation-
keyed identifiers, exact r6 coordinates, bounded counts, typed states, safe
version identifiers, and authority fingerprints. It contains no prompt text,
provider payload, paths, commands, output, account identity, or model-authored
proof.

The first identities are:

- evidence schema: `requirement-verification-evidence-v1`;
- policy: `app-issued-reviewed-requirement-verification-v1`;
- opportunity issuer: `reviewed-r6-requirement-opportunity-issuer-v1`;
- objective result issuer: `local-objective-verification-result-issuer-v1`;
- explicit acceptance issuer:
  `native-explicit-requirement-acceptance-issuer-v1`;
- pure objective integration:
  `reviewed-requirement-verification-objective-projection-v1`.

The immutable objective receipt bound remains 100. An authoritative active set
larger than 100 is not truncated and does not publish a partial denominator.

## Projection truth table

| Authority state | Projection |
| --- | --- |
| Confirmed r6 set has zero active requirements | `not_applicable` |
| R6 authority missing or invalid | `unknown`, authority missing |
| App opportunity set missing | `unknown`, known r6 eligible count retained |
| Opportunity/result binding or fingerprint invalid | `unknown`, no partial value |
| Any result missing or typed `unknown` | right-censored `unknown` with resolved, met, and eligible counts |
| Every opportunity has one typed pass/fail or accept/reject authority | exact known fraction |
| Active set exceeds 100 | bounded `unknown`, never truncation |

A requirement may have at most one authority record in this first slice. An
objective result and explicit acceptance cannot silently compete for the same
opportunity.

## Synthetic gates

`tests/test_requirement_verification_evidence.py` covers:

- exact r6 fingerprint, order, identifiers, coordinates, confirmation, and
  proposal ownership;
- complete and zero-sized active sets;
- typed pass, fail, unknown, accept, and reject outcomes;
- missing-result right-censoring;
- missing, duplicate, and foreign opportunities and results;
- cross-authority duplication;
- the greater-than-100 receipt bound;
- rejection of assistant/model authority labels;
- version and fingerprint tampering; and
- replacement of only the verified-requirement output in the pure v4 objective
  integration.

`tests/test_metric_operability.py` separately pins that this foundation does
not change the current r7 / `metric-operability-v3` release truth.

## Deferred dependencies

This slice is not live operability. A later append-only wave must design and
review all of the following together:

- native review/issuance workflow and expiration semantics;
- durable proposal, decision, binding, and publication receipts;
- database migration 58 or later (migrations 1-57 remain immutable);
- a new live projection/publication identity rather than rewriting r7;
- readiness reason/version updates;
- private authenticated API and generated-client changes;
- provider or local verification-source composition with objective provenance;
- restart, race, stale-window, deletion, migration-upgrade, and end-to-end UI
  gates.

Until that wave is complete and independently validated, the all-twenty
operability partition remains 16 shipped conditional paths, zero task-profile
configuration gaps, four provider/extractor gaps, and zero model-authoritative
measured metrics.
