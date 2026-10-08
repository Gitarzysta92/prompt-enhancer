# Agent checkpoint 11f handoff

## Outcome

A dedicated Agent-window route now recovers the exact durable catalog chat
after an application restart clears its live in-memory session. The automated
Agent-11 project/session/chat parity implementation is complete; a native owner
restart walkthrough remains pending.

Before this checkpoint, `/agent/window/<session>` checked the bounded live
session list and then the direct live-session endpoint. A definitive 404 was
immediately presented as “this in-memory session is no longer available,” even
when the same identifier still had retained history or truthful metadata in the
durable Agent catalog. The selection channel already knew how to perform this
fallback, but initial route hydration did not.

The initial route resolver now asks the durable catalog only after a definitive
live 404. An exact retained record opens its bounded saved timeline; an exact
metadata-only record opens the truthful history-unavailable card. Only absence
from both live memory and the durable catalog produces the missing-session
screen.

## Correctness boundaries

- A non-404 live-session error remains a connectivity/error state. It is not
  hidden by a catalog fallback.
- The catalog response must match the exact requested session identifier.
  Mismatched data fails closed as missing.
- Route lookup remains abort-owned. Changing the dedicated route, transport,
  or component lifetime aborts the old live/catalog chain; a late record cannot
  replace the newer route.
- A retained route restores visible messages and bounded receipts only. It does
  not restore write, command, web, approval, or reusable mutation authority.
- A metadata-only route never requests persisted events and never constructs
  an empty conversation as if it were retained history.
- After durable recovery, the route stops repeating the failed live lookup.
  Resuming the chat re-enters the existing revision-bound recovery and native
  authority-revalidation flow.
- The fallback depends only on the strict catalog read method, not on unrelated
  project/chat mutation capabilities.

## Validation

- Focused dedicated-route matrix: **4 tests passed** for retained restart
  recovery, metadata-only truthfulness, true live-plus-catalog absence, and a
  late catalog result after navigation to a newer live route.
- Full frontend Agent integration and route boundary: **184 tests passed**
  across the project/chat rail, complete Agent page, route ownership, catalog
  parser, and retained-history parser.
- After TypeScript rejected one invented synthetic history-state literal, the
  fixture was corrected to the generated contract value; the post-correction
  focused matrix passed **4 tests** and the production build passed with **559
  transformed modules**.
- Configured project-runtime backend restart matrix: **4 tests passed** for
  durable conversation recovery without authority, metadata-only refusal,
  catalog metadata persistence, and HTTP hierarchy/live-state truth after
  restart. A first attempt with the unrelated default interpreter lacked a
  locked dependency and never reached the HTTP assertion; the same tests were
  rerun successfully with the repository virtual environment.
- The existing approximately 510 kB minified Agent-page chunk advisory remains
  performance debt rather than a correctness failure.
- The rebuilt loopback app was reloaded at `/agent`; the Agent workspace, saved
  chat, and export control rendered, and browser logs were empty. No real
  retained deep link was opened because no owner-designated disposable chat was
  available for that native check.
- No model, GPU runtime, MCP host, or visible terminal was started.

## Owner review

Use a disposable **Save locally** chat:

1. Open the chat in its own Agent window and let that window reach the live
   conversation.
2. Restart the Prompt Enhancer application, then restore or reopen the same
   own-window route.
3. Confirm the saved conversation card appears instead of the
   “in-memory session is no longer available” screen.
4. Confirm no composer or protected authority appears until **Resume chat** is
   chosen, and that resume still requires the existing safe recovery flow.
5. Repeat with a disposable metadata-only chat and confirm the route explicitly
   says its messages were not stored.
6. Open a fictional/nonexistent window identifier and confirm the missing
   screen still links back to Agent.

## Next slice

Agent-12a will audit the active and retained conversation timeline against its
claims for streaming, safe reasoning summaries, progress/tool evidence, retry
behavior, and exact-or-unknown context usage. It will implement only the first
confirmed gap and add a focused correctness matrix before broader UI work.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
