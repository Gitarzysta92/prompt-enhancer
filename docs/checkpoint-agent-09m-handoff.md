# Agent checkpoint 09m — native-reviewed external file proposals

Date: 2026-08-28

## Outcome

An authorized external controller can now offer one exact UTF-8 file create or
revision-bound edit to a live Agent session. The proposal enters the existing
native diff card and cannot publish until the person approves it there. This
closes the previous dead end where a Codex-, Claude-, or other MCP-based
orchestrator could inspect and delegate work but could not hand its own exact
file result back to the protected Agent workflow.

## Controller and MCP contract

- The controller contract is `local-agent-orchestration.v9`; the MCP surface is
  `prompt-enhancer-agent-mcp.v13`.
- `agent_propose` is a dedicated, non-generic operation. Its input requires an
  explicit mutation-authorized literal, one request id, one relative path, one
  operation, and exact UTF-8 content.
- Creates require an absent target. Edits require the current SHA-256 revision.
  Stale revisions, wrong operation kinds, no-op edits, and changed request-id
  replays fail closed.
- The controller sends once. An identical retry returns the existing bounded
  receipt and never creates a second proposal or write.
- A successful submission means only `pending_native_review`. Only the native
  approval decision can publish the prepared bytes, after which exact
  verification produces `applied`.
- Denial, Stop, timeout, cancellation, failed publication, and unverified output
  have separate terminal receipts and never become success claims.

## Native UI

The approval card labels the source as **External controller proposal** and
shows the same exact bounded diff as a local-model proposal. The activity
timeline distinguishes controller proposals from model tool activity. A
verified external write refreshes the workspace and artifact views without
inventing a model response or completed model turn.

## Persistence and privacy boundary

Proposal content, target paths, approval identifiers, decisions, and lifecycle
events are live-memory only. Durable conversation history remains contiguous
and contains none of them. The retained idempotency receipt is bounded and
content-free. No direct-apply permission, hidden approval, remote listener,
provider configuration change, model load, or GPU use was introduced.

The repository privacy gate found one untracked screenshot left by an older
checkpoint. Repository policy forbids screenshots in documentation, so that
single file was removed without opening or copying it. The complete privacy
scan then passed.

## Shutdown defect found during native acceptance

The first warmed native reload reproduced
`runtime_stop_failed / automation_grant_worker`. Cooperative provider
cancellation was raised correctly, but `AutomationGrantService.poll_due()`
caught it as a normal provider failure and could continue through remaining
due grants past the five-second owner-cleanup deadline.

`RuntimeCooperativeStop` now propagates as control flow and is never persisted
as a provider failure. A regression proves the poll exits without advancing the
grant receipt. The real native app was then left open beyond its first
scheduler interval and closed through its ordinary confirmation. Eight seconds
later there were zero Prompt Enhancer windows, zero listeners, zero
`llama-server` processes, zero visible terminal windows, and no cleanup
diagnostic.

## Automated verification

- Focused proposal/controller/MCP backend slice: **139 passed**.
- Proposal plus real two-client Streamable HTTP MCP integration: **8 passed**.
- Complete Agent backend selection: **539 passed**.
- Focused Agent UI/contract slice: **291 passed**.
- Complete Agent UI selection: **509 passed** across 38 files.
- Scheduler, provider cancellation, ingestion, runtime, and native lifecycle
  slice after the live repair: **113 passed**.
- Generated API drift check passed.
- Production TypeScript/Vite build passed with 543 transformed modules.
- Repository privacy scan passed.
- `git diff --check` passed; Windows line-ending notices remain informational.

## Final native state

One console-free Agent owner window is running with one listener bound only to
`127.0.0.1:8765`. The project/chat rail is visible, the shared model runtime is
**Stopped**, and there are zero `llama-server` and zero visible terminal
windows. No model, credential, prompt, protected action, or provider session
was used for this checkpoint.

## Remaining owner acceptance

The automated proposal bridge is complete, but a real controller credential
and real model remain owner-controlled gates. The bounded walkthrough is:
create one scoped connection, submit a fictional proposal, inspect and deny it;
submit a second fictional proposal, approve it, verify the resulting artifact,
then revoke the credential. A later chosen model-backed turn, Stop, reviewed
write, and CPU/GPU cleanup check still precede legacy-surface retirement.

No commit or push was requested.
