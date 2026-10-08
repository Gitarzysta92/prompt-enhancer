# ADR 0017: Annotation paths - agents through the app's endpoint, and the central annotation server

- Status: accepted (2026-08-20); agent path and central path implemented locally
- Owner direction: the person has multiple ways to annotate the dataset.
  Besides rating manually and the built-in local judge, (a) after clicking an
  allowance, any model the person drives - Codex, Claude Code, or a local
  model - can call the app's endpoint, fetch sessions with a prepared
  metaprompt, and write annotations back; and (b) a separate "annotate
  remotely" action sends sessions and projects to the central server (the same
  one that will handle login, run locally today and on a VPS later), which
  spawns the most powerful model available to it, annotates, and stores the
  submissions - building, over time, a dataset good enough to train our own
  metric-prediction model.

## Context

`model_judgments` (migration 50) already stores per-model labels beside the
person's blind ratings, keyed by `model_alias` / `model_identity` /
`prompt_version`, compared on the Calibration page. What was missing: a way
for models *outside* the app to annotate, and a central store.

## Decision

1. **Agent annotation through the app's endpoint (local dataset).** A person
   clicks *Allow agent annotation*; while the allowance is on, the app serves
   under its token:
   - `GET /v1/annotation/metaprompt` - the prepared metaprompt: the system
     prompt, the three calibration questions, the closed label set, and the
     exact reply format;
   - `GET /v1/annotation/work?model=<name>&limit=N` - session ids (with
     provider and project id) that this model has not yet annotated;
   - `GET /v1/annotation/work/{session_id}` - the session's redacted analysis
     window (the same window P1 and the local judge read - never the raw
     transcript);
   - `POST /v1/annotation/annotations` - `{session_id, model_name, labels}`,
     stored as ordinary model judgments with `model_alias = "agent:<name>"`.
   The allowance is a switch the person can flip off at any time; with it off
   every route answers 403. Reading the window hands session content to
   whatever model the agent runs on - the allowance text says so.
2. **Central annotation server (central dataset).** The app embeds the
   central server's annotation routes under `/central/v1/*` with their own
   store (`central-annotations.sqlite3` in the app home) - the same code that
   will run on the VPS beside login; today the app token stands in for the
   login credential. *Annotate remotely* (a separate, explicit action naming
   the destination) submits redacted windows plus pseudonymous session and
   project ids in batches: `POST /central/v1/annotations/batch`. The central
   server annotates each window with the strongest model configured on it
   (locally: the app's own active runtime) using the same metaprompt, stores
   submission + labels + model identity + prompt version centrally, and
   returns the labels, which the app also records locally as
   `central:<model>` judgments - so central annotations join the same
   agreement table.
3. **The dataset.** Central rows are `(user_label, session_id, project_id,
   provider, window_fingerprint, redacted_window, labels, model_identity,
   prompt_version, submitted_at)` - enough to train a metric predictor later;
   windows are stored only on the central side and only through this explicit
   action. Locally nothing changes: metrics-only tables stay metrics-only.
4. **Boundaries.** Both paths are off by default and per-person switchable;
   the central submit is the one place session text crosses a boundary and it
   says where it goes before the first batch; judgments never become metric
   values; the activation gate is unchanged; no rankings.

## Consequences

- Four annotation paths (manual, local judge, own agents, central) all land
  in one comparable store; the Calibration page shows per-model agreement
  with the person for every path.
- Running the same central routes on a VPS later is a deployment change, not
  a design change: swap the base URL and put real login in front.
- Verified locally end to end on real sessions: an "agent" (scripted client)
  annotated through the endpoint, and a remote batch was annotated by the
  27B model through the central routes and stored centrally.

## Structured response acceptance (2026-08-26)

Central inference uses the same completed-assistant-response and strict bounded
JSON acceptance as the local judge. An invalid item is skipped without storing
its window/labels or preventing a later valid item in the batch from completing.
The current prompt/acceptance protocol is recorded; historical protocol rows
remain readable but do not count as current agreement or suppress explicitly
requested current-protocol annotation work. Direct agent label submissions are
still typed declarative annotations, not proof of the agent's generation or task
success. Allowance, destination disclosure and explicit submission gates remain.

Checkpoint 24 validation used fictional in-memory data and disposable synthetic
stores only. No external service was called, no real sessions were read, and no
GPU model was loaded. This evidence does not revalidate the historical real-data
claim above or certify a future remote deployment.

## Case-bound annotation receipts (2026-08-26, checkpoint 25)

Work windows now expose `case_fingerprint` and `case_version` alongside their
source-window fingerprint. A current agent annotation must echo that exact case
to enter reviewed-case comparison; older submissions remain stored as unbound
labels. Completing annotation work requires all rubric labels for one coherent
case, protocol and recorded model identity, not just one row for a session.

Central batch items/results carry the same provenance. The server validates the
case against the actual redacted window before inference; the client rejects
foreign or partial case receipts and counts only sessions whose returned labels
were accepted locally. A remote `stored` count is not authoritative evidence of
local completion. The SQLite store closes its connections after transactions and
reads, including failure paths. No old central rows are relabelled as current.

These are provenance and accounting checks, not proof of an external agent's
generation, model quality, human independence or delivery reconciliation. The
allowance, destination preview and explicit submission gates remain unchanged.
Tests use fictional cases and disposable stores only; no remote model or real
provider transcript was used for this checkpoint.
