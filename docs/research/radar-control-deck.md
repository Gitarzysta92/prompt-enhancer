# Radar control-deck decision

Status: metric-truth boundary retained; the single-radar layout is superseded
by [WP-15 interactive quality lenses](../work-packages/wp-15-interactive-quality-lenses.md),
August 2026.

## Evidence reviewed

- Cleveland and McGill's graphical-perception experiments established that
  position and length support more accurate quantitative judgments than angle
  and area encodings. DOI: <https://doi.org/10.1080/01621459.1984.10478080>.
- Albo et al. compared radial composite-indicator charts and found the radar
  chart least effective and least preferred for the evaluated lookup and
  comparison tasks. DOI: <https://doi.org/10.1109/TVCG.2015.2418937>.
- Mantovani et al. found that juxtaposed filled Kiviat plots can work well for
  multivariate *similarity detection*. That result supports radar as a compact
  scanning surface, not as the precise value-reading surface used here. DOI:
  <https://doi.org/10.2352/J.ImagingSci.Technol.2023.67.6.060406>.
- Zeng and Battle reviewed 59 graphical-perception studies and found that the
  best encoding depends on the analytical task; bars remain strongly supported
  for common value comparison and lookup tasks. DOI:
  <https://doi.org/10.1145/3544548.3581349>.
- Radar geometry depends on axis order. Recent feature-ordering work further
  demonstrates how arbitrary ordering can create misleading spikes and
  valleys: <https://arxiv.org/abs/2510.20738>.

## Product constraints

The dashboard therefore uses both encodings for different jobs:

1. The radar is a compact secondary scan of up to eight available
   positive-direction signals.
2. Axes retain the stable metric-definition order; missing axes are removed
   without reordering the values that remain.
3. Every axis uses the same bounded zero-to-one candidate-ratio scale.
4. Review-load metrics are not mixed into a higher-is-better polygon.
5. Unknown, Not applicable, Abstained, failed, or missing values are omitted
   rather than plotted as zero. The axis set is therefore dynamic and must be
   listed with the profile; shapes are comparable only when their axis sets
   and provenance match.
6. Geometry and the primary value use the same bounded `0–100%` candidate-
   coverage scale. Every radar label and card also shows the raw
   numerator/denominator fraction plus an uncalibrated/limited-base warning.
   This preserves fast comparison without presenting a `4 / 4` lexical
   checklist as a calibrated skill estimate.
7. A measured zero remains a real zero and is plotted at the center because
   its extractor ran. At least three available numeric axes are required to
   form a filled polygon. Its area is explicitly non-semantic and is never an
   overall score.
8. A compact horizontal metric board shows every value without interaction.
9. Receipts, denominators, coverage, extractor identity, calibration, and
   limitations live in one optional `Methods & details` disclosure.

## Metric truth boundary

The current coaching pack is a deterministic English/Polish candidate-rule
baseline. Qwen and BGE currently power a separate request-to-agent-work linkage
experiment; they do not produce the coaching ratios shown in the profile.
Until a metric passes a private human-labelled holdout and outcome validation,
the UI must describe it as a candidate signal or factor match rather than a
quality score. A value such as `4 / 4` means four rule-defined factors matched;
it does not mean the prompt was objectively perfect.

The first coaching pack also joins cues across a bounded conversation window.
For the context candidate, one broad lexical match can currently satisfy more
than one rubric factor. That explains how a session can report `4 / 4` even
when a human reviewer would judge its context incomplete. The UI exposes the
factor receipt and this limitation instead of presenting `100%` as quality.

The next metric-definition version must not silently modify this history. It
will require a new immutable pack with: an explicit prompt/specification unit,
distinct evidence per factor, task-type applicability, bilingual human labels,
and a held-out calibration report. Model-assisted scores stay experimental
until they beat the deterministic baseline and pass the same abstention,
privacy, and provenance gates.
