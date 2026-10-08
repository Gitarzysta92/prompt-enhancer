# Agent checkpoint 09w — coherent in-Agent model recovery

Date: 2026-08-28

## Outcome

A stopped or model-less chat no longer sends the user away from Agent while the
coordinated **Model & context** control is already available on the same page.
The chat now exposes one recovery action that reveals the rail and focuses the
exact model selector. Known stopped models use the same path.

This is navigation and state-truth repair only. The recovery action does not
start, stop, switch, bind, install, or download a model and grants no new
runtime, process, file, approval, provider, or network authority.

## Recovery matrix

- Coordinated runtime plus installed models: the session status names **Model
  & context** and offers **Choose or start model**.
- A collapsed project rail is expanded before focus moves to the model selector;
  open setup/settings drawers close without clearing their form state.
- A known-but-stopped chat model uses the same in-Agent recovery path instead
  of presenting status with no adjacent action.
- Coordinated runtime with an empty installed-model catalogue keeps the Models
  page link because the in-Agent selector cannot perform installation.
- Older backends without the coordinated runtime retain their existing Models
  page fallback.
- The disabled composer placeholder and first-message guidance name the same
  truthful recovery location instead of contradicting the session status.
- The new-session form no longer shows an unnecessary Models link when its own
  installed-model selector already has choices.

## Verification

- Five focused tests cover legacy fallback, installed-model focus recovery,
  known stopped models, an empty installed-model catalogue, and runtime-context
  behavior.
- The complete Agent page plus runtime-control suite passed **120/120 tests**.
- The complete frontend suite passed **160/160 files and 2,163/2,163 tests** in
  one serial run.
- TypeScript compilation and the production build passed with **547 transformed
  modules**. The repository privacy scan passed.

## Live and process evidence

The in-app browser reloaded `http://127.0.0.1:8765/agent` with the rebuilt
`AgentPage--N7bQv6T.js` asset. The retained fictional chat showed the new
model-less status and no **Open Models** link because installed choices were
available. After the projects rail was collapsed, activating **Choose or start
model** expanded the rail and focused `agent-runtime-model`.

The runtime remained **Stopped**. The app listener remained loopback-only on
`127.0.0.1:8765`; no Vitest/Vite worker and no local model runtime remained.
No LLM was loaded, so no GPU cleanup was required.

## Remaining acceptance

The overall Agent goal remains active. Owner-only acceptance still covers
artifact Preview/Reveal/Review/Download and stale-file refusal, then one actual
model-backed turn and Stop, one fictional reviewed write, model unload, and
process/GPU cleanup evidence. Autonomous audits can continue to remove other
contradictory or unreachable default-workflow states without starting a model.
