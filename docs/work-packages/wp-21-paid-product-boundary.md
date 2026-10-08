# WP-21: accounts, entitlements, billing, and hosted deep analysis

Status: **contract and development-emulator tranche planned; production
activation requires separately supplied infrastructure and credentials**

## Outcome

Prompt Enhancer should remain fully useful as an offline, local application while
offering optional paid capabilities for team synchronization and explicitly
approved hosted analysis. Login and payment may unlock a remote service; they
must never become prerequisites for local analysis, local history, export,
deletion, local social history, or received files.

The mergeable tranche is a closed, synthetic development foundation. It does not
listen remotely, charge a real payment method, contact an identity provider, or
send content to an LLM provider.

## Non-negotiable credential boundary

A tenant-scoped job can target only official commercial provider API adapters.
The destination type does not contain Codex CLI, Claude Code, manual import, or
another user-bound local execution path.

The installed Codex and Claude CLIs authenticate as the person who owns the
machine. They are never a multi-user backend, never selected by tenant input, and
never made reachable through a paid job validator. This prohibition is enforced
by a separate closed destination enum and persistence constraint, not only by
documentation.

## Bounded contexts and stores

Billing and hosted jobs do not become new responsibilities of the numeric team
snapshot control plane.

| Context | Owns | Must not own |
|---|---|---|
| Local analyzer | sessions, redaction previews, approvals, metric receipts, local history | accounts, subscriptions, payment events |
| Identity | account pseudonym, issuer/subject binding, tenant binding, auth session, device proof | email profile, prompt content, billing events |
| Control plane | organizations, memberships, roles, clients, devices, content-free sync authorization | payment ledger, provider requests, message/file plaintext |
| Billing | checkout intent, signed webhook fence, entitlement ledger, spend holds and settlements | session/project/metric identity or analyzed content |
| Deep analysis | approved tenant job, provider/model/retention/cost binding, structured result receipt | personal CLI credentials or unapproved source text |

The analyzer keeps its existing SQLite database. Development identity, billing,
and tenant-job persistence use a separate database and migration ledger.
Production adapters use separately credentialed PostgreSQL schemas. The only
cross-context tenant key is the opaque organization identifier; billing cannot
answer which session or metric consumed a charge.

## Account and OIDC boundary

The account model stores only:

- a server-issued account identifier;
- a reviewed issuer identifier;
- an installation-keyed pseudonym of `issuer + subject`;
- an opaque tenant-to-user binding; and
- bounded authentication-session and nonce state.

OIDC tokens are verified for issuer, audience, signature, expiry, and a single-use
nonce. Email, name, avatar, username, groups, raw subject, access token, refresh
token, and the original ID token are discarded unless a later contract and
privacy review explicitly require them. Development uses a locally signed static
issuer emulator; a real discovery/JWKS adapter remains unregistered.

Membership creation, invite acceptance, role change, device enrolment, and API
client issuance are application use cases protected by the same server-resolved
authorization policy as reads and revocations. Infrastructure fixture helpers do
not bypass that boundary.

## Developer API clients

API clients are tenant-bound, subject or service-account-bound, expiring,
revocable, and restricted to a closed scope set. Proposed paid scopes include:

- submit/read hosted jobs;
- read/administer billing; and
- the existing numeric snapshot and audit scopes.

New access actions are default-denied unless their required scope and current
membership, role, device, client, and entitlement all pass. Raw SQL, transcript
content, unrestricted file access, and personal CLI execution are never API
scopes.

## Billing ledger

The billing service owns an append-only ledger. Webhook events are verified by a
registered algorithm and fenced by provider event identifier plus content
digest:

- first valid event applies one ledger delta;
- replay with the same digest is an idempotent no-op;
- the same identifier with a different digest is a conflict;
- stale or incorrectly signed events are rejected; and
- consumed-event fences survive subscription deletion, preventing resurrection
  by replay.

Ledger entries represent grants, revocations, expiry, refund, and adjustment as
signed deltas with effective intervals. The current entitlement is a projection
over the ledger and satisfies the control plane’s read-only entitlement port.
The control plane never writes billing state.

Development checkout and webhooks are synthetic and never contact Stripe. Real
Checkout, Customer Portal, price identifiers, tax/VAT, refund policy, webhook
secret, and customer records require the owner’s legal Stripe account and a
separate activation review.

## Spend and hosted-analysis jobs

Every remote job performs these steps in order:

1. resolve the credential-bound tenant principal;
2. verify current membership, device, client scopes, and paid entitlement;
3. reserve estimated spend under user and organization caps;
4. consume one exact, unexpired redaction-preview approval;
5. verify provider, model, window fingerprint, metric set, redactor, destination,
   retention, size, and cost all match the approval;
6. invoke the selected official-provider port;
7. validate the structured response and persist only reviewed result receipts;
8. settle actual provider-reported cost; and
9. audit fixed identities and reason codes without content.

Entitlement authorizes payment; it never authorizes disclosure. Automation can
request a preview but cannot approve remote transmission.

Spend uses a two-phase hold/settlement ledger. Concurrent submissions cannot
oversubscribe a cap. Missing provider usage produces `cost_unknown`, keeps the
hold for reconciliation, and never becomes zero. Cancellation, provider failure,
membership/client/device revocation, and timeout have explicit settlement rules.

## Provider adapters

The application port admits only official OpenAI and Anthropic API destinations.
A development synthetic adapter produces fixed, content-free judgments.
Production adapters may be implemented against official APIs but are composed
only when all of the following exist:

- an owner-supplied commercial API account and key in approved secret custody;
- exact model allowlist and version policy;
- provider retention/training terms and region;
- per-user and per-organization budgets;
- request/response size and time limits;
- a reviewed structured response schema;
- egress logging that never records payloads; and
- an incident and deletion policy.

Absent any prerequisite, product readiness reports a fixed gap and the provider
call path is unconstructible.

## Readiness and configuration

Paid-product readiness is a new contract, separate from the settled development
team-control-plane readiness vocabulary. It reports identity, directory writes,
billing, entitlement projection, provider credentials, retention approval,
spend controls, remote transport, durable store, backup, and production
monitoring as exact closed states.

Identity, billing, and deep-analysis development APIs each require an exact
default-off setting, an explicitly composed service, and a principal resolver.
The global analyzer cost mode remains offline-only. Production readiness and
remote transport remain false in the development tranche.

## Privacy boundary

- The identity store contains no profile data beyond pseudonymous authentication
  binding.
- The billing store contains no session, project, metric, prompt, snippet,
  explanation, or provider-output identifier.
- Provider plaintext exists only in the approved request lifecycle and provider
  retention class disclosed to the user.
- Structured results are treated as sensitive derived data and remain local
  unless a separate allowlisted numeric sharing policy applies.
- Cache headers for all identity, billing, and hosted-analysis routes are
  `no-store, private`.
- Deletion, export, revocation, and entitlement lapse never require an active
  subscription.

## Mergeable development tranche

1. Add the tenant-job destination type that excludes every personal/local CLI
   destination.
2. Add identity, billing, and deep-analysis contracts, ports, services, and
   synthetic adapters.
3. Add server-authorized membership/device/client lifecycle use cases.
4. Add the append-only entitlement/spend ledger and signed webhook replay fence.
5. Add a product-readiness contract and local authenticated route.
6. Add exact default-off composition gates and private cache headers.
7. Regenerate OpenAPI and the strict browser client without exposing secrets.
8. Keep all real adapters unregistered and every production flag false.

## Release attack matrix

1. Tenant A cannot read, submit, settle, or cancel tenant B’s job or billing
   record, including guessed identifiers.
2. A tenant job cannot name Codex CLI, Claude Code, manual import, or a local
   device destination at the type or database boundary.
3. Replayed webhook applies once; conflicting reuse, stale timestamp, incorrect
   signature, and deleted-subscription resurrection all fail closed.
4. Two concurrent submissions competing for one remaining spend allowance result
   in one hold.
5. Missing usage becomes unknown and does not release or zero the hold.
6. Expired/revoked membership, device, client, session, nonce, approval, or
   entitlement denies the operation at the correct boundary.
7. Entitlement lapse and network absence do not affect local analysis, history,
   export, deletion, local social history, or received files.
8. OIDC wrong issuer/audience/signature/nonce/expiry is rejected without an
   account-enumeration oracle.
9. Remote provider invocation cannot occur without the exact consumed approval
   and spend hold.
10. Synthetic secret, API-key, email, card, path, hostname, transcript, and
    output canaries are absent from every new database, audit event, log, OpenAPI
    example, and generated client.

## Production activation still requires

- a domain, TLS, deployment region, monitoring, backups, and incident response;
- a reviewed identity provider and email/recovery policy;
- tenant PostgreSQL/RLS adapters and executed database attack tests;
- a legal Stripe account, prices, tax/VAT/refund terms, and webhook secret;
- official OpenAI/Anthropic commercial accounts, keys, retention settings, and
  budgets;
- controller/processor decisions, privacy notices, DPA/subprocessor review,
  retention and data-subject workflows; and
- an independent security review.

None of these prerequisites is simulated into a production-ready claim.
