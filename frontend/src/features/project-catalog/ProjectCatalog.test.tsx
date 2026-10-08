import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  CodexSession,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import {
  SYNTHETIC_METRIC_COVERAGE,
  SYNTHETIC_QUALITY_PROJECT_ID,
} from "../../shared/api/syntheticFixtures";
import { TransportError } from "../../shared/api/httpTransport";
import { ProjectCatalog } from "./ProjectCatalog";

const projectA = SYNTHETIC_QUALITY_PROJECT_ID;
const projectB = "b".repeat(64);

function session(input: {
  sessionId: string;
  projectId: string;
  projectName: string;
  sessionName: string;
  startedAt: string;
  complete?: boolean;
}): CodexSession {
  return {
    session_id: input.sessionId,
    installation_id: "1".repeat(64),
    project_id: input.projectId,
    project_display_name: input.projectName,
    session_display_name: input.sessionName,
    provider: "codex",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: input.startedAt,
    ended_at: null,
    terminal_state: null,
    events_complete: input.complete ?? false,
  };
}

const sessions = [
  session({
    sessionId: "c".repeat(64),
    projectId: projectA,
    projectName: "Example Observatory",
    sessionName: "Plan fictional catalog",
    startedAt: "2040-01-01T09:00:00Z",
    complete: true,
  }),
  session({
    sessionId: "d".repeat(64),
    projectId: projectA,
    projectName: "Example Observatory",
    sessionName: "Validate fictional catalog",
    startedAt: "2040-01-02T09:00:00Z",
  }),
  session({
    sessionId: "e".repeat(64),
    projectId: projectB,
    projectName: "Sample Workshop",
    sessionName: "Review sample workflow",
    startedAt: "2040-01-03T09:00:00Z",
  }),
];

function transportWithSessions(): {
  transport: PromptEnhancerTransport;
  listCodexSessions: ReturnType<typeof vi.fn>;
  aggregateProjectQuality: ReturnType<typeof vi.fn>;
} {
  const listCodexSessions = vi.fn(async () => ({
    sessions,
    limit: 100,
    offset: 0,
  }));
  const synthetic = createSyntheticTransport();
  const aggregateProjectQuality = vi.fn(async () =>
    synthetic.aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    }),
  );
  return {
    transport: {
      ...synthetic,
      listCodexSessions,
      aggregateProjectQuality,
    },
    listCodexSessions,
    aggregateProjectQuality,
  };
}

describe("ProjectCatalog", () => {
  it("drops selected projects removed by a verified catalog reload", async () => {
    const { transport } = transportWithSessions();
    const { rerender } = render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /Sample Workshop/ }));
    expect(screen.getByRole("complementary", { name: "Project aggregate selection" })).toHaveTextContent("1 project selected");
    const nextTransport = {
      ...transport,
      listCodexSessions: vi.fn(async () => ({ sessions: sessions.filter((item) => item.project_id !== projectB), limit: 100, offset: 0 })),
    };
    rerender(<ProjectCatalog navigate={vi.fn()} transport={nextTransport} />);
    await screen.findByText("Example Observatory");
    expect(screen.queryByRole("complementary", { name: "Project aggregate selection" })).toBeNull();
    expect(screen.queryByText(/hidden by the current filter/)).toBeNull();
  });

  it("mounts provider-wide coverage without coupling it to catalog success", async () => {
    const { transport } = transportWithSessions();
    const getMetricCoverage = vi.fn(async () => SYNTHETIC_METRIC_COVERAGE);
    transport.getMetricCoverage = getMetricCoverage;
    render(
      <ProjectCatalog
        coverageProvider="synthetic"
        navigate={vi.fn()}
        transport={transport}
      />,
    );

    expect(await screen.findByText("Example Observatory")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Coaching metric coverage" }))
      .toBeVisible();
    expect(getMetricCoverage).toHaveBeenCalledWith(
      "synthetic",
      expect.any(AbortSignal),
    );

    transport.getMetricCoverage = vi.fn(async () => {
      throw new Error("PRIVATE-COVERAGE-CANARY");
    });
    render(
      <ProjectCatalog navigate={vi.fn()} transport={transport} />,
    );
    expect((await screen.findAllByText("Example Observatory")).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("heading", { name: "Metric coverage: Unknown" })).length)
      .toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain("PRIVATE-COVERAGE-CANARY");
  });

  it("groups the bounded stored session list by full project pseudonym", async () => {
    const { transport, listCodexSessions } = transportWithSessions();
    const navigate = vi.fn();
    render(<ProjectCatalog navigate={navigate} transport={transport} />);

    expect(await screen.findByText("Example Observatory")).toBeVisible();
    expect(screen.getByText("Sample Workshop")).toBeVisible();
    expect(screen.getByText("2", { selector: "dd" })).toBeVisible();
    expect(document.body.textContent).not.toContain(projectA);
    expect(document.body.textContent).not.toContain(projectB);
    expect(listCodexSessions).toHaveBeenCalledTimes(1);
    expect(listCodexSessions).toHaveBeenCalledWith(100, 0, expect.any(AbortSignal));

    fireEvent.click(screen.getByRole("button", { name: "Open project Example Observatory" }));
    expect(navigate).toHaveBeenCalledWith({
      name: "project_overview",
      projectId: projectA,
    });
  });

  it("searches compactly across fictional project and session labels", async () => {
    const { transport } = transportWithSessions();
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Example Observatory");

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "sample workflow" },
    });
    expect(screen.queryByText("Example Observatory")).not.toBeInTheDocument();
    expect(screen.getByText("Sample Workshop")).toBeVisible();

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "does not exist" },
    });
    expect(screen.getByText("No matching projects")).toBeVisible();
  });

  it("accepts the backend's full safe 128-character version vocabulary", async () => {
    const compatible = {
      ...sessions[0],
      provider_version: "codex:app-server/0.144.5",
      adapter_version: `a${"x".repeat(127)}`,
      source_schema_version: "codex.app-server/v2+thread",
    };
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn(async () => ({
        sessions: [compatible],
        limit: 100,
        offset: 0,
      })),
    };

    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    expect(await screen.findByText("Example Observatory")).toBeVisible();
    expect(
      screen.queryByText("The locally indexed project catalog response was invalid."),
    ).not.toBeInTheDocument();
  });

  it("combines an explicit selection without navigation or client-side averaging", async () => {
    const { transport, aggregateProjectQuality, listCodexSessions } =
      transportWithSessions();
    const navigate = vi.fn();
    const latestQuality = vi.spyOn(transport, "getLatestSessionQualityAnalysis");
    render(<ProjectCatalog navigate={navigate} transport={transport} />);
    await screen.findByText("Example Observatory");

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select Example Observatory for combined profile",
      }),
    );
    const selection = screen.getByRole("complementary", {
      name: "Project aggregate selection",
    });
    expect(selection).toHaveTextContent(/1 project selected/i);
    fireEvent.click(
      within(selection).getByRole("button", { name: "Combine selected" }),
    );

    const resultHeading = await screen.findByRole("heading", {
      name: "Combined project signal profile",
    });
    expect(resultHeading).toBeVisible();
    await waitFor(() => expect(resultHeading).toHaveFocus());
    expect(document.title).toBe("Combined project signals · Prompt Enhancer");
    expect(aggregateProjectQuality).toHaveBeenCalledWith(
      {
        project_ids: [projectA],
        selection_mode: "all_analyzed_work",
      },
      expect.any(AbortSignal),
    );
    expect(navigate).not.toHaveBeenCalled();
    expect(latestQuality).not.toHaveBeenCalled();
    expect(listCodexSessions).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText(
        "All analyzed work · per eligible opportunity · ratio of sums",
      ),
    ).toBeVisible();
    const coverage = screen.getByLabelText("Combined profile coverage");
    expect(within(coverage).getAllByRole("definition")).toHaveLength(4);
    expect(coverage).toHaveTextContent(/Projects1Sessions1Completed1Missing0/);
    const lenses = screen.getByRole("group", { name: "Quality lenses" });
    expect(within(lenses).getAllByRole("button")).toHaveLength(4);
    expect(document.body.textContent).not.toContain(projectA);

    fireEvent.click(screen.getByRole("button", { name: "Back to projects" }));
    expect(await screen.findByText("Example Observatory")).toBeVisible();
    expect(screen.getByRole("checkbox", {
      name: "Select Example Observatory for combined profile",
    })).toBeChecked();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Combine selected" })).toHaveFocus(),
    );
    expect(document.title).toBe("Projects · Prompt Enhancer");
  });

  it("fails closed on an incompatible aggregate without exposing response content", async () => {
    const { transport } = transportWithSessions();
    const valid = await transport.aggregateProjectQuality({
      project_ids: [projectA],
      selection_mode: "all_analyzed_work",
    });
    transport.aggregateProjectQuality = vi.fn(async () => ({
      ...valid,
      private_label: "PRIVATE-AGGREGATE-CANARY",
    }) as never);
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Example Observatory");
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select Example Observatory for combined profile",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Combine selected" }));

    expect(
      await screen.findByText(
        "The local aggregate returned an incompatible metric contract.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Example Observatory")).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-AGGREGATE-CANARY");
  });

  it("rejects a provenance-incompatible nested aggregate", async () => {
    const { transport } = transportWithSessions();
    const valid = await transport.aggregateProjectQuality({
      project_ids: [projectA],
      selection_mode: "all_analyzed_work",
    });
    transport.aggregateProjectQuality = vi.fn(async () => ({
      ...valid,
      session_quality: {
        ...valid.session_quality,
        integrity_state: "incompatible" as const,
      },
    }));
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Example Observatory");
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select Example Observatory for combined profile",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Combine selected" }));

    expect(
      await screen.findByText(
        "The local aggregate returned an incompatible metric contract.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Combined project signal profile" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    [
      409,
      "One or more selected projects are no longer available in the safe local index.",
    ],
    [422, "The selected work exceeds the bounded local aggregate limit."],
  ])("maps backend status %s to a fixed content-free error", async (status, message) => {
    const { transport } = transportWithSessions();
    transport.aggregateProjectQuality = vi.fn(async () => {
      throw new TransportError("PRIVATE-SELECTION-CANARY", status);
    });
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Example Observatory");
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select Example Observatory for combined profile",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Combine selected" }));

    expect(await screen.findByText(message)).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-SELECTION-CANARY");
    expect(document.body.textContent).not.toContain(projectA);
  });

  it("caps explicit aggregate selection at 25 projects", async () => {
    const manySessions = Array.from({ length: 26 }, (_, index) =>
      session({
        sessionId: (index + 100).toString(16).padStart(64, "0"),
        projectId: (index + 200).toString(16).padStart(64, "0"),
        projectName: `Fictional Project ${index + 1}`,
        sessionName: `Synthetic Session ${index + 1}`,
        startedAt: `2040-01-${String((index % 26) + 1).padStart(2, "0")}T09:00:00Z`,
      }),
    );
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn(async () => ({
        sessions: manySessions,
        limit: 100,
        offset: 0,
      })),
    };
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Fictional Project 1");
    const checkboxes = screen.getAllByRole("checkbox");
    checkboxes.slice(0, 25).forEach((checkbox) => fireEvent.click(checkbox));

    expect(screen.getByText("Selection limit reached")).toBeVisible();
    expect(checkboxes[25]).toBeDisabled();
    expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(25);
  });

  it("renders the maximum admitted project catalog on fixed pages", async () => {
    const manySessions = Array.from({ length: 100 }, (_, index) => session({
      sessionId: (index + 1000).toString(16).padStart(64, "0"),
      projectId: (index + 2000).toString(16).padStart(64, "0"),
      projectName: `Bounded Project ${index.toString().padStart(3, "0")}`,
      sessionName: `Bounded Session ${index.toString().padStart(3, "0")}`,
      startedAt: new Date(Date.parse("2040-01-01T00:00:00Z") + index * 1000).toISOString(),
    }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn(async () => ({ sessions: manySessions, limit: 100, offset: 0 })),
    };
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);

    expect(await screen.findByText("Showing 1–30 of 100")).toBeVisible();
    expect(document.querySelectorAll(".project-catalog-card")).toHaveLength(30);
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing 31–60 of 100")).toBeVisible();
    expect(screen.queryByText("Bounded Project 099")).not.toBeInTheDocument();
    expect(screen.getByText("Bounded Project 069")).toBeVisible();
  });

  it("keeps hidden selections explicit when the catalog is filtered", async () => {
    const { transport } = transportWithSessions();
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);
    await screen.findByText("Example Observatory");
    fireEvent.click(screen.getByRole("checkbox", {
      name: "Select Example Observatory for combined profile",
    }));

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "sample workflow" },
    });

    expect(screen.queryByText("Example Observatory")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 hidden by the current filter",
    );
    expect(screen.getByRole("button", { name: "Combine selected" })).toBeEnabled();
  });

  it("freezes the reviewed selection while the local aggregate is in flight", async () => {
    const { transport } = transportWithSessions();
    let resolveAggregate: (() => void) | undefined;
    transport.aggregateProjectQuality = vi.fn(
      () => new Promise<never>((resolve) => {
        resolveAggregate = () => resolve(undefined as never);
      }),
    );
    const { unmount } = render(
      <ProjectCatalog navigate={vi.fn()} transport={transport} />,
    );
    await screen.findByText("Example Observatory");
    const first = screen.getByRole("checkbox", {
      name: "Select Example Observatory for combined profile",
    });
    const second = screen.getByRole("checkbox", {
      name: "Select Sample Workshop for combined profile",
    });
    fireEvent.click(first);
    fireEvent.click(screen.getByRole("button", { name: "Combine selected" }));

    expect(first).toBeDisabled();
    expect(second).toBeDisabled();
    expect(screen.getByRole("button", { name: "Combining locally..." })).toBeDisabled();
    expect(screen.getByRole("complementary", {
      name: "Project aggregate selection",
    })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Combining selected projects locally",
    );
    fireEvent.click(second);
    expect(second).not.toBeChecked();

    unmount();
    resolveAggregate?.();
  });

  it.each([
    ["additive fields", { ...sessions[0], private_label: "PRIVATE-CATALOG-CANARY" }],
    ["non-RFC3339 dates", { ...sessions[0], started_at: "January 1, 2040" }],
    ["calendar-impossible dates", { ...sessions[0], started_at: "2040-02-31T09:00:00Z" }],
  ])("fails closed on catalog rows with %s", async (_case, malformed) => {
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn(async () => ({
        sessions: [malformed],
        limit: 100,
        offset: 0,
      })) as never,
    };
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);

    expect(
      await screen.findByText("The locally indexed project catalog response was invalid."),
    ).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-CATALOG-CANARY");
  });

  it("rejects catalog responses above the declared 100-session boundary", async () => {
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn(async () => ({
        sessions: Array.from({ length: 101 }, (_, index) => ({
          ...sessions[0],
          session_id: (index + 500).toString(16).padStart(64, "0"),
        })),
        limit: 100,
        offset: 0,
      })),
    };
    render(<ProjectCatalog navigate={vi.fn()} transport={transport} />);

    expect(
      await screen.findByText("The locally indexed project catalog response was invalid."),
    ).toBeVisible();
  });

  it("aborts the safe index request when the view is left", async () => {
    let requestSignal: AbortSignal | undefined;
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions: vi.fn((_limit, _offset, signal) => {
        requestSignal = signal;
        return new Promise<never>(() => undefined);
      }),
    };
    const { unmount } = render(
      <ProjectCatalog navigate={vi.fn()} transport={transport} />,
    );
    await waitFor(() => expect(requestSignal).toBeDefined());
    unmount();
    expect(requestSignal?.aborted).toBe(true);
  });

  it("aborts an in-flight aggregate when the catalog is left", async () => {
    const { transport } = transportWithSessions();
    let comparisonSignal: AbortSignal | undefined;
    transport.aggregateProjectQuality = vi.fn((_request, signal) => {
      comparisonSignal = signal;
      return new Promise<never>(() => undefined);
    });
    const { unmount } = render(
      <ProjectCatalog navigate={vi.fn()} transport={transport} />,
    );
    await screen.findByText("Example Observatory");
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select Example Observatory for combined profile",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Combine selected" }));
    await waitFor(() => expect(comparisonSignal).toBeInstanceOf(AbortSignal));

    unmount();
    expect(comparisonSignal?.aborted).toBe(true);
  });
});
