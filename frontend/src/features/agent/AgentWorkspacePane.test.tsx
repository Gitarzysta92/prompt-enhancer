import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import type {
  AgentArtifactCapturePreview,
  AgentArtifactDetail,
  AgentEvent,
  AgentWorkspaceFile,
  AgentWorkspaceTransactionApplyCommand,
  AgentWorkspaceTransactionApplyResult,
  AgentWorkspaceTransactionPreview,
  AgentWorkspaceTransactionPreviewCommand,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentWorkspacePane } from "./AgentWorkspacePane";

const SESSION = "a".repeat(32);
const PROJECT = "9".repeat(32);
const OTHER_SESSION = "e".repeat(32);
const BASE = "b".repeat(64);
const PROPOSED = "c".repeat(64);
const PREVIEW = "d".repeat(32);
const OTHER_BASE = "f".repeat(64);
const OTHER_PROPOSED = "1".repeat(64);
const TRANSACTION_PLAN = "2".repeat(32);
const CREATED_PROPOSED = "3".repeat(64);

function file(path = "example.ts", content = "export const value = 1;\n", revision = BASE): AgentWorkspaceFile {
  return {
    contract_version: "local-agent-workspace.v1",
    session_id: SESSION,
    path,
    content,
    revision,
    byte_size: content.length,
    line_ending: "lf",
    editable: true,
  };
}

function transport() {
  return {
    getAgentWorkspaceTree: vi.fn(async (sessionId: string, path: string) => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: sessionId,
      path,
      entries: [
        { path: "src", name: "src", kind: "directory" as const, byte_size: null, editable_candidate: false },
        { path: "example.ts", name: "example.ts", kind: "file" as const, byte_size: 24, editable_candidate: true },
        { path: "other.ts", name: "other.ts", kind: "file" as const, byte_size: 24, editable_candidate: true },
        { path: "large.log", name: "large.log", kind: "file" as const, byte_size: 300_000, editable_candidate: false },
        { path: "linked", name: "linked", kind: "unavailable" as const, byte_size: null, editable_candidate: false },
      ],
      complete: true,
    })),
    getAgentWorkspaceFile: vi.fn(async (_sessionId: string, path: string) => (
      path === "other.ts"
        ? file("other.ts", "export const other = 1;\n", OTHER_BASE)
        : path === "created.ts"
          ? file("created.ts", "export const created = true;\n", PROPOSED)
          : path === "archive/example.ts"
            ? file("archive/example.ts", "export const value = 1;\n", BASE)
            : file()
    )),
    previewAgentWorkspaceEdit: vi.fn(async () => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "example.ts",
      expected_revision: BASE,
      proposed_revision: PROPOSED,
      line_ending: "lf" as const,
      diff: "--- a/example.ts\n+++ b/example.ts\n@@ -1 +1 @@\n-1\n+2",
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceEdit: vi.fn(async () => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: SESSION,
      path: "example.ts",
      revision: PROPOSED,
      byte_size: 24,
      applied: true as const,
    })),
    previewAgentWorkspaceCreate: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "created.ts",
      proposed_revision: PROPOSED,
      line_ending: "lf" as const,
      byte_size: 29,
      diff: "--- /dev/null\n+++ b/created.ts\n@@ -0,0 +1 @@\n+export const created = true;",
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceCreate: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      path: "created.ts",
      revision: PROPOSED,
      byte_size: 29,
      operation: "created" as const,
      applied: true as const,
    })),
    previewAgentWorkspaceDirectoryCreate: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "reviewed-folder",
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceDirectoryCreate: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      path: "reviewed-folder",
      operation: "directory_created" as const,
      applied: true as const,
    })),
    previewAgentWorkspaceDirectoryMove: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "src",
      target_path: "archive/src",
      contents_reviewed: false as const,
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceDirectoryMove: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      source_path: "src",
      target_path: "archive/src",
      contents_reviewed: false as const,
      operation: "directory_moved" as const,
      applied: true as const,
    })),
    previewAgentWorkspaceMove: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "example.ts",
      target_path: "archive/example.ts",
      expected_revision: BASE,
      byte_size: 24,
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceMove: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      source_path: "example.ts",
      target_path: "archive/example.ts",
      revision: BASE,
      byte_size: 24,
      operation: "moved" as const,
      applied: true as const,
    })),
    previewAgentWorkspaceFileTrash: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "example.ts",
      expected_revision: BASE,
      byte_size: 24,
      recovery: "windows_recycle_bin" as const,
      permanent: false as const,
      expires_at: "2026-08-20T22:00:00Z",
    })),
    applyAgentWorkspaceFileTrash: vi.fn(async () => ({
      contract_version: "local-agent-workspace-lifecycle.v1" as const,
      session_id: SESSION,
      path: "example.ts",
      revision: BASE,
      byte_size: 24,
      recovery: "windows_recycle_bin" as const,
      permanent: false as const,
      operation: "trashed" as const,
      applied: true as const,
    })),
    previewAgentWorkspaceTransaction: vi.fn(async (
      sessionId: string,
      command: AgentWorkspaceTransactionPreviewCommand,
    ): Promise<AgentWorkspaceTransactionPreview> => {
      const changes = [...command.changes].sort((left, right) => left.path.localeCompare(right.path));
      const files = changes.map((change) => {
        const created = change.operation === "create";
        return {
          operation: change.operation,
          path: change.path,
          expected_revision: change.expected_revision ?? null,
          proposed_revision: created
            ? CREATED_PROPOSED
            : change.path === "example.ts"
              ? PROPOSED
              : OTHER_PROPOSED,
          proposed_byte_size: new TextEncoder().encode(
            change.line_ending === "crlf" ? change.content.replaceAll("\n", "\r\n") : change.content,
          ).byteLength,
          line_ending: change.line_ending,
          diff: created
            ? `--- a/${change.path}\n+++ b/${change.path}\n@@ -0,0 +1 @@\n+new`
            : `--- a/${change.path}\n+++ b/${change.path}\n@@ -1 +1 @@\n-old\n+new`,
          added_lines: 1,
          removed_lines: created ? 0 : 1,
        };
      });
      return {
        contract_version: "local-agent-workspace-transaction.v2",
        session_id: sessionId,
        plan_id: TRANSACTION_PLAN,
        file_count: files.length,
        total_byte_size: files.reduce((total, item) => total + item.proposed_byte_size, 0),
        added_lines: files.length,
        removed_lines: files.reduce((total, item) => total + item.removed_lines, 0),
        files,
        expires_at: "2099-08-20T22:00:00Z",
      };
    }),
    applyAgentWorkspaceTransaction: vi.fn(async (
      sessionId: string,
      preview: AgentWorkspaceTransactionPreview,
      _command: AgentWorkspaceTransactionApplyCommand,
    ): Promise<AgentWorkspaceTransactionApplyResult> => ({
      contract_version: "local-agent-workspace-transaction.v2",
      session_id: sessionId,
      plan_id: preview.plan_id,
      state: "committed",
      reason: null,
      file_count: preview.file_count,
      files: preview.files.map((item) => ({
        path: item.path,
        state: "committed" as const,
        revision: item.proposed_revision,
        byte_size: item.proposed_byte_size,
      })),
    })),
  };
}

async function stageTwoWorkspaceFiles(): Promise<void> {
  fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
  const editor = await screen.findByLabelText("Workspace file editor");
  await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
  fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
  await screen.findByRole("button", { name: "Open staged file example.ts" });

  fireEvent.click(screen.getByRole("button", { name: "other.ts" }));
  await waitFor(() => expect(editor).toHaveValue("export const other = 1;\n"));
  fireEvent.change(editor, { target: { value: "export const other = 2;\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
  await screen.findByRole("button", { name: "Review 2-file transaction" });
}

async function stageNewWorkspaceFile(
  path = "created.ts",
  content = "export const created = true;\n",
): Promise<void> {
  const start = screen.getByRole("button", { name: "New file" });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  const pathField = await screen.findByLabelText("Workspace-relative new file path");
  fireEvent.change(pathField, { target: { value: path } });
  fireEvent.change(screen.getByLabelText("New file content"), { target: { value: content } });
  fireEvent.click(screen.getByRole("button", { name: "Stage new file in transaction" }));
  await screen.findByRole("button", { name: `Edit staged new file ${path}` });
}

describe("workspace inspection truth", () => {
  it("keeps the coding workbench primary while retaining discovery and safety tools on demand", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    const summary = screen.getByText("Workspace tools & safety").closest("summary");
    const details = summary?.closest("details");
    expect(summary).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(await screen.findByRole("button", { name: "example.ts" })).toBeVisible();
    expect(screen.getByLabelText("Workspace file editor")).toBeVisible();
    expect(screen.getByRole("region", { name: "Workspace discovery" })).not.toBeVisible();

    fireEvent.click(summary!);
    expect(details).toHaveAttribute("open");
    expect(screen.getByRole("region", { name: "Workspace discovery" })).toBeVisible();
    expect(screen.getByText(/Permanent deletion and directory removal are not available/u)).toBeVisible();
  });

  it("opens non-editable generated files in the exact artifact-capture review", async () => {
    const capturePreview: AgentArtifactCapturePreview = {
      contract_version: "agent-artifact-capture-preview.v1",
      project_id: PROJECT,
      session_id: SESSION,
      path: "large.log",
      title: "large.log",
      kind: "text",
      media_type: "text/plain; charset=utf-8",
      preview_kind: "text",
      sha256: "8".repeat(64),
      byte_size: 300_000,
      requires_native_confirmation: true,
      file_content_included: false,
    };
    const artifact = { title: "large.log" } as AgentArtifactDetail;
    const api = {
      ...transport(),
      previewAgentArtifactCapture: vi.fn(async () => capturePreview),
      captureAgentArtifact: vi.fn(async () => artifact),
    };
    const captured = vi.fn();
    render(
      <AgentWorkspacePane
        onArtifactCaptured={captured}
        pendingWrite={null}
        projectId={PROJECT}
        sessionId={SESSION}
        transport={api}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /large\.log — add as generated output/u }));
    expect(screen.getByLabelText("Workspace-relative file path")).toHaveValue("large.log");
    fireEvent.click(screen.getByRole("button", { name: "Review output" }));
    await screen.findByRole("region", { name: "Generated output review" });
    expect(api.previewAgentArtifactCapture).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      { path: "large.log" },
      expect.any(AbortSignal),
    );

    fireEvent.click(screen.getByRole("button", { name: "Add verified output" }));
    await waitFor(() => expect(api.captureAgentArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      {
        path: "large.log",
        title: "large.log",
        expected_sha256: "8".repeat(64),
        expected_byte_size: 300_000,
      },
      expect.any(AbortSignal),
    ));
    expect(captured).toHaveBeenCalledOnce();
    expect(screen.getByText(/large\.log is now available as a verified chat artifact/u)).toBeVisible();
  });

  it("refreshes saved artifacts without claiming success when a capture receipt is lost", async () => {
    const capturePreview: AgentArtifactCapturePreview = {
      contract_version: "agent-artifact-capture-preview.v1",
      project_id: PROJECT,
      session_id: SESSION,
      path: "large.log",
      title: "large.log",
      kind: "text",
      media_type: "text/plain; charset=utf-8",
      preview_kind: "text",
      sha256: "8".repeat(64),
      byte_size: 300_000,
      requires_native_confirmation: true,
      file_content_included: false,
    };
    const api = {
      ...transport(),
      previewAgentArtifactCapture: vi.fn(async () => capturePreview),
      captureAgentArtifact: vi.fn(async () => { throw new Error("synthetic connection lost after request"); }),
    };
    const uncertain = vi.fn();
    const captured = vi.fn();
    render(
      <AgentWorkspacePane
        onArtifactCaptured={captured}
        onCaptureUncertain={uncertain}
        pendingWrite={null}
        projectId={PROJECT}
        sessionId={SESSION}
        transport={api}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /large\.log — add as generated output/u }));
    fireEvent.click(screen.getByRole("button", { name: "Review output" }));
    await screen.findByRole("button", { name: "Add verified output" });
    fireEvent.click(screen.getByRole("button", { name: "Add verified output" }));

    expect(await screen.findByText(/Capture outcome is unknown/i)).toBeVisible();
    expect(uncertain).toHaveBeenCalledOnce();
    expect(captured).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add verified output" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Close and inspect saved artifacts" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add generated output" })).toBeNull());
  });

  it("opens an exact reviewed-path capture request once without reading the file", async () => {
    const api = {
      ...transport(),
      previewAgentArtifactCapture: vi.fn(),
      captureAgentArtifact: vi.fn(),
    };
    const { rerender } = render(
      <AgentWorkspacePane
        pendingWrite={null}
        projectId={PROJECT}
        sessionId={SESSION}
        transport={api}
      />,
    );
    await screen.findByRole("button", { name: "example.ts" });
    const request = {
      sessionId: SESSION,
      path: "example.ts",
      requestId: 12,
      intent: "capture" as const,
    };
    rerender(<AgentWorkspacePane
      fileRequest={request}
      pendingWrite={null}
      projectId={PROJECT}
      sessionId={SESSION}
      transport={api}
    />);
    const dialog = await screen.findByRole("dialog", { name: "Add generated output" });
    expect(within(dialog).getByLabelText("Workspace-relative file path")).toHaveValue("example.ts");
    expect(api.getAgentWorkspaceFile).not.toHaveBeenCalled();
    rerender(<AgentWorkspacePane
      fileRequest={request}
      pendingWrite={null}
      projectId={PROJECT}
      sessionId={SESSION}
      transport={api}
      userPresenceAvailable={false}
    />);
    expect(screen.getAllByRole("dialog", { name: "Add generated output" })).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add generated output" })).not.toBeInTheDocument());
  });

  it("refuses a reviewed-path capture request while an unsaved draft exists", async () => {
    const api = {
      ...transport(),
      previewAgentArtifactCapture: vi.fn(),
      captureAgentArtifact: vi.fn(),
    };
    const { rerender } = render(<AgentWorkspacePane
      pendingWrite={null}
      projectId={PROJECT}
      sessionId={SESSION}
      transport={api}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = await screen.findByLabelText("Workspace file editor");
    fireEvent.change(editor, { target: { value: "Fictional unsaved artifact draft\n" } });
    rerender(<AgentWorkspacePane
      fileRequest={{ sessionId: SESSION, path: "example.ts", requestId: 13, intent: "capture" }}
      pendingWrite={null}
      projectId={PROJECT}
      sessionId={SESSION}
      transport={api}
    />);
    expect(await screen.findByText(/Save, apply, or discard workspace drafts/u)).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Add generated output" })).not.toBeInTheDocument();
    expect(editor).toHaveValue("Fictional unsaved artifact draft\n");
  });

  it("reviews, confirms, verifies, and opens a new workspace file", async () => {
    const api = transport();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "New file" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new file path"), {
      target: { value: "created.ts" },
    });
    fireEvent.change(screen.getByLabelText("New file content"), {
      target: { value: "export const created = true;\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review new file" }));

    const review = await screen.findByRole("region", { name: "New file review" });
    expect(within(review).getByRole("figure", { name: "New file diff for created.ts" })).toBeVisible();
    expect(within(review).getByText(/\/dev\/null/u)).toBeVisible();
    expect(api.previewAgentWorkspaceCreate).toHaveBeenCalledWith(
      SESSION,
      {
        path: "created.ts",
        content: "export const created = true;\n",
        line_ending: "lf",
      },
      expect.any(AbortSignal),
    );
    fireEvent.click(within(review).getByRole("button", { name: "Create reviewed file" }));

    await screen.findByText(/created and verified created\.ts/iu);
    expect(api.applyAgentWorkspaceCreate).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({ preview_id: PREVIEW, path: "created.ts" }),
      {
        path: "created.ts",
        content: "export const created = true;\n",
        proposed_revision: PROPOSED,
        line_ending: "lf",
        confirmation: "apply_reviewed_workspace_create",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("export const created = true;\n");
    expect(applied).toHaveBeenCalledWith("created.ts");
  });

  it("uses a non-blocking discard dialog for a new-file draft and restores focus when kept", async () => {
    const api = transport();
    const nativeConfirm = vi.spyOn(window, "confirm");
    try {
      render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

      const newFile = await screen.findByRole("button", { name: "New file" });
      await waitFor(() => expect(newFile).toBeEnabled());
      fireEvent.click(newFile);
      fireEvent.change(await screen.findByLabelText("Workspace-relative new file path"), {
        target: { value: "synthetic-draft.ts" },
      });
      fireEvent.change(screen.getByLabelText("New file content"), {
        target: { value: "export const synthetic = true;\n" },
      });
      const cancel = screen.getByRole("button", { name: "Cancel" });
      cancel.focus();
      fireEvent.click(cancel);

      const firstDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      expect(within(firstDialog).getByText("Discard the pending workspace operation draft?")).toBeVisible();
      await waitFor(() => expect(within(firstDialog).getByRole("button", { name: "Keep draft" })).toHaveFocus());
      fireEvent.keyDown(document, { key: "Escape" });

      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).not.toBeInTheDocument());
      expect(screen.getByLabelText("Workspace-relative new file path")).toHaveValue("synthetic-draft.ts");
      expect(screen.getByLabelText("New file content")).toHaveValue("export const synthetic = true;\n");
      await waitFor(() => expect(cancel).toHaveFocus());

      fireEvent.click(cancel);
      const secondDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
      fireEvent.click(within(secondDialog).getByRole("button", { name: "Discard operation draft" }));

      await waitFor(() => expect(screen.queryByLabelText("Workspace-relative new file path")).not.toBeInTheDocument());
      expect(api.previewAgentWorkspaceCreate).not.toHaveBeenCalled();
      expect(api.applyAgentWorkspaceCreate).not.toHaveBeenCalled();
      expect(nativeConfirm).not.toHaveBeenCalled();
    } finally {
      nativeConfirm.mockRestore();
    }
  });

  it("reviews a no-overwrite move and reopens the verified target", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Rename or move" }));
    fireEvent.change(screen.getByLabelText("New workspace-relative path"), {
      target: { value: "archive/example.ts" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review move" }));
    const review = await screen.findByRole("region", { name: "File move review" });
    expect(within(review).getByText("example.ts")).toBeVisible();
    expect(within(review).getByText("archive/example.ts")).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Apply reviewed move" }));

    await screen.findByText(/moved and verified example\.ts/iu);
    expect(api.applyAgentWorkspaceMove).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({ source_path: "example.ts", target_path: "archive/example.ts" }),
      {
        source_path: "example.ts",
        target_path: "archive/example.ts",
        expected_revision: BASE,
        confirmation: "apply_reviewed_workspace_move",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("archive/example.ts", { selector: ".agent-workspace__editor-head strong" })).toBeVisible();
  });

  it("reviews one exact file and moves it recoverably to Windows Recycle Bin", async () => {
    const api = transport();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Move to Recycle Bin" }));
    const operation = await screen.findByRole("region", { name: "Move workspace file to Recycle Bin" });
    expect(within(operation).getByText("Windows Recycle Bin")).toBeVisible();
    expect(within(operation).getByText(/generated name instead of the original filename/iu)).toBeVisible();
    expect(within(operation).getByText("No")).toBeVisible();
    fireEvent.click(within(operation).getByRole("button", { name: "Review Recycle Bin move" }));

    const review = await screen.findByRole("region", { name: "Recycle Bin review" });
    expect(within(review).getByText("example.ts")).toBeVisible();
    expect(within(review).getByText(/24 bytes/u)).toBeVisible();
    expect(within(review).getByText("May be an app-generated private staging name")).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Move reviewed file to Recycle Bin" }));

    await screen.findByText(/permanent deletion was not used/iu);
    expect(api.previewAgentWorkspaceFileTrash).toHaveBeenCalledWith(
      SESSION,
      { path: "example.ts", expected_revision: BASE },
      expect.any(AbortSignal),
    );
    expect(api.applyAgentWorkspaceFileTrash).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({ path: "example.ts", permanent: false }),
      {
        path: "example.ts",
        expected_revision: BASE,
        confirmation: "apply_reviewed_workspace_file_trash",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("No file open", { selector: ".agent-workspace__editor-head strong" })).toBeVisible();
    expect(applied).toHaveBeenCalledWith("example.ts");
  });

  it("reviews and verifies one new directory without recursive or overwrite authority", async () => {
    const api = transport();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} pendingWrite={null} sessionId={SESSION} transport={api} />);

    const newFolder = await screen.findByRole("button", { name: "New folder" });
    await waitFor(() => expect(newFolder).toBeEnabled());
    fireEvent.click(newFolder);
    fireEvent.change(screen.getByLabelText("Workspace-relative new folder path"), {
      target: { value: "reviewed-folder" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review new folder" }));

    const review = await screen.findByRole("region", { name: "New folder review" });
    expect(within(review).getByText("reviewed-folder")).toBeVisible();
    expect(within(review).getByText(/parent folder must already exist/iu)).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Create reviewed folder" }));

    await screen.findByText(/created and verified folder reviewed-folder/iu);
    expect(api.previewAgentWorkspaceDirectoryCreate).toHaveBeenCalledWith(
      SESSION,
      { path: "reviewed-folder" },
      expect.any(AbortSignal),
    );
    expect(api.applyAgentWorkspaceDirectoryCreate).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({ preview_id: PREVIEW, path: "reviewed-folder" }),
      {
        path: "reviewed-folder",
        confirmation: "apply_reviewed_workspace_directory_create",
      },
      expect.any(AbortSignal),
    );
    expect(applied).toHaveBeenCalledWith("reviewed-folder");
  });

  it("explains that reviewed folder creation never creates missing parents", async () => {
    const api = transport();
    api.previewAgentWorkspaceDirectoryCreate.mockRejectedValueOnce(
      new TransportError("EXAMPLE_PRIVATE_DIRECTORY_CANARY", 422, "workspace_parent_unavailable"),
    );
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "New folder" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new folder path"), {
      target: { value: "missing/child" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review new folder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The parent folder must already exist and remain an ordinary accessible workspace folder.",
    );
    expect(screen.queryByText("EXAMPLE_PRIVATE_DIRECTORY_CANARY")).not.toBeInTheDocument();
    expect(api.applyAgentWorkspaceDirectoryCreate).not.toHaveBeenCalled();
  });

  it("hard-locks lifecycle controls when folder publication cannot be verified", async () => {
    const api = transport();
    api.applyAgentWorkspaceDirectoryCreate.mockRejectedValueOnce(
      new TransportError("EXAMPLE_PRIVATE_DIRECTORY_CANARY", 409, "workspace_directory_create_unverified"),
    );
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "New folder" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new folder path"), {
      target: { value: "reviewed-folder" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review new folder" }));
    const review = await screen.findByRole("region", { name: "New folder review" });
    fireEvent.click(within(review).getByRole("button", { name: "Create reviewed folder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The folder creation outcome is unverified. Further lifecycle changes are locked; inspect the path and start a new session.",
    );
    expect(screen.queryByText("EXAMPLE_PRIVATE_DIRECTORY_CANARY")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Workspace-relative new folder path")).toBeDisabled();
    expect(screen.queryByRole("region", { name: "New folder review" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review new folder" })).toBeDisabled();
  });

  it("reviews and verifies a folder move without claiming content review", async () => {
    const api = transport();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "src" }));
    fireEvent.click(await screen.findByRole("button", { name: "Move folder" }));
    fireEvent.change(screen.getByLabelText("New workspace-relative folder path"), {
      target: { value: "archive/src" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review folder move" }));

    const review = await screen.findByRole("region", { name: "Folder move review" });
    expect(within(review).getByText("src")).toBeVisible();
    expect(within(review).getByText("archive/src")).toBeVisible();
    expect(within(review).getByText(/contents reviewed/iu)).toBeVisible();
    expect(within(review).getByText(/not enumerated/iu)).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Move reviewed folder" }));

    await screen.findByText(/moved and verified folder src to archive\/src/iu);
    expect(api.previewAgentWorkspaceDirectoryMove).toHaveBeenCalledWith(
      SESSION,
      { source_path: "src", target_path: "archive/src" },
      expect.any(AbortSignal),
    );
    expect(api.applyAgentWorkspaceDirectoryMove).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({ preview_id: PREVIEW, contents_reviewed: false }),
      {
        source_path: "src",
        target_path: "archive/src",
        confirmation: "apply_reviewed_workspace_directory_move",
      },
      expect.any(AbortSignal),
    );
    expect(applied).toHaveBeenCalledWith("archive/src");
    expect(screen.getByLabelText("archive/src")).toBeVisible();
  });

  it("refuses a folder move into its own subtree before requesting authority", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "src" }));
    fireEvent.click(await screen.findByRole("button", { name: "Move folder" }));
    fireEvent.change(screen.getByLabelText("New workspace-relative folder path"), {
      target: { value: "src/nested/moved" },
    });

    expect(screen.getByRole("button", { name: "Review folder move" })).toBeDisabled();
    expect(api.previewAgentWorkspaceDirectoryMove).not.toHaveBeenCalled();
  });

  it("hard-locks folder lifecycle after an unverified directory move", async () => {
    const api = transport();
    api.applyAgentWorkspaceDirectoryMove.mockRejectedValueOnce(
      new TransportError("EXAMPLE_PRIVATE_DIRECTORY_MOVE_CANARY", 409, "workspace_directory_move_unverified"),
    );
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "src" }));
    fireEvent.click(await screen.findByRole("button", { name: "Move folder" }));
    fireEvent.change(screen.getByLabelText("New workspace-relative folder path"), {
      target: { value: "archive/src" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review folder move" }));
    const review = await screen.findByRole("region", { name: "Folder move review" });
    fireEvent.click(within(review).getByRole("button", { name: "Move reviewed folder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The folder move outcome is unverified. Further lifecycle changes are locked; inspect both paths and start a new session.",
    );
    expect(screen.queryByText("EXAMPLE_PRIVATE_DIRECTORY_MOVE_CANARY")).not.toBeInTheDocument();
    expect(screen.getByLabelText("New workspace-relative folder path")).toBeDisabled();
    expect(screen.queryByRole("region", { name: "Folder move review" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review folder move" })).toBeDisabled();
  });

  it("keeps lifecycle apply read-only when native user presence is unavailable", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} userPresenceAvailable={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "New file" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new file path"), { target: { value: "created.ts" } });
    fireEvent.change(screen.getByLabelText("New file content"), { target: { value: "example\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review new file" }));
    const review = await screen.findByRole("region", { name: "New file review" });
    expect(within(review).getByRole("button", { name: "Create reviewed file" })).toBeDisabled();
    expect(within(review).getByText(/native user-presence confirmation is unavailable/u)).toBeVisible();
  });

  it("locks the editor when the discovery endpoint proves the selected root changed", async () => {
    const api = {
      ...transport(),
      getAgentWorkspaceDiscovery: vi.fn().mockRejectedValue(
        new TransportError("EXAMPLE_PRIVATE_DISCOVERY_ROOT", 409, "workspace_root_changed"),
      ),
    };
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    expect(await screen.findByText(/workspace folder was moved or replaced/u)).toBeVisible();
    expect(screen.queryByText(/last write outcome could not be verified/u)).not.toBeInTheDocument();
    expect(screen.queryByText("EXAMPLE_PRIVATE_DISCOVERY_ROOT")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry folder" })).toBeDisabled();
    expect(api.getAgentWorkspaceFile).not.toHaveBeenCalled();
  });

  it("does not let a superseded transport's root error lock the replacement editor", async () => {
    const first = transport();
    const second = transport();
    let rejectOld!: (error: unknown) => void;
    first.getAgentWorkspaceTree.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
    const view = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={first} />);
    view.rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={second} />);
    await screen.findByRole("button", { name: /example.ts/u });
    await act(async () => rejectOld(new TransportError("EXAMPLE_PRIVATE_CANARY", 409, "workspace_root_changed")));
    fireEvent.click(screen.getByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    expect(editor).not.toHaveAttribute("readonly");
    expect(screen.queryByText(/workspace folder was moved or replaced/u)).not.toBeInTheDocument();
  });

  it("retains the applied receipt but locks the editor when readback finds a replacement root", async () => {
    const api = transport();
    api.getAgentWorkspaceFile.mockResolvedValueOnce(file())
      .mockRejectedValueOnce(new TransportError("EXAMPLE_PRIVATE_CANARY", 409, "workspace_root_changed"));
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply reviewed edit" }));
    await screen.findByText(/workspace folder was moved or replaced/u);
    expect(screen.getByText(/Applied the reviewed edit/u)).toBeVisible();
    expect(editor).toHaveValue("export const value = 2;\n");
    expect(editor).toBeEnabled();
    expect(editor).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Reload file" })).toBeDisabled();
    expect(api.applyAgentWorkspaceEdit).toHaveBeenCalledTimes(1);
  });

  it("does not call an incomplete zero-entry response an empty folder", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockResolvedValueOnce({ contract_version: "local-agent-workspace.v1", session_id: SESSION, path: ".", entries: [], complete: false });
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    await screen.findByText(/bounded folder view is incomplete/u);
    expect(screen.queryByText("This folder is empty.")).not.toBeInTheDocument();
    expect(screen.getByText(/No entries could be shown/u)).toBeVisible();
  });

  it("shows a confirmed empty folder only after complete enumeration", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockResolvedValueOnce({ contract_version: "local-agent-workspace.v1", session_id: SESSION, path: ".", entries: [], complete: true });
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    expect(await screen.findByText("This folder is empty.")).toBeVisible();
    expect(screen.queryByText(/bounded folder view is incomplete/u)).not.toBeInTheDocument();
  });

  it("explains a bounded inspection timeout and offers a read-only retry", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockRejectedValueOnce(new TransportError("EXAMPLE_PRIVATE_CANARY", 503, "workspace_inspection_timeout"));
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Folder inspection reached its time limit");
    expect(screen.queryByText(/EXAMPLE_PRIVATE_CANARY/u)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry folder" }));
    await screen.findByRole("button", { name: /example.ts/u });
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("preserves a copyable draft and blocks edits after the workspace root changes", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "Keep this fictional draft for review." } });
    api.getAgentWorkspaceTree.mockRejectedValueOnce(new TransportError("EXAMPLE_PRIVATE_CANARY", 409, "workspace_root_changed"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh folder" }));
    await screen.findByText(/workspace folder was moved or replaced/u);
    expect(editor).toHaveValue("Keep this fictional draft for review.");
    expect(editor).toBeEnabled();
    expect(editor).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    expect(api.previewAgentWorkspaceEdit).not.toHaveBeenCalled();
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_CANARY/u)).not.toBeInTheDocument();
  });
});

describe("AgentWorkspacePane", () => {
  it("stages two existing files, reviews every diff, and applies one bound transaction", async () => {
    const api = transport();
    const applied = vi.fn();
    const dirty = vi.fn();
    render(
      <AgentWorkspacePane
        onApplied={applied}
        onDirtyChange={dirty}
        pendingWrite={null}
        sessionId={SESSION}
        transport={api}
      />,
    );

    await stageTwoWorkspaceFiles();
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Review 2-file transaction" }));

    const review = await screen.findByRole("region", { name: "Multi-file transaction review" });
    expect(within(review).getByText(/2 files · 0 create · 2 edit · 2 additions · 2 removals/u)).toBeVisible();
    expect(within(review).getByRole("figure", { name: "Transaction diff for example.ts" })).toHaveAttribute("data-compact", "true");
    expect(within(review).getByRole("figure", { name: "Transaction diff for other.ts" })).toBeInTheDocument();
    expect([...review.querySelectorAll("summary")].map((item) => item.textContent)).toEqual([
      "example.ts edit+1 −1",
      "other.ts edit+1 −1",
    ]);
    expect(api.previewAgentWorkspaceTransaction).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      {
        changes: [
          { operation: "edit", path: "example.ts", content: "export const value = 2;\n", expected_revision: BASE, line_ending: "lf" },
          { operation: "edit", path: "other.ts", content: "export const other = 2;\n", expected_revision: OTHER_BASE, line_ending: "lf" },
        ],
      },
      expect.any(AbortSignal),
    );

    fireEvent.click(within(review).getByRole("button", { name: "Apply 2-file transaction" }));
    expect(await screen.findByText(/Committed and verified 2 reviewed files as one transaction/u)).toBeVisible();
    expect(api.applyAgentWorkspaceTransaction).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      expect.objectContaining({ plan_id: TRANSACTION_PLAN, file_count: 2 }),
      {
        changes: [
          { operation: "edit", path: "example.ts", content: "export const value = 2;\n", expected_revision: BASE, proposed_revision: PROPOSED, line_ending: "lf" },
          { operation: "edit", path: "other.ts", content: "export const other = 2;\n", expected_revision: OTHER_BASE, proposed_revision: OTHER_PROPOSED, line_ending: "lf" },
        ],
        confirmation: "apply_reviewed_workspace_transaction",
      },
      expect.any(AbortSignal),
    );
    expect(applied.mock.calls).toEqual([["example.ts"], ["other.ts"]]);
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
    expect(screen.queryByRole("button", { name: "Open staged file example.ts" })).not.toBeInTheDocument();
  });

  it("stages a new file with an existing-file edit and applies one mixed transaction", async () => {
    const api = transport();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = await screen.findByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
    await stageNewWorkspaceFile();

    expect(screen.getByText("2/8 staged · 1 create · 1 edit")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review 2-file transaction" }));
    const review = await screen.findByRole("region", { name: "Multi-file transaction review" });
    expect(within(review).getByText(/2 files · 1 create · 1 edit · 2 additions · 1 removal/u)).toBeVisible();
    expect([...review.querySelectorAll("summary")].map((item) => item.textContent)).toEqual([
      "created.ts create+1 −0",
      "example.ts edit+1 −1",
    ]);
    expect(api.previewAgentWorkspaceTransaction).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      {
        changes: [
          { operation: "create", path: "created.ts", content: "export const created = true;\n", expected_revision: null, line_ending: "lf" },
          { operation: "edit", path: "example.ts", content: "export const value = 2;\n", expected_revision: BASE, line_ending: "lf" },
        ],
      },
      expect.any(AbortSignal),
    );

    fireEvent.click(within(review).getByRole("button", { name: "Apply 2-file transaction" }));
    expect(await screen.findByText(/2 reviewed files as one transaction \(1 created, 1 edited\)/u)).toBeVisible();
    expect(api.applyAgentWorkspaceTransaction).toHaveBeenCalledExactlyOnceWith(
      SESSION,
      expect.objectContaining({ plan_id: TRANSACTION_PLAN, file_count: 2 }),
      {
        changes: [
          { operation: "create", path: "created.ts", content: "export const created = true;\n", expected_revision: null, proposed_revision: CREATED_PROPOSED, line_ending: "lf" },
          { operation: "edit", path: "example.ts", content: "export const value = 2;\n", expected_revision: BASE, proposed_revision: PROPOSED, line_ending: "lf" },
        ],
        confirmation: "apply_reviewed_workspace_transaction",
      },
      expect.any(AbortSignal),
    );
    expect(applied.mock.calls).toEqual([["created.ts"], ["example.ts"]]);
    expect(screen.queryByRole("button", { name: "Edit staged new file created.ts" })).not.toBeInTheDocument();
  });

  it("keeps a removed staged edit as an unsaved editor draft after explicit confirmation", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageTwoWorkspaceFiles();
    const remove = screen.getByRole("button", { name: "Remove other.ts from transaction" });
    fireEvent.click(remove);
    const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    expect(within(keepDialog).getByText(/current text will remain in the editor as an unsaved draft/u)).toBeVisible();
    fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep draft" }));
    expect(screen.getByRole("button", { name: "Open staged file other.ts" })).toBeVisible();

    fireEvent.click(remove);
    const removeDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(removeDialog).getByRole("button", { name: "Remove staged draft" }));

    expect(screen.queryByRole("button", { name: "Open staged file other.ts" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open staged file example.ts" })).toBeVisible();
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("export const other = 2;\n");
    expect(screen.getByText(/remains in the editor; no workspace file changed/u)).toBeVisible();
    expect(api.applyAgentWorkspaceTransaction).not.toHaveBeenCalled();
  });

  it("keeps or clears every staged draft only through the in-app confirmation", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageTwoWorkspaceFiles();
    const clear = screen.getByRole("button", { name: "Clear staged drafts" });
    fireEvent.click(clear);
    const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    expect(within(keepDialog).getByText("Discard all staged multi-file drafts?")).toBeVisible();
    fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep draft" }));
    expect(screen.getByRole("button", { name: "Open staged file example.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file other.ts" })).toBeVisible();

    fireEvent.click(clear);
    const clearDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(clearDialog).getByRole("button", { name: "Clear staged drafts" }));

    expect(screen.queryByRole("button", { name: "Open staged file example.ts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open staged file other.ts" })).not.toBeInTheDocument();
    expect(screen.getByText(/Cleared the transaction drafts; no workspace file changed/u)).toBeVisible();
    expect(api.applyAgentWorkspaceTransaction).not.toHaveBeenCalled();
  });

  it("reopens and renames a staged new-file draft without adding a duplicate member", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageNewWorkspaceFile();
    fireEvent.click(screen.getByRole("button", { name: "Edit staged new file created.ts" }));
    expect(screen.getByLabelText("Workspace-relative new file path")).toHaveValue("created.ts");
    expect(screen.getByLabelText("New file content")).toHaveValue("export const created = true;\n");
    fireEvent.change(screen.getByLabelText("Workspace-relative new file path"), {
      target: { value: "renamed.ts" },
    });
    fireEvent.change(screen.getByLabelText("New file content"), {
      target: { value: "export const renamed = true;\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update staged new file" }));

    expect(screen.queryByRole("button", { name: "Edit staged new file created.ts" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit staged new file renamed.ts" })).toBeVisible();
    expect(screen.getByText("1/8 staged · 1 create · 0 edit")).toBeVisible();
    expect(api.previewAgentWorkspaceTransaction).not.toHaveBeenCalled();
  });

  it("refuses a case-insensitive new-file path collision with a staged edit", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = await screen.findByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
    fireEvent.click(screen.getByRole("button", { name: "New file" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new file path"), {
      target: { value: "EXAMPLE.ts" },
    });
    fireEvent.change(screen.getByLabelText("New file content"), { target: { value: "collision\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage new file in transaction" }));

    expect(await screen.findByText(/example\.ts is already staged for edit/u)).toBeVisible();
    expect(screen.getByText("1/8 staged · 0 create · 1 edit")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit staged new file EXAMPLE.ts" })).not.toBeInTheDocument();
    expect(api.previewAgentWorkspaceTransaction).not.toHaveBeenCalled();
  });

  it("keeps mixed drafts and reports both rollback actions", async () => {
    const api = transport();
    api.applyAgentWorkspaceTransaction.mockResolvedValueOnce({
      contract_version: "local-agent-workspace-transaction.v2",
      session_id: SESSION,
      plan_id: TRANSACTION_PLAN,
      state: "rolled_back",
      reason: "workspace_write_failed",
      file_count: 2,
      files: [
        { path: "created.ts", state: "removed", revision: null, byte_size: null },
        { path: "example.ts", state: "restored", revision: BASE, byte_size: 24 },
      ],
    });
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = await screen.findByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
    await stageNewWorkspaceFile();
    fireEvent.click(screen.getByRole("button", { name: "Review 2-file transaction" }));
    const review = await screen.findByRole("region", { name: "Multi-file transaction review" });
    fireEvent.click(within(review).getByRole("button", { name: "Apply 2-file transaction" }));

    expect(await screen.findByText(/1 earlier edit was restored and 1 earlier creation was removed/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Edit staged new file created.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file example.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Review 2-file transaction" })).toBeEnabled();
  });

  it("blocks combined review while the new-file editor contains an unstaged change", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageTwoWorkspaceFiles();
    fireEvent.click(screen.getByRole("button", { name: "New file" }));
    fireEvent.change(screen.getByLabelText("Workspace-relative new file path"), {
      target: { value: "unstaged.ts" },
    });
    fireEvent.change(screen.getByLabelText("New file content"), { target: { value: "unstaged\n" } });

    expect(screen.getByRole("button", { name: "Review 2-file transaction" })).toBeDisabled();
    expect(screen.getByText(/new-file editor has changes that are not in this plan/u)).toBeVisible();
    expect(api.previewAgentWorkspaceTransaction).not.toHaveBeenCalled();
  });

  it("keeps every staged draft after a verified transaction rollback", async () => {
    const api = transport();
    api.applyAgentWorkspaceTransaction.mockResolvedValueOnce({
      contract_version: "local-agent-workspace-transaction.v2",
      session_id: SESSION,
      plan_id: TRANSACTION_PLAN,
      state: "rolled_back",
      reason: "workspace_write_failed",
      file_count: 2,
      files: [
        { path: "example.ts", state: "restored", revision: BASE, byte_size: 24 },
        { path: "other.ts", state: "not_applied", revision: null, byte_size: null },
      ],
    });
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageTwoWorkspaceFiles();
    fireEvent.click(screen.getByRole("button", { name: "Review 2-file transaction" }));
    const review = await screen.findByRole("region", { name: "Multi-file transaction review" });
    fireEvent.click(within(review).getByRole("button", { name: "Apply 2-file transaction" }));

    expect(await screen.findByText(/earlier edit was restored; the staged drafts remain available/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file example.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file other.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Review 2-file transaction" })).toBeEnabled();
  });

  it("preserves drafts but hard-locks every further write after an unverified transaction", async () => {
    const api = transport();
    api.applyAgentWorkspaceTransaction.mockResolvedValueOnce({
      contract_version: "local-agent-workspace-transaction.v2",
      session_id: SESSION,
      plan_id: TRANSACTION_PLAN,
      state: "unverified",
      reason: "workspace_transaction_unverified",
      file_count: 2,
      files: [
        { path: "example.ts", state: "unverified", revision: null, byte_size: null },
        { path: "other.ts", state: "not_applied", revision: null, byte_size: null },
      ],
    });
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);

    await stageTwoWorkspaceFiles();
    fireEvent.click(screen.getByRole("button", { name: "Review 2-file transaction" }));
    const review = await screen.findByRole("region", { name: "Multi-file transaction review" });
    fireEvent.click(within(review).getByRole("button", { name: "Apply 2-file transaction" }));

    expect(await screen.findByText(/transaction outcome is unverified/u)).toBeVisible();
    expect(screen.getByText(/start a new session after inspecting every listed file/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file example.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open staged file other.ts" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Review 2-file transaction" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear staged drafts" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove example.ts from transaction" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove other.ts from transaction" })).toBeDisabled();
    expect(api.applyAgentWorkspaceTransaction).toHaveBeenCalledTimes(1);
  });

  it("does not mistake an already staged draft for a disposable editor buffer", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Open staged file example.ts" }));
    await waitFor(() => expect(editor).toHaveValue("export const value = 2;\n"));
    fireEvent.click(screen.getByRole("button", { name: "other.ts" }));
    await waitFor(() => expect(editor).toHaveValue("export const other = 1;\n"));
    expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).not.toBeInTheDocument();
  });

  it("protects staged drafts when hiding the workspace", async () => {
    const api = transport();
    const close = vi.fn();
    render(<AgentWorkspacePane onClose={close} pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Stage for multi-file edit" }));

    const hide = screen.getByRole("button", { name: "Hide workspace" });
    hide.focus();
    fireEvent.click(hide);
    const keepDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    expect(within(keepDialog).getByText("Discard all staged multi-file drafts?")).toBeVisible();
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(within(keepDialog).getByRole("button", { name: "Keep draft" }));
    await waitFor(() => expect(hide).toHaveFocus());
    expect(close).not.toHaveBeenCalled();

    fireEvent.click(hide);
    const discardDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(discardDialog).getByRole("button", { name: "Discard and hide" }));
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("retains the manual draft but blocks review/apply when command cleanup becomes uncertain", async () => {
    const api = transport();
    const request = { sessionId: SESSION, path: "example.ts", requestId: 1 };
    const { rerender } = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} />);
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Workspace file editor"), { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    await screen.findByRole("button", { name: "Apply reviewed edit" });
    rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} blockedReason="Example command cleanup is unconfirmed." />);
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("export const value = 2;\n");
    expect(screen.getByLabelText("Workspace file editor")).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply reviewed edit" })).toBeDisabled();
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("restarts the initial receipt file read after a Strict Mode effect remount", async () => {
    const api = transport();
    const request = { sessionId: SESSION, path: "example.ts", requestId: 1 };
    render(<StrictMode><AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} /></StrictMode>);
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveValue("export const value = 1;\n"));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveFocus());
    expect(api.getAgentWorkspaceFile).toHaveBeenLastCalledWith(SESSION, "example.ts", expect.any(AbortSignal));
  });

  it("opens a turn-receipt file once, focuses the editor, and does not replay the request on rerender", async () => {
    const api = transport();
    const request = { sessionId: SESSION, path: "example.ts", requestId: 1 };
    const { rerender } = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} />);
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveValue("export const value = 1;\n"));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveFocus());
    expect(api.getAgentWorkspaceFile).toHaveBeenCalledExactlyOnceWith(SESSION, "example.ts", expect.any(AbortSignal));
    rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} userPresenceAvailable={false} />);
    expect(api.getAgentWorkspaceFile).toHaveBeenCalledTimes(1);
  });

  it("reveals a non-editable artifact in the bounded file tree without reading or executing it", async () => {
    const api = transport();
    const request = {
      sessionId: SESSION,
      path: "large.log",
      requestId: 1,
      intent: "reveal" as const,
    };
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={request} />);

    const entryButton = await screen.findByRole("button", { name: /large.log/u });
    const entry = entryButton.closest("li");
    expect(entryButton).toBeDisabled();
    expect(entry).toHaveAttribute("data-revealed", "true");
    expect(entry).toHaveAttribute("aria-current", "location");
    await waitFor(() => expect(entry).toHaveFocus());
    expect(screen.getByText(/file was not opened or executed/u)).toBeVisible();
    expect(api.getAgentWorkspaceFile).not.toHaveBeenCalled();
  });

  it("keeps a maximum folder page bounded while revealing a late requested path", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockImplementation(async (sessionId: string, path: string) => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: sessionId,
      path,
      entries: Array.from({ length: 400 }, (_, index) => ({
        path: `file-${index.toString().padStart(3, "0")}.txt`,
        name: `file-${index.toString().padStart(3, "0")}.txt`,
        kind: "file" as const,
        byte_size: 10,
        editable_candidate: true,
      })),
      complete: true,
    }));
    render(<AgentWorkspacePane
      fileRequest={{
        sessionId: SESSION,
        path: "file-399.txt",
        requestId: 99,
        intent: "reveal",
      }}
      pendingWrite={null}
      sessionId={SESSION}
      transport={api}
    />);

    const late = await screen.findByRole("button", { name: "file-399.txt" });
    expect(late.closest("li")).toHaveAttribute("aria-current", "location");
    expect(screen.getByText("Showing 351–400 of 400")).toBeVisible();
    expect(screen.queryByRole("button", { name: "file-000.txt" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem").filter((item) => item.closest(".agent-workspace__tree"))).toHaveLength(50);
  });

  it("navigates to a nested artifact parent for reveal while retaining an unsaved editor draft", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockImplementation(async (sessionId: string, path: string) => ({
      contract_version: "local-agent-workspace.v1" as const,
      session_id: sessionId,
      path,
      entries: path === "docs"
        ? [{
            path: "docs/synthetic-review.docx",
            name: "synthetic-review.docx",
            kind: "file" as const,
            byte_size: 512,
            editable_candidate: false,
          }]
        : [{
            path: "example.ts",
            name: "example.ts",
            kind: "file" as const,
            byte_size: 24,
            editable_candidate: true,
          }],
      complete: true,
    }));
    const { rerender } = render(
      <AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "example.ts" }));
    const editor = await screen.findByLabelText("Workspace file editor");
    fireEvent.change(editor, { target: { value: "Fictional unsaved manual edit" } });

    rerender(<AgentWorkspacePane
      fileRequest={{
        sessionId: SESSION,
        path: "docs/synthetic-review.docx",
        requestId: 2,
        intent: "reveal",
      }}
      pendingWrite={null}
      sessionId={SESSION}
      transport={api}
    />);

    const revealed = await screen.findByRole("button", { name: /synthetic-review.docx/u });
    expect(revealed.closest("li")).toHaveAttribute("data-revealed", "true");
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("Fictional unsaved manual edit");
    expect(api.getAgentWorkspaceTree).toHaveBeenCalledWith(SESSION, "docs", expect.any(AbortSignal));
    expect(api.getAgentWorkspaceFile).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Discard workspace changes?" })).not.toBeInTheDocument();
  });

  it("rejects an unsafe reveal path without forwarding it to workspace reads", async () => {
    const api = transport();
    render(<AgentWorkspacePane
      fileRequest={{ sessionId: SESSION, path: "../outside.docx", requestId: 1, intent: "reveal" }}
      pendingWrite={null}
      sessionId={SESSION}
      transport={api}
    />);
    expect(await screen.findByText(/not a safe workspace-relative path/u)).toBeVisible();
    expect(api.getAgentWorkspaceFile).not.toHaveBeenCalled();
    expect(api.getAgentWorkspaceTree).not.toHaveBeenCalledWith(
      SESSION,
      "..",
      expect.anything(),
    );
  });

  it("protects unsaved edits from receipt links and from hiding the workspace", async () => {
    const api = transport();
    const close = vi.fn();
    const { rerender } = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} onClose={close} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Workspace file editor"), { target: { value: "Fictional unsaved manual edit" } });
    rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} onClose={close} fileRequest={{ sessionId: SESSION, path: "other.ts", requestId: 1 }} />);
    const receiptDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    expect(within(receiptDialog).getByText("Discard the unsaved manual edit?")).toBeVisible();
    expect(api.getAgentWorkspaceFile).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("Fictional unsaved manual edit");
    fireEvent.click(within(receiptDialog).getByRole("button", { name: "Keep draft" }));

    const hide = screen.getByRole("button", { name: "Hide workspace" });
    fireEvent.click(hide);
    const keepHideDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(keepHideDialog).getByRole("button", { name: "Keep draft" }));
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(hide);
    const discardHideDialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(discardHideDialog).getByRole("button", { name: "Discard and hide" }));
    expect(close).toHaveBeenCalledTimes(1);
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("does not let a late file response replace a newer receipt selection", async () => {
    let finishFirst!: (value: AgentWorkspaceFile) => void;
    const api = transport();
    api.getAgentWorkspaceFile.mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve; }))
      .mockResolvedValueOnce(file("other.ts", "Newest fictional selection\n"));
    const { rerender } = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={{ sessionId: SESSION, path: "example.ts", requestId: 1 }} />);
    await waitFor(() => expect(api.getAgentWorkspaceFile).toHaveBeenCalledTimes(1));
    rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} fileRequest={{ sessionId: SESSION, path: "other.ts", requestId: 2 }} />);
    await waitFor(() => expect(screen.getByLabelText("Workspace file editor")).toHaveValue("Newest fictional selection\n"));
    await act(async () => finishFirst(file()));
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("Newest fictional selection\n");
  });

  it("never sends a stale receipt path to a replacement session or transport", async () => {
    const first = transport();
    const second = transport();
    const request = { sessionId: SESSION, path: "example.ts", requestId: 1 };
    const { rerender } = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={first} fileRequest={request} />);
    await waitFor(() => expect(first.getAgentWorkspaceFile).toHaveBeenCalledTimes(1));
    rerender(<AgentWorkspacePane pendingWrite={null} sessionId={OTHER_SESSION} transport={second} fileRequest={request} />);
    await waitFor(() => expect(second.getAgentWorkspaceTree).toHaveBeenCalled());
    expect(second.getAgentWorkspaceFile).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("");
  });

  it("opens a file, reviews the server diff, and applies only the reviewed draft", async () => {
    const api = transport();
    api.getAgentWorkspaceFile
      .mockResolvedValueOnce(file())
      .mockResolvedValueOnce(file("example.ts", "export const value = 2;\n", PROPOSED));
    const dirty = vi.fn();
    const applied = vi.fn();
    render(<AgentWorkspacePane onApplied={applied} onDirtyChange={dirty} pendingWrite={null} sessionId={SESSION} transport={api} />);

    expect(await screen.findByText("example.ts")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /example.ts/u }));
    const editor = await screen.findByLabelText("Workspace file editor") as HTMLTextAreaElement;
    expect(editor.value).toContain("value = 1");
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    expect(await screen.findByRole("region", { name: "Manual edit review" })).toBeTruthy();
    expect(screen.getByRole("figure", { name: "Manual edit diff for example.ts" })).toBeVisible();
    expect(screen.getByText(/\+2/u)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed edit" }));
    await waitFor(() => expect(api.applyAgentWorkspaceEdit).toHaveBeenCalledWith(
      SESSION,
      PREVIEW,
      {
        path: "example.ts",
        content: "export const value = 2;\n",
        expected_revision: BASE,
        proposed_revision: PROPOSED,
        line_ending: "lf",
        confirmation: "apply_reviewed_workspace_edit",
      },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/Applied the reviewed edit/u)).toBeTruthy();
    expect(editor.value).toContain("value = 2");
    expect(applied).toHaveBeenCalledExactlyOnceWith("example.ts");
  });

  it("shows the agent diff without applying it and protects an unsaved manual draft", async () => {
    const api = transport();
    const pending: AgentEvent = {
      seq: 3,
      at: "2026-08-20T20:00:00Z",
      kind: "approval_required",
      attachments: [],
      text: null,
      reasoning: null,
      stream_id: null,
      stream_phase: null,
      stream_status: null,
      tool: "write_file",
      arguments: { path: "example.ts" },
      call_id: "call-example",
      approval_id: "e".repeat(32),
      ok: null,
      preview: "--- a/example.ts\n+++ b/example.ts\n-agent\n+proposal",
    };
    render(<AgentWorkspacePane pendingWrite={pending} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    expect(screen.getByRole("button", { name: "large.log — too large to edit (256 KB limit)" })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent(/linked.*Unavailable — not opened or followed/u);
    const editor = await screen.findByLabelText("Workspace file editor") as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "unsaved\n" } });
    expect(screen.getByRole("region", { name: "Agent proposed diff" })).toBeTruthy();
    expect(screen.getByRole("figure", { name: "Agent proposed diff for example.ts" })).toHaveTextContent("+proposal");
    expect(screen.getByLabelText("Diff summary unavailable: no unified hunk headers")).toHaveTextContent("Counts unavailable · raw review");
    fireEvent.click(screen.getByRole("button", { name: /src/u }));
    const dialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    expect(within(dialog).getByText("Discard the unsaved manual edit?")).toBeVisible();
    expect(api.getAgentWorkspaceTree).toHaveBeenCalledTimes(1);
    expect(editor.value).toBe("unsaved\n");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep draft" }));
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("invalidates the apply button when the draft changes after preview", async () => {
    const api = transport();
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = await screen.findByLabelText("Workspace file editor") as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    await screen.findByRole("region", { name: "Manual edit review" });
    fireEvent.change(editor, { target: { value: "export const value = 3;\n" } });
    expect(screen.getByText(/draft changed after this preview/u)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Apply reviewed edit" })).toBeDisabled();
  });

  it("keeps a reviewed preview read-only without native user presence", async () => {
    const api = transport();
    render(
      <AgentWorkspacePane
        pendingWrite={null}
        sessionId={SESSION}
        transport={api}
        userPresenceAvailable={false}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = await screen.findByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, {
      target: { value: "export const value = 2;\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    await screen.findByRole("region", { name: "Manual edit review" });

    expect(screen.getByText(/preview is read-only here/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply reviewed edit" })).toBeDisabled();
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("drops an in-flight file response when the selected session changes", async () => {
    const api = transport();
    let resolveFile!: (value: AgentWorkspaceFile) => void;
    api.getAgentWorkspaceFile.mockImplementationOnce(() => new Promise((resolve) => {
      resolveFile = resolve;
    }));
    const view = render(
      <AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));

    view.rerender(
      <AgentWorkspacePane pendingWrite={null} sessionId={OTHER_SESSION} transport={api} />,
    );
    resolveFile(file());

    await waitFor(() => expect(api.getAgentWorkspaceTree).toHaveBeenCalledWith(
      OTHER_SESSION,
      ".",
      expect.any(AbortSignal),
    ));
    expect(screen.getByText("No file open")).toBeVisible();
    expect((screen.getByLabelText("Workspace file editor") as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps the write acknowledgment when the readback fails and retries only the read", async () => {
    const api = transport();
    const updated = "export const value = 2;\n";
    api.getAgentWorkspaceFile
      .mockResolvedValueOnce(file())
      .mockRejectedValueOnce(new Error("synthetic-readback-failure"))
      .mockResolvedValueOnce(file("example.ts", updated, PROPOSED));
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: updated } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply reviewed edit" }));
    await screen.findByText(/Applied the reviewed edit/u);
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload file" }));
    await waitFor(() => expect(api.getAgentWorkspaceFile).toHaveBeenCalledTimes(3));
    expect(api.applyAgentWorkspaceEdit).toHaveBeenCalledTimes(1);
    expect(editor).toHaveValue(updated);
    expect(screen.queryByText("synthetic-readback-failure")).not.toBeInTheDocument();
  });

  it("offers a read-only retry when the workspace root failed to load", async () => {
    const api = transport();
    api.getAgentWorkspaceTree.mockRejectedValueOnce(new Error("synthetic-tree-failure"));
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry folder" }));
    await screen.findByRole("button", { name: /example.ts/u });
    expect(api.getAgentWorkspaceTree).toHaveBeenCalledTimes(2);
    expect(api.applyAgentWorkspaceEdit).not.toHaveBeenCalled();
  });

  it("does not turn an uncertain write into a failure claim or repeat it on recovery", async () => {
    const api = transport();
    api.applyAgentWorkspaceEdit.mockRejectedValueOnce(new Error("synthetic-unknown-write-outcome"));
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "synthetic pending edit\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply reviewed edit" }));
    await screen.findByText(/Could not confirm whether the edit was applied/u);
    expect(editor).toHaveValue("synthetic pending edit\n");
    expect(screen.queryByText(/Applied the reviewed edit/u)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload file" }));
    const dialog = await screen.findByRole("dialog", { name: "Discard workspace changes?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Discard and open file" }));
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    expect(api.applyAgentWorkspaceEdit).toHaveBeenCalledTimes(1);
  });

  it("locks further edits when the server reports an unverified write result", async () => {
    const api = transport();
    api.applyAgentWorkspaceEdit.mockRejectedValueOnce(
      new TransportError("EXAMPLE_PRIVATE_CANARY", 409, "workspace_verification_failed"),
    );
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply reviewed edit" }));
    await screen.findByText(/write result is unverified/u);
    expect(editor).toHaveValue("export const value = 2;\n");
    expect(screen.getByRole("button", { name: "Review diff" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload file" })).toBeEnabled();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_CANARY/u)).not.toBeInTheDocument();
  });

  it("keeps the draft reviewable when a verified rollback reports no applied edit", async () => {
    const api = transport();
    api.applyAgentWorkspaceEdit.mockRejectedValueOnce(
      new TransportError("EXAMPLE_PRIVATE_CANARY", 503, "workspace_write_failed"),
    );
    render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    const editor = screen.getByLabelText("Workspace file editor");
    await waitFor(() => expect(editor).toHaveValue("export const value = 1;\n"));
    fireEvent.change(editor, { target: { value: "export const value = 2;\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Review diff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply reviewed edit" }));
    await screen.findByText(/reviewed edit was not applied/u);
    expect(editor).toHaveValue("export const value = 2;\n");
    expect(screen.getByRole("button", { name: "Review diff" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Reload file" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Applied the reviewed edit/u)).not.toBeInTheDocument();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_CANARY/u)).not.toBeInTheDocument();
  });

  it("discards an old transport's file result even when the session id is unchanged", async () => {
    const first = transport();
    const second = transport();
    let resolveFile!: (value: AgentWorkspaceFile) => void;
    first.getAgentWorkspaceFile.mockImplementationOnce(() => new Promise((resolve) => { resolveFile = resolve; }));
    const view = render(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={first} />);
    fireEvent.click(await screen.findByRole("button", { name: /example.ts/u }));
    view.rerender(<AgentWorkspacePane pendingWrite={null} sessionId={SESSION} transport={second} />);
    await waitFor(() => expect(second.getAgentWorkspaceTree).toHaveBeenCalledTimes(1));
    await act(async () => { resolveFile(file("example.ts", "synthetic obsolete connection\n")); });
    expect(screen.getByLabelText("Workspace file editor")).toHaveValue("");
    expect(screen.getByText("No file open")).toBeVisible();
    expect(second.getAgentWorkspaceFile).not.toHaveBeenCalled();
  });
});
