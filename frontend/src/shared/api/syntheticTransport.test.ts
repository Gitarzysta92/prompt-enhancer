import { describe, expect, it } from "vitest";
import type { ReviewCommand } from "./contracts";
import {
  SYNTHETIC_CANDIDATES,
  SYNTHETIC_COACHING_PROJECTION,
  SYNTHETIC_CURRENT_SESSION_QUALITY_RUN,
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_RUN,
  SYNTHETIC_MODEL_LINK_EXPERIMENT,
  SYNTHETIC_METRIC_COVERAGE,
  SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
  SYNTHETIC_SESSION_METRIC_READINESS,
} from "./syntheticFixtures";
import { createSyntheticTransport } from "./syntheticTransport";

describe("synthetic transport vertical slice", () => {
  it("is explicitly tagged as fixture transport and exposes no loopback health check", () => {
    const transport = createSyntheticTransport();

    expect(transport.runtimeKind).toBe("synthetic_fixture");
    expect("getRuntimeHealth" in transport).toBe(false);
  });

  it("keeps loopback control-plane readiness outside the synthetic fixture", async () => {
    const transport = createSyntheticTransport();

    await expect(transport.getControlPlaneReadiness()).rejects.toMatchObject({
      status: 404,
    });
  });

  it("serves an isolated exact all-twenty operability fixture", async () => {
    const transport = createSyntheticTransport();
    const first = await transport.getMetricOperabilityCatalog!();

    expect(first).toMatchObject({
      total_metric_count: 20,
      shipped_path_count: 16,
      task_profile_configuration_gap_count: 0,
      provider_adapter_gap_count: 4,
      experimental_model_path_count: 8,
      model_authoritative_metric_count: 0,
      local_only: true,
      content_persisted: false,
    });
    first.entries.pop();
    await expect(transport.getMetricOperabilityCatalog!()).resolves.toHaveProperty(
      "entries.length",
      20,
    );
  });

  it("pages fixture indexes with the same explicit bounds as the local transport", async () => {
    const transport = createSyntheticTransport();

    const candidates = await transport.listCandidates(
      "all",
      undefined,
      { limit: 1, offset: 1 },
    );

    expect(candidates).toEqual({
      candidates: [SYNTHETIC_CANDIDATES[1]],
      limit: 1,
      offset: 1,
    });
  });

  it("exposes content-free readiness consistent with the immutable coaching run", async () => {
    const transport = createSyntheticTransport();
    const capabilities = await transport.getProviderMetricCapabilities("synthetic");
    const readiness = await transport.getSessionMetricReadiness(
      SYNTHETIC_QUALITY_SESSION_ID,
    );
    const run = await transport.getLatestSessionQualityAnalysis(
      SYNTHETIC_QUALITY_SESSION_ID,
    );
    const sessions = await transport.listCodexSessions();

    expect(capabilities).toEqual(SYNTHETIC_PROVIDER_METRIC_CAPABILITIES);
    expect(readiness).toEqual(SYNTHETIC_SESSION_METRIC_READINESS);
    expect(readiness).toMatchObject({
      session_id: run.run.session_id,
      provider: run.run.provider,
      analysis_profile_key: run.run.analysis_profile_key,
      analysis_profile_version: run.run.analysis_profile_version,
      metric_pack_key: run.run.metric_pack_key,
      metric_pack_version: run.run.metric_pack_version,
    });
    expect(sessions.sessions[0]?.provider).toBe(readiness.provider);
    const resultState = new Map(
      run.results.map((result) => [
        `${result.key}.v${result.version}`,
        result.value_state,
      ]),
    );
    expect(readiness.metrics).toHaveLength(run.results.length);
    for (const metric of readiness.metrics) {
      expect(resultState.get(`${metric.metric_key}.v${metric.metric_version}`)).toBe(
        metric.state,
      );
      expect(metric).toMatchObject({
        reason_code: "measured",
        next_actions: ["none"],
        latest_run_id: run.run.run_id,
      });
    }

    readiness.metrics[0].next_actions = ["retry_analysis"];
    await expect(
      transport.getSessionMetricReadiness(SYNTHETIC_QUALITY_SESSION_ID),
    ).resolves.toEqual(SYNTHETIC_SESSION_METRIC_READINESS);
    await expect(
      transport.getProviderMetricCapabilities("codex"),
    ).rejects.toMatchObject({ status: 404 });
    await expect(
      transport.getSessionMetricReadiness(
        SYNTHETIC_QUALITY_SESSION_ID,
        "standard_engineering_v1",
      ),
    ).rejects.toMatchObject({ status: 404 });
  });

  it("exposes isolated, content-free provider and project coverage fixtures", async () => {
    const transport = createSyntheticTransport();
    const provider = await transport.getMetricCoverage("synthetic");
    const project = await transport.getProjectMetricCoverage(
      SYNTHETIC_QUALITY_PROJECT_ID,
      "synthetic",
    );

    expect(provider).toEqual(SYNTHETIC_METRIC_COVERAGE);
    expect(project).toEqual({ ...SYNTHETIC_METRIC_COVERAGE, scope: "one_project" });
    provider.metrics[0].contract_compatible_result_states.known = 99;
    await expect(transport.getMetricCoverage("synthetic")).resolves.toEqual(
      SYNTHETIC_METRIC_COVERAGE,
    );
    await expect(transport.getMetricCoverage("codex")).rejects.toMatchObject({
      status: 404,
    });
    await expect(
      transport.getProjectMetricCoverage("f".repeat(64), "synthetic"),
    ).rejects.toMatchObject({ status: 404 });
  });

  it("exposes a coherent canned pack-v3 readiness example", async () => {
    const detail = await createSyntheticTransport().getAnalysisRun(SYNTHETIC_RUN.run_id);
    const byKey = new Map(detail.results.map((result) => [result.key, result]));
    const eventEvidence = new Set(
      byKey.get("task.workflow.observed_event_count")?.evidence_event_ids,
    );

    expect(detail.run).toMatchObject({
      metric_pack_version: 3,
      metric_engine_version: "task-deterministic-2",
      schema_version: 6,
    });
    expect(detail.results).toHaveLength(15);
    expect(byKey.get("task.verification.pass_rate")).toMatchObject({
      numeric_value: 0.5,
      observed_count: 2,
      eligible_count: 2,
      coverage: 1,
      confidence: 1,
    });
    expect(byKey.get("task.usage.input_tokens")).toMatchObject({
      numeric_value: 10,
      observed_count: 1,
      eligible_count: 2,
      coverage: 0.5,
      confidence: null,
    });
    for (const result of detail.results) {
      expect(new Set(result.evidence_event_ids).size).toBe(result.evidence_event_ids.length);
      expect(result.evidence_event_ids.every((eventId) => eventEvidence.has(eventId))).toBe(true);
    }
  });

  it("reviews, analyzes, and queries one fictional task idempotently", async () => {
    const transport = createSyntheticTransport();
    const candidate = SYNTHETIC_CANDIDATES[0].candidate;
    const command = {
      action: "accept",
      request: {
        candidate_id: candidate.candidate_id,
        expected_discovery_version: candidate.discovery_version,
        task_category: "feature_implementation",
      },
    } satisfies ReviewCommand;

    const decision = await transport.review(command, "synthetic-review-v1");
    const repeatedDecision = await transport.review(command, "synthetic-review-v1");
    expect(decision.applied).toBe(true);
    expect(repeatedDecision).toMatchObject({
      decision_id: decision.decision_id,
      applied: false,
    });

    const output = decision.output_revisions[0];
    const taskIndex = await transport.listTaskRevisions();
    expect(taskIndex.tasks[0]).toMatchObject({
      task_id: output.task_id,
      session_ids: candidate.session_ids,
    });
    const analysis = await transport.startAnalysis(
      output.task_id,
      output.revision,
      "synthetic-analysis-v1",
    );
    const repeatedAnalysis = await transport.startAnalysis(
      output.task_id,
      output.revision,
      "synthetic-analysis-v1",
    );
    expect(analysis).toMatchObject({ status: "completed", applied: true });
    expect(repeatedAnalysis).toMatchObject({ run_id: analysis.run_id, applied: false });

    const detail = await transport.getAnalysisRun(analysis.run_id);
    expect(detail.run).toMatchObject({
      metric_pack_key: "core.metadata.task",
      metric_pack_version: 3,
      metric_engine_version: "task-deterministic-2",
      schema_version: 6,
    });
    expect(detail.results).toHaveLength(15);
    expect(detail.results.every((result) => result.evidence_event_ids.length === 0)).toBe(true);
    expect(detail.results.map((result) => result.key)).toContain(
      "task.data_quality.turn_usage_coverage",
    );
    expect(
      detail.results.find(
        (result) => result.key === "task.data_quality.turn_usage_coverage",
      ),
    ).toMatchObject({ value_state: "unknown", numeric_value: null });
    expect(detail.results.map((result) => result.key)).toContain(
      "task.verification.pass_rate",
    );
    const sessionCount = detail.results.find(
      (result) => result.key === "task.workflow.session_count",
    );
    expect(sessionCount).toMatchObject({
      value_state: "known",
      numeric_value: candidate.session_ids.length,
      observed_count: candidate.session_ids.length,
      eligible_count: candidate.session_ids.length,
    });
    expect(detail.results.some((result) => result.value_state === "unknown")).toBe(true);
  });

  it("exposes one explicit synthetic metric lab and current immutable coaching run", async () => {
    const transport = createSyntheticTransport();
    const sessions = await transport.listCodexSessions();
    expect(sessions.sessions).toEqual([
      expect.objectContaining({
        project_id: SYNTHETIC_QUALITY_PROJECT_ID,
        session_id: SYNTHETIC_QUALITY_SESSION_ID,
        project_display_name: "Synthetic Metric Lab",
      }),
    ]);
    const projectSessions = await transport.listProjectSessions(
      SYNTHETIC_QUALITY_PROJECT_ID,
    );
    expect(projectSessions).toMatchObject({ total: 1, has_more: false });
    expect(projectSessions.sessions).toHaveLength(1);
    const missingProject = await transport.listProjectSessions("f".repeat(64));
    expect(missingProject).toMatchObject({
      sessions: [],
      total: 0,
      has_more: false,
    });

    const latest = await transport.getLatestSessionQualityAnalysis(
      SYNTHETIC_QUALITY_SESSION_ID,
    );
    expect(latest.run).toMatchObject({
      run_id: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id,
      status: "completed",
      metric_pack_key: "experimental.redacted-text.coaching",
      metric_pack_version: 3,
      local_only: true,
      metric_scope_state: "exact",
    });
    expect(latest.run.selected_metric_keys).toEqual(
      [...new Set(latest.run.selected_metric_keys)].sort(),
    );
    expect(latest.results).toHaveLength(20);
    expect(latest.results.every((result) => result.value_state === "known")).toBe(true);
    expect(latest.results.every((result) => result.model_id === null)).toBe(true);

    const projectAggregate = await transport.aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    expect(projectAggregate).toMatchObject({
      aggregation_method: "ratio_of_sums",
      estimand: "per_eligible_opportunity",
      selected_project_count: 1,
      selection_mode: "all_analyzed_work",
      session_quality: {
        selected_session_count: 1,
        completed_run_count: 1,
        missing_run_count: 0,
      },
    });
    expect(projectAggregate.session_quality.metrics.every((metric) =>
      metric.not_selected_run_count === 0 &&
      metric.unknown_scope_run_count === 0
    )).toBe(true);
    const publicCohort = projectAggregate.session_quality.metrics.find(
      (metric) => metric.compatibility_cohorts.length > 0,
    )!.compatibility_cohorts[0];
    expect(publicCohort.compatibility_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(publicCohort).not.toHaveProperty("key");
    const serializedProjectAggregate = JSON.stringify(projectAggregate);
    expect(serializedProjectAggregate).not.toContain("provider_version");
    expect(serializedProjectAggregate).not.toContain("adapter_version");
    expect(serializedProjectAggregate).not.toContain("model_plan_fingerprint");

    const sessionAggregate = await transport.aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    expect(sessionAggregate.metrics.every((metric) =>
      metric.not_selected_run_count === 0 &&
      metric.unknown_scope_run_count === 0 &&
      metric.compatibility_cohorts[0]?.key.metric_scope_state === "exact"
    )).toBe(true);

    latest.results[0].numeric_value = 0;
    const secondRead = await transport.getSessionQualityAnalysisRun(
      latest.run.run_id,
    );
    expect(secondRead.results[0].numeric_value).toBe(1);
    await expect(
      transport.getSessionCoachingSummary!(latest.run.run_id),
    ).resolves.toEqual(SYNTHETIC_COACHING_PROJECTION);
  });

  it("replays the immutable current fixture for an explicit synthetic quality command", async () => {
    const transport = createSyntheticTransport();
    const outcome = await transport.startSessionQualityAnalysis(
      SYNTHETIC_QUALITY_SESSION_ID,
      {
        confirmation: "analyze_selected_redacted_text",
        preset_id: "coaching_profile_v1",
      },
      "dashboard-quality-analysis-synthetic",
    );
    expect(outcome).toMatchObject({
      applied: false,
      result_count: 20,
      run_id: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id,
      status: "completed",
    });

    const latest = await transport.getLatestSessionQualityAnalysis(
      SYNTHETIC_QUALITY_SESSION_ID,
    );
    expect(latest).toEqual(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN);
  });

  it("never presents a fictional redaction preview as a real approval flow", async () => {
    const transport = createSyntheticTransport();
    await expect(
      transport.prepareSessionQualityAnalysisPreview(
        SYNTHETIC_QUALITY_SESSION_ID,
        { preset_id: "coaching_profile_v1" },
      ),
    ).rejects.toMatchObject({ status: 501 });
    await expect(
      transport.approveSessionQualityAnalysisPreview(
        "e".repeat(64),
        {
          confirmation: "approve_exact_redacted_preview",
          expected_binding: {
            provider: "synthetic",
            session_id: SYNTHETIC_QUALITY_SESSION_ID,
            analysis_window_fingerprint: "a".repeat(64),
            metric_keys: ["prompt.goal_definition"],
            destination: "local",
            exact_model: "none",
            estimator_plan_version: "synthetic-plan-1",
            redactor_version: "synthetic-redactor-1",
            retention_class: "local_ephemeral",
            message_count: 1,
            character_count: 1,
            cost_state: "not_applicable",
            estimated_cost_microunits: null,
            cost_currency: null,
          },
        },
        "dashboard-quality-preview-approval-synthetic",
      ),
    ).rejects.toMatchObject({ status: 501 });
  });

  it("never fabricates durable queue history in synthetic demo mode", async () => {
    const transport = createSyntheticTransport();
    await expect(transport.listAnalysisJobs()).rejects.toMatchObject({ status: 501 });
    await expect(transport.getAnalysisJob("1".repeat(64))).rejects.toMatchObject({ status: 501 });
    await expect(
      transport.getLatestSessionAnalysisJob(SYNTHETIC_QUALITY_SESSION_ID),
    ).rejects.toMatchObject({ status: 501 });
    await expect(transport.cancelAnalysisJob("1".repeat(64))).rejects.toMatchObject({ status: 501 });
  });

  it("never fabricates standing automation consent in synthetic demo mode", async () => {
    const transport = createSyntheticTransport();
    const scope = {
      provider: "codex" as const,
      project_id: "1".repeat(64),
      metric_keys: ["prompt.context_sufficiency"],
      newest_session_limit: 20,
      check_interval_seconds: 900,
      resource_policy: {
        route: "balanced" as const,
        max_gpu_workers: 1 as const,
        max_cpu_workers: 1 as const,
        pause_on_battery: true as const,
        maximum_session_seconds: 1_800 as const,
      },
      local_only: true as const,
      remote_requires_fresh_approval: true as const,
    };
    await expect(transport.listAutomationGrants("codex")).rejects.toMatchObject({ status: 501 });
    await expect(transport.getAutomationGrant("2".repeat(64), scope)).rejects.toMatchObject({ status: 501 });
    await expect(transport.createAutomationGrant({
      provider: scope.provider,
      project_id: scope.project_id,
      metric_keys: scope.metric_keys,
      newest_session_limit: scope.newest_session_limit,
      check_interval_seconds: scope.check_interval_seconds,
      resource_policy: scope.resource_policy,
    })).rejects.toMatchObject({ status: 501 });
    await expect(transport.renewAutomationGrant("2".repeat(64), scope)).rejects.toMatchObject({ status: 501 });
    await expect(transport.revokeAutomationGrant("2".repeat(64), scope)).rejects.toMatchObject({ status: 501 });
    await expect(transport.pollAutomationGrants()).rejects.toMatchObject({ status: 501 });
  });

  it("keeps model-link excerpts transient while revisioning fictional review labels", async () => {
    const transport = createSyntheticTransport();
    const outcome = await transport.startModelLinkExperiment(
      SYNTHETIC_QUALITY_SESSION_ID,
      {
        confirmation: "compare_selected_redacted_text_with_local_models",
        device: "auto",
      },
      "dashboard-model-link-experiment-synthetic",
    );
    expect(outcome.suggestions).toHaveLength(2);

    const linkId = outcome.experiment.links[0].link_id;
    const annotation = await transport.annotateModelLink(
      outcome.experiment.run.run_id,
      linkId,
      { label: "relevant", expected_revision: 0 },
    );
    expect(annotation).toMatchObject({ revision: 1, label: "relevant" });

    const latest = await transport.getLatestModelLinkExperiment(
      SYNTHETIC_QUALITY_SESSION_ID,
    );
    expect(latest.annotations).toEqual([annotation]);
    expect(JSON.stringify(latest)).not.toContain("query_excerpt");
    expect(SYNTHETIC_MODEL_LINK_EXPERIMENT.annotations).toEqual([]);
  });
});
