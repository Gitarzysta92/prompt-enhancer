import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  CodexIngestionReport,
  CodexLabelEnrichmentReport,
  CodexLocalSourceStatus,
  CodexSession,
  DisplayLabelEntityKind,
  PromptEnhancerTransport,
  SessionMetric,
  VerificationCapability,
} from "../../shared/api/contracts";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { LocalSources } from "./LocalSources";

const PROJECT_A = "a".repeat(64);
const PROJECT_B = "b".repeat(64);
const SESSION_A = "c".repeat(64);
const SESSION_B = "d".repeat(64);
const SESSION_C = "e".repeat(64);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

const VALIDATION_CAPABILITY: VerificationCapability = {
  state: "validation_only",
  live_classification_enabled: false,
  classifier_version: "local-command-rules-v1",
  normalizer_version: "strict-shell-free-v2",
  candidate_schema_version: "ephemeral-command-v1",
  supported_kinds: [
    "test",
    "build",
    "lint",
    "type_check",
    "security",
    "artifact_validation",
  ],
  reason_code: "provider_adapter_and_holdout_required",
};

const SESSIONS: CodexSession[] = [
  {
    session_id: SESSION_A,
    installation_id: "1".repeat(64),
    project_id: PROJECT_A,
    project_display_name: "Example Workspace",
    session_display_name: "Synthetic verification task",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider: "codex",
    provider_version: "synthetic-version",
    adapter_version: "synthetic-adapter-v1",
    source_schema_version: "synthetic-schema-v1",
    started_at: "2040-01-02T10:00:00Z",
    ended_at: "2040-01-02T10:05:00Z",
    terminal_state: "completed",
    events_complete: true,
  },
  {
    session_id: SESSION_B,
    installation_id: "1".repeat(64),
    project_id: PROJECT_A,
    project_display_name: "Example Workspace",
    session_display_name: null,
    project_display_name_origin: "provider",
    session_display_name_origin: "unknown",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider: "codex",
    provider_version: "synthetic-version",
    adapter_version: "synthetic-adapter-v1",
    source_schema_version: "synthetic-schema-v1",
    started_at: "2040-01-03T10:00:00Z",
    ended_at: null,
    terminal_state: null,
    events_complete: false,
  },
  {
    session_id: SESSION_C,
    installation_id: "1".repeat(64),
    project_id: PROJECT_B,
    project_display_name: null,
    session_display_name: "Synthetic metrics review",
    project_display_name_origin: "unknown",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider: "codex",
    provider_version: "synthetic-version",
    adapter_version: "synthetic-adapter-v1",
    source_schema_version: "synthetic-schema-v1",
    started_at: "2040-01-04T10:00:00Z",
    ended_at: "2040-01-04T10:05:00Z",
    terminal_state: "completed",
    events_complete: true,
  },
];

const REPORT: CodexIngestionReport = {
  provider: "codex",
  sessions_seen: 3,
  sessions_selected: 3,
  sessions_inserted: 3,
  sessions_updated: 0,
  events_seen: 6,
  events_inserted: 6,
  events_updated: 0,
  metrics_written: 3,
  truncated: false,
};

const LABEL_REPORT: CodexLabelEnrichmentReport = {
  provider: "codex",
  requested_sessions: 1,
  matched_sessions: 1,
  summary_reads: 1,
  project_labels_filled: 0,
  session_labels_filled: 1,
  labels_unavailable: 0,
  sessions_not_found: 0,
  truncated: false,
};

const METRIC: SessionMetric = {
  key: "session.efficiency.turn_count",
  version: 1,
  dimension: "efficiency",
  display_name: "Turn count",
  numeric_value: 4,
  text_value: null,
  unit: "turns",
  source: "deterministic",
  observed_count: 4,
  eligible_count: 4,
  coverage: 1,
  confidence: 1,
  metric_pack_key: "core.metadata.session",
  metric_pack_version: 3,
  metric_engine_version: "synthetic-engine-v1",
  redactor_version: null,
  model_id: null,
  model_revision: null,
  tokenizer_id: null,
  prompt_version: null,
  rubric_version: null,
  computed_at: "2040-01-04T10:06:00Z",
};

function createLocalTransport(
  consentActive: boolean,
  sessionRows: CodexSession[] = SESSIONS,
  metricRows: SessionMetric[] = [METRIC],
  verificationCapability: VerificationCapability = VALIDATION_CAPABILITY,
): {
  transport: PromptEnhancerTransport;
  index: ReturnType<typeof vi.fn>;
  analyze: ReturnType<typeof vi.fn>;
  metrics: ReturnType<typeof vi.fn>;
  enrich: ReturnType<typeof vi.fn>;
  setManual: ReturnType<typeof vi.fn>;
  clearManual: ReturnType<typeof vi.fn>;
} {
  let status: CodexLocalSourceStatus = {
    consent_active: consentActive,
    indexed_sessions: sessionRows.length,
    indexed_projects: new Set(sessionRows.map((session) => session.project_id)).size,
    verification_capability: verificationCapability,
  };
  const index = vi.fn(async () => REPORT);
  const analyze = vi.fn(async () => REPORT);
  const metrics = vi.fn(async (sessionId: string) => ({
    session_id: sessionId,
    metrics: metricRows,
  }));
  const enrich = vi.fn(async () => LABEL_REPORT);
  const setManual = vi.fn(
    async (entityKind: DisplayLabelEntityKind, entityId: string) => ({
      entity_kind: entityKind,
      entity_id: entityId,
      revision: 1,
      changed: true,
    }),
  );
  const clearManual = vi.fn(
    async (entityKind: DisplayLabelEntityKind, entityId: string) => ({
      entity_kind: entityKind,
      entity_id: entityId,
      revision: 2,
      changed: true,
    }),
  );
  const transport: PromptEnhancerTransport = {
    ...createSyntheticTransport(),
    getCodexLocalSourceStatus: vi.fn(async () => status),
    grantCodexLocalHistoryConsent: vi.fn(async () => {
      status = { ...status, consent_active: true };
      return status;
    }),
    revokeCodexLocalHistoryConsent: vi.fn(async () => {
      status = { ...status, consent_active: false };
      return status;
    }),
    indexCodexLocalSessions: index,
    analyzeCodexLocalSessions: analyze,
    enrichCodexDisplayLabels: enrich,
    setManualDisplayLabel: setManual,
    clearManualDisplayLabel: clearManual,
    listCodexSessions: vi.fn(async (limit = 100, offset = 0) => ({
      sessions: sessionRows,
      limit,
      offset,
    })),
    getSessionMetrics: metrics,
  };
  return {
    transport,
    index,
    analyze,
    metrics,
    enrich,
    setManual,
    clearManual,
  };
}

function renderLocalSources(transport: PromptEnhancerTransport) {
  const navigate = vi.fn();
  const rendered = render(
    <LocalSources navigate={navigate} transport={transport} />,
  );
  return { ...rendered, navigate };
}

async function openAdvancedMaintenance() {
  const label = await screen.findByText("Advanced source maintenance");
  fireEvent.click(label.closest("summary")!);
  for (const title of screen.getAllByText(/^Sessions \(/)) {
    fireEvent.click(title.closest("summary")!);
  }
}

async function openAdvancedMaintenanceWithoutSessions() {
  const label = await screen.findByText("Advanced source maintenance");
  fireEvent.click(label.closest("summary")!);
}

describe("LocalSources", () => {
  it.each(["save", "clear", "enrich"] as const)("keeps the acknowledged %s receipt when the follow-up metadata read fails", async (kind) => {
    const rows = SESSIONS.map((session) => session.session_id === SESSION_B
      ? { ...session, session_display_name_origin: "manual" as const, session_manual_label_revision: 7 }
      : session);
    const { transport, setManual, clearManual, enrich } = createLocalTransport(true, rows);
    renderLocalSources(transport);
    await openAdvancedMaintenance();
    vi.mocked(transport.listCodexSessions).mockRejectedValueOnce(new Error("synthetic read failure"));
    if (kind === "enrich") {
      fireEvent.click(screen.getByRole("checkbox", { name: /Unnamed session/ }));
      fireEvent.click(screen.getByRole("button", { name: "Find missing labels" }));
    } else {
      fireEvent.click(screen.getAllByRole("button", { name: "Edit local session label" })[1]);
      if (kind === "save") fireEvent.change(screen.getByLabelText("Local display label"), { target: { value: "Example revised label" } });
      fireEvent.click(screen.getByRole("button", { name: kind === "save" ? "Save locally" : "Clear override" }));
    }
    const command = kind === "save" ? setManual : kind === "clear" ? clearManual : enrich;
    await screen.findByRole("button", { name: "Reload source metadata" });
    expect(screen.getByRole("alert")).toHaveTextContent("label change was acknowledged");
    expect(screen.queryByRole("textbox", { name: "Local display label" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Edit local session label" })[1]).toBeDisabled();
    expect(command).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Reload source metadata" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(command).toHaveBeenCalledOnce();
    expect(screen.getAllByRole("button", { name: "Edit local session label" })[1]).toBeEnabled();
    expect(screen.getByText(kind === "save" ? /label saved/ : kind === "clear" ? /label cleared/ : /missing label imported/)).toBeVisible();
  });

  it("offers an in-place retry after the initial overview request fails", async () => {
    const { transport } = createLocalTransport(false);
    vi.mocked(transport.getCodexLocalSourceStatus)
      .mockRejectedValueOnce(new Error("synthetic loopback interruption"));
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);

    renderLocalSources(transport);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Data sources" })).toBeVisible();
    expect(transport.getCodexLocalSourceStatus).toHaveBeenCalledTimes(2);
    expect(errorLog).not.toHaveBeenCalled();
    errorLog.mockRestore();
  });

  it("aborts and ignores an older overview after the transport changes", async () => {
    const stale = createLocalTransport(false);
    const staleStatus = await stale.transport.getCodexLocalSourceStatus();
    const stalePage = await stale.transport.listCodexSessions(100, 0);
    const pendingStatus = deferred<CodexLocalSourceStatus>();
    const pendingPage = deferred<typeof stalePage>();
    let statusSignal: AbortSignal | undefined;
    let pageSignal: AbortSignal | undefined;
    stale.transport.getCodexLocalSourceStatus = vi.fn((signal?: AbortSignal) => {
      statusSignal = signal;
      return pendingStatus.promise;
    });
    stale.transport.listCodexSessions = vi.fn((_limit = 100, _offset = 0, signal?: AbortSignal) => {
      pageSignal = signal;
      return pendingPage.promise;
    });
    const view = renderLocalSources(stale.transport);
    await waitFor(() => expect(stale.transport.listCodexSessions).toHaveBeenCalledTimes(1));

    const fresh = createLocalTransport(true);
    view.rerender(<LocalSources navigate={view.navigate} transport={fresh.transport} />);
    expect(await screen.findByText("Access granted")).toBeVisible();
    expect(statusSignal?.aborted).toBe(true);
    expect(pageSignal?.aborted).toBe(true);

    await act(async () => {
      pendingStatus.resolve(staleStatus);
      pendingPage.resolve(stalePage);
      await Promise.all([pendingStatus.promise, pendingPage.promise]);
    });
    expect(screen.getByText("Access granted")).toBeVisible();
    expect(screen.queryByText("Consent required")).toBeNull();
  });

  it("shows explicit consent state and groups only safe session metadata", async () => {
    const { transport } = createLocalTransport(false);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    expect(await screen.findByRole("heading", { name: "Codex local history" })).toBeVisible();
    expect(screen.getByText("Consent required")).toBeVisible();
    expect(screen.getByText("Example Workspace")).toBeVisible();
    expect(screen.getByText("Synthetic verification task")).toBeVisible();
    expect(screen.getByText("Unnamed project")).toBeVisible();
    expect(screen.getByText("Unnamed session")).toBeVisible();
    expect(screen.getAllByText("Codex label")).toHaveLength(3);
    expect(screen.getAllByText("Missing label")).toHaveLength(2);
    expect(screen.getAllByRole("checkbox")).toHaveLength(5);
    expect(screen.getByText(/Full paths, previews, prompts/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Objective verification evidence" })).toBeVisible();
    expect(screen.getByText("Calibration required")).toBeVisible();
    expect(screen.getByText(/Live Codex command inspection is disabled/i)).toBeVisible();
    expect(screen.getByText(/version-gated provider adapter/i)).toBeVisible();
  });

  it("requires an explicit grant before a bounded index", async () => {
    const { transport, index } = createLocalTransport(false);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    const indexButton = await screen.findByRole("button", {
      name: "Refresh content-discarding index",
    });
    expect(indexButton).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Maximum index sessions" })).toHaveValue("100");
    expect(
      screen.getByRole("combobox", { name: "Maximum analysis sessions" }),
    ).toHaveValue("10");
    const analyze = screen.getByRole("button", { name: "Import operational metrics" });
    const labels = screen.getByRole("button", { name: "Find missing labels" });
    expect(analyze).toBeDisabled();
    expect(analyze).toHaveAccessibleDescription(/grant local-history access/i);
    expect(labels).toBeDisabled();
    expect(labels).toHaveAccessibleDescription(/grant local-history access/i);

    fireEvent.click(
      screen.getByRole("button", { name: "Grant local-history access" }),
    );
    expect(await screen.findByText("Access granted")).toBeVisible();
    expect(analyze).toBeDisabled();
    expect(analyze).toHaveAccessibleDescription(/select at least one project or session/i);
    expect(labels).toBeDisabled();
    expect(labels).toHaveAccessibleDescription(/select at least one project or session/i);
    fireEvent.click(screen.getByRole("checkbox", { name: /Example Workspace/ }));
    expect(analyze).toBeEnabled();
    expect(analyze).not.toHaveAttribute("aria-describedby");
    expect(labels).toBeEnabled();
    expect(labels).not.toHaveAttribute("aria-describedby");
    fireEvent.click(indexButton);

    await waitFor(() => expect(index).toHaveBeenCalledWith(100));
    expect(await screen.findByText("3 sessions indexed.")).toBeVisible();
  });

  it("renders supported and unavailable verification capability states truthfully", async () => {
    const supported = createLocalTransport(true, SESSIONS, [METRIC], {
      ...VALIDATION_CAPABILITY,
      state: "supported",
      live_classification_enabled: true,
      reason_code: "private_holdout_passed",
    });
    const { unmount } = renderLocalSources(supported.transport);

    expect(await screen.findByText("Locally enabled")).toBeVisible();
    expect(screen.getByText(/Only categorical, versioned evidence/i)).toBeVisible();
    unmount();

    const unavailable = createLocalTransport(true, SESSIONS, [METRIC], {
      state: "unsupported",
      live_classification_enabled: false,
      classifier_version: null,
      normalizer_version: null,
      candidate_schema_version: null,
      supported_kinds: [],
      reason_code: "provider_not_supported",
    });
    renderLocalSources(unavailable.transport);

    expect(await screen.findByText("Unavailable", { selector: ".status-pill" })).toBeVisible();
    expect(
      screen.getByText(/This provider cannot currently supply validated objective verification evidence/i),
    ).toBeVisible();
  });

  it("analyzes a bounded project selection and opens one session workspace", async () => {
    const { transport, analyze, metrics } = createLocalTransport(true);
    const { navigate } = renderLocalSources(transport);
    await openAdvancedMaintenance();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Example Workspace/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Import operational metrics" }),
    );

    await waitFor(() =>
      expect(analyze).toHaveBeenCalledWith({
        project_ids: [PROJECT_A],
        session_ids: [],
        max_sessions: 10,
      }),
    );
    expect(metrics).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId: PROJECT_A,
      sessionId: SESSION_A,
      category: "execution",
    });
  });

  it("uses an explicit bounded selection to find missing labels", async () => {
    const { transport, enrich } = createLocalTransport(true);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Unnamed session/ }),
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Maximum label summary reads" }),
      { target: { value: "5" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Find missing labels" }),
    );

    await waitFor(() =>
      expect(enrich).toHaveBeenCalledWith({
        project_ids: [],
        session_ids: [SESSION_B],
        max_sessions: 5,
      }),
    );
    expect(
      await screen.findByText(/1 missing label imported from 1 summary read/i),
    ).toBeVisible();
  });

  it("stores a manual session label locally without renaming Codex", async () => {
    const { transport, setManual } = createLocalTransport(true);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    const editButtons = await screen.findAllByRole("button", {
      name: "Edit local session label",
    });
    fireEvent.click(editButtons[1]);
    fireEvent.change(screen.getByRole("textbox", { name: "Local display label" }), {
      target: { value: "Local review label" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save locally" }));

    await waitFor(() =>
      expect(setManual).toHaveBeenCalledWith(
        "session",
        SESSION_B,
        "Local review label",
        0,
      ),
    );
    expect(
      await screen.findByText(/The Codex task was not renamed/i),
    ).toBeVisible();
  });

  it("clears only the local manual override by revision", async () => {
    const rows = SESSIONS.map((session) =>
      session.session_id === SESSION_B
        ? {
            ...session,
            session_display_name: "Local review label",
            session_display_name_origin: "manual" as const,
            session_manual_label_revision: 7,
          }
        : session,
    );
    const { transport, clearManual } = createLocalTransport(true, rows);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    const editButtons = await screen.findAllByRole("button", {
      name: "Edit local session label",
    });
    fireEvent.click(editButtons[1]);
    fireEvent.click(screen.getByRole("button", { name: "Clear override" }));

    await waitFor(() =>
      expect(clearManual).toHaveBeenCalledWith("session", SESSION_B, 7),
    );
    expect(
      await screen.findByText(/Any available Codex label is visible again/i),
    ).toBeVisible();
  });

  it("keeps duplicate display names separate through full pseudonymous IDs", async () => {
    const duplicateRows: CodexSession[] = [
      {
        ...SESSIONS[0],
        project_display_name: "Shared Workspace",
        session_display_name: "Shared Task",
      },
      {
        ...SESSIONS[2],
        project_display_name: "Shared Workspace",
        session_display_name: "Shared Task",
      },
    ];

    const { transport, analyze } = createLocalTransport(true, duplicateRows);
    renderLocalSources(transport);
    await openAdvancedMaintenance();

    const projectCheckboxes = await screen.findAllByRole("checkbox", {
      name: /Shared Workspace/,
    });
    expect(projectCheckboxes).toHaveLength(2);
    expect((projectCheckboxes[0] as HTMLInputElement).value).toBe(PROJECT_A);
    expect((projectCheckboxes[1] as HTMLInputElement).value).toBe(PROJECT_B);
    expect(screen.getAllByRole("checkbox", { name: /Shared Task/ })).toHaveLength(2);

    fireEvent.click(projectCheckboxes[1]);
    fireEvent.click(screen.getByRole("button", { name: "Import operational metrics" }));

    await waitFor(() =>
      expect(analyze).toHaveBeenCalledWith({
        project_ids: [PROJECT_B],
        session_ids: [],
        max_sessions: 10,
      }),
    );
  });

  it("separates daily project browsing from advanced source maintenance", async () => {
    const { transport, metrics } = createLocalTransport(true);
    const { navigate } = renderLocalSources(transport);

    expect(await screen.findByRole("heading", { name: "Browse projects without losing context" })).toBeVisible();
    const sourceSummary = screen.getByLabelText("Indexed source summary");
    expect(within(sourceSummary).getByText("2")).toBeVisible();
    expect(within(sourceSummary).getByText("3")).toBeVisible();
    expect(screen.getByText("Advanced source maintenance")).toBeVisible();
    expect(screen.getByText("Example Workspace")).not.toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Open project workspace" }));
    expect(navigate).toHaveBeenCalledWith({ name: "projects" });
    expect(metrics).not.toHaveBeenCalled();
  });

  it("opens an exact session metric route without an inline metric read", async () => {
    const { transport, metrics } = createLocalTransport(true);
    const { navigate } = renderLocalSources(transport);
    await openAdvancedMaintenance();

    const metricButtons = await screen.findAllByRole("button", { name: "Open metrics" });
    fireEvent.click(metricButtons[1]);

    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId: PROJECT_A,
      sessionId: SESSION_B,
      category: "execution",
    });
    expect(metrics).not.toHaveBeenCalled();
  });

  it("bounds a large single project and preserves a page-two session selection", async () => {
    const largeRows = Array.from({ length: 45 }, (_, index) => ({
      ...SESSIONS[0],
      session_id: String(index).padStart(64, "0"),
      session_display_name: `Synthetic session ${index}`,
    }));
    const { transport, analyze } = createLocalTransport(true, largeRows);
    renderLocalSources(transport);
    await openAdvancedMaintenanceWithoutSessions();

    expect(screen.getByText("Sessions (45)")).toBeVisible();
    expect(screen.queryByText("Synthetic session 21")).toBeNull();
    fireEvent.click(screen.getByText("Sessions (45)").closest("summary")!);
    expect(await screen.findByText("Synthetic session 0")).toBeVisible();
    expect(screen.queryByText("Synthetic session 20")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Synthetic session 20/ }));
    fireEvent.click(screen.getByRole("button", { name: "Earlier" }));

    expect(screen.getByText(/1 selected on another page/)).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search loaded projects" }), {
      target: { value: "no matching project" },
    });
    expect(screen.getByText(/1 selected session outside the current project view/)).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search loaded projects" }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import operational metrics" }));

    await waitFor(() =>
      expect(analyze).toHaveBeenCalledWith({
        project_ids: [],
        session_ids: [largeRows[20].session_id],
        max_sessions: 10,
      }),
    );
  });

  it("pages many projects without broadening selection and provides a scope reset", async () => {
    const manyRows = Array.from({ length: 25 }, (_, index) => ({
      ...SESSIONS[0],
      project_id: String(index).padStart(64, "0"),
      session_id: `${String(index).padStart(63, "0")}a`,
      project_display_name: `Synthetic Project ${index}`,
      session_display_name: `Synthetic task ${index}`,
    }));
    const { transport, analyze } = createLocalTransport(true, manyRows);
    renderLocalSources(transport);
    await openAdvancedMaintenanceWithoutSessions();

    expect(screen.getAllByRole("checkbox")).toHaveLength(12);
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Projects in local source maintenance" })).getByRole("button", { name: "Later" }));
    expect(screen.getByText("Synthetic Project 12")).toBeVisible();
    expect(screen.queryByText("Synthetic Project 0")).toBeNull();
    expect(screen.getByText(/1 selected session outside the current project view/)).toBeVisible();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search loaded projects" }), {
      target: { value: "Synthetic Project 20" },
    });
    expect(screen.getByText("Synthetic Project 20")).toBeVisible();
    expect(screen.getByText(/1 selected session outside the current project view/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Import operational metrics" }));
    await waitFor(() =>
      expect(analyze).toHaveBeenCalledWith({
        project_ids: [manyRows[0].project_id],
        session_ids: [],
        max_sessions: 10,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText(/0 projects · 0 sessions selected/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Import operational metrics" })).toBeDisabled();
  });

  it("resets local search and pagination state when the transport owner changes", async () => {
    const rows = Array.from({ length: 14 }, (_, index) => ({
      ...SESSIONS[0],
      project_id: String(index).padStart(64, "0"),
      session_id: `${String(index).padStart(63, "0")}a`,
      project_display_name: `Transport project ${index}`,
      session_display_name: `Transport task ${index}`,
    }));
    const first = createLocalTransport(true, rows);
    const view = renderLocalSources(first.transport);
    await openAdvancedMaintenanceWithoutSessions();
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Projects in local source maintenance" })).getByRole("button", { name: "Later" }));

    const replacementRows = rows.map((row) => ({
      ...row,
      project_display_name: row.project_display_name?.replace("Transport", "Replacement"),
    }));
    const replacement = createLocalTransport(true, replacementRows);
    view.rerender(<LocalSources navigate={view.navigate} transport={replacement.transport} />);
    const search = await screen.findByRole("searchbox", { name: "Search loaded projects" });
    expect(search).toHaveValue("");
    fireEvent.click((await screen.findByText("Advanced source maintenance")).closest("summary")!);
    expect(screen.getByRole("checkbox", { name: /Replacement project 0/ })).toBeVisible();
    expect(screen.queryByText("Replacement project 13")).toBeNull();
    expect(screen.getByRole("button", { name: "Import operational metrics" })).toBeDisabled();
  });
});
