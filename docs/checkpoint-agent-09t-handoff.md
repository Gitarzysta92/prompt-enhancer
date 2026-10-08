# Agent checkpoint 09t — chat-first responsive review drawer

Date: 2026-08-28

## Outcome

The active Agent conversation now remains the primary work surface while Files
and reviewed changes open in one coherent **Files & review** drawer. Medium and
narrow windows no longer stack the workspace below the conversation or expand
the document simply because review is open.

This slice changes presentation and focus ownership only. It adds no file,
command, web, approval, model, controller, or MCP authority.

## Interaction contract

- **Files** and **Changes** are first-class tabs with roving Left/Right/Home/End
  keyboard navigation and explicit selected state.
- Both tab panels remain mounted while switching. A manual or staged workspace
  draft is therefore not destroyed by inspecting the change set.
- At widths up to 1,380 px, review is a viewport-bounded modal sheet with an
  inert background scrim. The conversation's position and document height stay
  unchanged while the sheet opens.
- At wide desktop widths, review remains a third resizable workbench column.
- Closing with unsaved workspace work requires an explicit discard decision.
  Declining leaves the drawer, draft, and editor intact. Accepting closes the
  drawer and restores focus to the message composer.
- Opening a verified or unverified receipt path switches to Files, loads only
  the current bounded workspace file, focuses the editor, and scrolls a tall
  editor into the drawer's visible scrollport.
- Artifact **Reveal in files** and **Review changes** actions route to the exact
  Files or Changes tab rather than adding review UI to the transcript.

## Verification

- TypeScript project compilation passed.
- Drawer, layout, and workspace coverage passed **57 tests**.
- The complete Agent page passed **104 tests**.
- Responsive Chromium coverage passed **125 tests**. This includes main and
  dedicated views at 360 px and 1,440 px plus the 1,024 px overlay contract.
- The full frontend suite's first high-contention run passed **2,150/2,151**;
  one asynchronous Office-preview assertion exceeded its one-second test
  default after passing in the isolated Agent run. The assertion now uses the
  established four-second viewer timeout. A final serial run passed **160/160
  files and 2,151/2,151 tests**, including the exact artifact → reveal → reopen
  → diff workflow.
- The production build passed with **547 transformed modules**. Generated API
  drift checking, the repository privacy scan, and tracked-diff whitespace
  checking passed.

## Runtime and privacy

All browser operations used synthetic in-memory fixtures. No provider history,
credential, account configuration, real prompt, local workspace content, or
remote model was read. No model runtime was started, so no model VRAM was
allocated. Test servers were loopback-only and were stopped after use.

The running native-owned app reloaded the new production asset at
`http://127.0.0.1:8765/agent`. At a 1,046 × 912 viewport the live review drawer
was fixed and bounded from 76 px to 836 px while the 760 px conversation card
kept its position. Files was selected on open, Right Arrow selected Changes,
and Close removed the drawer. Final inventory found one listener on 8765, no
listener on the test port 4173, no Vite process, and no `llama-server` process.

## Remaining owner acceptance

This automated slice does not replace the owner-controlled artifact and native
model acceptance. The remaining release gate is still: preview synthetic
text/image/PDF/Office artifacts in the live app; refocus a separate Agent
window; run and Stop one explicitly selected local model; review one fictional
write; unload it; and verify process/GPU cleanup. Native confirmations must not
be bypassed.
