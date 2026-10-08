# Agent checkpoint 08h handoff: truthful output handoff

Date: 2026-08-27
State: implementation and synthetic validation complete; native owner acceptance remains pending

## Outcome

Agent-08h closes the user-visible gap between an assistant statement about a
document and objective evidence that a workspace file was written. A completed
turn now says **no reviewed file writes** in its collapsed receipt when no
verified write exists. Expanding that receipt explains that model text alone is
not evidence that a file or document was created.

When reviewed writes do exist, their automatically projected artifact cards are
rendered at the active end of the live or retained conversation instead of
above the transcript. Empty artifact furniture is omitted from the Agent page;
loading, errors, and real artifact records remain visible. The existing viewer,
immutable version lineage, digest revalidation, file-opening action, and
download behavior are unchanged.

This checkpoint did not launch the native Prompt Enhancer app, a native window,
a local model, a command tool, or a GPU workload. A synthetic headless browser
fixture was used only to verify retained-chat layout and viewer behavior.

## Controller and artifact audit

This checkpoint revalidated the base controller lifecycle:

- the provider-neutral controller can discover the loopback contract, create a
  project, create a retained live chat, submit one message, and settle it with a
  finite cursor/deadline loop;
- ambiguous submission is not automatically repeated, deadline Stop is bounded,
  and a pending protected action returns to native review;
- reviewed `write_file` receipts automatically project into immutable artifact
  lineage for retained chats; and
- artifact bytes are re-hashed before preview or download, with stale, missing,
  malformed, oversized, and unsupported content failing closed.

Prompt Enhancer deliberately does not spawn Codex or Claude or inspect their
credentials. An external controller owns its process and deliberately passes a
selected message through the authenticated loopback API.

A subsequent Agent-08i audit found one continuation gap outside this
checkpoint: after a turn paused for native approval, the specialized helper had
no non-resubmitting way to resume observation. Agent-08i adds the bounded,
non-mutating `wait` command and strengthens cleanup-quarantine truth.

## Verification receipts

- Focused Agent UI tests: **109 passed across 3 files**.
- Complete frontend tests: **2,046 passed across 153 files**.
- Artifact and controller backend tests: **19 passed**.
- Focused Chromium layout/viewer tests: **2 passed** at 360 px and 1,440 px.
- Production TypeScript/Vite build: **533 modules transformed**.
- Targeted diff check: passed; only existing LF/CRLF notices were emitted.
- Privacy scanner: exactly one known pre-existing finding,
  `docs/checkpoint-agent-02-shell.png` (untracked binary). Agent-08h adds no
  privacy finding and did not change, remove, stage, ignore, or allowlist it.

All test data uses fictional identities, paths, projects, chats, models, and
content.

## Owner review later

During the existing guarded native acceptance, add two observations:

1. Ask the model for an output but do not approve or receive a write; confirm the
   turn visibly reports **no reviewed file writes** and no artifact card appears.
2. Approve one small fictional Markdown write; confirm its artifact card appears
   after the settled turn and opens the digest-verified viewer.

The remaining release blocker is still the bounded native/model owner run from
Agent-08g, including separate-window behavior, Stop, unload, process exit, and
CPU/GPU cleanup evidence. No automated test may claim that owner observation.
