# MCP Store checkpoint 03 handoff

## Outcome

The MCP Store can now save an exact reviewed Registry option as a durable,
non-executing management plan. Prepared plans survive application restart,
remain bound to the reviewed server version, option and plan digest, and can be
reopened from Agent settings.

This checkpoint does **not** install a package, connect an endpoint, start a
process, expose a tool, or edit an external client's configuration. Every
receipt fixes those effects to `false`, and the UI continues to show **Install
unavailable**.

## Durable management boundary

- A schema-v12 SQLite migration adds bounded server-plan, declared-requirement,
  project-binding, mutation-request and opaque secret-reference records.
- Creating a plan re-fetches the exact Registry review and rejects a changed
  catalog identity, version, option, plan revision, unsupported option, or
  inactive server before persistence.
- Plan creation, project changes, secret storage and secret removal each require
  local authentication plus one exact native user-presence confirmation.
- Every mutation carries a 128-bit request identity. Replays are idempotent;
  altered reuse, stale revisions and partial permission grants fail closed.
- Project bindings are scoped to one existing Agent project. Enabling a future
  plan requires every inferred permission, but its effective state remains
  `inactive_host_unavailable`; it grants no current tool authority.
- Installation, host, health, update and routing fields are durable truthful
  placeholders: `not_installed`, `not_started`, `not_checked` and `inactive`.

## Credential boundary

- Secret input is accepted only by the native-confirmed mutation route and is
  handed directly to Windows Credential Manager as a bounded `SecretStr`.
- SQLite retains only an opaque deterministic reference and content-free state.
  API responses and model context contain neither the secret nor a retrievable
  vault identifier.
- The UI uses a password control, clears the value after a verified store, and
  never displays it again.
- Store/removal transitions are restart-safe and truthfully distinguish
  pending, stored, failed and cleanup-required states.
- A retry reuses the same request identity and exact vault target, so an
  ambiguous prior OS-vault write or cleanup failure can be reconciled without a
  stale-revision loop.
- The non-Windows/unavailable adapter fails closed. No fallback secret file,
  database column, log entry or browser persistence was added.

## Agent experience

- **Prepared plans** appears above the MCP catalog and restores saved plan cards
  on reload.
- A reviewed active option can be saved only from its exact safety/setup review
  and only when native user presence is available.
- The plan view separates immutable identity, future project permissions,
  configuration readiness, vault state and the still-locked execution gate.
- All inferred permissions must be checked before a project plan can be saved;
  disabling the plan clears its grants.
- Secret controls distinguish first store, retry, removal, cleanup retry and
  reconciliation-only states without claiming the credential is usable by a
  host.

## Validation

- Broad selected Agent, MCP, database-migration, user-presence and OpenAPI suite:
  **173 tests passed** with one dependency deprecation warning.
- Complete Agent-page plus Store UI/contract/transport focus:
  **4 files / 153 tests passed**.
- The narrower Store UI/contract/transport set contributes **30 passing tests**,
  including strict response parsing, exact native path/body confirmation and
  rejection of secret-bearing or incoherent payloads.
- Production TypeScript/Vite build passed. The existing approximately 507 kB
  Agent chunk advisory remains performance debt, not a correctness failure.
- OpenAPI export/generation/check, repository privacy scan and whitespace
  validation passed.
- Windows Credential Manager behavior was exercised through a fake Win32 API
  at the exact opaque target. No real credential, model, MCP package, remote MCP
  endpoint or owner project was used.

## Owner click checklist

After reloading the native Agent window:

1. Open **Agent settings → MCP Store** and confirm the catalog remains usable.
2. Open an active server's **Review safety & plan** page. Confirm **Save prepared
   plan** asks for native confirmation and **Install unavailable** stays locked.
3. Return to the Store and confirm the plan appears under **Prepared plans** and
   reopens with install, host, health, update and routing shown as inactive.
4. If an Agent project exists, confirm every listed future permission must be
   checked before **Save project plan** enables. Saving must still report
   **Planned · host unavailable**.
5. If the option declares a secret, confirm the value field is masked and is
   empty after successful OS-vault storage. Do not enter a valuable production
   credential for this visual review.

## Remaining bounded checkpoints

1. **Store-04 — guarded host.** Add invisible supervised stdio and bounded
   Streamable HTTP/SSE clients; validate MCP initialization, protocol/version,
   tool schemas, cancellation, deadlines, size limits, egress decisions and
   verified process-tree cleanup. This is the next implementation slice.
2. **Store-05 — guarded install/update/uninstall.** Add an exact preview, native
   confirmation, package/endpoint change, verification and truthful rollback or
   cleanup state.
3. **Store-06 — project tool routing.** Route tools only from explicitly enabled
   servers into one selected Agent project and render progress, result and
   approval cards without inheriting workspace/model authority.
4. **Store-07 — adversarial validation.** Exercise malicious metadata, schemas
   and results; credentials; crashes, hangs and Stop; restart/update/uninstall;
   project isolation; and zero orphan or visible-terminal processes.

The Official Registry remains discovery and provenance input, not a security
approval. A prepared plan is durable intent, not an installed or trusted MCP
server.
