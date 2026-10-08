# MCP Store checkpoint 06d handoff

Date: 2026-08-30
Status: automated implementation complete; protected owner click-through and final Store UX acceptance remain
Runtime effect of the automated gate: synthetic package archives and in-process fixtures only; no real third-party MCP server, model runtime, visible terminal, retained connection or GPU allocation

## Outcome

Store-06d makes configuration-bearing MCPB packages inspectable before the user
can install or run them. The application now has an explicit, native-confirmed
configuration checkpoint instead of treating an uninspected package manifest as
an executable plan.

The inspection is deliberately non-executing. It may download the exact
checksum-pinned package into temporary staging, verify its digest and inspect
the bounded manifest configuration contract. It then discards the archive,
staging directory, manifest content and every configuration value. It does not
start a process, retain a connection, enumerate tools or grant Agent authority.

## Implemented behavior

- A local MCPB plan that declares configuration remains blocked with
  `configuration_inspection_required` until its exact package revision has a
  current inspection receipt.
- The read-only preview names the exact package, digest, expected effects and
  non-effects before native confirmation. The confirmed command is bound to the
  preview digest and request identity.
- Inspection supports the strict MCPB v0.3/v0.4 scalar configuration subset used
  by the installer: string, number, boolean, file and directory requirements;
  declared defaults; required values; exact `${user_config.NAME}` references in
  admitted arguments and environment entries. Unsupported or contradictory
  structures fail closed.
- Only content-free schema evidence is durable: management and plan identity,
  package/manifest/configuration digests, manifest version, archive size,
  requirement ids/counts, value-needed/default flags and inspection time.
- No configuration value, default value, manifest text, command, environment,
  endpoint, path, archive or staging location is returned by the API or written
  to SQLite. Required values are resolved just in time through the OS-backed
  vault for install/start; they are not copied into the database.
- A changed package, plan, manifest or permission contract invalidates stale
  inspection evidence and keeps install/runtime authority closed.
- Schema 27 adds a constrained current-inspection table and a unique current
  index. The 26-to-27 migration preserves older managed records without
  inventing inspection evidence.
- The Agent MCP Store now presents a prominent **Package configuration
  checkpoint**, loads the non-executing preview, requests native confirmation,
  and reports only digest/size/schema/count/time evidence afterward.
- The frontend parser rejects extra value-like fields, retained archives,
  process starts, connections, tool authority and server/receipt mismatches.

## Automated evidence

- MCP package/registry/server-management/runtime backend regression:
  **151 passed**.
- MCP server-management backend suite, including the private confirmed HTTP
  inspection journey: **72 passed**.
- OpenAPI export and privacy-contract suite: **6 passed**.
- Focused configuration contract/transport/Store UI suite: **67 passed**.
- Full frontend suite: **2,504 passed / 175 files**.
- Production frontend TypeScript/Vite build: passed.
- Generated OpenAPI TypeScript contract: regenerated and checked.
- Schema 26-to-27 migration subset: **5 passed**.
- Repository privacy scanner: passed.
- `git diff --check`: passed; existing line-ending warnings remain non-fatal.

All fixtures use fictional reserved identities, hosts, paths, values and
archives. No provider session, credential file or owner workspace content was
read.

## Protected live evidence

- The production frontend was rebuilt and the loopback app was restarted with a
  hidden process launch at `127.0.0.1:8765`.
- Health returned HTTP 200 with exactly one loopback listener.
- The restart produced **0 visible terminal windows**, **0 model runtimes** and
  **0 MCP host runtimes**.
- A retained synthetic Agent project and chat survived the reload.
- The MCP Store loaded its source/provenance, search, filters, plan states and
  truthful authority boundary without a console-visible route failure.
- No review-safe prepared plan existed in the live profile. The protected
  inspection button was therefore not fabricated or exercised against a real
  third-party package; its native-confirmed journey is covered by synthetic API,
  transport and UI tests and remains in the owner click ledger.

## Explicitly bounded support

- Optional configuration without a declared default may remain intentionally
  unset and is omitted. The current UI does not yet provide a separate optional
  customization editor.
- Composite, choice/list/object and non-exact interpolation forms are not
  accepted. They fail closed rather than being guessed.
- The inspection path proves safe schema discovery for exact MCPB packages. It
  does not claim that every historical or vendor-specific MCP package format is
  compatible.
- Final information architecture, tile/detail polish, live reconciliation,
  project tool-drawer integration and complete keyboard/visual acceptance belong
  to Store-06e.
- Malicious registry, logo, transport, DNS, schema, output, crash and child
  behavior remains the independent Store-07 adversarial gate.

## Owner click-later ledger

1. Open **Agent → Settings → MCP Store** and prepare one explicitly trusted,
   checksum-pinned configuration-bearing MCPB plan.
2. Confirm install is blocked by **Package configuration checkpoint** and the
   preview says no process, connection or tool authority will be created.
3. Click **Inspect package configuration**, review the native confirmation, and
   confirm the receipt shows metadata only—never a configuration value.
4. Confirm the required input controls appear only after inspection and that
   closing/reloading the app retains the schema state without retaining values.
5. Stop there unless the package itself has separately passed review; inspection
   is not installation or permission to run it.

## Next checkpoint

Store-06e is the active product slice: simplify the MCP Store and Agent tool
drawer into a coherent coding-chat experience with searchable source-provenanced
tiles, detail/install/health/permission states, project tool selection,
responsive and keyboard behavior, and live backend reconciliation.
