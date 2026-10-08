import { useEffect, useMemo, useState } from "react";
import {
  isTeamControlPlaneError,
  memberVisibilityGrantIdentity,
  memberVisibilityGrantIsUsable,
  memberVisibilityGrantsEqual,
  memberVisibilityPageIsValid,
  snapshotMemberVisibilityGrant,
  snapshotTeamMemberVisibilityRequest,
  teamMemberVisibilityRequestForAccess,
  teamMemberVisibilityRequestsEqual,
  type AnalyticsScope,
  type MemberVisibilityGrant,
  type ScopeAccess,
  type TeamControlPlanePort,
  type TeamMemberVisibilityRequest,
  type TeamMemberVisibilityPage,
} from "../../shared/api/teamControlPlane";
import { Icon } from "../../shared/ui/Icon";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import {
  MetricExplainerCardSlot,
  MetricExplainerDescriptions,
  metricExplainerTriggerProps,
  type MetricExplainerEntry,
} from "../model-ensemble/MetricExplainer";
import { useMetricKnowledgeCardController } from "../model-ensemble/MetricKnowledgeCard";
import { MODEL_ENSEMBLE_LENSES, type ModelEnsembleLensId } from "../model-ensemble/metricAxisModel";
import { memberCellLabel, teamLensColumns } from "./teamAggregatePresentation";
import { MEMBER_VISIBILITY_REASON_COPY, memberVisibilityAuditCopy, shortUtcDate } from "./teamAnalyticsCopy";

export {
  memberVisibilityGrantIdentity,
  memberVisibilityGrantIsUsable,
  memberVisibilityPageIsValid,
};

/**
 * Individual member visibility. The panel is closed by default and opens only
 * through an explicit action that the copy describes as audited. Without an
 * allowing grant the action stays disabled and the reason is visible. Rows are
 * ordered by pseudonymous member identifier, cells never sum to a member score,
 * and members who withheld consent are counted but never listed.
 */
export function MemberVisibilityPanel({
  grant,
  port,
  lensId,
  scope,
  scopeAccess,
}: {
  grant: MemberVisibilityGrant;
  port: TeamControlPlanePort;
  lensId: ModelEnsembleLensId;
  scope: Exclude<AnalyticsScope, "me">;
  scopeAccess: ScopeAccess | null;
}) {
  const [revealBinding, setRevealBinding] = useState<{
    port: TeamControlPlanePort;
    grant: MemberVisibilityGrant;
    request: TeamMemberVisibilityRequest;
  } | null>(null);
  const [pageBinding, setPageBinding] = useState<{
    port: TeamControlPlanePort;
    grant: MemberVisibilityGrant;
    request: TeamMemberVisibilityRequest;
    page: TeamMemberVisibilityPage;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [pageEpoch, setPageEpoch] = useState(0);
  const grantIdentity = memberVisibilityGrantIdentity(grant);
  const request = scopeAccess?.principal_id === port.principalId
    ? teamMemberVisibilityRequestForAccess(scope, scopeAccess, grant)
    : null;
  const requestIdentity = JSON.stringify(request);
  const explainerContextIdentity = `${grantIdentity.length}:${grantIdentity}${requestIdentity.length}:${requestIdentity}:${pageEpoch}`;
  const explainer = useMetricKnowledgeCardController(explainerContextIdentity);
  const allowed = memberVisibilityGrantIsUsable(grant, request, port.principalId, clockNow);
  const revealed = allowed
    && request !== null
    && revealBinding?.port === port
    && memberVisibilityGrantsEqual(revealBinding.grant, grant)
    && teamMemberVisibilityRequestsEqual(revealBinding.request, request);
  const page = revealed
    && request !== null
    && pageBinding?.port === port
    && memberVisibilityGrantsEqual(pageBinding.grant, grant)
    && teamMemberVisibilityRequestsEqual(pageBinding.request, request)
    ? pageBinding.page
    : null;
  const lens = MODEL_ENSEMBLE_LENSES.find((candidate) => candidate.id === lensId);
  const columns = useMemo(() => teamLensColumns(lensId), [lensId]);
  // A column is badged "measured" only when every listed member carries a
  // known cell for it; a column with any missing, unknown, N/A, or abstained
  // cell is state-only, so a missing member cell never sits under a measured badge.
  const entries: MetricExplainerEntry[] = columns.map((column) => {
    const members = page?.members ?? [];
    const knownCells = members.filter((member) => (
      member.metrics.find((cell) => cell.metric_key === column.key)?.value_state === "known"
    )).length;
    const allKnown = members.length > 0 && knownCells === members.length;
    return {
      key: column.key,
      label: column.label,
      provenance: allKnown ? "measured" : "not_measured",
      numericValue: null,
      valueLabel: members.length === 0
        ? "Per-member cells"
        : `Per-member cells · ${knownCells}/${members.length} known, ${members.length - knownCells} state-only or missing`,
    };
  });

  useEffect(() => {
    setClockNow(Date.now());
    setRevealBinding(null);
    setPageBinding(null);
    setLoading(false);
    setError(null);
  }, [grantIdentity, port, requestIdentity]);

  useEffect(() => {
    const expiry = grant.audit.expires_at === null ? Number.NaN : Date.parse(grant.audit.expires_at);
    if (!Number.isFinite(expiry)) return undefined;
    if (clockNow >= expiry) return undefined;
    const checkExpiry = () => {
      const nextNow = Date.now();
      setClockNow(nextNow);
      if (nextNow >= expiry) {
        setRevealBinding(null);
        setPageBinding(null);
        setLoading(false);
        setError(null);
      }
    };
    const delay = Math.max(0, Math.min(expiry - Date.now(), 2_147_000_000));
    const timer = window.setTimeout(checkExpiry, delay);
    return () => window.clearTimeout(timer);
  }, [grant.audit.expires_at, grantIdentity, port, clockNow]);

  useEffect(() => {
    if (!revealed || !allowed || request === null) return undefined;
    const controller = new AbortController();
    setPageBinding(null);
    setLoading(true);
    setError(null);
    port.getMemberVisibility(request, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        if (!memberVisibilityPageIsValid(next, grant, request, port)) {
          setPageBinding(null);
          setError("Member rows were withheld because the returned page did not match the exact active, audited consent grant.");
          return;
        }
        setPageBinding({
          port,
          grant: snapshotMemberVisibilityGrant(grant),
          request: snapshotTeamMemberVisibilityRequest(request),
          page: structuredClone(next),
        });
        setPageEpoch((current) => current + 1);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setPageBinding(null);
        setError(isTeamControlPlaneError(reason)
          ? MEMBER_VISIBILITY_REASON_COPY[reason.code === "member_visibility_unavailable" ? "unavailable_in_runtime" : "permission_not_granted"]
          : "Member visibility could not be loaded. Aggregates remain available.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [allowed, grantIdentity, port, requestIdentity, revealed]);

  function toggleReveal() {
    if (!allowed) return;
    setPageBinding(null);
    setError(null);
    if (request === null) return;
    setRevealBinding(revealed ? null : {
      port,
      grant: snapshotMemberVisibilityGrant(grant),
      request: snapshotTeamMemberVisibilityRequest(request),
    });
  }

  return (
    <section aria-labelledby="member-visibility-title" className="member-visibility" data-grant={grant.state}>
      <header className="member-visibility__header">
        <div>
          <p className="eyebrow">Individual members</p>
          <h3 id="member-visibility-title">Member visibility</h3>
          <p className="member-visibility__audit">
            {request === null && grant.state === "allowed"
              ? "The available member grant is bound to a different scope or cohort; it does not authorize this context."
              : memberVisibilityAuditCopy(grant)}
          </p>
        </div>
        <button
          aria-describedby="member-visibility-readiness"
          aria-expanded={allowed ? revealed : undefined}
          className={`button ${revealed ? "button--secondary" : "button--primary"}`}
          disabled={!allowed}
          onClick={toggleReveal}
          type="button"
        >
          <Icon name={revealed ? "x" : "users"} />
          {revealed ? "Hide individual members" : "Reveal individual members"}
        </button>
      </header>
      <p className="member-visibility__readiness" id="member-visibility-readiness">
        {allowed
          ? `Ready to reveal · the reveal is written to the ${grant.audit.log_destination?.replaceAll("_", " ")} · grant valid until ${shortUtcDate(grant.audit.expires_at!)} · rows are ordered by pseudonymous member id and never ranked`
          : `Not ready · ${grant.state === "denied" ? "no grant permits individual visibility" : grant.state === "unavailable" ? "no team control plane exists in this runtime" : "the grant lacks the exact active scope/cohort binding, consent, audit logging, grant id, or an unexpired expiry"} · aggregates stay available`}
      </p>
      {revealed && allowed && (
        <div aria-live="polite" className="member-visibility__body">
          {loading && <p className="member-visibility__status" role="status">Loading consented member rows…</p>}
          {error !== null && <p className="member-visibility__status" role="alert">{error}</p>}
          {page !== null && (
            <>
              <MetricExplainerDescriptions controller={explainer} entries={entries} surface="team-members" />
              <div className="member-visibility__scroll">
                <table className="member-visibility__table">
                  <caption>
                    <span>{lens?.label ?? "Metrics"} · {page.members.length} consented member{page.members.length === 1 ? "" : "s"} · {page.withheld_member_count} withheld consent and {page.withheld_member_count === 1 ? "is" : "are"} not listed · ordering: {page.ordering.replaceAll("_", " ")}</span>
                  </caption>
                  <thead>
                    <tr onKeyDown={(event) => moveRovingFocus(event)}>
                      <th scope="col">Member</th>
                      {columns.map((column) => (
                        <th key={column.key} scope="col">
                          <button
                            {...metricExplainerTriggerProps(explainer, "team-members", column.key)}
                            onClick={() => explainer.togglePin({ surface: "team-members", metricKey: column.key })}
                            type="button"
                          >
                            {column.shortLabel}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {page.members.map((member) => (
                      <tr key={member.member_id}>
                        <th scope="row">
                          <strong>{member.display_handle}</strong>
                          <small className="mono">{member.member_id.slice(0, 8)}…</small>
                        </th>
                        {columns.map((column) => {
                          const cell = member.metrics.find((candidate) => candidate.metric_key === column.key) ?? null;
                          return (
                            <td data-state={cell?.value_state ?? "missing"} key={column.key}>
                              {memberCellLabel(cell, column.direction)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="member-visibility__footnote">
                Cells are exact per-member fractions for the selected lens. No row total, average, or rank is computed; a member score does not exist in this product.
              </p>
              <MetricExplainerCardSlot controller={explainer} entries={entries} surface="team-members" />
            </>
          )}
        </div>
      )}
    </section>
  );
}
