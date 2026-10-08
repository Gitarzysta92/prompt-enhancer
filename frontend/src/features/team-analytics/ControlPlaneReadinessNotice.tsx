import type { ControlPlaneReadiness } from "../../shared/api/contracts";
import { CONTROL_PLANE_GAP_COPY } from "./teamAnalyticsCopy";

/** Backend-observed readiness only. This component has no metric-value path. */
export function ControlPlaneReadinessNotice({
  readiness,
  compact = false,
}: {
  readiness: ControlPlaneReadiness | null;
  compact?: boolean;
}) {
  if (readiness === null) return null;
  return (
    <section
      aria-label="Development control-plane readiness"
      className={`control-plane-readiness${compact ? " control-plane-readiness--compact" : ""}`}
    >
      <strong>Development boundary reachable · team data remains closed</strong>
      <p>
        {readiness.contract_version} · {readiness.profile} · production ready: no · remote listener: off.
        These are readiness facts, not account, cohort, or metric authorization.
      </p>
      <details>
        <summary>{readiness.gaps.length} exact backend blockers</summary>
        <ul>
          {readiness.gaps.map((gap) => (
            <li key={gap}>
              <code>{gap}</code>
              <span>{CONTROL_PLANE_GAP_COPY[gap]}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
