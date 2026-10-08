import { useEffect, useState } from "react";
import {
  isTeamControlPlaneError,
  teamAggregateRequestForAccess,
  teamAggregateRequestsEqual,
  teamAggregateSnapshotIsValid,
  teamCapabilityReportIsValid,
  type TeamAggregateRequest,
  type TeamAggregateSnapshot,
  type TeamCapabilityReport,
  type TeamControlPlanePort,
} from "../../shared/api/teamControlPlane";
import type { ModelEnsembleLensId } from "../model-ensemble/metricAxisModel";
import { TeamAggregateBoard } from "./TeamAggregateBoard";
import { ControlPlaneReadinessNotice } from "./ControlPlaneReadinessNotice";
import { teamSnapshotSummary } from "./teamAggregatePresentation";
import { SCOPE_REASON_COPY, shortUtcDate } from "./teamAnalyticsCopy";
import "./TeamAnalytics.css";

/**
 * Compact team affordance for the floating overlay. It is a collapsed drawer
 * beneath the radar workspace: one summary line while closed, and the team
 * aggregate for the current lens once opened, so team context never crowds the
 * radar. Without a serving port it states that plainly instead of hiding.
 */
export function TeamContextDrawer({
  port,
  lensId,
}: {
  port: TeamControlPlanePort | null;
  lensId: ModelEnsembleLensId;
}) {
  const [open, setOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<TeamCapabilityReport | null>(null);
  const [capabilitiesFailed, setCapabilitiesFailed] = useState(false);
  const [snapshot, setSnapshot] = useState<TeamAggregateSnapshot | null>(null);
  const [snapshotRequest, setSnapshotRequest] = useState<TeamAggregateRequest | null>(null);
  const [aggregateState, setAggregateState] = useState<"idle" | "loading" | "ready" | "not_served" | "failed">("idle");
  const [statePort, setStatePort] = useState<TeamControlPlanePort | null>(port);

  useEffect(() => {
    setStatePort(port);
    setCapabilities(null);
    setCapabilitiesFailed(false);
    setSnapshot(null);
    setSnapshotRequest(null);
    setAggregateState("idle");
    if (port === null) return undefined;
    const controller = new AbortController();
    port.getCapabilities(controller.signal)
      .then((report) => {
        if (controller.signal.aborted) return;
        if (!teamCapabilityReportIsValid(report, port)) {
          setCapabilitiesFailed(true);
          return;
        }
        setCapabilities(report);
      })
      .catch(() => { if (!controller.signal.aborted) setCapabilitiesFailed(true); });
    return () => controller.abort();
  }, [port]);

  // Associate every cached value with the exact port that produced it. This
  // gates the render synchronously on a prop change, before effects clear it.
  const currentCapabilities = statePort === port ? capabilities : null;
  const currentCapabilitiesFailed = statePort === port && capabilitiesFailed;
  const teamAccess = currentCapabilities?.scopes.find((access) => access.scope === "team") ?? null;
  const teamRequest = teamAccess === null ? null : teamAggregateRequestForAccess(teamAccess);
  const currentSnapshot = statePort === port
    && snapshotRequest !== null
    && teamRequest !== null
    && teamAggregateRequestsEqual(snapshotRequest, teamRequest)
    ? snapshot
    : null;
  const currentAggregateState = statePort === port ? aggregateState : "idle";
  const teamAllowed = teamAccess?.state === "allowed" && teamRequest !== null;

  useEffect(() => {
    if (!open || port === null || !teamAllowed || teamRequest === null || currentSnapshot !== null) return undefined;
    const controller = new AbortController();
    setAggregateState("loading");
    port.getAggregate(teamRequest, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        if (!teamAggregateSnapshotIsValid(next, teamRequest, port)) {
          setSnapshot(null);
          setSnapshotRequest(null);
          setAggregateState("failed");
          return;
        }
        setSnapshot(next);
        setSnapshotRequest({ ...teamRequest });
        setAggregateState("ready");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setAggregateState(isTeamControlPlaneError(reason) ? "not_served" : "failed");
      });
    return () => controller.abort();
  }, [currentSnapshot, open, port, teamAllowed, teamRequest?.cohort_id, teamRequest?.organization_id, teamRequest?.principal_id, teamRequest?.query_id, teamRequest?.team_id]);

  const summary = teamSnapshotSummary(currentSnapshot);
  const status = port === null
    ? "Unavailable · local-only overlay"
    : currentCapabilitiesFailed
      ? "Permissions unavailable"
      : currentCapabilities === null
        ? "Checking permissions"
        : teamAllowed
          ? `${teamAccess?.cohort_label ?? "Team cohort"}${currentSnapshot === null ? "" : ` · ${summary.measured} measured`}`
          : currentCapabilities.control_plane_readiness !== null
            ? `Development boundary · ${currentCapabilities.control_plane_readiness.gaps.length} blockers`
          : teamAccess?.state === "denied" ? "Not permitted for this role" : "No team service in this runtime";

  return (
    <details
      className="team-context-drawer"
      data-team-access={teamAccess?.state ?? (port === null ? "unavailable" : "checking")}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span>Team context</span>
        <small>{status}</small>
      </summary>
      {open && <div className="team-context-drawer__body">
        {port === null || (currentCapabilities !== null && !teamAllowed) ? (
          <>
            <p>
              {port === null
                ? "This overlay runs without a team control plane. The live watch stays personal and local; no cohort exists, nothing is synced, and no team value is estimated."
                : teamAccess === null
                  ? "The port did not describe a team scope."
                  : SCOPE_REASON_COPY[teamAccess.reason]}
            </p>
            <ControlPlaneReadinessNotice
              compact
              readiness={currentCapabilities?.control_plane_readiness ?? null}
            />
          </>
        ) : currentCapabilitiesFailed ? (
          <p role="alert">Team permissions could not be read. Nothing is assumed; the personal watch is unaffected.</p>
        ) : currentCapabilities === null ? (
          <p role="status">Checking team permissions…</p>
        ) : currentAggregateState === "loading" || currentAggregateState === "idle" ? (
          <p role="status">Loading the team aggregate for this lens…</p>
        ) : currentAggregateState === "not_served" ? (
          <p role="status">The team scope is not served in this runtime.</p>
        ) : currentAggregateState === "failed" || currentSnapshot === null ? (
          <p role="alert">The team aggregate could not be loaded. The personal watch is unaffected.</p>
        ) : (
          <>
            <p className="team-context-drawer__meta">
              {currentSnapshot.cohort_label} · {currentSnapshot.window.label} · generated {shortUtcDate(currentSnapshot.generated_at)} · aggregate only, no member ranking
            </p>
            <TeamAggregateBoard lensId={lensId} mode="compact" snapshot={currentSnapshot} />
            <p className="team-context-drawer__footnote">
              Same lens as the radar. Bands are per-metric intervals, never a polygon; ◇ marks a separate experimental model range; state-only rows are never plotted at zero.
            </p>
          </>
        )}
      </div>}
    </details>
  );
}
