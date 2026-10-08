import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CodexSession,
  ProviderCompatibilityStatus,
  PromptEnhancerTransport,
  SessionAnalysisRunResponse,
  SessionCoachingProjection,
  SessionMetric,
  SessionMetricReadinessReport,
  SessionQualityAnalysisPreview,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import {
  SYNTHETIC_METRIC_COVERAGE,
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_METRIC_READINESS,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import type { ProjectWorkspaceRoute } from "./ProjectWorkspace";
import { ProjectWorkspace } from "./ProjectWorkspace";

const projectId = "a".repeat(64);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}
const sessionId = "b".repeat(64);
const secondSessionId = "c".repeat(64);
const otherProjectId = "d".repeat(64);

class MastheadIntersectionObserver {
  static instances: MastheadIntersectionObserver[] = [];

  readonly root: Element | Document | null;
  readonly rootMargin: string;
  readonly thresholds: readonly number[];
  readonly callback: IntersectionObserverCallback;
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => [] as IntersectionObserverEntry[]);

  constructor(
    callback: IntersectionObserverCallback,
    options: IntersectionObserverInit = {},
  ) {
    this.callback = callback;
    this.root = options.root ?? null;
    this.rootMargin = options.rootMargin ?? "0px";
    this.thresholds = Array.isArray(options.threshold)
      ? options.threshold
      : [options.threshold ?? 0];
    MastheadIntersectionObserver.instances.push(this);
  }

  emit(isIntersecting: boolean) {
    const target = this.observe.mock.calls[0]?.[0] as Element | undefined;
    if (!target) throw new Error("The masthead sentinel was not observed.");
    this.callback(
      [
        {
          isIntersecting,
          target,
          intersectionRatio: isIntersecting ? 1 : 0,
        } as IntersectionObserverEntry,
      ],
      this as unknown as IntersectionObserver,
    );
  }
}

function installMastheadObserver() {
  MastheadIntersectionObserver.instances = [];
  vi.stubGlobal("IntersectionObserver", MastheadIntersectionObserver);
}

afterEach(() => {
  vi.unstubAllGlobals();
  MastheadIntersectionObserver.instances = [];
});

async function openLegacyQualityProfile() {
  const label = await screen.findByText("Legacy coaching profile");
  const disclosure = label.closest("details");
  if (!disclosure?.hasAttribute("open")) fireEvent.click(label);
  expect(disclosure).toHaveAttribute("open");
}

const EXACT_COMPATIBILITY: ProviderCompatibilityStatus = {
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
};

const sessions: CodexSession[] = [
  {
    session_id: sessionId,
    installation_id: "1".repeat(64),
    project_id: projectId,
    project_display_name: "Example Observatory",
    session_display_name: "Validate sample adapter",
    provider: "codex",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: "2040-01-02T09:00:00Z",
    ended_at: "2040-01-02T09:10:00Z",
    terminal_state: "completed",
    events_complete: true,
  },
  {
    session_id: secondSessionId,
    installation_id: "1".repeat(64),
    project_id: projectId,
    project_display_name: "Example Observatory",
    session_display_name: "Review sample workflow",
    provider: "codex",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: "2040-01-01T09:00:00Z",
    ended_at: null,
    terminal_state: null,
    events_complete: false,
  },
];

function metric(input: {
  key: string;
  dimension: string;
  displayName: string;
  numericValue: number | null;
}): SessionMetric {
  return {
    key: input.key,
    version: 2,
    dimension: input.dimension,
    display_name: input.displayName,
    numeric_value: input.numericValue,
    text_value: null,
    unit: "count",
    source: "synthetic_fixture",
    observed_count: input.numericValue === null ? 0 : 2,
    eligible_count: 2,
    coverage: input.numericValue === null ? 0 : 1,
    confidence: input.numericValue === null ? null : 1,
    metric_pack_key: "example.metadata.session",
    metric_pack_version: 4,
    metric_engine_version: "example-engine-1",
    redactor_version: "example-redactor-1",
    model_id: null,
    model_revision: null,
    tokenizer_id: null,
    prompt_version: null,
    rubric_version: null,
    computed_at: "2040-01-02T09:11:00Z",
  };
}

const storedMetrics = [
  metric({
    key: "session.reliability.tool_result_count",
    dimension: "reliability",
    displayName: "Tool result count",
    numericValue: 2,
  }),
  metric({
    key: "session.usage.total_tokens",
    dimension: "usage",
    displayName: "Provider total tokens",
    numericValue: 120,
  }),
  metric({
    key: "session.future.example_observation",
    dimension: "future",
    displayName: "Future example observation",
    numericValue: null,
  }),
];

function qualityDetail(): SessionAnalysisRunResponse {
  const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
  detail.run.session_id = sessionId;
  return detail;
}

function qualityPreview(
  requestedSessionId = sessionId,
): SessionQualityAnalysisPreview {
  const createdAt = new Date(Date.now() + 60_000);
  const previewText = "Synthetic redacted request for the example workspace.";
  return {
    preview_id: "e".repeat(64),
    created_at: createdAt.toISOString(),
    expires_at: new Date(createdAt.getTime() + 600_000).toISOString(),
    binding: {
      provider: "codex",
      session_id: requestedSessionId,
      analysis_window_fingerprint: "f".repeat(64),
      metric_keys: SYNTHETIC_SESSION_METRIC_READINESS.metrics.map(
        (metric) => metric.metric_key,
      ),
      destination: "local",
      exact_model: "none",
      estimator_plan_version: "example-plan-1",
      redactor_version: "example-redactor-1",
      retention_class: "local_ephemeral",
      message_count: 1,
      character_count: Array.from(previewText).length,
      cost_state: "not_applicable",
      estimated_cost_microunits: null,
      cost_currency: null,
    },
    messages: [{
      role: "user",
      kind: "request",
      language: "en",
      text: previewText,
    }],
  };
}

function metricReadinessReport(
  requestedSessionId = sessionId,
): SessionMetricReadinessReport {
  return {
    session_id: requestedSessionId,
    provider: "codex",
    preset_id: "coaching_profile_v1",
    analysis_profile_key: "coaching_profile",
    analysis_profile_version: 1,
    metric_pack_key: "experimental.redacted-text.coaching",
    metric_pack_version: 3,
    capability_report: {
      provider: "codex",
      surface: "text_window",
      catalog_version: "coaching-evidence-capabilities-v1",
      compatibility_state: "exact",
      provider_version: "example-provider-1",
      decoder_key: "codex_app_server",
      decoder_version: "example-adapter-1",
      checked_at: "2040-01-01T10:00:00Z",
      capabilities: [
        "request_text",
        "response_text",
        "plan_text",
        "action_evidence",
        "decision_evidence",
        "feedback_text",
        "objective_verification",
      ].map((capability) => ({
        capability,
        state: "supported" as const,
        reason_code: "verified_by_compatible_decoder" as const,
      })),
      structurally_attemptable_metric_count: 20,
      structurally_unsupported_metric_count: 0,
      structurally_unknown_metric_count: 0,
    },
    metrics: [],
  } as SessionMetricReadinessReport;
}

function coachingProjection(): SessionCoachingProjection {
  const common = {
    algorithm_id: "rules.coaching-loop.summary",
    algorithm_version: "1",
    candidate_policy_version: 2,
    confidence: null,
    construct_version: 1,
    coverage: 1,
    decision_state: "candidate" as const,
    denominator: 20,
    denominator_kind: "event_count" as const,
    denominator_kind_priority_version: 1,
    evidence_lower_bound: 0.84,
    evidence_upper_bound: 1,
    evidence_basis: ["rule.factor_counts" as const],
    evidence_kind: "deterministic_candidate" as const,
    evidence_tier: "redacted_content" as const,
    pack_key: "coaching.loop",
    pack_version: 1,
    polarity_successes: 20,
    recommendation_policy_version: 1,
    rule_priority_version: 1,
    source_provenance: {
      algorithm_id: "rules.en-pl.coaching",
      algorithm_version: "2",
      pack_key: "core.redacted-text.coaching",
      pack_version: 2,
    },
    task_type: "implementation" as const,
    abstention_code: null,
  };
  const friction = {
    ...common,
    code: "friction.rework_signal_high",
    evidence_lower_bound: 0,
    evidence_upper_bound: 0.16,
    polarity_successes: 0,
    metric_basis: ["collaboration.rework_candidate_rate.v1"],
  };
  return {
    projection_key: "coaching.loop.current",
    projection_version: 1,
    task_context_source: "reviewed_task",
    task_type: "implementation",
    summary: {
      outcome: {
        ...common,
        abstention_code: "objective_evidence_missing",
        code: "outcome.unknown",
        confidence: null,
        construct_version: null,
        coverage: null,
        decision_state: "abstained",
        denominator: null,
        denominator_kind: null,
        evidence_lower_bound: null,
        evidence_upper_bound: null,
        evidence_basis: [],
        evidence_disagreement: false,
        evidence_kind: null,
        evidence_tier: null,
        human_acceptance_status: "unknown",
        metric_basis: [],
        polarity_successes: null,
        source_provenance: null,
        status: "unknown",
      },
      strength: {
        ...common,
        code: "strength.testable_acceptance",
        metric_basis: ["prompt.acceptance_testability.v1"],
      },
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

function workspaceTransport() {
  const listProjectSessions = vi.fn(async () => ({
    sessions,
    limit: 100,
    offset: 0,
    total: sessions.length,
    has_more: false,
  }));
  const getSessionMetrics = vi.fn(async (requestedSessionId: string) => ({
    session_id: requestedSessionId,
    metrics: storedMetrics,
  }));
  const getLatestSessionQualityAnalysis = vi.fn(async () => {
    throw new TransportError("Synthetic immutable run was not found", 404);
  });
  const getSessionTextAnalysisCapability = vi.fn(async () => ({
    available: true,
    reason_code: "available",
    data_tier: "redacted_content",
    content_persistence: false,
    network_inference: false,
    raw_transcripts: false,
  } as const));
  const getCodexLocalSourceStatus = vi.fn(async () => ({
    consent_active: true,
    indexed_sessions: sessions.length,
    indexed_projects: 1,
    verification_capability: {
      state: "validation_only" as const,
      live_classification_enabled: false,
      supported_kinds: [],
      reason_code: "synthetic_validation_only",
    },
  }));
  const getProviderCompatibility = vi.fn(async () => EXACT_COMPATIBILITY);
  const checkProviderCompatibility = vi.fn(async () => EXACT_COMPATIBILITY);
  const getSessionMetricReadiness = vi.fn(async (requestedSessionId: string) =>
    metricReadinessReport(requestedSessionId),
  );
  const prepareSessionQualityAnalysisPreview = vi.fn(
    async (requestedSessionId: string) => qualityPreview(requestedSessionId),
  );
  const approveSessionQualityAnalysisPreview = vi.fn(async () => ({
    run_id: qualityDetail().run.run_id,
    status: "completed" as const,
    result_count: 10,
    applied: true,
    analysis_profile_key: "coaching_profile",
    analysis_profile_version: 1,
  }));
  const transport: PromptEnhancerTransport = {
    ...createSyntheticTransport(),
    listProjectSessions,
    getSessionMetrics,
    getLatestSessionQualityAnalysis,
    getSessionTextAnalysisCapability,
    getCodexLocalSourceStatus,
    getProviderCompatibility,
    checkProviderCompatibility,
    getSessionMetricReadiness,
    prepareSessionQualityAnalysisPreview,
    approveSessionQualityAnalysisPreview,
  };
  return {
    transport,
    listProjectSessions,
    getSessionMetrics,
    getLatestSessionQualityAnalysis,
    getProviderCompatibility,
    checkProviderCompatibility,
    getSessionMetricReadiness,
    prepareSessionQualityAnalysisPreview,
    approveSessionQualityAnalysisPreview,
  };
}

describe("ProjectWorkspace", () => {
  it("keeps a failed stored-metric read content-free and retries the same session", async () => {
    const { transport, getSessionMetrics } = workspaceTransport();
    getSessionMetrics
      .mockRejectedValueOnce(new Error("SYNTHETIC_PRIVATE_METRIC_FAILURE"))
      .mockResolvedValueOnce({ session_id: sessionId, metrics: storedMetrics });

    render(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "session_metrics", projectId, sessionId, category: "tools" }}
        transport={transport}
      />,
    );

    expect(await screen.findByText("Stored metrics for this session could not be loaded.")).toBeVisible();
    expect(document.body).not.toHaveTextContent("SYNTHETIC_PRIVATE_METRIC_FAILURE");
    const readsBeforeRetry = getSessionMetrics.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Tool result count")).toBeVisible();
    await waitFor(() => expect(getSessionMetrics).toHaveBeenCalledTimes(readsBeforeRetry + 1));
    await waitFor(() => {
      expect(screen.queryByText("Stored metrics for this session could not be loaded.")).not.toBeInTheDocument();
    });
  });

  it("opens a selected older session without weakening the 100-session project analysis boundary", async () => {
    const { transport, getSessionMetrics } = workspaceTransport();
    const firstPage = Array.from({ length: 100 }, (_, index) => ({ ...sessions[0], session_id: index.toString(16).padStart(64, "0") }));
    transport.listProjectSessions = vi.fn(async (_project, limit, offset = 0) => ({
      sessions: offset === 0 ? firstPage : [sessions[0]], limit: limit ?? 100, offset, total: 101, has_more: offset === 0,
    }));
    const { rerender } = render(<ProjectWorkspace navigate={vi.fn()} route={{ name: "session_metrics", projectId, sessionId: sessions[0].session_id, category: "tools" }} transport={transport} />);
    expect(await screen.findByText("Tool result count")).toBeVisible();
    expect(transport.listProjectSessions).toHaveBeenCalledWith(projectId, 100, 100, expect.any(AbortSignal));
    expect(getSessionMetrics).toHaveBeenCalledWith(sessions[0].session_id, expect.any(AbortSignal));
    expect(screen.queryByText(/selected session is not part/)).toBeNull();
    rerender(<ProjectWorkspace navigate={vi.fn()} route={{ name: "project_metrics", projectId, category: "prompt-quality" }} transport={transport} />);
    expect(await screen.findByRole("heading", { name: "Choose at most 100 sessions" })).toBeVisible();
  });

  it("bounds older-session lookup and lets the user explicitly search the next pages", async () => {
    const { transport } = workspaceTransport();
    const olderId = "e".repeat(64);
    transport.listProjectSessions = vi.fn(async (_project, limit, offset = 0) => ({
      sessions: offset === 1000 ? [{ ...sessions[0], session_id: olderId }] : Array.from({ length: 100 }, (_, index) => ({ ...sessions[0], session_id: (offset + index).toString(16).padStart(64, "0") })),
      limit: limit ?? 100, offset, total: 1001, has_more: offset < 1000,
    }));
    render(<ProjectWorkspace navigate={vi.fn()} route={{ name: "session_metrics", projectId, sessionId: olderId, category: "tools" }} transport={transport} />);
    const next = await screen.findByRole("button", { name: "Search next 1,000 sessions" });
    expect(transport.listProjectSessions).toHaveBeenCalledTimes(10);
    expect(screen.queryByText(/selected session is not part/)).toBeNull();
    fireEvent.click(next);
    expect(await screen.findByText("Tool result count")).toBeVisible();
    expect(transport.listProjectSessions).toHaveBeenCalledTimes(11);
  });

  it("mounts project-scoped coverage only on the overview", async () => {
    const { transport } = workspaceTransport();
    const report = {
      ...structuredClone(SYNTHETIC_METRIC_COVERAGE),
      scope: "one_project" as const,
    };
    const getProjectMetricCoverage = vi.fn(async () => report);
    transport.getProjectMetricCoverage = getProjectMetricCoverage;
    const { rerender } = render(
      <ProjectWorkspace
        coverageProvider="synthetic"
        navigate={vi.fn()}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Coaching metric coverage" }))
      .toBeVisible();
    expect(getProjectMetricCoverage).toHaveBeenCalledWith(
      projectId,
      "synthetic",
      expect.any(AbortSignal),
    );

    rerender(
      <ProjectWorkspace
        coverageProvider="synthetic"
        navigate={vi.fn()}
        route={{ name: "project_sessions", projectId }}
        transport={transport}
      />,
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Coaching metric coverage" }),
      ).not.toBeInTheDocument(),
    );
    expect(getProjectMetricCoverage).toHaveBeenCalledTimes(1);
  });

  it("keeps the iconized project-section navigator operable in the compact masthead", async () => {
    installMastheadObserver();
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    const { container } = render(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Example Observatory" }),
    ).toBeVisible();
    const workspace = container.querySelector(".project-workspace");
    const masthead = container.querySelector(
      ".project-workspace__compact-masthead",
    );
    expect(workspace).toHaveAttribute("data-masthead", "full");
    expect(masthead).not.toBeNull();
    expect(masthead?.children).toHaveLength(2);
    expect(
      masthead?.querySelector(".project-workspace__compact-identity"),
    ).toHaveTextContent("Example Observatory");
    const compactNavigation = container.querySelector(
      '[data-project-section-nav="compact"]',
    );
    const fullNavigation = container.querySelector(
      '[data-project-section-nav="full"]',
    );
    expect(compactNavigation).toHaveAttribute("aria-hidden", "true");
    expect(fullNavigation).not.toHaveAttribute("aria-hidden");
    expect(
      within(compactNavigation as HTMLElement).getByRole("link", {
        name: "Metric deck",
        hidden: true,
      }),
    ).toHaveAttribute("tabindex", "-1");
    expect(
      within(compactNavigation as HTMLElement).getByRole("link", {
        name: "Sessions, 2 indexed",
        hidden: true,
      }),
    ).toHaveAttribute("href", `/projects/${projectId}/sessions`);
    const fullMetricDeck = within(fullNavigation as HTMLElement).getByRole(
      "link",
      { name: "Metric deck" },
    );
    fullMetricDeck.focus();
    expect(fullMetricDeck).toHaveFocus();

    const observer = MastheadIntersectionObserver.instances[0];
    expect(observer).toBeDefined();
    expect(observer.rootMargin).toBe("64px 0px 0px 0px");
    expect(observer.observe).toHaveBeenCalledWith(
      container.querySelector(".project-workspace__masthead-sentinel"),
    );

    act(() => observer.emit(false));
    expect(workspace).toHaveAttribute("data-masthead", "compact");
    expect(
      container.querySelector(".project-workspace__masthead-anchor"),
    ).toHaveAttribute("data-visible", "true");
    expect(compactNavigation).not.toHaveAttribute("aria-hidden");
    expect(fullNavigation).toHaveAttribute("aria-hidden", "true");
    expect(
      within(compactNavigation as HTMLElement).getByRole("link", {
        name: "Metric deck",
      }),
    ).toHaveFocus();
    const compactSessions = within(compactNavigation as HTMLElement).getByRole(
      "link",
      { name: "Sessions, 2 indexed" },
    );
    expect(compactSessions).not.toHaveAttribute("tabindex");
    fireEvent.click(compactSessions);
    expect(navigate).toHaveBeenCalledWith({
      name: "project_sessions",
      projectId,
    });

    act(() => observer.emit(true));
    expect(workspace).toHaveAttribute("data-masthead", "full");
    expect(compactNavigation).toHaveAttribute("aria-hidden", "true");
    expect(fullNavigation).not.toHaveAttribute("aria-hidden");
    expect(
      within(fullNavigation as HTMLElement).getByRole("link", {
        name: "Metric deck",
      }),
    ).toHaveFocus();
  });

  it("re-observes on route and project changes and disconnects every stale observer", async () => {
    installMastheadObserver();
    const { transport } = workspaceTransport();
    const { container, rerender, unmount } = render(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Example Observatory" }),
    ).toBeVisible();
    const first = MastheadIntersectionObserver.instances[0];
    act(() => first.emit(false));
    expect(container.querySelector(".project-workspace")).toHaveAttribute(
      "data-masthead",
      "compact",
    );

    rerender(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_sessions", projectId }}
        transport={transport}
      />,
    );
    expect(first.disconnect).toHaveBeenCalledTimes(1);
    const second = MastheadIntersectionObserver.instances[1];
    expect(second.observe).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".project-workspace")).toHaveAttribute(
      "data-masthead",
      "compact",
    );
    act(() => second.emit(true));
    expect(container.querySelector(".project-workspace")).toHaveAttribute(
      "data-masthead",
      "full",
    );
    act(() => first.emit(false));
    expect(container.querySelector(".project-workspace")).toHaveAttribute(
      "data-masthead",
      "full",
    );
    expect(first.takeRecords).toHaveBeenCalledTimes(1);

    rerender(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_overview", projectId: otherProjectId }}
        transport={transport}
      />,
    );
    expect(second.disconnect).toHaveBeenCalledTimes(1);
    expect(second.takeRecords).toHaveBeenCalledTimes(1);
    const third = MastheadIntersectionObserver.instances[2];
    expect(third.observe).toHaveBeenCalledTimes(1);

    unmount();
    expect(third.disconnect).toHaveBeenCalledTimes(1);
    expect(third.takeRecords).toHaveBeenCalledTimes(1);
  });

  it("exposes exact pages and nested locations through native project-section links", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    const { container, rerender } = render(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Example Observatory" }),
    ).toBeVisible();

    let navigation = screen.getByRole("navigation", {
      name: "Project sections",
    });
    expect(
      within(navigation).getByRole("link", { name: "Metric deck" }),
    ).toHaveAttribute("aria-current", "page");
    fireEvent.click(
      within(navigation).getByRole("link", { name: "Metric deck" }),
    );
    expect(navigate).not.toHaveBeenCalled();
    expect(container.querySelector(".project-workspace__view")).toHaveAttribute(
      "data-workspace-view",
      "deck",
    );

    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_metrics", projectId, category: "prompt-quality" }}
        transport={transport}
      />,
    );
    navigation = screen.getByRole("navigation", { name: "Project sections" });
    expect(
      within(navigation).getByRole("link", { name: "Metric deck" }),
    ).toHaveAttribute("aria-current", "location");
    expect(container.querySelector(".project-workspace__view")).toHaveAttribute(
      "data-workspace-view",
      "signals",
    );

    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{
          name: "session_metrics",
          projectId,
          sessionId,
          category: "prompt-quality",
        }}
        transport={transport}
      />,
    );
    navigation = screen.getByRole("navigation", { name: "Project sections" });
    expect(
      within(navigation).getByRole("link", { name: "Sessions, 2 indexed" }),
    ).toHaveAttribute("aria-current", "location");
    expect(container.querySelector(".project-workspace__view")).toHaveAttribute(
      "data-workspace-view",
      "signals",
    );
  });

  it("titles every project view and focuses headings after subsequent route changes", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    const { rerender } = render(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    const deckHeading = await screen.findByRole("heading", {
      name: "What do you want to review?",
    });
    await waitFor(() =>
      expect(document.title).toBe(
        "Metric deck · Example Observatory · Prompt Enhancer",
      ),
    );
    expect(deckHeading).not.toHaveFocus();

    fireEvent.click(screen.getByRole("link", { name: "Sessions, 2 indexed" }));
    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_sessions", projectId }}
        transport={transport}
      />,
    );
    const sessionsHeading = await screen.findByRole("heading", { name: "Sessions" });
    await waitFor(() => expect(sessionsHeading).toHaveFocus());
    expect(document.title).toBe("Sessions · Example Observatory · Prompt Enhancer");

    fireEvent.click(screen.getByRole("link", { name: "Metric deck" }));
    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    const restoredDeckHeading = await screen.findByRole("heading", {
      name: "What do you want to review?",
    });
    await waitFor(() => expect(restoredDeckHeading).toHaveFocus());
    expect(document.title).toBe("Metric deck · Example Observatory · Prompt Enhancer");

    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "session_metrics", projectId, sessionId, category: "tools" }}
        transport={transport}
      />,
    );
    const toolHeading = await screen.findByRole("heading", {
      name: "Validate sample adapter",
    });
    await waitFor(() => expect(toolHeading).toHaveFocus());
    expect(document.title).toBe(
      "Tool reliability signals · Example Observatory · Prompt Enhancer",
    );
  });

  it("retains a pending route heading focus while the project index is loading", async () => {
    const { transport } = workspaceTransport();
    const projectIndex = deferred<Awaited<ReturnType<PromptEnhancerTransport["listProjectSessions"]>>>();
    transport.listProjectSessions = vi.fn(() => projectIndex.promise);
    const { rerender } = render(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    await screen.findByText("Loading this project's stored session index...");

    const sessionsNavigation = screen.getByRole("link", { name: "Sessions" });
    sessionsNavigation.focus();
    rerender(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_sessions", projectId }}
        transport={transport}
      />,
    );
    expect(sessionsNavigation).toHaveFocus();

    await act(async () => {
      projectIndex.resolve({
        sessions,
        limit: 100,
        offset: 0,
        total: sessions.length,
        has_more: false,
      });
      await projectIndex.promise;
    });

    const sessionsHeading = await screen.findByRole("heading", { level: 2, name: "Sessions" });
    await waitFor(() => expect(sessionsHeading).toHaveFocus());
  });

  it("focuses the bounded quality heading instead of delegating a truncated project route", async () => {
    const { transport } = workspaceTransport();
    const truncatedSessions = Array.from({ length: 100 }, (_, index) => ({
      ...sessions[0],
      session_id: index.toString(16).padStart(64, "0"),
    }));
    transport.listProjectSessions = vi.fn(async () => ({
      sessions: truncatedSessions,
      limit: 100,
      offset: 0,
      total: 101,
      has_more: true,
    }));
    const { rerender } = render(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );
    await screen.findByRole("heading", { name: "What do you want to review?" });

    const promptQualityCard = screen.getByRole("button", { name: /Prompt quality/i });
    promptQualityCard.focus();
    rerender(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{ name: "project_metrics", projectId, category: "prompt-quality" }}
        transport={transport}
      />,
    );

    const boundaryHeading = await screen.findByRole("heading", { name: "Choose at most 100 sessions" });
    await waitFor(() => expect(boundaryHeading).toHaveFocus());
  });

  it("sets a useful route title for a valid project with no indexed sessions", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    transport.listProjectSessions = vi.fn(async () => ({
      sessions: [],
      limit: 100,
      offset: 0,
      total: 0,
      has_more: false,
    }));
    render(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_overview", projectId }}
        transport={transport}
      />,
    );

    expect(
      await screen.findByText(
        "This project is not present in the current bounded local index.",
      ),
    ).toBeVisible();
    await waitFor(() =>
      expect(document.title).toBe("Metric deck · Unnamed project · Prompt Enhancer"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Back to projects" }));
    expect(navigate).toHaveBeenCalledWith({ name: "projects" });
  });

  it("offers a direct project-session recovery when a selected session is absent", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    render(
      <ProjectWorkspace
        navigate={navigate}
        route={{
          name: "session_metrics",
          projectId,
          sessionId: "f".repeat(64),
          category: "tools",
        }}
        transport={transport}
      />,
    );

    expect(await screen.findByText("The selected session is not part of this indexed project.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open project sessions" }));
    expect(navigate).toHaveBeenCalledWith({ name: "project_sessions", projectId });
  });

  it("names each review context as signals rather than a universal metric", async () => {
    const { transport } = workspaceTransport();
    const { container, rerender } = render(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{
          name: "session_metrics",
          projectId,
          sessionId,
          category: "prompt-quality",
        }}
        transport={transport}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Example Observatory" }),
    ).toBeVisible();
    let context = container.querySelector(".project-workspace__context");
    expect(context).toHaveAttribute("aria-label", "Current signals");
    expect(within(context as HTMLElement).getByText("Signals")).toBeVisible();
    expect(
      within(context as HTMLElement).getByText("Prompt & collaboration signals"),
    ).toBeVisible();
    expect(screen.queryByText("Current metric")).not.toBeInTheDocument();

    rerender(
      <ProjectWorkspace
        navigate={vi.fn()}
        route={{
          name: "session_metrics",
          projectId,
          sessionId,
          category: "tools",
        }}
        transport={transport}
      />,
    );
    context = container.querySelector(".project-workspace__context");
    expect(
      within(context as HTMLElement).getByText("Tool reliability signals"),
    ).toBeVisible();
  });

  it("renders coaching beside an always-visible metric control deck", async () => {
    const { transport } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    transport.getSessionCoachingSummary = vi.fn(async () => coachingProjection());
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };

    render(<ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />);

    await openLegacyQualityProfile();

    expect(
      await screen.findByRole(
        "heading",
        { name: "Make the next task easier" },
        { timeout: 5_000 },
      ),
    ).toBeVisible();
    expect(screen.getByText("Task: Implementation")).toBeVisible();
    expect(screen.getByText("Outcome unknown")).toBeVisible();
    expect(screen.getByText("A repeated correction needs review")).toBeVisible();
    expect(screen.getByText("Methods & details").closest("details")).not.toHaveAttribute("open");
    expect(
      screen.getByRole("heading", { name: "Goal cue coverage" }),
    ).toBeVisible();
  });

  it("loads exactly one session response and filters it to the route category", async () => {
    const { transport, listProjectSessions, getSessionMetrics } = workspaceTransport();
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "tools",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    expect(await screen.findByText("Tool result count")).toBeVisible();
    expect(screen.queryByText("Provider total tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Future example observation")).not.toBeInTheDocument();
    expect(listProjectSessions).toHaveBeenCalledWith(
      projectId,
      100,
      0,
      expect.any(AbortSignal),
    );
    expect(getSessionMetrics).toHaveBeenCalledTimes(2); // category metrics + the radar card
    expect(getSessionMetrics).toHaveBeenCalledWith(sessionId, expect.any(AbortSignal));
  });

  it("offers keyboard-native metric cards without a session dropdown", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    const route: ProjectWorkspaceRoute = { name: "project_overview", projectId };
    const { rerender } = render(
      <ProjectWorkspace navigate={navigate} route={route} transport={transport} />,
    );

    expect(
      await screen.findByRole("heading", { name: "What do you want to review?" }),
    ).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    const deck = screen.getByRole("navigation", { name: "Metric categories" });
    const metricCards = within(deck).getAllByRole("button");
    expect(metricCards).toHaveLength(8);
    expect(metricCards[0]).toHaveAccessibleName(/Prompt quality/i);
    expect(metricCards[0]).toHaveClass("project-metric-card--featured");
    expect(within(metricCards[0]).getByText("Start here · radar profile")).toBeVisible();
    const promptCard = within(deck).getByRole("button", {
      name: /Prompt quality/i,
    });
    promptCard.focus();
    expect(promptCard).toHaveFocus();

    fireEvent.click(within(deck).getByRole("button", { name: /Tools/i }));
    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId,
      sessionId,
      category: "tools",
    });

    fireEvent.click(promptCard);
    expect(navigate).toHaveBeenCalledWith({
      name: "project_metrics",
      projectId,
      category: "prompt-quality",
    });

    fireEvent.click(screen.getByRole("link", { name: /^Sessions/ }));
    expect(navigate).toHaveBeenCalledWith({ name: "project_sessions", projectId });

    navigate.mockClear();
    rerender(
      <ProjectWorkspace
        navigate={navigate}
        route={{ name: "project_sessions", projectId }}
        transport={transport}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Open Review sample workflow" }),
    );
    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId,
      sessionId: secondSessionId,
      category: "prompt-quality",
    });
  });

  it("promotes the canonical metric workspace and keeps the prior quality profile in an explicit legacy disclosure", async () => {
    const {
      transport,
      getSessionMetrics,
      getLatestSessionQualityAnalysis,
    } = workspaceTransport();
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    const canonicalHeading = await screen.findByRole("heading", {
      name: "Measure the analyzed window, then estimate every eligible axis locally",
    });
    expect(canonicalHeading).toBeVisible();
    expect(screen.getByRole("region", { name: canonicalHeading.textContent ?? "" })).toHaveClass("model-ensemble");
    expect(screen.queryByRole("region", { name: "Canonical session metric workspace" })).not.toBeInTheDocument();
    expect(screen.getByText("Legacy coaching profile")).toBeVisible();
    expect(screen.getByText(/not the canonical measurement snapshot/i)).toBeVisible();
    expect(screen.queryByText("Prompt & collaboration coaching")).not.toBeInTheDocument();
    expect(screen.queryByText(/Ten-model chunk ensemble/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Legacy coaching profile"));
    expect(await screen.findByText("Prompt & collaboration coaching")).toBeVisible();
    expect(screen.getByText("0 assessable · 11 unavailable")).toBeVisible();
    expect(screen.getByText(/no placeholder values are generated/i)).toBeVisible();
    expect(document.title).toMatch(/^Prompt & collaboration signals ·/);
    expect(getSessionMetrics).toHaveBeenCalledTimes(1); // the session radar card is the one legitimate consumer
    expect(getLatestSessionQualityAnalysis).toHaveBeenCalledWith(
      sessionId,
      expect.any(AbortSignal),
    );
  });

  it("loads cached metric readiness without initiating a provider check", async () => {
    const {
      transport,
      getSessionMetricReadiness,
      checkProviderCompatibility,
    } = workspaceTransport();
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };

    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    await waitFor(() =>
      expect(getSessionMetricReadiness).toHaveBeenCalledWith(
        sessionId,
        "coaching_profile_v1",
        expect.any(AbortSignal),
      ),
    );
    expect(checkProviderCompatibility).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/content-free metric readiness could not be loaded/i),
    ).not.toBeInTheDocument();
  });

  it("keeps the synthetic demo session, run, and readiness provider identities coherent", async () => {
    const transport = createSyntheticTransport();
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId: SYNTHETIC_QUALITY_PROJECT_ID,
      sessionId: SYNTHETIC_QUALITY_SESSION_ID,
      category: "prompt-quality",
    };

    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText("Coherent metric pack v3", {}, { timeout: 5_000 }),
    ).toBeVisible();
    expect(
      screen.queryByText(/metric readiness did not match the selected session/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/content-free metric readiness could not be loaded/i),
    ).not.toBeInTheDocument();
  });

  it("preserves stored metric values when readiness metadata cannot be loaded", async () => {
    const { transport } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    const getSessionMetricReadiness = vi.fn(async () => {
      throw new Error("PRIVATE-READINESS-CANARY");
    });
    transport.getSessionMetricReadiness = getSessionMetricReadiness;
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };

    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText(/Content-free metric readiness could not be loaded/i),
    ).toBeVisible();
    expect(screen.getAllByText("100%").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain("PRIVATE-READINESS-CANARY");
    fireEvent.click(screen.getByRole("button", { name: "Retry readiness" }));
    await waitFor(() => expect(getSessionMetricReadiness).toHaveBeenCalledTimes(2));
  });

  it("renders one coherent immutable run without loading the legacy metric endpoint", async () => {
    const { transport, getSessionMetrics } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText("Coherent metric pack v1", {}, { timeout: 5_000 }),
    ).toBeVisible();
    expect(screen.getAllByText("100%").length).toBeGreaterThan(0);
    const modelLab = screen.getByText("Local model lab").closest("details");
    expect(modelLab).not.toHaveAttribute("open");
    expect(
      screen.getByRole("heading", {
        name: "Do the models link requests to the right agent work?",
        hidden: true,
      }),
    ).not.toBeVisible();
    expect(getSessionMetrics).toHaveBeenCalledTimes(1); // the session radar card is the one legitimate consumer
  });

  it("loads cached provider status without checking until the explicit action", async () => {
    const {
      transport,
      getProviderCompatibility,
      checkProviderCompatibility,
    } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByRole(
        "heading",
        { name: "Goal cue coverage" },
        { timeout: 5_000 },
      ),
    ).toBeVisible();
    expect(getProviderCompatibility).toHaveBeenCalledWith(
      "codex",
      expect.any(AbortSignal),
    );
    expect(checkProviderCompatibility).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(
      screen.getByRole("heading", { name: "Goal cue coverage" }),
    ).toBeVisible();
    expect(await screen.findByText("Exact match")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Check compatibility" }));
    await waitFor(() => expect(checkProviderCompatibility).toHaveBeenCalledTimes(1));
  });

  it("fails closed while an explicit compatibility refresh is pending or fails", async () => {
    const { transport } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    let rejectCheck: ((error: unknown) => void) | undefined;
    transport.checkProviderCompatibility = vi.fn(
      () =>
        new Promise<ProviderCompatibilityStatus>((_resolve, reject) => {
          rejectCheck = reject;
        }),
    );
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    const analyze = await screen.findByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(analyze).toBeEnabled());
    fireEvent.click(screen.getByText("Methods & details"));
    fireEvent.click(screen.getByRole("button", { name: "Check compatibility" }));

    await waitFor(() => expect(analyze).toBeDisabled());
    expect(screen.getByText(/compatibility is being checked/i)).toBeVisible();
    rejectCheck?.(new Error("PRIVATE-COMPATIBILITY-CANARY"));

    expect(
      await screen.findByText("The local compatibility check could not be completed."),
    ).toBeVisible();
    expect(analyze).toBeDisabled();
    expect(screen.getByText(/has not been checked/i)).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-COMPATIBILITY-CANARY");
  });

  it("clears only the canceled in-dialog compatibility request's loading state", async () => {
    const { transport } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    transport.prepareSessionQualityAnalysisPreview = vi.fn(async () => {
      throw new TransportError(
        "PRIVATE-PROVIDER-CANARY",
        503,
        "provider_compatibility_blocked",
      );
    });
    let compatibilitySignal: AbortSignal | undefined;
    transport.checkProviderCompatibility = vi.fn(
      (_provider: string, signal: AbortSignal) => {
        compatibilitySignal = signal;
        return new Promise<ProviderCompatibilityStatus>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("Canceled", "AbortError")),
            { once: true },
          );
        });
      },
    );
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    const analyze = await screen.findByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(analyze).toBeEnabled());
    fireEvent.click(analyze);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Recheck compatibility" }),
    );

    await waitFor(() => expect(compatibilitySignal).toBeInstanceOf(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));

    await waitFor(() => expect(compatibilitySignal?.aborted).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Check compatibility" })).toBeEnabled(),
    );
    expect(screen.queryByText("Loading")).not.toBeInTheDocument();
    expect(analyze).toBeDisabled();
  });

  it("keeps stored diagnostics accessible but blocks analysis for an incompatible provider", async () => {
    const { transport } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    transport.getProviderCompatibility = vi.fn(async () => ({
      ...EXACT_COMPATIBILITY,
      state: "incompatible" as const,
      capability_state: "unsupported" as const,
      reason_code: "source_schema_unsupported" as const,
    }));
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByRole("heading", { name: "Goal cue coverage" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeDisabled();
    expect(screen.getByText(/incompatible with prompt-text analysis/i)).toBeVisible();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(
      screen.getByRole("heading", { name: "Goal cue coverage" }),
    ).toBeVisible();
    expect(await screen.findByText("Incompatible")).toBeVisible();
    expect(screen.queryByRole("button", { name: /continue/i })).not.toBeInTheDocument();
  });

  it("runs analysis only after the explicit review, then fetches immutable detail", async () => {
    const { transport, prepareSessionQualityAnalysisPreview } = workspaceTransport();
    const approve = vi.fn(async () => ({
      run_id: qualityDetail().run.run_id,
      status: "completed" as const,
      result_count: 10,
      applied: true,
      analysis_profile_key: "coaching_profile" as const,
      analysis_profile_version: 1 as const,
    }));
    const getDetail = vi.fn(async () => qualityDetail());
    transport.approveSessionQualityAnalysisPreview = approve;
    transport.getSessionQualityAnalysisRun = getDetail;
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "reasoning",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    await screen.findByText(/no compatible Coaching v1 analysis run/i);
    expect(prepareSessionQualityAnalysisPreview).not.toHaveBeenCalled();
    const analyzeButton = screen.getByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(analyzeButton).toBeEnabled());
    fireEvent.click(analyzeButton);
    const dialog = screen.getByRole("dialog", { name: "Ready to analyze" });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Prepare redacted preview",
      }),
    );
    expect(prepareSessionQualityAnalysisPreview).toHaveBeenCalledWith(
      sessionId,
      { preset_id: "coaching_profile_v1" },
      expect.any(AbortSignal),
    );
    fireEvent.click(
      await within(dialog).findByRole("button", {
        name: "Approve once and analyze",
      }),
    );

    await waitFor(() => expect(approve).toHaveBeenCalledTimes(1));
    expect(approve).toHaveBeenCalledWith(
      "e".repeat(64),
      {
        confirmation: "approve_exact_redacted_preview",
        expected_binding: qualityPreview().binding,
      },
      expect.stringMatching(/^dashboard-quality-preview-approval-/),
      expect.any(AbortSignal),
    );
    expect(getDetail).toHaveBeenCalledWith(
      qualityDetail().run.run_id,
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("Coherent metric pack v1")).toBeVisible();
    expect(screen.getByText("Analysis completed and stored locally. The latest metric profile is now shown.")).toBeVisible();
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Ready to analyze" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("does not fetch result detail after a binding mismatch and prepares retry for the same session", async () => {
    const { transport, prepareSessionQualityAnalysisPreview } = workspaceTransport();
    transport.getLatestSessionQualityAnalysis = vi.fn(async () => qualityDetail());
    transport.approveSessionQualityAnalysisPreview = vi.fn(async () => {
      throw new TransportError(
        "PRIVATE-BINDING-CANARY",
        409,
        "redaction_preview_binding_mismatch",
      );
    });
    const getDetail = vi.fn(async () => qualityDetail());
    transport.getSessionQualityAnalysisRun = getDetail;
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(<ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />);

    await openLegacyQualityProfile();

    const analyze = await screen.findByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(analyze).toBeEnabled());
    fireEvent.click(analyze);
    const dialog = screen.getByRole("dialog", { name: "Ready to analyze" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Approve once and analyze" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/exact preview binding changed/i);
    expect(document.body.textContent).not.toContain("PRIVATE-BINDING-CANARY");
    expect(getDetail).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Prepare fresh preview" }));
    await waitFor(() => expect(prepareSessionQualityAnalysisPreview).toHaveBeenCalledTimes(2));
    expect(
      prepareSessionQualityAnalysisPreview.mock.calls.every(
        ([requestedSessionId]) => requestedSessionId === sessionId,
      ),
    ).toBe(true);
  });

  it("aborts a pending preview when navigation changes the selected session identity", async () => {
    const { transport } = workspaceTransport();
    let previewSignal: AbortSignal | undefined;
    const prepare = vi.fn(
      (_requestedSessionId: string, _request: unknown, signal?: AbortSignal) => {
        previewSignal = signal;
        return new Promise<SessionQualityAnalysisPreview>((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Canceled", "AbortError")),
            { once: true },
          );
        });
      },
    );
    transport.prepareSessionQualityAnalysisPreview = prepare;
    const firstRoute: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    const { rerender } = render(
      <ProjectWorkspace navigate={vi.fn()} route={firstRoute} transport={transport} />,
    );
    await openLegacyQualityProfile();
    const analyze = await screen.findByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(analyze).toBeEnabled());
    fireEvent.click(analyze);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    await waitFor(() => expect(previewSignal).toBeInstanceOf(AbortSignal));

    const secondRoute: ProjectWorkspaceRoute = {
      ...firstRoute,
      sessionId: secondSessionId,
    };
    rerender(
      <ProjectWorkspace navigate={vi.fn()} route={secondRoute} transport={transport} />,
    );

    await waitFor(() => expect(previewSignal?.aborted).toBe(true));
    expect(prepare).toHaveBeenCalledWith(
      sessionId,
      { preset_id: "coaching_profile_v1" },
      expect.any(AbortSignal),
    );
    expect(transport.approveSessionQualityAnalysisPreview).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Ready to analyze" })).not.toBeInTheDocument();
  });

  it("keeps analysis disabled when capability verification fails", async () => {
    const { transport } = workspaceTransport();
    transport.getSessionTextAnalysisCapability = vi.fn(async () => {
      throw new TransportError("PRIVATE-CAPABILITY-CANARY", 200);
    });
    const start = vi.spyOn(transport, "prepareSessionQualityAnalysisPreview");
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    const button = await screen.findByRole("button", { name: "Analyze locally" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(
      await screen.findByText(/capability status could not be verified/i),
    ).toBeVisible();
    fireEvent.click(button);
    expect(start).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("PRIVATE-CAPABILITY-CANARY");
  });

  it("keeps analysis disabled when redacted-content consent is revoked", async () => {
    const { transport } = workspaceTransport();
    transport.getCodexLocalSourceStatus = vi.fn(async () => ({
      consent_active: false,
      indexed_sessions: sessions.length,
      indexed_projects: 1,
      verification_capability: {
        state: "validation_only" as const,
        live_classification_enabled: false,
        supported_kinds: [],
        reason_code: "synthetic_validation_only",
      },
    }));
    const start = vi.spyOn(transport, "prepareSessionQualityAnalysisPreview");
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText(/redacted-text consent is not active/i),
    ).toBeVisible();
    const button = screen.getByRole("button", { name: "Analyze locally" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(start).not.toHaveBeenCalled();
  });

  it("fails closed when the content-free consent status cannot be loaded", async () => {
    const { transport } = workspaceTransport();
    transport.getCodexLocalSourceStatus = vi.fn(async () => {
      throw new TransportError("PRIVATE-CONSENT-STATUS-CANARY", 503);
    });
    const start = vi.spyOn(transport, "prepareSessionQualityAnalysisPreview");
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "reasoning",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText(/consent status could not be verified/i),
    ).toBeVisible();
    const button = screen.getByRole("button", { name: "Analyze locally" });
    expect(button).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("PRIVATE-CONSENT-STATUS-CANARY");
  });

  it("fails closed when the content-free consent status is malformed", async () => {
    const { transport } = workspaceTransport();
    transport.getCodexLocalSourceStatus = vi.fn(async () => ({
      consent_active: true,
    }) as never);
    const start = vi.spyOn(transport, "prepareSessionQualityAnalysisPreview");
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    await openLegacyQualityProfile();

    expect(
      await screen.findByText(/consent status could not be verified/i),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
  });

  it("requires one session instead of aggregating project metrics in the client", async () => {
    const { transport, getSessionMetrics } = workspaceTransport();
    const route: ProjectWorkspaceRoute = {
      name: "project_metrics",
      projectId,
      category: "model-usage",
    };
    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    expect(
      await screen.findByText("Choose a session for model usage"),
    ).toBeVisible();
    expect(screen.getByText(/not calculated in the browser/i)).toBeVisible();
    expect(getSessionMetrics).not.toHaveBeenCalled();
  });

  it("routes a project with missing Coaching v1 runs to a session for analysis", async () => {
    const { transport } = workspaceTransport();
    const navigate = vi.fn();
    const route: ProjectWorkspaceRoute = {
      name: "project_metrics",
      projectId,
      category: "prompt-quality",
    };

    render(
      <ProjectWorkspace navigate={navigate} route={route} transport={transport} />,
    );

    expect(
      await screen.findByText("2 of 2 sessions need analysis"),
    ).toBeVisible();
    expect(screen.getByText(/older metric packs remain preserved/i)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Open a session to analyze" }),
    );
    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId,
      sessionId,
      category: "prompt-quality",
    });
  });

  it("blocks a project-wide profile when page totals contradict the loaded scope", async () => {
    const { transport } = workspaceTransport();
    transport.listProjectSessions = vi.fn(async () => ({
      sessions: [sessions[0]],
      limit: 100,
      offset: 0,
      total: 2,
      has_more: false,
    }));
    const aggregate = vi.spyOn(transport, "aggregateSessionQuality");
    const route: ProjectWorkspaceRoute = {
      name: "project_metrics",
      projectId,
      category: "prompt-quality",
    };

    render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );

    expect(
      await screen.findByText("The project-scoped catalog response was inconsistent."),
    ).toBeVisible();
    expect(aggregate).not.toHaveBeenCalled();
    expect(screen.queryByText("Coherent metric pack v1")).not.toBeInTheDocument();
  });

  it("aborts an in-flight metric read when the workspace is left", async () => {
    const { transport } = workspaceTransport();
    let metricSignal: AbortSignal | undefined;
    transport.getSessionMetrics = vi.fn((_sessionId, signal) => {
      metricSignal = signal;
      return new Promise<never>(() => undefined);
    });
    const route: ProjectWorkspaceRoute = {
      name: "session_metrics",
      projectId,
      sessionId,
      category: "tools",
    };
    const { unmount } = render(
      <ProjectWorkspace navigate={vi.fn()} route={route} transport={transport} />,
    );
    await waitFor(() => expect(metricSignal).toBeDefined());
    unmount();
    expect(metricSignal?.aborted).toBe(true);
  });
});
