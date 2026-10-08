# MCP Store checkpoint 06e.1 handoff

Date: 2026-08-30
Status: automated implementation complete; owner visual review pending
Runtime effect of the automated gate: synthetic browser fixtures and a read-only
live Store reload only; no package was installed, no MCP server or model was
started, and no protected authority was granted

## Outcome

The MCP Store now has a focused management information architecture instead of
mixing discovery, lifecycle controls and safety explanations inside every tile.
The main Agent conversation remains the primary work surface; Store management
stays in Agent settings and separates **Browse servers** from **Managed
servers** with keyboard-reachable tabs.

Browse owns search, distribution filtering, compact catalog tiles and exact
review entry points. Managed owns prepared/installed lifecycle state, recovery
and management detail. Advanced safety and lifecycle material is progressively
disclosed rather than repeated across the catalog.

## Changed

- `AgentMcpStorePanel` now uses the shared tab system for distinct Browse and
  Managed workspaces, including roving keyboard behavior and explicit empty
  recovery.
- Compact tiles expose a single visually consistent **View details** action
  while retaining unique accessible names for every server.
- Package/connection detail was removed from discovery tiles and remains bound
  to exact review/management views.
- Store safety boundaries moved into one concise progressive disclosure.
- The Store settings drawer can use a wider desktop canvas; all five settings
  sections occupy a coherent equal-width row and become a horizontal strip on
  narrow screens.
- The settings drawer exposes its current section through a testable state
  attribute.
- A dedicated synthetic `agent-mcp-store` fixture isolates Store acceptance
  data from established Agent/chat scenarios.

## Automated evidence

- Focused MCP Store component suite: **23 passed**.
- Store plus Agent layout contracts: **36 passed**.
- Agent settings/page regression: **146 passed**.
- Complete Agent frontend feature suite: **475 passed / 28 files**.
- Full frontend suite: **2,506 passed / 175 files**.
- Rendered Store journeys at **360 px and 1440 px**: **2 passed**.
- Production TypeScript/Vite build: passed. The existing large-chunk advisory
  remains a non-failing performance item for Sweep-01c.
- Repository privacy scanner: passed.
- `git diff --check`: passed; existing Windows line-ending notices remain
  non-failing.

Every new fixture uses reserved fictional identities, hosts and paths. No real
provider transcript, credential, owner workspace or package content was read.

## Live read-only evidence

- The rebuilt Store opened at the existing loopback Agent route without a
  server restart or additional listener.
- The settings drawer presented five coherent sections and the Store presented
  Browse/Managed as a two-tab workspace.
- The live official registry rendered 24 compact entries with 24 distinct
  accessible review actions.
- Arrow-key navigation moved Browse to Managed and back; search disappeared in
  Managed and returned in Browse; the empty managed state remained truthful.
- The browser error log remained empty.
- Process census: **1** loopback listener, **0** visible child windows,
  **0** model workers and **0** MCP workers.

## Explicit red-evidence ledger

An accidentally broad 82-case legacy workflow run was not green: **66 passed,
16 failed**. The failures repeat eight pre-existing/non-Store scenarios at two
widths: Local Models compatibility/completion copy or visibility, Agent
reasoning visibility, Agent model-switch admission, the older expectation that
Stop disables drafting, and workspace-inventory visibility. The new Store
fixture was separated from those routes and its two independent journeys then
passed.

This evidence is not hidden or relabelled as a full E2E pass. Reconciliation of
those old scenario assertions versus current intended behavior belongs to the
route/control inventory in Sweep-01a; any confirmed product defect reopens its
owning Agent, Runtime or Workspace checkpoint.

## Still bounded

- Source-provenanced logo treatment, sorting, pagination/stale-request recovery,
  compatibility presentation and complete lifecycle-state polish remain in
  Store-06e.2.
- Live project permission/health/tool-selection reconciliation remains in
  Store-06e.3.
- The compact in-chat tool drawer and final activity/approval presentation
  remain in Store-06e.4.
- No real install, update, rollback, uninstall, server start or consequential
  tool call was fabricated. Those remain protected actions and owner acceptance
  debt.

## Owner click-later ledger

1. Open **Agent → Agent settings → MCP Store**.
2. Confirm Browse feels like a compact catalog and expand the single safety
   boundary only when needed.
3. Use the keyboard to move between **Browse servers** and **Managed servers**.
4. Review the layout once at a narrow width and once on the desktop.
5. Do not install a real server unless that exact package and permission plan
   has been separately trusted.

## Next checkpoint

Store-06e.2 is active: make every catalog entry source-provenanced and visually
trustworthy, then complete search/filter/sort, detail, compatibility,
install/update/rollback/uninstall state and loading/empty/offline/error recovery
without weakening the existing review and authority boundaries.
