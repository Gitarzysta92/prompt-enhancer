import type { ReadinessActionKind, ReadinessCard } from "../../shared/api/teamControlPlane";
import { Icon, type IconName } from "../../shared/ui/Icon";
import {
  READINESS_ACTION_LABELS,
  READINESS_REASON_COPY,
  READINESS_STATE_LABELS,
  READINESS_TITLES,
  shortUtcDate,
} from "./teamAnalyticsCopy";

const CARD_ICONS: Readonly<Record<ReadinessCard["id"], IconName>> = {
  local: "lock",
  team_sync: "users",
  deep_analysis: "activity",
  billing: "layers",
};

/**
 * Four readiness cards: local analysis, team sync, deep analysis, billing.
 * A card is only "ready" when the shell observed the capability; absent
 * services render as unavailable with the reason spelled out, and their
 * actions stay disabled instead of pretending to configure anything.
 */
export function ReadinessCards({
  cards,
  onAction,
  compact = false,
}: {
  cards: readonly ReadinessCard[];
  onAction?: (kind: ReadinessActionKind) => void;
  compact?: boolean;
}) {
  return (
    <ul
      aria-label="Capability readiness"
      className={`readiness-cards${compact ? " readiness-cards--compact" : ""}`}
    >
      {cards.map((card) => {
        const actionLabel = READINESS_ACTION_LABELS[card.action.kind];
        const actionEnabled = card.action.enabled && actionLabel !== null && onAction !== undefined;
        return (
          <li
            aria-busy={card.state === "checking" ? true : undefined}
            className="readiness-card"
            data-card={card.id}
            data-state={card.state}
            key={card.id}
          >
            <header>
              <span aria-hidden="true" className="readiness-card__icon"><Icon name={CARD_ICONS[card.id]} /></span>
              <div>
                <strong>{READINESS_TITLES[card.id]}</strong>
                <span className="readiness-card__state" data-state={card.state}>
                  {READINESS_STATE_LABELS[card.state]}
                </span>
              </div>
            </header>
            <p>{READINESS_REASON_COPY[card.reason]}</p>
            <footer>
              <small>{card.checked_at === null ? "Not checked yet" : `Checked ${shortUtcDate(card.checked_at)}`}</small>
              {actionLabel === null ? (
                <small className="readiness-card__no-action">No action available in this build</small>
              ) : (
                <button
                  className="button button--secondary button--compact"
                  disabled={!actionEnabled}
                  onClick={() => { if (onAction !== undefined && actionEnabled) onAction(card.action.kind); }}
                  type="button"
                >
                  {actionLabel}
                </button>
              )}
            </footer>
          </li>
        );
      })}
    </ul>
  );
}
