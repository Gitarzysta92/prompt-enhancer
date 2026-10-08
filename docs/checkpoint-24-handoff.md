# Checkpoint 24: trustworthy acceptance of model judgments and commentary

Scope: repair structured model-result acceptance and the affected Session,
Calibration and Prompt Check behavior. This is a bounded reliability checkpoint,
not a claim that the entire application is finished or that model scores are
accurate.

## What was wrong

- Local judgment, interpretation, Prompt Check commentary and central inference
  extracted model text without checking the generation's completion receipt. A
  complete-looking JSON object from a limited, filtered, tool-request or otherwise
  ambiguous response could be accepted.
- Parsers searched for braces inside prose, accepted duplicate keys and coerced
  invalid commentary fields into defaults. Interpretation could report success
  with empty or malformed content. Some invalid types could escape as exceptions.
- Historical acceptance protocols remained in agreement calculations. Making the
  parser stricter alone would not prevent unchecked stored results from being
  treated as current evidence.
- The frontend transport dropped the safe invalid-reply reason. Screens could
  misleadingly report an unavailable model instead of an unusable response.

## Implemented

- A shared whole-response gate requires exactly one completed assistant text
  answer with `finish_reason: stop`, with no tool call, refusal or runtime error.
  Whole replies are capped at 2,000,000 bytes, content at 64,000 characters and
  JSON depth at 32. Missing completion information is not inferred as success.
- Structured JSON has unique keys, valid Unicode and finite numbers. One exact
  outer JSON fence is compatible; surrounding prose, extra objects and malformed
  schemas are not salvaged into successful results. Per-consumer text/list bounds
  remain stricter than the outer transport ceiling.
- Invalid commentary leaves deterministic metric values and states unchanged.
  Invalid judgment does not overwrite prior labels. A central batch skips a bad
  result and continues to a later valid item. No raw error content is exposed.
- Judgment acceptance is versioned as `judge-v4-complete-json-anchor-15k` and
  `judge-v4-complete-json-anchor-6k`; commentary as
  `prompt-check-commentary-v2-complete-json`; interpretation as
  `interpret-v2-complete-json`. Rubric questions and metric definitions did not
  change. Existing records are not silently upgraded or deleted.
- Agreement excludes older/unknown protocols and reserved missing window
  identities. Reports expose the accepted protocol list and excluded-label count.
  No eligible pairs means unknown agreement, not zero percent. Existing sweeps and
  explicitly requested annotation work can revisit historical protocol results.
- Session labels show their protocol and historical/missing-identity eligibility.
  Invalid reply messages preserve prior labels/explanations and allow retry.
  Calibration explains exclusions without changing the person's blind ratings.
  The safe transport code and generated API contracts match these UI states.

## Verification evidence

- Initial acceptance/schema regressions: 107 failing cases, with 20 passing
  controls, before repairs. These are variations of the identified defects, not
  107 separate product bugs. Four historical-agreement cases and nine frontend
  message/provenance/transport cases also failed before their respective fixes.
- Final focused backend run: **342 passed** across 14 files, including the new
  reply tests, existing judgment/annotation persistence, calibration math and
  reporting, Prompt Check HTTP/MCP/hook, API export and metric privacy coverage.
  The existing test-client deprecation warning remains. Full backend verification
  was not repeated; the checkpoint 21 full-suite baseline is historical evidence.
- Full frontend: **1,598 passed across 123 files** in 78.02 seconds. The first
  broad run had 1,595 passes and one unrelated Team Analytics timeout. Its
  unchanged 18-test file passed in isolation, followed by the successful full
  rerun with the final changes; neither assertions nor timeouts were weakened.
  Focused current judgment/calibration/HTTP transport: **152 passed**.
- Browser suites: **79 synthetic workflows** and **18 intercepted HTTP cases**
  passed. New cases cover judgment history, retry and explanation preservation,
  and the real frontend HTTP transport's Calibration error/exclusion behavior at
  360 and 1440 px, including CSRF and no blind-rating mutation.
- Two separate in-app browser flows inspected the judgment panel at narrow and
  desktop widths: labels survived failure, retry displayed the current protocol,
  failed explanation regeneration kept the prior explanation, and the page did
  not overflow horizontally. Wide tables retain their own scroller. The browser
  skill supplied the actual interactive layout check; no screenshot was saved.
- Production build, generated API consistency, strict browser-fixture TypeScript,
  Python compilation and whitespace checks passed. The first build identified
  required protocol fields missing from typed synthetic fixtures; those fixtures
  were aligned with the generated contract and the build was rerun successfully.

The counts above are separate verification runs, not a total of unique tests to
add together. Browser fixtures and stub inference do not certify real model
quality or all installed runtime variants.

## Later review checklist

1. Session view: historical judgments show their protocol and exclusion notice;
   they remain available rather than disappearing. Judge again with a running
   model; an invalid response leaves them intact and offers retry.
2. Explain this session: a valid explanation is readable; a subsequent invalid
   response does not replace it with an empty success panel.
3. Calibration: historical exclusion counts are explained, missing agreement
   displays as unavailable, and judging does not submit or change a human rating.
4. Prompt Check: deterministic cues still appear when commentary is invalid;
   malformed model output is not disguised as valid advice.

## Boundaries and remaining work

- No owner configuration, provider credentials or real sessions were read. No
  external model/network inference was used. No GPU model was loaded; zero model
  runtime processes were observed after testing. The owned browser tab was closed
  and its viewport restored. The owned HTTP test listener exited; the pre-existing
  synthetic development listener was left alone.
- The production assets were rebuilt. No normal owner-app restart is claimed;
  no listener was observed on its usual port during cleanup. Tests used isolated
  synthetic fixtures rather than launching ingestion against private data.
- The existing privacy gate finding from checkpoint 21 is unresolved: an old
  synthetic SQLite fixture remains under `test-results/browser-workflow-e3rix2kz`.
  Its previous deletion was blocked. No alternate deletion path, exclusion or
  scanner weakening was attempted. The unchanged scanner was rerun and reports
  exactly one finding for that same prohibited artifact; privacy sign-off remains
  open. There were no additional scanner findings.
- Completion receipts and valid JSON are not proof of task success, instruction
  resistance or calibrated model quality. This checkpoint does not establish
  representative human calibration, immutable model-revision admission, matching
  human/model evidence windows, central delivery reconciliation, native approval
  click-through or the broader unfinished product capabilities in the ledger.
- All prior working-tree changes are preserved. No commit or push was performed.
