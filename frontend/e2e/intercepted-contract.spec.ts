import { expect, test, type Page, type Route } from "@playwright/test";

// This suite deliberately replaces application routes with bounded synthetic
// fixtures. It proves browser/transport contracts, not a real backend journey.

import {
  SYNTHETIC_CURRENT_SESSION_QUALITY_RUN,
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_METRIC_READINESS,
} from "../src/shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../src/shared/api/syntheticTransport";
import { exampleCalibrationReview } from "../src/features/calibration/calibrationFixtures.test-support";
import { exampleAgentTurn, exampleWriteReceipt } from "../src/features/agent/agentTurnFixtures.test-support";
import { exampleAgentSession } from "../src/shared/api/agentSession.test-support";

const PRIVATE_HEADERS = {
  "Cache-Control": "no-store, private",
  "Content-Type": "application/json",
  Pragma: "no-cache",
};

for (const width of [360, 1440]) {
  for (const windowMode of [false, true]) {
    test(`Agent HTTP cleanup refusal keeps the draft and ignores stale ready pages at ${width}px (${windowMode ? "separate" : "main"})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const session = exampleAgentSession();
      const alias = "example-model";
      let refused = false;
      let sends = 0;
      let stalePages = 0;
      await page.route("**/v1/agent/sessions", (route) => json(route, [session]));
      await page.route(`**/v1/agent/sessions/${session.session_id}`, (route) => json(route, session));
      await page.route("**/v1/local-models", (route) => json(route, {
        contract_version: "local-models.v1", runtime_available: true, storage_root: "D:/example/models", downloads: [],
        models: [{ record: { alias, display_name: "Example Small CPU", format: "gguf", path: "D:/example/models/example.gguf", context_size: 4096,
          default_device: "cpu", added_at: "2040-01-01T00:00:00Z", provenance_verified: false },
          runtime: { state: "running", device: "cpu" }, endpoint_path: `/v1/local-models/${alias}/chat/completions` }],
        hardware: { gpu_name: null, gpu_memory_mb: null, gpu_memory_free_mb: null, ram_mb: 8192,
          llama_server_path: "D:/example/runtime/llama-server.exe", llama_server_version: "example-v1" },
      }));
      await page.route("**/v1/agent/sessions/*/events/stream*", async (route) => {
        if (refused) stalePages += 1;
        await route.fulfill({ status: 200, headers: { ...PRIVATE_HEADERS, "Content-Type": "text/event-stream; charset=utf-8" },
          body: `data: ${JSON.stringify({ contract_version: "local-agent.v9", session_id: session.session_id, cleanup_unconfirmed: false,
            closing: false, stopping: false, running: false, pending_approval_id: null, events: [], last_seq: 0, first_seq: 0 })}\n\n` });
      });
      await page.route("**/v1/agent/sessions/*/messages", async (route) => {
        sends += 1;
        expect(route.request().headers()["x-prompt-enhancer-csrf"]).toBe("synthetic-browser-csrf-token");
        refused = true;
        await json(route, { detail: { code: "command_cleanup_unconfirmed", message: "EXAMPLE_PRIVATE_CLEANUP_CANARY" } }, 409);
      });
      await page.goto(windowMode ? `/agent/window/${session.session_id}` : "/agent");
      const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
      await expect(composer).toBeEnabled();
      await composer.fill("Keep this fictional request for review.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByLabel("Agent activity status")).toContainText("Command cleanup unconfirmed");
      await expect.poll(() => stalePages).toBeGreaterThan(0);
      await expect(page.getByLabel("Agent activity status")).toContainText("Command cleanup unconfirmed");
      await expect(composer).toHaveValue("Keep this fictional request for review.");
      await expect(composer).toHaveAttribute("readonly", "");
      await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
      await expect(page.getByText("EXAMPLE_PRIVATE_CLEANUP_CANARY", { exact: false })).toHaveCount(0);
      expect(sends).toBe(1);
      const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
      expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
    });
  }

  test("Calibration HTTP review retains the draft and renews an expired case receipt at " + width + "px", async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installLocalHttpFixture(page);
    const session = "a".repeat(64);
    const metric = "prompt.task_definition_coverage";
    let reviews = 0;
    let rawReads = 0;
    let saved = false;
    const submissions: { review_id: string; session_id: string; ratings: Record<string, string> }[] = [];
    const progress = () => ({
      contract_version: "calibration-ratings.v1", sample_id: "b".repeat(64), sample_size: 1,
      rated_sessions: saved ? 1 : 0, rater_count: saved ? 1 : 0,
      metrics: [{ metric_key: metric, rated_sessions: saved ? 1 : 0, low: 0, medium: 0, high: saved ? 1 : 0, cannot_judge: 0 }],
    });
    await page.route("**/v1/calibration/sample**", (route) => json(route, {
      contract_version: "calibration-ratings.v1", sample_id: "b".repeat(64), sample_version: "example-sample-v1",
      created_at: "2040-01-01T00:00:00Z", target_size: 1, metric_keys: [metric],
      members: [{ position: 0, session_id: session, provider: "codex", project_id: "c".repeat(64),
        project_display_name: "Example project", session_display_name: "Example reviewed case", started_at: null, rated_metric_keys: saved ? [metric] : [] }],
    }));
    await page.route("**/v1/calibration/progress", (route) => json(route, progress()));
    await page.route("**/v1/calibration/review", (route) => {
      expect(route.request().method()).toBe("POST");
      expect(route.request().headers()["x-prompt-enhancer-csrf"]).toBe("synthetic-browser-csrf-token");
      expect(route.request().postDataJSON()).toEqual({ session_id: session, window_characters: 15000 });
      reviews += 1;
      return json(route, exampleCalibrationReview(session, { provider: "codex", review_id: (reviews === 1 ? "d" : "e").repeat(32),
        case_fingerprint: (reviews === 1 ? "d" : "e").repeat(64), records: [{ sequence: 0, role: "user", content: "Review the synthetic case. " + "example".repeat(100) }] }));
    });
    await page.route("**/v1/sessions/*/transcript", (route) => { rawReads += 1; return json(route, {}, 500); });
    await page.route("**/v1/calibration/ratings**", (route) => {
      if (route.request().method() === "GET") return json(route, saved ? [{
        rater_id: "f".repeat(64), session_id: session, metric_key: metric, label: "high", rated_at: "2040-01-01T00:00:00Z", revision: 1,
        rating_version: "calibration-rating-v2-reviewed-case", case_fingerprint: "e".repeat(64), case_version: "calibration-case.v1", window_fingerprint: "e".repeat(64),
      }] : []);
      expect(route.request().method()).toBe("PUT");
      expect(route.request().headers()["x-prompt-enhancer-csrf"]).toBe("synthetic-browser-csrf-token");
      submissions.push(route.request().postDataJSON());
      if (submissions.length === 1) return json(route, { detail: { code: "calibration_review_expired", message: "SYNTHETIC_PRIVATE_CANARY" } }, 409);
      saved = true;
      return json(route, progress());
    });
    await page.goto("/calibration");
    await page.getByRole("textbox", { name: "Rater name", exact: true }).fill("Example rater");
    await page.getByRole("textbox", { name: "Rater name", exact: true }).press("Enter");
    await page.getByRole("button", { name: "Next unrated", exact: true }).click();
    await expect(page.getByLabel("Redacted case evidence")).toContainText("Review the synthetic case.");
    await page.getByRole("radiogroup", { name: "Task definition", exact: true }).getByText("High", { exact: true }).click();
    const save = page.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeDisabled();
    await page.getByRole("checkbox", { name: /I reviewed this case/ }).check();
    await save.click();
    await expect(page.getByText(/review receipt could not be confirmed/)).toBeVisible();
    await expect(save).toBeDisabled();
    await expect(page.getByRole("radiogroup", { name: "Task definition" }).getByRole("radio").nth(2)).toBeChecked();
    await expect(page.getByText("SYNTHETIC_PRIVATE_CANARY", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh case", exact: true }).click();
    await expect(page.getByText(/Case eeeeeeeeeeee/)).toBeVisible();
    await expect(save).toBeDisabled();
    await page.getByRole("checkbox", { name: /I reviewed this case/ }).check();
    await save.click();
    await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
    expect(submissions).toHaveLength(2);
    expect(submissions.map((request) => request.review_id)).toEqual(["d".repeat(32), "e".repeat(32)]);
    expect(submissions.every((request) => request.session_id === session && request.ratings[metric] === "high")).toBe(true);
    expect(reviews).toBe(2);
    expect(rawReads).toBe(0);
    const layout = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
    expect(layout.content).toBeLessThanOrEqual(layout.viewport);
  });

  test("Calibration HTTP judgments distinguish invalid replies and historical results at " + width + "px", async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installLocalHttpFixture(page);
    const session = "a".repeat(64);
    const metric = "prompt.task_definition_coverage";
    let judgmentRequests = 0;
    let ratingMutations = 0;
    await page.route("**/v1/calibration/sample**", (route) => json(route, {
      contract_version: "calibration-ratings.v1", sample_id: "b".repeat(64), sample_version: "example-sample-v1",
      created_at: "2040-01-01T00:00:00Z", target_size: 1, metric_keys: [metric],
      members: [{ position: 0, session_id: session, provider: "codex", project_id: "c".repeat(64),
        project_display_name: "Example project", session_display_name: "Example request", started_at: null, rated_metric_keys: [] }],
    }));
    await page.route("**/v1/calibration/progress", (route) => json(route, {
      contract_version: "calibration-ratings.v1", sample_id: "b".repeat(64), sample_size: 1, rated_sessions: 0, rater_count: 0,
      metrics: [{ metric_key: metric, rated_sessions: 0, low: 0, medium: 0, high: 0, cannot_judge: 0 }],
    }));
    await page.route("**/v1/calibration/ratings**", (route) => {
      if (route.request().method() !== "GET") ratingMutations += 1;
      return json(route, []);
    });
    await page.route("**/v1/model-judge/agreement", (route) => json(route, {
      contract_version: "model-judge.v1", model_alias: "example-local-model", judged_sessions: judgmentRequests >= 2 ? 1 : 0,
      excluded_judgments: judgmentRequests >= 2 ? 0 : 3, accepted_prompt_versions: ["judge-v4-complete-json-anchor-15k"],
      metrics: [{ metric_key: metric, pairs: 0, agreement_rate: null, cohen_kappa: null, state: "insufficient_data", reason: "no_overlapping_ratings" }],
      caveat: "Experimental judgments; historical protocols do not enter current agreement.",
    }));
    await page.route("**/v1/model-judge/sweep", (route) => json(route, {
      contract_version: "model-judge.v1", running: false, model_alias: "example-local-model", total: 0, done: 0, failed: 0, last_error_code: null,
    }));
    await page.route("**/v1/model-judge/sessions/" + session, (route) => {
      expect(route.request().method()).toBe("POST");
      expect(route.request().headers()["x-prompt-enhancer-csrf"]).toBe("synthetic-browser-csrf-token");
      judgmentRequests += 1;
      return judgmentRequests === 1
        ? json(route, { detail: { code: "model_reply_invalid", message: "SYNTHETIC_PRIVATE_CANARY" } }, 502)
        : json(route, { contract_version: "model-judge.v1", session_id: session, model_alias: "example-local-model", raw_valid: true,
          judgments: [{ session_id: session, metric_key: metric, label: "high", model_alias: "example-local-model", model_identity: "example.gguf",
            prompt_version: "judge-v4-complete-json-anchor-15k", window_fingerprint: "d".repeat(64), judged_at: "2040-01-01T00:00:00Z" }] });
    });
    await page.goto("/calibration");
    await expect(page.getByText(/3 stored judgments excluded from current agreement/)).toBeVisible();
    await page.getByRole("button", { name: "Next unrated", exact: true }).click();
    await page.getByRole("button", { name: "Judge this session", exact: true }).click();
    await expect(page.getByText(/incomplete or invalid reply.*Existing judgments were kept/)).toBeVisible();
    await expect(page.getByText(/3 stored judgments excluded from current agreement/)).toBeVisible();
    await expect(page.getByText("SYNTHETIC_PRIVATE_CANARY", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Judge this session", exact: true }).click();
    await expect(page.getByText(/Model judged this session.*your own rating stays blind/)).toBeVisible();
    await expect(page.getByText(/3 stored judgments excluded from current agreement/)).toHaveCount(0);
    await expect(page.locator(".calibration__agreement").getByText("0%", { exact: true })).toHaveCount(0);
    expect(judgmentRequests).toBe(2);
    expect(ratingMutations).toBe(0);
    const layout = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
    expect(layout.content).toBeLessThanOrEqual(layout.viewport);
  });

  for (const ending of ["length", "dropped"] as const) {
    test("Models HTTP chat recovers a " + ending + " reply at " + width + "px", async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await installLocalHttpFixture(page);
      await page.route("**/v1/local-models", (route) => json(route, localModelsOverviewFixture("example-small-cpu")));
      await page.route("**/v1/local-models/runtime", (route) => json(route, readyRuntimeFixture("example-small-cpu")));
      const requests: { messages: { role: string; content: string }[]; stream: boolean }[] = [];
      await page.route("**/v1/local-models/example-small-cpu/chat/completions", async (route) => {
        expect(route.request().headers()["x-prompt-enhancer-csrf"]).toBe("synthetic-browser-csrf-token");
        requests.push(route.request().postDataJSON());
        const first = requests.length === 1;
        const choice = {
          delta: { content: first ? "Example unfinished HTTP reply." : "Example confirmed HTTP answer." },
          finish_reason: first ? ending === "length" ? "length" : null : "stop",
        };
        await route.fulfill({
          body: "data: " + JSON.stringify({ choices: [choice] }) + "\n\n"
            + (first && ending === "dropped" ? "" : "data: [DONE]\n\n"),
          headers: { ...PRIVATE_HEADERS, "Content-Type": "text/event-stream; charset=utf-8" },
        });
      });

      await page.goto("/models");
      const composer = page.getByRole("textbox", { name: "Message", exact: true });
      await composer.fill("Give a bounded example reply.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText(ending === "length" ? "response token limit" : "reply did not finish");
      const partial = page.locator('[data-response-status="' + (ending === "length" ? "incomplete" : "failed") + '"]');
      await expect(partial).toContainText("Example unfinished HTTP reply.");
      await composer.fill("Example next draft.");
      await page.getByRole("button", { name: "Retry last message", exact: true }).click();
      await expect(page.locator('[data-response-status="complete"]')).toContainText("Example confirmed HTTP answer.");
      await expect(composer).toHaveValue("Example next draft.");
      await expect(page.getByRole("alert")).toHaveCount(0);
      expect(requests).toHaveLength(2);
      expect(requests[1].stream).toBe(true);
      expect(requests[1].messages).toEqual([{ role: "user", content: "Give a bounded example reply." }]);
      const layout = await page.evaluate(() => ({
        content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
      }));
      expect(layout.content).toBeLessThanOrEqual(layout.viewport);
    });
  }
}

async function json(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    headers: PRIVATE_HEADERS,
    status,
  });
}

function integer(value: string | null, fallback: number): number {
  if (value === null) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

function localModelStatusFixture(
  alias = "example-model",
  displayName = "Example Small CPU",
) {
  return {
    endpoint_path: `/v1/local-models/${alias}/chat/completions`,
    record: {
      added_at: "2040-01-01T00:00:00Z",
      alias,
      context_size: 8192,
      default_device: "cpu" as const,
      display_name: displayName,
      format: "gguf",
      path: `D:/example/models/${alias}.gguf`,
      provenance_verified: false,
    },
    runtime: { state: "running" as const, device: "cpu" as const },
    placement: {
      contract_version: "local-model-placement.v1",
      alias,
      context_size: 8192,
      gpu_memory_free_mb: null,
      actual_offload_verified: false,
      options: [
        { device: "gpu", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "split", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
      ],
    },
  };
}

function localModelsOverviewFixture(
  alias = "example-model",
  displayName = "Example Small CPU",
) {
  return {
    contract_version: "local-models.v1",
    runtime_available: true,
    storage_root: "D:/example/models",
    storage_free_bytes: 64 * 1024 ** 3,
    download_reserve_bytes: 512 * 1024 ** 2,
    download_ledger_error_code: null,
    downloads: [],
    hardware: {
      gpu_name: null,
      gpu_memory_mb: null,
      gpu_memory_free_mb: null,
      ram_mb: 8192,
      llama_server_path: "D:/example/runtime/llama-server.exe",
      llama_server_version: "example-v1",
    },
    models: [localModelStatusFixture(alias, displayName)],
  };
}

function readyRuntimeFixture(alias = "example-model") {
  const selection = {
    alias,
    device: "cpu" as const,
    gpu_layers: 0,
    context_size: 8192,
  };
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision: 4,
    state: "ready",
    requested: selection,
    served: {
      ...selection,
      started_at: "2040-01-01T00:00:00Z",
      pid: 4242,
    },
    cleanup: {
      state: "not_required",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: null,
      gpu_memory_free_after_mb: null,
      gpu_memory_released_mb: null,
    },
    capabilities: {
      state: "verified",
      probe_version: "local-runtime-multimodal-probe.v2",
      text: true,
      tools: true,
      vision: false,
      audio: false,
      recording: false,
      structured_output: false,
      error_code: null,
    },
    context: {
      state: "unknown",
      used_tokens: null,
      limit_tokens: 8192,
      requested_output_tokens: null,
      available_output_tokens: null,
      source: "runtime_limit_only",
      scope: "runtime_limit",
      policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: "no_request_measured",
    },
    active_requests: 0,
    last_error_code: null,
  };
}

async function installReadyAgentFixture(page: Page): Promise<void> {
  const session = exampleAgentSession({
    model_alias: "example-model",
    settings: {
      ...exampleAgentSession().settings,
      project_id: null,
      model_alias: "example-model",
      title: "Example workspace",
    },
  });
  await page.route("**/v1/agent/sessions", (route) => json(route, [session]));
  await page.route(`**/v1/agent/sessions/${session.session_id}`, (route) => json(route, session));
  await page.route("**/v1/local-models", (route) => json(route, localModelsOverviewFixture()));
  await page.route("**/v1/local-models/runtime", (route) => json(route, readyRuntimeFixture()));
}

function promptCheckFixture() {
  return {
    contract_version: "prompt-check.v1",
    check_id: "e".repeat(32),
    created_at: "2026-08-20T20:01:00Z",
    provider: "other",
    agent_model: null,
    metrics: [{
      key: "prompt.acceptance_testability",
      display_name: "Acceptance testability",
      description: "Checkable acceptance requirements",
      state: "known",
      value: 0.5,
      numerator: 1,
      denominator: 2,
      higher_is_better: true,
      explanation_code: "observed",
      cues: [],
    }],
    context: {
      task_type: "implement",
      language: "en",
      prompt_chars: 30,
      prompt_words: 5,
      sentence_count: 1,
      bullet_count: 0,
      question_count: 0,
      file_references: 1,
      code_identifiers: 0,
      urls: 0,
      prior_context_supplied: 0,
      depends_on_prior_context: false,
      verification_requested: false,
      missing_elements: ["a checkable pass condition"],
    },
    commentary: {
      state: "ok",
      model_alias: "example-local-model",
      prompt_version: "prompt-check-commentary-v1",
      findings: [{ aspect: "verification", severity: "high", why: "No check is named.", suggestion: "Name the focused test command." }],
      reformulated_prompt: "Update example.ts, run the focused test, and report the changed files and result.",
      reformulated_elements: [],
      notes: null,
      caveat: "Local-model suggestion; not measured evidence.",
    },
    summary: "The target is visible, but verification needs a concrete pass condition.",
    engine_version: "engine-v1",
    rubric_version: "rubric-v1",
    dashboard_path: `/prompt-checks/${"e".repeat(32)}`,
    other_metric_families_note: "Collaboration and outcome metrics require later session evidence.",
  };
}

const CODEX_UNSUPPORTED_METRICS = new Map<string, "feedback_text" | "objective_verification" | "decision_evidence" | "action_evidence">([
  ["collaboration.rework_candidate_rate", "feedback_text"],
  ["logic.hypothesis_test_linkage", "objective_verification"],
  ["logic.decision_rationale_coverage", "decision_evidence"],
  ["logic.requirement_action_traceability", "action_evidence"],
  ["outcome.agent_claim_grounding", "objective_verification"],
  ["outcome.first_pass_verification", "objective_verification"],
  ["outcome.verified_requirement_coverage", "objective_verification"],
]);

function codexReadinessFixture(): typeof SYNTHETIC_SESSION_METRIC_READINESS {
  const fixture = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
  fixture.provider = "codex";
  fixture.capability_report.provider = "codex";
  fixture.capability_report.provider_version = "synthetic-codex-provider-1";
  fixture.capability_report.decoder_key = "codex.app-server.text-window";
  fixture.capability_report.structurally_attemptable_metric_count = 13;
  fixture.capability_report.structurally_unsupported_metric_count = 7;
  fixture.capability_report.capabilities = fixture.capability_report.capabilities.map(
    (capability) => ({
      ...capability,
      state: ["request_text", "response_text", "plan_text"].includes(capability.capability)
        ? "supported"
        : "unsupported",
      reason_code: ["request_text", "response_text", "plan_text"].includes(capability.capability)
        ? "verified_by_compatible_decoder"
        : "not_declared_by_decoder",
    }),
  );
  fixture.metrics = fixture.metrics.map((metric) => {
    const missing = CODEX_UNSUPPORTED_METRICS.get(metric.metric_key);
    if (missing === undefined) {
      return {
        ...metric,
        available_capabilities: metric.available_capabilities.filter((capability) =>
          ["request_text", "response_text", "plan_text"].includes(capability)
        ),
      };
    }
    const action = ({
      action_evidence: "collect_action_evidence",
      decision_evidence: "collect_decision_evidence",
      feedback_text: "collect_feedback_evidence",
      objective_verification: "collect_objective_verification",
    } as const)[missing];
    return {
      ...metric,
      state: "unsupported",
      reason_code: "provider_capability_missing",
      next_actions: [action],
      available_capabilities: metric.available_capabilities.filter((capability) =>
        ["request_text", "response_text", "plan_text"].includes(capability)
      ),
      missing_capabilities: [missing],
      latest_run_id: null,
    };
  });
  return fixture;
}

async function installLocalHttpFixture(page: Page): Promise<void> {
  const transport = createSyntheticTransport();
  const agentSessionId = "a".repeat(32);
  const initialAgentRevision = "b".repeat(64);
  const proposedAgentRevision = "c".repeat(64);
  const agentPreviewId = "d".repeat(32);
  const initialAgentContent = "export const value = 1;\n";
  const initialHelperRevision = "e".repeat(64);
  const proposedHelperRevision = "f".repeat(64);
  const transactionPlanId = "1".repeat(32);
  const lifecycleRevision = "2".repeat(64);
  const createPreviewId = "3".repeat(32);
  const movePreviewId = "4".repeat(32);
  const directoryPreviewId = "5".repeat(32);
  const directoryMovePreviewId = "6".repeat(32);
  const trashPreviewId = "7".repeat(32);
  const initialHelperContent = "export const helper = 1;\n";
  let agentContent = initialAgentContent;
  let agentRevision = initialAgentRevision;
  let helperContent = initialHelperContent;
  let helperRevision = initialHelperRevision;
  let lifecycleDirectoryPath: string | null = null;
  let lifecyclePath: string | null = null;
  let lifecycleContent = "";

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (!path.startsWith("/auth/") && path !== "/health" && !path.startsWith("/v1/")) {
      await route.continue();
      return;
    }

    if (path === "/health" && method === "GET") {
      await json(route, {
        status: "ok",
        cost_mode: "offline_only",
        data_tier: "metadata",
      });
      return;
    }
    if (path === "/auth/session" && method === "GET") {
      await json(route, {
        csrf_token: "synthetic-browser-csrf-token",
        expires_in_seconds: 300,
      });
      return;
    }
    if (path === "/v1/capabilities" && method === "GET") {
      await json(route, await transport.getSessionTextAnalysisCapability());
      return;
    }
    if (path === "/v1/research/text-analysis-methods" && method === "GET") {
      await json(route, await transport.getTextAnalysisResearch!());
      return;
    }
    if (path === "/v1/metric-contracts/v2/operability-catalog" && method === "GET") {
      await json(route, await transport.getMetricOperabilityCatalog!());
      return;
    }
    if (path === "/v1/local-sources/claude-code" && method === "GET") {
      await json(route, await transport.getClaudeLocalSourceStatus());
      return;
    }
    if (path === "/v1/local-sources/codex" && method === "GET") {
      await json(route, await transport.getCodexLocalSourceStatus());
      return;
    }
    if (path === "/v1/sessions" && method === "GET") {
      await json(
        route,
        await transport.listCodexSessions(
          integer(url.searchParams.get("limit"), 100),
          integer(url.searchParams.get("offset"), 0),
        ),
      );
      return;
    }
    if (path === "/v1/agent/sessions" && method === "GET") {
      await json(route, [exampleAgentSession({
        session_id: agentSessionId,
        settings: {
          ...exampleAgentSession().settings,
          workspace: "D:\\example\\workspace",
          project_id: null,
          model_alias: null,
          title: "Example workspace",
        },
        model_alias: null,
      })]);
      return;
    }
    const agentChanges = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/changes$/);
    if (agentChanges && method === "GET") {
      const changed = agentRevision !== initialAgentRevision;
      await json(route, {
        contract_version: "agent-change-set.v1",
        session_id: agentChanges[1],
        scope: "reviewed_paths_only",
        coverage: "complete",
        settled: true,
        reviewed_writes: changed ? 1 : 0,
        verified_writes: changed ? 1 : 0,
        unverified_writes: 0,
        agent_writes: 0,
        manual_writes: changed ? 1 : 0,
        reviewed_noops: 0,
        command_attempts: 0,
        omitted_write_receipts: 0,
        tracking_failed: false,
        files: changed ? [{
          path: "example.ts",
          net_effect: "modified",
          verification: "verified",
          reason: null,
          reviewed_writes: 1,
          agent_writes: 0,
          manual_writes: 1,
          current_byte_size: new TextEncoder().encode(agentContent).byteLength,
          diff_available: true,
        }] : [],
      });
      return;
    }
    const agentChangeDiff = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/changes\/diff$/);
    if (agentChangeDiff && method === "GET") {
      expect(url.searchParams.get("path")).toBe("example.ts");
      const changed = agentRevision !== initialAgentRevision;
      await json(route, {
        contract_version: "agent-change-set.v1",
        session_id: agentChangeDiff[1],
        summary: {
          path: "example.ts",
          net_effect: changed ? "modified" : "reverted",
          verification: "verified",
          reason: null,
          reviewed_writes: 1,
          agent_writes: 0,
          manual_writes: 1,
          current_byte_size: new TextEncoder().encode(agentContent).byteLength,
          diff_available: true,
        },
        diff_state: changed ? "available" : "no_change",
        diff: changed
          ? "--- a/example.ts\n+++ b/example.ts\n@@ -1 +1 @@\n-export const value = 1;\n+export const value = 2;"
          : null,
        added_lines: changed ? 1 : 0,
        removed_lines: changed ? 1 : 0,
      });
      return;
    }
    if (path === "/v1/prompt-checks" && method === "POST") {
      await json(route, promptCheckFixture());
      return;
    }
    const agentDiscovery = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/discovery$/);
    if (agentDiscovery && method === "GET") {
      const changed = agentRevision !== initialAgentRevision;
      await json(route, {
        contract_version: "local-agent-workspace-discovery.v1",
        session_id: agentDiscovery[1],
        scope: "selected_workspace",
        inventory_coverage: "complete",
        inventory_reasons: [],
        scanned_entry_count: 2,
        observed_file_count: 2,
        files: [
          { path: "example.ts", byte_size: new TextEncoder().encode(agentContent).byteLength, editable_candidate: true },
          { path: "src/helper.ts", byte_size: new TextEncoder().encode(helperContent).byteLength, editable_candidate: true },
        ],
        git_state: "available",
        git_coverage: "complete",
        git_reasons: [],
        git_change_count: changed ? 1 : 0,
        git_changes: changed ? [{ path: "example.ts", kind: "modified", staged: false, unstaged: true }] : [],
      });
      return;
    }
    const agentTree = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/tree$/);
    if (agentTree && method === "GET") {
      const requestedPath = url.searchParams.get("path") ?? ".";
      const directChild = (candidate: string): boolean => {
        const remainder = requestedPath === "."
          ? candidate
          : candidate.startsWith(`${requestedPath}/`)
            ? candidate.slice(requestedPath.length + 1)
            : "";
        return remainder !== "" && !remainder.includes("/");
      };
      const entries: Array<{ path: string; name: string; kind: "directory" | "file"; byte_size: number | null; editable_candidate: boolean }> = requestedPath === "src"
        ? [{ path: "src/helper.ts", name: "helper.ts", kind: "file", byte_size: helperContent.length, editable_candidate: true }]
        : requestedPath === "." ? [
            { path: "src", name: "src", kind: "directory" as const, byte_size: null, editable_candidate: false },
            { path: "archive", name: "archive", kind: "directory" as const, byte_size: null, editable_candidate: false },
            { path: "example.ts", name: "example.ts", kind: "file" as const, byte_size: agentContent.length, editable_candidate: true },
          ] : [];
      if (lifecycleDirectoryPath && directChild(lifecycleDirectoryPath)) {
        entries.push({
          path: lifecycleDirectoryPath,
          name: lifecycleDirectoryPath.split("/").at(-1)!,
          kind: "directory",
          byte_size: null,
          editable_candidate: false,
        });
      }
      if (lifecyclePath && directChild(lifecyclePath)) {
        entries.push({
          path: lifecyclePath,
          name: lifecyclePath.split("/").at(-1)!,
          kind: "file",
          byte_size: new TextEncoder().encode(lifecycleContent).byteLength,
          editable_candidate: true,
        });
      }
      await json(route, {
        contract_version: "local-agent-workspace.v1",
        session_id: agentTree[1],
        path: requestedPath,
        entries,
        complete: true,
      });
      return;
    }
    const agentFile = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/file$/);
    if (agentFile && method === "GET") {
      const requestedPath = url.searchParams.get("path");
      const helper = requestedPath === "src/helper.ts";
      const lifecycle = requestedPath === lifecyclePath;
      const content = lifecycle ? lifecycleContent : helper ? helperContent : agentContent;
      await json(route, {
        contract_version: "local-agent-workspace.v1",
        session_id: agentFile[1],
        path: requestedPath,
        content,
        revision: lifecycle ? lifecycleRevision : helper ? helperRevision : agentRevision,
        byte_size: new TextEncoder().encode(content).byteLength,
        line_ending: "lf",
        editable: true,
      });
      return;
    }
    const agentDirectoryPreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/directories$/);
    if (agentDirectoryPreview && method === "POST") {
      const body = request.postDataJSON() as { path: string };
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentDirectoryPreview[1],
        preview_id: directoryPreviewId,
        path: body.path,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentDirectoryApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/directories\/([a-f0-9]{32})\/apply$/);
    if (agentDirectoryApply && method === "POST") {
      const body = request.postDataJSON() as { path: string; confirmation: string };
      expect(agentDirectoryApply[2]).toBe(directoryPreviewId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_directory_create");
      lifecycleDirectoryPath = body.path;
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentDirectoryApply[1],
        path: body.path,
        operation: "directory_created",
        applied: true,
      });
      return;
    }
    const agentDirectoryMovePreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/directory-moves$/);
    if (agentDirectoryMovePreview && method === "POST") {
      const body = request.postDataJSON() as { source_path: string; target_path: string };
      expect(body.source_path).toBe(lifecycleDirectoryPath);
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentDirectoryMovePreview[1],
        preview_id: directoryMovePreviewId,
        source_path: body.source_path,
        target_path: body.target_path,
        contents_reviewed: false,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentDirectoryMoveApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/directory-moves\/([a-f0-9]{32})\/apply$/);
    if (agentDirectoryMoveApply && method === "POST") {
      const body = request.postDataJSON() as { source_path: string; target_path: string; confirmation: string };
      expect(agentDirectoryMoveApply[2]).toBe(directoryMovePreviewId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_directory_move");
      expect(body.source_path).toBe(lifecycleDirectoryPath);
      if (lifecyclePath?.startsWith(`${body.source_path}/`)) {
        lifecyclePath = `${body.target_path}${lifecyclePath.slice(body.source_path.length)}`;
      }
      lifecycleDirectoryPath = body.target_path;
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentDirectoryMoveApply[1],
        source_path: body.source_path,
        target_path: body.target_path,
        contents_reviewed: false,
        operation: "directory_moved",
        applied: true,
      });
      return;
    }
    const agentCreatePreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/creates$/);
    if (agentCreatePreview && method === "POST") {
      const body = request.postDataJSON() as { path: string; content: string; line_ending: string };
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentCreatePreview[1],
        preview_id: createPreviewId,
        path: body.path,
        proposed_revision: lifecycleRevision,
        line_ending: body.line_ending,
        byte_size: new TextEncoder().encode(body.content).byteLength,
        diff: `--- /dev/null\n+++ b/${body.path}\n@@ -0,0 +1 @@\n+${body.content.trimEnd()}`,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentCreateApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/creates\/([a-f0-9]{32})\/apply$/);
    if (agentCreateApply && method === "POST") {
      const body = request.postDataJSON() as { path: string; content: string; proposed_revision: string; confirmation: string };
      expect(agentCreateApply[2]).toBe(createPreviewId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_create");
      expect(body.proposed_revision).toBe(lifecycleRevision);
      lifecyclePath = body.path;
      lifecycleContent = body.content;
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentCreateApply[1],
        path: body.path,
        revision: lifecycleRevision,
        byte_size: new TextEncoder().encode(body.content).byteLength,
        operation: "created",
        applied: true,
      });
      return;
    }
    const agentMovePreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/moves$/);
    if (agentMovePreview && method === "POST") {
      const body = request.postDataJSON() as { source_path: string; target_path: string; expected_revision: string };
      expect(body.source_path).toBe(lifecyclePath);
      expect(body.expected_revision).toBe(lifecycleRevision);
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentMovePreview[1],
        preview_id: movePreviewId,
        source_path: body.source_path,
        target_path: body.target_path,
        expected_revision: lifecycleRevision,
        byte_size: new TextEncoder().encode(lifecycleContent).byteLength,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentMoveApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/moves\/([a-f0-9]{32})\/apply$/);
    if (agentMoveApply && method === "POST") {
      const body = request.postDataJSON() as { source_path: string; target_path: string; expected_revision: string; confirmation: string };
      expect(agentMoveApply[2]).toBe(movePreviewId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_move");
      expect(body.source_path).toBe(lifecyclePath);
      lifecyclePath = body.target_path;
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentMoveApply[1],
        source_path: body.source_path,
        target_path: body.target_path,
        revision: lifecycleRevision,
        byte_size: new TextEncoder().encode(lifecycleContent).byteLength,
        operation: "moved",
        applied: true,
      });
      return;
    }
    const agentTrashPreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/file-trash$/);
    if (agentTrashPreview && method === "POST") {
      const body = request.postDataJSON() as { path: string; expected_revision: string };
      expect(body.path).toBe(lifecyclePath);
      expect(body.expected_revision).toBe(lifecycleRevision);
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentTrashPreview[1],
        preview_id: trashPreviewId,
        path: body.path,
        expected_revision: lifecycleRevision,
        byte_size: new TextEncoder().encode(lifecycleContent).byteLength,
        recovery: "windows_recycle_bin",
        permanent: false,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentTrashApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/file-trash\/([a-f0-9]{32})\/apply$/);
    if (agentTrashApply && method === "POST") {
      const body = request.postDataJSON() as { path: string; expected_revision: string; confirmation: string };
      expect(agentTrashApply[2]).toBe(trashPreviewId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_file_trash");
      expect(body.path).toBe(lifecyclePath);
      const trashedPath = body.path;
      lifecyclePath = null;
      await json(route, {
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: agentTrashApply[1],
        path: trashedPath,
        revision: lifecycleRevision,
        byte_size: new TextEncoder().encode(lifecycleContent).byteLength,
        recovery: "windows_recycle_bin",
        permanent: false,
        operation: "trashed",
        applied: true,
      });
      return;
    }
    const agentPreviews = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/previews$/);
    if (agentPreviews && method === "POST") {
      const body = request.postDataJSON();
      await json(route, {
        contract_version: "local-agent-workspace.v1",
        session_id: agentPreviews[1],
        preview_id: agentPreviewId,
        path: body.path,
        expected_revision: body.expected_revision,
        proposed_revision: proposedAgentRevision,
        line_ending: body.line_ending,
        diff: "--- a/example.ts\n+++ b/example.ts\n@@ -1 +1 @@\n-export const value = 1;\n+export const value = 2;",
        expires_at: "2026-08-20T22:00:00Z",
      }, 201);
      return;
    }
    const agentApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/previews\/([a-f0-9]{32})\/apply$/);
    if (agentApply && method === "POST") {
      const body = request.postDataJSON();
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.content).not.toBe(initialAgentContent);
      agentContent = body.content;
      agentRevision = proposedAgentRevision;
      await json(route, {
        contract_version: "local-agent-workspace.v1",
        session_id: agentApply[1],
        path: body.path,
        revision: proposedAgentRevision,
        byte_size: new TextEncoder().encode(agentContent).byteLength,
        applied: true,
      });
      return;
    }
    const agentTransactionPreview = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/transactions$/);
    if (agentTransactionPreview && method === "POST") {
      const body = request.postDataJSON() as { changes: Array<{ operation: "edit"; path: string; content: string; expected_revision: string; line_ending: string }> };
      expect(body.changes.map((item) => item.path)).toEqual(["example.ts", "src/helper.ts"]);
      expect(body.changes.every((item) => item.operation === "edit")).toBe(true);
      const files = body.changes.map((item) => {
        const helper = item.path === "src/helper.ts";
        const before = helper ? initialHelperContent : initialAgentContent;
        const proposedRevision = helper ? proposedHelperRevision : proposedAgentRevision;
        return {
          operation: item.operation,
          path: item.path,
          expected_revision: item.expected_revision,
          proposed_revision: proposedRevision,
          line_ending: item.line_ending,
          proposed_byte_size: new TextEncoder().encode(item.content).byteLength,
          added_lines: 1,
          removed_lines: 1,
          diff: `--- a/${item.path}\n+++ b/${item.path}\n@@ -1 +1 @@\n-${before.trimEnd()}\n+${item.content.trimEnd()}`,
        };
      });
      await json(route, {
        contract_version: "local-agent-workspace-transaction.v2",
        session_id: agentTransactionPreview[1],
        plan_id: transactionPlanId,
        file_count: files.length,
        total_byte_size: files.reduce((total, item) => total + item.proposed_byte_size, 0),
        added_lines: files.length,
        removed_lines: files.length,
        files,
        expires_at: "2040-01-01T00:02:00Z",
      }, 201);
      return;
    }
    const agentTransactionApply = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/workspace\/transactions\/([a-f0-9]{32})\/apply$/);
    if (agentTransactionApply && method === "POST") {
      const body = request.postDataJSON() as { confirmation: string; changes: Array<{ operation: "edit"; path: string; content: string; proposed_revision: string }> };
      expect(agentTransactionApply[2]).toBe(transactionPlanId);
      expect(request.headers()["x-prompt-enhancer-user-presence"]).toBe("a".repeat(32));
      expect(body.confirmation).toBe("apply_reviewed_workspace_transaction");
      expect(body.changes.map((item) => item.path)).toEqual(["example.ts", "src/helper.ts"]);
      expect(body.changes.every((item) => item.operation === "edit")).toBe(true);
      for (const change of body.changes) {
        if (change.path === "src/helper.ts") {
          helperContent = change.content;
          helperRevision = proposedHelperRevision;
        } else {
          agentContent = change.content;
          agentRevision = proposedAgentRevision;
        }
      }
      await json(route, {
        contract_version: "local-agent-workspace-transaction.v2",
        session_id: agentTransactionApply[1],
        plan_id: transactionPlanId,
        state: "committed",
        reason: null,
        file_count: 2,
        files: [
          { path: "example.ts", state: "committed", revision: proposedAgentRevision, byte_size: new TextEncoder().encode(agentContent).byteLength },
          { path: "src/helper.ts", state: "committed", revision: proposedHelperRevision, byte_size: new TextEncoder().encode(helperContent).byteLength },
        ],
      });
      return;
    }
    const agentEvents = path.match(/^\/v1\/agent\/sessions\/([a-f0-9]{32})\/events\/stream$/);
    if (agentEvents && method === "GET") {
      await route.fulfill({
        body: `data: ${JSON.stringify({ contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false, session_id: agentEvents[1], events: [], running: false, pending_approval_id: null, last_seq: 0, first_seq: 0 })}\n\n`,
        headers: { "Cache-Control": "no-store, private", "Content-Type": "text/event-stream; charset=utf-8", Pragma: "no-cache" },
        status: 200,
      });
      return;
    }

    const projectSessions = path.match(/^\/v1\/projects\/([a-f0-9]{64})\/sessions$/);
    if (projectSessions && method === "GET") {
      const page = await transport.listProjectSessions(
        projectSessions[1],
        integer(url.searchParams.get("limit"), 100),
        integer(url.searchParams.get("offset"), 0),
      );
      await json(
        route,
        {
          ...page,
          sessions: page.sessions.map((session) => ({ ...session, provider: "codex" })),
        },
      );
      return;
    }

    const compatibility = path.match(/^\/v1\/providers\/([^/]+)\/compatibility$/);
    if (compatibility && method === "GET") {
      if (!transport.getProviderCompatibility) throw new Error("Synthetic compatibility fixture is unavailable");
      await json(route, await transport.getProviderCompatibility(compatibility[1] as "synthetic"));
      return;
    }
    const capabilities = path.match(/^\/v1\/providers\/([^/]+)\/capabilities$/);
    if (capabilities && method === "GET") {
      await json(route, await transport.getProviderMetricCapabilities(capabilities[1] as "synthetic"));
      return;
    }

    const readiness = path.match(/^\/v1\/sessions\/([a-f0-9]{64})\/metric-readiness$/);
    if (readiness && method === "GET") {
      await json(route, codexReadinessFixture());
      return;
    }
    const metrics = path.match(/^\/v1\/sessions\/([a-f0-9]{64})\/metrics$/);
    if (metrics && method === "GET") {
      await json(route, await transport.getSessionMetrics(metrics[1]));
      return;
    }
    const latestRun = path.match(
      /^\/v1\/sessions\/([a-f0-9]{64})\/quality-analysis-runs\/latest$/,
    );
    if (latestRun && method === "GET") {
      await json(route, await transport.getLatestSessionQualityAnalysis(latestRun[1]));
      return;
    }
    const run = path.match(/^\/v1\/quality-analysis\/runs\/([a-f0-9]{64})$/);
    if (run && method === "GET") {
      await json(route, await transport.getSessionQualityAnalysisRun(run[1]));
      return;
    }
    const coaching = path.match(
      /^\/v1\/quality-analysis\/runs\/([a-f0-9]{64})\/coaching-summary$/,
    );
    if (coaching && method === "GET") {
      if (!transport.getSessionCoachingSummary) throw new Error("Synthetic coaching fixture is unavailable");
      await json(route, await transport.getSessionCoachingSummary(coaching[1]));
      return;
    }
    if (path === "/v1/quality-analysis/aggregate" && method === "POST") {
      await json(route, await transport.aggregateSessionQuality(request.postDataJSON()));
      return;
    }
    if (path === "/v1/quality-analysis/aggregate-projects" && method === "POST") {
      await json(route, await transport.aggregateProjectQuality(request.postDataJSON()));
      return;
    }
    if (path === "/v1/analysis-jobs" && method === "GET") {
      await json(route, {
        jobs: [],
        limit: integer(url.searchParams.get("limit"), 50),
        offset: integer(url.searchParams.get("offset"), 0),
      });
      return;
    }
    if (path === "/v1/automation-grants" && method === "GET") {
      await json(route, []);
      return;
    }
    if (path === "/v1/discovery/candidates" && method === "GET") {
      await json(route, await transport.listCandidates(
        (url.searchParams.get("status") ?? "all") as "all" | "undecided" | "decided",
        undefined,
        {
          limit: integer(url.searchParams.get("limit"), 100),
          offset: integer(url.searchParams.get("offset"), 0),
        },
      ));
      return;
    }
    if (path === "/v1/task-revisions" && method === "GET") {
      await json(route, await transport.listTaskRevisions(
        url.searchParams.get("task_id") ?? undefined,
        undefined,
        {
          limit: integer(url.searchParams.get("limit"), 100),
          offset: integer(url.searchParams.get("offset"), 0),
        },
      ));
      return;
    }
    if (path === "/v1/task-lifecycles" && method === "GET") {
      await json(route, {
        lifecycles: [],
        limit: integer(url.searchParams.get("limit"), 100),
        offset: integer(url.searchParams.get("offset"), 0),
      });
      return;
    }
    if (path === "/v1/analysis/runs" && method === "GET") {
      await json(route, await transport.listAnalysisRuns(
        url.searchParams.get("task_id") ?? undefined,
        undefined,
        {
          limit: integer(url.searchParams.get("limit"), 100),
          offset: integer(url.searchParams.get("offset"), 0),
        },
      ));
      return;
    }
    const decisions = path.match(/^\/v1\/discovery\/candidates\/([a-f0-9]{64})\/decisions$/);
    if (decisions && method === "GET") {
      await json(route, await transport.getCandidateDecisions(decisions[1]));
      return;
    }

    await json(
      route,
      { detail: { code: "synthetic_fixture_route_missing" } },
      501,
    );
  });
}

test.beforeEach(async ({ page }) => {
  await installLocalHttpFixture(page);
});

for (const width of [360, 1440]) {
  for (const windowMode of [false, true]) {
    test(`workspace HTTP inspection recovery keeps draft ownership at ${width}px (${windowMode ? "dedicated" : "main"})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      let state: "incomplete" | "timeout" | "ready" | "replaced" = "incomplete";
      let edits = 0;
      const id = "a".repeat(32);
      await page.route("**/v1/agent/sessions/*/workspace/tree?*", async (route) => {
        if (state === "timeout" || state === "replaced") {
          await json(route, { detail: { code: state === "timeout" ? "workspace_inspection_timeout" : "workspace_root_changed",
            message: "EXAMPLE_PRIVATE_WORKSPACE_CANARY" } }, state === "timeout" ? 503 : 409);
          return;
        }
        await json(route, { contract_version: "local-agent-workspace.v1", session_id: id, path: ".", complete: state === "ready",
          entries: state === "ready" ? [{ path: "example.ts", name: "example.ts", kind: "file", byte_size: 24, editable_candidate: true }] : [] });
      });
      await page.route("**/v1/agent/sessions/*/workspace/previews**", async (route) => {
        edits += 1;
        await json(route, { detail: { code: "workspace_root_changed" } }, 409);
      });
      if (windowMode) {
        const summary = exampleAgentTurn({ writes: [exampleWriteReceipt({ path: "example.ts" })] });
        await page.route("**/v1/agent/sessions/*/events/stream*", async (route) => {
          const after = Number(new URL(route.request().url()).searchParams.get("after") ?? 0);
          await route.fulfill({ status: 200, headers: { ...PRIVATE_HEADERS, "Content-Type": "text/event-stream; charset=utf-8" }, body: `data: ${JSON.stringify({
            contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: id, closing: false, stopping: false, running: false,
            pending_approval_id: null, first_seq: 1, last_seq: 1,
            events: after < 1 ? [{ seq: 1, at: summary.finished_at, kind: "done", turn_id: summary.turn_id, turn_summary: summary }] : [],
          })}\n\n` });
        });
      }
      await page.goto(windowMode ? `/agent/window/${id}` : "/agent");
      if (!windowMode) {
        await page.getByRole("button", { name: "Files & review", exact: true }).click();
      }
      if (windowMode) {
        await page.getByLabel("Turn 1 details", { exact: true }).click();
        await page.getByRole("button", { name: "Open example.ts in workspace", exact: true }).click();
      }
      const workspace = page.getByRole("region", { name: "Files and reviewed changes", exact: true });
      await expect(workspace.getByText(/No entries could be shown/u)).toBeVisible();
      await expect(workspace.getByText("This folder is empty.", { exact: true })).toHaveCount(0);
      state = "timeout";
      await workspace.getByRole("button", { name: "Refresh folder", exact: true }).click();
      await expect(workspace.getByRole("alert")).toContainText("Folder inspection reached its time limit");
      state = "ready";
      await workspace.getByRole("button", { name: "Retry folder", exact: true }).click();
      await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
      const editor = workspace.getByRole("textbox", { name: "Workspace file editor", exact: true });
      await expect(editor).toHaveValue("export const value = 1;\n");
      await editor.fill("Keep this fictional HTTP draft.");
      state = "replaced";
      await workspace.getByRole("button", { name: "Refresh folder", exact: true }).click();
      await expect(workspace.getByRole("alert")).toContainText("workspace folder was moved or replaced");
      await expect(editor).toHaveValue("Keep this fictional HTTP draft.");
      await expect(editor).toBeEnabled();
      await expect(editor).toHaveAttribute("readonly", "");
      await expect(workspace.getByRole("button", { name: "Review diff", exact: true })).toBeDisabled();
      await expect(page.getByText("EXAMPLE_PRIVATE_WORKSPACE_CANARY", { exact: false })).toHaveCount(0);
      expect(edits).toBe(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    });
  }
}

for (const windowMode of [false, true]) {
  test(`accepts v4 turn receipts through HTTP and opens the bound workspace file (${windowMode ? "dedicated" : "main"})`, async ({ page }) => {
    await page.setViewportSize({ width: 920, height: 860 });
    const summary = exampleAgentTurn({ writes: [exampleWriteReceipt({ path: "example.ts" })] });
    await page.route("**/v1/agent/sessions/*/events/stream*", async (route) => {
      const after = Number(new URL(route.request().url()).searchParams.get("after") ?? 0);
      await route.fulfill({ status: 200, headers: { "Cache-Control": "no-store, private", "Content-Type": "text/event-stream; charset=utf-8", Pragma: "no-cache" }, body: `data: ${JSON.stringify({
        contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: "a".repeat(32), closing: false, stopping: false, running: false, pending_approval_id: null, first_seq: 1, last_seq: 1,
        events: after < 1 ? [{ seq: 1, at: summary.finished_at, kind: "done", turn_id: summary.turn_id, turn_summary: summary }] : [],
      })}\n\n` });
    });
    await page.goto(windowMode ? `/agent/window/${"a".repeat(32)}` : "/agent");
    const turnDetails = page.getByLabel("Turn 1 details", { exact: true });
    await turnDetails.click();
    await expect(page.getByLabel("Turn telemetry")).toContainText("Total tokens18");
    await page.getByRole("button", { name: "Open example.ts in workspace", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Workspace file editor", exact: true })).toHaveValue("export const value = 1;\n");
    await expect(page.getByRole("textbox", { name: "Workspace file editor", exact: true })).toBeFocused();
  });
}

for (const viewport of [{ width: 390, height: 844 }, { width: 800, height: 600 }]) {
  for (const path of ["/agent", `/agent/window/${"a".repeat(32)}`]) {
    test(`keeps the Agent transcript readable at ${viewport.width}px on ${path}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await installReadyAgentFixture(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "Example workspace" })).toBeVisible();
      const transcript = page.getByRole("log");
      await expect(transcript).toBeVisible();
      expect(await transcript.evaluate((element) => element.clientHeight)).toBeGreaterThanOrEqual(240);
      const composer = page.getByRole("textbox", { name: "Message to the agent" });
      await composer.scrollIntoViewIfNeeded();
      await expect(composer).toBeInViewport();
      await composer.fill("Read example.ts without changing it.");
      await expect(composer).toHaveValue("Read example.ts without changing it.");
      const dimensions = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth,
        viewport: document.documentElement.clientWidth,
      }));
      expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
    });
  }
}

for (const viewport of [{ width: 390, height: 844 }, { width: 1046, height: 912 }]) {
  test(`drafts the next Agent message and recovers the latest activity at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const alias = "example-stream-model";
    const session = exampleAgentSession({
      running: true,
      model_alias: alias,
      settings: {
        ...exampleAgentSession().settings,
        model_alias: alias,
        title: "Example streaming chat",
      },
    });
    const streamId = "c".repeat(32);
    let streamCalls = 0;
    let releaseTerminal: (() => void) | undefined;
    const at = "2040-01-01T10:00:00Z";
    const activity = [
      { seq: 1, at, kind: "user", text: "Inspect the synthetic project", attachments: [] },
      ...Array.from({ length: 24 }, (_, index) => ({ seq: index + 2, at, kind: "status", text: `Synthetic activity ${index + 1}`, attachments: [] })),
      { seq: 26, at, kind: "assistant_delta", text: "I should inspect the target first.", stream_id: streamId, stream_phase: "reasoning", attachments: [] },
      { seq: 27, at, kind: "assistant_delta", text: "Inspecting the project…", stream_id: streamId, stream_phase: "content", attachments: [] },
    ] as const;

    await page.route("**/v1/agent/sessions", (route) => json(route, [session]));
    await page.route(`**/v1/agent/sessions/${session.session_id}`, (route) => json(route, session));
    await page.route("**/v1/local-models", (route) => json(route, {
      contract_version: "local-models.v1",
      runtime_available: true,
      storage_root: "D:/example/models",
      downloads: [],
      models: [{
        record: {
          alias,
          display_name: "Example Stream Model",
          format: "gguf",
          path: "D:/example/models/example.gguf",
          context_size: 8192,
          default_device: "cpu",
          added_at: at,
          provenance_verified: false,
        },
        runtime: { state: "running", device: "cpu" },
        endpoint_path: `/v1/local-models/${alias}/chat/completions`,
      }],
      hardware: {
        gpu_name: null,
        gpu_memory_mb: null,
        gpu_memory_free_mb: null,
        ram_mb: 8192,
        llama_server_path: "D:/example/runtime/llama-server.exe",
        llama_server_version: "example-v1",
      },
    }));
    await page.route("**/v1/agent/sessions/*/events/stream*", async (route) => {
      streamCalls += 1;
      if (streamCalls === 1) {
        await route.fulfill({
          status: 200,
          headers: { ...PRIVATE_HEADERS, "Content-Type": "text/event-stream; charset=utf-8" },
          body: `data: ${JSON.stringify({
            contract_version: "local-agent.v9",
            cleanup_unconfirmed: false,
            session_id: session.session_id,
            closing: false,
            stopping: false,
            running: true,
            pending_approval_id: null,
            first_seq: 1,
            last_seq: 27,
            events: activity,
          })}\n\n`,
        });
        return;
      }
      await new Promise<void>((resolve) => { releaseTerminal = resolve; });
      await route.fulfill({
        status: 200,
        headers: { ...PRIVATE_HEADERS, "Content-Type": "text/event-stream; charset=utf-8" },
        body: `data: ${JSON.stringify({
          contract_version: "local-agent.v9",
          cleanup_unconfirmed: false,
          session_id: session.session_id,
          closing: false,
          stopping: false,
          running: false,
          pending_approval_id: null,
          first_seq: 1,
          last_seq: 28,
          events: [{ seq: 28, at, kind: "assistant", text: "Inspection complete.", reasoning: "I inspected the target first.", stream_id: streamId, stream_status: "complete", attachments: [] }],
        })}\n\n`,
      });
    });

    await page.goto("/agent");
    const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
    await expect(page.getByLabel("Agent response streaming")).toContainText("Inspecting the project");
    await expect(page.getByText("Write the next message now · Send unlocks when this response ends")).toBeVisible();
    await expect(composer).toBeEnabled();
    await composer.fill("Use this synthetic instruction on the next turn.");
    await expect(page.getByRole("button", { name: "Stop response", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send", exact: true })).toHaveCount(0);
    expect((await page.locator(".agent__reasoning > summary").boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);

    const transcript = page.getByRole("log");
    await transcript.evaluate((element) => {
      element.scrollTop = 0;
      element.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    const jump = page.getByRole("button", { name: "Jump to latest activity", exact: true });
    await expect(jump).toBeVisible();
    await jump.click();
    expect(await transcript.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight)).toBeLessThan(2);

    await expect.poll(() => Boolean(releaseTerminal)).toBe(true);
    releaseTerminal?.();
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeEnabled();
    await expect(composer).toHaveValue("Use this synthetic instruction on the next turn.");
    await expect(page.getByText("Ctrl/⌘+Enter sends · Enter adds a line")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("gives the Agent conversation priority at a medium desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1046, height: 912 });
  await page.goto("/agent");

  const shell = page.locator(".app-shell");
  await expect(shell).toHaveClass(/app-shell--agent-focus/u);
  await expect(page.locator(".sidebar")).toBeHidden();
  await expect(page.locator(".mobile-shell-header")).toBeVisible();
  const conversation = page.getByRole("region", { name: "Agent conversation" });
  await expect(conversation).toBeVisible();
  expect((await conversation.boundingBox())?.width ?? 0).toBeGreaterThan(680);

  await page.getByRole("button", { name: "Open navigation" }).click();
  const navigation = page.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("button", { name: "Agent", exact: true })).toHaveAttribute("aria-current", "page");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("filters Agent navigation without unmounting the active conversation", async ({ page }) => {
  await page.setViewportSize({ width: 1046, height: 912 });
  const projectId = "1".repeat(32);
  const sessionId = "a".repeat(32);
  const workspace = "D:\\example\\workspace";
  const project = {
    contract_version: "agent-catalog.v2" as const,
    project_id: projectId,
    name: "Example coding project",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    pinned: true,
    archived_at: null,
    session_count: 1,
    is_default: false,
  };
  const catalogSession = {
    contract_version: "agent-catalog.v2" as const,
    session_id: sessionId,
    project_id: projectId,
    title: "Example active chat",
    workspace,
    model_alias: null,
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    last_opened_at: "2040-01-01T10:01:00Z",
    revision: 2,
    pinned: false,
    archived_at: null,
    history_state: "memory_only" as const,
    retention_policy: "metadata_only" as const,
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: false,
    lineage: null,
  };
  const live = exampleAgentSession({
    session_id: sessionId,
    settings: {
      ...exampleAgentSession().settings,
      workspace,
      project_id: projectId,
      title: catalogSession.title,
      model_alias: null,
    },
    model_alias: null,
  });
  await page.route(/\/v1\/agent\/sessions$/, (route) => json(route, [live]));
  const catalogPage = (items: unknown[], key: "projects" | "sessions") => ({
    contract_version: "agent-catalog-page.v1",
    snapshot: "9".repeat(64),
    limit: 100,
    offset: 0,
    total: items.length,
    next_offset: null,
    complete: true,
    [key]: items,
  });
  await page.route(new RegExp(`/v1/agent/projects/${projectId}/sessions/page(?:\\?.*)?$`), (route) => {
    const searching = Boolean(new URL(route.request().url()).searchParams.get("search"));
    return json(route, catalogPage(searching ? [] : [catalogSession], "sessions"));
  });
  await page.route(/\/v1\/agent\/catalog\/sessions\/page(?:\?.*)?$/, (route) => {
    const searching = Boolean(new URL(route.request().url()).searchParams.get("search"));
    return json(route, catalogPage(searching ? [] : [catalogSession], "sessions"));
  });
  await page.route(/\/v1\/agent\/projects\/page(?:\?.*)?$/, (route) => {
    const searching = Boolean(new URL(route.request().url()).searchParams.get("search"));
    return json(route, catalogPage(searching ? [] : [project], "projects"));
  });

  await page.goto("/agent");
  const conversation = page.getByRole("region", { name: "Agent conversation" });
  const composer = conversation.getByRole("textbox", { name: "Message to the agent" });
  await expect(composer).toBeVisible();
  const runtimeRegion = conversation.getByRole("region", { name: "Shared local model runtime" });
  const runtimeSummary = runtimeRegion.locator(".agent-runtime__composer-disclosure > summary");
  const alwaysVisibleTouchTargets = [
    page.getByRole("button", { name: "Collapse projects and chats" }),
    page.getByRole("button", { name: "Create project" }),
    page.getByRole("button", { name: "New chat", exact: true }),
    page.getByRole("searchbox", { name: "Search projects and chats" }),
    page.getByRole("button", { name: /^Example active chat ·/ }),
    runtimeSummary,
  ];
  for (const target of alwaysVisibleTouchTargets) {
    expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  await runtimeSummary.click();
  const expandedRuntimeTouchTargets = [
    runtimeRegion.getByRole("combobox", { name: "Model", exact: true }),
    runtimeRegion.getByRole("combobox", { name: "Model placement", exact: true }),
    runtimeRegion.getByRole("combobox", { name: "Context limit", exact: true }),
    runtimeRegion.getByRole("button", { name: "Start model" }),
    runtimeRegion.getByRole("button", { name: "Stop runtime", exact: true }),
    runtimeRegion.getByRole("button", { name: "Refresh", exact: true }),
  ];
  for (const target of expandedRuntimeTouchTargets) {
    expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  await page.getByRole("searchbox", { name: "Search projects and chats" }).fill("not in this rail");
  await expect(page.getByText("No project matches this view.", { exact: false })).toBeVisible();
  await expect(page.getByText("No chat matches your search.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Example active chat" })).toBeVisible();
  await expect(composer).toBeVisible();

  await page.getByRole("button", { name: "Collapse projects and chats" }).click();
  await expect(page.getByLabel("Current project: Example coding project")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Example active chat" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

for (const width of [390, 1046]) {
  test(`keeps Files & Review workbench primary while secondary tools stay available at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 912 });
    await page.goto("/agent");

    const openFiles = page.getByRole("button", { name: "Files & review", exact: true });
    await expect(openFiles).toBeVisible();
    await openFiles.click();

    const workspace = page.getByRole("region", { name: "Files and reviewed changes", exact: true });
    const support = workspace.locator("details.agent-workspace__support");
    const supportSummary = support.locator("summary");
    const discovery = workspace.getByRole("region", { name: "Workspace discovery", exact: true });

    await expect(workspace.getByRole("button", { name: "example.ts", exact: true })).toBeVisible();
    await expect(support).not.toHaveAttribute("open", "");
    await expect(discovery).not.toBeVisible();
    expect((await supportSummary.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);

    await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
    const editor = workspace.getByRole("textbox", { name: "Workspace file editor", exact: true });
    await expect(editor).toBeEnabled();
    await expect(editor).toHaveValue("export const value = 1;\n");

    await supportSummary.click();
    await expect(support).toHaveAttribute("open", "");
    await expect(discovery).toBeVisible();
    const discoveryTargets = [
      ["file filter", discovery.getByRole("searchbox", { name: "Filter mapped files", exact: true })],
      ["content query", discovery.getByRole("searchbox", { name: "Search workspace contents", exact: true })],
      ["file pattern", discovery.getByRole("textbox", { name: "Workspace search file pattern", exact: true })],
      ["regular expression", discovery.locator(".agent-discovery__regex")],
    ] as const;
    for (const [name, target] of discoveryTargets) {
      expect((await target.boundingBox())?.height ?? 0, `${name} control height`).toBeGreaterThanOrEqual(44);
    }
    await expect(workspace).toContainText("Permanent deletion and directory removal are not available.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("keeps a reviewed workspace edit fail-closed without native user presence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 920 });
  await page.goto("/agent");

  await expect(page.getByRole("heading", { name: "Example workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Files & review", exact: true }).click();
  const workspace = page.getByRole("region", { name: "Files and reviewed changes" });
  const conversation = page.getByRole("region", { name: "Agent conversation" });
  await expect(workspace).toContainText(
    "Manual edits, new files, folders, no-overwrite moves, recoverable single-file Recycle Bin removal, and adding an exact generated output require native user-presence confirmation",
  );
  await expect(workspace).toContainText("Permanent deletion and directory removal are not available.");
  await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
  const editor = page.getByRole("textbox", { name: "Workspace file editor" });
  await expect(editor).toHaveValue("export const value = 1;\n");
  await editor.fill("export const value = 2;\n");
  await page.getByRole("button", { name: "Review diff" }).click();
  await expect(page.getByRole("region", { name: "Manual edit review" })).toContainText("+export const value = 2;");
  await expect(page.getByRole("status").filter({
    hasText: "native user-presence confirmation is unavailable",
  })).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply reviewed edit" })).toBeDisabled();
  await expect(editor).toHaveValue("export const value = 2;\n");

  const [workspaceBox, conversationBox] = await Promise.all([workspace.boundingBox(), conversation.boundingBox()]);
  expect(workspaceBox).not.toBeNull();
  expect(conversationBox).not.toBeNull();
  expect(workspaceBox!.x).toBeGreaterThan(conversationBox!.x);
  expect(conversationBox!.x + conversationBox!.width).toBeLessThanOrEqual(workspaceBox!.x + 1);

  await page.setViewportSize({ width: 420, height: 820 });
  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  await expect(editor).toBeVisible();
});

test("publishes a natively confirmed manual edit into the live reviewed change set", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 920 });
  await page.addInitScript(() => {
    Object.defineProperty(globalThis, "pywebview", {
      configurable: true,
      value: {
        api: {
          confirm_user_presence: async () => ({
            version: "native-user-presence-v1",
            approved: true,
            approval_token: "a".repeat(32),
          }),
        },
      },
    });
  });
  await page.route("**/auth/session", (route) => json(route, {
    csrf_token: "synthetic-browser-csrf-token",
    expires_in_seconds: 300,
    user_presence_confirmation_available: true,
    user_presence_confirmation_mode: "native_bridge_bound_token",
  }));
  await page.goto("/agent");

  await page.getByRole("button", { name: "Files & review", exact: true }).click();
  const workspace = page.getByRole("region", { name: "Files and reviewed changes" });
  const discovery = workspace.getByRole("region", { name: "Workspace discovery", exact: true });
  await workspace.getByText("Workspace tools & safety", { exact: true }).click();
  await expect(discovery).toContainText("Complete application-readable inventory");
  await expect(discovery).toContainText("2 files observed");
  await expect(discovery).toContainText("0 changes reported by bounded porcelain status");
  await discovery.getByRole("searchbox", { name: "Filter mapped files", exact: true }).fill("helper");
  await expect(discovery.getByText("src/helper.ts", { exact: true })).toBeVisible();
  await expect(discovery.getByText("example.ts", { exact: true })).toHaveCount(0);
  await discovery.getByRole("searchbox", { name: "Filter mapped files", exact: true }).fill("");
  await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
  const editor = workspace.getByRole("textbox", { name: "Workspace file editor" });
  await expect(editor).toHaveValue("export const value = 1;\n");
  await editor.fill("export const value = 2;\n");
  await workspace.getByRole("button", { name: "Review diff", exact: true }).click();
  await expect(workspace.getByRole("button", { name: "Apply reviewed edit", exact: true })).toBeEnabled();
  await workspace.getByRole("button", { name: "Apply reviewed edit", exact: true }).click();
  await expect(workspace.getByRole("status").filter({ hasText: "atomically published and verified" })).toBeVisible();
  await expect(discovery).toContainText("1 change reported by bounded porcelain status");
  await expect(discovery.getByRole("list", { name: "Git changes", exact: true })).toContainText("Modified");
  await expect(discovery.getByRole("list", { name: "Git changes", exact: true })).toContainText("Unstaged");

  await page.getByRole("tab", { name: "Changes", exact: true }).click();
  const changeSet = page.getByRole("region", { name: "Reviewed session change set", exact: true });
  await expect(changeSet).toContainText("Complete reviewed-path coverage");
  await expect(changeSet).toContainText("1 current change");
  await expect(changeSet).toContainText("1 reviewed write");
  await expect(changeSet).toContainText("1 manual");
  await changeSet.getByRole("button", { name: "Review net diff", exact: true }).click();
  const netDiff = page.getByRole("region", { name: "Net diff for example.ts", exact: true });
  await expect(netDiff).toContainText("-export const value = 1;");
  await expect(netDiff).toContainText("+export const value = 2;");
  const diffFigure = netDiff.getByRole("figure", { name: "Net diff for example.ts", exact: true });
  await expect(diffFigure.getByText("+1", { exact: true })).toBeVisible();
  await expect(diffFigure.getByText("−1", { exact: true })).toBeVisible();
  await expect(diffFigure.getByText("1 hunk", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

for (const width of [390, 1440]) {
  test(`creates and moves one reviewed folder, then moves and recycles its file at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 920 });
    await page.addInitScript(() => {
      Object.defineProperty(globalThis, "pywebview", {
        configurable: true,
        value: {
          api: {
            confirm_user_presence: async () => ({
              version: "native-user-presence-v1",
              approved: true,
              approval_token: "a".repeat(32),
            }),
          },
        },
      });
    });
    await page.route("**/auth/session", (route) => json(route, {
      csrf_token: "synthetic-browser-csrf-token",
      expires_in_seconds: 300,
      user_presence_confirmation_available: true,
      user_presence_confirmation_mode: "native_bridge_bound_token",
    }));
    await page.goto("/agent");

    await page.getByRole("button", { name: "Files & review", exact: true }).click();
    const workspace = page.getByRole("region", { name: "Files and reviewed changes" });
    await workspace.getByRole("button", { name: "New folder", exact: true }).click();
    await workspace.getByLabel("Workspace-relative new folder path").fill("reviewed-folder");
    await workspace.getByRole("button", { name: "Review new folder", exact: true }).click();
    const folderReview = workspace.getByRole("region", { name: "New folder review", exact: true });
    await expect(folderReview).toContainText("reviewed-folder");
    await expect(folderReview).toContainText("parent folder must already exist");
    await folderReview.getByRole("button", { name: "Create reviewed folder", exact: true }).click();
    await expect(workspace.getByRole("status").filter({ hasText: "Created and verified folder reviewed-folder" })).toBeVisible();

    await workspace.getByRole("button", { name: "New file", exact: true }).click();
    await workspace.getByLabel("Workspace-relative new file path").fill("reviewed-folder/created.ts");
    await workspace.getByLabel("New file content").fill("export const created = true;\n");
    await workspace.getByRole("button", { name: "Review new file", exact: true }).click();
    const createReview = workspace.getByRole("region", { name: "New file review", exact: true });
    await expect(createReview).toContainText("--- /dev/null");
    await expect(createReview).toContainText("+++ b/reviewed-folder/created.ts");
    await createReview.getByRole("button", { name: "Create reviewed file", exact: true }).click();
    await expect(workspace.getByRole("status").filter({ hasText: "Created and verified reviewed-folder/created.ts" })).toBeVisible();
    const editor = workspace.getByRole("textbox", { name: "Workspace file editor", exact: true });
    await expect(editor).toHaveValue("export const created = true;\n");

    await workspace.getByRole("button", { name: "Move folder", exact: true }).click();
    await workspace.getByLabel("New workspace-relative folder path").fill("archive/reviewed-folder");
    await workspace.getByRole("button", { name: "Review folder move", exact: true }).click();
    const directoryMoveReview = workspace.getByRole("region", { name: "Folder move review", exact: true });
    await expect(directoryMoveReview).toContainText("reviewed-folder");
    await expect(directoryMoveReview).toContainText("archive/reviewed-folder");
    await expect(directoryMoveReview).toContainText("Contents reviewed");
    await expect(directoryMoveReview).toContainText("not enumerated");
    await directoryMoveReview.getByRole("button", { name: "Move reviewed folder", exact: true }).click();
    await expect(workspace.getByRole("status").filter({ hasText: "Moved and verified folder reviewed-folder to archive/reviewed-folder" })).toBeVisible();
    await expect(editor).toBeDisabled();
    await workspace.getByRole("button", { name: "created.ts", exact: true }).click();
    await expect(editor).toHaveValue("export const created = true;\n");

    await workspace.getByRole("button", { name: "Rename or move", exact: true }).click();
    await workspace.getByLabel("New workspace-relative path").fill("src/created.ts");
    await workspace.getByRole("button", { name: "Review move", exact: true }).click();
    const moveReview = workspace.getByRole("region", { name: "File move review", exact: true });
    await expect(moveReview).toContainText("archive/reviewed-folder/created.ts");
    await expect(moveReview).toContainText("src/created.ts");
    await moveReview.getByRole("button", { name: "Apply reviewed move", exact: true }).click();
    await expect(workspace.getByRole("status").filter({ hasText: "Moved and verified archive/reviewed-folder/created.ts → src/created.ts" })).toBeVisible();
    await expect(editor).toHaveValue("export const created = true;\n");
    await expect(workspace.getByRole("button", { name: "created.ts", exact: true })).toBeVisible();

    await workspace.getByRole("button", { name: "Move to Recycle Bin", exact: true }).click();
    const trashOperation = workspace.getByRole("region", { name: "Move workspace file to Recycle Bin", exact: true });
    await expect(trashOperation).toContainText("Permanent deletion");
    await expect(trashOperation).toContainText("No");
    await trashOperation.getByRole("button", { name: "Review Recycle Bin move", exact: true }).click();
    const trashReview = workspace.getByRole("region", { name: "Recycle Bin review", exact: true });
    await expect(trashReview).toContainText("src/created.ts");
    await expect(trashReview).toContainText("Windows Recycle Bin");
    await trashReview.getByRole("button", { name: "Move reviewed file to Recycle Bin", exact: true }).click();
    await expect(workspace.getByRole("status").filter({ hasText: "Permanent deletion was not used" })).toBeVisible();
    await expect(workspace.getByText("No file open", { exact: true })).toBeVisible();
    await expect(workspace.getByRole("button", { name: "created.ts", exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

for (const width of [390, 1440]) {
  test(`reviews and commits a natively confirmed two-file transaction at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 920 });
    await page.addInitScript(() => {
      Object.defineProperty(globalThis, "pywebview", {
        configurable: true,
        value: {
          api: {
            confirm_user_presence: async () => ({
              version: "native-user-presence-v1",
              approved: true,
              approval_token: "a".repeat(32),
            }),
          },
        },
      });
    });
    await page.route("**/auth/session", (route) => json(route, {
      csrf_token: "synthetic-browser-csrf-token",
      expires_in_seconds: 300,
      user_presence_confirmation_available: true,
      user_presence_confirmation_mode: "native_bridge_bound_token",
    }));
    await page.goto("/agent");

    await page.getByRole("button", { name: "Files & review", exact: true }).click();
    const workspace = page.getByRole("region", { name: "Files and reviewed changes" });
    const editor = workspace.getByRole("textbox", { name: "Workspace file editor" });
    await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
    await expect(editor).toHaveValue("export const value = 1;\n");
    await editor.fill("export const value = 2;\n");
    await workspace.getByRole("button", { name: "Stage for multi-file edit", exact: true }).click();
    await expect(workspace.getByRole("button", { name: "Open staged file example.ts", exact: true })).toBeVisible();

    await workspace.getByRole("button", { name: "src", exact: true }).click();
    await workspace.getByRole("button", { name: "helper.ts", exact: true }).click();
    await expect(editor).toHaveValue("export const helper = 1;\n");
    await editor.fill("export const helper = 2;\n");
    await workspace.getByRole("button", { name: "Stage for multi-file edit", exact: true }).click();
    await workspace.getByRole("button", { name: "Review 2-file transaction", exact: true }).click();

    const review = workspace.getByRole("region", { name: "Multi-file transaction review", exact: true });
    await expect(review).toContainText("2 files · 0 create · 2 edit · 2 additions · 2 removals");
    await expect(review.locator("summary")).toHaveCount(2);
    await expect(review.locator("summary").nth(0)).toContainText("example.ts");
    await expect(review.locator("summary").nth(1)).toContainText("src/helper.ts");
    await review.getByRole("button", { name: "Apply 2-file transaction", exact: true }).click();

    await expect(workspace.getByRole("status").filter({ hasText: "Committed and verified 2 reviewed files" })).toBeVisible();
    await expect(editor).toHaveValue("export const helper = 2;\n");
    await expect(workspace.getByRole("button", { name: "Open staged file example.ts", exact: true })).toHaveCount(0);
    await workspace.getByRole("button", { name: "Up", exact: true }).click();
    await workspace.getByRole("button", { name: "example.ts", exact: true }).click();
    await expect(editor).toHaveValue("export const value = 2;\n");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("checks and improves an agent draft through the local Prompt Check endpoint without sending it", async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 820 });
  await installReadyAgentFixture(page);
  await page.goto("/agent");

  const draft = page.getByRole("textbox", { name: "Message to the agent" });
  await draft.fill("Update example.ts");
  await page.getByRole("button", { name: "Review prompt without sending" }).click();

  await expect(page.getByRole("heading", { name: "Before the agent acts" })).toBeVisible();
  await expect(page.getByText("a checkable pass condition")).toBeVisible();
  await expect(page.getByText(/Name the focused test command/)).toBeVisible();
  await expect(page.getByText(/model output, not measured evidence/)).toBeVisible();

  await page.getByRole("button", { name: "Use suggested prompt" }).click();
  await expect(draft).toHaveValue("Update example.ts, run the focused test, and report the changed files and result.");
  await expect(page.getByRole("heading", { name: "Before the agent acts" })).toHaveCount(0);
  await expect(page.getByText(/Check it again to validate/)).toBeVisible();
  await expect(page.getByText("Update example.ts", { exact: true })).toHaveCount(0);

  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
});

test("keeps the canonical metric workspace truthful when the bounded source is unavailable", async ({ page }) => {
  await page.goto(
    `/projects/${SYNTHETIC_QUALITY_PROJECT_ID}/sessions/${SYNTHETIC_QUALITY_SESSION_ID}/metrics/prompt-quality`,
  );

  await expect(
    page.getByLabel("Runtime status: Local loopback service available", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Measure the analyzed window, then estimate every eligible axis locally",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({
      hasText: "This installation cannot read the selected session through the bounded adapter.",
    }),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /metric radar/i })).toHaveCount(0);
  await expect(page.getByText(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id)).toHaveCount(0);
});

test("keeps local job state truthful and responsive", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 820 });
  await page.goto("/analysis-jobs");

  await expect(page.getByRole("heading", { name: "Analysis jobs" })).toBeVisible();
  await expect(
    page.getByText("No durable jobs match this filter. Missing jobs are not treated as completed work."),
  ).toBeVisible();
  await expect(page.getByText(/Local real .* SQLite queue .* one local worker/)).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
});

test("fails the social hub closed with exact zero local-real state", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 820 });
  await page.goto("/social");

  await expect(page.getByRole("heading", { name: "Social hub" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Social features are not served in this runtime" })).toContainText(
    "0 friends · 0 relationships · 0 requests · 0 conversations · 0 messages · 0 file offers · presence not shared",
  );
  await expect(page.getByRole("note", { name: "Fictional synthetic demo" })).toHaveCount(0);
  await expect(page.getByRole("form", { name: /Message|Offer a file/ })).toHaveCount(0);
  await expect(page.locator("input[type='file']")).toHaveCount(0);
});

test("keeps local task records local-only without inferring work lifecycle", async ({ page }) => {
  await page.setViewportSize({ width: 620, height: 900 });
  await page.goto("/tasks/flow");

  await expect(page.getByRole("heading", { name: "Task flow" })).toBeVisible();
  const summary = page.getByRole("region", { name: "Task flow compact summary" });
  await expect(summary.getByText("Work state Unknown", { exact: true }).locator(".."))
    .toContainText("0");
  await expect(summary.getByText("Backlog", { exact: true }).locator(".."))
    .toContainText("0");
  await expect(summary.getByText("In progress", { exact: true }).locator(".."))
    .toContainText("0");
  await expect(summary.getByText("Done", { exact: true }).locator(".."))
    .toContainText("0");
  await expect(summary.getByText("Historical / unreconciled", { exact: true }).locator(".."))
    .toContainText("0 / 1");
  await expect(summary).toContainText("0 team-sourced records · 0 remote-synced records");
  await expect(page.getByText("Local · this installation only")).toBeVisible();
  await expect(page.getByRole("note", { name: "Fictional synthetic demo" })).toHaveCount(0);
  const unreconciled = page.getByRole("region", { name: "State not reconciled" });
  await expect(unreconciled).toContainText("No backlog, in-progress, or done state is fabricated");
  await expect(unreconciled.getByText("Unknown", { exact: true })).toHaveCount(2);
});

test("renders the server-bound all-twenty operability gate without a session read", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto("/research/methods");

  await expect(page.getByLabel("Runtime status: Local loopback service available", { exact: true })).toHaveAttribute(
    "data-service-state",
    "available",
  );
  await expect(page.getByRole("heading", {
    name: "What can produce measured evidence today",
  })).toBeVisible();
  const summary = page.getByLabel("Metric operability summary");
  await expect(summary.getByText("Measured paths shipped").locator("..")).toContainText("16");
  await expect(summary.getByText("Need project profile").locator("..")).toContainText("0");
  await expect(summary.getByText("Need source adapter").locator("..")).toContainText("4");
  await expect(summary.getByText("Model-authored metrics").locator("..")).toContainText("0");
  await expect(page.locator("[data-operability-state]")).toHaveCount(20);
});

test("requires an exact local project grant before background scheduling", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto(`/projects/${SYNTHETIC_QUALITY_PROJECT_ID}/automation`);

  await expect(page.getByRole("heading", { name: "Project automation" })).toBeVisible();
  await expect(page.getByText("Remote execution is never unattended")).toBeVisible();
  await expect(page.getByText("Consent active", { exact: true })).toBeVisible();
  await expect(page.getByText("Project indexed", { exact: true })).toBeVisible();
  await expect(page.getByText("Readiness verified", { exact: true })).toBeVisible();
  await expect(page.getByText("No grant exists for this project")).toBeVisible();

  const create = page.getByRole("button", { name: "Create 30-day local grant" });
  await expect(create).toBeDisabled();
  await page.getByRole("button", { name: "Select attemptable" }).click();
  await page.getByRole("checkbox", {
    name: /I authorize this local service to schedule selected metrics/,
  }).check();
  await expect(create).toBeEnabled();
  await expect(page.getByText("Every 15 minutes while the service runs")).toBeVisible();
  await expect(page.getByText("30 days, then renew explicitly")).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
});
