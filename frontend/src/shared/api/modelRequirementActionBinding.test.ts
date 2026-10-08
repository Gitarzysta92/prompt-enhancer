import { describe, expect, it } from "vitest";
import { MetricDefinitionsOutOfDateError } from "./metricPublicationV2Contract";
import {
  ModelEnsemblePayloadError,
  parseModelRequirementActionEvidenceBinding,
} from "./modelEnsembleContract";

const UNAVAILABLE = "9059e785839871abf94e1fea1c86c48e737621047a526cd3c9e94099a5b5e07f";
const AWAITING = "0ca65041b98be25e41cbbba908641f116f0e81b45416f89fd7ddf177489add4a";
const OVERFLOW = "528224b052ffbec5c2b404b8970ab2ced61b84bc39cc20d70fd77320a059875f";
const SOURCE_INCOMPLETE = "d44bd4fa494e3123c7cb6f23ada45473204a55736c8a0ae9e5305ba30d91c699";
const BINDING_INVALID = "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da";

function marker(source:
  | "unavailable" | "awaiting_review" | "candidate_manifest_overflow"
  | "candidate_source_incomplete" | "binding_invalid") {
  const markers = {
    unavailable: [UNAVAILABLE, "requirement-action-unavailable-v1"],
    awaiting_review: [AWAITING, "requirement-action-awaiting-review-v1"],
    candidate_manifest_overflow: [OVERFLOW, "requirement-action-candidate-manifest-overflow-v1"],
    candidate_source_incomplete: [SOURCE_INCOMPLETE, "requirement-action-candidate-source-incomplete-v1"],
    binding_invalid: [BINDING_INVALID, "requirement-action-binding-invalid-v1"],
  } as const;
  return {
    evidence_source: source,
    source_run_id: null,
    requirement_plan_confirmation_id: null,
    requirement_plan_evidence_fingerprint: null,
    candidate_manifest_fingerprint: null,
    confirmation_id: null,
    proposal_id: null,
    reviewed_descriptor_set_fingerprint: null,
    evidence_fingerprint: markers[source][0],
    evidence_schema_version: markers[source][1],
    evidence_policy_version: "reviewed-requirement-action-v1",
    local_only: true,
    content_persisted: false,
  };
}

function reviewed() {
  return {
    evidence_source: "reviewed_requirement_action",
    source_run_id: "1".repeat(64),
    requirement_plan_confirmation_id: "2".repeat(64),
    requirement_plan_evidence_fingerprint: "3".repeat(64),
    candidate_manifest_fingerprint: "4".repeat(64),
    confirmation_id: "5".repeat(64),
    proposal_id: "6".repeat(64),
    reviewed_descriptor_set_fingerprint: "8".repeat(64),
    evidence_fingerprint: "7".repeat(64),
    evidence_schema_version: "requirement-action-evidence-v1",
    evidence_policy_version: "reviewed-requirement-action-v1",
    local_only: true,
    content_persisted: false,
  };
}

describe("selected r7 public requirement-action binding", () => {
  it("accepts only exact public markers and complete reviewed authority shapes", () => {
    expect(parseModelRequirementActionEvidenceBinding(marker("unavailable"))).toEqual(marker("unavailable"));
    expect(parseModelRequirementActionEvidenceBinding(marker("awaiting_review"))).toEqual(marker("awaiting_review"));
    expect(parseModelRequirementActionEvidenceBinding(marker("candidate_manifest_overflow")))
      .toEqual(marker("candidate_manifest_overflow"));
    expect(parseModelRequirementActionEvidenceBinding(marker("candidate_source_incomplete")))
      .toEqual(marker("candidate_source_incomplete"));
    expect(parseModelRequirementActionEvidenceBinding(marker("binding_invalid")))
      .toEqual(marker("binding_invalid"));
    expect(parseModelRequirementActionEvidenceBinding(reviewed())).toEqual(reviewed());
  });

  it("rejects partial authority, marker reuse, and extra fields", () => {
    for (const candidate of [
      { ...reviewed(), confirmation_id: null },
      { ...reviewed(), reviewed_descriptor_set_fingerprint: null },
      { ...reviewed(), evidence_fingerprint: UNAVAILABLE },
      { ...reviewed(), evidence_fingerprint: OVERFLOW },
      { ...marker("awaiting_review"), source_run_id: "1".repeat(64) },
      { ...marker("candidate_manifest_overflow"), evidence_fingerprint: SOURCE_INCOMPLETE },
      { ...marker("binding_invalid"), evidence_fingerprint: AWAITING },
      { ...marker("binding_invalid"), reviewed_descriptor_set_fingerprint: "8".repeat(64) },
      { ...marker("unavailable"), unexpected: false },
      { ...reviewed(), candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1" },
      { ...reviewed(), candidate_metadata_fingerprint: "9".repeat(64) },
    ]) {
      expect(() => parseModelRequirementActionEvidenceBinding(candidate)).toThrow(ModelEnsemblePayloadError);
    }
  });

  it("classifies a future source or schema as definitions out of date", () => {
    expect(() => parseModelRequirementActionEvidenceBinding({
      ...marker("unavailable"), evidence_source: "future_review",
    })).toThrow(MetricDefinitionsOutOfDateError);
    expect(() => parseModelRequirementActionEvidenceBinding({
      ...marker("unavailable"), evidence_schema_version: "requirement-action-evidence-v2",
    })).toThrow(MetricDefinitionsOutOfDateError);
  });
});
