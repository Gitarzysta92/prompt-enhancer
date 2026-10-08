# Local task flow truth model

The Task Flow screen is a local, content-free projection of four existing record families:

- discovery candidates are proposals produced by a versioned deterministic discovery step;
- accept, reject, merge, and split receipts are explicit human decisions;
- task revisions are immutable outputs of accepted review decisions;
- analysis runs describe analysis execution only.

The Kanban columns deliberately describe record kinds: proposed groupings, confirmed revisions, accepted/merged/split receipts, rejected proposals, and decided proposals whose action is unavailable. A missing action is never counted as acceptance or rejection. A decided proposal with no exposed receipt identifier remains decided, and the candidate-keyed audit route is still queried; the receipt is unknown, not absent. The application does not expose authoritative backlog, in-progress, done, task-start, or task-finish events. Those fields therefore remain **Unknown**; a completed analysis run never moves or completes a task.

Every card retains a shortened presentation of its input fingerprint and version provenance. Opening a decided proposal's audit drawer reads the existing loopback-only decision route on demand and validates the exact candidate, decision, revision-link, timestamp, and closed-code shape before rendering it. Task audit drawers list immutable revisions and their matching analysis events; a future correction appears as another revision instead of overwriting history.

Candidate, revision, and analysis indexes are bounded, paged, separate requests rather than one atomic snapshot. The screen surfaces page-end, duplicate, and cap receipts. Absence of matching analysis is reported only as an observation from that bounded index; if its end was not proven, analysis history stays unknown.

The surface does not load prompt, transcript, source-file, or provider-output content. It has no team or remote task source, so the compact summary reports exactly zero team-sourced and remote-synced records. Team sync, assignment, due dates, priority, and remote collaboration are not implemented by this view.
