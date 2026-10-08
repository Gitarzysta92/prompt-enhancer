# MCP Store checkpoint 01 handoff

## Outcome

The Agent settings drawer now contains a real, searchable **MCP Store** backed
by the public Official MCP Registry. It is a read-only discovery checkpoint:
the page can search, filter, page through, and inspect normalized public server
metadata, but it cannot yet install, connect, update, uninstall, request a
credential, edit another client's configuration, or start a process.

This boundary is deliberate. Registry membership is provenance, not a safety
verdict, and package metadata is not executable authority.

## Tools that are usable today

The local model inside an Agent chat already has ten bounded workspace tools:

- read-only `list_dir`, `read_file`, and `search_text`;
- reviewed `write_file`, `create_directory`, `move_file`, `move_directory`, and
  `trash_file` operations;
- separately approved `run_command` and `fetch_url` operations.

Every protected operation waits for native review. File writes show a diff;
moves and removals are revision/path bound; command and fetch output remains
bounded. The Agent also already provides durable projects/chats, retained
history, branching, export, attachments, artifact/document cards, workspace
review, model placement/context controls, Stop, and restart recovery without
restoring approval authority.

Codex, Claude Code, and other local MCP clients can control that authored Agent
surface through the scoped loopback `/mcp/agent` endpoint. Its 19 default tools
are `agent_discover`, `agent_invoke`, `agent_open`, `agent_resume`,
`agent_fork`, `agent_export`, `agent_close`, `agent_catalog`, `agent_history`,
`agent_artifacts`, `agent_stage_attachment`, `agent_context`,
`agent_workspace`, `agent_propose`, `agent_propose_transaction`,
`agent_propose_lifecycle`, `agent_turn`, `agent_stop`, and `agent_wait`.
Native applies and approvals remain unavailable through MCP; model lifecycle
requires a separately granted connection scope.

That existing endpoint exposes Prompt Enhancer to an external orchestrator. It
does **not** make Prompt Enhancer an MCP client capable of hosting arbitrary
third-party servers. The latter is the remaining Store trajectory.

## Store-01 implementation

- `GET /v1/integrations/mcp-store/catalog` queries the Official MCP Registry
  through a no-proxy, no-redirect, bounded HTTPS client.
- Search, cursor, page size, response bytes, server count, packages, remotes,
  text, URLs, and timestamps are strictly bounded and normalized.
- The restart-safe fallback cache contains only normalized public registry
  metadata. It is exact-query keyed, size bounded, atomic, and never contains
  commands, environment variables, credentials, remote query strings, or tool
  output.
- `GET /v1/integrations/mcp-store/icons/{icon_key}` proxies only allowlisted
  HTTPS raster icons with type and byte limits. Entries without a trustworthy
  declared icon receive deterministic initials; a logo is never invented.
- Compact cards show title, identity, publisher, version, status, local package
  and remote transport facts, source/site links, and an explicit **Not
  managed** state.
- Search, local-package/remote-server filters, pagination with identity
  de-duplication, cached/partial truth, keyboard labels, forced-colors support,
  and responsive layouts are implemented.
- Every card displays a disabled **Install unavailable** action. No hidden
  command, package manager, remote connection, client edit, or worker exists
  behind it.

## Live defect found and repaired

The first real-browser pass caught a composition bug that the isolated router
fixture missed. The Store route produced `Cache-Control: no-store, private`,
but the application-wide security middleware did not classify the new path and
overwrote it with plain `no-store`. The strict frontend therefore rejected the
otherwise valid response. The middleware now preserves the private response
contract, and a full-app regression test covers that exact boundary.

The Store also reports safe failure classes without rendering an exception or
remote payload. A transient registry failure leaves Agent chat usable and
offers one explicit retry; no automatic retry loop is present.

## Validation

- Store backend: **13 tests passed**, including the full-app middleware,
  restart cache, query binding, malformed rows, exact icon-source hashing,
  untrusted/SVG rejection, transport bounds, authentication, and read-only
  routing.
- Broad Agent/controller/MCP backend: **194 tests passed**.
- Store frontend focus: **17 tests passed** across strict parsing, transport,
  safe failures, search, filters, pagination, cache/partial states, and the
  disabled installation boundary.
- Broad Agent frontend: **35 files / 449 tests passed**.
- The production TypeScript/Vite build passed with 556 modules. The Store is a
  separate lazy chunk; the pre-existing approximately 507 kB Agent-page chunk
  still triggers Vite's advisory and remains performance debt.
- OpenAPI export/generation/check, Python compilation, privacy scan, and
  whitespace validation passed during the checkpoint.
- Live `/agent` validation rendered 24 official entries, returned 11 results
  for `filesystem`, split those results into 10 local-package and one remote
  entry, expanded remote connection details, and paged the unfiltered catalog
  from 24 to 48 de-duplicated cards.
- The live desktop and 360 px passes had no horizontal overflow and no browser
  warning/error. The final runtime had one listener on 127.0.0.1:8765, none on
  8766, and no local-model process.

## Next bounded checkpoints

1. **Store-02 — inspect and plan.** Add a server detail view, versions,
   provenance, license/repository/package evidence, supported transport and
   runtime compatibility, required arguments/environment/credentials, proposed
   filesystem/network/process scope, and a deterministic install-plan preview.
   This remains non-executing.
2. **Store-03 — durable management model.** Add local installation records,
   revisions, per-project enablement, health state, update availability,
   credential references, and permission grants. Secrets must use an OS-backed
   private store and never appear in the database, logs, export, or model
   context.
3. **Store-04 — guarded host.** Implement hidden, supervised stdio plus bounded
   Streamable HTTP/SSE clients; MCP initialize/list-tools/call-tool validation;
   timeouts, cancellation, process-tree cleanup, loopback/egress policy,
   schema/result bounds, and content-free diagnostics.
4. **Store-05 — install/update/uninstall UX.** Turn the disabled card action
   into preview -> native confirmation -> execute -> verify, with a separate
   guarded uninstall flow and truthful rollback/cleanup uncertainty.
5. **Store-06 — Agent tool routing.** Bind enabled servers to selected projects,
   expose exact tool schemas to the chosen local model, show progress/tool
   cards and approval prompts in conversation, and retain only bounded receipts.
   An MCP tool must never inherit workspace or model-lifecycle authority merely
   because it is installed.
6. **Store-07 — adversarial validation.** Cover every admitted package and
   transport family, malicious schemas/results, credential prompts, crashes,
   hangs, cancellation, app restart, update/uninstall, project isolation, and
   zero orphan processes/terminal windows.

The Official Registry should remain the primary catalog. Package portals such
as npm or PyPI may enrich a selected registry entry in Store-02, but only through
allowlisted documented APIs and identity-bound provenance. Random marketplace
scraping or executing a portal-provided command is outside the safe design.
