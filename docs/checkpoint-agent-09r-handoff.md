# Agent checkpoint 09r — manual mixed create/edit review

Date: 2026-08-28

## Outcome

The manual **Files & review** workspace card can now stage a target-absent new
file and exact-revision edits to existing files in the same two-to-eight-file
transaction. The user sees every operation and diff before one native approval;
the UI then reports created and edited files separately.

This closes the manual-editor parity gap left by Agent-09q. It reuses the
`local-agent-workspace-transaction.v2` service boundary and adds no general
delete authority.

## Correctness boundary

- A staged item explicitly remains either `create` or `edit`; preview requests
  no longer reinterpret every manual draft as an edit.
- New-file staging validates a relative path, the UTF-8 byte limit, the
  two-to-eight-file limit, and case-insensitive path uniqueness before review.
- A staged creation can be reopened, edited, or renamed without creating a
  duplicate entry. It does not read or write an absent target while staging.
- Existing-file edits remain bound to their exact source revision. A path that
  appears after a creation was staged invalidates the review instead of being
  overwritten.
- Preview and apply are blocked while either editor contains an unstaged draft.
  Applying still requires one native-presence approval of the complete review.
- Successful results report created and edited counts. Rollback results report
  restored edits separately from same-transaction creations that were removed.
- A rolled-back or uncertain outcome keeps the drafts available for inspection;
  it is never presented as a successful commit.
- Permanent deletion and directory removal remain unavailable.

## Verification

- Focused manual workspace component coverage: **47 passed**.
- Component, strict transaction-contract, and HTTP transport coverage:
  **235 passed**.
- Backend transaction, proposal, controller, and MCP coverage:
  **155 passed** with one existing third-party warning.
- Full frontend suite: **158 files and 2,130 tests passed**.
- Complete responsive workflow coverage: **71 passed** at 360 px and 1440 px,
  including the mixed create/edit review and apply flow.
- Production TypeScript/Vite build passed with **544 transformed modules**.
- Generated OpenAPI drift check, Python bytecode compilation, repository
  privacy/secret scan, and `git diff --check` passed. The repository continues
  to emit its existing Windows line-ending notices.
- Adversarial UI coverage includes staged-create reopen and rename,
  case-insensitive create/edit collision, mixed rollback reporting, and refusal
  to review while the new-file editor contains an unstaged change.

## Live checkpoint

The existing console-free app was reloaded at
`http://127.0.0.1:8765/agent`. A retained synthetic chat resumed with protected
actions off, and the live **Files & review** drawer exposed the new
**Multi-file transaction** copy: stage two to eight creations and edits,
inspect every diff, then use one approval. No workspace mutation was submitted
during this read-only inspection.

The final runtime inventory found one loopback-only listener in one application
process tree, no preview-server listener, and no `llama-server` process. No
model was loaded for this checkpoint, so it consumed no model VRAM and left
none to unload.

## Remaining owner acceptance

Automated coverage proves the transaction state machine, responsive UI, and
transport contract. The real native-presence interaction still needs one owner
walkthrough using only fictional files: stage one creation and one edit, deny
the first review, preview again, approve once, inspect both results, then test a
stale-target refusal. This gate must not be automated around the native
confirmation.

The broader release also still needs the owner artifact walkthrough, separate
chat-window refocus check, one real-model turn and Stop, one reviewed fictional
write, and explicit model unload/process/GPU verification.

## Next slice

No further owner-independent feature gap is known in the screenshot capability
list. The next correct step is the bounded owner acceptance sequence above. If
the owner is unavailable, perform a truth audit that maps every advertised
Agent capability to its automated evidence and owner-gated evidence; do not add
new controls or claim release readiness merely to avoid the gate.
