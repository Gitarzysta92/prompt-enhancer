# Agent checkpoint 10m — Files & Review workbench hierarchy

Date: 2026-08-29

## Outcome

The Files & Review drawer now presents the file tree and editor as the primary
coding workbench. Discovery, bounded content search, Git metadata, and the full
reviewed-change safety explanation remain available in one collapsed
**Workspace tools & safety** disclosure instead of pushing the editor below
the useful viewport.

This preserves every existing workspace capability and fail-closed boundary;
it changes information hierarchy and repairs two undersized discovery
controls. No file, approval, runtime, history, or controller authority changed.

## Reproduced defects

1. The long safety copy and always-expanded discovery/search/Git card occupied
   the top of the drawer, leaving the actual file tree and editor below the
   fold at the owner's 1046 px viewport.
2. **File pattern** omitted an explicit text-input type, so its intended CSS did
   not apply and Chromium rendered a 21 px control.
3. The narrow-width rule reset the **Regular expression** row to automatic
   height, reducing its interactive target to 19 px at 390 px.
4. Older HTTP workspace scenarios assumed the pre-drawer layout and used a
   stale partial v8 session fixture, so they no longer exercised the current
   product path reliably.

## Implemented boundary

- **Workspace tools & safety** is closed by default and has a 44 px summary.
- The discovery component remains mounted while visually collapsed, so its
  workspace-root replacement lock continues to run.
- File tree, empty/open-file state, editor, diff actions, and multi-file staging
  remain directly available in the Files tab.
- Discovery filter, content query, file pattern, and regex row are at least
  44 px at desktop and narrow widths.
- Multi-file diff disclosures are at least 44 px.
- The file-pattern control is explicitly `type="text"`.
- A current synthetic `local-agent.v8` fixture and explicit drawer/tab actions
  keep the affected HTTP browser workflows aligned with the shipped UI.

## Verification

- Focused workspace/review/discovery/layout suite: **85/85 passed**.
- Affected real Chromium workspace matrix: **12/12 passed** across:
  - 360 and 1440 px root-replacement/draft recovery in main and dedicated
    windows;
  - workbench-first hierarchy at 390 and 1046 px;
  - fail-closed and natively confirmed single-file review;
  - create, folder move, file move, and recoverable removal at 390 and 1440 px;
  - failure-atomic two-file review and commit at 390 and 1440 px.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live application at 1046 × 912:
  - disclosure closed by default and file editor immediately visible;
  - disclosure, filter, content query, file pattern, and regex controls measured
    exactly 44 px;
  - no horizontal overflow;
  - zero browser diagnostics.
- Final runtime inventory: one Prompt Enhancer window, one listener on
  `127.0.0.1:8765`, zero detected local-model server processes, and no terminal
  windows opened by this checkpoint.

The synthetic retained workspace used for live inspection was empty, so live
verification exercised hierarchy and disclosure behavior. Populated browse,
edit, lifecycle, and transaction behavior is covered by the focused component
and intercepted-loopback Chromium scenarios above. No real model was loaded.

## Next checkpoint

Agent-10n should audit generated output and attachment UX as one bounded slice:
artifact/document cards, image/PDF/Office/text viewer routing, Preview/Reveal/
Review changes/Download actions, attachment staging and removal, unsupported
media truth states, keyboard/focus behavior, and narrow layouts. Start with
synthetic files and intercepted contracts; owner-confirmed native capture and a
real multimodal model remain separate gates.
