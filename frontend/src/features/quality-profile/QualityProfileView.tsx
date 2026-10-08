import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { formatPercent } from "../../shared/lib/format";
import type {
  ProviderCompatibilityStatus,
  SessionMetricReadinessReport,
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisPreviewApprovalRequest,
  SessionQualityAnalysisPreviewRequest,
  SessionTextAnalysisCapability,
} from "../../shared/api/contracts";
import { parseSessionMetricReadinessReport } from "../../shared/api/httpTransport";
import { METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS } from "../../shared/api/metricOperabilityContract";
import {
  promptTextCompatibilityBlocker,
  ProviderCompatibilityCard,
} from "../provider-compatibility";
import { AnalyzeLocallyDialog } from "./AnalyzeLocallyDialog";
import { MetricOpportunityMap } from "./MetricOpportunityMap";
import { ProfileShareDialog } from "./ProfileShareDialog";
import { QualityRadar } from "./QualityRadar";
import "./QualityProfileView.css";
import type {
  QualityMetricObservation,
  QualityMetricProfile,
  QualityMetricState,
  QualitySnapshotKind,
} from "./qualityProfile";

const STATE_LABELS: Record<QualityMetricState, string> = {
  observed: "Rule candidate",
  partial: "Partial rule candidate",
  "not-selected": "Not selected",
  incompatible: "Incompatible provenance",
  unavailable: "Unknown",
  abstained: "Not measurable",
  "not-applicable": "Not applicable",
  "execution-error": "Execution error",
};

const PROVIDER_ADAPTER_GAP_KEYS = new Set<string>(
  METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS,
);

function isProviderAdapterUnavailable(metric: QualityMetricObservation): boolean {
  if (!PROVIDER_ADAPTER_GAP_KEYS.has(metric.definition.key)) return false;
  return ![
    "observed",
    "partial",
    "not-selected",
    "incompatible",
    "not-applicable",
    "execution-error",
  ].includes(metric.state);
}

function stateLabel(metric: QualityMetricObservation): string {
  return isProviderAdapterUnavailable(metric)
    ? "Provider adapter unavailable"
    : STATE_LABELS[metric.state];
}

const SIGNAL_LABELS: Record<string, string> = {
  "goal.action": "Requested action cue",
  "goal.target": "Possible target after the action",
  "goal.outcome": "Purpose or intended-outcome connector",
  "constraint.expected_categories": "Applicable constraint categories",
  "completion.requirements": "Detected requirement clauses",
  "completion.checkable": "Clauses with an observable-check cue",
  "deliverable.expected_slots": "Applicable output-detail slots",
  "choices.prompt_clauses": "Analyzed user clauses",
  "choices.marker_clauses": "Clauses with unresolved-choice markers",
  "task.action": "Requested-action cue",
  "task.target": "Possible action target",
  "task.context": "Operating-context cue",
  "task.outcome": "Outcome or check cue",
  "problem.observed": "Observed-behavior cue",
  "problem.expected": "Expected-behavior cue",
  "problem.reproduction": "Reproduction-step cue",
  "problem.environment": "Environment cue",
  "context.artifact": "Artifact or component cue",
  "context.current_state": "Current-state cue",
  "context.environment": "Environment or version cue",
  "context.boundary": "Scope or boundary cue",
  "constraints.detected": "Detected constraint clauses",
  "constraints.precise": "Constraints with a concrete detail",
  "acceptance.requirements": "Detected requirement clauses",
  "acceptance.checkable": "Requirements with a check cue",
  "deliverables.detected": "Detected deliverable clauses",
  "deliverables.detailed": "Deliverables with an output-detail cue",
  "ambiguity.candidates": "Detected ambiguity candidates",
  "ambiguity.resolved": "Candidates followed by clarification",
  "clarification.questions": "Detected agent questions",
  "clarification.productive": "Questions followed by a substantive answer",
  "exploration.hypotheses": "Detected exploration or hypothesis clauses",
  "exploration.converted": "Clauses followed by plan or evidence",
  "scope.changes": "Detected scope changes",
  "scope.acknowledged": "Scope changes followed by acknowledgement",
  "rework.feedback_turns": "User feedback turns",
  "rework.candidates": "Correction-marker candidates",
};

function signalLabel(code: string): string {
  return SIGNAL_LABELS[code] ?? code.replaceAll(".", " ");
}

function signalValue(
  status: "detected" | "missing" | "counted" | "unknown",
  count: number | null,
): string {
  if (status === "detected") return "Detected";
  if (status === "missing") return "Missing";
  if (status === "unknown") return "Unknown";
  return count !== null && Number.isSafeInteger(count) && count >= 0
    ? `${count}`
    : "Count unavailable";
}

function explanationLine(metric: QualityMetricObservation): string | null {
  if (metric.errorCode === "metric-not-selected") {
    return "This metric was outside the exact metric scope selected for the completed run. It is omitted—not missing, failed, or scored as zero.";
  }
  if (metric.errorCode === "metric-scope-unknown") {
    return "This legacy run did not record its selected metric scope, so absence cannot be classified as an omission or a failure.";
  }
  if (metric.errorCode === "incompatible-provenance") {
    return "Stored observations use incompatible metric, provider, redactor, or estimator provenance. No combined value is shown and this state is not an execution failure.";
  }
  if (isProviderAdapterUnavailable(metric)) {
    return "Unavailable with the current provider adapter. This contract needs typed, reviewed evidence links; agent prose, model estimates, and missing evidence never fill the value or become zero.";
  }
  if (
    metric.definition.key === "collaboration.exploration_conversion" &&
    metric.ratio === 0 &&
    metric.fractionDenominator !== null
  ) {
    return `The rule found ${metric.fractionDenominator} hypothesis-marker clause${metric.fractionDenominator === 1 ? "" : "s"}, but no later related structured plan, decision, action, or verification item. This is an uncalibrated lexical-link result—not zero exploration ability.`;
  }
  if (metric.explanationCode === "denominator_unknown") {
    return "Not measured: Standard engineering v1 cannot safely assume which task-specific factors apply. This is not a zero or a negative judgment.";
  }
  if (metric.explanationCode === "source_extraction_incomplete") {
    return "The provider projection was incomplete, so the extractor abstained instead of scoring partial evidence.";
  }
  if (metric.explanationCode === "unsupported_language") {
    return "The selected window did not contain enough supported English or Polish text for this rule set.";
  }
  if (metric.explanationCode === "message_kind_unavailable") {
    return "The provider cannot expose the message kind required by this metric.";
  }
  if (metric.explanationCode === "message_kind_unobserved") {
    return "The required message kind was supported but not observed in this window.";
  }
  if (metric.explanationCode === "diagnostic_task_not_detected") {
    return "No bug or diagnosis-task cue was detected, so problem-evidence quality stays Unknown instead of becoming zero.";
  }
  if (
    metric.explanationCode?.endsWith("_unobserved") ||
    metric.explanationCode?.endsWith("_unknown")
  ) {
    return "The metric-specific denominator was not observed in this window. The result stays Unknown, not zero.";
  }
  if (metric.explanationCode === "conversion_evidence_unavailable") {
    return "The provider does not expose a structured plan, decision, action, or verification item needed to assess conversion.";
  }
  if (
    metric.explanationCode === "objective_evidence_stream_required" ||
    metric.explanationCode === "objective_verification_stream_required" ||
    metric.explanationCode === "objective_verification_episode_required"
  ) {
    return "This metric requires structured objective evidence. Agent prose and completion claims are deliberately ignored, so the result abstains.";
  }
  return null;
}

function denominatorSource(metric: QualityMetricObservation): string {
  if (metric.definition.key === "prompt.goal_definition") {
    return "Fixed Standard engineering v1 slots: action, target, outcome.";
  }
  if (metric.definition.key === "prompt.completion_evaluability") {
    return "Requirement clauses conservatively detected by deterministic rules.";
  }
  if (metric.definition.key === "prompt.open_decision_load") {
    return "All analyzed user clauses in the bounded window.";
  }
  if (metric.definition.key === "prompt.task_definition_coverage") {
    return "Three focus-request factors: action, target, and intended outcome.";
  }
  if (metric.definition.key === "prompt.problem_evidence_quality") {
    return "Only diagnosis candidates: observed behavior, expected behavior, reproduction, and environment.";
  }
  if (metric.definition.key === "prompt.context_sufficiency") {
    return "Three focus-request factors: current state, environment or version, and boundary.";
  }
  if (metric.explanationCode === "denominator_unknown") {
    return "Unknown—the standard preset deliberately does not invent one.";
  }
  return "Versioned task profile or metric-specific observed candidates.";
}

function summary(metrics: readonly QualityMetricObservation[]): string {
  if (metrics.length === 0) return "No metric observations supplied";
  const observed = metrics.filter((metric) => metric.state === "observed").length;
  const partial = metrics.filter((metric) => metric.state === "partial").length;
  const notSelected = metrics.filter((metric) => metric.state === "not-selected").length;
  const incompatible = metrics.filter((metric) => metric.state === "incompatible").length;
  const unavailable = metrics.filter((metric) => metric.state === "unavailable").length;
  const abstained = metrics.filter((metric) => metric.state === "abstained").length;
  const failed = metrics.filter((metric) => metric.state === "execution-error").length;
  const notApplicable = metrics.filter((metric) => metric.state === "not-applicable").length;
  return [
    `${observed} assessable`,
    partial > 0 ? `${partial} partial` : null,
    notSelected > 0 ? `${notSelected} not selected` : null,
    incompatible > 0 ? `${incompatible} incompatible` : null,
    unavailable > 0 ? `${unavailable} unavailable` : null,
    abstained > 0 ? `${abstained} not measurable` : null,
    failed > 0 ? `${failed} failed` : null,
    notApplicable > 0 ? `${notApplicable} not applicable` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function coverageLine(metric: QualityMetricObservation): string {
  if (metric.state === "not-selected") {
    return "Not in the selected metric scope; excluded from analysis coverage.";
  }
  if (metric.eligible === 0) return "No eligible observations were available for this snapshot.";
  if (
    !Number.isSafeInteger(metric.observed) ||
    !Number.isSafeInteger(metric.eligible) ||
    metric.observed < 0 ||
    metric.eligible < 1 ||
    metric.observed > metric.eligible ||
    !Number.isFinite(metric.coverage) ||
    metric.coverage < 0 ||
    metric.coverage > 1
  ) {
    return "Window coverage is unavailable because the stored counts are not valid.";
  }
  return `${metric.observed} of ${metric.eligible} eligible observations were usable (${formatPercent(metric.coverage)} coverage).`;
}

function fractionLine(metric: QualityMetricObservation): string {
  if (metric.state === "not-selected") {
    return "No fraction was expected because this metric was not selected.";
  }
  if (
    metric.fractionNumerator === null ||
    metric.fractionDenominator === null ||
    !Number.isSafeInteger(metric.fractionNumerator) ||
    !Number.isSafeInteger(metric.fractionDenominator) ||
    metric.fractionNumerator < 0 ||
    metric.fractionDenominator < 1 ||
    metric.fractionNumerator > metric.fractionDenominator
  ) {
    return "No metric fraction was produced for this state.";
  }
  return `${metric.fractionNumerator} of ${metric.fractionDenominator} metric-specific items satisfied the candidate definition.`;
}

export interface AnalyzeLocallyHandler {
  exactSessionId: string;
  preparePreview: (
    sessionId: string,
    request: SessionQualityAnalysisPreviewRequest,
    signal: AbortSignal,
  ) => Promise<SessionQualityAnalysisPreview>;
  approvePreview: (
    sessionId: string,
    previewId: string,
    request: SessionQualityAnalysisPreviewApprovalRequest,
    idempotencyKey: string,
    signal: AbortSignal,
  ) => Promise<void>;
}

function analysisCapabilityCopy(
  capability: SessionTextAnalysisCapability,
): string | null {
  if (capability.available) return null;
  if (capability.reason_code === "local_source_unavailable") {
    return "Analyze is unavailable because the Codex local-source adapter is not active.";
  }
  if (capability.reason_code === "analysis_service_unavailable") {
    return "This running app does not expose bounded text analysis. Restart after updating the local backend.";
  }
  if (capability.reason_code === "redacted_content_consent_required") {
    return "Redacted-text consent is not active. Open Data sources and grant access before analyzing.";
  }
  if (capability.reason_code === "consent_status_invalid") {
    return "Consent status could not be verified, so local analysis stays disabled.";
  }
  if (capability.reason_code === "synthetic_preview") {
    return "New local analyses are disabled in the fictional preview.";
  }
  return "Capability status could not be verified, so local analysis stays disabled.";
}

interface QualityProfileViewProps {
  profile: QualityMetricProfile;
  onAnalyzeLocally?: AnalyzeLocallyHandler;
  /** Null or omitted means capability has not been verified yet. */
  analysisCapability?: SessionTextAnalysisCapability | null;
  providerCompatibility?: ProviderCompatibilityStatus | null;
  compatibilityLoading?: boolean;
  onCheckProviderCompatibility?: (signal: AbortSignal) => Promise<void>;
  onRetryMetricReadiness?: () => void;
  onUpdateProvider?: () => void;
  /** Cached, content-free explanation metadata. It never supplies metric values. */
  metricReadiness?: SessionMetricReadinessReport | null;
  metricReadinessError?: string;
  metricReadinessLoading?: boolean;
  /** Optional compact coaching deck rendered below the collapsible radar. */
  primaryContent?: ReactNode;
  /** Content-free identity shown before a real provider read begins. */
  sessionDescriptor?: string;
  /** False when this profile is embedded as a demoted legacy disclosure. */
  manageDocumentContext?: boolean;
}

function numericOwnerIdentity(value: number | null): readonly [string, number?] {
  if (value === null) return ["null"];
  if (Number.isNaN(value)) return ["nan"];
  if (value === Number.POSITIVE_INFINITY) return ["positive-infinity"];
  if (value === Number.NEGATIVE_INFINITY) return ["negative-infinity"];
  if (Object.is(value, -0)) return ["negative-zero"];
  return ["finite", value];
}

function profileOwnerIdentity(
  profile: QualityMetricProfile,
  exactSessionId: string | undefined,
): string {
  function snapshotIdentity(snapshot: QualityMetricProfile["latest"]) {
    return {
      kind: snapshot.kind,
      integrity: snapshot.integrity,
      pack: snapshot.metricPackVersion,
      scope: snapshot.scope,
      metrics: snapshot.metrics.map((metric) => ({
        key: metric.definition.key,
        version: metric.definition.version,
        direction: metric.definition.direction,
        state: metric.state,
        ratio: numericOwnerIdentity(metric.ratio),
        numerator: numericOwnerIdentity(metric.fractionNumerator),
        denominator: numericOwnerIdentity(metric.fractionDenominator),
        observed: numericOwnerIdentity(metric.observed),
        eligible: numericOwnerIdentity(metric.eligible),
        coverage: numericOwnerIdentity(metric.coverage),
        notSelectedRuns: numericOwnerIdentity(metric.notSelectedRuns),
        unknownScopeRuns: numericOwnerIdentity(metric.unknownScopeRuns),
        schema: metric.metricSchemaVersion,
        explanation: metric.explanationCode,
        algorithm: metric.algorithmId,
        algorithmVersion: metric.algorithmVersion,
        model: metric.modelId,
        error: metric.errorCode,
        definitionVersion: metric.definitionVersion,
        computedAt: metric.computedAt,
        signals: metric.signals.map((signal) => [
          signal.code,
          signal.status,
          numericOwnerIdentity(signal.count),
        ]),
      })),
    };
  }
  return JSON.stringify({
    session: exactSessionId ?? null,
    kind: profile.kind,
    analysisProfile: profile.analysisProfile?.state ?? null,
    initial: snapshotIdentity(profile.initial),
    latest: snapshotIdentity(profile.latest),
  });
}

function readinessBelongsToProfile(
  report: SessionMetricReadinessReport,
  profile: QualityMetricProfile,
  exactSessionId: string | undefined,
  providerCompatibility: ProviderCompatibilityStatus | null | undefined,
): boolean {
  return (
    exactSessionId !== undefined &&
    report.session_id === exactSessionId &&
    profile.analysisProfile?.state === "coaching" &&
    report.preset_id === "coaching_profile_v1" &&
    report.analysis_profile_key === "coaching_profile" &&
    report.analysis_profile_version === 1 &&
    report.metric_pack_key === "experimental.redacted-text.coaching" &&
    report.metric_pack_version === profile.latest.metricPackVersion &&
    report.capability_report.provider === report.provider &&
    providerCompatibility != null &&
    providerCompatibility.capability === "session_text_analysis" &&
    providerCompatibility.provider === report.provider
  );
}

function validatedMetricReadiness(
  report: SessionMetricReadinessReport | null | undefined,
): SessionMetricReadinessReport | null {
  if (report == null) return null;
  try {
    return parseSessionMetricReadinessReport(report);
  } catch {
    return null;
  }
}

interface CapturedAnalysisContext {
  handler: AnalyzeLocallyHandler;
  onCheckCompatibility?: (signal: AbortSignal) => Promise<void>;
  ownerIdentity: string;
  sessionDescriptor?: string;
}

export function QualityProfileView(props: QualityProfileViewProps) {
  const ownerIdentity = profileOwnerIdentity(
    props.profile,
    props.onAnalyzeLocally?.exactSessionId,
  );
  return <QualityProfileViewOwned {...props} ownerIdentity={ownerIdentity} />;
}

function QualityProfileViewOwned({
  profile,
  onAnalyzeLocally,
  analysisCapability,
  onRetryMetricReadiness,
  providerCompatibility,
  compatibilityLoading = false,
  onCheckProviderCompatibility,
  onUpdateProvider,
  primaryContent,
  metricReadiness,
  metricReadinessError = "",
  metricReadinessLoading = false,
  sessionDescriptor,
  manageDocumentContext = true,
  ownerIdentity,
}: QualityProfileViewProps & { ownerIdentity: string }) {
  const [snapshotKind, setSnapshotKind] = useState<QualitySnapshotKind>("latest");
  const [shareOpen, setShareOpen] = useState(false);
  const [analysisContext, setAnalysisContext] =
    useState<CapturedAnalysisContext | null>(null);
  const [providerCheckState, setProviderCheckState] = useState<{
    failed: boolean;
    pending: boolean;
  }>({ failed: false, pending: false });
  const headingRef = useRef<HTMLHeadingElement>(null);
  const providerCheckControllerRef = useRef<AbortController | null>(null);
  const activeOwnerIdentityRef = useRef(ownerIdentity);
  const id = useId();
  const profileTitleId = `${id}-quality-profile-title`;
  const analysisCapabilityId = `${id}-quality-analysis-capability`;
  const pipelineTitleId = `${id}-quality-pipeline-title`;
  const metricDetailsTitleId = `${id}-quality-metric-details-title`;
  const snapshot = snapshotKind === "initial" ? profile.initial : profile.latest;
  const initialAvailable = profile.initial.integrity !== "unavailable";
  // Every current qualitative pack is explicitly uncalibrated. Export stays
  // disabled until a future human-calibrated profile has its own closed DTO.
  const shareBlocked = true;
  const integrityBlocked =
    snapshot.integrity === "invalid-contract" ||
    snapshot.integrity === "mixed-provenance";
  const stalePack = snapshot.integrity === "stale-pack";
  const allNotSelected = snapshot.metrics.length > 0 && snapshot.metrics.every(
    (metric) => metric.state === "not-selected",
  );
  const allUnavailable = snapshot.metrics.length > 0 && snapshot.metrics.every(
    (metric) => metric.state === "unavailable",
  );
  const allLegacyScopeUnknown = allUnavailable && snapshot.metrics.every(
    (metric) => metric.errorCode === "metric-scope-unknown",
  );
  const shareBlockedTitle =
    snapshot.integrity === "unavailable" || stalePack
      ? "Run Coaching v1 analysis before sharing"
      : snapshot.integrity !== "coherent"
        ? "Sharing is blocked until metric provenance is coherent"
        : "Sharing is blocked until coaching candidates are human calibrated";
  const providerCheckPending = providerCheckState.pending;
  const capabilityMessage =
    analysisCapability == null
      ? "Checking whether this local installation supports bounded text analysis."
      : analysisCapabilityCopy(analysisCapability);
  const compatibilityMessage = compatibilityLoading || providerCheckPending
    ? "Provider compatibility is being checked, so prompt-text analysis stays disabled."
    : promptTextCompatibilityBlocker(providerCompatibility ?? null);
  const analysisBlocker = capabilityMessage ?? compatibilityMessage;
  const analysisDisabled = analysisBlocker !== null;
  const validatedReadiness = validatedMetricReadiness(metricReadiness);
  const readinessOwned =
    validatedReadiness !== null &&
    readinessBelongsToProfile(
      validatedReadiness,
      profile,
      onAnalyzeLocally?.exactSessionId,
      providerCompatibility,
    );
  const ownedReadiness = readinessOwned ? validatedReadiness : null;
  const readinessStale = metricReadiness != null && !readinessOwned;

  async function checkProviderCompatibility(
    handler: (signal: AbortSignal) => Promise<void>,
  ) {
    if (providerCheckPending) {
      return;
    }
    const requestOwnerIdentity = ownerIdentity;
    const controller = new AbortController();
    providerCheckControllerRef.current?.abort();
    providerCheckControllerRef.current = controller;
    setProviderCheckState({ failed: false, pending: true });
    try {
      await handler(controller.signal);
    } catch {
      if (
        !controller.signal.aborted &&
        activeOwnerIdentityRef.current === requestOwnerIdentity
      ) {
        setProviderCheckState({ failed: true, pending: false });
      }
    } finally {
      if (providerCheckControllerRef.current === controller) {
        providerCheckControllerRef.current = null;
      }
      if (
        !controller.signal.aborted &&
        activeOwnerIdentityRef.current === requestOwnerIdentity
      ) {
        setProviderCheckState((current) => ({ ...current, pending: false }));
      }
    }
  }

  useEffect(() => {
    if (!manageDocumentContext) return undefined;
    const previousTitle = document.title;
    const profileTitle = `${profile.title} · Prompt Enhancer`;
    document.title = profileTitle;
    headingRef.current?.focus();
    return () => {
      if (document.title === profileTitle) document.title = previousTitle;
    };
  }, [manageDocumentContext, profile.title]);

  useLayoutEffect(() => {
    if (activeOwnerIdentityRef.current === ownerIdentity) return;
    activeOwnerIdentityRef.current = ownerIdentity;
    providerCheckControllerRef.current?.abort();
    providerCheckControllerRef.current = null;
    setSnapshotKind("latest");
    setShareOpen(false);
    setAnalysisContext(null);
    setProviderCheckState({ failed: false, pending: false });
  }, [ownerIdentity]);

  useLayoutEffect(
    () => () => providerCheckControllerRef.current?.abort(),
    [],
  );

  return (
    <section
      aria-labelledby={profileTitleId}
      className={`quality-profile quality-profile--${profile.kind}`}
    >
      <header className="quality-profile__header">
        <div>
          <p className="eyebrow">{profile.eyebrow}</p>
          <h2 id={profileTitleId} ref={headingRef} tabIndex={-1}>{profile.title}</h2>
          <p>{profile.question}</p>
        </div>
        <div className="quality-profile__actions">
          {initialAvailable && (
            <div aria-label="Specification point" className="quality-profile__switch" role="group">
              <button
                aria-pressed={snapshotKind === "initial"}
                onClick={() => setSnapshotKind("initial")}
                type="button"
              >
                {profile.initialLabel}
              </button>
              <button
                aria-pressed={snapshotKind === "latest"}
                onClick={() => setSnapshotKind("latest")}
                type="button"
              >
                {profile.latestLabel}
              </button>
            </div>
          )}
          {onAnalyzeLocally && compatibilityMessage && onCheckProviderCompatibility && (
            <button
              className="button button--secondary button--compact"
              disabled={compatibilityLoading || providerCheckPending}
              onClick={() => {
                void checkProviderCompatibility(onCheckProviderCompatibility);
              }}
              title="Check the installed provider schema before local analysis"
              type="button"
            >
              {compatibilityLoading || providerCheckPending
                ? "Checking provider…"
                : "Check provider"}
            </button>
          )}
          {onAnalyzeLocally && (
            <div className="quality-profile__analysis-action">
              <button
                aria-describedby={analysisDisabled ? analysisCapabilityId : undefined}
                className="button button--primary button--compact"
                disabled={analysisDisabled}
                onClick={() => {
                  const currentHandler = onAnalyzeLocally;
                  setAnalysisContext({
                    handler: currentHandler,
                    onCheckCompatibility: onCheckProviderCompatibility,
                    ownerIdentity,
                    sessionDescriptor,
                  });
                }}
                title={analysisBlocker ?? undefined}
                type="button"
              >
                Analyze locally
              </button>
              {analysisBlocker && (
                <span id={analysisCapabilityId} role="status">
                  {analysisBlocker}
                </span>
              )}
              {providerCheckState.failed && (
                <span className="quality-profile__action-error" role="alert">
                  The content-free provider check could not be completed. No session content was read.
                </span>
              )}
            </div>
          )}
          <button
            className="button button--secondary button--compact"
            disabled={shareBlocked}
            onClick={() => setShareOpen(true)}
            title={shareBlocked ? shareBlockedTitle : undefined}
            type="button"
          >
            Share profile
          </button>
        </div>
      </header>
      <div className="quality-profile__snapshot-line">
        <span>{snapshotKind === "initial" ? profile.initialLabel : profile.latestLabel}</span>
        <span>{summary(snapshot.metrics)}</span>
        {snapshot.scope && (
          <span>
            {snapshot.scope.completedRuns} of {snapshot.scope.selectedSessions} selected
            sessions have a compatible Coaching v1 run
            {snapshot.scope.missingRuns > 0
              ? ` · ${snapshot.scope.missingRuns} need analysis`
              : ""}
          </span>
        )}
        {snapshot.integrity === "coherent" && (
          <span className="quality-profile__snapshot-provenance">
            Coherent metric pack{snapshot.metricPackVersion ? ` v${snapshot.metricPackVersion}` : ""}
          </span>
        )}
        {stalePack && (
          <span className="quality-profile__snapshot-refresh">
            Re-analysis required · stored pack v{snapshot.metricPackVersion}
          </span>
        )}
        {integrityBlocked && (
          <span className="quality-profile__snapshot-alert">
            {snapshot.integrity === "mixed-provenance"
              ? "Mixed provenance blocked"
              : "Invalid metric contract"}
          </span>
        )}
        {snapshotKind === "latest" && metricReadinessLoading && !metricReadinessError && (
          <span>Checking content-free metric readiness</span>
        )}
        {snapshotKind === "latest" && metricReadinessError && (
          <span className="quality-profile__snapshot-alert">
            Content-free metric readiness could not be loaded. Stored metric values are unchanged.
            {onRetryMetricReadiness && (
              <button
                className="button button--secondary button--compact"
                onClick={onRetryMetricReadiness}
                type="button"
              >
                Retry readiness
              </button>
            )}
          </span>
        )}
        {snapshotKind === "latest" && readinessStale && (
          <span className="quality-profile__snapshot-alert" role="status">
            Readiness metadata was withheld because its complete exact session, preset, metric-pack, analysis-profile, and current-provider ownership could not be verified. Stored metric values remain authoritative.
          </span>
        )}
        {snapshotKind === "latest" && readinessOwned && !metricReadinessLoading && (
          <span className="quality-profile__readiness-owner">
            Readiness verified for this exact session and metric pack · {ownedReadiness?.metrics.length ?? 0} metric records
          </span>
        )}
      </div>
      <details className="quality-profile__radar-panel" open>
        <summary>
          <span className="quality-profile__radar-summary-copy">
            <span className="quality-profile__radar-kicker">Visual overview</span>
            <strong>{profile.kind === "prompt" ? "Prompt-quality radar" : "Logic & decisions radar"}</strong>
            <small>Exact values first · measured higher-is-better axes only · fixed 0–100%</small>
          </span>
          <span aria-hidden="true" className="quality-profile__radar-toggle">
            <span className="quality-profile__radar-toggle--open">Hide radar</span>
            <span className="quality-profile__radar-toggle--closed">Show radar</span>
          </span>
        </summary>
        <div className="quality-profile__radar-content">
          <QualityRadar
            contextIdentity={JSON.stringify({
              owner: profileOwnerIdentity(profile, onAnalyzeLocally?.exactSessionId),
              snapshot: snapshotKind,
              readinessSession: ownedReadiness?.session_id ?? null,
              readinessRuns: ownedReadiness?.metrics.map((metric) => metric.latest_run_id) ?? [],
            })}
            metrics={snapshot.metrics}
            readiness={snapshotKind === "latest" ? ownedReadiness?.metrics : null}
          />
        </div>
      </details>
      {primaryContent !== undefined && (
        <div className="quality-profile__layout">
          <div className="quality-profile__visual">{primaryContent}</div>
        </div>
      )}
      <MetricOpportunityMap />
      <details className="quality-profile__method-boundary">
        <summary>
          <span>
            <strong>Methods &amp; details</strong>
            <small>Receipts, denominators, limitations, provenance and provider readiness</small>
          </span>
          <span>Optional</span>
        </summary>
        <div className="quality-profile__method-content">
          <div className="quality-profile__method-grid">
            <div>
              <strong>Experimental baseline</strong>
              <span>Deterministic English/Polish candidate rules, not model scores.</span>
            </div>
            <div>
              <strong>Accuracy not established</strong>
              <span>Repeatable arithmetic does not establish that a detected cue is correct. Any accuracy claim requires a representative independent human holdout.</span>
            </div>
            <div>
              <strong>Preview-window scope</strong>
              <span>Up to 100 messages and 100,000 redacted characters around the latest user message.</span>
            </div>
          </div>

          <section aria-labelledby={pipelineTitleId} className="quality-pipeline">
            <header>
              <p className="eyebrow">Active scoring path</p>
              <h3 id={pipelineTitleId}>How these percentages are produced</h3>
            </header>
            <ol>
              <li><strong>Size-limited local read</strong><span>Codex currently returns the selected session before the smaller preview window is selected; oversized responses fail closed.</span></li>
              <li><strong>Bounded preview</strong><span>Up to 100 messages and 100,000 redacted characters around the latest user message.</span></li>
              <li><strong>Safe projection</strong><span>User, agent-response, and plan text only; reasoning, commands, paths, and tool output are excluded.</span></li>
              <li><strong>Local preparation</strong><span>Best-effort redaction, English/Polish detection, and clause segmentation.</span></li>
              <li><strong>Candidate rules</strong><span>Versioned lexical and transition rules mark observable cues and candidate links.</span></li>
              <li><strong>Ratio</strong><span>Matched rule-defined items divided by eligible rule-defined items; missing denominators abstain.</span></li>
              <li><strong>Content-free storage</strong><span>Only states, counts, fractions, receipts, and pinned provenance are persisted.</span></li>
            </ol>
            <p>
              <strong>Active coaching model: none.</strong> Qwen3 Embedding 0.6B and BGE Reranker v2 M3 belong to a separate request-to-response linkage experiment and do not change these percentages.
            </p>
          </section>

          <div className="quality-profile__provenance-detail">
            <span>{profile.summary}</span>
            {profile.analysisProfile && <span>{profile.analysisProfile.label}</span>}
          </div>

          <section aria-labelledby={metricDetailsTitleId} className="quality-methods">
            <header>
              <p className="eyebrow">Metric receipts</p>
              <h3 id={metricDetailsTitleId}>How each value was produced</h3>
            </header>
            <div className="quality-methods__grid">
              {snapshot.metrics.map((metric) => (
                <article className="quality-method" key={metric.definition.key}>
                  <header>
                    <div>
                      <strong>{metric.definition.label}</strong>
                      <span>{metric.definition.question}</span>
                    </div>
                    <b>{metric.ratio === null ? "—" : formatPercent(metric.ratio)}</b>
                    <small>{stateLabel(metric)}</small>
                  </header>

                  {metric.signals.length > 0 && (
                    <ul aria-label={`${metric.definition.label} evidence receipt`} className="quality-method__signals">
                      {metric.signals.map((signal) => (
                        <li className={`quality-signal quality-signal--${signal.status}`} key={signal.code}>
                          <span aria-hidden="true">
                            {signal.status === "detected"
                              ? "✓"
                              : signal.status === "missing"
                                ? "○"
                                : signal.status === "unknown"
                                  ? "—"
                                  : "#"}
                          </span>
                          <span>{signalLabel(signal.code)}</span>
                          <strong>{signalValue(signal.status, signal.count)}</strong>
                        </li>
                      ))}
                    </ul>
                  )}

                  {explanationLine(metric) && (
                    <p className="quality-method__explanation" role="note">
                      {explanationLine(metric)}
                    </p>
                  )}
                  <dl>
                    <div><dt>Fraction</dt><dd>{fractionLine(metric)}</dd></div>
                    <div><dt>Window coverage</dt><dd>{coverageLine(metric)}</dd></div>
                    {metric.notSelectedRuns > 0 && (
                      <div>
                        <dt>Scope omissions</dt>
                        <dd>
                          {metric.notSelectedRuns} completed run{metric.notSelectedRuns === 1 ? "" : "s"} did not select this metric. Those runs are excluded—not missing or failed.
                        </dd>
                      </div>
                    )}
                    {metric.unknownScopeRuns > 0 && (
                      <div>
                        <dt>Legacy scope unknown</dt>
                        <dd>
                          {metric.unknownScopeRuns} completed legacy run{metric.unknownScopeRuns === 1 ? " does" : "s do"} not preserve the selected metric set. Absence remains unknown—not missing or failed.
                        </dd>
                      </div>
                    )}
                    <div><dt>Denominator</dt><dd>{denominatorSource(metric)}</dd></div>
                    <div><dt>Extractor</dt><dd>{metric.modelId === null ? "Deterministic EN/PL rules · no model" : "Model-assisted result with pinned provenance"}</dd></div>
                    <div><dt>Method</dt><dd>{metric.definition.method}</dd></div>
                    <div><dt>Limit</dt><dd>{metric.definition.limitation}</dd></div>
                  </dl>
                </article>
              ))}
            </div>
          </section>

          {onAnalyzeLocally && (
            <ProviderCompatibilityCard
              loading={compatibilityLoading}
              onCheck={onCheckProviderCompatibility}
              onUpdate={onUpdateProvider}
              status={providerCompatibility ?? null}
            />
          )}

        </div>
      </details>
      {allUnavailable && !allLegacyScopeUnknown && (
        <div className="quality-profile__calibration" role="note">
          <strong>
            {stalePack
              ? "This profile was produced by an older immutable metric pack"
              : "No compatible Coaching v1 analysis run is available"}
          </strong>
          <span>
            {stalePack
              ? "The old result remains preserved, but its values are not relabeled as current metrics. Run the one-click local analysis to create a Coaching pack v3 profile."
              : "Older analysis packs remain preserved but are never mixed with this profile. Analyze the selected sessions with Coaching v1 to create comparable versioned receipts; no placeholder values are generated."}
          </span>
        </div>
      )}
      {allLegacyScopeUnknown && (
        <div className="quality-profile__calibration" role="note">
          <strong>A compatible legacy run exists, but its selected metric scope was not recorded</strong>
          <span>
            Missing result rows cannot be classified as selected, omitted, or failed. Run a new exact-scope local analysis to establish that provenance boundary.
          </span>
        </div>
      )}
      {allNotSelected && (
        <div className="quality-profile__calibration" role="note">
          <strong>No metric in this view was selected for the completed run</strong>
          <span>
            The run is valid, but its exact metric scope omitted this view. Select the metrics you want and start a new local analysis; omissions are never relabeled as missing, failed, or zero.
          </span>
        </div>
      )}
      {integrityBlocked && (
        <div className="quality-profile__integrity-error" role="alert">
          <strong>Profile comparison and sharing are blocked</strong>
          <span>
            {snapshot.integrity === "mixed-provenance"
              ? "Incompatible metrics are withheld from the radar and sharing. Compatible per-metric values remain visible with their own receipts, but no cross-metric comparison is implied."
              : "Stored rows do not form a valid metric-pack snapshot. No axis values are presented until the contract is repaired."}
          </span>
        </div>
      )}
      <footer className="quality-profile__boundary">
        These are observable text signals—not a developer ranking, cognitive-skill measurement, hidden chain-of-thought inference, or overall score.
      </footer>
      {shareOpen && (
        <ProfileShareDialog
          onClose={() => setShareOpen(false)}
          profile={profile}
          snapshotKind={snapshotKind}
        />
      )}
      {analysisContext?.ownerIdentity === ownerIdentity && (
        <AnalyzeLocallyDialog
          exactSessionId={analysisContext.handler.exactSessionId}
          onApprovePreview={analysisContext.handler.approvePreview}
          onCheckCompatibility={analysisContext.onCheckCompatibility}
          onClose={() => setAnalysisContext(null)}
          onPreparePreview={analysisContext.handler.preparePreview}
          sessionDescriptor={analysisContext.sessionDescriptor}
        />
      )}
    </section>
  );
}
