import { describe, expect, it } from "vitest";
import { createCoachingLoopViewModel } from "./coachingLoopAdapter";

const source = {
  pack_key: "core.redacted-text.coaching",
  pack_version: 2,
  algorithm_id: "rules.en-pl.coaching",
  algorithm_version: "2",
};

function candidate(
  code: string,
  metricBasis: string,
  coverage = 0.8,
) {
  const friction = code.startsWith("friction.");
  return {
    abstention_code: null,
    algorithm_id: "rules.coaching-loop.summary",
    algorithm_version: "1",
    candidate_policy_version: 2,
    code,
    confidence: null,
    construct_version: 1,
    coverage,
    decision_state: "candidate",
    denominator: 20,
    denominator_kind: "event_count",
    denominator_kind_priority_version: 1,
    evidence_lower_bound: friction ? 0 : 0.84,
    evidence_upper_bound: friction ? 0.16 : 1,
    evidence_basis: ["rule.factor_counts"],
    evidence_kind: "deterministic_candidate",
    evidence_tier: "redacted_content",
    metric_basis: [metricBasis],
    pack_key: "coaching.loop",
    pack_version: 1,
    polarity_successes: friction ? 0 : 20,
    recommendation_policy_version: 1,
    rule_priority_version: 1,
    source_provenance: source,
    task_type: "implementation",
  };
}

function abstained(code: string, reason: string) {
  return {
    abstention_code: reason,
    algorithm_id: "rules.coaching-loop.summary",
    algorithm_version: "1",
    candidate_policy_version: 2,
    code,
    confidence: null,
    construct_version: null,
    coverage: null,
    decision_state: "abstained",
    denominator: null,
    denominator_kind: null,
    denominator_kind_priority_version: 1,
    evidence_lower_bound: null,
    evidence_upper_bound: null,
    evidence_basis: [],
    evidence_kind: null,
    evidence_tier: null,
    metric_basis: [],
    pack_key: "coaching.loop",
    pack_version: 1,
    polarity_successes: null,
    recommendation_policy_version: 1,
    rule_priority_version: 1,
    source_provenance: null,
    task_type: "implementation",
  };
}

function validProjection() {
  const friction = candidate(
    "friction.rework_signal_high",
    "collaboration.rework_candidate_rate.v1",
  );
  return {
    projection_key: "coaching.loop.current",
    projection_version: 1,
    task_context_source: "reviewed_task",
    task_type: "implementation",
    summary: {
      outcome: {
        ...abstained("outcome.unknown", "objective_evidence_missing"),
        evidence_disagreement: false,
        human_acceptance_status: "unknown",
        status: "unknown",
      },
      strength: candidate(
        "strength.testable_acceptance",
        "prompt.acceptance_testability.v1",
        1,
      ),
      friction,
      next_experiment: {
        ...friction,
        code: "experiment.confirm_contract_before_execution",
      },
      prompt_template: {
        ...friction,
        code: "prompt_template.preflight_contract",
        slot_codes: ["goal", "scope", "acceptance", "confirmation"],
        template_version: 1,
      },
    },
  };
}

describe("createCoachingLoopViewModel", () => {
  it("maps only closed content-free receipts into an uncalibrated coaching deck", () => {
    const model = createCoachingLoopViewModel(validProjection());

    expect(model).toMatchObject({
      assessment: {
        calibration: "candidate-unvalidated",
        taskType: "implementation",
        evidenceTier: "text-only",
        methodCode: "deterministic-candidates-v1",
      },
      outcome: {
        status: "unknown",
        basis: "none",
        reasonCode: "evidence-missing",
      },
      strength: { state: "available", category: "acceptance-criteria" },
      friction: { state: "available", category: "rework" },
      nextExperiment: { state: "available", category: "rework" },
      improvedPrompt: { state: "available", templateCode: "preflight-contract" },
      evidence: { state: "partial", minimumRatio: 0.8, candidateCount: 2 },
      sharing: { status: "blocked", reasonCode: "uncalibrated" },
    });
    expect(JSON.stringify(model)).not.toContain("prompt text");
  });

  it("fails closed for omitted provenance, unknown codes, and extra content", () => {
    const missing = validProjection();
    delete (missing.summary.strength as Record<string, unknown>).source_provenance;
    expect(createCoachingLoopViewModel(missing)).toBeNull();

    const unknownCode = validProjection();
    unknownCode.summary.friction.code = "friction.future_metric";
    expect(createCoachingLoopViewModel(unknownCode)).toBeNull();

    const contentCanary = validProjection() as Record<string, unknown>;
    contentCanary.prompt_excerpt = "reserved-example-secret";
    expect(createCoachingLoopViewModel(contentCanary)).toBeNull();
  });

  it("rejects task-context and candidate-basis contradictions", () => {
    const contextMismatch = validProjection();
    contextMismatch.task_context_source = "not_reviewed";
    expect(createCoachingLoopViewModel(contextMismatch)).toBeNull();

    const basisMismatch = validProjection();
    basisMismatch.summary.next_experiment.coverage = 0.5;
    expect(createCoachingLoopViewModel(basisMismatch)).toBeNull();
  });

  it("preserves an unreviewed task as abstained instead of scoring it", () => {
    const projection: Record<string, unknown> = validProjection();
    projection.task_type = "unknown";
    projection.task_context_source = "not_reviewed";
    const unknown = abstained("strength.unknown", "task_type_unknown");
    unknown.task_type = "unknown";
    const friction = { ...unknown, code: "friction.unknown" };
    projection.summary = {
      outcome: {
        ...unknown,
        code: "outcome.unknown",
        abstention_code: "objective_evidence_missing",
        evidence_disagreement: false,
        human_acceptance_status: "unknown",
        status: "unknown",
      },
      strength: unknown,
      friction,
      next_experiment: { ...friction, code: "experiment.unknown" },
      prompt_template: {
        ...friction,
        code: "prompt_template.unknown",
        slot_codes: [],
        template_version: null,
      },
    };

    const model = createCoachingLoopViewModel(projection);
    expect(model).toMatchObject({
      assessment: { taskType: "other", evidenceTier: "abstained" },
      strength: { state: "abstained", reasonCode: "unsupported-task" },
      friction: { state: "abstained", reasonCode: "unsupported-task" },
      nextExperiment: { state: "abstained", reasonCode: "unsupported-task" },
      improvedPrompt: { state: "abstained", reasonCode: "unsupported-task" },
    });
  });
});
