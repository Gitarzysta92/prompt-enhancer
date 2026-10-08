import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AgentChangeDiff,
  AgentChangedFile,
  AgentChangeRestoreApplyResult,
  AgentChangeRestorePreview,
  AgentChangeSet,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentChangeSetPanel } from "./AgentChangeSetPanel";

const SESSION = "a".repeat(32);

function changedFile(overrides: Partial<AgentChangedFile> = {}): AgentChangedFile {
  return {
    path: "src/example.ts",
    net_effect: "modified",
    verification: "verified",
    reason: null,
    reviewed_writes: 2,
    agent_writes: 1,
    manual_writes: 1,
    current_byte_size: 20,
    diff_available: true,
    ...overrides,
  };
}

function changeSet(overrides: Partial<AgentChangeSet> = {}): AgentChangeSet {
  return {
    contract_version: "agent-change-set.v1",
    session_id: SESSION,
    scope: "reviewed_paths_only",
    coverage: "complete",
    settled: true,
    reviewed_writes: 2,
    verified_writes: 2,
    unverified_writes: 0,
    agent_writes: 1,
    manual_writes: 1,
    reviewed_noops: 0,
    command_attempts: 0,
    omitted_write_receipts: 0,
    tracking_failed: false,
    files: [changedFile()],
    ...overrides,
  };
}

function changeDiff(overrides: Partial<AgentChangeDiff> = {}): AgentChangeDiff {
  return {
    contract_version: "agent-change-set.v1",
    session_id: SESSION,
    summary: changedFile(),
    diff_state: "available",
    diff: "--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-old\n+new",
    added_lines: 1,
    removed_lines: 1,
    ...overrides,
  };
}

function restorePreview(overrides: Partial<AgentChangeRestorePreview> = {}): AgentChangeRestorePreview {
  return {
    contract_version: "agent-change-restore.v1",
    session_id: SESSION,
    preview_id: "d".repeat(32),
    path: "src/example.ts",
    operation: "edit",
    baseline_state: "present",
    expected_revision: "b".repeat(64),
    restored_revision: "c".repeat(64),
    restored_byte_size: 12,
    line_ending: "lf",
    diff_state: "available",
    diff: "--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-current\n+baseline",
    added_lines: 1,
    removed_lines: 1,
    recovery: "revision_bound_write",
    permanent: false,
    expires_at: "2030-01-02T03:04:05Z",
    requires_native_confirmation: true,
    ...overrides,
  };
}

function restoreResult(overrides: Partial<AgentChangeRestoreApplyResult> = {}): AgentChangeRestoreApplyResult {
  return {
    contract_version: "agent-change-restore.v1",
    session_id: SESSION,
    path: "src/example.ts",
    operation: "edit",
    baseline_state: "present",
    current_revision: "c".repeat(64),
    current_byte_size: 12,
    recovery: "revision_bound_write",
    permanent: false,
    net_effect: "reverted",
    filesystem_verification: "verified",
    change_set_verification: "verified",
    change_set_reason: null,
    applied: true,
    ...overrides,
  };
}

describe("AgentChangeSetPanel", () => {
  it("previews, confirms, and reports an objectively verified exact baseline restore", async () => {
    const preview = restorePreview();
    const result = restoreResult();
    const onRestored = vi.fn();
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn(),
      previewAgentChangeRestore: vi.fn().mockResolvedValue(preview),
      applyAgentChangeRestore: vi.fn().mockResolvedValue(result),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      onRestored={onRestored}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);

    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Restore baseline" }));
    const recovery = await screen.findByRole("region", { name: "Baseline restore review" });
    expect(recovery).toHaveTextContent("Restore the retained file bytes");
    expect(screen.getByRole("figure", { name: "Baseline restore diff for src/example.ts" })).toHaveTextContent("+baseline");
    expect(transport.previewAgentChangeRestore).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      { path: "src/example.ts" },
      expect.any(AbortSignal),
    );

    fireEvent.click(screen.getByRole("button", { name: "Apply baseline restore" }));
    expect(await screen.findByText("Baseline restored and verified on disk.")).toBeVisible();
    expect(transport.applyAgentChangeRestore).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      preview.preview_id,
      {
        path: preview.path,
        operation: preview.operation,
        expected_revision: preview.expected_revision,
        restored_revision: preview.restored_revision,
        confirmation: "apply_reviewed_change_restore",
      },
      expect.any(AbortSignal),
    );
    expect(onRestored).toHaveBeenCalledExactlyOnceWith(result);
  });

  it("keeps restore application unavailable when native confirmation is absent", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn(),
      previewAgentChangeRestore: vi.fn().mockResolvedValue(restorePreview()),
      applyAgentChangeRestore: vi.fn(),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
      userPresenceAvailable={false}
    />);
    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Restore baseline" }));
    expect(await screen.findByText(/Native confirmation is unavailable/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply baseline restore" })).toBeDisabled();
    expect(transport.applyAgentChangeRestore).not.toHaveBeenCalled();
  });

  it("turns a stale apply into an explicit fresh-preview recovery path", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn(),
      previewAgentChangeRestore: vi.fn().mockResolvedValue(restorePreview()),
      applyAgentChangeRestore: vi.fn().mockRejectedValue(
        new TransportError("Local API request failed (409)", 409, "workspace_revision_changed"),
      ),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Restore baseline" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply baseline restore" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was claimed as restored");
    fireEvent.click(screen.getByRole("button", { name: "Create fresh preview" }));
    await waitFor(() => expect(transport.previewAgentChangeRestore).toHaveBeenCalledTimes(2));
  });

  it("opens an existing artifact or starts exact capture directly from its reviewed path", async () => {
    const onOpenArtifact = vi.fn();
    const onAddArtifact = vi.fn();
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn(),
    };
    const { rerender } = render(<AgentChangeSetPanel
      artifactPaths={new Set(["src/example.ts"])}
      fileActionsDisabled={false}
      onAddArtifact={onAddArtifact}
      onOpenArtifact={onOpenArtifact}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Open artifact" }));
    expect(onOpenArtifact).toHaveBeenCalledExactlyOnceWith("src/example.ts");

    rerender(<AgentChangeSetPanel
      artifactPaths={new Set()}
      fileActionsDisabled={false}
      onAddArtifact={onAddArtifact}
      onOpenArtifact={onOpenArtifact}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    fireEvent.click(screen.getByRole("button", { name: "Add as artifact" }));
    expect(onAddArtifact).toHaveBeenCalledExactlyOnceWith("src/example.ts");
  });
  it("opens and focuses the exact retained net diff requested by an artifact action", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
    };
    const request = { sessionId: SESSION, path: "src/example.ts", requestId: 9 };
    const { rerender } = render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      reviewRequest={request}
      sessionId={SESSION}
      transport={transport}
    />);

    const diff = await screen.findByRole("region", { name: "Net diff for src/example.ts" });
    expect(diff).toHaveTextContent("+new");
    await waitFor(() => expect(diff).toHaveFocus());
    expect(transport.getAgentChangeDiff).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      "src/example.ts",
      expect.any(AbortSignal),
    );

    rerender(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      reviewRequest={request}
      sessionId={SESSION}
      transport={transport}
    />);
    expect(transport.getAgentChangeDiff).toHaveBeenCalledTimes(1);
  });

  it("reports an artifact path with no bounded retained diff instead of reviewing another file", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      reviewRequest={{ sessionId: SESSION, path: "docs/missing.docx", requestId: 10 }}
      sessionId={SESSION}
      transport={transport}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "no retained net-diff entry",
    );
    expect(transport.getAgentChangeDiff).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: /Net diff/u })).not.toBeInTheDocument();
  });

  it("ignores an artifact diff request owned by another chat", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      reviewRequest={{ sessionId: "b".repeat(32), path: "src/example.ts", requestId: 11 }}
      sessionId={SESSION}
      transport={transport}
    />);
    expect(await screen.findByText("Modified")).toBeVisible();
    expect(transport.getAgentChangeDiff).not.toHaveBeenCalled();
  });

  it("shows current net effects and lazily loads an exact per-file diff", async () => {
    const openFile = vi.fn();
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      onOpenFile={openFile}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);

    expect(await screen.findByText("Complete reviewed-path coverage")).toBeVisible();
    expect(screen.getByText(/1 current change · 2 reviewed writes/u)).toBeVisible();
    expect(screen.getByText("Modified")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review net diff" }));
    const region = await screen.findByRole("region", { name: "Net diff for src/example.ts" });
    expect(screen.getByLabelText("Diff summary: 1 added line, 1 removed line, 1 hunk")).toBeVisible();
    expect(region).toHaveTextContent("+new");
    expect(transport.getAgentChangeDiff).toHaveBeenCalledWith("a".repeat(32), "src/example.ts", expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Open current file" }));
    expect(openFile).toHaveBeenCalledExactlyOnceWith("src/example.ts");
  });

  it("makes partial authority and uninventoried command effects prominent", async () => {
    const partialFile = changedFile({
      verification: "partial",
      reason: "current_revision_changed",
    });
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet({
        coverage: "partial",
        command_attempts: 1,
        files: [partialFile],
      })),
      getAgentChangeDiff: vi.fn(),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);

    expect(await screen.findByText("Partial reviewed-path coverage")).toBeVisible();
    expect(screen.getByText(/1 approved command attempt may have uninventoried file effects/u)).toBeVisible();
    expect(screen.getByText("Current file changed after the latest reviewed write")).toBeVisible();
    expect(screen.getByText(/1 path needs attention/u)).toBeVisible();
  });

  it("does not present an unsettled lifecycle snapshot as final", async () => {
    const transport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet({
        coverage: "partial",
        settled: false,
      })),
      getAgentChangeDiff: vi.fn(),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);

    expect(await screen.findByText("Partial reviewed-path coverage")).toBeVisible();
    expect(screen.getByText(
      "The session is active, closing, or its cleanup is unconfirmed; this inventory is not final.",
    )).toBeVisible();
  });

  it("does not let an old session response overwrite a replacement session", async () => {
    let resolveOld!: (value: AgentChangeSet) => void;
    const old = new Promise<AgentChangeSet>((resolve) => { resolveOld = resolve; });
    const nextSession = "b".repeat(32);
    const transport = {
      getAgentChangeSet: vi.fn()
        .mockReturnValueOnce(old)
        .mockResolvedValueOnce(changeSet({
          session_id: nextSession,
          reviewed_writes: 0,
          verified_writes: 0,
          agent_writes: 0,
          manual_writes: 0,
          files: [],
        })),
      getAgentChangeDiff: vi.fn(),
    };
    const { rerender } = render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    rerender(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={nextSession}
      transport={transport}
    />);
    expect(await screen.findByText("No reviewed file publication has entered this session change set.")).toBeVisible();
    resolveOld(changeSet());
    await Promise.resolve();
    expect(screen.queryByText("Modified")).not.toBeInTheDocument();
  });

  it("aborts an open diff when the active session changes", async () => {
    let resolveDiff!: (value: AgentChangeDiff) => void;
    const pendingDiff = new Promise<AgentChangeDiff>((resolve) => { resolveDiff = resolve; });
    const nextSession = "b".repeat(32);
    const transport = {
      getAgentChangeSet: vi.fn()
        .mockResolvedValueOnce(changeSet())
        .mockResolvedValueOnce(changeSet({
          session_id: nextSession,
          reviewed_writes: 0,
          verified_writes: 0,
          agent_writes: 0,
          manual_writes: 0,
          files: [],
        })),
      getAgentChangeDiff: vi.fn().mockReturnValue(pendingDiff),
    };
    const { rerender } = render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Review net diff" }));
    const signal = transport.getAgentChangeDiff.mock.calls[0][2] as AbortSignal;
    expect(signal.aborted).toBe(false);

    rerender(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={nextSession}
      transport={transport}
    />);
    expect(await screen.findByText("No reviewed file publication has entered this session change set.")).toBeVisible();
    expect(signal.aborted).toBe(true);
    resolveDiff(changeDiff());
    await Promise.resolve();
    expect(screen.queryByRole("region", { name: "Net diff for src/example.ts" })).not.toBeInTheDocument();
  });

  it("clears an open diff when the replacement transport cannot load change sets", async () => {
    const availableTransport = {
      getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
      getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
    };
    const { rerender } = render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={availableTransport}
    />);
    await screen.findByText("Modified");
    fireEvent.click(screen.getByRole("button", { name: "Review net diff" }));
    expect(await screen.findByRole("region", { name: "Net diff for src/example.ts" })).toBeVisible();

    rerender(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={{}}
    />);
    expect(screen.getByText("The current transport cannot load a reviewed change set.")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Net diff for src/example.ts" })).not.toBeInTheDocument();
    expect(screen.queryByText("Modified")).not.toBeInTheDocument();
  });

  it("drops stale data on refresh failure and recovers explicitly", async () => {
    const transport = {
      getAgentChangeSet: vi.fn()
        .mockRejectedValueOnce(new Error("synthetic failure"))
        .mockResolvedValueOnce(changeSet({
          reviewed_writes: 1,
          verified_writes: 1,
          agent_writes: 1,
          manual_writes: 0,
          reviewed_noops: 1,
          files: [],
        })),
      getAgentChangeDiff: vi.fn(),
    };
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No previous result is presented as current");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/1 reviewed no-op recorded/u)).toBeVisible();
    await waitFor(() => expect(transport.getAgentChangeSet).toHaveBeenCalledTimes(2));
  });

  it("disables file actions when the session connection is not authoritative", async () => {
    render(<AgentChangeSetPanel
      fileActionsDisabled
      onOpenFile={vi.fn()}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
        getAgentChangeDiff: vi.fn(),
      }}
    />);
    await screen.findByText("Modified");
    expect(screen.getByRole("button", { name: "Review net diff" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open current file" })).toBeDisabled();
  });

  it("keeps a missing path diff reviewable without offering a nonexistent current file", async () => {
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      onOpenFile={vi.fn()}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentChangeSet: vi.fn().mockResolvedValue(changeSet({
          coverage: "partial",
          files: [changedFile({
            net_effect: "reverted",
            verification: "partial",
            reason: "current_file_missing",
            current_byte_size: null,
          })],
        })),
        getAgentChangeDiff: vi.fn(),
      }}
    />);
    await screen.findByText("Back at session baseline");
    expect(screen.getByRole("button", { name: "Review net diff" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open current file" })).toBeDisabled();
  });

  it("makes recovery discoverable and inspects the exact current path from both detailed reviews", async () => {
    const openFile = vi.fn();
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      onOpenFile={openFile}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentChangeSet: vi.fn().mockResolvedValue(changeSet()),
        getAgentChangeDiff: vi.fn().mockResolvedValue(changeDiff()),
        previewAgentChangeRestore: vi.fn().mockResolvedValue(restorePreview()),
        applyAgentChangeRestore: vi.fn(),
      }}
    />);

    expect(await screen.findByText("Recovery review available · restore baseline")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review net diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect current file" }));
    expect(openFile).toHaveBeenLastCalledWith("src/example.ts");

    fireEvent.click(screen.getByRole("button", { name: "Close diff" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore baseline" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect current file" }));
    expect(openFile).toHaveBeenCalledTimes(2);
    expect(openFile).toHaveBeenLastCalledWith("src/example.ts");
  });

  it("explains why recovery is unavailable instead of offering a dead action", async () => {
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentChangeSet: vi.fn().mockResolvedValue(changeSet({
          coverage: "partial",
          files: [changedFile({
            verification: "unavailable",
            reason: "baseline_not_retained",
          })],
        })),
        getAgentChangeDiff: vi.fn(),
        previewAgentChangeRestore: vi.fn(),
        applyAgentChangeRestore: vi.fn(),
      }}
    />);

    expect(await screen.findByText("Recovery unavailable · baseline not retained")).toBeVisible();
    expect(screen.getByRole("button", { name: "Restore baseline" })).toBeDisabled();
  });

  it("names created-file recovery as a Recycle Bin action before preview", async () => {
    render(<AgentChangeSetPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentChangeSet: vi.fn().mockResolvedValue(changeSet({
          files: [changedFile({ net_effect: "created" })],
        })),
        getAgentChangeDiff: vi.fn(),
        previewAgentChangeRestore: vi.fn(),
        applyAgentChangeRestore: vi.fn(),
      }}
    />);

    expect(await screen.findByText("Recovery review available · Recycle Bin")).toBeVisible();
    expect(screen.getByRole("button", { name: "Review Recycle Bin recovery" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Restore baseline" })).not.toBeInTheDocument();
  });
});
