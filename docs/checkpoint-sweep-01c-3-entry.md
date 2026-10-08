# Checkpoint Sweep-01c.3 entry

Status: automated complete; owner review queued
Entered: 2026-09-01
Parent: [Sweep-01c entry](checkpoint-sweep-01c-entry.md)
Prerequisite: [Sweep-01c.2 handoff](checkpoint-sweep-01c-2-handoff.md)

## User-visible outcome

Maximum supported Agent histories and loaded catalogs remain responsive while
the user pages, changes scope or navigates away. A delayed, cancelled or
out-of-order response cannot append foreign records, rewind selection or mix
two retained-history heads. Browsing older transcript activity never mounts the
complete 4,000-event history at once.

## Frozen stress contract

- Retained history is read in strict monotonic pages against one immutable
  `last_seq`. A changed head, repeated/out-of-order sequence, empty non-terminal
  page, wrong chat or more than 100 pages fails closed without reconstructing a
  mixed conversation.
- The transcript exposes deterministic Earlier/Later/Latest navigation through
  a 200-event window. A nearby user-turn boundary may extend that window by at
  most 50 events, so at most 250 activity records are mounted at once even when
  the admitted history contains 4,000 events.
- Project and chat render pages remain capped at 40 rows, artifacts at 50 cards,
  and server responses at 100 records while all bounded storage pages remain
  browseable.
- Replacing search, project, chat or artifact-lifecycle scope aborts the owned
  continuation. A transport that resolves despite abort is still rejected by
  the exact read owner and cannot alter the replacement scope.
- Synthetic browser fixtures exercise maximum retained history plus maximum
  bounded project/chat/artifact catalogs at 360 and 1,440 px. Direct mounted
  rows/cards and transcript records stay within the limits above.
- In-memory render-page and transcript-navigation reactions complete within a
  200 ms regression budget on the locked Chromium fixture. This is a local
  regression threshold, not a claim about field INP or model/network latency.
- After the fixture settles, cumulative layout shift caused without recent user
  input remains below 0.02 and the page has no horizontal overflow.

## Safety and evidence boundary

- Stress data is generated from reserved identifiers, fictional names, fixed
  timestamps and synthetic relative paths only.
- The fixture uses an in-memory transport. It reads no provider cache or local
  workspace and starts no model, command, MCP host, native confirmation or
  network request.
- Performance evidence records exact collection sizes, mounted-node counts and
  elapsed interaction observations. A timeout or unavailable browser signal is
  a failed/unknown gate, never silently converted to a pass.

## Exit gate

- Component tests cover maximum history, fixed-window navigation, changed-head
  refusal, delayed continuation resolution after scope replacement, repeated
  pages and preserved loaded prefixes.
- Chromium at 360 and 1,440 px proves node, interaction, overflow and layout
  shift budgets using the maximum synthetic fixture.
- Affected and complete frontend regressions, Playwright, production build,
  generated API, privacy, whitespace and hidden rebuilt-loopback checks pass.

Closed by: [Sweep-01c.3 handoff](checkpoint-sweep-01c-3-handoff.md)
