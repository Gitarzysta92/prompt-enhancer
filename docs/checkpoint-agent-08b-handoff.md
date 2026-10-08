# Agent-08b handoff: bounded external-controller client and setup

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload remains deferred

## Outcome

Codex, Claude Code, or another local orchestrator no longer has to hand-roll the
Prompt Enhancer Agent protocol or expose the local API token. The bundled
`prompt-enhancer agent-controller` command performs one bounded stdio JSON
exchange, uses the existing private token internally, communicates only with one
validated loopback origin, emits one machine-readable result, and exits.

The bridge supports content-free discovery, one manifest-declared JSON
operation, and a specialized finite Agent turn. It starts no application,
server, terminal, model runtime, Codex process, Claude process, or shell command.
Direct HTTP remains available through the same documented v4 endpoint when a
controller deliberately needs binary or SSE behavior.

## Implemented boundary

- `prompt-enhancer agent-controller-config` prints a token-free, content-free
  provider-neutral command contract and valid stdin envelope shapes.
- `prompt-enhancer agent-controller discover` loads the existing private token
  without creating application state, verifies the complete v4 manifest, and
  returns it in one JSON result envelope.
- `agent-controller invoke` resolves one operation from the verified manifest,
  substitutes exact encoded path parameters, passes bounded scalar queries and
  a bounded JSON object body, and accepts only the status/response mode declared
  for that operation.
- Generic invocation refuses unknown operations, malformed parameters, bodies
  on GET/DELETE, native-only routes, binary responses, and SSE before making the
  target request.
- `agent-controller turn` reads one exact session and submits one message only
  while idle. It validates every event page, advances a strictly monotonic
  cursor, fails closed on missed/truncated events, surfaces native approval, and
  stops only on the v4 terminal condition.
- An ambiguous message exchange is never retried. The client performs one event
  reconciliation; it continues only when the exact user event is observed and
  otherwise returns `submission_uncertain`.
- A turn deadline issues Stop at most once, then performs a separately bounded
  drain. Results distinguish `settled`, `needs_native_approval`,
  `submission_uncertain`, `stopped`, and `incomplete`.
- The HTTP transport accepts only `http` at an exact loopback origin, rejects
  credentials/path/query fragments in the base URL, disables environment
  proxies, refuses redirects, bounds request/response bytes, and never includes
  the token or server response body in a diagnostic.
- Sensitive `invoke` and `turn` calls require both an explicit CLI context-egress
  acknowledgement and a per-request record that the task was authorized and its
  redaction preview completed. Those records are validated but not echoed.
- The Agent **Connections & controller API** card now exposes copyable setup and
  discovery commands, explains that the bridge owns no process lifecycle, and
  keeps direct bearer HTTP as an advanced secret-store path.
- The canonical Agent plan records Agent-08a/08b as complete while keeping the
  remaining release-hardening, recovery, diagnostics, retention, native 320 px,
  and legacy-retirement gates open.

## Correctness repairs found during implementation

1. The v4 data model previously constrained field literals but did not itself
   reject a complete-looking manifest with missing routes, duplicate operations,
   a relabelled native apply, or an unsafe path. It now fixes exact counts,
   unique method/path pairs, local path grammar, required lifecycle operations,
   and the exact ten native operation names.
2. Direct bearer examples forced an orchestrator either to read the token or to
   reproduce secret injection. The stdio bridge now reads the existing token
   privately and never places it in arguments, setup output, result output, or
   exceptions.
3. Ordinary URL clients may follow redirects or honor environment proxy
   variables. The controller transport disables both and verifies the final
   origin before accepting a response.
4. A naive turn loop can duplicate a non-idempotent message after a connection
   timeout. The client records the pre-send cursor, performs one exact event
   reconciliation, and never automatically sends the message twice.
5. A generic operation bridge could accidentally turn native review into an API
   convenience feature. Native operations are rejected from the verified
   manifest before path resolution or transport access; server-side native
   confirmation remains the second independent barrier.
6. The first setup descriptor rendered the two allowed destination values as one
   non-valid sample string. It now emits a valid `local_controller` envelope and
   lists the complete destination enum separately.
7. The roadmap still said “Agent-08 next,” which obscured both completed
   controller receipts and the unfinished release-hardening work. It now names
   Agent-08a/08b truthfully and makes Agent-08c the next bounded slice.

## Verification receipts

- The focused controller/API/CLI/privacy suite passed **48 tests**.
- The controller client includes a real FastAPI synthetic lifecycle covering
  project creation, durable live-chat creation, one settled turn, workspace file
  reading, file-create preview, client-side native-apply refusal, and unchanged
  filesystem evidence.
- The broader Agent, catalog, history, artifact, attachment, workspace,
  runtime/model, cancellation, OpenAPI, native-presence, CLI and privacy suite
  passed **884 tests**, with **1 Windows symlink-privilege skip**.
- One old hardening test that intentionally starts a real hanging child command
  tree was deselected to avoid recreating visible process surprises. The three
  dedicated real-command process test modules were outside this non-spawning
  checkpoint; no claim is made for them here.
- The complete frontend gate passed **1,995 tests across 149 files**.
- The focused frontend manifest/transport/controller panel slice passed **177
  tests**.
- The complete Playwright gate passed **113 tests**. Controller setup passed at
  360 px and 1,440 px with the chat composer retained and no viewport overflow.
- The production TypeScript/Vite build passed with **527 modules transformed**;
  strict TypeScript, generated API consistency, Python compilation, and six
  OpenAPI export tests also passed.
- In-app rendered inspection at 1,280 x 720 confirmed the expanded setup,
  commands, native boundary, retained composer, zero command-row overflow, and
  zero horizontal page overflow.
- `git diff --check` reported no whitespace errors; Windows line-ending notices
  remain informational.
- The repository privacy scanner returned only the known pre-existing untracked
  binary finding. A synthetic credential-URL fixture that initially resembled an
  email address was rewritten rather than allowlisted; this checkpoint leaves no
  additional privacy finding.
- Zero Prompt Enhancer, Agent, or `llama-server` processes and zero relevant GPU
  allocations remained after validation. Ports 8765 and 8766 were closed. The
  existing synthetic Vite fixture remained bound only to 127.0.0.1:4173.

## Owner checklist for the later native reload

1. Reload a matching Prompt Enhancer build, open Agent, expand **Connections &
   controller API**, and confirm the setup/discovery commands appear with v4 and
   52/5/10 route counts.
2. With the Prompt Enhancer listener already running, execute
   `prompt-enhancer agent-controller-config`, then
   `prompt-enhancer agent-controller discover`. Confirm one JSON result per
   command and no token in the process list, terminal output, or copied setup.
3. Let a local Codex/Claude controller call `invoke` with a synthetic
   `list_projects` envelope after the per-task authorization/redaction review.
   Confirm malformed or unacknowledged envelopes fail with only a stable code.
4. Create a synthetic local-history project/chat through declared operations and
   call `turn` with one selected message. Confirm one user event, monotonic event
   sequences, a settled result, and no duplicate message after any induced
   connection ambiguity.
5. Read one synthetic workspace file and prepare one create/edit preview. Confirm
   that `invoke` returns `controller_native_review_required` for its apply and
   that only the native reviewed flow can change the file.
6. Trigger a harmless synthetic long turn with a short deadline. Confirm one Stop
   request, a finite drain, and a `stopped` or truthful `incomplete` result.
7. Stop/unload any real model used for optional acceptance and verify its process
   and VRAM allocation are gone.

These native/controller checks remain intentionally unpassed until the owner
reload. They must use synthetic content first and must never put a real token,
private workspace content, or unreviewed transcript into a model context.

## Next checkpoint

The next correct slice is **Agent-08c — non-spawning release-hardening harness**:
synthetic repeated runtime state transitions and long streams, crash recovery at
load/stream/approval/file/command/artifact/migration boundaries, opt-in
content-free diagnostics, and complete retention/delete/export verification.
Real model/GPU soak and the final 320 px native walkthrough remain owner-gated.
Legacy layout retirement stays last and requires explicit parity evidence.
