/** Small dependency-free SVG plots for prompt checks: a radar of one check, a trend over checks. */

export type RadarReading = { key: string; label: string; value: number | null; higherIsBetter: boolean };

export function promptMetricQualityValue(value: number | null, higherIsBetter: boolean): number | null {
  if (value === null || !Number.isFinite(value) || value < 0 || value > 1) return null;
  return higherIsBetter ? value : 1 - value;
}

function qualityPercentLabel(value: number, higherIsBetter: boolean): string {
  const quality = promptMetricQualityValue(value, higherIsBetter) ?? 0;
  const qualityPercent = Math.round(quality * 100);
  return `${qualityPercent}%${higherIsBetter ? "" : " quality"}`;
}

function qualityDetailLabel(value: number, higherIsBetter: boolean): string {
  const oriented = qualityPercentLabel(value, higherIsBetter);
  if (higherIsBetter) return oriented;
  return `${oriented} (raw ${Math.round(value * 100)}%; lower is better)`;
}

function polar(cx: number, cy: number, r: number, index: number, total: number): [number, number] {
  const angle = -Math.PI / 2 + (index / total) * Math.PI * 2;
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

/** Radar chart of the prompt metrics; unknown metrics are drawn hollow at the centre and named. */
export function PromptMetricRadar({ readings }: { readings: RadarReading[] }) {
  const size = 300;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 108;
  const total = Math.max(readings.length, 3);
  const rings = [0.25, 0.5, 0.75, 1];
  const points = readings.map((reading, index) => {
    const quality = promptMetricQualityValue(reading.value, reading.higherIsBetter);
    const normalized = quality ?? 0;
    return { ...reading, value: quality === null ? null : reading.value, normalized, point: polar(cx, cy, radius * normalized, index, total), labelPoint: polar(cx, cy, radius + 26, index, total) };
  });
  const known = points.filter((p) => p.value !== null);
  const polygon = points.map((p) => (p.value === null ? polar(cx, cy, 0, 0, 1) : p.point)).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <figure className="prompt-plot prompt-plot--radar">
      <svg aria-label="Prompt metric radar" role="img" viewBox={`-110 -8 ${size + 220} ${size + 16}`}>
        <title>Prompt metrics - {known.length} of {readings.length} measurable</title>
        {rings.map((ring) => (
          <polygon
            key={ring}
            className="prompt-plot__ring"
            points={Array.from({ length: total }, (_, i) => polar(cx, cy, radius * ring, i, total)).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
          />
        ))}
        {points.map((p, index) => {
          const [x, y] = polar(cx, cy, radius, index, total);
          return <line key={`axis-${p.key}`} className="prompt-plot__axis" x1={cx} x2={x} y1={cy} y2={y} />;
        })}
        {known.length >= 1 && <polygon className="prompt-plot__area" points={polygon} />}
        {points.map((p) => (
          <g key={p.key}>
            <circle className={p.value === null ? "prompt-plot__dot prompt-plot__dot--unknown" : "prompt-plot__dot"} cx={p.point[0]} cy={p.point[1]} r={p.value === null ? 3 : 4.5}>
              <title>{p.label}: {p.value === null ? "not measurable" : qualityDetailLabel(p.value, p.higherIsBetter)}</title>
            </circle>
            <text className="prompt-plot__label" textAnchor={p.labelPoint[0] < cx - 5 ? "end" : p.labelPoint[0] > cx + 5 ? "start" : "middle"} x={p.labelPoint[0]} y={p.labelPoint[1] + 4}>
              {p.label}{p.value === null ? " (n/a)" : ` ${qualityPercentLabel(p.value, p.higherIsBetter)}`}
            </text>
          </g>
        ))}
      </svg>
      <figcaption>Higher is better on every axis; metrics the rubric could not measure sit at the centre and are marked n/a.</figcaption>
    </figure>
  );
}

export type TrendSeries = {
  key: string;
  label: string;
  higherIsBetter: boolean;
  points: { x: number; value: number | null; at: string }[];
};

/** Trend of each prompt metric across the stored checks (oldest left, newest right). */
export function PromptMetricTrend({ series }: { series: TrendSeries[] }) {
  const width = 640;
  const height = 180;
  const pad = { left: 36, right: 12, top: 10, bottom: 24 };
  const count = Math.max(1, ...series.map((s) => s.points.length));
  const xFor = (index: number) => pad.left + (count <= 1 ? (width - pad.left - pad.right) / 2 : (index / (count - 1)) * (width - pad.left - pad.right));
  const yFor = (value: number) => pad.top + (1 - value) * (height - pad.top - pad.bottom);
  return (
    <figure className="prompt-plot prompt-plot--trend">
      <svg aria-label="Prompt metric trend across checks" role="img" viewBox={`0 0 ${width} ${height}`}>
        <title>Prompt metrics across {count} checks</title>
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line className="prompt-plot__grid" x1={pad.left} x2={width - pad.right} y1={yFor(tick)} y2={yFor(tick)} />
            <text className="prompt-plot__tick" textAnchor="end" x={pad.left - 6} y={yFor(tick) + 4}>{Math.round(tick * 100)}%</text>
          </g>
        ))}
        {series.map((s, seriesIndex) => {
          const segments: string[] = [];
          let current: string[] = [];
          s.points.forEach((p, index) => {
            const quality = promptMetricQualityValue(p.value, s.higherIsBetter);
            if (quality === null) {
              if (current.length) segments.push(current.join(" "));
              current = [];
            } else {
              current.push(`${xFor(index).toFixed(1)},${yFor(quality).toFixed(1)}`);
            }
          });
          if (current.length) segments.push(current.join(" "));
          return (
            <g key={s.key} className={`prompt-plot__series prompt-plot__series--${seriesIndex}`}>
              {segments.map((segment, i) => <polyline key={i} fill="none" points={segment} />)}
              {s.points.map((p, index) => {
                const quality = promptMetricQualityValue(p.value, s.higherIsBetter);
                return p.value === null || quality === null ? null : (
                  <circle key={index} cx={xFor(index)} cy={yFor(quality)} r={2.5}>
                    <title>{s.label} · {new Date(p.at).toLocaleString()} · {qualityDetailLabel(p.value, s.higherIsBetter)}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}
        <text className="prompt-plot__tick" x={pad.left} y={height - 6}>oldest</text>
        <text className="prompt-plot__tick" textAnchor="end" x={width - pad.right} y={height - 6}>newest</text>
      </svg>
      <figcaption className="prompt-plot__legend">
        {series.map((s, index) => <span key={s.key} className={`prompt-plot__legend-item prompt-plot__series--${index}`}><i /> {s.label}{s.higherIsBetter ? "" : " · quality (raw lower is better)"}</span>)}
      </figcaption>
    </figure>
  );
}
