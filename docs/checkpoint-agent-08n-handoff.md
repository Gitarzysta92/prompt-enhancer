# Agent checkpoint 08n handoff: truthful artifact version review

Date: 2026-08-27
State: implementation and synthetic validation complete; native/model owner acceptance remains pending

## Outcome

Agent-08n closes a usability and truthfulness gap in the conversation artifact
viewer. Artifact lineage was already immutable and digest-bound, but the UI
always opened only the newest revision while displaying a bare version count.
The viewer now exposes the recorded lineage directly:

- a keyboard-accessible version selector lists newest-first version number,
  byte size, provenance, and reviewed-write event where available;
- the selected version shows its position in the lineage and a shortened
  SHA-256 identity;
- preview and download request the selected immutable `version_id`, never an
  inferred path or the newest version by accident;
- Markdown Preview/Source, inert text, validated image, and sandboxed PDF
  rendering follow the selected version's own media/preview contract;
- **Open current file** appears only for the latest text revision, so a
  historical selection cannot masquerade as the current workspace file; and
- a historical revision whose digest no longer matches the current workspace
  fails closed, disables download, and explains that its bytes were not copied
  into application storage.

This preserves the privacy boundary from ADR 0016: artifact metadata and
lineage are retained locally for `local_history` chats, while file bytes remain
in the admitted workspace. An older version becomes reviewable again only if
the workspace file is explicitly restored to that exact recorded digest. No
model claim is treated as file evidence.

## Verification receipts

- Focused artifact backend gate: **8 passed**.
- Focused artifact component gate: **8 passed**.
- Agent artifact/history/change-set/release backend group: **36 passed**.
- Complete Agent frontend component group: **240 passed across 18 files**.
- Chromium saved-history/artifact workflow: **2 passed**, at 360 px and
  1,440 px.
- Production TypeScript/Vite build: **533 modules transformed**.
- Python source/test compilation: passed.
- `git diff --check`: passed (line-ending notices only).
- In-app browser verification at 1,280 px confirmed the latest preview,
  historical selector, digest/provenance summary, fail-closed stale message,
  disabled historical download, and zero page-wide horizontal overflow.

All browser and service fixtures are fictional and local. This checkpoint did
not launch Prompt Enhancer, a visible terminal, a real local model, or a GPU
workload. Ports 8765 and 8766 had no listener and no `llama-server` process was
present after validation.

The privacy scanner still reports exactly one known pre-existing finding: the
untracked binary screenshot `docs/checkpoint-agent-02-shell.png`. Agent-08n
introduced no additional privacy finding and did not weaken a scanner rule.

## What remains

The capability list captured before the Agent rebuild is obsolete: every row
now has implementation plus synthetic automated evidence. The retirement gate
is still intentionally blocked on the native owner walkthrough: reload the
application, use one registered local model, reopen a retained chat, exercise
streaming and Stop, inspect a reviewed file and a multi-version artifact, open
the dedicated window, switch placement/model, then unload and confirm process
and GPU cleanup. Automated evidence does not replace that observation.
