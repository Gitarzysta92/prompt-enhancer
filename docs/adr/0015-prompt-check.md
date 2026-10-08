# ADR 0015: Prompt check - validate a prompt in context before an agent acts on it

- Status: accepted (2026-08-19)
- Owner direction: a person using Claude Code, Codex or any model should be
  able to send the prompt they are about to use for validation; the software
  measures it in the context it was written in (earlier turns when the agent
  has them, otherwise what can be read from the prompt itself), shows metrics
  and plots, and prepares commentary for the external agent - what to improve,
  with reformulated elements - so the model the person uses works better for
  that prompt. Optional: not every prompt has to go through it.

## Context

Every metric the app computes today is about whole sessions after the fact.
The coaching pack's prompt family (`prompt.task_definition_coverage`,
`problem_evidence_quality`, `context_sufficiency`, `constraint_precision`,
`acceptance_testability`, `deliverable_contract`) is already "focus request
only" - it measures one prompt and names the cues it found or missed - and the
app now runs a local model (ADR 0013) that can read text and write
suggestions. The missing piece is a surface that takes a prompt *before* it is
sent, from the person or from the agent, and answers in time to matter.

## Decision

1. **One service, three entrances.** `application/prompt_check.py` is the
   single implementation. It is reachable as `POST /v1/prompt-checks` (the
   dashboard's *Prompt check* page and any script), as the MCP tool
   `check_prompt` (ADR 0014 surface; Codex, Claude Code or any MCP client
   decides when to call it), and as the Claude Code `UserPromptSubmit` hook
   `prompt-enhancer claude-prompt-check`, which posts the prompt to the app's
   loopback API and hands the advice back as `additionalContext`. The hook is
   opt-in, skips prompts under four words and slash commands, never blocks
   (silent exit 0 on any failure), and can be switched off with
   `PROMPT_ENHANCER_PROMPT_CHECK_HOOK=0` or made deterministic-only with
   `PROMPT_ENHANCER_PROMPT_CHECK_COMMENTARY=0`.
2. **Deterministic first.** The prompt (and the earlier turns, if supplied) go
   through the same redactor, language detector and coaching engine as session
   analysis, with the prompt as the focus request, so the six prompt metrics
   are exactly the dashboard's metrics, with their detected / missing cues.
   Content-free context inference adds task type, language, size, references,
   whether the prompt relies on earlier turns (and whether any were supplied),
   whether verification was asked for, and a list of elements to consider
   adding. Unknown stays unknown and is explained ("too short or language not
   recognised", "only measured for bug / diagnosis prompts").
3. **Model commentary, visibly separate.** When a local model is active, it
   receives the prompt, the earlier turns and the deterministic findings and
   must answer with strict JSON: findings (aspect, severity, why, suggestion),
   a reformulated prompt that keeps the person's intent and language and uses
   `<specify: …>` placeholders rather than invented values, element-level
   rewrites, notes. The reply is parsed strictly and bounded; anything else is
   `reply_invalid`. Commentary is labelled model output and is never a metric.
   Acceptance protocol `prompt-check-commentary-v2-complete-json` also requires
   one completed assistant text reply (`finish_reason: stop`) before parsing.
   Missing, limited, filtered, tool-request or ambiguous completions remain
   invalid even if their text looks like complete JSON. One exact outer JSON
   fence is tolerated; surrounding prose, duplicate keys, invalid Unicode,
   non-finite numbers, excessive depth, extra fields and malformed or overlong
   suggestions are rejected rather than coerced, clipped or given invented
   defaults. Deterministic readings are still returned and stored unchanged.
4. **Context comes from the caller or from the prompt.** Agents pass the
   earlier turns as `prior_messages` (oldest first, bounded); the dashboard
   form accepts them as `user:` / `assistant:` lines. Without them, the check
   infers dependence on earlier context from the prompt and says so, and the
   hook tells the agent to resolve references from its own context.
5. **Only metrics are kept.** Migration 53 adds `prompt_checks`: per check the
   provider and agent model hint, language, task type, sizes, the
   content-free readings (states, values, cues), the commentary state and
   model alias, and an HMAC fingerprint of the prompt. The prompt, the earlier
   turns and the commentary are returned to the caller and never stored. The
   Prompt check page plots the stored checks (radar per check, trend across
   checks) and links each row; a stored check shows no text.
6. **Surface rules.** ADR 0014's surface gains its one text-accepting tool;
   its description says so. The prompt travels only to 127.0.0.1 and, through
   the commentary, into the connected agent's context - where it already was.

## Consequences

- A vague prompt gets a concrete answer in seconds (deterministic) or
  20-40 s with the 27B model's commentary; the agent can ask one clarifying
  question or restate the task before doing work.
- The same rubric on prompts and on sessions means a person can see whether
  better prompts (higher cue coverage) lead to better sessions - the trend
  plots are the first half of that comparison.
- The deterministic cues are conservative by design; the model's commentary
  often catches more (for example an implicit file path from earlier turns)
  and is clearly marked as the part that may be wrong.
