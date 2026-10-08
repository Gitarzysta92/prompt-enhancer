import { describe, expect, it } from "vitest";
import { MetricDefinitionsOutOfDateError } from "./metricPublicationV2Contract";
import {
  ModelEnsemblePayloadError,
  parseModelRequirementVerificationEvidenceBinding,
} from "./modelEnsembleContract";

const GLOBAL_IDENTITY = {
  opportunity_issuer_version: "reviewed-r6-requirement-opportunity-issuer-v1",
  result_issuer_version: "local-objective-verification-result-issuer-v1",
  acceptance_issuer_version: "native-explicit-requirement-acceptance-issuer-v1",
  evidence_schema_version: "requirement-verification-evidence-v1",
  evidence_policy_version: "app-issued-reviewed-requirement-verification-v1",
  persistence_schema_version: "requirement-verification-persistence-v1",
  evidence_projection_version: "reviewed-requirement-verification-objective-projection-v1",
  objective_projection_version: "reviewed-requirement-verification-objective-projection-v1",
  binding_schema_version: "session-requirement-verification-evidence-binding-v1",
  binding_fingerprint: "f".repeat(64),
  local_only: true,
  content_persisted: false,
} as const;

const NULL_PLAN = {
  requirement_plan_confirmation_id: null,
  requirement_plan_proposal_id: null,
  requirement_plan_evidence_fingerprint: null,
  requirement_plan_schema_version: null,
  requirement_plan_policy_version: null,
  requirement_plan_review_rubric_version: null,
} as const;

const REVIEWED_PLAN = {
  requirement_plan_confirmation_id: "1".repeat(64),
  requirement_plan_proposal_id: "2".repeat(64),
  requirement_plan_evidence_fingerprint: "3".repeat(64),
  requirement_plan_schema_version: "requirement-plan-evidence-v1",
  requirement_plan_policy_version: "reviewed-requirement-plan-v1",
  requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1",
} as const;

const NULL_EVIDENCE = {
  evidence_set_fingerprint: null,
  through_revision: null,
  authority_head_count: null,
  objective_result_count: null,
  native_acceptance_count: null,
  resolved_opportunity_count: null,
  met_requirement_count: null,
} as const;

function unavailable() {
  return {
    evidence_source: "unavailable",
    ...NULL_PLAN,
    opportunity_count: null,
    opportunity_set_fingerprint: null,
    ...NULL_EVIDENCE,
    ...GLOBAL_IDENTITY,
  };
}

function bounded() {
  return {
    evidence_source: "opportunity_bound_exceeded",
    ...REVIEWED_PLAN,
    opportunity_count: 101,
    opportunity_set_fingerprint: "4".repeat(64),
    ...NULL_EVIDENCE,
    ...GLOBAL_IDENTITY,
  };
}

function awaiting() {
  return {
    evidence_source: "awaiting_evidence",
    ...REVIEWED_PLAN,
    opportunity_count: 2,
    opportunity_set_fingerprint: "4".repeat(64),
    evidence_set_fingerprint: null,
    through_revision: null,
    authority_head_count: 0,
    objective_result_count: 0,
    native_acceptance_count: 0,
    resolved_opportunity_count: 0,
    met_requirement_count: 0,
    ...GLOBAL_IDENTITY,
  };
}

function persisted() {
  return {
    evidence_source: "persisted_evidence",
    ...REVIEWED_PLAN,
    opportunity_count: 2,
    opportunity_set_fingerprint: "4".repeat(64),
    evidence_set_fingerprint: "5".repeat(64),
    through_revision: 3,
    authority_head_count: 2,
    objective_result_count: 1,
    native_acceptance_count: 1,
    resolved_opportunity_count: 1,
    met_requirement_count: 1,
    ...GLOBAL_IDENTITY,
  };
}

describe("selected r8 public requirement-verification binding", () => {
  it("accepts every exact content-free source shape", () => {
    for (const candidate of [unavailable(), bounded(), awaiting(), persisted()]) {
      expect(parseModelRequirementVerificationEvidenceBinding(candidate)).toEqual(candidate);
    }
  });

  it("rejects partial authority, count drift, private identity, and extra fields", () => {
    for (const candidate of [
      { ...unavailable(), requirement_plan_confirmation_id: "1".repeat(64) },
      { ...bounded(), opportunity_count: 100 },
      { ...awaiting(), evidence_set_fingerprint: "5".repeat(64) },
      { ...awaiting(), authority_head_count: null },
      { ...persisted(), authority_head_count: 1 },
      { ...persisted(), resolved_opportunity_count: 3 },
      { ...persisted(), binding_fingerprint: "not-a-pseudonym" },
      { ...persisted(), session_id: "6".repeat(64) },
      { ...persisted(), bound_at: "2026-01-01T00:00:00Z" },
    ]) {
      expect(() => parseModelRequirementVerificationEvidenceBinding(candidate))
        .toThrow(ModelEnsemblePayloadError);
    }
  });

  it("classifies a future source or version as definitions out of date", () => {
    expect(() => parseModelRequirementVerificationEvidenceBinding({
      ...unavailable(), evidence_source: "future_evidence",
    })).toThrow(MetricDefinitionsOutOfDateError);
    expect(() => parseModelRequirementVerificationEvidenceBinding({
      ...unavailable(), binding_schema_version: "session-requirement-verification-evidence-binding-v2",
    })).toThrow(MetricDefinitionsOutOfDateError);
  });
});
