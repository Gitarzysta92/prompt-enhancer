# MCP Store checkpoint 02 handoff

## Outcome

The read-only MCP Store can now open an exact version-bound safety and setup
review for a selected Official MCP Registry entry. The review explains what is
known from public registry metadata, what input and authority the option would
need, what risks are implied, and what still requires runtime verification.

This remains a non-executing checkpoint. Install, update, uninstall, process
hosting, remote connection, credential collection, project enablement, and
tool routing are still unavailable. The disabled Install control is truthful:
reviewing an entry grants no authority and performs no compatibility probe.

## Exact review boundary

- GET /v1/integrations/mcp-store/servers/{catalog_id}/review requires the exact
  normalized server name and version as query parameters.
- catalog_id is deterministically bound to that name and version. A mismatched
  path, name, version, response identity, or plan identity is rejected.
- The backend requests the exact Official MCP Registry version and its bounded
  version history through a no-proxy, no-redirect HTTPS client.
- Final origin, URL, content type, response size, schema shape, collection
  sizes, and text lengths are validated. A missing exact version is reported
  without rendering an upstream body.
- Version-history failure is isolated: exact review may remain available while
  the history section is explicitly partial or unavailable.
- Responses are authenticated, private, and non-cacheable.

## What the review shows

- exact server identity, version, status, description, source/site links, and
  publisher/provenance evidence;
- bounded version history with current-version identity preserved;
- each declared local package or remote transport as a separate install option;
- registry-declared runtime arguments, environment/header requirements, secret
  classification, and whether user input is still required;
- package integrity evidence when supplied by the registry;
- fixed remote host and TLS facts, or an explicit template-requires-
  configuration state without exposing URL paths or query strings;
- deterministic process, filesystem, network, credential, and supply-chain
  risk facts;
- platform, runtime, package-manager, MCP-handshake, schema, and tool-list
  compatibility as unknown until a later guarded host verifies them;
- a deterministic 64-character plan revision suitable for binding a future
  native confirmation to the reviewed inputs.

The normalized response never returns a command to execute, a secret or
default value, a placeholder value, a choice value, a remote URL path/query,
tool arguments/results, or local file content.

## Agent experience

- Store cards now have Review safety & plan when an exact review is available.
- The review opens inside Agent settings without discarding search, filters,
  pagination, or the selected catalog state.
- Back returns to the same catalog view.
- Risks, requirements, provenance, versions, install options, compatibility
  unknowns, and remaining safeguards are separated into scannable sections.
- Local-package and remote-template options are presented truthfully; neither
  is mistaken for verified compatibility.
- Install remains disabled and states which guarded checkpoints are missing.
- The layout was checked at desktop and 390 px without document-level
  horizontal overflow. The browser produced no warnings or errors.

## Validation

- Store backend and OpenAPI focus: **24 tests passed**.
- Broad Agent, workspace, runtime, controller, and MCP backend:
  **836 tests passed** with one unrelated deprecation warning.
- Focused Store parser, transport, and UI: **4 files / 27 tests passed**.
- Broad frontend: **73 files / 1,115 tests passed** in a clean non-parallel run.
- Production TypeScript/Vite build passed with 557 modules. The existing
  approximately 507 kB Agent chunk advisory remains performance debt.
- OpenAPI export/generation/check, Python compilation, privacy scan, and
  whitespace validation passed.
- Live review passed for one real local npm-package entry and one real SSE
  remote entry. The UI showed only bounded provenance, requirements, host, and
  risk facts; no endpoint path/query or input value was exposed.
- The live app finished with one loopback listener, no secondary listener, no
  local-model process, and no terminal or console descendant in its process
  tree.

## Remaining bounded checkpoints

1. **Store-03 — durable management model.** Add local installation records,
   revisions, per-project enablement, health/update state, permission grants,
   and references to secrets held by an OS-backed private store. No secret may
   enter the database, logs, export, or model context.
2. **Store-04 — guarded host.** Add hidden supervised stdio and bounded
   Streamable HTTP/SSE clients, MCP initialization/list-tools/call-tool
   validation, cancellation, deadlines, result/schema limits, egress policy,
   and verified process-tree cleanup.
3. **Store-05 — guarded install/update/uninstall.** Implement preview, native
   confirmation, execution, verification, and truthful rollback/cleanup states.
4. **Store-06 — project tool routing.** Bind explicitly enabled servers to one
   selected Agent project, expose exact schemas to the local model, and render
   progress/tool/approval cards without inheriting workspace or model authority.
5. **Store-07 — adversarial validation.** Exercise malicious metadata,
   arguments, schemas and results; credential flows; crashes, hangs and Stop;
   restart/update/uninstall; project isolation; and zero orphan processes or
   visible terminal windows.

The Official Registry remains catalog and provenance input, not a security
approval. Package portals may later enrich an identity-bound selected entry
through documented allowlisted APIs, but portal scraping or executing a
registry-provided command is outside this checkpoint.
