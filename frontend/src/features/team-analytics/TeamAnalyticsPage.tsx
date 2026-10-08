import { useEffect, useMemo, useState } from "react";
import {
  isTeamControlPlaneError,
  teamAggregateRequestForAccess,
  teamAggregateRequestsEqual,
  teamAggregateSnapshotIsValid,
  teamCapabilityReportIsValid,
  type AnalyticsScope,
  type ReadinessActionKind,
  type TeamAggregateSnapshot,
  type TeamAggregateRequest,
  type TeamCapabilityReport,
  type TeamControlPlanePort,
} from "../../shared/api/teamControlPlane";
import type { AppRoute } from "../../shared/platform/platform";
import type { RuntimeDataMode, RuntimeServiceState } from "../../shared/platform/runtimeMode";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { Icon } from "../../shared/ui/Icon";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import { MODEL_ENSEMBLE_LENSES, type ModelEnsembleLensId } from "../model-ensemble/metricAxisModel";
import { MemberVisibilityPanel } from "./MemberVisibilityPanel";
import { ControlPlaneReadinessNotice } from "./ControlPlaneReadinessNotice";
import { ReadinessCards } from "./ReadinessCards";
import { ScopeSwitcher } from "./ScopeSwitcher";
import { TeamAggregateBoard } from "./TeamAggregateBoard";
import { teamSnapshotSummary } from "./teamAggregatePresentation";
import {
  ORIGIN_LABELS,
  SCOPE_LABELS,
  localReadinessCard,
  orderedReadinessCards,
  scopeAccessCopy,
  shortUtcDate,
} from "./teamAnalyticsCopy";
import "./TeamAnalytics.css";

type AggregateState =
  | { kind: "idle"; port: TeamControlPlanePort }
  | { kind: "loading"; request: TeamAggregateRequest; port: TeamControlPlanePort }
  | { kind: "ready"; request: TeamAggregateRequest; port: TeamControlPlanePort; snapshot: TeamAggregateSnapshot }
  | { kind: "not_served"; scope: AnalyticsScope; port: TeamControlPlanePort; message: string }
  | { kind: "failed"; request: TeamAggregateRequest; port: TeamControlPlanePort };

type CapabilityState =
  | { kind: "loading"; port: TeamControlPlanePort }
  | { kind: "ready"; port: TeamControlPlanePort; report: TeamCapabilityReport }
  | { kind: "failed"; port: TeamControlPlanePort };

function readinessRoute(kind: ReadinessActionKind): AppRoute | null {
  switch (kind) {
    case "open_local_sources": return { name: "local_sources" };
    case "open_job_centre": return { name: "analysis_jobs" };
    case "open_methods_and_models": return { name: "research" };
    case "none":
    default: return null;
  }
}

/**
 * Me / Team / Organization analytics. Everything on this page is driven by the
 * typed team control-plane port: the shell never guesses that a cohort, sync,
 * or billing service exists. Scopes the port cannot serve fail closed with a
 * visible reason, aggregates are the only cohort publication, and individual
 * members appear only behind an explicit, audited reveal.
 */
export function TeamAnalyticsPage({
  port,
  runtimeMode,
  serviceState,
  navigate,
}: {
  port: TeamControlPlanePort;
  runtimeMode: RuntimeDataMode;
  serviceState: RuntimeServiceState;
  navigate: (route: AppRoute) => void;
}) {
  const [capabilityState, setCapabilityState] = useState<CapabilityState>({ kind: "loading", port });
  const [reloadToken, setReloadToken] = useState(0);
  const [scope, setScope] = useState<AnalyticsScope | null>(null);
  const [lensId, setLensId] = useState<ModelEnsembleLensId>("task-framing");
  const [aggregate, setAggregate] = useState<AggregateState>({ kind: "idle", port });
  const [aggregateToken, setAggregateToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setScope(null);
    setAggregate({ kind: "idle", port });
    setCapabilityState({ kind: "loading", port });
    port.getCapabilities(controller.signal)
      .then((report) => {
        if (controller.signal.aborted) return;
        if (!teamCapabilityReportIsValid(report, port)) {
          setCapabilityState({ kind: "failed", port });
          return;
        }
        setCapabilityState({ kind: "ready", port, report });
        setScope((current) => {
          if (current !== null && report.scopes.some((access) => access.scope === current && access.state === "allowed")) return current;
          const team = report.scopes.find((access) => access.scope === "team");
          return team?.state === "allowed" ? "team" : "me";
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setCapabilityState({ kind: "failed", port });
      });
    return () => controller.abort();
  }, [port, reloadToken]);

  const capabilities = capabilityState.kind === "ready" && capabilityState.port === port
    ? capabilityState.report
    : null;
  const capabilitiesLoading = capabilityState.port !== port || capabilityState.kind === "loading";
  const capabilitiesError = capabilityState.port === port && capabilityState.kind === "failed";

  useEffect(() => {
    if (scope === null || capabilities === null) return undefined;
    const access = capabilities.scopes.find((candidate) => candidate.scope === scope);
    if (access === undefined || access.state !== "allowed") {
      setAggregate({ kind: "not_served", scope, port, message: access === undefined ? "This scope is not described by the port." : scopeAccessCopy(access) });
      return undefined;
    }
    const request = teamAggregateRequestForAccess(access);
    if (request === null) {
      setAggregate({ kind: "not_served", scope, port, message: "The port did not provide an exact immutable scope and cohort query identity." });
      return undefined;
    }
    const controller = new AbortController();
    setAggregate({ kind: "loading", request, port });
    port.getAggregate(request, controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        if (!teamAggregateSnapshotIsValid(snapshot, request, port)) {
          setAggregate({ kind: "failed", request, port });
          return;
        }
        setAggregate({ kind: "ready", request, port, snapshot });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (isTeamControlPlaneError(reason) && reason.code === "scope_not_served_by_this_runtime") {
          setAggregate({
            kind: "not_served",
            scope,
            port,
            message: "No team control plane serves this scope in the current runtime. Personal metrics stay in the project workspace; nothing is synced or estimated here.",
          });
          return;
        }
        setAggregate({ kind: "failed", request, port });
      });
    return () => controller.abort();
  }, [aggregateToken, capabilities, port, scope]);

  const readinessCards = useMemo(() => orderedReadinessCards(
    capabilities?.readiness ?? [],
    localReadinessCard(runtimeMode, serviceState, capabilities?.checked_at ?? null),
  ), [capabilities, runtimeMode, serviceState]);

  const activeScope = scope ?? "me";
  const activeScopeAccess = capabilities?.scopes.find((access) => access.scope === activeScope) ?? null;
  const activeAggregateRequest = activeScopeAccess === null ? null : teamAggregateRequestForAccess(activeScopeAccess);
  const aggregateMatchesActive = aggregate.kind === "idle"
    || (aggregate.kind === "not_served" && aggregate.scope === activeScope)
    || (aggregate.kind !== "not_served"
      && activeAggregateRequest !== null
      && teamAggregateRequestsEqual(aggregate.request, activeAggregateRequest));
  const currentAggregate: AggregateState = aggregate.port === port && aggregateMatchesActive
    ? aggregate
    : { kind: "idle", port };
  const snapshot = currentAggregate.kind === "ready"
    && currentAggregate.snapshot.scope === activeScope
    ? currentAggregate.snapshot
    : null;
  const summary = teamSnapshotSummary(snapshot);
  const originLabel = capabilities === null ? "Origin not reported yet" : ORIGIN_LABELS[capabilities.origin];

  return (
    <section aria-labelledby="team-analytics-title" className="team-analytics" data-runtime={runtimeMode}>
      <header className="page-header route-header team-analytics__header">
        <div>
          <p className="eyebrow">Analytics scopes</p>
          <h1 id="team-analytics-title">Team analytics</h1>
          <p>Compare me, team, and organization scopes through aggregate evidence with cohort size, missingness, comparability, freshness, and uncertainty. No rankings and no universal score exist here.</p>
        </div>
        <div className="page-header__meta">
          <span className="privacy-chip"><Icon name="lock" /> {originLabel}</span>
        </div>
      </header>

      {capabilitiesLoading && capabilities === null ? (
        <LoadingState label="Checking scope permissions" />
      ) : capabilitiesError && capabilities === null ? (
        <ErrorState
          message="Scope permissions could not be read from the port. Nothing is assumed: every scope stays closed until the port answers."
          onRetry={() => setReloadToken((value) => value + 1)}
        />
      ) : capabilities === null ? null : (
        <>
          <ScopeSwitcher
            onChange={(nextScope) => {
              setAggregate({ kind: "idle", port });
              setScope(nextScope);
            }}
            scopes={capabilities.scopes}
            value={activeScope}
          />

          <ReadinessCards
            cards={readinessCards}
            onAction={(kind) => {
              const route = readinessRoute(kind);
              if (route !== null) navigate(route);
            }}
          />
          <ControlPlaneReadinessNotice
            readiness={capabilities.control_plane_readiness}
          />

          <section aria-labelledby="team-aggregate-title" className="team-analytics__aggregate">
            <header className="team-analytics__aggregate-header">
              <div>
                <p className="eyebrow">{SCOPE_LABELS[activeScope]} scope</p>
                <h2 id="team-aggregate-title">
                  {snapshot === null ? `${SCOPE_LABELS[activeScope]} aggregate` : snapshot.cohort_label}
                </h2>
                {snapshot !== null && (
                  <p>
                    {snapshot.window.label} · generated {shortUtcDate(snapshot.generated_at)} · {snapshot.calibration.replaceAll("_", " ")} · {snapshot.publication_policy.replaceAll("_", " ")}
                  </p>
                )}
              </div>
              {snapshot !== null && (
                <dl className="team-analytics__counts">
                  <div><dt>Measured</dt><dd>{summary.measured}/20</dd></div>
                  <div><dt>State-only</dt><dd>{summary.stateOnly}</dd></div>
                  <div><dt>Experimental</dt><dd>{summary.experimental}</dd></div>
                  <div><dt>Suppressed</dt><dd>{summary.suppressed}</dd></div>
                </dl>
              )}
            </header>

            {currentAggregate.kind === "loading" && <LoadingState label={`Loading the ${SCOPE_LABELS[currentAggregate.request.scope].toLowerCase()} aggregate`} />}
            {currentAggregate.kind === "failed" && (
              <ErrorState
                message="The aggregate could not be loaded from the port. The last state is not retained because none was published."
                onRetry={() => setAggregateToken((value) => value + 1)}
              />
            )}
            {currentAggregate.kind === "not_served" && (
              <div className="team-analytics__not-served" role="status">
                <span className="privacy-status__icon"><Icon name="lock" /></span>
                <div>
                  <strong>{SCOPE_LABELS[currentAggregate.scope]} scope is not served here</strong>
                  <p>{currentAggregate.message}</p>
                </div>
                {currentAggregate.scope === "me" && runtimeMode === "local_real" && (
                  <button className="button button--secondary" onClick={() => navigate({ name: "projects" })} type="button">
                    Open Projects
                  </button>
                )}
              </div>
            )}
            {snapshot !== null && (
              <>
                <nav
                  aria-label="Aggregate lens"
                  className="team-analytics__lenses"
                  onKeyDown={(event) => moveRovingFocus(event, (index) => setLensId(MODEL_ENSEMBLE_LENSES[index].id))}
                >
                  {MODEL_ENSEMBLE_LENSES.map((lens) => (
                    <button
                      aria-label={`${lens.label} lens · ${lens.expectedMetricCount} metrics`}
                      aria-pressed={lens.id === lensId}
                      key={lens.id}
                      onClick={() => setLensId(lens.id)}
                      type="button"
                    >
                      <span aria-hidden="true">{lens.shortLabel}</span>
                      <small aria-hidden="true">{lens.expectedMetricCount} metrics</small>
                    </button>
                  ))}
                </nav>
                <TeamAggregateBoard lensId={lensId} mode="full" snapshot={snapshot} />
                <p className="team-analytics__legend">
                  Bands are per-metric 95% sampling intervals on exact cohort fractions; they are never joined into a polygon. Hatched bands and diamonds are experimental model ranges, shown separately and never merged with measured values. Suppressed, withheld, unknown, N/A, and needs-evidence rows sit in the state lane and are never drawn as zero.
                </p>
              </>
            )}
          </section>

        </>
      )}
      <div
        aria-label="Reserved member visibility region"
        className="team-analytics__member-slot"
        data-member-panel={capabilities !== null && activeScope !== "me" ? "active" : "reserved"}
      >
        {capabilities !== null && activeScope !== "me" && (
          <MemberVisibilityPanel
            grant={capabilities.member_visibility}
            lensId={lensId}
            port={port}
            scope={activeScope}
            scopeAccess={activeScopeAccess}
          />
        )}
      </div>
    </section>
  );
}
