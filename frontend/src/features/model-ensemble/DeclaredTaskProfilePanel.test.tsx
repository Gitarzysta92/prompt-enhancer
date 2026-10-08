import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  DeclaredTaskProfile,
  ModelEnsembleRun,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { DeclaredTaskProfilePanel } from "./DeclaredTaskProfilePanel";

const SESSION_ID = "a".repeat(64);
const OTHER_SESSION_ID = "e".repeat(64);
const RUN_ID = "f".repeat(64);

function profileFixture(revision = 2, sessionId = SESSION_ID): DeclaredTaskProfile {
  return {
    profile_id: "b".repeat(64),
    provider: "codex",
    session_id: sessionId,
    revision,
    previous_profile_id: revision === 1 ? null : "c".repeat(64),
    constraint_kinds: ["cost", "privacy"],
    expected_outcome_count: 3,
    deliverable_slots: ["artifact", "format"],
    profile_fingerprint: "d".repeat(64),
    confirmed_at: "2040-01-02T10:00:00Z",
    confirmation_authority: "authenticated_local_user",
    schema_version: "declared-task-profile-v1",
    policy_version: "authenticated-local-user-v1",
    local_only: true,
    content_persisted: false,
  };
}

function transportWith(methods: Partial<PromptEnhancerTransport>): PromptEnhancerTransport {
  return methods as PromptEnhancerTransport;
}

function bindingFixture(
  profile: DeclaredTaskProfile,
): NonNullable<ModelEnsembleRun["metric_profile_binding"]> {
  return {
    profile_source: "declared_task_profile",
    profile_id: profile.profile_id,
    profile_revision: profile.revision,
    profile_fingerprint: profile.profile_fingerprint,
    profile_schema_version: "declared-task-profile-v1",
    profile_policy_version: "authenticated-local-user-v1",
    local_only: true,
    content_persisted: false,
  };
}

function renderProfile(
  transport: PromptEnhancerTransport,
  sessionId = SESSION_ID,
  sealedRunId: string | null = RUN_ID,
  sealedMetricProfileBinding: ModelEnsembleRun["metric_profile_binding"] = null,
  sealedMetricProjectionVersion: NonNullable<ModelEnsembleRun["metric_publication_v2"]>["projection_version"] | null = null,
) {
  return render(
    <DeclaredTaskProfilePanel
      sealedMetricProfileBinding={sealedMetricProfileBinding}
      sealedMetricProjectionVersion={sealedMetricProjectionVersion}
      sealedRunContext="latest_head"
      sealedRunId={sealedRunId}
      sessionId={sessionId}
      transport={transport}
    />,
  );
}

describe("DeclaredTaskProfilePanel", () => {
  it("renders only closed controls and keeps every absent family unknown", async () => {
    const transport = transportWith({
      getDeclaredTaskProfile: vi.fn().mockResolvedValue({ session_id: SESSION_ID, profile: null, confirmation_available: true }),
      saveDeclaredTaskProfile: vi.fn(),
    });
    renderProfile(transport);

    expect(await screen.findByText(/denominators remain unknown/i)).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/not applicable/i)).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Constraint kinds" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Acceptance outcomes" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Deliverable slots" })).toBeVisible();

    fireEvent.click(screen.getByLabelText("Configure expected constraint kinds"));
    fireEvent.click(screen.getByRole("button", { name: "Review profile change" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/choose at least one constraint kind/i);
    expect(transport.saveDeclaredTaskProfile).not.toHaveBeenCalled();
  });

  it("requires a separate confirmation and saves sorted closed values against the exact revision", async () => {
    const current = profileFixture();
    const saved = {
      ...current,
      profile_id: "9".repeat(64),
      previous_profile_id: current.profile_id,
      revision: 3,
      constraint_kinds: ["cost", "privacy", "safety"] as const,
      expected_outcome_count: 4,
      deliverable_slots: ["artifact", "format", "location"] as const,
      profile_fingerprint: "8".repeat(64),
    };
    const save = vi.fn().mockResolvedValue({ profile: saved, applied: true });
    const transport = transportWith({
      getDeclaredTaskProfile: vi.fn().mockResolvedValue({ session_id: SESSION_ID, profile: current, confirmation_available: true }),
      saveDeclaredTaskProfile: save,
    });
    const view = renderProfile(transport);
    await screen.findByText("Revision 2");

    fireEvent.click(screen.getByLabelText("Safety"));
    fireEvent.change(screen.getByLabelText("Expected checkable outcomes"), { target: { value: "4" } });
    fireEvent.click(screen.getByLabelText("Location"));
    fireEvent.click(screen.getByRole("button", { name: "Review profile change" }));

    expect(save).not.toHaveBeenCalled();
    const confirmation = screen.getByRole("group", { name: "Confirm reviewed task profile" });
    expect(confirmation).toHaveTextContent(/exact current revision 2/i);
    fireEvent.click(within(confirmation).getByRole("button", { name: "Confirm reviewed profile" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith(
      SESSION_ID,
      {
        expected_revision: 2,
        constraint_kinds: ["cost", "privacy", "safety"],
        expected_outcome_count: 4,
        deliverable_slots: ["artifact", "format", "location"],
        confirmation: "save_reviewed_declared_task_profile",
      },
      expect.stringMatching(/^dashboard-declared-task-profile-/),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText(/latest sealed head ffffffff…ffff has no exact reviewed-profile binding/i)).toBeVisible();
    expect(screen.getByText(/current profile-bound seal/i)).toBeVisible();

    view.rerender(
      <DeclaredTaskProfilePanel
        sealedMetricProfileBinding={null}
        sealedMetricProjectionVersion="metric-contract-v2-projection-5"
        sealedRunContext="latest_head"
        sealedRunId={"7".repeat(64)}
        sessionId={SESSION_ID}
        transport={transport}
      />,
    );
    expect(screen.getByText(/does not exactly bind its source, schema, revision, and fingerprint/i)).toBeVisible();
    expect(screen.getByText(/metrics remain unverified/i)).toBeVisible();

    view.rerender(
      <DeclaredTaskProfilePanel
        sealedMetricProfileBinding={bindingFixture(saved)}
        sealedMetricProjectionVersion="metric-contract-v2-projection-5"
        sealedRunContext="latest_head"
        sealedRunId={"6".repeat(64)}
        sessionId={SESSION_ID}
        transport={transport}
      />,
    );
    expect(screen.getByText(/exactly bound to latest sealed head 66666666…6666/i)).toBeVisible();
    expect(screen.getByText(/metrics are verified current/i)).toBeVisible();
    expect(screen.getByText(/verified current/i)).toHaveAttribute(
      "data-profile-publication-status",
      "verified_current",
    );

    view.rerender(
      <DeclaredTaskProfilePanel
        sealedMetricProfileBinding={bindingFixture(saved)}
        sealedMetricProjectionVersion="metric-contract-v2-projection-6"
        sealedRunContext="latest_head"
        sealedRunId={"5".repeat(64)}
        sessionId={SESSION_ID}
        transport={transport}
      />,
    );
    expect(screen.getByText(/exactly bound to latest sealed head 55555555…5555/i)).toBeVisible();
    expect(screen.getByText(/metrics are verified current/i)).toHaveAttribute(
      "data-profile-publication-status",
      "verified_current",
    );
  });

  it("cancels a pending confirmation when the session changes and ignores the old load", async () => {
    let resolveOld: ((value: { session_id: string; profile: DeclaredTaskProfile | null; confirmation_available: boolean }) => void) | null = null;
    const oldLoad = new Promise<{ session_id: string; profile: DeclaredTaskProfile | null; confirmation_available: boolean }>((resolve) => {
      resolveOld = resolve;
    });
    const get = vi.fn((sessionId: string) => sessionId === SESSION_ID
      ? oldLoad
      : Promise.resolve({ session_id: OTHER_SESSION_ID, profile: profileFixture(1, OTHER_SESSION_ID), confirmation_available: true }));
    const transport = transportWith({ getDeclaredTaskProfile: get, saveDeclaredTaskProfile: vi.fn() });
    const view = renderProfile(transport);
    view.rerender(
      <DeclaredTaskProfilePanel
        sealedMetricProfileBinding={null}
        sealedMetricProjectionVersion={null}
        sealedRunContext="latest_head"
        sealedRunId={RUN_ID}
        sessionId={OTHER_SESSION_ID}
        transport={transport}
      />,
    );
    expect(await screen.findByText("Revision 1")).toBeVisible();
    resolveOld!({ session_id: SESSION_ID, profile: profileFixture(2), confirmation_available: true });
    await Promise.resolve();
    expect(screen.queryByText("Revision 2")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confirm reviewed task profile" })).not.toBeInTheDocument();
  });

  it("reloads a stale revision conflict without applying the rejected draft", async () => {
    const revision2 = profileFixture(2);
    const revision3 = { ...profileFixture(3), expected_outcome_count: 5 };
    const get = vi.fn()
      .mockResolvedValueOnce({ session_id: SESSION_ID, profile: revision2, confirmation_available: true })
      .mockResolvedValueOnce({ session_id: SESSION_ID, profile: revision3, confirmation_available: true });
    const conflict = Object.assign(new Error("conflict"), { status: 409 });
    const save = vi.fn().mockRejectedValue(conflict);
    const transport = transportWith({ getDeclaredTaskProfile: get, saveDeclaredTaskProfile: save });
    renderProfile(transport);
    await screen.findByText("Revision 2");

    fireEvent.change(screen.getByLabelText("Expected checkable outcomes"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Review profile change" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm reviewed profile" }));

    expect(await screen.findByText("Revision 3")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent(/newer profile revision was saved elsewhere/i);
    expect(screen.getByLabelText("Expected checkable outcomes")).toHaveValue(5);
    expect(get).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[0][1].expected_revision).toBe(2);
  });
});
