import { formatPercent } from "../lib/format";

export function CoverageBar({
  coverage,
  observed,
  eligible,
  compact = false,
}: {
  coverage: number;
  observed: number;
  eligible: number;
  compact?: boolean;
}) {
  const measurable = Number.isFinite(coverage)
    && coverage >= 0
    && coverage <= 1
    && Number.isInteger(observed)
    && Number.isInteger(eligible)
    && observed >= 0
    && eligible > 0
    && observed <= eligible;
  const boundedCoverage = measurable ? Math.max(0, Math.min(1, coverage)) : 0;
  const ariaPercent =
    boundedCoverage === 0
      ? 0
      : Number((boundedCoverage * 100).toPrecision(6));
  const label = eligible === 0
      ? "No eligible evidence"
      : measurable
        ? `${observed} of ${eligible} observations (${formatPercent(boundedCoverage)})`
        : "Coverage unavailable";

  return (
    <div className={`coverage ${compact ? "coverage--compact" : ""}`}>
      <div className="coverage__label">
        <span>Coverage</span>
        <span>{eligible === 0 ? "Not observed" : measurable ? formatPercent(boundedCoverage) : "Unavailable"}</span>
      </div>
      {measurable ? (
        <div
          aria-label={label}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={ariaPercent}
          className="coverage__track"
          role="meter"
        >
          <span className="coverage__fill" style={{ width: `${boundedCoverage * 100}%` }} />
        </div>
      ) : (
        <div aria-hidden="true" className="coverage__track" data-unknown="true">
          <span className="coverage__fill" style={{ width: "0%" }} />
        </div>
      )}
      {!compact && <span className="coverage__caption">{label}</span>}
    </div>
  );
}
