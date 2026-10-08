# Agent-08d handoff: responsive and accessibility acceptance

Date: 2026-08-27
Status: synthetic implementation and acceptance complete; native owner review remains deferred

## Outcome

Agent-08d makes the Agent recovery/controller surface usable without pulling
attention away from the chat. The work is frontend-only and retains the exact
Agent-08c content-free backend contract.

- **Projects & chats health** remains behind both **Connections & controller
  API** and **Connection & setup**. It performs no request until **Run health
  check** is activated.
- A persistent atomic status region announces not-run, checking, unavailable
  and completed states. The region exposes `aria-busy` while the request is in
  flight rather than relying on a newly mounted result to be announced.
- Catalog and live observations render independently. A missing live snapshot
  no longer hides valid catalog counts; closed reason codes are translated to
  safe owner-facing explanations.
- Recovery work is a labelled **Next safe actions** region. No prompt, message,
  path, identifier, timestamp, artifact byte, attachment byte, exception detail
  or token is introduced.
- Health facts use the card's available width rather than the viewport. This
  fixes the three-column squeeze observed in the narrow desktop rail.
- **Peer folder sharing** is a separate collapsed disclosure. Expanding
  controller information no longer exposes the complete Team Folders form.
- A keyboard skip link moves directly from the Agent heading to the conversation,
  bypassing projects and settings when the responsive layout shows chat first.
- Connection summaries, health actions and primary run/model controls meet a
  44 px interaction floor. Focus remains visible in forced-colors mode and the
  reduced-motion path adds no animation.

## Synthetic acceptance fixture

The development-only Agent fixture now serves one internally coherent
`attention_required` hardening snapshot and records only how many times it was
requested. Browser acceptance proves the counter is zero before activation and
one after keyboard activation. The fixture contains only fictional projects,
chats, models, paths and events and performs no HTTP, native, filesystem, model
or GPU work.

The rendered check exercises 1,440 px and 360 px, then explicitly resizes the
mobile case to **320 px**. It verifies:

- conversation skip-link focus;
- keyboard opening of both nested disclosures;
- Team Folders remains hidden until separately opened;
- health is not requested automatically;
- atomic status and recovery-region semantics;
- 44 px connection, health, file-review and Send controls;
- forced-colors focus visibility;
- zero document or control overflow.

Direct in-app inspection reused an already-running synthetic development
listener. It showed one health request after activation, Peer Folder Sharing
still closed, zero horizontal overflow and the expected labelled status/action
regions. No screenshot was stored in the repository.

## Verification receipts

- Focused Agent page/controller/layout unit gate: **104 passed**.
- Focused controller browser gate: **2 passed** at desktop/mobile, including the
  explicit 320 px resize.
- Complete populated-workflow browser file: **62 passed**.
- Complete frontend gate: **2,004 passed across 150 files**.
- Complete browser gate: **113 passed**.
- Backend Agent hardening contract: **6 passed**.
- Production TypeScript/Vite build: **528 modules transformed**.
- Generated API parity and `git diff --check` passed.
- The unchanged privacy scanner reports exactly one finding: the known
  pre-existing untracked `docs/checkpoint-agent-02-shell.png` binary. It was not
  modified, removed, ignored or allowlisted.
- No Prompt Enhancer Agent process, `llama-server`, owned model process or known
  Agent/model GPU process remained. Ports 8765 and 8766 were closed. The same
  pre-existing loopback development listener on 4173 was reused and left
  untouched; no new server or native window was launched.

## Owner review later

1. Restart Prompt Enhancer normally and open one fictional Agent chat.
2. Press Tab to reveal **Skip projects and settings; go to conversation**, then
   activate it and confirm focus moves to the conversation card.
3. Open **Connections & controller API**. Confirm Controller API is visible but
   Peer Folder Sharing stays collapsed.
4. Open **Connection & setup**. Confirm there is no health result until **Run
   health check** is selected.
5. Run the check. Confirm only aggregate facts, safe states and recovery actions
   appear; no content, paths or identifiers appear.
6. Repeat at desktop and the narrowest native window. Confirm the transcript,
   Stop/file-review controls and composer remain usable without horizontal
   scrolling.

## Next bounded slice

Agent-08e prepares the owner-gated finish without running it: a feature-parity
ledger for legacy retirement and a guarded native/model smoke harness with
explicit startup, chat, file-review, Stop, unload, process-exit and GPU-release
receipts. The harness must default to no execution and cannot start a native app
or model without a deliberate owner action.
