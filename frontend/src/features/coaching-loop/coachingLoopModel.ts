export type CoachingOutcomeStatus =
  | "verified"
  | "failed"
  | "mixed"
  | "unknown"
  | "abstained"
  | "not-applicable";

export type CoachingBasis =
  | "objective"
  | "human-reviewed"
  | "mixed"
  | "observed-text"
  | "none";

export type CoachingSignalCategory =
  | "task-framing"
  | "acceptance-criteria"
  | "clarification"
  | "scope-control"
  | "verification"
  | "rework"
  | "exploration-to-plan";

export type CoachingAvailability =
  | "available"
  | "unknown"
  | "abstained"
  | "not-applicable";

export type CoachingUnavailableReasonCode =
  | "evidence-missing"
  | "insufficient-coverage"
  | "unsupported-task"
  | "not-observed"
  | "method-abstained"
  | "not-applicable-task";

export interface AvailableCoachingInsight {
  state: "available";
  category: CoachingSignalCategory;
  basis: Exclude<CoachingBasis, "none">;
}

export interface UnavailableCoachingInsight {
  state: "unknown" | "abstained" | "not-applicable";
  category: null;
  reasonCode: CoachingUnavailableReasonCode;
}

export type CoachingInsight =
  | AvailableCoachingInsight
  | UnavailableCoachingInsight;

export interface AvailableCoachingExperiment {
  state: "available";
  category: CoachingSignalCategory;
}

export interface UnavailableCoachingExperiment {
  state: "unknown" | "abstained" | "not-applicable";
  category: null;
  reasonCode: CoachingUnavailableReasonCode;
}

export type CoachingExperiment =
  | AvailableCoachingExperiment
  | UnavailableCoachingExperiment;

export type ImprovedPromptTemplateCode =
  | "acceptance-first"
  | "clarify-first"
  | "context-anchor"
  | "deliverable-contract"
  | "diagnosis-evidence"
  | "exploration-to-plan"
  | "hypothesis-test-loop"
  | "preflight-contract"
  | "requirement-plan-map"
  | "scope-boundary"
  | "task-contract"
  | "verification-first";

export interface AvailableImprovedPrompt {
  state: "available";
  templateCode: ImprovedPromptTemplateCode;
}

export interface UnavailableImprovedPrompt {
  state: "unknown" | "abstained" | "not-applicable";
  reasonCode: CoachingUnavailableReasonCode;
}

export type ImprovedPrompt = AvailableImprovedPrompt | UnavailableImprovedPrompt;

export type ObjectiveEvidenceCode =
  | "automated-checks"
  | "acceptance-checks"
  | "automated-and-acceptance";

export interface ObjectiveOutcome {
  status: "verified" | "failed" | "mixed";
  basis: "objective";
  evidenceCode: ObjectiveEvidenceCode;
}

export interface HumanReviewedOutcome {
  status: "verified" | "failed" | "mixed";
  basis: "human-reviewed";
  evidenceCode: "human-review";
}

export interface UnassessedOutcome {
  status: "unknown" | "abstained" | "not-applicable";
  basis: "none";
  reasonCode: CoachingUnavailableReasonCode;
}

export type CoachingOutcome =
  | ObjectiveOutcome
  | HumanReviewedOutcome
  | UnassessedOutcome;

export interface MeasuredEvidenceCoverage {
  state: "complete" | "partial";
  minimumRatio: number;
  candidateCount: number;
}

export interface UnmeasuredEvidenceCoverage {
  state: "unknown" | "abstained" | "not-applicable";
  reasonCode: CoachingUnavailableReasonCode;
}

export type CoachingEvidenceCoverage =
  | MeasuredEvidenceCoverage
  | UnmeasuredEvidenceCoverage;

export type CoachingEvidenceTier =
  | "objective"
  | "mixed"
  | "text-only"
  | "unknown"
  | "abstained";

export type CoachingTaskType =
  | "implementation"
  | "diagnosis"
  | "planning"
  | "research"
  | "review"
  | "other";

export type CoachingMethodCode =
  | "workflow-comparison-v1"
  | "deterministic-candidates-v1"
  | "human-rubric-v1";

export type CoachingLimitationCode =
  | "single-task-candidate"
  | "partial-evidence"
  | "human-review-required";

export type CoachingProvenanceCode =
  | "synthetic-local-v1"
  | "local-versioned-run"
  | "human-reviewed-run";

export type CoachingSharing =
  | { status: "content-free" }
  | {
      status: "blocked";
      reasonCode: "uncalibrated" | "consent-required" | "incoherent-evidence";
    };

/**
 * This UI boundary accepts closed codes and counts only. It deliberately does
 * not accept prompt-derived prose, identifiers, paths, receipts, or provider
 * content. Copy is rendered from versioned local dictionaries in the view.
 */
export interface CoachingLoopViewModel {
  assessment: {
    calibration: "candidate-unvalidated" | "human-calibrated";
    taskType: CoachingTaskType;
    evidenceTier: CoachingEvidenceTier;
    methodCode: CoachingMethodCode;
  };
  outcome: CoachingOutcome;
  strength: CoachingInsight;
  friction: CoachingInsight;
  nextExperiment: CoachingExperiment;
  improvedPrompt: ImprovedPrompt;
  evidence: CoachingEvidenceCoverage;
  details: {
    limitationCode: CoachingLimitationCode;
    provenanceCode: CoachingProvenanceCode;
  };
  sharing: CoachingSharing;
}

/**
 * This is intentionally a closed, content-free export contract. It excludes
 * prompt templates, evidence receipts, identifiers, provenance, counts, and
 * paths. Derived labels are still sensitive and require an explicit reviewed
 * share action.
 */
export interface CoachingShareSummary {
  schema: "coaching-loop-share.v1";
  outcome: CoachingOutcomeStatus;
  outcomeBasis: CoachingBasis;
  strengthCategory: CoachingSignalCategory | "unavailable";
  frictionCategory: CoachingSignalCategory | "unavailable";
  experimentCategory: CoachingSignalCategory | "unavailable";
  evidenceState: CoachingEvidenceCoverage["state"];
  calibration: "human-calibrated";
  boundary: "observed-workflow-signals-not-person-score";
}

export function createContentFreeShareSummary(
  model: CoachingLoopViewModel,
): CoachingShareSummary | null {
  if (
    model.sharing.status !== "content-free" ||
    model.assessment.calibration !== "human-calibrated"
  ) {
    return null;
  }

  return {
    schema: "coaching-loop-share.v1",
    outcome: model.outcome.status,
    outcomeBasis: model.outcome.basis,
    strengthCategory:
      model.strength.state === "available" ? model.strength.category : "unavailable",
    frictionCategory:
      model.friction.state === "available" ? model.friction.category : "unavailable",
    experimentCategory:
      model.nextExperiment.state === "available"
        ? model.nextExperiment.category
        : "unavailable",
    evidenceState: model.evidence.state,
    calibration: "human-calibrated",
    boundary: "observed-workflow-signals-not-person-score",
  };
}
