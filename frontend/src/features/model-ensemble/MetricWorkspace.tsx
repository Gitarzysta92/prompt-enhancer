import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type {
  ModelEnsembleRun,
  ModelEnsembleAttemptStage,
  PromptEnhancerTransport,
  RequirementPlanEvidenceContract,
  RequirementActionEvidenceContract,
} from "../../shared/api/contracts";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import {
  MetricKnowledgeCardSlot,
  metricKnowledgeCardTriggerProps,
  useMetricKnowledgeCardController,
} from "./MetricKnowledgeCard";
import { MetricHistoryDrawer, type MetricWorkspaceHistory } from "./MetricHistoryDrawer";
import { ModelConstellationDrawer } from "./ModelConstellationDrawer";
import { ModelEnsembleRadar } from "./ModelEnsembleRadar";
import {
  MODEL_ENSEMBLE_LENSES,
  MODEL_ENSEMBLE_OBJECTIVE_CONTRACT_COUNT,
  isModelEnsembleTypedMetric,
  isModelEnsembleV2Metric,
  modelEnsembleAxisGuidanceSentences,
  modelEnsembleAxisPendingBoundsLabel,
  modelEnsembleAxisRawRateLabel,
  modelEnsembleKnowledgeEntries,
  modelEnsembleMetricPresentation,
  modelEnsembleMetricStateValue,
  modelEnsembleObjectiveMeasurableCount,
  modelEnsembleObjectiveMeasuredCount,
  modelEnsemblePrimaryMetrics,
  modelEnsembleCompletedSmallExperts,
  modelEnsembleMetricStatus,
  modelEnsembleMetricStatusLabel,
  modelEnsemblePredictiveVisibility,
  modelEnsembleRadarAxes,
  type ModelEnsembleLensId,
  type ModelEnsembleRadarData,
} from "./metricAxisModel";
import { ME_SCOPE_CONTEXT, type MetricScopeContext } from "./metricContextFacts";
import { shortIdentity } from "./modelStages";
import { metricEvidenceReadinessForPublication } from "./metricEvidenceReadiness";
import { MetricEvidenceFilePanel } from "./MetricEvidenceFilePanel";
import { RequirementPlanEvidencePanel } from "./RequirementPlanEvidencePanel";
import { RequirementActionEvidencePanel } from "./RequirementActionEvidencePanel";

/**
 * The trajectory helpers and the history contract used to live in this file.
 * They are re-exported so existing imports keep working; new code should import
 * `./trajectorySelection` and `./MetricHistoryDrawer` directly.
 */
export {
  modelEnsembleHistoryRadarValue,
  modelEnsembleTrajectoryRadarData,
} from "./trajectorySelection";
export type { MetricWorkspaceHistory } from "./MetricHistoryDrawer";

const METRIC_CONTRACT_COUNT = MODEL_ENSEMBLE_LENSES.reduce(
  (total, lens) => total + lens.expectedMetricCount,
  0,
);
const METRIC_CONTRACT_KEYS = new Set(
  MODEL_ENSEMBLE_LENSES.flatMap((lens) => lens.metrics.map((metric) => metric.key)),
);

type PrimaryMetric = ReturnType<typeof modelEnsemblePrimaryMetrics>[number];

interface MetricWorkspaceReceiptSummary {
  measured: number;
  legacySignals: number;
  pending: number;
  notApplicable: number;
  unresolved: number;
  missing: number;
}

function metricWorkspaceReceiptSummary(
  metrics: readonly PrimaryMetric[],
): MetricWorkspaceReceiptSummary {
  const receipts = new Map<string, PrimaryMetric>();
  for (const metric of metrics) {
    if (METRIC_CONTRACT_KEYS.has(metric.metric_key)) receipts.set(metric.metric_key, metric);
  }
  const summary: MetricWorkspaceReceiptSummary = {
    measured: 0,
    legacySignals: 0,
    pending: 0,
    notApplicable: 0,
    unresolved: 0,
    missing: Math.max(0, METRIC_CONTRACT_COUNT - receipts.size),
  };
  for (const metric of receipts.values()) {
    const status = modelEnsembleMetricStatus(metric);
    if (metric.value_state === "known") {
      if (isModelEnsembleV2Metric(metric) || isModelEnsembleTypedMetric(metric)) summary.measured += 1;
      else summary.legacySignals += 1;
    } else if (status === "pending") {
      summary.pending += 1;
    } else if (metric.value_state === "not_applicable") {
      summary.notApplicable += 1;
    } else {
      summary.unresolved += 1;
    }
  }
  return summary;
}

function metricWorkspaceBoardValue(
  axis: ReturnType<typeof modelEnsembleRadarAxes>[number],
): string {
  const metric = axis.metric;
  if (metric === null || metric.value_state !== "known" || typeof metric.numeric_value !== "number") {
    return modelEnsembleMetricStateValue(metric);
  }
  if (axis.direction === "lower_is_better") {
    const kind = isModelEnsembleV2Metric(metric) || isModelEnsembleTypedMetric(metric)
      ? "measured raw rate"
      : "legacy signal";
    return `${Math.round(metric.numeric_value * 100)}% ${kind}`;
  }
  return modelEnsembleMetricPresentation(metric, axis.direction).value;
}

function metricWorkspaceComparisonLabel(label: string | undefined): string {
  const trimmed = label?.trim();
  return trimmed === undefined || trimmed === "" ? "the comparison publication" : trimmed;
}

export function metricEvidenceFileProjectionSupported(
  projectionVersion: string | undefined,
): boolean {
  return projectionVersion === "metric-contract-v2-projection-4"
    || projectionVersion === "metric-contract-v2-projection-5"
    || projectionVersion === "metric-contract-v2-projection-6"
    || projectionVersion === "metric-contract-v2-projection-7"
    || projectionVersion === "metric-contract-v2-projection-8";
}

export function MetricWorkspace({
  mode,
  run,
  runId,
  stageRun = null,
  transport,
  lensId,
  onLensChange,
  snapshotLabel,
  comparisonRun = null,
  comparisonLabel,
  scopeLabel = "Scope not exposed",
  history,
  attemptStages = [],
  scopeContext,
  evidenceSessionId,
  evidenceEnabled = false,
  onEvidenceChanged,
}: {
  mode: "full" | "compact";
  run: ModelEnsembleRadarData;
  runId: string;
  stageRun?: ModelEnsembleRun | null;
  transport: Pick<PromptEnhancerTransport,
    | "getModelPredictiveMetricDetail"
    | "previewAgentMetricEvidence"
    | "importAgentMetricEvidence"
    | "listMetricLifecycleProposals"
    | "decideMetricLifecycleProposal"
    | "getRequirementPlanEvidenceContract"
    | "previewRequirementPlanEvidence"
    | "importRequirementPlanEvidence"
    | "listRequirementPlanProposals"
    | "reviewRequirementPlanProposal"
    | "decideRequirementPlanProposal"
    | "getRequirementActionEvidenceContract"
    | "previewRequirementActionEvidence"
    | "importRequirementActionEvidence"
    | "listRequirementActionProposals"
    | "reviewRequirementActionProposal"
    | "decideRequirementActionProposal">
    & Partial<Pick<PromptEnhancerTransport, "getUserPresenceCapability">>;
  lensId: ModelEnsembleLensId;
  onLensChange: (lens: ModelEnsembleLensId) => void;
  snapshotLabel: string;
  comparisonRun?: ModelEnsembleRadarData | null;
  comparisonLabel?: string;
  scopeLabel?: string;
  history?: MetricWorkspaceHistory;
  attemptStages?: readonly ModelEnsembleAttemptStage[];
  /** Analytics scope carried into every knowledge card (strip and board); defaults to Me. */
  scopeContext?: MetricScopeContext;
  evidenceSessionId?: string;
  evidenceEnabled?: boolean;
  onEvidenceChanged?: () => void;
}) {
  const [selectedMetricKey, setSelectedMetricKey] = useState("");
  const boardHelp = useMetricKnowledgeCardController(runId);
  const previousRunId = useRef(runId);
  const workspaceHeadingId = useId();
  const boardHeadingId = useId();
  const axes = useMemo(() => modelEnsembleRadarAxes(run, lensId), [lensId, run]);
  const primaryMetrics = useMemo(() => modelEnsemblePrimaryMetrics(run), [run]);
  const receiptSummary = useMemo(
    () => metricWorkspaceReceiptSummary(primaryMetrics),
    [primaryMetrics],
  );
  const completedSmallExperts = modelEnsembleCompletedSmallExperts(run);
  const visibleExperimental = (run.predictive_metrics ?? []).filter(
    (metric) => modelEnsemblePredictiveVisibility(metric, completedSmallExperts).visible,
  ).length;
  const objectiveMeasured = modelEnsembleObjectiveMeasuredCount(run);
  // Derived from the sealed states themselves (capability_available on the five
  // objective contracts), so the header stays truthful with or without the
  // additive readiness projection; the projection can only restate this count.
  const objectiveMeasurable = modelEnsembleObjectiveMeasurableCount(run);
  const evidenceReadiness = useMemo(
    () => metricEvidenceReadinessForPublication(run.metric_evidence_readiness_v2, run.metric_publication_v2),
    [run.metric_evidence_readiness_v2, run.metric_publication_v2],
  );
  const comparisonHasNumericValues = useMemo(
    () => comparisonRun !== null
      && modelEnsembleRadarAxes(comparisonRun, lensId).some((axis) => axis.plotted !== null),
    [comparisonRun, lensId],
  );
  const defaultMetricKey = axes.find((axis) => (
    axis.metric?.value_state === "known"
    && (isModelEnsembleV2Metric(axis.metric) || isModelEnsembleTypedMetric(axis.metric))
  ))?.key
    ?? axes.find((axis) => axis.metric?.value_state === "known")?.key
    ?? axes.find((axis) => axis.metric !== null)?.key
    ?? axes[0]?.key
    ?? "";
  const activeMetricKey = axes.some((axis) => axis.key === selectedMetricKey)
    ? selectedMetricKey
    : defaultMetricKey;
  const activeDirection = axes.find((axis) => axis.key === activeMetricKey)?.direction ?? "higher_is_better";
  const activeLens = MODEL_ENSEMBLE_LENSES.find((lens) => lens.id === lensId);
  useLayoutEffect(() => {
    if (previousRunId.current === runId) return;
    previousRunId.current = runId;
    boardHelp.dismiss();
  }, [boardHelp.dismiss, runId]);
  return (
    <section
      aria-labelledby={workspaceHeadingId}
      className={`metric-workspace metric-workspace--${mode}`}
      data-run-id={runId}
      data-workspace-mode={mode}
    >
      <header className="metric-workspace__snapshot">
        <div>
          <span>{snapshotLabel}</span>
          <h3 id={workspaceHeadingId}>Metric workspace · Snapshot {shortIdentity(runId)}</h3>
          <span className="metric-workspace__scope" data-scope={(scopeContext ?? ME_SCOPE_CONTEXT).scope}>Scope · {(scopeContext ?? ME_SCOPE_CONTEXT).label}</span>
        </div>
        <dl aria-label={`${METRIC_CONTRACT_COUNT}-contract receipt summary`}>
          <div data-receipt-state="measured"><dt>Measured</dt><dd>{receiptSummary.measured}/{METRIC_CONTRACT_COUNT}</dd></div>
          <div data-receipt-state="legacy_signal"><dt>Legacy signals</dt><dd>{receiptSummary.legacySignals}</dd></div>
          <div data-receipt-state="pending"><dt>Pending</dt><dd>{receiptSummary.pending}</dd></div>
          <div data-receipt-state="not_applicable"><dt>N/A</dt><dd>{receiptSummary.notApplicable}</dd></div>
          <div data-receipt-state="unresolved"><dt>Unresolved</dt><dd>{receiptSummary.unresolved}</dd></div>
          <div data-receipt-state="missing"><dt>No receipt</dt><dd>{receiptSummary.missing}</dd></div>
          {objectiveMeasurable !== null && (
            <div data-objective-measurable={objectiveMeasurable}>
              <dt>Objective measurable</dt>
              <dd>{objectiveMeasurable}/{MODEL_ENSEMBLE_OBJECTIVE_CONTRACT_COUNT}</dd>
            </div>
          )}
          {objectiveMeasured !== null && (
            <div data-objective-measured={objectiveMeasured}>
              <dt>Objective measured</dt>
              <dd>{objectiveMeasured}/{MODEL_ENSEMBLE_OBJECTIVE_CONTRACT_COUNT}</dd>
            </div>
          )}
          {evidenceReadiness !== null && (
            <div data-capability-gaps={evidenceReadiness.capability_missing_count}>
              <dt>Capability gaps</dt><dd>{evidenceReadiness.capability_missing_count}/20</dd>
            </div>
          )}
          <div><dt>Visible estimates</dt><dd>{visibleExperimental}/20</dd></div>
          <div><dt>Window</dt><dd>{scopeLabel}</dd></div>
        </dl>
      </header>
      <div
        aria-label="Metric workspace view"
        className="metric-workspace__lenses"
        onKeyDown={(event) => moveRovingFocus(event, (index) => onLensChange(MODEL_ENSEMBLE_LENSES[index].id))}
        role="group"
      >
        {MODEL_ENSEMBLE_LENSES.map((lens) => (
          <button
            aria-label={`${lens.label} lens · ${lens.expectedMetricCount} metrics`}
            aria-pressed={lens.id === lensId}
            key={lens.id}
            onClick={() => onLensChange(lens.id)}
            type="button"
          >
            <span aria-hidden="true">{lens.shortLabel}</span><small aria-hidden="true">{lens.expectedMetricCount} metrics</small>
          </button>
        ))}
      </div>
      <div className="metric-workspace__primary">
        <ModelEnsembleRadar
          compact={mode === "compact"}
          comparisonLabel={comparisonLabel}
          comparisonRun={comparisonRun}
          contextIdentity={runId}
          detailRunId={runId}
          detailTransport={transport}
          helpController={boardHelp}
          lensId={lensId}
          scopeContext={scopeContext}
          onSelectedMetricKeyChange={setSelectedMetricKey}
          run={run}
          selectedMetricKey={activeMetricKey}
          snapshotLabel={snapshotLabel}
        />
        {mode === "full" && (
          <section aria-labelledby={boardHeadingId} className="metric-workspace__board">
            <header><h4 id={boardHeadingId}>{activeLens?.label ?? "Metric values"} · exact metric values</h4><span>Exact states and next actions</span></header>
            <div onKeyDown={(event) => moveRovingFocus(event, (index) => setSelectedMetricKey(axes[index].key))}>
              {axes.map((axis) => {
                const status = modelEnsembleMetricStatus(axis.metric);
                const rawRate = modelEnsembleAxisRawRateLabel(axis);
                const pendingBounds = modelEnsembleAxisPendingBoundsLabel(axis);
                const numericValue = axis.metric?.numeric_value;
                const radarOrientation = rawRate === null || typeof numericValue !== "number"
                  ? null
                  : `radar orientation ${100 - Math.round(numericValue * 100)}%`;
                // The same two sentences the radar inspector and knowledge card
                // render: the action here can never differ from the inspector's.
                const guidance = modelEnsembleAxisGuidanceSentences(axis);
                return (
                  <button
                    aria-pressed={axis.key === activeMetricKey}
                    data-guidance-kind={guidance.kind}
                    data-status={status}
                    key={axis.key}
                    {...metricKnowledgeCardTriggerProps(boardHelp, "board", axis.key)}
                    onClick={() => { setSelectedMetricKey(axis.key); boardHelp.togglePin({ surface: "board", metricKey: axis.key }); }}
                    type="button"
                  >
                    <span>
                      <strong>{axis.label}</strong>
                      <small>
                        {modelEnsembleMetricStatusLabel(status)}
                        {radarOrientation === null ? "" : ` · ${radarOrientation}`}
                        {pendingBounds === null ? "" : ` · ${pendingBounds}`}
                      </small>
                    </span>
                    <b>{metricWorkspaceBoardValue(axis)}</b>
                    <span aria-hidden="true" className="metric-workspace__board-action">{guidance.action}</span>
                  </button>
                );
              })}
            </div>
            <MetricKnowledgeCardSlot
              controller={boardHelp}
              entries={modelEnsembleKnowledgeEntries(axes, scopeContext)}
              surface="board"
            />
          </section>
        )}
      </div>
      {evidenceEnabled
        && evidenceSessionId !== undefined
        && metricEvidenceFileProjectionSupported(run.metric_publication_v2?.projection_version)
        && (
          <MetricEvidenceFilePanel
            compact={mode === "compact"}
            onEvidenceChanged={onEvidenceChanged}
            sessionId={evidenceSessionId}
            sourceRunId={runId}
            transport={transport}
          />
        )}
      {evidenceEnabled
        && evidenceSessionId !== undefined
        && ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
          run.metric_publication_v2?.projection_version ?? "",
        )
        && stageRun?.requirement_action_evidence_binding !== null
        && stageRun?.requirement_action_evidence_binding !== undefined
        && (
          <RequirementActionEvidencePanel
            compact={mode === "compact"}
            onEvidenceChanged={onEvidenceChanged}
            publicEvidenceBinding={stageRun.requirement_action_evidence_binding}
            publicEvidenceSource={stageRun.requirement_action_evidence_binding.evidence_source}
            sessionId={evidenceSessionId}
            sourceProjectionVersion={run.metric_publication_v2!.projection_version as RequirementActionEvidenceContract["source_projection_version"]}
            sourceRunId={runId}
            transport={transport}
          />
        )}
      {evidenceEnabled
        && evidenceSessionId !== undefined
        && [
          "metric-contract-v2-projection-5",
          "metric-contract-v2-projection-6",
          "metric-contract-v2-projection-7",
          "metric-contract-v2-projection-8",
        ].includes(run.metric_publication_v2?.projection_version ?? "")
        && (
          <RequirementPlanEvidencePanel
            compact={mode === "compact"}
            onEvidenceChanged={onEvidenceChanged}
            sessionId={evidenceSessionId}
            sourceProjectionVersion={run.metric_publication_v2!.projection_version as RequirementPlanEvidenceContract["source_projection_version"]}
            sourceRunId={runId}
            transport={transport}
          />
        )}
      {comparisonRun !== null && (
        <p
          className="metric-workspace__comparison-note"
          data-comparison-state={comparisonHasNumericValues ? "numeric" : "state_only"}
        >
          {comparisonHasNumericValues
            ? `Dashed geometry marks ${metricWorkspaceComparisonLabel(comparisonLabel)} where numeric values exist.`
            : `No numeric comparison is available for ${metricWorkspaceComparisonLabel(comparisonLabel)} in this lens.`}
        </p>
      )}
      <div className="metric-workspace__drawers">
        <ModelConstellationDrawer attemptStages={attemptStages} compact={mode === "compact"} run={stageRun} />
        <MetricHistoryDrawer
          direction={activeDirection}
          history={activeMetricKey === "" ? undefined : history}
          metricKey={activeMetricKey}
        />
      </div>
    </section>
  );
}
