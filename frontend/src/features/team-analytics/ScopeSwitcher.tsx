import { useId } from "react";
import {
  ANALYTICS_SCOPES,
  type AnalyticsScope,
  type ScopeAccess,
} from "../../shared/api/teamControlPlane";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import { SCOPE_DESCRIPTIONS, SCOPE_LABELS, scopeAccessCopy } from "./teamAnalyticsCopy";

/**
 * Me / Team / Organization context switcher. Scopes the runtime cannot serve
 * stay in the tab order with `aria-disabled` so keyboard and screen-reader
 * users can still discover why; the reason is always rendered as visible text,
 * never only as a tooltip. Selecting a scope never reveals data on its own:
 * the page still asks the port, which fails closed.
 */
export function ScopeSwitcher({
  scopes,
  value,
  onChange,
  compact = false,
}: {
  scopes: readonly ScopeAccess[];
  value: AnalyticsScope;
  onChange: (scope: AnalyticsScope) => void;
  compact?: boolean;
}) {
  const idPrefix = useId();
  const accessFor = (scope: AnalyticsScope): ScopeAccess =>
    scopes.find((candidate) => candidate.scope === scope)
      ?? {
        principal_id: "0".repeat(64),
        scope,
        state: "unavailable",
        reason: "local_runtime_has_no_team_service",
        cohort_label: null,
        cohort_id: null,
        team_id: null,
        organization_id: null,
        aggregate_query_id: null,
      };
  const blocked = ANALYTICS_SCOPES.map(accessFor).filter((access) => access.state !== "allowed");
  return (
    <div className={`scope-switcher${compact ? " scope-switcher--compact" : ""}`}>
      <div
        aria-label="Analytics scope"
        className="scope-switcher__group"
        onKeyDown={(event) => moveRovingFocus(event)}
        role="group"
      >
        {ANALYTICS_SCOPES.map((scope) => {
          const access = accessFor(scope);
          const allowed = access.state === "allowed";
          return (
            <button
              aria-describedby={`${idPrefix}-${scope}`}
              aria-disabled={allowed ? undefined : "true"}
              aria-pressed={scope === value}
              data-access={access.state}
              key={scope}
              onClick={() => { if (allowed) onChange(scope); }}
              type="button"
            >
              <span>{SCOPE_LABELS[scope]}</span>
              {!compact && (
                <small>{allowed ? (access.cohort_label ?? SCOPE_DESCRIPTIONS[scope]) : access.state === "denied" ? "Not permitted" : "Unavailable"}</small>
              )}
            </button>
          );
        })}
      </div>
      <div className="scope-switcher__reasons">
        {ANALYTICS_SCOPES.map((scope) => (
          <span hidden id={`${idPrefix}-${scope}`} key={scope}>
            {SCOPE_LABELS[scope]}: {SCOPE_DESCRIPTIONS[scope]} {scopeAccessCopy(accessFor(scope))}
          </span>
        ))}
        {blocked.length === 0 ? null : (
          <ul aria-label="Scopes not available">
            {blocked.map((access) => (
              <li key={access.scope}>
                <strong>{SCOPE_LABELS[access.scope]}</strong> · {scopeAccessCopy(access)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
