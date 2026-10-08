# Agent checkpoint 08i handoff: safe orchestration continuation and document review

Date: 2026-08-27
State: implementation and synthetic validation complete; native owner acceptance remains pending

## Outcome

Agent-08i closes two gaps left outside the frozen parity ledger.

First, a controller turn that pauses for native review now has a safe
continuation path. `prompt-enhancer agent-controller wait` accepts the same
session plus the exact cursor returned by `turn`, then performs bounded event
observation without submitting a message and without requesting Stop. This lets
Codex, Claude Code, or another local orchestrator hand an approval to the owned
Agent window and continue the original turn instead of risking a duplicate
prompt.

Second, Markdown artifacts are now document-like to review. The digest-
revalidated viewer defaults to rendered GFM and offers an exact Source view.
Raw HTML is skipped, remote images are represented only by an inert notice, and
all links—including fragment and external links—remain non-clickable in an
artifact preview. Other text/code/data artifacts keep the exact plain-text
viewer; active document formats remain download-only; image and PDF validation
is unchanged.

This checkpoint did not launch the native Prompt Enhancer app, a native window,
a local model, a command tool, or a GPU workload. Synthetic headless Chromium
fixtures were used for UI validation.

## Controller v6 truth contract

`local-agent-orchestration.v6` and
`prompt-enhancer-agent-controller-cli.v2` make the new behavior explicit:

- settled means running, closing, stopping, and cleanup quarantine are all
  false, no approval is pending, and the observed cursor reached `last_seq`;
- `cleanup_unconfirmed` is a distinct controller outcome and can never be
  collapsed into settled;
- after `needs_native_approval`, `wait` resumes from the prior cursor without
  resubmission or Stop;
- a `wait` deadline returns `incomplete` plus its cursor and never mutates the
  session;
- a cursor ahead of the live session fails closed; and
- token-authenticated controllers still cannot approve protected actions or
  apply reviewed workspace mutations.

The Agent Controller card now displays the exact discovered v6 contract instead
of the stale hard-coded `v4` label and exposes the continuation command under
Connection & setup.

## Defect found by the complete gate

The first complete frontend run exposed one five-second timeout in an existing
Agent-page test that combined project creation, navigation, settings,
accessibility, draft retention, and file-drawer behavior. The test passed alone
at 4.95 seconds, proving it was an overloaded scheduling edge rather than a
product wait. It was split into two independently scoped behavior tests without
raising any timeout. Both focused tests and the complete rerun pass.

## Verification receipts

- Broader controller/artifact/release/OpenAPI backend gate: **57 passed**.
- Focused frontend controller, contract, viewer, and transport gate:
  **192 passed across 5 files**.
- Complete frontend gate: **2,049 passed across 153 files**.
- Complete populated-workflow Chromium gate: **66 passed** at 360 px and
  1,440 px.
- Generated OpenAPI/TypeScript parity: passed.
- Production TypeScript/Vite build: **533 modules transformed**.
- Python source and test compilation: passed.
- `git diff --check`: passed; Windows line-ending notices only.
- No stale controller v1 or orchestration v5 contract references remain in the
  active source, tests, frontend, or current documentation.
- Ports 8765 and 8766 had no listeners after validation.

All fixtures use fictional identities, paths, projects, chats, models, tokens,
and content.

The repository privacy scan still reports only the previously known untracked
binary screenshot `docs/checkpoint-agent-02-shell.png`; Agent-08i introduced no
new privacy finding.

## Deliberate boundaries

- `wait` observes an existing live chat; it does not create projects, start a
  model, spawn Codex/Claude, approve an action, or own an external process.
- Prompt Enhancer exposes the loopback orchestration surface. The external
  controller owns its process and deliberately selects what enters its context.
- Markdown rendering is a local inert review surface, not an active-document or
  network-fetch capability.
- Real Windows window ownership, model execution, Stop, process exit, and
  CPU/GPU cleanup still require the guarded owner acceptance from Agent-08g.

## Owner review later

In the bounded native acceptance, let one fictional write pause for approval.
Record the controller `turn` cursor, decide the action in the native window,
then call `wait` with that cursor. Confirm the original turn completes once,
with no duplicate user message and no unexpected Stop. Open the resulting
Markdown card, switch Preview/Source, and confirm its link text is inert.
