import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ProviderCompatibilityStatus,
  SessionMetricReadinessReport,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_CURRENT_SESSION_QUALITY_RUN,
  SYNTHETIC_SESSION_METRIC_READINESS,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "../../shared/api/syntheticFixtures";
import { createQualityMetricProfile } from "./qualityProfile";
import { QualityProfileView, type AnalyzeLocallyHandler } from "./QualityProfileView";

function promptProfile() {
  return createQualityMetricProfile(
    "prompt-quality",
    structuredClone(SYNTHETIC_SESSION_QUALITY_RUN),
    SYNTHETIC_QUALITY_SESSION_ID,
  )!;
}

function exactSubsetProfile() {
  const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
  const selectedKey = "prompt.goal_definition";
  detail.results = detail.results.filter((item) => item.key === selectedKey);
  detail.run.selected_metric_keys = [selectedKey];
  return createQualityMetricProfile(
    "prompt-quality",
    detail,
    SYNTHETIC_QUALITY_SESSION_ID,
  )!;
}

function legacyUnknownScopeProfile() {
  const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
  detail.run.metric_scope_state = "legacy_unknown";
  detail.run.selected_metric_keys = [];
  detail.results = [];
  return createQualityMetricProfile(
    "prompt-quality",
    detail,
    SYNTHETIC_QUALITY_SESSION_ID,
  )!;
}

function analysisFlow(): AnalyzeLocallyHandler {
  return {
    exactSessionId: SYNTHETIC_QUALITY_SESSION_ID,
    preparePreview: vi.fn(async () => {
      throw new Error("not exercised");
    }),
    approvePreview: vi.fn(async () => undefined),
  };
}

function coachingPromptProfile() {
  const profile = promptProfile();
  profile.analysisProfile = {
    state: "coaching",
    label: "Coaching profile v1",
  };
  profile.latest.metricPackVersion = 3;
  return profile;
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

const SYNTHETIC_EXACT_COMPATIBILITY: ProviderCompatibilityStatus = {
  ...EXACT_COMPATIBILITY,
  provider: "synthetic",
  provider_family: "synthetic_provider",
  source_schema_family: "synthetic_session",
};

describe("QualityProfileView", () => {
  it("does not present repeatable rule output as an accuracy claim", () => {
    render(<QualityProfileView profile={promptProfile()} />);

    expect(screen.getByText("Accuracy not established")).toBeInTheDocument();
    expect(screen.getByText(/representative independent human holdout/i)).toBeInTheDocument();
  });

  it("keeps an open analysis review bound to the transport captured by its opener", () => {
    const first = analysisFlow();
    const second = analysisFlow();
    const profile = promptProfile();
    const common = {
      analysisCapability: {
        available: true,
        reason_code: "available",
        data_tier: "redacted_content",
        content_persistence: false,
        network_inference: false,
        raw_transcripts: false,
      } as const,
      profile,
      providerCompatibility: EXACT_COMPATIBILITY,
    };
    const { rerender } = render(
      <QualityProfileView {...common} onAnalyzeLocally={first} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Analyze locally" }));

    rerender(<QualityProfileView {...common} onAnalyzeLocally={second} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));

    expect(first.preparePreview).toHaveBeenCalledTimes(1);
    expect(second.preparePreview).not.toHaveBeenCalled();
  });

  it("does not turn malformed counted signals or an empty profile into zero-state claims", () => {
    const profile = promptProfile();
    profile.latest.metrics[0].signals = [{
      code: "goal.action",
      status: "counted",
      count: null,
    }];
    const { rerender } = render(<QualityProfileView profile={profile} />);
    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText("Count unavailable")).toBeVisible();

    const empty = promptProfile();
    empty.latest.metrics = [];
    rerender(<QualityProfileView profile={empty} />);
    expect(screen.getByText("No metric observations supplied")).toBeVisible();
    expect(screen.queryByText(/No metric in this view was selected/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/No compatible Coaching v1 analysis run is available/i)).not.toBeInTheDocument();
  });

  it("synchronously resets initial-snapshot and pinned state when a same-kind profile changes", () => {
    const first = promptProfile();
    first.initial = {
      ...structuredClone(first.latest),
      kind: "initial",
    };
    const second = promptProfile();
    second.initial = {
      ...structuredClone(second.latest),
      kind: "initial",
    };
    second.latest.metrics[0].ratio = 0.5;
    second.latest.metrics[0].fractionNumerator = 1;
    second.latest.metrics[0].fractionDenominator = 2;
    second.latest.metrics[0].algorithmVersion = "synthetic-revision-b";
    second.latest.metrics[0].computedAt = "2040-01-02T00:00:00Z";

    const { rerender } = render(<QualityProfileView profile={first} />);
    fireEvent.click(screen.getByRole("button", { name: "Initial request" }));
    fireEvent.click(screen.getByRole("button", { name: /Checkability cue coverage/i }));
    expect(screen.getByRole("button", { name: "Clear pin" })).toBeVisible();

    rerender(<QualityProfileView profile={second} />);

    expect(screen.getByRole("button", { name: "Latest analysis window" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByRole("button", { name: "Clear pin" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Goal cue coverage/i })).toHaveTextContent("50%");
  });

  it("withholds cross-session readiness and never renders an arbitrary readiness error", () => {
    const readiness = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    readiness.session_id = "d".repeat(64);
    const privateError = "PRIVATE-READINESS-DETAIL-CANARY";

    render(
      <QualityProfileView
        analysisCapability={{
          available: true,
          reason_code: "available",
          data_tier: "redacted_content",
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        }}
        metricReadiness={readiness}
        metricReadinessError={privateError}
        onAnalyzeLocally={analysisFlow()}
        profile={promptProfile()}
        providerCompatibility={EXACT_COMPATIBILITY}
      />,
    );

    expect(screen.getByText(/content-free metric readiness could not be loaded/i)).toBeVisible();
    expect(screen.getByText(/current-provider ownership could not be verified/i)).toBeVisible();
    expect(document.body).not.toHaveTextContent(privateError);
    expect(screen.queryByText(/Missing evidence channels:/i)).not.toBeInTheDocument();
  });

  it.each([
    {
      label: "foreign metric-pack key",
      mutate: (report: SessionMetricReadinessReport) => {
        report.metric_pack_key = "experimental.redacted-text.foreign";
      },
      compatibility: SYNTHETIC_EXACT_COMPATIBILITY,
    },
    {
      label: "foreign preset",
      mutate: (report: SessionMetricReadinessReport) => {
        report.preset_id = "standard_engineering_v1";
      },
      compatibility: SYNTHETIC_EXACT_COMPATIBILITY,
    },
    {
      label: "current-provider mismatch",
      mutate: (_report: SessionMetricReadinessReport) => undefined,
      compatibility: EXACT_COMPATIBILITY,
    },
  ])("withholds readiness with a $label", ({ mutate, compatibility }) => {
    const readiness = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
    mutate(readiness);

    render(
      <QualityProfileView
        metricReadiness={readiness}
        onAnalyzeLocally={analysisFlow()}
        profile={coachingPromptProfile()}
        providerCompatibility={compatibility}
      />,
    );

    expect(screen.getByText(/readiness metadata was withheld/i)).toBeVisible();
    expect(screen.queryByText(/readiness verified/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Checkability cue coverage/i })).toHaveTextContent(
      "50%",
    );
  });

  it("fails closed when no current-provider compatibility context is available", () => {
    render(
      <QualityProfileView
        metricReadiness={structuredClone(SYNTHETIC_SESSION_METRIC_READINESS)}
        onAnalyzeLocally={analysisFlow()}
        profile={coachingPromptProfile()}
      />,
    );

    expect(screen.getByText(/readiness metadata was withheld/i)).toBeVisible();
    expect(screen.queryByText(/readiness verified/i)).not.toBeInTheDocument();
  });

  it("accepts readiness only for the exact coaching profile and current provider context", () => {
    render(
      <QualityProfileView
        metricReadiness={structuredClone(SYNTHETIC_SESSION_METRIC_READINESS)}
        onAnalyzeLocally={analysisFlow()}
        profile={coachingPromptProfile()}
        providerCompatibility={SYNTHETIC_EXACT_COMPATIBILITY}
      />,
    );

    expect(screen.getByText(/readiness verified for this exact session and metric pack/i)).toHaveTextContent(
      "20 metric records",
    );
    expect(screen.queryByText(/readiness metadata was withheld/i)).not.toBeInTheDocument();
  });

  it.each([
    {
      label: "null metrics",
      mutate: (report: Record<string, unknown>) => {
        report.metrics = null;
      },
    },
    {
      label: "non-array metrics",
      mutate: (report: Record<string, unknown>) => {
        report.metrics = { metric_key: "prompt.goal_definition" };
      },
    },
    {
      label: "null capability report",
      mutate: (report: Record<string, unknown>) => {
        report.capability_report = null;
      },
    },
    {
      label: "malformed metric record",
      mutate: (report: Record<string, unknown>) => {
        const metrics = [...(report.metrics as unknown[])];
        metrics[0] = null;
        report.metrics = metrics;
      },
    },
  ])("bounds a prop-supplied readiness report with $label", ({ mutate }) => {
    const readiness = structuredClone(
      SYNTHETIC_SESSION_METRIC_READINESS,
    ) as unknown as Record<string, unknown>;
    mutate(readiness);

    render(
      <QualityProfileView
        metricReadiness={readiness as unknown as SessionMetricReadinessReport}
        onAnalyzeLocally={analysisFlow()}
        profile={coachingPromptProfile()}
        providerCompatibility={SYNTHETIC_EXACT_COMPATIBILITY}
      />,
    );

    expect(screen.getByText(/readiness metadata was withheld/i)).toBeVisible();
    expect(screen.queryByText(/readiness verified/i)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("0 metric records");
    expect(screen.getByRole("button", { name: /Checkability cue coverage/i })).toHaveTextContent(
      "50%",
    );
  });

  it("summarizes valid incompatibility separately and preserves compatible metric cards", () => {
    const profile = promptProfile();
    profile.latest.integrity = "mixed-provenance";
    Object.assign(profile.latest.metrics[0], {
      state: "incompatible" as const,
      ratio: null,
      fractionNumerator: null,
      fractionDenominator: null,
      observed: 0,
      eligible: 0,
      coverage: 0,
      errorCode: "incompatible-provenance" as const,
    });

    render(<QualityProfileView profile={profile} />);

    expect(screen.getByText(/2 partial · 1 incompatible/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /Goal cue coverage/i })).toHaveTextContent(
      "Incompatible",
    );
    expect(screen.getByRole("button", { name: /Checkability cue coverage/i })).toHaveTextContent(
      "50%",
    );
    expect(screen.getByText(/Incompatible metrics are withheld from the radar and sharing/i)).toBeVisible();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText(/No combined value is shown and this state is not an execution failure/i)).toBeVisible();
  });

  it("labels exact-scope omissions separately from unknown, failed, and zero", () => {
    const { container } = render(<QualityProfileView profile={exactSubsetProfile()} />);

    expect(screen.getByText(/0 assessable · 1 partial · 4 not selected/)).toBeVisible();
    expect(screen.getByLabelText("Radar availability")).toHaveTextContent(
      "4 not selected",
    );
    const omitted = screen.getByRole("button", { name: /Expected constraint cues/i });
    expect(omitted).toHaveTextContent("Not selected");
    expect(omitted).toHaveTextContent("1 run omitted by selected scope");
    expect(omitted.querySelector(".quality-board__track--missing > span")).toBeNull();

    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getAllByText(/outside the exact metric scope/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/excluded—not missing or failed/i).length).toBeGreaterThan(0);
    expect(container).not.toHaveTextContent(/No compatible Coaching v1 analysis run/i);
  });

  it("explains a coherent legacy unknown scope without claiming no run exists", () => {
    render(<QualityProfileView profile={legacyUnknownScopeProfile()} />);

    expect(screen.getByText(
      /A compatible legacy run exists, but its selected metric scope was not recorded/i,
    )).toBeVisible();
    expect(screen.getByText(/cannot be classified as selected, omitted, or failed/i)).toBeVisible();
    expect(screen.queryByText(/No compatible Coaching v1 analysis run is available/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getAllByText(/1 completed legacy run does not preserve/i).length).toBeGreaterThan(0);
  });

  it("shows every metric in one zero-configuration control deck", () => {
    const profile = promptProfile();
    const { container } = render(<QualityProfileView profile={promptProfile()} />);

    expect(screen.getByRole("heading", { name: "Prompt contract" })).toBeVisible();
    expect(screen.getByText(/Radar withheld · exact-value bars/)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Radar availability")).toHaveTextContent("3 measured");
    expect(screen.getByLabelText("Radar availability")).toHaveTextContent("2 plottable axes");
    expect(screen.getByLabelText("Radar availability")).toHaveTextContent("2 abstained");
    const board = screen.getByRole("region", { name: "Prompt-quality candidates" });
    expect(board).toBeVisible();
    for (const metric of profile.latest.metrics) {
      expect(within(board).getByText(metric.definition.label)).toBeVisible();
    }
    expect(
      container.querySelectorAll(
        ".quality-board__track:not(.quality-board__track--missing)",
      ),
    ).toHaveLength(3);
    expect(container.querySelectorAll(".quality-board__metric")).toHaveLength(5);
    expect(container.querySelector("select")).not.toBeInTheDocument();
    expect(container.querySelector('input[type="checkbox"]')).not.toBeInTheDocument();
    expect(container.querySelectorAll(".quality-profile__radar-panel")).toHaveLength(1);
    expect(container.querySelectorAll(".quality-profile__method-boundary")).toHaveLength(1);
    expect(container.querySelectorAll(".quality-radar__inspector-details")).toHaveLength(1);
    const radarPanel = container.querySelector(".quality-profile__radar-panel");
    expect(radarPanel).toHaveAttribute("open");
    expect(screen.getByText("Prompt-quality radar")).toBeVisible();
    fireEvent.click(within(radarPanel as HTMLElement).getByText("Prompt-quality radar"));
    expect(radarPanel).not.toHaveAttribute("open");
    fireEvent.click(within(radarPanel as HTMLElement).getByText("Prompt-quality radar"));
    expect(radarPanel).toHaveAttribute("open");
    expect(screen.getByText("Methods & details")).toBeVisible();
    expect(screen.getByText("Broader value map")).toBeVisible();
    expect(screen.getByText("9 families")).toBeVisible();
    expect(
      screen.getByText(/0 assessable · 3 partial · 2 not measurable/),
    ).toBeVisible();
    const goalMetric = within(board)
      .getByText("Goal cue coverage")
      .closest(".quality-board__metric");
    expect(goalMetric).not.toBeNull();
    expect(
      goalMetric?.querySelector<HTMLElement>(".quality-board__track > span"),
    ).toHaveStyle({ width: "100%" });
    expect(screen.queryByText("Overall score")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText("Standard engineering v1")).toBeVisible();
    expect(screen.getByRole("heading", { name: "How these percentages are produced" })).toBeVisible();
    expect(screen.getByText(/Active coaching model: none/i)).toBeVisible();
    expect(screen.getByText(/Qwen3 Embedding 0.6B and BGE Reranker v2 M3/i)).toBeVisible();
    expect(screen.getByText(/3 of 3 metric-specific items/i)).toBeVisible();
    expect(screen.getAllByText(/8 of 10 eligible observations/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Requested action cue")).toBeVisible();
    expect(screen.getAllByText("Detected")).toHaveLength(3);
    expect(screen.getByText(/lower is better only as a review cue/i)).toBeVisible();
  });

  it("keeps the absent initial snapshot disabled and exposes only an explicit run action", () => {
    render(
      <QualityProfileView
        analysisCapability={{
          available: true,
          reason_code: "available",
          data_tier: "redacted_content",
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        }}
        onAnalyzeLocally={analysisFlow()}
        providerCompatibility={EXACT_COMPATIBILITY}
        profile={promptProfile()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Initial request" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeEnabled();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText("Exact match")).toBeVisible();
  });

  it("keeps results visible but analysis disabled until compatibility is checked", () => {
    const onCheck = vi.fn(async () => undefined);
    render(
      <QualityProfileView
        analysisCapability={{
          available: true,
          reason_code: "available",
          data_tier: "redacted_content",
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        }}
        onAnalyzeLocally={analysisFlow()}
        onCheckProviderCompatibility={onCheck}
        profile={promptProfile()}
      />,
    );

    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeDisabled();
    expect(screen.getByText(/has not been checked/i)).toBeVisible();
    expect(
      within(screen.getByRole("region", { name: "Prompt-quality candidates" })).getByText(
        "Goal cue coverage",
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText("Standard engineering v1")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Check provider" }));
    expect(onCheck).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /continue/i })).not.toBeInTheDocument();
  });

  it("warns when a completed run has legacy or unknown preset provenance", () => {
    const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
    delete (detail.run as Partial<typeof detail.run>).analysis_profile_key;
    delete (detail.run as Partial<typeof detail.run>).analysis_profile_version;
    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    render(<QualityProfileView profile={profile} />);

    fireEvent.click(screen.getByText("Methods & details"));
    expect(screen.getByText("Legacy / unknown analysis profile")).toBeVisible();
    expect(screen.queryByText("Standard engineering v1")).not.toBeInTheDocument();
  });

  it("fails closed with a truthful capability reason", () => {
    render(
      <QualityProfileView
        analysisCapability={{
          available: false,
          reason_code: "local_source_unavailable",
          data_tier: null,
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        }}
        onAnalyzeLocally={analysisFlow()}
        profile={promptProfile()}
      />,
    );

    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeDisabled();
    expect(screen.getByText(/local-source adapter is not active/i)).toBeVisible();
  });

  it("does not enable analysis before capability verification completes", () => {
    render(
      <QualityProfileView
        onAnalyzeLocally={analysisFlow()}
        profile={promptProfile()}
      />,
    );

    expect(screen.getByRole("button", { name: "Analyze locally" })).toBeDisabled();
    expect(screen.getByText(/checking whether this local installation/i)).toBeVisible();
  });

  it("blocks values and sharing when the immutable result contract is contradictory", () => {
    const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
    detail.results[0].coverage = 1;
    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const { container } = render(<QualityProfileView profile={profile} />);

    expect(container.querySelector(".quality-profile__snapshot-alert")).toHaveTextContent(
      "Invalid metric contract",
    );
    expect(screen.getByRole("button", { name: "Share profile" })).toBeDisabled();
    expect(screen.getByText(/comparison and sharing are blocked/i)).toBeVisible();
    expect(container.querySelectorAll(".quality-board__metric--missing")).toHaveLength(5);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("presents an older coaching pack as re-analysis work, not corruption", () => {
    const detail = structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
    detail.run.analysis_profile_key = "coaching_profile";
    detail.run.analysis_profile_version = 1;
    detail.run.metric_pack_key = "experimental.redacted-text.coaching";
    detail.run.metric_pack_version = 1;
    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    render(<QualityProfileView profile={profile} />);

    expect(screen.getByText(/re-analysis required/i)).toBeVisible();
    expect(screen.getByText(/older immutable metric pack/i)).toBeVisible();
    expect(screen.queryByText("Invalid metric contract")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/profile comparison and sharing are blocked/i),
    ).not.toBeInTheDocument();
  });

  it("labels an unresolved provider-adapter contract as unavailable without inventing a value", () => {
    const detail = structuredClone(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN);
    const metric = detail.results.find(
      (result) => result.key === "outcome.agent_claim_grounding",
    )!;
    metric.value_state = "unknown";
    metric.numeric_value = null;
    metric.fraction = null;
    metric.observed_count = 0;
    metric.eligible_count = 0;
    metric.coverage = 0;
    metric.explanation_code = "objective_verification_stream_required";
    const profile = createQualityMetricProfile(
      "reasoning",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    render(<QualityProfileView profile={profile} />);

    const card = screen.getByText("Agent claim grounding").closest("article")!;
    expect(within(card).getByText("Provider adapter unavailable")).toBeInTheDocument();
    expect(within(card).getByText(/agent prose, model estimates, and missing evidence never fill the value or become zero/i)).toBeInTheDocument();
    expect(within(card).getByText("—")).toBeInTheDocument();
  });

  it.each([
    ["observed", "Rule candidate"],
    ["partial", "Partial rule candidate"],
    ["not-selected", "Not selected"],
    ["incompatible", "Incompatible provenance"],
  ] as const)("keeps a %s provider-gap status instead of relabeling it unavailable", (state, label) => {
    const detail = structuredClone(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN);
    const profile = createQualityMetricProfile(
      "reasoning",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const metric = profile.latest.metrics.find(
      (candidate) => candidate.definition.key === "outcome.agent_claim_grounding",
    )!;
    metric.state = state;

    render(<QualityProfileView profile={profile} />);

    const card = screen.getByText("Agent claim grounding").closest("article")!;
    expect(within(card).getByText(label)).toBeInTheDocument();
    expect(within(card).queryByText("Provider adapter unavailable")).toBeNull();
  });

  it("does not allow sharing a no-run profile", () => {
    const profile = createQualityMetricProfile(
      "reasoning",
      null,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    render(<QualityProfileView profile={profile} />);

    expect(screen.getByText(/no compatible Coaching v1 analysis run/i)).toBeVisible();
    const shareButton = screen.getByRole("button", { name: "Share profile" });
    expect(shareButton).toBeDisabled();
    expect(shareButton).toHaveAttribute(
      "title",
      "Run Coaching v1 analysis before sharing",
    );
    expect(
      screen.queryByText(/profile comparison and sharing are blocked/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});
