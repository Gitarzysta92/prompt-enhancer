# Agent checkpoint 09s — bounded workspace text search

Date: 2026-08-28

## Outcome

The Agent **Files & review** workspace card can now search admitted UTF-8 text
inside the selected workspace. The same structured, read-only result is exposed
through the local controller API and the fixed 18-tool MCP surface, so native and
connected-agent clients share one correctness boundary.

This slice adds discovery only. It grants no write, command, web, approval, or
model authority.

## Correctness boundary

- Literal and regular-expression searches accept an optional root-relative glob.
- Results use canonical relative paths, one-based line numbers, stable path/line
  order, exact match counts, and explicit complete or partial coverage.
- The scan is bounded to 20,000 inspected entries, 32 path levels, 2,000,000
  bytes per admitted file, 16,000,000 inspected bytes in total, 80 matches, a
  five-second scan window, and a 50 ms per-line regular-expression match window.
- Queries and globs are limited to 1,024 characters. Invalid queries, globs, and
  regular expressions return fixed safe errors rather than parser details.
- Symlinks and reparse points, generated directories, non-UTF-8 or binary
  content, over-limit files, and replaced workspace roots are refused or reported
  as explicit exclusions. A replaced root locks the session instead of becoming
  a misleading partial result.
- Search previews replace control, formatting, and surrogate code points before
  entering the UI, controller response, MCP response, or terminal-facing output.
- The frontend drops stale responses when the session changes, cancels searches
  during refresh, validates the exact response shape, and only offers **Open
  result** for a path admitted by the current workspace map.

## Verification

- Focused search frontend and contract coverage: **227 passed**.
- Backend, controller, CLI, HTTP, OpenAPI, and direct Streamable HTTP MCP
  coverage: **193 passed** with one existing third-party warning.
- Full frontend suite: **159 files and 2,149 tests passed**.
- Complete responsive workflow coverage: **73 passed** at 360 px and 1440 px,
  including bounded search and opening an editable match.
- Production TypeScript/Vite build passed with **545 transformed modules**.
- Generated OpenAPI drift checking and TypeScript compilation passed.
- The first full responsive pass exposed an overflowing workspace drawer and
  ambiguous legacy selectors. Both were corrected before the final 73-test pass.

## Live checkpoint

The console-free application was closed through its normal native confirmation
and relaunched from the repository build at `http://127.0.0.1:8765/agent`.
A retained synthetic chat resumed with protected actions disabled. The live
**Files & review** drawer exposed **Search file contents**; a bounded read-only
literal search returned a truthful zero-match result for the empty synthetic
workspace.

The live **Controller API** panel reported **Ready**, 59 Agent routes, five
runtime routes, ten native review gates, contract
`local-agent-orchestration.v12`, and 18 core connected-agent tools. The final
runtime inventory found one loopback-only listener, no preview-server listener,
and no `llama-server` process. No model was loaded, so this checkpoint used no
model VRAM and left none to unload.

## Remaining owner acceptance

Automated and live read-only evidence covers this search slice. Native-presence
acceptance is still required for the broader release: one fictional mixed
create/edit transaction, one artifact walkthrough, separate-window refocus,
one real-model turn and Stop, one reviewed fictional write, and explicit model
unload/process/GPU verification. Those checks must not be automated around the
native confirmation.

## Next slice

The next correct checkpoint is the bounded owner acceptance sequence above.
If the owner is unavailable, the safe owner-independent work is a truth audit
that maps every advertised Agent capability to automated evidence, live
read-only evidence, or an explicit owner gate. Do not add another control until
that audit identifies a concrete, testable gap.
