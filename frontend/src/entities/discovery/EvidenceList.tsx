import type { CandidateSignal } from "./model";
import { evidenceDirectionLabel } from "./model";
import { formatPercent, shortId, titleFromKey } from "../../shared/lib/format";
import { CoverageBar } from "../../shared/ui/CoverageBar";
import { StatusPill } from "../../shared/ui/StatusPill";

export function EvidenceList({ signals }: { signals: CandidateSignal[] }) {
  if (signals.length === 0) {
    return <p className="muted">No discovery evidence was recorded.</p>;
  }

  return (
    <ol className="evidence-list">
      {signals.map((signal) => (
        <li className="evidence-item" key={`${signal.key}-${signal.session_ids.join("-")}`}>
          <div className="evidence-item__heading">
            <div>
              <strong>{titleFromKey(signal.key)}</strong>
              <span className="mono">v{signal.version}</span>
            </div>
            <StatusPill
              tone={
                signal.direction === "supports_link"
                  ? "positive"
                  : signal.direction === "supports_boundary"
                    ? "warning"
                    : "neutral"
              }
            >
              {evidenceDirectionLabel(signal.direction)}
            </StatusPill>
          </div>
          <p className="evidence-item__code">
            Evidence code <strong>{titleFromKey(signal.evidence_code)}</strong>
          </p>
          <div className="evidence-item__meta">
            <span>
              Confidence: {signal.confidence == null ? "Unknown" : formatPercent(signal.confidence)}
            </span>
            <span>
              Pair: {shortId(signal.session_ids[0])} + {shortId(signal.session_ids[1])}
            </span>
            {signal.numeric_evidence !== null && (
              <span>
                Observed: {signal.numeric_evidence} {signal.evidence_unit ?? "units"}
              </span>
            )}
          </div>
          <CoverageBar
            compact
            coverage={signal.coverage}
            eligible={signal.eligible_count}
            observed={signal.observed_count}
          />
        </li>
      ))}
    </ol>
  );
}
