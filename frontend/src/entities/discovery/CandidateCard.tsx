import { candidateTitle, type CandidateListItem } from "./model";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import { formatPercent, formatTimestamp, shortId } from "../../shared/lib/format";
import { CoverageBar } from "../../shared/ui/CoverageBar";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";

export function CandidateCard({
  item,
  active,
  selected,
  onInspect,
  onSelect,
}: {
  item: CandidateListItem;
  active: boolean;
  selected: boolean;
  onInspect: () => void;
  onSelect: (selected: boolean) => void;
}) {
  const { candidate } = item;
  const title = candidateTitle(candidate);
  const projectName = candidate.project_display_name?.trim();
  const confidence = candidate.confidence;

  return (
    <article className={`candidate-card ${active ? "candidate-card--active" : ""}`}>
      <label className="candidate-card__select">
        <input
          checked={selected}
          disabled={item.decision_status === "decided"}
          onChange={(event) => onSelect(event.target.checked)}
          type="checkbox"
        />
        <span className="sr-only">Select {title} for merge</span>
      </label>
      <button
        aria-current={active ? "true" : undefined}
        className="candidate-card__body"
        onClick={onInspect}
        type="button"
      >
        <span className="candidate-card__topline">
          <span className="candidate-card__identity">
            <span className="candidate-card__glyph"><Icon name="branch" /></span>
            <span>
              <strong>{title}</strong>
              <small>
                <ProviderBadge provider={candidate.provider} />
                {" "}
                {formatTimestamp(candidate.created_at)}
              </small>
            </span>
          </span>
          <StatusPill tone={item.decision_status === "decided" ? "positive" : "warning"}>
            {item.decision_status !== "decided"
              ? "Needs review"
              : item.decision_source === "automation"
                ? "Auto-accepted"
                : item.decision_action ?? "Reviewed"}
          </StatusPill>
        </span>

        <span className="candidate-card__stats">
          <span>
            <small>Sessions</small>
            <strong>{candidate.session_ids.length}</strong>
          </span>
          <span>
            <small>Confidence</small>
            <strong>{confidence == null ? "Unknown" : formatPercent(confidence)}</strong>
          </span>
          <span>
            <small>Project</small>
            <strong className={projectName ? "" : "mono"}>{projectName ?? shortId(candidate.project_id)}</strong>
          </span>
        </span>
        <CoverageBar
          compact
          coverage={candidate.coverage}
          eligible={candidate.eligible_count}
          observed={candidate.observed_count}
        />
        <span className="candidate-card__open">
          Review evidence <Icon name="arrow" />
        </span>
      </button>
    </article>
  );
}
