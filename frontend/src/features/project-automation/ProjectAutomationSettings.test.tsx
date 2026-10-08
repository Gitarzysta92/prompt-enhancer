import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AutomationGrantCreateRequest,
  AutomationGrantRecord,
  AutomationGrantScope,
  CodexLocalSourceStatus,
  CodexSession,
  PromptEnhancerTransport,
  SessionMetricReadinessReport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { SYNTHETIC_SESSION_METRIC_READINESS } from "../../shared/api/syntheticFixtures";
import { ProjectAutomationSettings } from "./ProjectAutomationSettings";

const projectId = "a".repeat(64);
const sessionId = "b".repeat(64);
const grantId = "c".repeat(64);

function session(): CodexSession {
  return {
    session_id: sessionId,
    installation_id: "d".repeat(64),
    project_id: projectId,
    project_display_name: "Example Automation Project",
    session_display_name: "Example indexed session",
    provider: "codex",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: "2040-01-03T09:00:00Z",
    ended_at: "2040-01-03T09:12:00Z",
    terminal_state: "completed",
    events_complete: true,
  };
}

function consent(active = true): CodexLocalSourceStatus {
  return {
    consent_active: active,
    indexed_sessions: 1,
    indexed_projects: 1,
    verification_capability: {
      state: "validation_only",
      live_classification_enabled: false,
      supported_kinds: [],
      reason_code: "local_validation_only",
      candidate_schema_version: null,
      classifier_version: null,
      normalizer_version: null,
    },
  };
}

function metricReadiness(
  selectedSessionId = sessionId,
): SessionMetricReadinessReport {
  const value = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS);
  value.session_id = selectedSessionId;
  value.provider = "codex";
  value.capability_report.provider = "codex";
  return value;
}

function grantScope(
  overrides: Partial<AutomationGrantScope> = {},
): AutomationGrantScope {
  return {
    provider: "codex",
    project_id: projectId,
    metric_keys: ["prompt.context_sufficiency"],
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

function grant(
  state: AutomationGrantRecord["state"] = "active",
  overrides: Partial<AutomationGrantRecord> = {},
): AutomationGrantRecord {
  return {
    grant_id: grantId,
    revision: 1,
    scope: grantScope(),
    state,
    created_at: "2040-01-01T09:00:00Z",
    renewed_at: "2040-01-01T09:00:00Z",
    expires_at: "2040-01-31T09:00:00Z",
    next_check_at: "2040-01-03T09:15:00Z",
    last_checked_at: null,
    revoked_at: state === "revoked" ? "2040-01-03T10:00:00Z" : null,
    last_error_code: null,
    ...overrides,
  };
}

function localTransport(initialGrants: AutomationGrantRecord[] = []) {
  const transport = createSyntheticTransport() as PromptEnhancerTransport;
  const listProjectSessions = vi.fn(async () => ({
    sessions: [session()],
    limit: 100,
    offset: 0,
    total: 1,
    has_more: false,
  }));
  const getCodexLocalSourceStatus = vi.fn(async () => consent());
  const getSessionMetricReadiness = vi.fn(async () => metricReadiness());
  const listAutomationGrants = vi.fn(async () => initialGrants);
  const createAutomationGrant = vi.fn(async (
    request: AutomationGrantCreateRequest,
    _signal?: AbortSignal,
  ) =>
    grant("active", {
      scope: {
        ...request,
        local_only: true,
        remote_requires_fresh_approval: true,
      },
    }),
  );
  const renewAutomationGrant = vi.fn(async (
    _requestedGrantId: string,
    scope: AutomationGrantScope,
  ) => grant("active", {
    revision: 2,
    scope,
    renewed_at: "2040-01-03T10:00:00Z",
    expires_at: "2040-02-02T10:00:00Z",
    next_check_at: "2040-01-03T10:00:00Z",
  }));
  const revokeAutomationGrant = vi.fn(async (
    _requestedGrantId: string,
    scope: AutomationGrantScope,
  ) => grant("revoked", {
    revision: 2,
    scope,
    revoked_at: "2040-01-03T10:00:00Z",
  }));
  const pollAutomationGrants = vi.fn(async () => ({
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
  }));
  Object.assign(transport, {
    listProjectSessions,
    getCodexLocalSourceStatus,
    getSessionMetricReadiness,
    listAutomationGrants,
    createAutomationGrant,
    renewAutomationGrant,
    revokeAutomationGrant,
    pollAutomationGrants,
  });
  return {
    transport,
    listProjectSessions,
    getCodexLocalSourceStatus,
    getSessionMetricReadiness,
    listAutomationGrants,
    createAutomationGrant,
    renewAutomationGrant,
    revokeAutomationGrant,
    pollAutomationGrants,
  };
}

function renderLocal(transport: PromptEnhancerTransport, navigate = vi.fn()) {
  return {
    navigate,
    ...render(
      <ProjectAutomationSettings
        navigate={navigate}
        projectId={projectId}
        runtimeMode="local_real"
        serviceState="available"
        transport={transport}
      />,
    ),
  };
}

async function chooseGrantScope() {
  fireEvent.click(await screen.findByRole("button", { name: "Select attemptable" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I authorize this local service/i }));
}

describe("ProjectAutomationSettings", () => {
  it.each(["codex", "claude_code"] as const)("names the actual %s source on the consent gate", async (provider) => {
    const local = localTransport();
    local.listProjectSessions.mockResolvedValue({ sessions: [{ ...session(), provider }], limit: 100, offset: 0, total: 1, has_more: false });
    const syntheticClaudeStatus = await createSyntheticTransport().getClaudeLocalSourceStatus();
    local.transport.getClaudeLocalSourceStatus = vi.fn(async () => ({ ...syntheticClaudeStatus, consent_active: true, indexed_sessions: 1, indexed_projects: 1 }));
    renderLocal(local.transport);
    await screen.findByText("Consent active");
    const label = provider === "claude_code" ? "Claude Code" : "Codex";
    expect(screen.getByText(`Redacted-content access for the local ${label} source`)).toBeVisible();
    if (provider === "claude_code") expect(local.getCodexLocalSourceStatus).not.toHaveBeenCalled();
    else expect(local.transport.getClaudeLocalSourceStatus).not.toHaveBeenCalled();
  });

  it("fails closed in synthetic demo without reading or creating standing consent", () => {
    const local = localTransport();
    render(
      <ProjectAutomationSettings
        navigate={vi.fn()}
        projectId={projectId}
        runtimeMode="synthetic_demo"
        serviceState="available"
        transport={local.transport}
      />,
    );

    expect(screen.getByText("Automation is not running")).toBeVisible();
    expect(screen.getByText(/does not create standing consent/i)).toBeVisible();
    expect(local.listProjectSessions).not.toHaveBeenCalled();
    expect(local.listAutomationGrants).not.toHaveBeenCalled();
  });

  it.each(["checking", "unavailable"] as const)(
    "does not query project automation while service health is %s",
    (serviceState) => {
      const local = localTransport();
      render(
        <ProjectAutomationSettings
          navigate={vi.fn()}
          projectId={projectId}
          runtimeMode="local_real"
          serviceState={serviceState}
          transport={local.transport}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        serviceState === "checking" ? /checking the local service/i : /service unavailable/i,
      );
      expect(local.listAutomationGrants).not.toHaveBeenCalled();
    },
  );

  it("creates an exact project grant only after metric selection and explicit authorization", async () => {
    const local = localTransport();
    renderLocal(local.transport);

    expect(await screen.findByText("Consent active")).toBeVisible();
    expect(screen.getByText("Project indexed")).toBeVisible();
    expect(screen.getByText("Readiness verified")).toBeVisible();
    expect(screen.getByText(/Remote execution is never unattended/i)).toBeVisible();
    expect(screen.getByText("Balanced")).toBeVisible();
    expect(screen.getByText("Every 15 minutes while the service runs")).toBeVisible();
    expect(screen.getByText("30 days, then renew explicitly")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "Newest sessions per check" })).toHaveValue(20);
    const create = screen.getByRole("button", { name: "Create 30-day local grant" });
    expect(create).toBeDisabled();

    await chooseGrantScope();
    expect(create).toBeEnabled();
    fireEvent.click(create);

    await waitFor(() => expect(local.createAutomationGrant).toHaveBeenCalledTimes(1));
    const request = local.createAutomationGrant.mock.calls[0][0];
    expect(request).toEqual({
      provider: "codex",
      project_id: projectId,
      metric_keys: [...request.metric_keys].sort(),
      newest_session_limit: 20,
      check_interval_seconds: 900,
      resource_policy: {
        route: "balanced",
        max_gpu_workers: 1,
        max_cpu_workers: 1,
        pause_on_battery: true,
        maximum_session_seconds: 1_800,
      },
    });
    expect(await screen.findByText(`Grant ${grantId.slice(0, 8)}…${grantId.slice(-6)}`)).toBeVisible();
    const receipt = screen.getByRole("article");
    expect(within(receipt).getByText(`${request.metric_keys.length} selected metrics`)).toBeVisible();
  });

  it("requires fresh authorization whenever the selected grant scope changes", async () => {
    const local = localTransport();
    renderLocal(local.transport);
    await chooseGrantScope();

    const authorization = screen.getByRole("checkbox", {
      name: /I authorize this local service/i,
    });
    const create = screen.getByRole("button", { name: "Create 30-day local grant" });
    expect(authorization).toBeChecked();
    expect(create).toBeEnabled();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Newest sessions per check" }), {
      target: { value: "21" },
    });
    expect(authorization).not.toBeChecked();
    expect(create).toBeDisabled();

    fireEvent.click(authorization);
    expect(create).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(authorization).not.toBeChecked();
    expect(create).toBeDisabled();
  });

  it("blocks activation when consent, project identity, or readiness is unavailable", async () => {
    const local = localTransport();
    local.getCodexLocalSourceStatus.mockResolvedValue(consent(false));
    const report = metricReadiness();
    report.metrics[0].state = "incompatible";
    report.metrics[0].reason_code = "provider_incompatible";
    local.getSessionMetricReadiness.mockResolvedValue(report);
    renderLocal(local.transport);

    expect(await screen.findByText("Consent required")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: report.metrics[0].display_name })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /I authorize this local service/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create 30-day local grant" })).toBeDisabled();
    expect(local.createAutomationGrant).not.toHaveBeenCalled();
  });

  it("fails closed on readiness identity drift", async () => {
    const local = localTransport();
    local.getSessionMetricReadiness.mockResolvedValue(metricReadiness("e".repeat(64)));
    renderLocal(local.transport);

    expect(await screen.findByText(/readiness did not match the exact project session/i)).toBeVisible();
    expect(screen.getByText("Readiness unavailable")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create 30-day local grant" })).toBeDisabled();
  });

  it("renews and revokes only after confirming the exact existing scope", async () => {
    const existing = grant();
    const local = localTransport([existing]);
    renderLocal(local.transport);
    expect(await screen.findByText(`Grant ${grantId.slice(0, 8)}…${grantId.slice(-6)}`)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Renew 30 days" }));
    const renewGroup = screen.getByRole("group", { name: "Confirm renew grant" });
    fireEvent.click(within(renewGroup).getByRole("button", { name: "Confirm renew" }));
    await waitFor(() => expect(local.renewAutomationGrant).toHaveBeenCalledWith(
      grantId,
      existing.scope,
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("Revision 2")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Revoke grant" }));
    const revokeGroup = screen.getByRole("group", { name: "Confirm revoke grant" });
    fireEvent.click(within(revokeGroup).getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(local.revokeAutomationGrant).toHaveBeenCalledWith(
      grantId,
      expect.objectContaining({ project_id: projectId, provider: "codex" }),
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("revoked")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revoke grant" })).not.toBeInTheDocument();
  });

  it("polls all due grants truthfully, refreshes receipts, and links to the Job Centre", async () => {
    const local = localTransport([grant()]);
    const navigate = vi.fn();
    renderLocal(local.transport, navigate);
    await screen.findByText(`Grant ${grantId.slice(0, 8)}…${grantId.slice(-6)}`);
    const link = screen.getByRole("link", { name: "Open Job Centre" });
    link.focus();
    expect(link).toHaveFocus();
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith({ name: "analysis_jobs" });

    fireEvent.click(screen.getByRole("button", { name: "Check due grants now" }));
    await waitFor(() => expect(local.pollAutomationGrants).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Scheduler receipt")).toBeVisible();
    expect(screen.getByText(/1 jobs created · 1 reused/i)).toBeVisible();
    expect(local.listAutomationGrants).toHaveBeenCalledTimes(2);
  });

  it("separates the enforced publication cutoff from blocking preemption", async () => {
    const local = localTransport([grant()]);
    local.pollAutomationGrants.mockResolvedValueOnce({
      grants_checked: 2,
      grants_revoked: 0,
      grants_power_paused: 1,
      grants_policy_unsupported: 1,
      power_external_observations: 0,
      power_battery_observations: 0,
      power_unknown_observations: 1,
      candidates_seen: 0,
      jobs_created: 0,
      jobs_reused: 0,
      jobs_superseded: 0,
      failures: 1,
      maximum_session_runtime_deadline_enforced: false,
      session_quality_result_publication_deadline_enforced: true,
      blocking_execution_preemption_enforced: false,
    });
    renderLocal(local.transport);
    await screen.findByRole("article");

    fireEvent.click(screen.getByRole("button", { name: "Check due grants now" }));

    expect(await screen.findByText(/1 power-paused · 1 unsupported profiles/i)).toBeVisible();
    expect(screen.getByText(/session-quality result publication cutoff: enforced/i)).toBeVisible();
    expect(screen.getByText(/blocking-call force-stop: not provided/i)).toBeVisible();
    expect(screen.getByText(/hard runtime deadline: not enforced/i)).toBeVisible();
  });

  it("suppresses raw command errors and refuses a mismatched create response", async () => {
    const local = localTransport();
    local.createAutomationGrant.mockRejectedValueOnce(
      new TransportError("PRIVATE-AUTOMATION-CANARY", 403, "automation_consent_required"),
    );
    renderLocal(local.transport);
    await chooseGrantScope();
    fireEvent.click(screen.getByRole("button", { name: "Create 30-day local grant" }));
    expect(await screen.findByText(/standing redacted-content consent is no longer active/i)).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-AUTOMATION-CANARY");

    local.createAutomationGrant.mockResolvedValueOnce(grant("active", {
      grant_id: "f".repeat(64),
      scope: grantScope({ project_id: "e".repeat(64) }),
    }));
    fireEvent.click(screen.getByRole("button", { name: "Create 30-day local grant" }));
    expect(await screen.findByText(/did not match this exact provider and project/i)).toBeVisible();
    expect(document.body.textContent).not.toContain("e".repeat(64));
  });

  it("aborts an in-flight command when the exact project identity changes", async () => {
    const local = localTransport();
    let resolveCreate!: (value: AutomationGrantRecord) => void;
    local.createAutomationGrant.mockImplementationOnce(() => new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    const view = renderLocal(local.transport);
    await chooseGrantScope();
    fireEvent.click(screen.getByRole("button", { name: "Create 30-day local grant" }));
    await waitFor(() => expect(local.createAutomationGrant).toHaveBeenCalledTimes(1));
    const signal = local.createAutomationGrant.mock.calls[0][1] as AbortSignal;

    const nextProjectId = "e".repeat(64);
    view.rerender(
      <ProjectAutomationSettings
        navigate={vi.fn()}
        projectId={nextProjectId}
        runtimeMode="local_real"
        serviceState="available"
        transport={local.transport}
      />,
    );
    expect(signal.aborted).toBe(true);
    resolveCreate(grant());

    await waitFor(() => expect(screen.queryByText(
      `Grant ${grantId.slice(0, 8)}…${grantId.slice(-6)}`,
    )).not.toBeInTheDocument());
  });

  it("shows the actual stored resource profile when it differs from new-grant defaults", async () => {
    const existing = grant("active", {
      scope: grantScope({
        check_interval_seconds: 1_800,
        resource_policy: {
          route: "deep",
          max_gpu_workers: 1,
          max_cpu_workers: 2,
          pause_on_battery: false,
          maximum_session_seconds: 3_600,
        },
      }),
    });
    renderLocal(localTransport([existing]).transport);

    const receipt = await screen.findByRole("article");
    expect(within(receipt).getByText("deep")).toBeVisible();
    expect(within(receipt).getByText("2")).toBeVisible();
    expect(within(receipt).getByText(/current reviewed session-quality use 0/i)).toBeVisible();
    expect(within(receipt).getByText(/historical continue policy \(unsupported\)/i)).toBeVisible();
    expect(within(receipt).getByText(/not executable or renewable/i)).toBeVisible();
    expect(within(receipt).getByRole("button", { name: "Renew 30 days" })).toBeDisabled();
  });

  it("hides unrecognized persisted error codes behind reviewed copy", async () => {
    const local = localTransport([grant("active", { last_error_code: "PRIVATE_ERROR_CANARY" })]);
    renderLocal(local.transport);
    expect(await screen.findByText(/unrecognized content-free failure code/i)).toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE_ERROR_CANARY");
  });
});
