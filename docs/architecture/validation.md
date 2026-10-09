# Architecture audit validation

Date: 2026-10-08. Source/documentation evidence only; no beta gate closed.

## Observation boundaries

Published source base `bfb67b6`; inspected development base `acdf0e5` with 747
preserved pending files. Source hashes and LF-normalized publication comparison
are in `source-observation.json`. The atlas records 122 components, all twenty
canonical metric IDs, eight workflow families and WP01–WP08. Metadata census:
1,161 source files, 23 route families, 32 feature directories, 53 HTTP route modules.

All Python files in the selected source tree parsed successfully. The limited
AST check found no absolute application imports pointing to infrastructure or
interfaces. It does not inspect every relative/dynamic import or prove complete
hexagonal separation. Source and test references were checked for existence;
test existence alone was never recorded as a pass.

## Fresh bounded checks

The following source-synthetic selection passed **122 tests in 18.85 seconds**:

```text
tests/test_metric_engine_contracts.py
tests/test_metric_engine_composition.py
tests/test_session_quality_aggregation.py
tests/test_project_quality_aggregation.py
tests/test_local_agent_contracts.py
tests/test_agent_parameters_contract.py
```

The parent runner confirmed owned cleanup. No model, provider, native window or
installer was involved. Green MA06, MA14 and A01 refer only to these bounded
contracts. MA14 is Engineering V1 ratio aggregation, not all-twenty ensemble
pooling. Counts are for the selection; do not sum each node's repeated citation.

The documentation branch passed **144 collaboration/privacy tests in 114.19
seconds**, with owned cleanup confirmed:

```text
tests/test_collaboration_policy.py
tests/test_privacy_scan.py
tests/test_privacy_scan_gallery_png.py
tests/test_privacy_scan_exclusions.py
```

The full repository privacy scan passed. The scanner change contains only seven
exact reviewed diagram hash entries; rejection behavior and limits are unchanged.
Generated-output checks passed; 551 local Markdown links resolved; all seven SVGs
parsed; cards stayed inside the image bounds; routed edges did not cross card
interiors; all PNGs contained only IHDR/IDAT/IEND chunks. The skill validator
passed. Images were visually reviewed locally using generated diagrams only.

R25 green refers to written policy and its metadata tests, not enforced owner-only
permissions. Hosted CI status belongs to the eventual PR and is not implied by
these local checks. No full backend/frontend or release suite was rerun for this
documentation-only change; the existing full-suite failure remains explicit.

## Independent source and documentation review

Three read-only review lanes covered analytics/metrics, Agent/workflows, and
native/distribution/CI. Review corrections included exact WP dependencies,
optional model commentary versus deterministic prompt checks, V1 aggregation
lineage, absent measured adapters versus existing metric definitions, private
source wording, native approval versus ordinary chat, and published/unpublished
source binding. The skill was forward-reviewed against a collaborator tasked
with the future composer workflow; it routes through W prerequisites instead of
treating the current prompt-check button as that implementation.

## Existing failures and incomplete qualification

These are development observations carried from the October 6–7 evidence, not
new runtime tests in this audit. The linked historical main ledger predates some
of them; its new audit addendum identifies that distinction.

- Full frontend run: `owned_process_timeout` at 600.11 seconds, cleanup confirmed;
  incomplete final-only report. Localize with incremental evidence before rerun.
- Clean-main external build graph: `E_BOUNDARY`, eight expected deferred chunk
  identities missing/ambiguous. Source components exist; do not claim eight
  features are absent or relax the budget.
- Inventory helper: static POSIX ancestor-swap finding; portable admission open.
- Real interpretation quality pilots failed unchanged semantic gates. Schema
  validity does not make experimental estimates authoritative metrics.
- Workflow engine/editor/adapters/true parallel qualification are absent.
- Update Apply/relaunch/recovery composition, signed distribution, dependency
  closure and current installed/clean-machine acceptance remain open.

No full application, real-model, GPU, native, packaged, clean-machine or hosted
release gate was claimed by this audit. Personal applications and private
provider data were not used. The documentation branch carries no pending product
implementation and does not change source visibility or repository permissions.

## Regeneration

```text
python scripts/render_architecture_atlas.py
powershell -NoProfile -File scripts/render_architecture_png.ps1
python scripts/render_architecture_atlas.py --check
python scripts/privacy_scan.py
git diff --check
```

The Python renderer uses only the standard library. PNG rendering uses Windows
System.Drawing and Arial, opens no windows, and may vary across font/runtime
versions. Visually review every regenerated PNG and update only its exact
allowlisted hash. Never add directory/glob exemptions. `--check` validates the
generated catalog/SVG/layouts; the privacy scanner verifies pinned PNG bytes.
Source observations require a fresh authorized source review, not merely rerendering.
