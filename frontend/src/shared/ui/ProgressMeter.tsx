import { formatPercent } from "../lib/format";

/**
 * Determinate progress primitive with an explicit `state` channel. The bar is
 * always the same height, so pause/resume/complete transitions never shift
 * layout; the state word is rendered as visible text (never colour-only or
 * hover-only) and echoed in `aria-valuetext`.
 */
export type ProgressMeterState = "idle" | "active" | "paused" | "complete" | "stopped";

export function ProgressMeter({
  label,
  value,
  max = 100,
  state,
  detail,
  compact = false,
}: {
  label: string;
  /** Completed units; `null` means the amount is not known and is not drawn as zero. */
  value: number | null;
  max?: number;
  state: ProgressMeterState;
  /** Visible detail such as "12.4 MB of 40 MB · paused". */
  detail: string;
  compact?: boolean;
}) {
  const validMax = Number.isFinite(max) && max > 0;
  const validValue = value !== null && Number.isFinite(value) && value >= 0;
  const bounded = validMax && validValue ? Math.min(max, value) : null;
  const percent = bounded === null ? null : (bounded / max) * 100;
  const ariaPercent = percent === null
    ? undefined
    : percent === 0
      ? 0
      : Number(percent.toPrecision(6));
  const percentLabel = percent === null ? "Unknown" : formatPercent(percent / 100);
  return (
    <div className={`ui-progress${compact ? " ui-progress--compact" : ""}`} data-state={state}>
      <div className="ui-progress__label">
        <span>{label}</span>
        <span>{percentLabel}</span>
      </div>
      <div
        aria-label={label}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={ariaPercent}
        aria-valuetext={percent === null ? `${detail} · amount unknown` : `${percentLabel} · ${detail}`}
        className="ui-progress__track"
        data-unknown={percent === null ? "true" : undefined}
        role="progressbar"
      >
        <span className="ui-progress__fill" style={{ width: percent === null ? "0%" : `${percent}%` }} />
      </div>
      <span className="ui-progress__detail">{detail}</span>
    </div>
  );
}
