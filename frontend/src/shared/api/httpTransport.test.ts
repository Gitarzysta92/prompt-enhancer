import { describe, expect, it, vi } from "vitest";
import { exampleAgentSession } from "./agentSession.test-support";
import { exampleAgentOrchestrationManifest } from "./agentOrchestrationFixtures.test-support";
import type {
  AgentArtifactVersion,
  AgentSettings,
  AnalysisJobState,
  AutomationGrantRecord,
  AutomationGrantScope,
  ModelCompatibilityCatalog,
  ModelRuntimeInventory,
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisRequest,
} from "./contracts";
import {
  assertSameOriginRelativePath,
  createHttpTransport,
  parseAnalysisJobPage,
  parseAnalysisJobRecord,
  parseAutomationGrantList,
  parseAutomationGrantRecord,
  parseAutomationPollResult,
  parseMetricCoverageReport,
  parseProviderCapabilityReport,
  parseProviderCompatibilityStatus,
  parseRuntimeHealth,
  parseSessionAnalysisRunResponse,
  parseSessionMetricReadinessReport,
  parseSessionQualityAnalysisPreview,
  parseSessionTextAnalysisCapability,
  parseWorkspaceFolderPick,
  parseWorkspaceFolderPickerCapability,
  TransportError,
} from "./httpTransport";
import {
  SYNTHETIC_MODEL_LINK_EXPERIMENT,
  SYNTHETIC_MODEL_LINK_OUTCOME,
  SYNTHETIC_METRIC_COVERAGE,
  SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
  SYNTHETIC_SESSION_METRIC_READINESS,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "./syntheticFixtures";
import { SYNTHETIC_TEXT_ANALYSIS_RESEARCH } from "./syntheticResearchFixture";
import { createSyntheticTransport } from "./syntheticTransport";
import {
  deriveModelCompatibilityDisposition,
  FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS,
  ModelCompatibilityPayloadError,
  parseModelCompatibilityCatalog,
} from "./modelCompatibilityContract";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function privateJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store, private",
      Pragma: "no-cache",
    },
  });
}

const AUTH_RESPONSE = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: true,
  user_presence_confirmation_mode: "native_bridge_bound_token",
} as const;
const USER_PRESENCE_TOKEN = "u".repeat(48);
const AGENT_SETTINGS: AgentSettings = {
  workspace: "D:\\example\\workspace",
  project_id: "b".repeat(32),
  model_alias: "synthetic-model",
  parameters: {
    temperature: 0.2,
    top_p: 0.95,
    max_tokens: 1400,
    enable_thinking: false,
  },
  instructions: null,
  allow_writes: false,
  allow_commands: false,
  allow_web: false,
  max_steps: 10,
  command_timeout_seconds: 120,
  title: null,
  retention_policy: "metadata_only",
};
const AGENT_PROJECT_ID = "1".repeat(32);
const AGENT_CATALOG_SESSION_ID = "2".repeat(32);
const AGENT_ARTIFACT_ID = "3".repeat(32);
const AGENT_ARTIFACT_VERSION_ID = "4".repeat(32);
const AGENT_ATTACHMENT_ID = "5".repeat(32);

function agentProject(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-catalog.v2",
    project_id: AGENT_PROJECT_ID,
    name: "Example project",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    pinned: false,
    archived_at: null,
    session_count: 1,
    is_default: false,
    ...overrides,
  };
}

function agentCatalogSession(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-catalog.v2",
    session_id: AGENT_CATALOG_SESSION_ID,
    project_id: AGENT_PROJECT_ID,
    title: "Example chat",
    workspace: "D:\\example\\workspace",
    model_alias: "example-model",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    last_opened_at: "2040-01-01T10:00:00Z",
    revision: 2,
    pinned: true,
    archived_at: null,
    history_state: "memory_only",
    retention_policy: "metadata_only",
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: false,
    lineage: null,
    ...overrides,
  };
}

function agentArtifactVersion(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-artifact.v3",
    version_id: AGENT_ARTIFACT_VERSION_ID,
    artifact_id: AGENT_ARTIFACT_ID,
    version_number: 1,
    created_at: "2040-01-01T10:01:00Z",
    path: "docs/example.md",
    media_type: "text/markdown; charset=utf-8",
    preview_kind: "text",
    provenance: "verified_output",
    sha256: "5".repeat(64),
    byte_size: 27,
    source_turn_id: null,
    source_event_seq: null,
    ...overrides,
  };
}

function agentArtifact(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: AGENT_ARTIFACT_ID,
    project_id: AGENT_PROJECT_ID,
    session_id: AGENT_CATALOG_SESSION_ID,
    title: "example.md",
    kind: "markdown",
    path: "docs/example.md",
    created_at: "2040-01-01T10:01:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 1,
    version_count: 1,
    availability: "available",
    lifecycle_state: "active",
    archived_at: null,
    removed_at: null,
    latest_version: agentArtifactVersion(),
    ...overrides,
  };
}

function agentArtifactExport(overrides: Record<string, unknown> = {}) {
  const selected = agentArtifactVersion();
  return {
    contract_version: "agent-artifact-export.v1",
    exported_at: "2040-01-01T10:04:00Z",
    artifact: { ...agentArtifact(), versions: [selected] },
    selected_version: selected,
    evidence: {
      verification: "exact_current_workspace_readback",
      algorithm: "sha256",
      sha256: selected.sha256,
      byte_size: selected.byte_size,
      verified: true,
    },
    content_included: false,
    absolute_path_included: false,
    sensitivity: "sensitive_local_metadata",
    ...overrides,
  };
}

function agentAttachment(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-attachment.v2",
    attachment_id: AGENT_ATTACHMENT_ID,
    session_id: AGENT_CATALOG_SESSION_ID,
    display_name: "example.png",
    kind: "image",
    media_type: "image/png",
    byte_size: 3,
    sha256: "6".repeat(64),
    width: 1,
    height: 1,
    duration_ms: null,
    sample_rate_hz: null,
    channels: null,
    routing: "native_multimodal",
    document_format: null,
    projected_characters: null,
    projection_truncated: null,
    omitted_features: [],
    context_tokens: null,
    context_cost_source: "runtime_unreported",
    model_alias: "example-model",
    capability_probe_version: "local-runtime-multimodal-probe.v2",
    source: "file",
    retention: "memory_only",
    state: "staged",
    created_at: "2040-01-01T10:00:00Z",
    expires_at: "2040-01-01T11:00:00Z",
    attached_event_seq: null,
    ...overrides,
  };
}

function privateArtifactResponse(body: BodyInit, contentType = "text/plain; charset=utf-8") {
  const byteSize = typeof body === "string" ? new TextEncoder().encode(body).length : 27;
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(byteSize),
      "Content-Disposition": `inline; filename="agent-artifact-${AGENT_ARTIFACT_ID.slice(0, 8)}"`,
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store, private",
      Pragma: "no-cache",
      "Content-Security-Policy": "default-src 'none'; sandbox",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function localRuntime(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision: 4,
    state: "ready",
    requested: { alias: "example-model", device: "split", gpu_layers: 20, context_size: 8192 },
    served: {
      alias: "example-model", device: "split", gpu_layers: 20, context_size: 8192,
      started_at: "2040-01-01T10:00:00Z", pid: 1234,
    },
    cleanup: {
      state: "not_required", process_exit_confirmed: true,
      gpu_memory_free_before_mb: null, gpu_memory_free_after_mb: null,
      gpu_memory_released_mb: null,
    },
    capabilities: {
      state: "verified", probe_version: "local-runtime-multimodal-probe.v2",
      text: true, tools: true, vision: false, audio: false, recording: false,
      structured_output: false, error_code: null,
    },
    context: {
      state: "unknown", used_tokens: null, limit_tokens: 8192,
      requested_output_tokens: null, available_output_tokens: null,
      source: "runtime_limit_only", scope: "runtime_limit", policy: "runtime_enforced",
      compacted_messages: 0, reason_code: "no_request_measured",
    },
    active_requests: 0,
    last_error_code: null,
    ...overrides,
  };
}

async function sha256(value: string): Promise<string> {
  const digest = new Uint8Array(
    await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
  );
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
const CONTROL_PLANE_READINESS_RESPONSE = {
  contract_version: "control-plane-v2",
  delivery_guarantee: "at_least_once_with_monotonic_ack",
  gaps: [
    "backup_and_replica_erasure_not_implemented",
    "billing_not_implemented",
    "credential_lifecycle_incomplete",
    "disclosure_control_unreviewed",
    "durable_recipient_delivery_not_implemented",
    "governance_review_pending",
    "out_of_band_provisioning_only",
    "producer_pipeline_not_connected",
    "production_database_adapter_missing",
    "production_identity_provider_missing",
    "production_signature_algorithm_missing",
    "remote_transport_not_implemented",
  ],
  production_ready: false,
  profile: "development",
  remote_listening_enabled: false,
} as const;
const CONTENT_FREE_ANALYSIS_REQUEST: SessionQualityAnalysisRequest = {
  confirmation: "analyze_selected_redacted_text",
  preset_id: "coaching_profile_v1",
};

function qualityRunResponse() {
  return structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
}

function redactionPreview(
  sessionId = "5".repeat(64),
): SessionQualityAnalysisPreview {
  const text = "Synthetic redacted request for transport validation.";
  return {
    preview_id: "e".repeat(64),
    created_at: "2040-01-01T10:00:00Z",
    expires_at: "2040-01-01T10:10:00Z",
    binding: {
      provider: "codex",
      session_id: sessionId,
      analysis_window_fingerprint: "a".repeat(64),
      metric_keys: SYNTHETIC_SESSION_METRIC_READINESS.metrics.map(
        (metric) => metric.metric_key,
      ),
      destination: "local",
      exact_model: "none",
      estimator_plan_version: "example-plan-1",
      redactor_version: "example-redactor-1",
      retention_class: "local_ephemeral",
      message_count: 1,
      character_count: Array.from(text).length,
      cost_state: "not_applicable",
      estimated_cost_microunits: null,
      cost_currency: null,
    },
    messages: [{ role: "user", kind: "request", language: "en", text }],
  };
}

function analysisJobPayload(
  state: AnalysisJobState = "queued",
  overrides: Record<string, unknown> = {},
) {
  const terminal = ["completed", "partial", "failed", "cancelled", "superseded"]
    .includes(state);
  return {
    job_id: "1".repeat(64),
    identity: {
      kind: "session_quality",
      provider: "codex",
      project_id: "3".repeat(64),
      session_id: "4".repeat(64),
      input_fingerprint: "5".repeat(64),
      provenance_fingerprint: "6".repeat(64),
      metric_keys: ["logic.decomposition_coverage", "prompt.goal_definition"],
      estimator_plan_version: "example-plan-1",
      redactor_version: "example-redactor-1",
      provider_schema_version: "example-schema-1",
      automation_grant_id: null,
      local_only: true,
    },
    state,
    stage_number: state === "stage_n" ? 2 : null,
    progress_completed: state === "completed" ? 2 : 1,
    progress_total: 2,
    attempt_count: state === "preprocessing" || state === "stage_n" ? 1 : 0,
    max_attempts: 3,
    available_at: "2040-01-01T10:00:00Z",
    cancel_requested: false,
    last_error_code: null,
    terminal_reason_code: terminal ? state : null,
    created_at: "2040-01-01T09:00:00Z",
    updated_at: "2040-01-01T10:00:00Z",
    terminal_at: terminal ? "2040-01-01T10:00:00Z" : null,
    ...overrides,
  };
}

function automationScope(
  overrides: Partial<AutomationGrantScope> = {},
): AutomationGrantScope {
  return {
    provider: "codex",
    project_id: "3".repeat(64),
    metric_keys: ["logic.decomposition_coverage", "prompt.context_sufficiency"],
    newest_session_limit: 20,
    check_interval_seconds: 900,
    resource_policy: {
      route: "balanced",
      max_gpu_workers: 1,
      max_cpu_workers: 1,
      pause_on_battery: true,
      maximum_session_seconds: 1_800,
    },
    local_only: true,
    remote_requires_fresh_approval: true,
    ...overrides,
  };
}

function automationGrantPayload(
  state: AutomationGrantRecord["state"] = "active",
  overrides: Record<string, unknown> = {},
) {
  return {
    grant_id: "9".repeat(64),
    revision: 1,
    scope: automationScope(),
    state,
    created_at: "2040-01-01T09:00:00Z",
    renewed_at: "2040-01-01T09:00:00Z",
    expires_at: "2040-01-31T09:00:00Z",
    next_check_at: "2040-01-01T09:15:00Z",
    last_checked_at: null,
    revoked_at: state === "revoked" ? "2040-01-02T09:00:00Z" : null,
    last_error_code: null,
    ...overrides,
  };
}
const PROVIDER_COMPATIBILITY = {
  provider: "codex",
  capability: "session_text_analysis",
  state: "exact",
  capability_state: "supported",
  provider_family: "codex_app_server",
  provider_version: "1.2.3",
  adapter_family: "codex_app_server",
  adapter_version: "2.0.0",
  source_schema_family: "codex_thread",
  source_schema_version: "1",
  content_schema_family: "codex_thread_items",
  content_schema_version: "1",
  reason_code: "exact_match",
  checked_at: "2040-01-01T10:00:00Z",
  update_support: "unsupported",
  update_target: null,
} as const;

describe("same-origin HTTP transport", () => {
  it("strictly accepts canonical exact and legacy-unknown quality run scopes", () => {
    const exact = qualityRunResponse();
    expect(parseSessionAnalysisRunResponse(exact, {
      sessionId: exact.run.session_id,
      runId: exact.run.run_id,
    })).toEqual(exact);

    const legacy = qualityRunResponse();
    legacy.run.metric_scope_state = "legacy_unknown";
    legacy.run.selected_metric_keys = [];
    legacy.results = [];
    expect(parseSessionAnalysisRunResponse(legacy)).toEqual(legacy);

    const legacyMultiVersion = qualityRunResponse();
    legacyMultiVersion.run.metric_scope_state = "legacy_unknown";
    legacyMultiVersion.run.selected_metric_keys = [];
    legacyMultiVersion.results = [
      legacyMultiVersion.results[0],
      { ...legacyMultiVersion.results[0], version: 2 },
    ];
    expect(parseSessionAnalysisRunResponse(legacyMultiVersion)).toEqual(
      legacyMultiVersion,
    );
  });

  it("rejects unbound or noncanonical quality run scope responses", () => {
    const malformed: unknown[] = [
      (() => {
        const value = qualityRunResponse() as unknown as { run: Record<string, unknown> };
        delete value.run.metric_scope_state;
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.selected_metric_keys = [...value.run.selected_metric_keys].reverse();
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.selected_metric_keys = [
          value.run.selected_metric_keys[0],
          value.run.selected_metric_keys[0],
        ];
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.selected_metric_keys = Array.from(
          { length: 101 },
          (_, index) => `metric.synthetic_${index.toString().padStart(3, "0")}`,
        );
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.selected_metric_keys = ["private metric key"];
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.results.pop();
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.metric_scope_state = "legacy_unknown";
        value.run.selected_metric_keys = [];
        value.results = [value.results[0], structuredClone(value.results[0])];
        return value;
      })(),
      (() => {
        const value = qualityRunResponse();
        value.run.metric_scope_state = "legacy_unknown";
        return value;
      })(),
    ];

    malformed.forEach((value) => {
      expect(() => parseSessionAnalysisRunResponse(value)).toThrow(
        new TransportError("Quality analysis response was invalid", 200),
      );
    });
    const exact = qualityRunResponse();
    expect(() => parseSessionAnalysisRunResponse(exact, {
      sessionId: "f".repeat(64),
    })).toThrow(new TransportError("Quality analysis response was invalid", 200));
    expect(() => parseSessionAnalysisRunResponse(exact, {
      runId: "e".repeat(64),
    })).toThrow(new TransportError("Quality analysis response was invalid", 200));
  });

  it("checks the actual minimal health route without bootstrapping a session", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        cost_mode: "offline_only",
        data_tier: "metadata",
      }),
    );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getRuntimeHealth()).resolves.toEqual({
      status: "ok",
      costMode: "offline_only",
      dataTier: "metadata",
    });
    expect(transport.runtimeKind).toBe("local_loopback");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/health",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
        redirect: "error",
        referrerPolicy: "no-referrer",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("rejects non-minimal or non-local runtime health payloads", () => {
    expect(() =>
      parseRuntimeHealth({
        status: "ok",
        cost_mode: "offline_only",
        data_tier: "metadata",
        remote_approved: true,
      }),
    ).toThrow(/health response was invalid/i);
    expect(() =>
      parseRuntimeHealth({
        status: "ok",
        cost_mode: "metered",
        data_tier: "remote_redacted",
      }),
    ).toThrow(/health response was invalid/i);
  });

  it("fails the health check on an HTTP or content-type error", async () => {
    const unavailable = createHttpTransport({
      fetch: vi.fn().mockResolvedValueOnce(jsonResponse({}, 503)) as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const wrongType = createHttpTransport({
      fetch: vi.fn().mockResolvedValueOnce(
        new Response("ok", {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        }),
      ) as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(unavailable.getRuntimeHealth()).rejects.toMatchObject({
      status: 503,
    });
    await expect(wrongType.getRuntimeHealth()).rejects.toMatchObject({
      status: 200,
    });
  });

  it("runs, reads, and annotates the selected-session model experiment through exact local routes", async () => {
    const annotation = {
      link_id: "b".repeat(64),
      revision: 1,
      label: "relevant",
      annotated_at: "2040-01-03T09:02:00Z",
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_MODEL_LINK_OUTCOME))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_MODEL_LINK_EXPERIMENT))
      .mockResolvedValueOnce(jsonResponse(annotation));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const sessionId = "5".repeat(64);
    const runId = "a".repeat(64);
    const linkId = "b".repeat(64);

    await transport.startModelLinkExperiment(
      sessionId,
      {
        confirmation: "compare_selected_redacted_text_with_local_models",
        device: "auto",
      },
      "dashboard-model-link-experiment-example",
    );
    await transport.getLatestModelLinkExperiment(sessionId);
    await transport.annotateModelLink(runId, linkId, {
      label: "relevant",
      expected_revision: 0,
    });

    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/sessions/${sessionId}/model-link-experiments`,
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          confirmation: "compare_selected_redacted_text_with_local_models",
          device: "auto",
        }),
        headers: expect.objectContaining({
          "Idempotency-Key": "dashboard-model-link-experiment-example",
          "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
        }),
      }),
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/sessions/${sessionId}/model-link-experiments/latest`,
    );
    expect(fetchMock.mock.calls[3][0]).toBe(
      `/v1/model-link-experiments/${runId}/links/${linkId}/annotations`,
    );
  });

  it("projects only allowlisted model-experiment failure codes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "local_model_execution_failed",
              message: "SYNTHETIC_PRIVATE_CANARY",
            },
          },
          503,
        ),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport
      .startModelLinkExperiment(
        "5".repeat(64),
        {
          confirmation: "compare_selected_redacted_text_with_local_models",
          device: "auto",
        },
        "dashboard-model-link-experiment-example",
      )
      .catch((value: unknown) => value);

    expect(error).toMatchObject({
      status: 503,
      reasonCode: "local_model_execution_failed",
    });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it("preserves the fixed model-cleanup reason without exposing server error text", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: {
        code: "model_ensemble_cleanup_unconfirmed", message: "SYNTHETIC_PRIVATE_CANARY",
      } }, 503));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport.startModelEnsemble("a".repeat(64), {
      confirmation: "run_local_metric_cascade_on_selected_redacted_text",
    }, "example-cleanup-error").catch((value: unknown) => value);
    expect(error).toMatchObject({ status: 503, reasonCode: "model_ensemble_cleanup_unconfirmed" });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reads the content-free research catalog without a mutation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_TEXT_ANALYSIS_RESEARCH));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getTextAnalysisResearch?.()).resolves.toEqual(
      SYNTHETIC_TEXT_ANALYSIS_RESEARCH,
    );
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/research/text-analysis-methods");
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("validates the private all-twenty metric operability catalog", async () => {
    const payload = await createSyntheticTransport().getMetricOperabilityCatalog!();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(payload));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getMetricOperabilityCatalog?.()).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/metric-contracts/v2/operability-catalog",
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "GET" }));
    expect(fetchMock.mock.calls[1][1]?.headers).not.toEqual(
      expect.objectContaining({ "X-Prompt-Enhancer-CSRF": expect.anything() }),
    );
  });

  it("rejects a forged metric operability partition without exposing the response", async () => {
    const payload = await createSyntheticTransport().getMetricOperabilityCatalog!();
    const forged = {
      ...payload,
      shipped_path_count: 20,
      private_detail: "SYNTHETIC_PRIVATE_CANARY",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(forged));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.getMetricOperabilityCatalog?.().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(TransportError);
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it.each([
    "claude_home_invalid",
    "claude_home_override_unsupported",
    "claude_code_not_installed",
    "codex_not_installed",
  ] as const)("projects the fixed onboarding failure code %s without forwarding detail", async (code) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code,
          message: "SYNTHETIC_PRIVATE_ONBOARDING_CANARY",
        },
      }, 422));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.acceptOnboarding({
      providers: ["claude_code"],
      claude_home: "D:/example/claude-home",
    }).catch((value: unknown) => value);

    expect(error).toMatchObject({ status: 422, reasonCode: code });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_ONBOARDING_CANARY");
  });

  it("discards an arbitrary onboarding failure code and its detail", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "SYNTHETIC_PRIVATE_ONBOARDING_CODE",
          message: "SYNTHETIC_PRIVATE_ONBOARDING_CANARY",
        },
      }, 422));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.acceptOnboarding({
      providers: ["claude_code"],
      claude_home: "D:/example/claude-home",
    }).catch((value: unknown) => value);

    expect(error).toMatchObject({ status: 422, reasonCode: null });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_ONBOARDING");
  });

  it("validates and reads the private model compatibility catalog with GET", async () => {
    const payload = await createSyntheticTransport().getTextModelCompatibility!();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(payload));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getTextModelCompatibility?.()).resolves.toEqual(payload);
    expect(payload.models.map((entry) => entry.configuration_key)).toEqual(
      FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS.map(
        (entry) => entry.configuration_key,
      ),
    );
    expect(Object.isFrozen(FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS)).toBe(true);
    expect(
      FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS.every(Object.isFrozen),
    ).toBe(true);
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/research/text-model-compatibility");
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "GET" }));
    expect(fetchMock.mock.calls[1][1]?.headers).not.toEqual(
      expect.objectContaining({ "X-Prompt-Enhancer-CSRF": expect.anything() }),
    );
  });

  it("fails closed on extra fields and contradictory compatibility inventory", async () => {
    const payload = await createSyntheticTransport().getTextModelCompatibility!();
    const extraField = {
      ...payload,
      inventory: {
        ...payload.inventory,
        hostname: "SYNTHETIC_PRIVATE_CANARY",
      },
    };
    const contradictory = {
      ...payload,
      inventory: {
        ...payload.inventory,
        preferred_device: "cpu",
        cuda_state: "unknown",
        cuda_available: false,
        cuda_vram_bucket: null,
        cuda_capability_bucket: null,
        discovery_reason_codes: ["cuda_inventory_unknown"],
      },
    };
    const falsifiedNf4Provenance = {
      ...payload,
      models: payload.models.map((entry) =>
        entry.quantization === "bitsandbytes_nf4"
          ? {
              ...entry,
              measurement_method: "not_measured",
              measurement_precision: "not_measured",
              observed_peak_gpu_allocation_mib: null,
              resource_measurement_state: "missing",
            }
          : entry,
      ),
    };

    for (const invalidPayload of [extraField, contradictory, falsifiedNf4Provenance]) {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
        .mockResolvedValueOnce(privateJsonResponse(invalidPayload));
      const transport = createHttpTransport({
        fetch: fetchMock as unknown as typeof fetch,
        origin: "http://127.0.0.1:4173",
      });
      const error = await transport.getTextModelCompatibility?.().catch((value: unknown) => value);

      expect(error).toBeInstanceOf(TransportError);
      expect(error).toMatchObject({ status: 200 });
      expect(String(error)).toBe("TransportError: Model compatibility response was invalid");
      expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
    }
  });

  it("rejects every omission, swap, and immutable compatibility provenance change", async () => {
    const payload = await createSyntheticTransport().getTextModelCompatibility!();
    const fullPrecisionKey = "qwen3_4b_rubric_full_precision_cuda_screen_v1";
    const measuredSmallKey = "mdeberta_xnli_unquantized_cuda_screen_v1";

    const patchEntry = (
      key: string,
      patch: Record<string, unknown>,
    ): ModelCompatibilityCatalog => {
      const changed = structuredClone(payload);
      const index = changed.models.findIndex(
        (entry) => entry.configuration_key === key,
      );
      expect(index).toBeGreaterThanOrEqual(0);
      changed.models[index] = {
        ...changed.models[index],
        ...patch,
      } as typeof changed.models[number];
      return changed;
    };

    const omitted = structuredClone(payload);
    omitted.models.splice(3, 1);
    const duplicated = structuredClone(payload);
    duplicated.models[3] = structuredClone(duplicated.models[2]);
    const swapped = structuredClone(payload);
    [swapped.models[2], swapped.models[3]] = [
      swapped.models[3],
      swapped.models[2],
    ];

    const attacks: Array<[string, unknown]> = [
      ["omitted configuration", omitted],
      ["duplicate configuration", duplicated],
      ["reordered configurations", swapped],
      ["configuration identity", patchEntry(fullPrecisionKey, { configuration_key: "forged_configuration_v1" })],
      ["private extra field", patchEntry(fullPrecisionKey, { raw_model_path: "SYNTHETIC_PRIVATE_CANARY" })],
      ["model identity", patchEntry(fullPrecisionKey, { model_key: "forged_model" })],
      ["repository identity", patchEntry(fullPrecisionKey, { repository_id: "ExampleOrg/forged-model" })],
      ["revision", patchEntry(fullPrecisionKey, { revision: "b".repeat(40) })],
      ["task", patchEntry(fullPrecisionKey, { task: "requirement_action_retrieval" })],
      ["role", patchEntry(fullPrecisionKey, { role: "retrieval" })],
      ["language scope", patchEntry(fullPrecisionKey, { language_scope: "english" })],
      ["license", patchEntry(fullPrecisionKey, { license_spdx: "MIT" })],
      ["quantization", patchEntry(fullPrecisionKey, { quantization: "bitsandbytes_nf4" })],
      ["dtype", patchEntry(fullPrecisionKey, { dtype: "float32" })],
      ["runtime", patchEntry(fullPrecisionKey, { runtime: "forged_runtime" })],
      ["measurement source", patchEntry(fullPrecisionKey, { measurement_source: "forged_source" })],
      ["GPU measurement", patchEntry(measuredSmallKey, { observed_peak_gpu_allocation_mib: 1_121.561 })],
      ["benchmark identity", patchEntry(measuredSmallKey, { benchmark_key: "forged_benchmark" })],
      ["case count", patchEntry(measuredSmallKey, { synthetic_case_count: 19 })],
      ["trust boundary", patchEntry(fullPrecisionKey, { trust_remote_code: true })],
      ["product activation", patchEntry(fullPrecisionKey, { product_enabled: true })],
      ["activation permission", patchEntry(fullPrecisionKey, { activation_allowed: true })],
      ["download permission", patchEntry(fullPrecisionKey, { download_allowed: true })],
      ["status", patchEntry(measuredSmallKey, { status: "unavailable" })],
      ["reason", patchEntry(measuredSmallKey, { reason_codes: ["cuda_unavailable"] })],
      [
        "coherent but forged missing measurement",
        patchEntry(measuredSmallKey, {
          measurement_method: "not_measured",
          measurement_precision: "not_measured",
          resource_measurement_state: "missing",
          observed_peak_gpu_allocation_mib: null,
          benchmark_key: null,
          synthetic_case_count: null,
        }),
      ],
      [
        "coherent but forged complete measurement",
        patchEntry(measuredSmallKey, {
          resource_measurement_state: "complete",
          observed_peak_child_rss_mib: 512,
          status: "research_only",
          reason_codes: ["exploratory_resource_fit"],
        }),
      ],
    ];

    for (const [name, attack] of attacks) {
      expect(
        () => parseModelCompatibilityCatalog(attack),
        name,
      ).toThrow(ModelCompatibilityPayloadError);
    }
  });

  it("accepts status changes only when they are exactly derived from coherent inventory", async () => {
    const base = await createSyntheticTransport().getTextModelCompatibility!();
    const inventoryCases: Array<Partial<ModelRuntimeInventory>> = [
      {
        preferred_device: "cpu",
        cuda_state: "unknown",
        cuda_available: null,
        mps_available: false,
        cuda_vram_bucket: null,
        cuda_capability_bucket: null,
        discovery_reason_codes: ["cuda_inventory_unknown"],
      },
      {
        preferred_device: "cpu",
        cuda_state: "unavailable",
        cuda_available: false,
        mps_available: false,
        cuda_vram_bucket: null,
        cuda_capability_bucket: null,
        discovery_reason_codes: [],
      },
      { system_ram_bucket: "below_16_gib_class" },
      { cuda_vram_bucket: "below_8_gib_class" },
    ];

    for (const patch of inventoryCases) {
      const inventory = {
        ...base.inventory,
        ...patch,
      } satisfies ModelRuntimeInventory;
      const payload = {
        ...base,
        inventory,
        models: FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS.map(
          (configuration) => ({
            ...configuration,
            ...deriveModelCompatibilityDisposition(inventory, configuration),
          }),
        ),
      } satisfies ModelCompatibilityCatalog;

      expect(parseModelCompatibilityCatalog(payload)).toEqual(payload);
    }
  });

  it("starts only an explicit local synthetic model job with CSRF", async () => {
    const runtime = {
      preferred_device: "cuda",
      cuda_state: "available",
      cuda_available: true,
      mps_available: false,
      cpu_available: true,
      cpu_architecture_bucket: "x86_64",
      logical_core_bucket: "9_to_16",
      system_ram_bucket: "16_gib_class",
      cuda_vram_bucket: "16_gib_class",
      cuda_capability_bucket: "8_x",
      model_cache_free_disk_bucket: "10240_to_51199_mib",
      discovery_reason_codes: [],
      inventory_version: "bucketed-sensitive-hardware-inventory-v3",
      one_model_at_a_time: true,
      subprocess_isolation: true,
      raw_session_data_accepted: false,
      model_child_gpu_allocation_ceiling_mib: 6144,
      model_child_rss_ceiling_mib: 8192,
      model_downloads_started: false,
      model_activation_allowed: false,
      sensitivity: "sensitive_derived",
      local_only: true,
      persisted: false,
      synced: false,
    } as const;
    const job = {
      job_id: "a".repeat(32),
      status: "queued",
      candidate: {
        candidate: "all",
        device: "auto",
        mode: "full",
        allow_download: false,
      },
      created_at: "2040-01-01T00:00:00Z",
      started_at: null,
      completed_at: null,
      resolved_device: null,
      error_code: null,
      outcomes: [],
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(runtime))
      .mockResolvedValueOnce(jsonResponse(job, 202));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getTextModelRuntime?.()).resolves.toEqual(runtime);
    await expect(transport.startTextModelEvaluation?.(job.candidate)).resolves.toEqual(job);
    expect(fetchMock.mock.calls[2][0]).toBe("/v1/research/text-model-evaluations");
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify(job.candidate),
      headers: expect.objectContaining({
        "Content-Type": "application/json",
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      }),
    }));
  });

  it.each([
    "https://outside.invalid/v1/discovery/candidates",
    "//outside.invalid/v1/discovery/candidates",
    "v1/discovery/candidates",
    "/v1\\discovery\\candidates",
  ])("rejects unexpected target %s", (target) => {
    expect(() => assertSameOriginRelativePath(target, "http://127.0.0.1:4173")).toThrow(
      TransportError,
    );
  });

  it("bootstraps browser auth and uses relative URLs with included credentials", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      input === "/auth/session"
        ? jsonResponse(AUTH_RESPONSE)
        : jsonResponse({ candidates: [], limit: 100, offset: 0 }),
    ) as unknown as typeof fetch;
    const transport = createHttpTransport({
      fetch: fetchMock,
      origin: "http://127.0.0.1:4173",
    });

    await transport.listCandidates("undecided");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/auth/session",
      expect.objectContaining({
        credentials: "include",
        method: "GET",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/v1/discovery/candidates?status=undecided",
      expect.objectContaining({
        credentials: "include",
        method: "GET",
        redirect: "error",
        referrerPolicy: "no-referrer",
      }),
    );
  });

  it("carries exact bounded pagination through each Task Flow index", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (input === "/auth/session") return jsonResponse(AUTH_RESPONSE);
      if (String(input).startsWith("/v1/discovery/candidates")) {
        return jsonResponse({ candidates: [], limit: 100, offset: 100 });
      }
      if (String(input).startsWith("/v1/task-revisions")) {
        return jsonResponse({ tasks: [], limit: 100, offset: 200 });
      }
      return jsonResponse({ runs: [], limit: 100, offset: 300 });
    });
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const taskId = "a".repeat(64);

    await transport.listCandidates("all", undefined, { limit: 100, offset: 100 });
    await transport.listTaskRevisions(taskId, undefined, { limit: 100, offset: 200 });
    await transport.listAnalysisRuns(undefined, undefined, { limit: 100, offset: 300 });

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/discovery/candidates?limit=100&offset=100",
      `/v1/task-revisions?task_id=${taskId}&limit=100&offset=200`,
      "/v1/analysis/runs?limit=100&offset=300",
    ]);
  });

  it("reads private loopback control-plane readiness without a data credential", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) =>
      input === "/auth/session"
        ? jsonResponse(AUTH_RESPONSE)
        : privateJsonResponse(CONTROL_PLANE_READINESS_RESPONSE),
    );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getControlPlaneReadiness()).resolves.toEqual(
      CONTROL_PLANE_READINESS_RESPONSE,
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/v1/control-plane/readiness",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        method: "GET",
      }),
    );
    const headers = fetchMock.mock.calls[1][1]?.headers as Record<string, string>;
    expect(headers).not.toHaveProperty("X-Control-Plane-Credential");
    expect(headers).not.toHaveProperty("X-Prompt-Enhancer-CSRF");
  });

  it("rejects control-plane readiness without exact private cache headers", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(CONTROL_PLANE_READINESS_RESPONSE));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getControlPlaneReadiness()).rejects.toMatchObject({
      status: 200,
    });
  });

  it("does not parse an unexpected response type", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        new Response("not-json", {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        }),
      ) as unknown as typeof fetch;
    const transport = createHttpTransport({
      fetch: fetchMock,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listCandidates()).rejects.toMatchObject({ status: 200 });
  });

  it("derives a content-free text-analysis capability only from coherent privacy fields", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse({
          session_text_analysis: true,
          session_text_analysis_data_tier: "redacted_content",
          session_text_content_persistence: false,
          codex_local_source: true,
          network_inference: false,
          raw_transcripts: false,
          unrelated_server_field: "discarded",
        }),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getSessionTextAnalysisCapability()).resolves.toEqual({
      available: true,
      reason_code: "available",
      data_tier: "redacted_content",
      content_persistence: false,
      network_inference: false,
      raw_transcripts: false,
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/capabilities");
  });

  it("fails closed on malformed or contradictory text-analysis capabilities", () => {
    expect(() =>
      parseSessionTextAnalysisCapability({
        session_text_analysis: true,
        session_text_analysis_data_tier: null,
        session_text_content_persistence: false,
        codex_local_source: true,
        network_inference: false,
        raw_transcripts: false,
      }),
    ).toThrow(TransportError);
    expect(() =>
      parseSessionTextAnalysisCapability({
        session_text_analysis: false,
        session_text_analysis_data_tier: null,
        session_text_content_persistence: false,
        codex_local_source: false,
        network_inference: true,
        raw_transcripts: false,
      }),
    ).toThrow(TransportError);
  });

  it("parses only an exact coherent content-free provider compatibility DTO", () => {
    expect(parseProviderCompatibilityStatus(PROVIDER_COMPATIBILITY)).toEqual(
      PROVIDER_COMPATIBILITY,
    );
    expect(() =>
      parseProviderCompatibilityStatus(PROVIDER_COMPATIBILITY, "claude_code"),
    ).toThrow(TransportError);
    expect(() =>
      parseProviderCompatibilityStatus({
        ...PROVIDER_COMPATIBILITY,
        private_provider_detail: "PRIVATE-CANARY",
      }),
    ).toThrow(TransportError);
    expect(() =>
      parseProviderCompatibilityStatus({
        ...PROVIDER_COMPATIBILITY,
        capability_state: "unsupported",
      }),
    ).toThrow(TransportError);
    expect(() =>
      parseProviderCompatibilityStatus({
        ...PROVIDER_COMPATIBILITY,
        provider_family: "private-hostname",
      }),
    ).toThrow(TransportError);
    expect(() =>
      parseProviderCompatibilityStatus({
        ...PROVIDER_COMPATIBILITY,
        adapter_version: "C:/Users/example",
      }),
    ).toThrow(TransportError);
  });

  it("loads cached compatibility and checks it only through an explicit mutation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(PROVIDER_COMPATIBILITY))
      .mockResolvedValueOnce(jsonResponse(PROVIDER_COMPATIBILITY));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.getProviderCompatibility?.("codex");
    await transport.checkProviderCompatibility?.("codex");

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/providers/codex/compatibility",
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock.mock.calls[1][1]?.headers).not.toEqual(
      expect.objectContaining({ "X-Prompt-Enhancer-CSRF": expect.anything() }),
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      "/v1/providers/codex/compatibility/check",
    );
    expect(fetchMock.mock.calls[2][1]).toEqual(
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
        }),
      }),
    );
  });

  it("reads cached provider and session metric readiness through exact GET routes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_PROVIDER_METRIC_CAPABILITIES))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_SESSION_METRIC_READINESS));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(
      transport.getProviderMetricCapabilities("synthetic"),
    ).resolves.toEqual(SYNTHETIC_PROVIDER_METRIC_CAPABILITIES);
    await expect(
      transport.getSessionMetricReadiness(
        SYNTHETIC_SESSION_METRIC_READINESS.session_id,
      ),
    ).resolves.toEqual(SYNTHETIC_SESSION_METRIC_READINESS);

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/providers/synthetic/capabilities",
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/sessions/${SYNTHETIC_SESSION_METRIC_READINESS.session_id}/metric-readiness?preset_id=coaching_profile_v1`,
    );
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({ method: "GET" }));
      expect(call[1]?.headers).not.toEqual(
        expect.objectContaining({ "X-Prompt-Enhancer-CSRF": expect.anything() }),
      );
    }
  });

  it("accepts only the complete coherent content-free provider capability projection", () => {
    expect(
      parseProviderCapabilityReport(
        SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        "synthetic",
      ),
    ).toEqual(SYNTHETIC_PROVIDER_METRIC_CAPABILITIES);

    expect(
      parseProviderCapabilityReport({
        ...SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        provider_version: "synthetic/1:compatible",
      }),
    ).toMatchObject({ provider_version: "synthetic/1:compatible" });

    const duplicateCapability = structuredClone(
      SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
    );
    duplicateCapability.capabilities[6] = structuredClone(
      duplicateCapability.capabilities[0],
    );
    const incoherentState = structuredClone(
      SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
    );
    incoherentState.capabilities[0] = {
      ...incoherentState.capabilities[0],
      state: "unsupported",
    };
    const invalidCount = {
      ...SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
      structurally_attemptable_metric_count: 19,
    };

    expect(() =>
      parseProviderCapabilityReport({
        ...SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        private_payload: "SYNTHETIC-PRIVATE-CANARY",
      }),
    ).toThrow(TransportError);
    expect(() => parseProviderCapabilityReport(duplicateCapability)).toThrow(
      TransportError,
    );
    expect(() => parseProviderCapabilityReport(incoherentState)).toThrow(
      TransportError,
    );
    expect(() => parseProviderCapabilityReport(invalidCount)).toThrow(
      TransportError,
    );
    expect(() =>
      parseProviderCapabilityReport(
        SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        "codex",
      ),
    ).toThrow(TransportError);
  });

  it("reads provider and project metric coverage through private no-store routes", async () => {
    const projectId = "4".repeat(64);
    const projectCoverage = {
      ...structuredClone(SYNTHETIC_METRIC_COVERAGE),
      scope: "one_project" as const,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(SYNTHETIC_METRIC_COVERAGE))
      .mockResolvedValueOnce(privateJsonResponse(projectCoverage));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getMetricCoverage("synthetic")).resolves.toEqual(
      SYNTHETIC_METRIC_COVERAGE,
    );
    await expect(
      transport.getProjectMetricCoverage(projectId, "synthetic"),
    ).resolves.toEqual(projectCoverage);

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/metric-coverage?provider=synthetic",
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/projects/${projectId}/metric-coverage?provider=synthetic`,
    );
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({
        cache: "no-store",
        method: "GET",
      }));
    }
  });

  it("fails closed when metric coverage is not delivered as a private response", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_METRIC_COVERAGE));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getMetricCoverage("synthetic")).rejects.toThrow(
      "Private local response was not cache-safe",
    );
  });

  it("accepts only exact, identifier-free and internally preserved coverage", () => {
    expect(
      parseMetricCoverageReport(
        SYNTHETIC_METRIC_COVERAGE,
        "synthetic",
        "provider_catalog",
      ),
    ).toEqual(SYNTHETIC_METRIC_COVERAGE);

    const cases: unknown[] = [
      { ...SYNTHETIC_METRIC_COVERAGE, project_id: "4".repeat(64) },
      { ...SYNTHETIC_METRIC_COVERAGE, generated_at: "2040-02-31T09:13:00Z" },
      {
        ...SYNTHETIC_METRIC_COVERAGE,
        capability_report: {
          ...SYNTHETIC_METRIC_COVERAGE.capability_report,
          checked_at: "2040-02-31T09:13:00Z",
        },
      },
      { ...SYNTHETIC_METRIC_COVERAGE, provider: "codex" },
      {
        ...SYNTHETIC_METRIC_COVERAGE,
        latest_profile_runs: {
          completed: 0, running: 0, failed: 0, never_run: 1,
        },
      },
      (() => {
        const value = structuredClone(SYNTHETIC_METRIC_COVERAGE);
        value.metrics[0].contract_compatible_result_states.known = 2;
        return value;
      })(),
      (() => {
        const value = structuredClone(SYNTHETIC_METRIC_COVERAGE);
        value.metrics[0].display_name = "PRIVATE-COVERAGE-CANARY";
        return value;
      })(),
      (() => {
        const value = structuredClone(SYNTHETIC_METRIC_COVERAGE);
        value.metrics.reverse();
        return value;
      })(),
    ];

    for (const value of cases) {
      expect(() =>
        parseMetricCoverageReport(value, "synthetic", "provider_catalog"),
      ).toThrow(TransportError);
    }
  });

  it("accepts the backend readiness-token alphabet and rejects values outside its bounds", () => {
    const completeAlphabet = "A._+:/-readiness-v1";
    const maximumLength = `A${"x".repeat(127)}`;
    expect(
      parseProviderCapabilityReport({
        ...SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        provider_version: completeAlphabet,
        decoder_key: maximumLength,
        decoder_version: completeAlphabet,
      }),
    ).toMatchObject({
      provider_version: completeAlphabet,
      decoder_key: maximumLength,
      decoder_version: completeAlphabet,
    });

    for (const invalidToken of [
      ".leading-punctuation",
      "contains whitespace",
      `A${"x".repeat(128)}`,
    ]) {
      expect(() => parseProviderCapabilityReport({
        ...SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
        provider_version: invalidToken,
      })).toThrow(TransportError);
    }
  });

  it("rejects readiness metadata that is incomplete, reordered, or contradicts its state", () => {
    expect(
      parseSessionMetricReadinessReport(
        SYNTHETIC_SESSION_METRIC_READINESS,
        SYNTHETIC_SESSION_METRIC_READINESS.session_id,
      ),
    ).toEqual(SYNTHETIC_SESSION_METRIC_READINESS);

    const reordered = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    reordered.metrics.reverse();
    const contradictoryAction = structuredClone(
      SYNTHETIC_SESSION_METRIC_READINESS,
    );
    contradictoryAction.metrics[0].next_actions = ["retry_analysis"];
    const privateDisplay = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    privateDisplay.metrics[0].display_name = "SYNTHETIC-PRIVATE-CANARY";
    const duplicateMetric = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    duplicateMetric.metrics[19] = structuredClone(duplicateMetric.metrics[0]);

    expect(() =>
      parseSessionMetricReadinessReport({
        ...SYNTHETIC_SESSION_METRIC_READINESS,
        raw_excerpt: "SYNTHETIC-PRIVATE-CANARY",
      }),
    ).toThrow(TransportError);
    expect(() => parseSessionMetricReadinessReport(reordered)).toThrow(
      TransportError,
    );
    expect(() => parseSessionMetricReadinessReport(contradictoryAction)).toThrow(
      TransportError,
    );
    expect(() => parseSessionMetricReadinessReport(privateDisplay)).toThrow(
      TransportError,
    );
    expect(() => parseSessionMetricReadinessReport(duplicateMetric)).toThrow(
      TransportError,
    );
    expect(() =>
      parseSessionMetricReadinessReport(
        SYNTHETIC_SESSION_METRIC_READINESS,
        "f".repeat(64),
      ),
    ).toThrow(TransportError);
  });

  it.each([
    "metric_not_selected",
    "metric_scope_unknown",
  ] as const)("accepts truthful %s readiness with an explicit selection action", (reason) => {
    const report = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    report.metrics[0].state = "unknown";
    report.metrics[0].reason_code = reason;
    report.metrics[0].next_actions = ["select_metric_for_analysis"];

    expect(parseSessionMetricReadinessReport(report).metrics[0]).toMatchObject({
      state: "unknown",
      reason_code: reason,
      next_actions: ["select_metric_for_analysis"],
      latest_run_id: SYNTHETIC_SESSION_METRIC_READINESS.metrics[0].latest_run_id,
    });
  });

  it.each([
    "queued", "preprocessing", "stage_n", "awaiting_approval", "completed",
    "partial", "failed", "cancelled", "superseded",
  ] as const)("accepts a coherent browser-safe %s job", (state) => {
    const parsed = parseAnalysisJobRecord(analysisJobPayload(state));
    expect(parsed.state).toBe(state);
    expect(parsed).not.toHaveProperty("dedupe_key");
    expect(parsed).not.toHaveProperty("lease_owner");
    expect(parsed).not.toHaveProperty("lease_token");
    expect(parsed).not.toHaveProperty("lease_expires_at");
  });

  it("rejects job payloads with private extras, remote execution, unsorted metrics, or incoherent runtime state", () => {
    const extra = {
      ...analysisJobPayload(),
      raw_error: "PRIVATE-JOB-ERROR-CANARY",
    };
    const remote = analysisJobPayload("queued");
    (remote.identity as Record<string, unknown>).local_only = false;
    const unsorted = analysisJobPayload("queued");
    (unsorted.identity as { metric_keys: string[] }).metric_keys.reverse();
    const leakedInternalFields = analysisJobPayload("queued", {
      dedupe_key: "2".repeat(64),
      lease_owner: "7".repeat(64),
      lease_token: "8".repeat(64),
      lease_expires_at: "2040-01-01T10:00:30Z",
    });
    const missingTerminal = analysisJobPayload("failed", {
      terminal_at: null,
      terminal_reason_code: null,
    });
    const wrongStage = analysisJobPayload("stage_n", { stage_number: null });

    for (const value of [
      extra,
      remote,
      unsorted,
      leakedInternalFields,
      missingTerminal,
      wrongStage,
    ]) {
      const error = (() => {
        try {
          parseAnalysisJobRecord(value);
          return null;
        } catch (caught) {
          return caught;
        }
      })();
      expect(error).toBeInstanceOf(TransportError);
      expect(String(error)).not.toContain("PRIVATE-JOB-ERROR-CANARY");
    }
  });

  it("validates filtered job pages and rejects duplicate or cross-state records", () => {
    const queued = analysisJobPayload("queued");
    expect(parseAnalysisJobPage(
      { jobs: [queued], limit: 25, offset: 0 },
      25,
      0,
      "queued",
    ).jobs).toHaveLength(1);
    expect(() => parseAnalysisJobPage(
      { jobs: [queued, queued], limit: 25, offset: 0 },
      25,
      0,
      "queued",
    )).toThrow(TransportError);
    expect(() => parseAnalysisJobPage(
      { jobs: [analysisJobPayload("failed")], limit: 25, offset: 0 },
      25,
      0,
      "queued",
    )).toThrow(TransportError);
  });

  it("lists, opens, resolves latest, and cancels content-free jobs on exact routes", async () => {
    const queued = analysisJobPayload("queued");
    const cancelled = analysisJobPayload("cancelled", {
      terminal_reason_code: "cancellation_requested",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({ jobs: [queued], limit: 25, offset: 50 }))
      .mockResolvedValueOnce(privateJsonResponse(queued))
      .mockResolvedValueOnce(privateJsonResponse(queued))
      .mockResolvedValueOnce(privateJsonResponse(cancelled));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const page = await transport.listAnalysisJobs("queued", 25, 50);
    await transport.getAnalysisJob("1".repeat(64));
    await transport.getLatestSessionAnalysisJob("4".repeat(64));
    const result = await transport.cancelAnalysisJob("1".repeat(64));

    expect(page.jobs).toHaveLength(1);
    expect(result.state).toBe("cancelled");
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/analysis-jobs?limit=25&offset=50&state=queued",
    );
    expect(fetchMock.mock.calls[2][0]).toBe(`/v1/analysis-jobs/${"1".repeat(64)}`);
    expect(fetchMock.mock.calls[3][0]).toBe(
      `/v1/sessions/${"4".repeat(64)}/analysis-jobs/latest`,
    );
    expect(fetchMock.mock.calls[4][0]).toBe(
      `/v1/analysis-jobs/${"1".repeat(64)}/cancellation`,
    );
    expect(fetchMock.mock.calls[4][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      method: "POST",
      credentials: "include",
    }));
    expect((fetchMock.mock.calls[4][1] as RequestInit).headers).toEqual(
      expect.objectContaining({
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      }),
    );
  });

  it("fails closed when the job API omits private no-store response headers", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({
        jobs: [analysisJobPayload("queued")],
        limit: 25,
        offset: 0,
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listAnalysisJobs("queued", 25, 0)).rejects.toThrow(
      "Private local response was not cache-safe",
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      cache: "no-store",
    }));
  });

  it.each(["active", "revoked", "expired"] as const)(
    "accepts a coherent %s automation grant with a fixed 30-day lifetime",
    (state) => {
      const record = parseAutomationGrantRecord(automationGrantPayload(state));
      expect(record.state).toBe(state);
      expect(record.scope.local_only).toBe(true);
      expect(record.scope.remote_requires_fresh_approval).toBe(true);
    },
  );

  it("rejects private extras, remote scope, identity drift, and incoherent automation grants", () => {
    const privateExtra = {
      ...automationGrantPayload(),
      prompt: "PRIVATE-AUTOMATION-CANARY",
    };
    const remote = automationGrantPayload();
    (remote.scope as AutomationGrantScope).local_only = false as true;
    const unsorted = automationGrantPayload();
    (unsorted.scope as AutomationGrantScope).metric_keys.reverse();
    const wrongLifetime = automationGrantPayload("active", {
      expires_at: "2040-02-01T09:00:00Z",
    });
    const missingRevocation = automationGrantPayload("revoked", {
      revoked_at: null,
    });
    const privatePolicy = automationGrantPayload();
    (privatePolicy.scope as AutomationGrantScope).resource_policy = {
      ...automationScope().resource_policy,
      max_gpu_workers: 2 as 1,
    };

    for (const value of [
      privateExtra,
      remote,
      unsorted,
      wrongLifetime,
      missingRevocation,
      privatePolicy,
    ]) {
      const error = (() => {
        try {
          parseAutomationGrantRecord(value);
          return null;
        } catch (caught) {
          return caught;
        }
      })();
      expect(error).toBeInstanceOf(TransportError);
      expect(String(error)).not.toContain("PRIVATE-AUTOMATION-CANARY");
    }
    expect(() => parseAutomationGrantRecord(
      automationGrantPayload(),
      "9".repeat(64),
      automationScope({ project_id: "8".repeat(64) }),
    )).toThrow(TransportError);
  });

  it("validates provider-bound automation lists and content-free poll counters", () => {
    const grant = automationGrantPayload();
    expect(parseAutomationGrantList([grant], "codex")).toHaveLength(1);
    expect(() => parseAutomationGrantList([grant, grant], "codex")).toThrow(
      TransportError,
    );
    expect(() => parseAutomationGrantList([grant], "claude_code")).toThrow(
      TransportError,
    );
    const poll = {
      grants_checked: 1,
      grants_revoked: 0,
      grants_power_paused: 0,
      grants_policy_unsupported: 0,
      power_external_observations: 1,
      power_battery_observations: 0,
      power_unknown_observations: 0,
      candidates_seen: 2,
      jobs_created: 1,
      jobs_reused: 1,
      jobs_superseded: 0,
      failures: 0,
      maximum_session_runtime_deadline_enforced: false as const,
      session_quality_result_publication_deadline_enforced: true as const,
      blocking_execution_preemption_enforced: false as const,
    };
    expect(parseAutomationPollResult(poll)).toEqual(poll);
    expect(() => parseAutomationPollResult({ ...poll, failures: -1 })).toThrow(
      TransportError,
    );
    expect(() => parseAutomationPollResult({ ...poll, raw_error: "private" })).toThrow(
      TransportError,
    );

    const incoherent = [
      { ...poll, grants_checked: 2 },
      { ...poll, grants_power_paused: 1 },
      { ...poll, grants_policy_unsupported: 1 },
      { ...poll, candidates_seen: 1 },
      { ...poll, jobs_superseded: 3 },
      { ...poll, maximum_session_runtime_deadline_enforced: true },
      { ...poll, session_quality_result_publication_deadline_enforced: false },
      { ...poll, blocking_execution_preemption_enforced: true },
    ];
    for (const value of incoherent) {
      expect(() => parseAutomationPollResult(value)).toThrow(TransportError);
    }
  });

  it.each([
    ["fast route", { route: "fast" }],
    ["two CPU workers", { max_cpu_workers: 2 }],
    ["battery continuation", { pause_on_battery: false }],
    ["different runtime budget", { maximum_session_seconds: 3_600 }],
  ])("rejects an unreviewed create profile (%s) before fetch", async (_label, update) => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const scope = automationScope();
    const request = {
      provider: scope.provider,
      project_id: scope.project_id,
      metric_keys: scope.metric_keys,
      newest_session_limit: scope.newest_session_limit,
      check_interval_seconds: scope.check_interval_seconds,
      resource_policy: {
        route: "balanced",
        max_gpu_workers: 1,
        max_cpu_workers: 1,
        pause_on_battery: true,
        maximum_session_seconds: 1_800,
        ...update,
      },
    };

    await expect(transport.createAutomationGrant(request as never)).rejects.toMatchObject({
      status: 400,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lists, creates, opens, renews, revokes, and polls automation on exact private routes", async () => {
    const scope = automationScope();
    const active = automationGrantPayload();
    const renewed = automationGrantPayload("active", {
      revision: 2,
      renewed_at: "2040-01-02T09:00:00Z",
      expires_at: "2040-02-01T09:00:00Z",
      next_check_at: "2040-01-02T09:00:00Z",
    });
    const revoked = { ...renewed, state: "revoked", revoked_at: "2040-01-02T10:00:00Z" };
    const poll = {
      grants_checked: 1,
      grants_revoked: 0,
      grants_power_paused: 0,
      grants_policy_unsupported: 0,
      power_external_observations: 1,
      power_battery_observations: 0,
      power_unknown_observations: 0,
      candidates_seen: 2,
      jobs_created: 1,
      jobs_reused: 1,
      jobs_superseded: 0,
      failures: 0,
      maximum_session_runtime_deadline_enforced: false as const,
      session_quality_result_publication_deadline_enforced: true as const,
      blocking_execution_preemption_enforced: false as const,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse([active]))
      .mockResolvedValueOnce(privateJsonResponse(active))
      .mockResolvedValueOnce(privateJsonResponse(active, 201))
      .mockResolvedValueOnce(privateJsonResponse(renewed))
      .mockResolvedValueOnce(privateJsonResponse(revoked))
      .mockResolvedValueOnce(privateJsonResponse(poll));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const createRequest = {
      provider: scope.provider,
      project_id: scope.project_id,
      metric_keys: scope.metric_keys,
      newest_session_limit: scope.newest_session_limit,
      check_interval_seconds: scope.check_interval_seconds,
      resource_policy: {
        route: "balanced" as const,
        max_gpu_workers: 1 as const,
        max_cpu_workers: 1 as const,
        pause_on_battery: true as const,
        maximum_session_seconds: 1_800 as const,
      },
    };

    await transport.listAutomationGrants("codex", false);
    await transport.getAutomationGrant("9".repeat(64), scope);
    await transport.createAutomationGrant(createRequest);
    await transport.renewAutomationGrant("9".repeat(64), scope);
    await transport.revokeAutomationGrant("9".repeat(64), scope);
    expect(await transport.pollAutomationGrants()).toEqual(poll);

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/automation-grants?provider=codex&active_only=false",
      `/v1/automation-grants/${"9".repeat(64)}`,
      "/v1/automation-grants",
      `/v1/automation-grants/${"9".repeat(64)}/renewal`,
      `/v1/automation-grants/${"9".repeat(64)}/revocation`,
      "/v1/automation-grants/poll",
    ]);
    for (const [, request] of fetchMock.mock.calls.slice(1)) {
      expect(request).toEqual(expect.objectContaining({
        cache: "no-store",
        credentials: "include",
      }));
    }
    expect(JSON.parse((fetchMock.mock.calls[3][1] as RequestInit).body as string)).toEqual(
      createRequest,
    );
  });

  it("fails closed when automation responses are cacheable and preserves safe consent reasons", async () => {
    const cacheableFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse([automationGrantPayload()]));
    const cacheable = createHttpTransport({
      fetch: cacheableFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(cacheable.listAutomationGrants("codex")).rejects.toThrow(
      "Private local response was not cache-safe",
    );

    const deniedFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: { code: "automation_consent_required" },
      }, 403));
    const denied = createHttpTransport({
      fetch: deniedFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(denied.createAutomationGrant({
      provider: "codex",
      project_id: automationScope().project_id,
      metric_keys: automationScope().metric_keys,
      newest_session_limit: 20,
      check_interval_seconds: 900,
      resource_policy: {
        route: "balanced",
        max_gpu_workers: 1,
        max_cpu_workers: 1,
        pause_on_battery: true,
        maximum_session_seconds: 1_800,
      },
    })).rejects.toMatchObject({
      status: 403,
      reasonCode: "automation_consent_required",
    });
  });

  it("strictly validates a local preview and rejects remote, private-extra, drifted, or inconsistent shapes", () => {
    const sessionId = "5".repeat(64);
    const valid = redactionPreview(sessionId);
    expect(parseSessionQualityAnalysisPreview(valid, sessionId)).toEqual(valid);

    const remote = structuredClone(valid);
    remote.binding.destination = "remote" as "local";
    remote.binding.retention_class = "remote_30_day" as "local_ephemeral";
    remote.binding.cost_state = "unknown" as "not_applicable";
    const extra = { ...valid, raw_provider_path: "PRIVATE-PATH-CANARY" };
    const wrongSession = structuredClone(valid);
    wrongSession.binding.session_id = "6".repeat(64);
    const wrongCharacters = structuredClone(valid);
    wrongCharacters.binding.character_count += 1;
    const wrongTtl = structuredClone(valid);
    wrongTtl.expires_at = "2040-01-01T10:09:59Z";
    const incompleteMetrics = structuredClone(valid);
    incompleteMetrics.binding.metric_keys.pop();

    for (const value of [
      remote,
      extra,
      wrongSession,
      wrongCharacters,
      wrongTtl,
      incompleteMetrics,
    ]) {
      let error: unknown;
      try {
        parseSessionQualityAnalysisPreview(value, sessionId);
      } catch (caught) {
        error = caught;
      }
      expect(error).toBeInstanceOf(TransportError);
      expect(String(error)).not.toContain("PRIVATE-PATH-CANARY");
    }
  });

  it("prepares and approves an exact private preview with no-store transport policy", async () => {
    const sessionId = "5".repeat(64);
    const preview = redactionPreview(sessionId);
    const outcome = {
      run_id: "6".repeat(64),
      status: "completed",
      result_count: 20,
      applied: true,
      analysis_profile_key: "coaching_profile",
      analysis_profile_version: 1,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(preview))
      .mockResolvedValueOnce(privateJsonResponse(outcome));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const prepared = await transport.prepareSessionQualityAnalysisPreview(
      sessionId,
      { preset_id: "coaching_profile_v1" },
    );
    const approved = await transport.approveSessionQualityAnalysisPreview(
      prepared.preview_id,
      {
        confirmation: "approve_exact_redacted_preview",
        expected_binding: prepared.binding,
      },
      "dashboard-quality-preview-approval-example",
    );

    expect(approved).toEqual(outcome);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/sessions/${sessionId}/quality-analysis-previews`,
    );
    const preparation = fetchMock.mock.calls[1][1] as RequestInit;
    expect(preparation).toEqual(expect.objectContaining({
      method: "POST",
      cache: "no-store",
      credentials: "include",
      referrerPolicy: "no-referrer",
    }));
    expect(JSON.parse(preparation.body as string)).toEqual({
      preset_id: "coaching_profile_v1",
    });
    const approval = fetchMock.mock.calls[2][1] as RequestInit;
    expect(approval.cache).toBe("no-store");
    expect(approval.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "dashboard-quality-preview-approval-example",
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
    }));
    expect(JSON.parse(approval.body as string)).toEqual({
      confirmation: "approve_exact_redacted_preview",
      expected_binding: preview.binding,
    });
  });

  it("fails closed if a secret-bearing success response lacks private no-store headers", async () => {
    const sessionId = "5".repeat(64);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(redactionPreview(sessionId)));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(
      transport.prepareSessionQualityAnalysisPreview(
        sessionId,
        { preset_id: "coaching_profile_v1" },
      ),
    ).rejects.toMatchObject({ status: 200, reasonCode: null });
  });

  it("extracts only an allowlisted preview failure code and discards server content", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: {
          code: "redaction_preview_binding_mismatch",
          message: "PRIVATE-PREVIEW-ERROR-CANARY",
        },
      }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.approveSessionQualityAnalysisPreview(
      "e".repeat(64),
      {
        confirmation: "approve_exact_redacted_preview",
        expected_binding: redactionPreview().binding,
      },
      "dashboard-quality-preview-approval-mismatch",
    ).catch((value: unknown) => value);

    expect(error).toMatchObject({
      status: 409,
      reasonCode: "redaction_preview_binding_mismatch",
    });
    expect(String(error)).not.toContain("PRIVATE-PREVIEW-ERROR-CANARY");
  });

  it.each([
    "provider_unavailable",
    "no_analyzable_text",
    "provider_protocol_rejected",
    "provider_compatibility_blocked",
    "source_selection_limit",
    "source_provider_response_limit",
    "source_thread_structure_limit",
    "source_preview_window_limit",
    "source_resource_limit",
  ] as const)("extracts allowlisted detail code %s without forwarding server messages", async (code) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code,
              message: "PRIVATE-SERVER-CONTENT-CANARY",
            },
            reason_code: "metric_execution_failed",
          },
          503,
        ),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport
      .startSessionQualityAnalysis(
        "5".repeat(64),
        CONTENT_FREE_ANALYSIS_REQUEST,
        `dashboard-quality-analysis-safe-error-${code}`,
      )
      .catch((value: unknown) => value);
    expect(error).toMatchObject({
      status: 503,
      reasonCode: code,
    });
    expect(String(error)).not.toContain("PRIVATE-SERVER-CONTENT-CANARY");
  });

  it("ignores unknown, top-level, and raw safe-looking error details", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: { code: "PRIVATE_UNKNOWN_CODE", message: "provider_unavailable" },
            reason_code: "provider_unavailable",
          },
          503,
        ),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport
      .startSessionQualityAnalysis(
        "5".repeat(64),
        CONTENT_FREE_ANALYSIS_REQUEST,
        "dashboard-quality-analysis-unknown-error",
      )
      .catch((value: unknown) => value);
    expect(error).toMatchObject({ status: 503, reasonCode: null });
  });

  it("loads a project-scoped bounded session page", async () => {
    const projectId = "4".repeat(64);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse({
          sessions: [],
          limit: 25,
          offset: 50,
          total: 75,
          has_more: false,
        }),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const response = await transport.listProjectSessions(projectId, 25, 50);

    expect(response).toMatchObject({ total: 75, has_more: false });
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/projects/${projectId}/sessions?limit=25&offset=50`,
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("keeps CSRF in memory and attaches it only to mutations", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse({
          consent_active: true,
          indexed_sessions: 0,
          indexed_projects: 0,
        }),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.grantCodexLocalHistoryConsent();

    const mutationInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(mutationInit).toEqual(
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
    expect(mutationInit.headers).toEqual(
      expect.objectContaining({
        "X-Prompt-Enhancer-CSRF": "synthetic-csrf-token",
      }),
    );
    expect(mutationInit.headers).not.toEqual(
      expect.objectContaining({ "X-Prompt-Enhancer-Token": expect.anything() }),
    );
  });

  it("shares one browser bootstrap across concurrent initial requests", async () => {
    let resolveBootstrap: ((response: Response) => void) | undefined;
    const pendingBootstrap = new Promise<Response>((resolve) => {
      resolveBootstrap = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      input === "/auth/session"
        ? pendingBootstrap
        : Promise.resolve(jsonResponse({ candidates: [], limit: 100, offset: 0 })),
    );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const first = transport.listCandidates();
    const second = transport.listCandidates();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveBootstrap?.(jsonResponse(AUTH_RESPONSE));
    await Promise.all([first, second]);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(
      fetchMock.mock.calls.filter(([input]) => input === "/auth/session"),
    ).toHaveLength(1);
  });

  it("re-establishes in-memory browser auth once after a 401", async () => {
    const refreshedAuth = {
      csrf_token: "synthetic-refreshed-csrf-token",
      expires_in_seconds: 300,
    };
    const sourceStatus = {
      consent_active: true,
      indexed_sessions: 0,
      indexed_projects: 0,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: "authentication required" }, 401))
      .mockResolvedValueOnce(jsonResponse(refreshedAuth))
      .mockResolvedValueOnce(jsonResponse(sourceStatus));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.grantCodexLocalHistoryConsent();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[0][0]).toBe("/auth/session");
    expect(fetchMock.mock.calls[2][0]).toBe("/auth/session");
    const retriedMutation = fetchMock.mock.calls[3][1] as RequestInit;
    expect(retriedMutation.headers).toEqual(
      expect.objectContaining({
        "X-Prompt-Enhancer-CSRF": "synthetic-refreshed-csrf-token",
      }),
    );
  });

  it("reads latest and detail quality snapshots without initiating an analysis", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_SESSION_QUALITY_RUN))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_SESSION_QUALITY_RUN))
      .mockResolvedValueOnce(jsonResponse({ projection_key: "coaching.loop.current" }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.getLatestSessionQualityAnalysis("5".repeat(64));
    await transport.getSessionQualityAnalysisRun("6".repeat(64));
    await transport.getSessionCoachingSummary!("6".repeat(64));

    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/sessions/${"5".repeat(64)}/quality-analysis-runs/latest`,
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/quality-analysis/runs/${"6".repeat(64)}`,
    );
    expect(fetchMock.mock.calls[3][0]).toBe(
      `/v1/quality-analysis/runs/${"6".repeat(64)}/coaching-summary`,
    );
    expect(fetchMock.mock.calls[3][1]).toEqual(
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock.mock.calls[1][1]?.headers).not.toEqual(
      expect.objectContaining({ "Idempotency-Key": expect.anything() }),
    );
  });

  it("posts the exact reviewed quality request with in-memory CSRF and idempotency", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: "6".repeat(64),
          status: "completed",
          result_count: 20,
          applied: true,
          analysis_profile_key: "coaching_profile",
          analysis_profile_version: 1,
        }),
      );
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const request: SessionQualityAnalysisRequest = {
      confirmation: "analyze_selected_redacted_text",
      preset_id: "coaching_profile_v1",
    };

    const outcome = await transport.startSessionQualityAnalysis(
      "5".repeat(64),
      request,
      "dashboard-quality-analysis-example",
    );

    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/sessions/${"5".repeat(64)}/quality-analysis-runs`,
    );
    const mutation = fetchMock.mock.calls[1][1] as RequestInit;
    expect(mutation.method).toBe("POST");
    expect(mutation.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        "Idempotency-Key": "dashboard-quality-analysis-example",
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      }),
    );
    expect(JSON.parse(mutation.body as string)).toEqual(request);
    expect(outcome).toMatchObject({
      analysis_profile_key: "coaching_profile",
      analysis_profile_version: 1,
    });
  });

  it("posts a content-free selected-session aggregate without an idempotency key", async () => {
    const sessionIds = ["5".repeat(64), "6".repeat(64)];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ selected_session_count: 2 }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.aggregateSessionQuality({ session_ids: sessionIds });

    expect(fetchMock.mock.calls[1][0]).toBe("/v1/quality-analysis/aggregate");
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      }),
    );
    expect(request.headers).not.toEqual(
      expect.objectContaining({ "Idempotency-Key": expect.anything() }),
    );
    expect(JSON.parse(request.body as string)).toEqual({ session_ids: sessionIds });
  });

  it("posts only the closed selected-project comparison scope", async () => {
    const projectIds = ["7".repeat(64), "8".repeat(64)];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ selected_project_count: 2 }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.aggregateProjectQuality({
      project_ids: projectIds,
      selection_mode: "all_analyzed_work",
    });

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/quality-analysis/aggregate-projects",
    );
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      }),
    );
    expect(request.headers).not.toEqual(
      expect.objectContaining({ "Idempotency-Key": expect.anything() }),
    );
    expect(JSON.parse(request.body as string)).toEqual({
      project_ids: projectIds,
      selection_mode: "all_analyzed_work",
    });
  });
});

describe("local agent model-readiness transport", () => {
  it("uses revision-bound runtime and session-model endpoints without losing identity", async () => {
    const switchedSession = exampleAgentSession({
      model_alias: "example-model",
      settings: { ...exampleAgentSession().settings, model_alias: "example-model" },
    });
    const idle = localRuntime({
      revision: 6,
      state: "idle",
      requested: null,
      served: null,
      capabilities: {
        ...localRuntime().capabilities,
        state: "not_probed",
        text: false,
        tools: false,
      },
      context: {
        ...localRuntime().context,
        limit_tokens: null,
        reason_code: "runtime_not_served",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(localRuntime()))
      .mockResolvedValueOnce(jsonResponse(localRuntime({ revision: 5 })))
      .mockResolvedValueOnce(jsonResponse(switchedSession))
      .mockResolvedValueOnce(jsonResponse(idle));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getLocalRuntime()).resolves.toMatchObject({
      state: "ready",
      served: { alias: "example-model" },
    });
    await expect(transport.switchLocalRuntime({
      alias: "example-model",
      expected_revision: 4,
      device: "split",
      gpu_layers: 20,
      context_size: 8192,
      remember: true,
      fast_attention: true,
      tool_calling: true,
    })).resolves.toMatchObject({ revision: 5, state: "ready" });
    await expect(transport.switchAgentSessionModel(switchedSession.session_id, {
      model_alias: "example-model",
      expected_revision: 2,
    })).resolves.toMatchObject({ model_alias: "example-model" });
    await expect(transport.stopLocalRuntime({
      alias: "example-model",
      expected_revision: 5,
    })).resolves.toMatchObject({ revision: 6, state: "idle" });

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/local-models/runtime",
      "/v1/local-models/runtime/switch",
      `/v1/agent/sessions/${switchedSession.session_id}/model`,
      "/v1/local-models/runtime/stop",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toMatchObject({
      alias: "example-model",
      expected_revision: 4,
      device: "split",
    });
    expect(JSON.parse(fetchMock.mock.calls[3][1].body as string)).toEqual({
      model_alias: "example-model",
      expected_revision: 2,
    });
  });

  it("requests context-bound placement admission without exposing a model path", async () => {
    const admission = {
      contract_version: "local-model-placement.v1",
      alias: "example-model",
      context_size: 32768,
      gpu_memory_free_mb: 12000,
      actual_offload_verified: false,
      options: [
        { device: "gpu", state: "available", reason_code: "gpu_estimate_fits", recommended_gpu_layers: 8, estimated_vram_required_mb: 6000 },
        { device: "split", state: "available", reason_code: "split_estimate_available", recommended_gpu_layers: 6, estimated_vram_required_mb: 5000 },
        { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
      ],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(admission));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getLocalModelPlacement("example-model", 32768)).resolves.toEqual(admission);
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/local-models/example-model/placement?context_size=32768",
    );
    expect(JSON.stringify(fetchMock.mock.calls[1])).not.toContain("models\\example");
  });

  it("sends revision-checked durable download commands to their exact closed routes", async () => {
    const downloadId = "d".repeat(64);
    const response = { download_id: downloadId, state: "paused", status_revision: 10 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(response))
      .mockResolvedValueOnce(jsonResponse(response))
      .mockResolvedValueOnce(jsonResponse(response))
      .mockResolvedValueOnce(jsonResponse(response));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.pauseLocalModelDownload(downloadId, 6);
    await transport.resumeLocalModelDownload(downloadId, 7);
    await transport.retryLocalModelDownload(downloadId, 8);
    await transport.cancelLocalModelDownload(downloadId, 9);

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      `/v1/local-models/downloads/${downloadId}/pause`,
      `/v1/local-models/downloads/${downloadId}/resume`,
      `/v1/local-models/downloads/${downloadId}/retry`,
      `/v1/local-models/downloads/${downloadId}/cancel`,
    ]);
    expect(fetchMock.mock.calls.slice(1).map((call) => JSON.parse(call[1].body as string))).toEqual([
      { expected_status_revision: 6 },
      { expected_status_revision: 7 },
      { expected_status_revision: 8 },
      { expected_status_revision: 9 },
    ]);
  });

  it.each([
    "runtime_activation_superseded",
    "runtime_shutdown_in_progress",
    "runtime_placement_unavailable",
    "runtime_gpu_layers_invalid",
    "runtime_context_unsupported",
  ] as const)(
    "preserves the safe %s lifecycle reason without exposing server detail",
    async (reasonCode) => {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
        .mockResolvedValueOnce(jsonResponse({
          detail: {
            code: reasonCode,
            message: "SYNTHETIC_PRIVATE_RUNTIME_DETAIL_CANARY",
          },
        }, 409));
      const transport = createHttpTransport({
        fetch: fetchMock as unknown as typeof fetch,
        origin: "http://127.0.0.1:4173",
      });

      const error = await transport.switchLocalRuntime({
        alias: "example-model",
        expected_revision: 4,
        device: "cpu",
        gpu_layers: 0,
        context_size: 8192,
        remember: true,
        fast_attention: true,
        tool_calling: true,
      }).catch((caught: unknown) => caught);

      expect(error).toMatchObject({ status: 409, reasonCode });
      expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_RUNTIME_DETAIL_CANARY");
    },
  );

  it("reads only the strict context receipt for the requested Agent chat", async () => {
    const sessionId = "a".repeat(32);
    const receipt = {
      contract_version: "agent-session-context.v1",
      session_id: sessionId,
      revision: 0,
      binding_state: "unmeasured",
      source: "runtime_chat_template_preflight",
      unknown_reason: "no_request_measured",
      turn_id: null,
      turn_number: null,
      model_alias: null,
      observed_at: null,
      context: null,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(receipt))
      .mockResolvedValueOnce(privateJsonResponse({
        ...receipt,
        session_id: "b".repeat(32),
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getAgentSessionContext!(sessionId)).resolves.toEqual(receipt);
    await expect(transport.getAgentSessionContext!(sessionId)).rejects.toMatchObject({ status: 200 });
    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      `/v1/agent/sessions/${sessionId}/context`,
      `/v1/agent/sessions/${sessionId}/context`,
    ]);
  });

  it("reads the strict path-free local model compatibility receipt", async () => {
    const receipt = {
      contract_version: "local-model-compatibility.v1",
      adapter: {
        adapter_id: "llama.cpp-openai-gguf",
        adapter_version: "llama.cpp-openai-gguf.v1",
        runtime_version: null,
        runtime_identity_state: "unknown",
        runtime_binary_sha256: null,
        capability_probe_version: "local-runtime-multimodal-probe.v2",
      },
      models: [{
        alias: "example-model",
        state: "unknown",
        reason_code: "model_not_executed",
        format: "gguf",
        architecture: null,
        tokenizer_model: null,
        training_context_size: null,
        metadata_reader_version: "gguf-metadata.v1",
        artifact_identity_state: "unverified",
        artifact_sha256: null,
        source_revision: null,
        source_license: null,
        source_license_policy: null,
        execution_state: "not_run",
        context_counter_state: "not_run",
      }],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(receipt));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getLocalModelCompatibility?.()).resolves.toMatchObject(receipt);
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/local-models/compatibility");
  });

  it("fails closed on an incoherent runtime status payload", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(localRuntime({
        context: { ...localRuntime().context, limit_tokens: 4096 },
      })));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getLocalRuntime()).rejects.toMatchObject({ status: 200 });
  });

  it("discovers the complete private Agent controller contract and rejects truncation", async () => {
    const valid = exampleAgentOrchestrationManifest();
    const truncated = structuredClone(valid);
    truncated.endpoints.pop();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(valid))
      .mockResolvedValueOnce(privateJsonResponse(truncated));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getAgentOrchestration()).resolves.toMatchObject({
      contract_version: "local-agent-orchestration.v22",
      route_coverage: "all_agent_routes_plus_controller_runtime_routes",
    });
    await expect(transport.getAgentOrchestration()).rejects.toMatchObject({ status: 200 });
    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/agent/orchestration",
      "/v1/agent/orchestration",
    ]);
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({ cache: "no-store" }));
    }
  });

  it("manages direct Agent MCP credentials only through private native-confirmed requests", async () => {
    const connectionId = "a".repeat(32);
    const projectId = "b".repeat(32);
    const sessionId = "c".repeat(32);
    const token = `pemcp2.${connectionId}.1.${"A".repeat(43)}`;
    const endpoint = "http://127.0.0.1:4173/mcp/agent";
    const codexConfig = [
      "[mcp_servers.prompt-enhancer-agent]",
      `url = ${JSON.stringify(endpoint)}`,
      'bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"',
      "tool_timeout_sec = 330",
      'default_tools_approval_mode = "prompt"',
    ].join("\n");
    const claudeConfig = JSON.stringify({
      mcpServers: {
        "prompt-enhancer-agent": {
          type: "http",
          url: endpoint,
          headers: {
            Authorization: "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}",
          },
        },
      },
    });
    const connection = {
      contract_version: "agent-mcp-connection.v4",
      connection_id: connectionId,
      label: "Synthetic Codex connection",
      client_kind: "codex",
      created_at: "2026-08-28T12:00:00+00:00",
      updated_at: "2026-08-28T12:00:00+00:00",
      expires_at: "2026-11-26T12:00:00+00:00",
      last_used_at: null,
      last_tool_at: null,
      last_tool_name: null,
      last_tool_outcome: null,
      last_tool_source: null,
      last_auth_rejected_at: null,
      revoked_at: null,
      revision: 1,
      credential_revision: 1,
      allow_model_lifecycle: false,
      scope: {
        contract_version: "agent-mcp-scope.v1",
        state: "bound",
        project_id: projectId,
        project_name: "Synthetic project",
        catalog_access: "project_only",
        chat_access: "project_only",
        workspace_access: "project_only",
        native_approval_inherited: false,
      },
      state: "active",
    } as const;
    const credential = {
      contract_version: "agent-mcp-connection.v4",
      connection,
      endpoint_url: endpoint,
      bearer_token: token,
      codex_toml: codexConfig,
      claude_json: claudeConfig,
      idempotent_replay: false,
      secret_stored_by_server: false,
      starts_process: false,
      starts_terminal: false,
    } as const;
    const clientSetup = {
      contract_version: "agent-mcp-client-setup.v1",
      endpoint_url: endpoint,
      bearer_token_env_var: "PROMPT_ENHANCER_AGENT_MCP_TOKEN",
      codex_toml: codexConfig,
      claude_json: claudeConfig,
      codex_add_command: `codex mcp add prompt-enhancer-agent --url ${endpoint} --bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN`,
      claude_add_command: `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' prompt-enhancer-agent ${endpoint}`,
      credential_included: false,
      connection_authority_granted: false,
      native_connection_required: true,
      starts_process: false,
      starts_terminal: false,
      provider_configuration_changed: false,
    } as const;
    const rotatedToken = `pemcp2.${connectionId}.2.${"B".repeat(43)}`;
    const rotated = {
      ...credential,
      connection: {
        ...connection,
        revision: 2,
        credential_revision: 2,
      },
      bearer_token: rotatedToken,
      codex_toml: codexConfig,
      claude_json: claudeConfig,
    };
    const revoked = {
      ...rotated.connection,
      updated_at: "2026-08-29T12:00:00+00:00",
      revoked_at: "2026-08-29T12:00:00+00:00",
      revision: 3,
      state: "revoked",
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-mcp-management.v2",
        activity_epoch: "f".repeat(32),
        connections: [connection],
        active_count: 1,
        controller_ownerships: {
          contract_version: "agent-controller-ownership-list.v1",
          ownerships: [],
          active_count: 0,
        },
        tool_activity_sequences: [{
          contract_version: "agent-mcp-tool-activity-sequence.v1",
          connection_id: connection.connection_id,
          credential_revision: connection.credential_revision,
          sequence: 0,
          tool_name: null,
          tool_source: null,
          started_at: null,
          completed_at: null,
          outcome: null,
        }],
      }))
      .mockResolvedValueOnce(privateJsonResponse(clientSetup))
      .mockResolvedValueOnce(privateJsonResponse(credential))
      .mockResolvedValueOnce(privateJsonResponse(rotated))
      .mockResolvedValueOnce(privateJsonResponse(revoked))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-controller-ownership.v1",
        project_id: projectId,
        session_id: sessionId,
        released_connection_id: connectionId,
        released_revision: 4,
        released_at: "2026-08-29T12:01:00+00:00",
        released_by: "native",
        session_settled: true,
        native_approval_inherited: false,
      }));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.listAgentMcpConnections?.()).resolves.toMatchObject({
      active_count: 1,
    });
    await expect(transport.getAgentMcpClientSetup?.()).resolves.toMatchObject({
      endpoint_url: endpoint,
      credential_included: false,
      connection_authority_granted: false,
    });
    await expect(transport.createAgentMcpConnection?.({
      request_id: "1".repeat(32),
      label: "Synthetic Codex connection",
      client_kind: "codex",
      project_id: projectId,
      allow_model_lifecycle: false,
      expires_in_days: 90,
    })).resolves.toMatchObject({ bearer_token: token, starts_process: false });
    await expect(transport.rotateAgentMcpConnection?.(connectionId, {
      request_id: "2".repeat(32),
      expected_revision: 1,
      expires_in_days: 90,
    })).resolves.toMatchObject({ bearer_token: rotatedToken });
    await expect(transport.revokeAgentMcpConnection?.(connectionId, {
      expected_revision: 2,
    })).resolves.toMatchObject({ state: "revoked", revision: 3 });
    await expect(transport.releaseAgentControllerOwnership?.({
      session_id: sessionId,
      expected_revision: 4,
    })).resolves.toMatchObject({
      session_id: sessionId,
      released_by: "native",
      session_settled: true,
    });

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/integrations/agent-mcp/connections",
      "/v1/integrations/agent-mcp/setup",
      "/v1/integrations/agent-mcp/connections",
      `/v1/integrations/agent-mcp/connections/${connectionId}/rotate`,
      `/v1/integrations/agent-mcp/connections/${connectionId}/revoke`,
      "/v1/integrations/agent-mcp/connections/ownerships/release",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: "GET",
      cache: "no-store",
    }));
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: "GET",
      cache: "no-store",
    }));
    expect(fetchMock.mock.calls[2][1]?.headers).not.toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    for (const call of fetchMock.mock.calls.slice(3)) {
      expect(call[1]).toEqual(expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
        }),
      }));
    }
    expect(approveUserPresence).toHaveBeenCalledTimes(4);
  });

  it("uses private, versioned project and catalog-session routes with exact bindings", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-catalog.v2",
        projects: [agentProject()],
      }))
      .mockResolvedValueOnce(privateJsonResponse(agentProject()))
      .mockResolvedValueOnce(privateJsonResponse(agentProject({ name: "Renamed project", revision: 3 })))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-catalog.v2",
        sessions: [agentCatalogSession()],
      }))
      .mockResolvedValueOnce(privateJsonResponse(agentCatalogSession()))
      .mockResolvedValueOnce(privateJsonResponse(agentCatalogSession({ title: "Renamed chat", revision: 3 })))
      .mockResolvedValueOnce(new Response(null, {
        status: 204,
        headers: { "Cache-Control": "no-store, private", Pragma: "no-cache" },
      }))
      .mockResolvedValueOnce(new Response(null, {
        status: 204,
        headers: { "Cache-Control": "no-store, private", Pragma: "no-cache" },
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listAgentProjects({
      search: "Example name",
      includeArchived: true,
      limit: 25,
    })).resolves.toMatchObject({ projects: [{ project_id: AGENT_PROJECT_ID }] });
    await expect(transport.createAgentProject({ name: "Example project" }))
      .resolves.toMatchObject({ project_id: AGENT_PROJECT_ID });
    await expect(transport.updateAgentProject(AGENT_PROJECT_ID, {
      expected_revision: 2,
      name: "Renamed project",
    })).resolves.toMatchObject({ name: "Renamed project", revision: 3 });
    await expect(transport.listAgentCatalogSessions({
      projectId: AGENT_PROJECT_ID,
      includeArchived: false,
      limit: 10,
    })).resolves.toMatchObject({ sessions: [{ session_id: AGENT_CATALOG_SESSION_ID }] });
    await expect(transport.getAgentCatalogSession(AGENT_CATALOG_SESSION_ID))
      .resolves.toMatchObject({ project_id: AGENT_PROJECT_ID });
    await expect(transport.updateAgentCatalogSession(AGENT_CATALOG_SESSION_ID, {
      expected_revision: 2,
      title: "Renamed chat",
    })).resolves.toMatchObject({ title: "Renamed chat", revision: 3 });
    await expect(transport.deleteAgentCatalogSession(AGENT_CATALOG_SESSION_ID, {
      expected_catalog_revision: 3,
      expected_history_revision: 4,
    }))
      .resolves.toBeUndefined();
    await expect(transport.deleteAgentProject(AGENT_PROJECT_ID, {
      expected_revision: 3,
    })).resolves.toBeUndefined();

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/agent/projects?search=Example+name&include_archived=true&limit=25",
    );
    expect(fetchMock.mock.calls[4][0]).toBe(
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions?include_archived=false&limit=10`,
    );
    expect(fetchMock.mock.calls[7][0]).toBe(
      `/v1/agent/catalog/sessions/${AGENT_CATALOG_SESSION_ID}?expected_catalog_revision=3&expected_history_revision=4`,
    );
    expect(fetchMock.mock.calls[8][0]).toBe(
      `/v1/agent/projects/${AGENT_PROJECT_ID}?expected_revision=3`,
    );
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toEqual({
      name: "Example project",
    });
    expect(JSON.parse(fetchMock.mock.calls[3][1].body as string)).toEqual({
      expected_revision: 2,
      name: "Renamed project",
    });
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({ cache: "no-store" }));
    }
  });

  it("uses strict private snapshot-bound pages for Agent projects, chats, and artifacts", async () => {
    const snapshot = "a".repeat(64);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-catalog-page.v1",
        snapshot,
        limit: 100,
        offset: 0,
        total: 1,
        next_offset: null,
        complete: true,
        projects: [agentProject()],
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-catalog-page.v1",
        snapshot,
        limit: 100,
        offset: 100,
        total: 100,
        next_offset: null,
        complete: true,
        sessions: [],
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-artifact-page.v1",
        project_id: AGENT_PROJECT_ID,
        session_id: AGENT_CATALOG_SESSION_ID,
        view: "active",
        snapshot,
        limit: 100,
        offset: 100,
        total: 100,
        next_offset: null,
        complete: true,
        counts: { active: 100, archived: 0, removed: 0, total: 100 },
        artifacts: [],
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.pageAgentProjects!({
      search: "Example name",
      includeArchived: true,
      limit: 100,
      offset: 0,
    })).resolves.toMatchObject({ total: 1, complete: true });
    await expect(transport.pageAgentCatalogSessions!({
      projectId: AGENT_PROJECT_ID,
      includeArchived: false,
      limit: 100,
      offset: 100,
      snapshot,
    })).resolves.toMatchObject({ total: 100, complete: true });
    await expect(transport.pageAgentArtifacts!(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { view: "active", limit: 100, offset: 100, snapshot },
    )).resolves.toMatchObject({ total: 100, counts: { active: 100 } });

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/agent/projects/page?limit=100&offset=0&search=Example+name&include_archived=true",
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/page?limit=100&offset=100&include_archived=false&snapshot=${snapshot}`,
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/artifacts/page?view=active&limit=100&offset=100&snapshot=${snapshot}`,
    ]);
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({
        method: "GET",
        cache: "no-store",
      }));
    }
  });

  it("rejects invalid Agent page continuations before bootstrap or network access", async () => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.pageAgentProjects!({ offset: 1 }))
      .rejects.toMatchObject({ status: 422 });
    await expect(transport.pageAgentCatalogSessions!({ limit: 101 }))
      .rejects.toMatchObject({ status: 422 });
    await expect(transport.pageAgentArtifacts!(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { offset: 1, snapshot: "not-a-snapshot" },
    )).rejects.toMatchObject({ status: 422 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forks retained Agent history through the exact private idempotent endpoint", async () => {
    const requestId = "6".repeat(32);
    const childSessionId = "7".repeat(32);
    const receipt = {
      contract_version: "agent-session-fork.v1",
      request_id: requestId,
      idempotent_replay: false,
      session: agentCatalogSession({
        session_id: childSessionId,
        title: "Example branch",
        history_state: "durable_local",
        retention_policy: "local_history",
        history_revision: 4,
        last_event_seq: 4,
        turn_count: 1,
        conversation_available: true,
        lineage: {
          contract_version: "agent-session-lineage.v1",
          source_project_id: AGENT_PROJECT_ID,
          source_session_id: AGENT_CATALOG_SESSION_ID,
          source_catalog_revision: 2,
          source_history_revision: 4,
          branch_event_seq: 4,
          copied_event_count: 4,
          copied_turn_count: 1,
          copied_attachment_count: 0,
          created_at: "2040-01-01T10:00:00Z",
        },
      }),
      source_tail_omitted: false,
      approvals_copied: false,
      mutation_authority_copied: false,
      pending_tool_state_copied: false,
      staged_attachments_copied: false,
      artifacts_copied: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(receipt));
    const approveUserPresence = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });
    const command = {
      request_id: requestId,
      expected_catalog_revision: 2,
      expected_history_revision: 4,
      destination_project_id: null,
      through_event_seq: 4,
      title: "Example branch",
    };

    await expect(transport.forkAgentSession(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      command,
    )).resolves.toMatchObject({
      request_id: requestId,
      session: { session_id: childSessionId },
      mutation_authority_copied: false,
    });
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/forks`,
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      method: "POST",
    }));
    expect(fetchMock.mock.calls[1][1].headers).toEqual(expect.objectContaining({
      "Content-Type": "application/json",
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
    }));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual(command);
    expect(approveUserPresence).not.toHaveBeenCalled();
  });

  it("loads, resumes, exports, and natively revalidates retained Agent history", async () => {
    const retainedEvent = {
      seq: 1,
      at: "2040-01-01T10:00:00Z",
      kind: "status",
      text: "Synthetic retained state.",
    };
    const retainedPage = {
      contract_version: "local-agent.v9",
      session_id: AGENT_CATALOG_SESSION_ID,
      events: [retainedEvent],
      running: false,
      closing: false,
      stopping: false,
      cleanup_unconfirmed: false,
      pending_approval_id: null,
      last_seq: 1,
      first_seq: 1,
    };
    const recovered = exampleAgentSession({
      session_id: AGENT_CATALOG_SESSION_ID,
      last_seq: 1,
      history_revision: 1,
      recovered: true,
      authority_revalidated: false,
      recovery_state: "recovered",
      settings: {
        ...exampleAgentSession().settings,
        project_id: AGENT_PROJECT_ID,
        title: "Example chat",
        retention_policy: "local_history",
        allow_writes: false,
        allow_commands: false,
        allow_web: false,
      },
    });
    const revalidated = {
      ...recovered,
      authority_revalidated: true,
      settings: { ...recovered.settings, allow_writes: true },
    };
    const exported = {
      contract_version: "agent-history.v1",
      exported_at: "2040-01-01T10:05:00Z",
      project_id: AGENT_PROJECT_ID,
      session_id: AGENT_CATALOG_SESSION_ID,
      title: "Example chat",
      workspace: "D:\\example\\workspace",
      model_alias: "example-model",
      history_revision: 1,
      turn_count: 0,
      interrupted: false,
      events: [retainedEvent],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(retainedPage))
      .mockResolvedValueOnce(privateJsonResponse(recovered))
      .mockResolvedValueOnce(privateJsonResponse(exported))
      .mockResolvedValueOnce(privateJsonResponse(revalidated));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.getAgentPersistedEvents(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      0,
    )).resolves.toMatchObject({ last_seq: 1, events: [{ kind: "status" }] });
    await expect(transport.resumeAgentSession(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { expected_catalog_revision: 2, expected_history_revision: 1 },
    )).resolves.toMatchObject({ recovered: true, authority_revalidated: false });
    await expect(transport.exportAgentHistory(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { expected_catalog_revision: 2, expected_history_revision: 1 },
    ))
      .resolves.toMatchObject({ history_revision: 1, project_id: AGENT_PROJECT_ID });
    await expect(transport.revalidateAgentAuthority(AGENT_CATALOG_SESSION_ID, {
      expected_catalog_revision: 2,
      allow_writes: true,
      allow_commands: false,
      allow_web: false,
    })).resolves.toMatchObject({ authority_revalidated: true, settings: { allow_writes: true } });

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/events?after=0&limit=8`,
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/resume`,
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/export?expected_catalog_revision=2&expected_history_revision=1`,
      `/v1/agent/sessions/${AGENT_CATALOG_SESSION_ID}/authority`,
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toEqual({
      expected_catalog_revision: 2,
      expected_history_revision: 1,
    });
    const authorityRequest = fetchMock.mock.calls[4][1] as RequestInit;
    expect(authorityRequest.headers).toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
    }));
    expect(approveUserPresence).toHaveBeenCalledWith(expect.objectContaining({
      method: "POST",
      path: `/v1/agent/sessions/${AGENT_CATALOG_SESSION_ID}/authority`,
    }));
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toEqual(expect.objectContaining({ cache: "no-store" }));
    }
  });

  it.each([
    { expected_catalog_revision: 0, expected_history_revision: 1 },
    { expected_catalog_revision: 2, expected_history_revision: -1 },
    { expected_catalog_revision: 2.5, expected_history_revision: 1 },
  ])("rejects invalid retained export heads before any network read: %o", async (request) => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.exportAgentHistory(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      request,
    )).rejects.toMatchObject({ status: 400 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lists, opens, natively captures, and safely reads Agent artifacts", async () => {
    const payload = "Synthetic artifact preview.\n";
    const detail = { ...agentArtifact(), versions: [agentArtifactVersion()] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-artifact.v3",
        project_id: AGENT_PROJECT_ID,
        session_id: AGENT_CATALOG_SESSION_ID,
        view: "active",
        counts: { active: 1, archived: 0, removed: 0, total: 1 },
        artifacts: [agentArtifact({ availability: "unchecked" })],
      }))
      .mockResolvedValueOnce(privateJsonResponse(detail))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-artifact-capture-preview.v1",
        project_id: AGENT_PROJECT_ID,
        session_id: AGENT_CATALOG_SESSION_ID,
        path: "docs/example.md",
        title: "example.md",
        kind: "markdown",
        media_type: "text/markdown; charset=utf-8",
        preview_kind: "text",
        sha256: "5".repeat(64),
        byte_size: 27,
        requires_native_confirmation: true,
        file_content_included: false,
      }))
      .mockResolvedValueOnce(privateJsonResponse(detail, 201))
      .mockResolvedValueOnce(privateJsonResponse(agentArtifactExport()))
      .mockResolvedValueOnce(privateArtifactResponse(payload));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });
    const base = `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/artifacts`;

    await expect(transport.listAgentArtifacts(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
    )).resolves.toMatchObject({ artifacts: [{ artifact_id: AGENT_ARTIFACT_ID }] });
    await expect(transport.getAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
    )).resolves.toMatchObject({ availability: "available", versions: [{ version_number: 1 }] });
    await expect(transport.previewAgentArtifactCapture(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { path: "docs/example.md" },
    )).resolves.toMatchObject({
      path: "docs/example.md",
      sha256: "5".repeat(64),
      file_content_included: false,
    });
    await expect(transport.captureAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      {
        path: "docs/example.md",
        expected_sha256: "5".repeat(64),
        expected_byte_size: 27,
      },
    )).resolves.toMatchObject({ artifact_id: AGENT_ARTIFACT_ID });
    await expect(transport.exportAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 1, version_id: AGENT_ARTIFACT_VERSION_ID },
    )).resolves.toMatchObject({
      contract_version: "agent-artifact-export.v1",
      content_included: false,
      absolute_path_included: false,
      evidence: { verified: true, sha256: "5".repeat(64) },
    });
    const content = await transport.getAgentArtifactContent(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      AGENT_ARTIFACT_VERSION_ID,
      false,
    );
    expect(content.contentType).toBe("text/plain; charset=utf-8");
    expect(content.filename).toBe(`agent-artifact-${AGENT_ARTIFACT_ID.slice(0, 8)}`);
    await expect(content.blob.text()).resolves.toBe(payload);

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      `${base}?view=active`,
      `${base}/${AGENT_ARTIFACT_ID}`,
      `${base}/capture-preview`,
      base,
      `${base}/${AGENT_ARTIFACT_ID}/export`,
      `${base}/${AGENT_ARTIFACT_ID}/versions/${AGENT_ARTIFACT_VERSION_ID}/content`,
    ]);
    expect(approveUserPresence).toHaveBeenCalledWith(expect.objectContaining({
      method: "POST",
      path: base,
    }));
    expect(fetchMock.mock.calls[4][1].headers).toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    expect(fetchMock.mock.calls[5][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
    }));
    expect(fetchMock.mock.calls[6][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      credentials: "include",
      redirect: "error",
    }));
  });

  it("updates artifact lifecycle by revision and natively confirms reversible removal", async () => {
    const archived = agentArtifact({
      lifecycle_state: "archived",
      archived_at: "2040-01-01T10:02:00Z",
      updated_at: "2040-01-01T10:02:00Z",
      revision: 2,
    });
    const removed = agentArtifact({
      lifecycle_state: "removed",
      archived_at: "2040-01-01T10:02:00Z",
      removed_at: "2040-01-01T10:03:00Z",
      updated_at: "2040-01-01T10:03:00Z",
      revision: 3,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(archived))
      .mockResolvedValueOnce(privateJsonResponse(removed));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });
    const path = `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/artifacts/${AGENT_ARTIFACT_ID}`;

    await expect(transport.updateAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 1, operation: "archive" },
    )).resolves.toMatchObject({ lifecycle_state: "archived", revision: 2 });
    await expect(transport.removeAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      {
        expected_revision: 2,
        confirmation: "move_archived_artifact_record_to_removed",
      },
    )).resolves.toMatchObject({ lifecycle_state: "removed", revision: 3 });

    expect(fetchMock.mock.calls[1][0]).toBe(path);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      body: JSON.stringify({ expected_revision: 1, operation: "archive" }),
      cache: "no-store",
      method: "PATCH",
    }));
    expect(fetchMock.mock.calls[1][1].headers).not.toHaveProperty("X-Prompt-Enhancer-User-Presence");
    expect(fetchMock.mock.calls[2][0]).toBe(`${path}/remove`);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      body: JSON.stringify({
        expected_revision: 2,
        confirmation: "move_archived_artifact_record_to_removed",
      }),
      cache: "no-store",
      method: "POST",
    }));
    expect(fetchMock.mock.calls[2][1].headers).toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    expect(approveUserPresence).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      method: "POST",
      path: `${path}/remove`,
    }));
  });

  it("rejects malformed artifact lifecycle commands before network access", async () => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.updateAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 1, operation: "rename", title: "  untrimmed  " },
    )).rejects.toMatchObject({ status: 400 });
    await expect(transport.removeAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 0, confirmation: "move_archived_artifact_record_to_removed" },
    )).rejects.toMatchObject({ status: 400 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects cacheable or executable artifact content responses", async () => {
    const missingSafety = new Response("Synthetic artifact", {
      status: 200,
      headers: {
        "Content-Type": "text/html",
        "Content-Length": "18",
        "Content-Disposition": `inline; filename="agent-artifact-${AGENT_ARTIFACT_ID.slice(0, 8)}"`,
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(missingSafety);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getAgentArtifactContent(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      AGENT_ARTIFACT_VERSION_ID,
      false,
    )).rejects.toThrow("Agent artifact content response was invalid");
  });

  it("rejects malformed or contradictory artifact lineage exports", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(agentArtifactExport({
        content_included: true,
      })));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.exportAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 1, version_id: AGENT_ARTIFACT_VERSION_ID },
    )).rejects.toThrow("Agent artifact export response was invalid");

    const noNetwork = vi.fn();
    const guarded = createHttpTransport({
      fetch: noNetwork as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(guarded.exportAgentArtifact(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      { expected_revision: 0, version_id: AGENT_ARTIFACT_VERSION_ID },
    )).rejects.toMatchObject({ status: 400 });
    expect(noNetwork).not.toHaveBeenCalled();
  });

  it("loads only an exact no-store document projection bound to the selected artifact version", async () => {
    const selected = agentArtifactVersion({
      path: "docs/synthetic-review.docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      preview_kind: "document",
      byte_size: 512,
    }) as AgentArtifactVersion;
    const projection = {
      contract_version: "agent-document-preview.v1",
      project_id: AGENT_PROJECT_ID,
      session_id: AGENT_CATALOG_SESSION_ID,
      artifact_id: AGENT_ARTIFACT_ID,
      version_id: AGENT_ARTIFACT_VERSION_ID,
      source_sha256: selected.sha256,
      source_byte_size: selected.byte_size,
      format: "docx",
      sections: [{
        index: 1,
        kind: "document",
        title: "Document",
        paragraphs: ["Synthetic local projection"],
        rows: [],
        truncated: false,
      }],
      omitted_features: ["media"],
      truncated: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(projection));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getAgentArtifactDocumentPreview(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      selected,
    )).resolves.toMatchObject({
      format: "docx",
      sections: [{ paragraphs: ["Synthetic local projection"] }],
    });
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/agent/projects/${AGENT_PROJECT_ID}/sessions/${AGENT_CATALOG_SESSION_ID}/artifacts/${AGENT_ARTIFACT_ID}/versions/${AGENT_ARTIFACT_VERSION_ID}/preview`,
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      credentials: "include",
      redirect: "error",
    }));

    const mismatchFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        ...projection,
        source_sha256: "9".repeat(64),
      }));
    const mismatchTransport = createHttpTransport({
      fetch: mismatchFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(mismatchTransport.getAgentArtifactDocumentPreview(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      AGENT_ARTIFACT_ID,
      selected,
    )).rejects.toMatchObject({ status: 200 });
  });

  it("fails closed on cross-project recovery and forbidden retained export material", async () => {
    const mismatchedRecovery = exampleAgentSession({
      session_id: AGENT_CATALOG_SESSION_ID,
      recovered: true,
      authority_revalidated: false,
      recovery_state: "recovered",
      settings: {
        ...exampleAgentSession().settings,
        project_id: "9".repeat(32),
        retention_policy: "local_history",
        allow_writes: false,
        allow_commands: false,
        allow_web: false,
      },
    });
    const mismatchFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(mismatchedRecovery));
    const mismatchTransport = createHttpTransport({
      fetch: mismatchFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(mismatchTransport.resumeAgentSession(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { expected_catalog_revision: 2, expected_history_revision: 0 },
    )).rejects.toMatchObject({ status: 200 });

    const forbiddenExport = {
      contract_version: "agent-history.v1",
      exported_at: "2040-01-01T10:05:00Z",
      project_id: AGENT_PROJECT_ID,
      session_id: AGENT_CATALOG_SESSION_ID,
      title: "Example chat",
      workspace: "D:\\example\\workspace",
      model_alias: "example-model",
      history_revision: 1,
      turn_count: 0,
      interrupted: false,
      events: [{
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "status",
        text: "Synthetic retained state.",
        approval_id: "8".repeat(32),
      }],
    };
    const exportFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(forbiddenExport));
    const exportTransport = createHttpTransport({
      fetch: exportFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(exportTransport.exportAgentHistory(
      AGENT_PROJECT_ID,
      AGENT_CATALOG_SESSION_ID,
      { expected_catalog_revision: 2, expected_history_revision: 1 },
    ))
      .rejects.toMatchObject({ status: 200 });
  });

  it("fails closed on mismatched or cacheable Agent catalog responses", async () => {
    const mismatched = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(agentProject({ project_id: "3".repeat(32) })));
    const mismatchTransport = createHttpTransport({
      fetch: mismatched as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(mismatchTransport.getAgentProject(AGENT_PROJECT_ID))
      .rejects.toMatchObject({ status: 200 });

    const cacheable = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({
        contract_version: "agent-catalog.v2",
        sessions: [agentCatalogSession()],
      }));
    const cacheableTransport = createHttpTransport({
      fetch: cacheable as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(cacheableTransport.listAgentCatalogSessions())
      .rejects.toThrow("Private local response was not cache-safe");
  });

  it("preserves only closed Agent catalog failure codes", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "agent_catalog_session_revision_conflict",
          message: "SYNTHETIC-PRIVATE-CANARY",
        },
      }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const error = await transport.updateAgentCatalogSession(
      AGENT_CATALOG_SESSION_ID,
      { expected_revision: 1, pinned: true },
    ).catch((caught: unknown) => caught);
    expect(error).toMatchObject({
      status: 409,
      reasonCode: "agent_catalog_session_revision_conflict",
    });
    expect(String(error)).not.toContain("SYNTHETIC-PRIVATE-CANARY");
  });

  it.each([
    "workspace_root_changed",
    "workspace_inspection_timeout",
    "workspace_write_failed",
    "workspace_cleanup_failed",
    "workspace_verification_failed",
    "workspace_parent_unavailable",
    "workspace_path_not_found",
    "workspace_directory_unavailable",
    "workspace_not_a_directory",
    "workspace_revision_changed",
    "workspace_link_or_reparse_refused",
    "path_invalid",
    "path_outside_workspace",
    "workspace_directory_create_failed",
    "workspace_directory_create_unverified",
    "workspace_directory_move_into_self",
    "workspace_directory_move_unsupported",
    "workspace_directory_move_failed",
    "workspace_directory_move_unverified",
    "workspace_file_trash_unsupported",
    "workspace_file_trash_failed",
    "workspace_file_trash_unverified",
  ] as const)("preserves only the fixed %s workspace reason", async (code) => {
    const status = code === "workspace_inspection_timeout"
      || code === "workspace_write_failed"
      || code === "workspace_cleanup_failed"
      || code === "workspace_directory_create_failed"
      || code === "workspace_directory_move_failed"
      || code === "workspace_file_trash_failed"
      ? 503
      : code === "workspace_parent_unavailable" || code === "path_invalid"
        || code === "workspace_directory_unavailable"
        || code === "workspace_not_a_directory"
        || code === "workspace_directory_move_into_self"
        || code === "workspace_directory_move_unsupported"
        || code === "workspace_file_trash_unsupported"
        ? 422
        : code === "workspace_path_not_found"
          ? 404
        : code === "workspace_link_or_reparse_refused" || code === "path_outside_workspace"
          ? 403
          : 409;
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code, message: "EXAMPLE_PRIVATE_WORKSPACE_CANARY" } }, status));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport.getAgentWorkspaceTree("a".repeat(32), ".").catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status, reasonCode: code });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_WORKSPACE_CANARY");
  });

  it.each(["get", "list", "send", "stop", "create"])("does not accept missing cleanup authority from %s", async (operation) => {
    const invalid = { ...exampleAgentSession(), cleanup_unconfirmed: undefined };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(operation === "list" ? [invalid] : invalid));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const result = operation === "get" ? transport.getAgentSession("a".repeat(32))
      : operation === "list" ? transport.listAgentSessions()
      : operation === "send" ? transport.sendAgentMessage("a".repeat(32), "Example message")
      : operation === "stop" ? transport.stopAgentSession("a".repeat(32))
      : transport.createAgentSession(exampleAgentSession().settings);
    await expect(result).rejects.toMatchObject({ status: 200 });
  });

  it("keeps the command cleanup reason but never its internal exception", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "command_cleanup_unconfirmed", message: "EXAMPLE_PRIVATE_CANARY" } }, 409));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport.sendAgentMessage("a".repeat(32), "Example request").catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 409, reasonCode: "command_cleanup_unconfirmed" });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_CANARY");
  });

  it("preserves the allowlisted model-not-ready reason when session creation is rejected", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "model_not_ready" } }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.createAgentSession(AGENT_SETTINGS)).rejects.toMatchObject({
      status: 409,
      reasonCode: "model_not_ready",
    });
  });

  it.each(["model_not_ready", "no_active_model", "turn_in_progress", "session_closing"] as const)(
    "preserves the %s reason when a message is rejected",
    async (reasonCode) => {
    const sessionId = "a".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: reasonCode } }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.sendAgentMessage(sessionId, "Synthetic request")).rejects.toMatchObject({
      status: 409,
      reasonCode,
    });
    },
  );

  it("preserves the close-timeout recovery code without forwarding server content", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "session_stop_timeout", message: "Synthetic internal detail" } }, 409));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport.deleteAgentSession("a".repeat(32)).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 409, reasonCode: "session_stop_timeout" });
    expect(String(error)).not.toContain("Synthetic internal detail");
  });

  it("accepts the documented empty 204 response when an Agent session is closed", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.deleteAgentSession("a".repeat(32))).resolves.toBeUndefined();
  });

  it("does not mistake an unexpected 200 JSON response for a confirmed session deletion", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: "Synthetic unexpected response" }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.deleteAgentSession("a".repeat(32))).rejects.toMatchObject({ status: 200 });
  });

  it("preserves the documented inactive-model reason for judge failures", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "model_not_active" } }, 409));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.judgeSessionWithModel("a".repeat(64))).rejects.toMatchObject({ status: 409, reasonCode: "model_not_active" });
  });

  it.each(["review", "save"])("keeps the closed calibration receipt failure for %s", async (operation) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "calibration_review_expired", message: "SYNTHETIC_PRIVATE_CANARY" } }, 409));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const result = operation === "review" ? transport.reviewCalibrationCase("a".repeat(64), 15000)
      : transport.submitCalibrationRatings({ session_id: "a".repeat(64), rater_label: "Example rater", ratings: { "prompt.task_definition_coverage": "high" }, review_id: "b".repeat(32) });
    const error = await result.catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 409, reasonCode: "calibration_review_expired" });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("content-type")).toBe("application/json");
  });

  it("refuses reviewed evidence from a cacheable response", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE)).mockResolvedValueOnce(jsonResponse({}));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.reviewCalibrationCase("a".repeat(64), 6000)).rejects.toMatchObject({ status: 200 });
  });

  it.each(["judgeSessionWithModel", "interpretSessionWithModel"] as const)("preserves only the closed invalid-reply reason for %s", async (operation) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "model_reply_invalid", message: "SYNTHETIC_PRIVATE_CANARY" } }, 502));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport[operation]("a".repeat(64)).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 502, reasonCode: "model_reply_invalid" });
    expect(String(error)).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });
});

describe("local agent event streaming transport", () => {
  it("consumes private same-origin SSE through the browser session", async () => {
    const sessionId = "a".repeat(32);
    const streamId = "b".repeat(32);
    const payload = {
      contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
      session_id: sessionId,
      events: [{
        seq: 1,
        at: "2026-08-20T01:00:00Z",
        kind: "assistant_delta",
        text: "Hello",
        reasoning: null,
        stream_id: streamId,
        stream_phase: "content",
        stream_status: null,
        tool: null,
        arguments: null,
        call_id: null,
        approval_id: null,
        ok: null,
        preview: null,
      }],
      running: false,
      pending_approval_id: null,
      last_seq: 1,
      first_seq: 1,
    };
    const encoded = new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
    const eventResponse = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoded.slice(0, 17));
        controller.enqueue(encoded.slice(17));
        controller.close();
      },
    }), {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(eventResponse);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const pages: unknown[] = [];

    await transport.streamAgentEvents(sessionId, 0, (page) => pages.push(page));

    expect(pages).toHaveLength(1);
    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/events/stream?after=0&limit=8`);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
    }));
    expect(fetchMock.mock.calls[1][1]?.headers).toEqual({ Accept: "text/event-stream" });
  });
});

describe("local agent reviewed change-set transport", () => {
  const sessionId = "a".repeat(32);
  const summary = {
    path: "src/example.ts",
    net_effect: "modified",
    verification: "verified",
    reason: null,
    reviewed_writes: 1,
    agent_writes: 1,
    manual_writes: 0,
    current_byte_size: 12,
    diff_available: true,
  };

  it("uses private relative GET routes and strict response parsing", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-change-set.v1",
        session_id: sessionId,
        scope: "reviewed_paths_only",
        coverage: "complete",
        settled: true,
        reviewed_writes: 1,
        verified_writes: 1,
        unverified_writes: 0,
        agent_writes: 1,
        manual_writes: 0,
        reviewed_noops: 0,
        command_attempts: 0,
        omitted_write_receipts: 0,
        tracking_failed: false,
        files: [summary],
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-change-set.v1",
        session_id: sessionId,
        summary,
        diff_state: "available",
        diff: "--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-old\n+new",
        added_lines: 1,
        removed_lines: 1,
      }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.getAgentChangeSet(sessionId)).resolves.toMatchObject({ coverage: "complete" });
    await expect(transport.getAgentChangeDiff(sessionId, "src/example.ts")).resolves.toMatchObject({ diff_state: "available" });
    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/changes`);
    expect(fetchMock.mock.calls[2][0]).toBe(`/v1/agent/sessions/${sessionId}/changes/diff?path=src%2Fexample.ts`);
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(call[1]).toMatchObject({ method: "GET", cache: "no-store", credentials: "include", redirect: "error", referrerPolicy: "no-referrer" });
      expect((call[1] as RequestInit).headers).not.toEqual(expect.objectContaining({
        "X-Prompt-Enhancer-User-Presence": expect.anything(),
      }));
    }
  });

  it.each(["set", "diff"] as const)("rejects %s content without private no-store response headers", async (operation) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ content: "EXAMPLE_PRIVATE_CHANGE_CANARY" }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const request = operation === "set"
      ? transport.getAgentChangeSet(sessionId)
      : transport.getAgentChangeDiff(sessionId, "src/example.ts");
    const error = await request.catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 200 });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_CHANGE_CANARY");
  });

  it("preserves only the fixed missing-path reason from a rejected diff read", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: {
          code: "change_path_not_found",
          message: "EXAMPLE_PRIVATE_CHANGE_CANARY",
        },
      }, 404));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const error = await transport.getAgentChangeDiff(sessionId, "src/example.ts").catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 404, reasonCode: "change_path_not_found" });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_CHANGE_CANARY");
  });

  it("previews and applies an exact revision-bound restore with native confirmation", async () => {
    const path = "src/example.ts";
    const previewId = "d".repeat(32);
    const currentRevision = "b".repeat(64);
    const baselineRevision = "c".repeat(64);
    const preview = {
      contract_version: "agent-change-restore.v1",
      session_id: sessionId,
      preview_id: previewId,
      path,
      operation: "edit",
      baseline_state: "present",
      expected_revision: currentRevision,
      restored_revision: baselineRevision,
      restored_byte_size: 9,
      line_ending: "lf",
      diff_state: "available",
      diff: `--- a/${path}\n+++ b/${path}\n@@ -1 +1 @@\n-current\n+baseline`,
      added_lines: 1,
      removed_lines: 1,
      recovery: "revision_bound_write",
      permanent: false,
      expires_at: "2030-01-02T03:04:05Z",
      requires_native_confirmation: true,
    } as const;
    const result = {
      contract_version: "agent-change-restore.v1",
      session_id: sessionId,
      path,
      operation: "edit",
      baseline_state: "present",
      current_revision: baselineRevision,
      current_byte_size: 9,
      recovery: "revision_bound_write",
      permanent: false,
      net_effect: "reverted",
      filesystem_verification: "verified",
      change_set_verification: "verified",
      change_set_reason: null,
      applied: true,
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(preview, 201))
      .mockResolvedValueOnce(privateJsonResponse(result));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });
    const previewRequest = { path };
    await expect(transport.previewAgentChangeRestore(sessionId, previewRequest)).resolves.toMatchObject({
      preview_id: previewId,
      operation: "edit",
    });
    const applyRequest = {
      path,
      operation: "edit",
      expected_revision: currentRevision,
      restored_revision: baselineRevision,
      confirmation: "apply_reviewed_change_restore",
    } as const;
    await expect(transport.applyAgentChangeRestore(
      sessionId,
      previewId,
      applyRequest,
    )).resolves.toMatchObject({ applied: true, net_effect: "reverted" });

    const previewCall = fetchMock.mock.calls[1];
    expect(previewCall[0]).toBe(`/v1/agent/sessions/${sessionId}/changes/restores`);
    expect(previewCall[1]).toMatchObject({ method: "POST", cache: "no-store" });
    expect((previewCall[1] as RequestInit).headers).not.toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": expect.anything(),
    }));
    const applyPath = `/v1/agent/sessions/${sessionId}/changes/restores/${previewId}/apply`;
    const applyCall = fetchMock.mock.calls[2];
    expect(applyCall[0]).toBe(applyPath);
    expect((applyCall[1] as RequestInit).headers).toEqual(expect.objectContaining({
      "Content-Type": "application/json",
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    expect(approveUserPresence).toHaveBeenCalledExactlyOnceWith({
      method: "POST",
      path: applyPath,
      bodySha256: await sha256(JSON.stringify(applyRequest)),
    });
  });

  it("rejects restore response authority drift without exposing response content", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "agent-change-restore.v1",
        session_id: sessionId,
        preview_id: "d".repeat(32),
        path: "private/canary.ts",
        operation: "edit",
        baseline_state: "present",
        expected_revision: "b".repeat(64),
        restored_revision: "c".repeat(64),
        restored_byte_size: 9,
        line_ending: "lf",
        diff_state: "available",
        diff: "EXAMPLE_PRIVATE_CHANGE_CANARY",
        added_lines: 1,
        removed_lines: 1,
        recovery: "revision_bound_write",
        permanent: false,
        expires_at: "2030-01-02T03:04:05Z",
        requires_native_confirmation: true,
      }, 201));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const error = await transport.previewAgentChangeRestore(
      sessionId,
      { path: "src/example.ts" },
    ).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 200 });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_CHANGE_CANARY");
  });

  it("preserves only an allowlisted restore refusal code", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: {
          code: "change_restore_baseline_unavailable",
          message: "EXAMPLE_PRIVATE_CHANGE_CANARY",
        },
      }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const error = await transport.previewAgentChangeRestore(
      sessionId,
      { path: "src/example.ts" },
    ).catch((caught: unknown) => caught);
    expect(error).toMatchObject({
      status: 409,
      reasonCode: "change_restore_baseline_unavailable",
    });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_CHANGE_CANARY");
  });
});

describe("local agent workspace transport", () => {
  it.each(["discovery", "tree", "search", "file", "preview"] as const)("rejects %s data without private no-store response headers", async (operation) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse({ content: "EXAMPLE_PRIVATE_WORKSPACE_CANARY" }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    const id = "a".repeat(32);
    const request = operation === "discovery" ? transport.getAgentWorkspaceDiscovery(id)
      : operation === "tree" ? transport.getAgentWorkspaceTree(id, ".")
      : operation === "search" ? transport.getAgentWorkspaceSearch(id, { query: "example", glob: "**/*", regex: false })
      : operation === "file" ? transport.getAgentWorkspaceFile(id, "example.txt")
      : transport.previewAgentWorkspaceEdit(id, { path: "example.txt", content: "example", expected_revision: "b".repeat(64), line_ending: "lf" });
    const error = await request.catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 200 });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_WORKSPACE_CANARY");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ cache: "no-store", credentials: "include", redirect: "error", referrerPolicy: "no-referrer" });
  });

  it("searches through the exact private route and rejects response path drift", async () => {
    const sessionId = "a".repeat(32);
    const valid = {
      contract_version: "local-agent-workspace-search.v1",
      session_id: sessionId,
      scope: "application_readable_utf8_text",
      coverage: "complete",
      reasons: [],
      reason_code: null,
      scanned_entry_count: 3,
      inspected_byte_count: 120,
      skipped_entry_count: 0,
      match_count: 1,
      matches: [{ path: "src/app.ts", line_number: 4, preview: "const synthetic = true;" }],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(valid))
      .mockResolvedValueOnce(privateJsonResponse({
        ...valid,
        matches: [{ path: "C:/private.txt", line_number: 4, preview: "private" }],
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const request = { query: "synthetic", glob: "src/**/*.ts", regex: true };

    await expect(transport.getAgentWorkspaceSearch(sessionId, request)).resolves.toMatchObject({
      coverage: "complete",
      match_count: 1,
    });
    const params = new URLSearchParams({ query: request.query, glob: request.glob, regex: "true" });
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/agent/sessions/${sessionId}/workspace/search?${params.toString()}`,
    );
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "GET",
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    await expect(transport.getAgentWorkspaceSearch(sessionId, request)).rejects.toMatchObject({
      message: "Local agent workspace search response was invalid",
      status: 200,
    });
  });

  it("loads discovery from the exact private session route and rejects path authority drift", async () => {
    const sessionId = "a".repeat(32);
    const valid = {
      contract_version: "local-agent-workspace-discovery.v1",
      session_id: sessionId,
      scope: "selected_workspace",
      inventory_coverage: "complete",
      inventory_reasons: [],
      scanned_entry_count: 1,
      observed_file_count: 1,
      files: [{ path: "example.txt", byte_size: 7, editable_candidate: true }],
      git_state: "not_repository",
      git_coverage: "not_applicable",
      git_reasons: [],
      git_change_count: 0,
      git_changes: [],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(valid))
      .mockResolvedValueOnce(privateJsonResponse({
        ...valid,
        files: [{ path: "C:/private.txt", byte_size: 7, editable_candidate: true }],
      }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });

    await expect(transport.getAgentWorkspaceDiscovery(sessionId)).resolves.toMatchObject({
      session_id: sessionId,
      observed_file_count: 1,
      git_state: "not_repository",
    });
    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/discovery`);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      cache: "no-store",
      credentials: "include",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    await expect(transport.getAgentWorkspaceDiscovery(sessionId)).rejects.toMatchObject({
      message: "Local agent workspace discovery response was invalid",
      status: 200,
    });
  });

  it("uses relative session-bound routes and strict response parsing", async () => {
    const sessionId = "a".repeat(32);
    const base = "b".repeat(64);
    const proposed = "c".repeat(64);
    const previewId = "d".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: ".",
        entries: [{ path: "src", name: "src", kind: "directory", byte_size: null, editable_candidate: false }],
        complete: true,
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: "src/app.py",
        content: "one\ntwo\n",
        revision: base,
        byte_size: 8,
        line_ending: "lf",
        editable: true,
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        preview_id: previewId,
        path: "src/app.py",
        expected_revision: base,
        proposed_revision: proposed,
        line_ending: "lf",
        diff: "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n one\n-two\n+new",
        expires_at: "2026-08-20T20:00:00Z",
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: "src/app.py",
        revision: proposed,
        byte_size: 8,
        applied: true,
      }));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.getAgentWorkspaceTree(sessionId, ".")).resolves.toMatchObject({ path: "." });
    await expect(transport.getAgentWorkspaceFile(sessionId, "src/app.py")).resolves.toMatchObject({ revision: base });
    const previewRequest = { path: "src/app.py", content: "one\nnew\n", expected_revision: base, line_ending: "lf" as const };
    await expect(transport.previewAgentWorkspaceEdit(sessionId, previewRequest)).resolves.toMatchObject({ preview_id: previewId });
    const applyRequest = {
      path: "src/app.py",
      content: "one\nnew\n",
      expected_revision: base,
      proposed_revision: proposed,
      line_ending: "lf",
      confirmation: "apply_reviewed_workspace_edit",
    } as const;
    await expect(transport.applyAgentWorkspaceEdit(sessionId, previewId, applyRequest)).resolves.toMatchObject({ applied: true });

    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/tree?path=.`);
    expect(fetchMock.mock.calls[2][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/file?path=src%2Fapp.py`);
    expect(fetchMock.mock.calls[3][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/previews`);
    expect(fetchMock.mock.calls[4][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/previews/${previewId}/apply`);
    for (const call of fetchMock.mock.calls.slice(1)) expect(call[1]).toMatchObject({ cache: "no-store" });
    const apply = fetchMock.mock.calls[4][1] as RequestInit;
    expect(apply.headers).toEqual(expect.objectContaining({
      "Content-Type": "application/json",
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    expect(approveUserPresence).toHaveBeenCalledOnce();
    expect(approveUserPresence).toHaveBeenCalledWith({
      method: "POST",
      path: `/v1/agent/sessions/${sessionId}/workspace/previews/${previewId}/apply`,
      bodySha256: await sha256(JSON.stringify(applyRequest)),
    });
  });

  it("binds reviewed workspace create, directory create/move, and file move operations to native confirmation", async () => {
    const sessionId = "a".repeat(32);
    const createPreviewId = "b".repeat(32);
    const movePreviewId = "c".repeat(32);
    const directoryPreviewId = "e".repeat(32);
    const directoryMovePreviewId = "f".repeat(32);
    const revision = "d".repeat(64);
    const createRequest = {
      path: "notes/example.txt",
      content: "example\n",
      line_ending: "lf" as const,
    };
    const createPreview = {
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: sessionId,
      preview_id: createPreviewId,
      path: createRequest.path,
      proposed_revision: revision,
      line_ending: "lf",
      byte_size: 8,
      diff: "--- /dev/null\n+++ b/notes/example.txt\n@@ -0,0 +1 @@\n+example",
      expires_at: "2026-08-27T12:00:00Z",
    } as const;
    const createApplyRequest = {
      path: createRequest.path,
      content: createRequest.content,
      proposed_revision: revision,
      line_ending: "lf",
      confirmation: "apply_reviewed_workspace_create",
    } as const;
    const moveRequest = {
      source_path: createRequest.path,
      target_path: "reviewed-archive/example.txt",
      expected_revision: revision,
    };
    const movePreview = {
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: sessionId,
      preview_id: movePreviewId,
      source_path: moveRequest.source_path,
      target_path: moveRequest.target_path,
      expected_revision: revision,
      byte_size: 8,
      expires_at: "2026-08-27T12:00:00Z",
    } as const;
    const moveApplyRequest = {
      ...moveRequest,
      confirmation: "apply_reviewed_workspace_move",
    } as const;
    const directoryRequest = { path: "archive" };
    const directoryPreview = {
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: sessionId,
      preview_id: directoryPreviewId,
      path: directoryRequest.path,
      expires_at: "2026-08-27T12:00:00Z",
    } as const;
    const directoryApplyRequest = {
      path: directoryRequest.path,
      confirmation: "apply_reviewed_workspace_directory_create",
    } as const;
    const directoryMoveRequest = {
      source_path: "archive",
      target_path: "reviewed-archive",
    };
    const directoryMovePreview = {
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: sessionId,
      preview_id: directoryMovePreviewId,
      source_path: directoryMoveRequest.source_path,
      target_path: directoryMoveRequest.target_path,
      contents_reviewed: false,
      expires_at: "2026-08-27T12:00:00Z",
    } as const;
    const directoryMoveApplyRequest = {
      ...directoryMoveRequest,
      confirmation: "apply_reviewed_workspace_directory_move",
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(createPreview))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        path: createRequest.path,
        revision,
        byte_size: 8,
        operation: "created",
        applied: true,
      }))
      .mockResolvedValueOnce(privateJsonResponse(directoryPreview))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        path: directoryRequest.path,
        operation: "directory_created",
        applied: true,
      }))
      .mockResolvedValueOnce(privateJsonResponse(directoryMovePreview))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        source_path: directoryMoveRequest.source_path,
        target_path: directoryMoveRequest.target_path,
        contents_reviewed: false,
        operation: "directory_moved",
        applied: true,
      }))
      .mockResolvedValueOnce(privateJsonResponse(movePreview))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        source_path: moveRequest.source_path,
        target_path: moveRequest.target_path,
        revision,
        byte_size: 8,
        operation: "moved",
        applied: true,
      }));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    const reviewedCreate = await transport.previewAgentWorkspaceCreate(sessionId, createRequest);
    await expect(transport.applyAgentWorkspaceCreate(
      sessionId,
      reviewedCreate,
      createApplyRequest,
    )).resolves.toMatchObject({ operation: "created", revision });
    const reviewedDirectory = await transport.previewAgentWorkspaceDirectoryCreate(sessionId, directoryRequest);
    await expect(transport.applyAgentWorkspaceDirectoryCreate(
      sessionId,
      reviewedDirectory,
      directoryApplyRequest,
    )).resolves.toMatchObject({ operation: "directory_created" });
    const reviewedDirectoryMove = await transport.previewAgentWorkspaceDirectoryMove(sessionId, directoryMoveRequest);
    await expect(transport.applyAgentWorkspaceDirectoryMove(
      sessionId,
      reviewedDirectoryMove,
      directoryMoveApplyRequest,
    )).resolves.toMatchObject({ operation: "directory_moved", contents_reviewed: false });
    const reviewedMove = await transport.previewAgentWorkspaceMove(sessionId, moveRequest);
    await expect(transport.applyAgentWorkspaceMove(
      sessionId,
      reviewedMove,
      moveApplyRequest,
    )).resolves.toMatchObject({ operation: "moved", revision });

    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/creates`);
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/agent/sessions/${sessionId}/workspace/creates/${createPreviewId}/apply`,
    );
    expect(fetchMock.mock.calls[3][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/directories`);
    expect(fetchMock.mock.calls[4][0]).toBe(
      `/v1/agent/sessions/${sessionId}/workspace/directories/${directoryPreviewId}/apply`,
    );
    expect(fetchMock.mock.calls[5][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/directory-moves`);
    expect(fetchMock.mock.calls[6][0]).toBe(
      `/v1/agent/sessions/${sessionId}/workspace/directory-moves/${directoryMovePreviewId}/apply`,
    );
    expect(fetchMock.mock.calls[7][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/moves`);
    expect(fetchMock.mock.calls[8][0]).toBe(
      `/v1/agent/sessions/${sessionId}/workspace/moves/${movePreviewId}/apply`,
    );
    expect(approveUserPresence).toHaveBeenCalledTimes(4);
    expect(approveUserPresence).toHaveBeenNthCalledWith(1, {
      method: "POST",
      path: `/v1/agent/sessions/${sessionId}/workspace/creates/${createPreviewId}/apply`,
      bodySha256: await sha256(JSON.stringify(createApplyRequest)),
    });
    expect(approveUserPresence).toHaveBeenNthCalledWith(2, {
      method: "POST",
      path: `/v1/agent/sessions/${sessionId}/workspace/directories/${directoryPreviewId}/apply`,
      bodySha256: await sha256(JSON.stringify(directoryApplyRequest)),
    });
    expect(approveUserPresence).toHaveBeenNthCalledWith(3, {
      method: "POST",
      path: `/v1/agent/sessions/${sessionId}/workspace/directory-moves/${directoryMovePreviewId}/apply`,
      bodySha256: await sha256(JSON.stringify(directoryMoveApplyRequest)),
    });
    expect(approveUserPresence).toHaveBeenNthCalledWith(4, {
      method: "POST",
      path: `/v1/agent/sessions/${sessionId}/workspace/moves/${movePreviewId}/apply`,
      bodySha256: await sha256(JSON.stringify(moveApplyRequest)),
    });
  });

  it("binds reviewed Recycle Bin transport to native confirmation and strict receipts", async () => {
    const sessionId = "a".repeat(32);
    const previewId = "b".repeat(32);
    const revision = "c".repeat(64);
    const request = { path: "notes/example.txt", expected_revision: revision };
    const applyRequest = {
      ...request,
      confirmation: "apply_reviewed_workspace_file_trash",
    } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        preview_id: previewId,
        path: request.path,
        expected_revision: revision,
        byte_size: 8,
        recovery: "windows_recycle_bin",
        permanent: false,
        expires_at: "2026-08-27T12:00:00Z",
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        path: request.path,
        revision,
        byte_size: 8,
        recovery: "windows_recycle_bin",
        permanent: false,
        operation: "trashed",
        applied: true,
      }));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    const preview = await transport.previewAgentWorkspaceFileTrash(sessionId, request);
    await expect(transport.applyAgentWorkspaceFileTrash(
      sessionId,
      preview,
      applyRequest,
    )).resolves.toMatchObject({ operation: "trashed", permanent: false });

    const applyPath = `/v1/agent/sessions/${sessionId}/workspace/file-trash/${previewId}/apply`;
    expect(fetchMock.mock.calls[1][0]).toBe(`/v1/agent/sessions/${sessionId}/workspace/file-trash`);
    expect(fetchMock.mock.calls[2][0]).toBe(applyPath);
    expect(approveUserPresence).toHaveBeenCalledWith({
      method: "POST",
      path: applyPath,
      bodySha256: await sha256(JSON.stringify(applyRequest)),
    });
  });

  it("rejects forged workspace lifecycle transport responses", async () => {
    const sessionId = "a".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-lifecycle.v1",
        session_id: sessionId,
        preview_id: "b".repeat(32),
        path: "other.txt",
        proposed_revision: "c".repeat(64),
        line_ending: "lf",
        byte_size: 8,
        diff: "--- /dev/null\n+++ b/other.txt\n@@ -0,0 +1 @@\n+example",
        expires_at: "2026-08-27T12:00:00Z",
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN),
    });

    await expect(transport.previewAgentWorkspaceCreate(sessionId, {
      path: "notes/example.txt",
      content: "example\n",
      line_ending: "lf",
    })).rejects.toMatchObject({
      message: "Local agent workspace create preview was invalid",
      status: 200,
    });
  });

  it("previews and applies a strict multi-file transaction with one native binding", async () => {
    const sessionId = "a".repeat(32);
    const planId = "b".repeat(32);
    const alphaOld = "1".repeat(64);
    const alphaNew = "2".repeat(64);
    const betaOld = "3".repeat(64);
    const betaNew = "4".repeat(64);
    const previewRequest = {
      changes: [
        { operation: "edit" as const, path: "beta.txt", content: "beta new\n", expected_revision: betaOld, line_ending: "lf" as const },
        { operation: "edit" as const, path: "alpha.txt", content: "alpha new\n", expected_revision: alphaOld, line_ending: "lf" as const },
      ],
    };
    const previewResponse = {
      contract_version: "local-agent-workspace-transaction.v2",
      session_id: sessionId,
      plan_id: planId,
      file_count: 2,
      total_byte_size: 19,
      added_lines: 2,
      removed_lines: 2,
      files: [
        { operation: "edit" as const, path: "alpha.txt", expected_revision: alphaOld, proposed_revision: alphaNew, line_ending: "lf", proposed_byte_size: 10, added_lines: 1, removed_lines: 1, diff: "--- a/alpha.txt\n+++ b/alpha.txt\n@@ -1 +1 @@\n-alpha old\n+alpha new" },
        { operation: "edit" as const, path: "beta.txt", expected_revision: betaOld, proposed_revision: betaNew, line_ending: "lf", proposed_byte_size: 9, added_lines: 1, removed_lines: 1, diff: "--- a/beta.txt\n+++ b/beta.txt\n@@ -1 +1 @@\n-beta old\n+beta new" },
      ],
      expires_at: "2026-08-27T12:00:00Z",
    };
    const applyRequest = {
      changes: previewResponse.files.map((item) => ({
        operation: item.operation,
        path: item.path,
        content: previewRequest.changes.find((change) => change.path === item.path)!.content,
        expected_revision: item.expected_revision,
        proposed_revision: item.proposed_revision,
        line_ending: item.line_ending as "lf",
      })),
      confirmation: "apply_reviewed_workspace_transaction" as const,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(previewResponse))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace-transaction.v2",
        session_id: sessionId,
        plan_id: planId,
        state: "committed",
        reason: null,
        file_count: 2,
        files: [
          { path: "alpha.txt", state: "committed", revision: alphaNew, byte_size: 10 },
          { path: "beta.txt", state: "committed", revision: betaNew, byte_size: 9 },
        ],
      }));
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    const preview = await transport.previewAgentWorkspaceTransaction(sessionId, previewRequest);
    await expect(transport.applyAgentWorkspaceTransaction(sessionId, preview, applyRequest)).resolves.toMatchObject({
      state: "committed",
      file_count: 2,
    });

    const previewPath = `/v1/agent/sessions/${sessionId}/workspace/transactions`;
    const applyPath = `/v1/agent/sessions/${sessionId}/workspace/transactions/${planId}/apply`;
    expect(fetchMock.mock.calls[1][0]).toBe(previewPath);
    expect(fetchMock.mock.calls[2][0]).toBe(applyPath);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ cache: "no-store" });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ cache: "no-store" });
    expect(approveUserPresence).toHaveBeenCalledOnce();
    expect(approveUserPresence).toHaveBeenCalledWith({
      method: "POST",
      path: applyPath,
      bodySha256: await sha256(JSON.stringify(applyRequest)),
    });
  });

  it("preserves only an allowlisted transaction expiry reason", async () => {
    const sessionId = "a".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: {
          code: "workspace_transaction_expired",
          message: "EXAMPLE_PRIVATE_TRANSACTION_CANARY",
        },
      }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.previewAgentWorkspaceTransaction(sessionId, {
      changes: [
        { operation: "edit", path: "alpha.txt", content: "alpha new\n", expected_revision: "1".repeat(64), line_ending: "lf" },
        { operation: "edit", path: "beta.txt", content: "beta new\n", expected_revision: "2".repeat(64), line_ending: "lf" },
      ],
    }).catch((caught: unknown) => caught);

    expect(error).toMatchObject({ status: 409, reasonCode: "workspace_transaction_expired" });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_TRANSACTION_CANARY");
  });

  it("rejects a workspace tree that returns an absolute local path", async () => {
    const sessionId = "a".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: ".",
        entries: [{ path: "C:/private.txt", name: "private.txt", kind: "file", byte_size: 1, editable_candidate: true }],
        complete: true,
      }));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.getAgentWorkspaceTree(sessionId, ".")).rejects.toMatchObject({
      message: "Local agent workspace tree response was invalid",
      status: 200,
    });
  });
});

describe("application update transport", () => {
  const currentStatus = {
    contract_version: "application-update-status.v3",
    instance_id: "a".repeat(32),
    revision: 1,
    contains_private_data: false,
    installed_version: "1.2.3",
    channel: "stable",
    state: "current",
    available_version: null,
    artifact_size_bytes: null,
    downloaded_bytes: null,
    last_checked_at: "2040-01-02T03:04:05Z",
    reason_code: null,
    verification_code: null,
    can_check: true,
    can_stage: false,
    can_cancel: false,
    can_retry: false,
    can_apply: false,
    can_verify: false,
    package_review: { state: "not_configured", reason_code: null, checked_at: null },
  } as const;

  it("reads local status and checks only through browser CSRF authentication", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(currentStatus))
      .mockResolvedValueOnce(privateJsonResponse(currentStatus));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const fence = { expected_revision: 1, expected_instance_id: "a".repeat(32) };
    await expect(transport.getApplicationUpdateStatus!()).resolves.toEqual(currentStatus);
    await expect(transport.checkApplicationUpdate!(fence)).resolves.toEqual(currentStatus);

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/auth/session",
      "/v1/application-updates/status",
      "/v1/application-updates/check",
    ]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "GET", cache: "no-store" });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: "POST",
      cache: "no-store",
      credentials: "include",
    });
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).toMatchObject({
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      "Content-Type": "application/json",
    });
    expect((fetchMock.mock.calls[2][1] as RequestInit).body).toBe(JSON.stringify(fence));
  });

  it("rejects malformed update status without retaining unknown fields", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        ...currentStatus,
        source_url: "EXAMPLE_PRIVATE_UPDATE_CANARY",
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    const error = await transport.getApplicationUpdateStatus!().catch((caught: unknown) => caught);
    expect(error).toMatchObject({
      message: "Application update status response was invalid",
      status: 200,
    });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_UPDATE_CANARY");
  });

  it("fences every mutating update action with the v2 coordinator identity", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockImplementation(() => Promise.resolve(privateJsonResponse(currentStatus)));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const fence = { expected_revision: 1, expected_instance_id: "a".repeat(32) };

    await transport.checkApplicationUpdate!(fence);
    await transport.stageApplicationUpdate!(fence);
    await transport.cancelApplicationUpdate!(fence);
    await transport.retryApplicationUpdate!(fence);
    await transport.verifyApplicationUpdate!(fence);

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      "/v1/application-updates/check",
      "/v1/application-updates/stage",
      "/v1/application-updates/cancel",
      "/v1/application-updates/retry",
      "/v1/application-updates/verify",
    ]);
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect((call[1] as RequestInit).body).toBe(JSON.stringify(fence));
      expect((call[1] as RequestInit).headers).toMatchObject({
        "Content-Type": "application/json",
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
      });
    }
  });
});

describe("workspace folder picker transport", () => {
  it("reads capability and opens the chooser with browser CSRF authentication", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-workspace-folder-picker.v1",
        available: true,
        mode: "server_native_dialog",
      }))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-workspace-folder-picker.v1",
        status: "selected",
        path: "D:\\example\\chosen-workspace",
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getWorkspaceFolderPickerCapability!()).resolves.toEqual({
      contract_version: "local-workspace-folder-picker.v1",
      available: true,
      mode: "server_native_dialog",
    });
    await expect(transport.chooseWorkspaceFolder!()).resolves.toEqual({
      contract_version: "local-workspace-folder-picker.v1",
      status: "selected",
      path: "D:\\example\\chosen-workspace",
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/auth/session",
      "/v1/local-ui/workspace-folder-picker",
      "/v1/local-ui/workspace-folder-picker",
    ]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "GET", cache: "no-store" });
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: "POST",
      cache: "no-store",
      credentials: "include",
    });
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).toMatchObject({
      "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
    });
  });

  it("rejects inconsistent, extra, and non-absolute picker responses", () => {
    expect(() => parseWorkspaceFolderPickerCapability({
      contract_version: "local-workspace-folder-picker.v1",
      available: false,
      mode: "server_native_dialog",
    })).toThrow("Workspace folder picker capability response was invalid");
    expect(() => parseWorkspaceFolderPick({
      contract_version: "local-workspace-folder-picker.v1",
      status: "selected",
      path: "relative-folder",
    })).toThrow("Workspace folder picker response was invalid");
    expect(() => parseWorkspaceFolderPick({
      contract_version: "local-workspace-folder-picker.v1",
      status: "cancelled",
      path: null,
      detail: "EXAMPLE_PRIVATE_PATH_CANARY",
    })).toThrow("Workspace folder picker response was invalid");
  });
});

describe("native user-presence transport binding", () => {
  it("marks a native decline before dispatch and does not post the capture", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE));
    const host = globalThis as typeof globalThis & { pywebview?: unknown };
    const previous = host.pywebview;
    host.pywebview = {
      api: {
        confirm_user_presence: vi.fn(async () => ({
          version: "native-user-presence-v1",
          approved: false,
          reason: "user_declined",
        })),
      },
    };
    try {
      const transport = createHttpTransport({
        fetch: fetchMock as unknown as typeof fetch,
        origin: "http://127.0.0.1:4173",
        userPresenceBridgeAvailable: () => true,
      });
      await expect(transport.captureAgentArtifact(
        AGENT_PROJECT_ID,
        AGENT_CATALOG_SESSION_ID,
        {
          path: "docs/example.md",
          expected_sha256: "5".repeat(64),
          expected_byte_size: 27,
        },
      )).rejects.toMatchObject({ status: 403, reasonCode: "native_confirmation_declined_before_dispatch" });
      expect(fetchMock).toHaveBeenCalledOnce();
    } finally {
      host.pywebview = previous;
    }
  });

  it("reports only the exact server-issued native confirmation capability", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      ...AUTH_RESPONSE,
      user_presence_confirmation_available: true,
    }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceBridgeAvailable: () => true,
    });

    await expect(transport.getUserPresenceCapability!()).resolves.toEqual({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    });
    await expect(transport.getUserPresenceCapability!()).resolves.toEqual({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe("/auth/session");
  });

  it("waits for the bounded native bridge-ready event when the server tuple is available", async () => {
    let bridgeReady = false;
    const bridgeAvailable = vi.fn(() => bridgeReady);
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceBridgeAvailable: bridgeAvailable,
      userPresenceBridgeReadyTimeoutMs: 1_000,
    });

    const capability = transport.getUserPresenceCapability!();
    await vi.waitFor(() => expect(bridgeAvailable).toHaveBeenCalled());
    bridgeReady = true;
    globalThis.dispatchEvent(new Event("pywebviewready"));
    await expect(capability).resolves.toEqual({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("fails closed after the bounded bridge-ready wait", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceBridgeAvailable: () => false,
      userPresenceBridgeReadyTimeoutMs: 1,
    });

    await expect(transport.getUserPresenceCapability!()).resolves.toEqual({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: false,
      mode: "unavailable",
    });
  });

  it("closes the abort race before the bridge-ready listener is registered", async () => {
    const controller = new AbortController();
    const bridgeAvailable = vi.fn(() => {
      controller.abort();
      return false;
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceBridgeAvailable: bridgeAvailable,
      userPresenceBridgeReadyTimeoutMs: 10_000,
    });

    await expect(transport.getUserPresenceCapability!(controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(bridgeAvailable).toHaveBeenCalledOnce();
  });

  it("fails closed when the server capability field has the wrong type", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      ...AUTH_RESPONSE,
      user_presence_confirmation_available: "yes",
    }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getUserPresenceCapability!()).rejects.toMatchObject({ status: 200 });
  });

  it("does not call the bridge or mutation route when the server reports unavailable", async () => {
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      csrf_token: AUTH_RESPONSE.csrf_token,
      expires_in_seconds: AUTH_RESPONSE.expires_in_seconds,
      user_presence_confirmation_available: false,
      user_presence_confirmation_mode: "unavailable",
    }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.decideAgentApproval(
      "a".repeat(32),
      "b".repeat(32),
      false,
    )).rejects.toMatchObject({ status: 503 });
    expect(approveUserPresence).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe("/auth/session");
  });

  it("preserves only the one-shot approval conflict reason", async () => {
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        detail: {
          code: "approval_already_settled",
          message: "EXAMPLE_PRIVATE_APPROVAL_CANARY",
        },
      }, 409));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    const error = await transport.decideAgentApproval(
      "a".repeat(32),
      "b".repeat(32),
      true,
    ).catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      status: 409,
      reasonCode: "approval_already_settled",
    });
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_APPROVAL_CANARY");
    expect(approveUserPresence).toHaveBeenCalledOnce();
  });

  it("binds the non-spawning Agent acceptance gate to native presence and its exact body", async () => {
    const request = {
      confirmation: "begin_guarded_agent_native_acceptance",
    } as const;
    const receipt = {
      contract_version: "agent-native-acceptance-start.v1",
      owner_presence_confirmed: true,
      model_execution_started: false,
      process_spawn_requested: false,
      workspace_access_requested: false,
      content_persisted: false,
      expires_on_reload: true,
    } as const;
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(receipt));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.beginAgentNativeAcceptance!(request)).resolves.toEqual(receipt);

    const path = "/v1/diagnostics/agent-native-acceptance/start";
    expect(approveUserPresence).toHaveBeenCalledWith({
      method: "POST",
      path,
      bodySha256: await sha256(JSON.stringify(request)),
    });
    expect(fetchMock.mock.calls[1][0]).toBe(path);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify(request),
      cache: "no-store",
      headers: expect.objectContaining({
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
        "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
      }),
    }));
  });

  it("binds agent-tool and lifecycle decisions to their exact POST path and body", async () => {
    const agentSessionId = "a".repeat(32);
    const approvalId = "b".repeat(32);
    const metricSessionId = "c".repeat(64);
    const proposalId = "d".repeat(64);
    const decision = {
      confirmation: "apply_local_user_metric_lifecycle_decision",
      decision: "confirm",
      expected_proposal_revision: 1,
      expected_source_run_id: "e".repeat(64),
    } as const;
    const approveUserPresence = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(exampleAgentSession()))
      .mockResolvedValueOnce(privateJsonResponse({}));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.decideAgentApproval(agentSessionId, approvalId, true)).resolves.toEqual(exampleAgentSession());
    await expect(transport.decideMetricLifecycleProposal!(
      metricSessionId,
      proposalId,
      decision,
      "dashboard-lifecycle-decision-example",
    )).rejects.toMatchObject({ status: 200 });

    const agentPath = `/v1/agent/sessions/${agentSessionId}/approvals/${approvalId}`;
    const lifecyclePath = `/v1/sessions/${metricSessionId}/metric-lifecycle-evidence/proposals/${proposalId}/decision`;
    expect(approveUserPresence).toHaveBeenNthCalledWith(1, {
      method: "POST",
      path: agentPath,
      bodySha256: await sha256(JSON.stringify({ approved: true })),
    });
    expect(approveUserPresence).toHaveBeenNthCalledWith(2, {
      method: "POST",
      path: lifecyclePath,
      bodySha256: await sha256(JSON.stringify(decision)),
    });
    for (const requestIndex of [1, 2]) {
      expect((fetchMock.mock.calls[requestIndex][1] as RequestInit).headers).toEqual(expect.objectContaining({
        "X-Prompt-Enhancer-CSRF": AUTH_RESPONSE.csrf_token,
        "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
      }));
    }
  });

  it("does not invoke native user presence for an edit preview", async () => {
    const sessionId = "a".repeat(32);
    const base = "b".repeat(64);
    const proposed = "c".repeat(64);
    const previewId = "d".repeat(32);
    const approveUserPresence = vi.fn().mockRejectedValue(new Error("must not be called"));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        preview_id: previewId,
        path: "src/example.py",
        expected_revision: base,
        proposed_revision: proposed,
        line_ending: "lf",
        diff: "--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-old\n+new",
        expires_at: "2040-01-02T10:00:00Z",
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approveUserPresence,
    });

    await expect(transport.previewAgentWorkspaceEdit(sessionId, {
      path: "src/example.py",
      content: "new\n",
      expected_revision: base,
      line_ending: "lf",
    })).resolves.toMatchObject({ preview_id: previewId });
    expect(approveUserPresence).not.toHaveBeenCalled();
    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).not.toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": expect.anything(),
    }));
  });

  it("stages attachment bytes with an exact media contract and never serializes them into JSON", async () => {
    const body = new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(agentAttachment()));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.stageAgentAttachment(AGENT_CATALOG_SESSION_ID, {
      blob: body,
      displayName: "example.png",
      source: "file",
    })).resolves.toMatchObject({ attachment_id: AGENT_ATTACHMENT_ID, state: "staged" });

    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/agent/sessions/${AGENT_CATALOG_SESSION_ID}/attachments?name=example.png&source=file`,
    );
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.body).toBe(body);
    expect(new Headers(request.headers).get("content-type")).toBe("image/png");
  });

  it("stages canonical document bytes and accepts only the private projected preview contract", async () => {
    const body = new Blob(["# Synthetic local notes"], { type: "text/markdown" });
    const document = agentAttachment({
      display_name: "example-notes.md",
      kind: "document",
      media_type: "text/markdown",
      byte_size: body.size,
      width: null,
      height: null,
      routing: "local_text_projection",
      document_format: "markdown",
      projected_characters: 23,
      projection_truncated: false,
      omitted_features: [],
    });
    const preview = {
      contract_version: "agent-attachment-document-preview.v1",
      session_id: AGENT_CATALOG_SESSION_ID,
      attachment_id: AGENT_ATTACHMENT_ID,
      sha256: "6".repeat(64),
      media_type: "text/markdown",
      document_format: "markdown",
      text: "# Synthetic local notes",
      projected_characters: 23,
      projection_truncated: false,
      preview_truncated: false,
      omitted_features: [],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(privateJsonResponse(document))
      .mockResolvedValueOnce(privateJsonResponse(preview));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.stageAgentAttachment(AGENT_CATALOG_SESSION_ID, {
      blob: body,
      displayName: "example-notes.md",
      source: "file",
    })).resolves.toMatchObject({ kind: "document", routing: "local_text_projection" });
    expect(new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers).get("content-type"))
      .toBe("text/markdown");
    await expect(transport.getAgentAttachmentDocumentPreview(
      AGENT_CATALOG_SESSION_ID,
      AGENT_ATTACHMENT_ID,
    )).resolves.toMatchObject({
      text: "# Synthetic local notes",
      preview_truncated: false,
    });
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/agent/sessions/${AGENT_CATALOG_SESSION_ID}/attachments/${AGENT_ATTACHMENT_ID}/document-preview`,
    );
  });

  it("refuses unsupported PDF attachment uploads before any request", async () => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.stageAgentAttachment(AGENT_CATALOG_SESSION_ID, {
      blob: new Blob(["%PDF-1.7 synthetic"], { type: "application/pdf" }),
      displayName: "synthetic.pdf",
      source: "file",
    })).rejects.toThrow("attachment upload was invalid");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends only staged attachment identities beside text", async () => {
    const sessionId = "a".repeat(32);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(exampleAgentSession({ session_id: sessionId })));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await transport.sendAgentMessage(sessionId, "Inspect this image", [AGENT_ATTACHMENT_ID]);
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      text: "Inspect this image",
      attachment_ids: [AGENT_ATTACHMENT_ID],
    });
  });

  it("accepts only private, non-sniffable same-origin attachment previews", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const content = new Response(bytes, {
      status: 200,
      headers: {
        "Content-Type": "image/png",
        "Content-Length": "3",
        "Content-Disposition": `inline; filename="agent-attachment-${AGENT_ATTACHMENT_ID.slice(0, 8)}.png"`,
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(content);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getAgentAttachmentContent(
      AGENT_CATALOG_SESSION_ID,
      AGENT_ATTACHMENT_ID,
    )).resolves.toMatchObject({
      contentType: "image/png",
      byteSize: 3,
      filename: `agent-attachment-${AGENT_ATTACHMENT_ID.slice(0, 8)}.png`,
    });
    expect((fetchMock.mock.calls[1][1] as RequestInit).referrerPolicy).toBe("no-referrer");
  });

  it("rejects an otherwise valid attachment preview when privacy headers are incomplete", async () => {
    const content = new Response(new Uint8Array([1]), {
      status: 200,
      headers: {
        "Content-Type": "image/png",
        "Content-Length": "1",
        "Content-Disposition": `inline; filename="agent-attachment-${AGENT_ATTACHMENT_ID.slice(0, 8)}.png"`,
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cross-Origin-Resource-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(content);
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getAgentAttachmentContent(
      AGENT_CATALOG_SESSION_ID,
      AGENT_ATTACHMENT_ID,
    )).rejects.toThrow("Agent attachment content response was invalid");
  });
});
