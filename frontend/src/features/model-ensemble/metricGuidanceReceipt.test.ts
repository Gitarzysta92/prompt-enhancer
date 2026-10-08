import { describe, expect, it } from "vitest";
import {
  METRIC_V2_CONTRACT_IDENTITIES,
  METRIC_V2_KEYS,
  MetricDefinitionsOutOfDateError,
  MetricPublicationV2PayloadError,
  metricDefinitionCompatibility,
  parseMetricPublicationV2,
} from "../../shared/api/metricPublicationV2Contract";
import {
  syntheticMetricPublicationV2,
  syntheticPublishedMetricV2,
  type MetricScenarioV2,
} from "../../test/metricPublicationV2Fixture";
import { QUALITY_ANALYSIS_DEFINITIONS } from "../quality-profile/qualityProfile";
import {
  METRIC_GUIDANCE_STATE_CLASSES,
  exactPercent,
  metricGuidanceFocusFactors,
  metricGuidanceReceiptSentences,
  metricGuidanceTemplateIds,
  metricGuidanceTemplateText,
  type MetricGuidanceStateClass,
} from "./metricGuidanceReceipt";
import { metricDefinitionsOutOfDateCopy } from "./MetricDefinitionsAlert";

const DIRECTIONS = new Map(QUALITY_ANALYSIS_DEFINITIONS.map((definition) => [definition.key, definition.direction]));
const LABELS = new Map(QUALITY_ANALYSIS_DEFINITIONS.map((definition) => [definition.key, definition.label]));

function scenarioFor(stateClass: MetricGuidanceStateClass, objective: boolean): MetricScenarioV2 | null {
  switch (stateClass) {
    case "known_retain": return { value_state: "known", numerator: 3, denominator: 4, state_class: "known_retain" };
    case "known_improve": return { value_state: "known", numerator: 1, denominator: 4, state_class: "known_improve" };
    case "pending_closure": return { value_state: "pending", eligible: 4, pending: 2, numerator: 1 };
    case "objective_evidence_missing": return objective ? { value_state: "unknown", eligible: 0, capability_available: false } : null;
    case "objective_evidence_unresolved": return objective ? { value_state: "unknown", eligible: 2, unknown: 1, capability_available: true } : null;
    case "evidence_unresolved": return objective ? null : { value_state: "unknown" };
    case "no_opportunity": return { value_state: "not_applicable" };
    case "evidence_coverage_abstained": return { value_state: "abstained" };
    case "analysis_failed": return { value_state: "execution_error" };
    default: return null;
  }
}

function sentencesFor(
  metricKey: typeof METRIC_V2_KEYS[number],
  scenario: MetricScenarioV2,
  projectionVersion: Parameters<typeof metricGuidanceReceiptSentences>[0]["projectionVersion"] = "metric-contract-v2-projection-1",
) {
  const published = syntheticPublishedMetricV2(metricKey, scenario);
  return metricGuidanceReceiptSentences({
    metricKey,
    label: LABELS.get(metricKey) ?? metricKey,
    direction: DIRECTIONS.get(metricKey) ?? "higher_is_better",
    projectionVersion,
    guidance: published.guidance as never,
    evidenceAuthority: published.state.evidence_authority,
    explanationCode: published.state.explanation_code,
    capabilityAvailable: published.state.statistics.capability_available,
  });
}

/** Two sentences: each ends with one terminal period and contains no other sentence boundary. */
function expectExactlyTwoSentences(meaning: string, action: string) {
  for (const sentence of [meaning, action]) {
    expect(sentence.trim().endsWith(".")).toBe(true);
    // A sentence boundary is ". " followed by a capital letter or a quote; ratios such as "0.5" or "v1." never qualify.
    expect(sentence.slice(0, -1)).not.toMatch(/[.!?]\s+[A-Z“"]/u);
  }
}

describe("metric guidance template catalog", () => {
  it("resolves every published template identity for all twenty keys and all nine state classes", () => {
    for (const metricKey of METRIC_V2_KEYS) {
      for (const stateClass of METRIC_GUIDANCE_STATE_CLASSES) {
        const ids = metricGuidanceTemplateIds(metricKey, stateClass);
        expect(metricGuidanceTemplateText(ids.diagnosis), `${metricKey} ${stateClass} diagnosis`).toBeTruthy();
        expect(metricGuidanceTemplateText(ids.action), `${metricKey} ${stateClass} action`).toBeTruthy();
        expect(metricGuidanceTemplateText(ids.verification), `${metricKey} ${stateClass} verification`).toBeTruthy();
      }
    }
  });

  it("refuses template identities from another catalog version or an unknown metric key", () => {
    expect(metricGuidanceTemplateText("diagnosis.prompt.task_definition_coverage.v2")).toBeNull();
    expect(metricGuidanceTemplateText("diagnosis.prompt.not_a_metric.v1")).toBeNull();
    expect(metricGuidanceTemplateText("action.unknown_family.v1")).toBeNull();
    expect(metricGuidanceTemplateText("prose sentence")).toBeNull();
  });

  it("formats exact bounds without rounding away a tenth", () => {
    expect(exactPercent(0.25)).toBe("25%");
    expect(exactPercent(1 / 3)).toBe("33.3%");
    expect(exactPercent(0)).toBe("0%");
    expect(exactPercent(1)).toBe("100%");
  });
});

describe("metric guidance receipt sentences", () => {
  it("renders exactly two deterministic sentences for every key and every state class the key can publish", () => {
    let rendered = 0;
    for (const metricKey of METRIC_V2_KEYS) {
      const objective = METRIC_V2_CONTRACT_IDENTITIES[metricKey].authority === "objective_receipt";
      for (const stateClass of METRIC_GUIDANCE_STATE_CLASSES) {
        const scenario = scenarioFor(stateClass, objective);
        if (scenario === null) continue;
        const first = sentencesFor(metricKey, scenario);
        const second = sentencesFor(metricKey, scenario);
        expect(second, `${metricKey} ${stateClass} deterministic`).toEqual(first);
        expectExactlyTwoSentences(first.meaning, first.action);
        expect(first.action, `${metricKey} ${stateClass} verify clause`).toMatch(/ — verify: /u);
        expect(first.meaning, `${metricKey} ${stateClass} no template placeholder`).not.toMatch(/no reviewed wording/u);
        expect(first.action, `${metricKey} ${stateClass} no template placeholder`).not.toMatch(/no reviewed/u);
        rendered += 1;
      }
    }
    // 15 conversation keys × 7 classes + 5 objective keys × 8 classes.
    expect(rendered).toBe(15 * 7 + 5 * 8);
  });

  it("retains a known_retain receipt at the floor even when not every factor was met, without re-deciding from the value", () => {
    const retain = sentencesFor("prompt.task_definition_coverage", { value_state: "known", numerator: 3, denominator: 4, state_class: "known_retain" });
    expect(retain.kind).toBe("measured");
    expect(retain.meaning).toMatch(/^Measured: 3\/4 .+ classes it as retain even though 1 .+ did not meet it/u);
    expect(retain.action).toMatch(/^Retain: keep the practice/u);
    expect(retain.action).not.toMatch(/Focus on|State the action/u);
    // The client renders the producer's class as published: a lower value classed retain still retains …
    const producerRetain = sentencesFor("prompt.task_definition_coverage", { value_state: "known", numerator: 1, denominator: 4, state_class: "known_retain" });
    expect(producerRetain.action).toMatch(/^Retain:/u);
    // … and a fully met value classed improve still renders the improve template.
    const producerImprove = sentencesFor("prompt.task_definition_coverage", { value_state: "known", numerator: 4, denominator: 4, state_class: "known_improve" });
    expect(producerImprove.action).not.toMatch(/^Retain:/u);
    expect(producerImprove.meaning).toMatch(/classes it as improve/u);
  });

  it("orients lower-is-better values as radar quality inside the same sentence family", () => {
    const rework = sentencesFor("collaboration.rework_candidate_rate", { value_state: "known", numerator: 1, denominator: 4, state_class: "known_retain" });
    expect(rework.meaning).toMatch(/a raw rate of 25%, radar quality 75% because lower is better/u);
    expect(rework.action).toMatch(/^Retain:/u);
  });

  it("names focus factors only from measured per-factor statistics and never more than two", () => {
    const perFactor = sentencesFor("prompt.context_sufficiency", {
      value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve",
      factor_evidence: "per_factor_measured", focus_factor_keys: ["current_state", "boundary"],
    });
    expect(perFactor.action).toMatch(/^Focus on current state and boundary \(measured per-factor statistics\): /u);
    expect(perFactor.basis).toBe("measured");
    const aggregate = sentencesFor("prompt.context_sufficiency", {
      value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve", factor_evidence: "aggregate_only",
    });
    expect(aggregate.action).not.toMatch(/Focus on/u);
    expect(aggregate.basis).toBe("method-only");
    expect(aggregate.meaning).toMatch(/aggregate-only factor evidence, so no individual factor is named/u);
    const notObserved = sentencesFor("prompt.context_sufficiency", { value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve" });
    expect(notObserved.action).not.toMatch(/Focus on/u);
    expect(metricGuidanceFocusFactors({ factor_evidence: "aggregate_only", focus_factor_keys: ["a"] })).toEqual([]);
    expect(metricGuidanceFocusFactors({ factor_evidence: "per_factor_measured", focus_factor_keys: ["a", "b", "c"] })).toEqual(["a", "b"]);
  });

  it("exposes exact censoring bounds for a pending receipt and never a zero", () => {
    const pending = sentencesFor("collaboration.ambiguity_resolution", { value_state: "pending", eligible: 4, pending: 2, numerator: 1 });
    expect(pending.kind).toBe("pending");
    expect(pending.state).toBe("pending");
    expect(pending.meaning).toMatch(/^Pending: 2 of 4 .+ are still open .+ lower bound of 25% and an upper bound of 75%/u);
    expect(pending.meaning).toMatch(/not a measurement and not a zero/u);
    expect(pending.action).toMatch(/^Nothing to change yet: the open opportunity must close .+ — verify: re-measure after the episode horizon closes/u);
    const thirds = sentencesFor("collaboration.ambiguity_resolution", { value_state: "pending", eligible: 3, pending: 1, numerator: 1 });
    expect(thirds.meaning).toMatch(/lower bound of 33\.3% and an upper bound of 66\.7%/u);
    const unpublished = sentencesFor("collaboration.ambiguity_resolution", {
      value_state: "pending", eligible: 4, pending: 2, numerator: 1, censoring_lower_bound: null, censoring_upper_bound: null,
    });
    expect(unpublished.meaning).toMatch(/published no censoring bounds/u);
  });

  it("states that a missing objective capability cannot be fixed by wording and is verified by adapter readiness", () => {
    for (const metricKey of METRIC_V2_KEYS.filter((key) => METRIC_V2_CONTRACT_IDENTITIES[key].authority === "objective_receipt")) {
      const missing = sentencesFor(metricKey, { value_state: "unknown", eligible: 0, capability_available: false });
      expect(missing.kind, metricKey).toBe("unavailable");
      expect(missing.meaning, metricKey).toMatch(/^Adapter capability missing: the current adapter cannot measure .+ no user wording or agent action can fix that/u);
      expect(missing.meaning, metricKey).toMatch(/missing capability, not a low value/u);
      expect(missing.action, metricKey).toMatch(/^No user wording or agent action can supply this value: when a supported structured-evidence adapter is available/u);
      expect(missing.action, metricKey).toMatch(/use its confirmation workflow to emit typed tool, test, artifact, or acceptance receipts; until then keep the metric unknown/u);
      expect(missing.action, metricKey).toMatch(/verify: adapter readiness — a supported adapter produces a fresh sealed receipt/u);
      expect(missing.action, metricKey).toMatch(/collecting more prose is not verification/u);
      expect(missing.audience, metricKey).toBe("tooling");
    }
  });

  it("keeps unresolved objective evidence distinct from missing capability", () => {
    const unresolved = sentencesFor("outcome.verified_requirement_coverage", { value_state: "unknown", eligible: 2, unknown: 1, capability_available: true });
    expect(unresolved.meaning).toMatch(/^Objective evidence unresolved: a typed receipt exists .+ leaves 1 of 2 .+ unresolved/u);
    expect(unresolved.action).toMatch(/^Resolve the opportunities the existing typed receipt leaves open/u);
  });

  it("renders exact r8 unknown bounds without mislabeling native acceptance authority", () => {
    const unavailable = sentencesFor(
      "outcome.verified_requirement_coverage",
      {
        value_state: "unknown", eligible: 2, unknown: 2,
        capability_available: true, source_complete: true,
        censoring_lower_bound: 0, censoring_upper_bound: 1,
        explanation_code: "requirement_verification_evidence_unavailable",
      },
      "metric-contract-v2-projection-8",
    );
    expect(unavailable.meaning).toMatch(/reviewed denominator contains 2/i);
    expect(unavailable.meaning).toMatch(/exact right-censored interval is 0%–100%/i);
    expect(unavailable.meaning).toMatch(/app-issued verification results or separately typed native human acceptances/i);
    expect(unavailable.meaning).toMatch(/assistant completion claims never count/i);
    expect(unavailable.action).not.toMatch(/existing typed receipt leaves open/i);

    const published = syntheticPublishedMetricV2(
      "outcome.verified_requirement_coverage",
      {
        value_state: "unknown", eligible: 4, unknown: 2,
        capability_available: true, source_complete: true,
        censoring_lower_bound: 0.25, censoring_upper_bound: 0.75,
        explanation_code: "app_issued_requirement_verification_pending",
      },
    );
    published.guidance.met_count = 1;
    published.guidance.not_met_count = 1;
    const partial = metricGuidanceReceiptSentences({
      metricKey: "outcome.verified_requirement_coverage",
      label: "Verified requirement coverage",
      direction: "higher_is_better",
      projectionVersion: "metric-contract-v2-projection-8",
      guidance: published.guidance as never,
      evidenceAuthority: published.state.evidence_authority,
      explanationCode: "app_issued_requirement_verification_pending",
      capabilityAvailable: true,
    });
    expect(partial.meaning).toMatch(/resolves 2 of 4/i);
    expect(partial.meaning).toMatch(/exact right-censored interval is 25%–75%/i);
    expect(partial.meaning).not.toMatch(/a typed receipt exists/i);
    expect(partial.action).toMatch(/fresh sealed r8 receipt reaches zero unresolved/i);
  });

  it("keeps an available adapter with absent objective evidence distinct from an adapter capability gap", () => {
    const missingEvidence = sentencesFor("logic.requirement_action_traceability", {
      value_state: "unknown", eligible: 0, capability_available: true,
    });
    expect(missingEvidence.kind).toBe("unknown");
    expect(missingEvidence.meaning).toMatch(/^Objective evidence missing: the adapter exposes the required evidence family/u);
    expect(missingEvidence.meaning).toMatch(/no authoritative opportunity set or typed receipt/u);
    expect(missingEvidence.action).toBe(
      `${metricGuidanceTemplateText("action.collect_objective_receipt.v1")} — verify: adapter readiness — a supported adapter produces a fresh sealed receipt scoped to this metric; collecting more prose is not verification.`,
    );
  });

  it("maps every non-value state class to an unplotted inspector state", () => {
    const table: Array<[MetricScenarioV2, string, RegExp]> = [
      [{ value_state: "not_applicable" }, "not_applicable", /^Not applicable: no eligible/u],
      [{ value_state: "abstained" }, "abstained", /^Needs evidence: the local contract abstained/u],
      [{ value_state: "execution_error" }, "execution_error", /^Error: the local analysis stage .+ failed/u],
      [{ value_state: "unknown" }, "unknown", /^Unknown: the contract could not establish/u],
    ];
    for (const [scenario, state, pattern] of table) {
      const sentences = sentencesFor("logic.decomposition_coverage", scenario);
      expect(sentences.state, state).toBe(state);
      expect(sentences.meaning, state).toMatch(pattern);
    }
  });
});

describe("canonical V2 wire parser guidance rules", () => {
  it("accepts up to two focus factors only with measured per-factor statistics", () => {
    const perFactor = syntheticMetricPublicationV2({
      "prompt.context_sufficiency": {
        value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve",
        factor_evidence: "per_factor_measured", focus_factor_keys: ["current_state", "boundary"],
      },
    });
    expect(parseMetricPublicationV2(structuredClone(perFactor))).toEqual(perFactor);
    const aggregate = syntheticMetricPublicationV2({
      "prompt.context_sufficiency": { value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve", factor_evidence: "aggregate_only" },
    });
    expect(parseMetricPublicationV2(structuredClone(aggregate))).toEqual(aggregate);
    const tamper = (mutate: (guidance: Record<string, unknown>) => void) => {
      const fixture = structuredClone(perFactor) as unknown as { metrics: Array<{ guidance: Record<string, unknown> }> };
      mutate(fixture.metrics[2].guidance);
      return fixture;
    };
    expect(() => parseMetricPublicationV2(tamper((guidance) => { guidance.focus_factor_keys = ["a", "b", "c"]; }))).toThrow(MetricPublicationV2PayloadError);
    expect(() => parseMetricPublicationV2(tamper((guidance) => { guidance.factor_evidence = "aggregate_only"; }))).toThrow(MetricPublicationV2PayloadError);
    expect(() => parseMetricPublicationV2(tamper((guidance) => { guidance.factor_evidence = "not_observed"; }))).toThrow(MetricPublicationV2PayloadError);
    expect(() => parseMetricPublicationV2(tamper((guidance) => { guidance.focus_factor_keys = ["a", "a"]; }))).toThrow(MetricPublicationV2PayloadError);
    expect(() => parseMetricPublicationV2(tamper((guidance) => { guidance.contract_factor_count = 1; }))).toThrow(MetricPublicationV2PayloadError);
    // Aggregate-only evidence cannot claim a measured basis.
    const aggregateMeasured = structuredClone(aggregate) as unknown as { metrics: Array<{ guidance: Record<string, unknown> }> };
    aggregateMeasured.metrics[2].guidance.basis = "measured";
    expect(() => parseMetricPublicationV2(aggregateMeasured)).toThrow(MetricPublicationV2PayloadError);
    // A non-known state never carries factor evidence.
    const pendingFactors = structuredClone(syntheticMetricPublicationV2({ "prompt.context_sufficiency": { value_state: "pending" } })) as unknown as { metrics: Array<{ guidance: Record<string, unknown> }> };
    pendingFactors.metrics[2].guidance.factor_evidence = "per_factor_measured";
    expect(() => parseMetricPublicationV2(pendingFactors)).toThrow(MetricPublicationV2PayloadError);
  });

  it("keeps the producer's known state class as published instead of re-deciding it from the value", () => {
    const publication = syntheticMetricPublicationV2({
      "prompt.task_definition_coverage": { value_state: "known", numerator: 3, denominator: 4, state_class: "known_retain" },
      "prompt.problem_evidence_quality": { value_state: "known", numerator: 4, denominator: 4, state_class: "known_improve" },
    });
    const parsed = parseMetricPublicationV2(structuredClone(publication));
    expect(parsed.metrics[0].guidance.state_class).toBe("known_retain");
    expect(parsed.metrics[1].guidance.state_class).toBe("known_improve");
  });

  it("publishes the objective measured count of five and rejects a wrong count", () => {
    const publication = syntheticMetricPublicationV2({
      "outcome.first_pass_verification": { value_state: "known", numerator: 1, denominator: 1, state_class: "known_retain" },
      "outcome.verified_requirement_coverage": { value_state: "known", numerator: 2, denominator: 3, state_class: "known_improve" },
    });
    expect(publication.objective_measured_count).toBe(2);
    expect(parseMetricPublicationV2(structuredClone(publication)).objective_measured_count).toBe(2);
    const wrong = structuredClone(publication) as unknown as Record<string, unknown>;
    wrong.objective_measured_count = 3;
    expect(() => parseMetricPublicationV2(wrong)).toThrow(MetricPublicationV2PayloadError);
  });
});

describe("metric definitions compatibility gate", () => {
  it("is pure, needs no fetch, and binds to the exact registry version and contract-set fingerprint", () => {
    const publication = syntheticMetricPublicationV2();
    expect(metricDefinitionCompatibility(publication)).toMatchObject({ state: "compatible", registryVersion: "all-20-factor-contracts-v2" });
    expect(metricDefinitionCompatibility({ registry_version: "all-20-factor-contracts-v3" })).toEqual({ state: "definitions_out_of_date", mismatch: "registry_version" });
    expect(metricDefinitionCompatibility({ contract_set_fingerprint: "0".repeat(64) })).toEqual({ state: "definitions_out_of_date", mismatch: "contract_set_fingerprint" });
    expect(metricDefinitionCompatibility({ guidance_template_catalog_version: "metric-guidance-templates-v2" })).toEqual({ state: "definitions_out_of_date", mismatch: "guidance_template_catalog_version" });
    expect(metricDefinitionCompatibility({
      metric_contract_fingerprints: [{ metric_key: "prompt.task_definition_coverage", contract_fingerprint: "1".repeat(64) }],
    })).toEqual({ state: "definitions_out_of_date", mismatch: "metric_contract_fingerprint" });
  });

  it("makes the parser throw the distinct definitions-out-of-date error for identity mismatches only", () => {
    const registry = structuredClone(syntheticMetricPublicationV2()) as unknown as Record<string, unknown>;
    registry.registry_version = "all-20-factor-contracts-v3";
    expect(() => parseMetricPublicationV2(registry)).toThrow(MetricDefinitionsOutOfDateError);
    const fingerprint = structuredClone(syntheticMetricPublicationV2()) as unknown as Record<string, unknown>;
    fingerprint.contract_set_fingerprint = "0".repeat(64);
    let caught: unknown;
    try { parseMetricPublicationV2(fingerprint); } catch (error) { caught = error; }
    expect(caught).toBeInstanceOf(MetricDefinitionsOutOfDateError);
    expect((caught as MetricDefinitionsOutOfDateError).code).toBe("definitions_out_of_date");
    expect((caught as MetricDefinitionsOutOfDateError).mismatch).toBe("contract_set_fingerprint");
    const perMetric = structuredClone(syntheticMetricPublicationV2()) as unknown as { metrics: Array<{ state: Record<string, unknown> }> };
    perMetric.metrics[0].state.contract_fingerprint = "2".repeat(64);
    expect(() => parseMetricPublicationV2(perMetric)).toThrow(MetricDefinitionsOutOfDateError);
    // A shape/semantic problem stays a plain payload error.
    const zeroFilled = structuredClone(syntheticMetricPublicationV2()) as unknown as { metrics: Array<{ state: Record<string, unknown> }> };
    zeroFilled.metrics[0].state.numeric_value = 0;
    let plain: unknown;
    try { parseMetricPublicationV2(zeroFilled); } catch (error) { plain = error; }
    expect(plain).toBeInstanceOf(MetricPublicationV2PayloadError);
    expect(plain).not.toBeInstanceOf(MetricDefinitionsOutOfDateError);
  });

  it("uses update-client wording and never reconnect wording", () => {
    const copy = metricDefinitionsOutOfDateCopy("registry_version");
    expect(copy.title).toMatch(/out of date · update this client/u);
    expect(copy.detail).toMatch(/All twenty values and their guidance are withheld until you update the client/u);
    expect(`${copy.title} ${copy.detail} ${copy.binding}`).not.toMatch(/reconnect/iu);
    expect(copy.binding).toMatch(/all-20-factor-contracts-v2/u);
  });
});
