import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentArtifact,
  AgentArtifactContent,
  AgentArtifactDetail,
  AgentArtifactExport,
  AgentArtifactLifecycleCounts,
  AgentDocumentPreview,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentArtifactsPanel } from "./AgentArtifactsPanel";

vi.mock("./AgentPdfPreview", async () => {
  const { useEffect } = await import("react");
  return {
    AgentPdfPreview: ({
      onStateChange,
      title,
      versionNumber,
    }: {
      blob: Blob;
      onStateChange: (phase: "loading" | "ready" | "error") => void;
      title: string;
      versionNumber: number;
    }) => {
      useEffect(() => {
        onStateChange("ready");
      }, []);
      return (
        <section aria-label={`PDF preview of ${title} v${versionNumber}`} data-state="ready">
          <span>Ready · local canvas</span>
          <canvas aria-label={`Rendered PDF page 1 of 1`} role="img" />
        </section>
      );
    },
  };
});

const PROJECT = "1".repeat(32);
const SESSION = "2".repeat(32);
const ARTIFACT = "3".repeat(32);
const VERSION = "4".repeat(32);
const VERSION_TWO = "7".repeat(32);
const MARKDOWN_TEXT = "# Synthetic artifact preview\n";
const MARKDOWN_BYTES = new TextEncoder().encode(MARKDOWN_TEXT).byteLength;

function content(payload: BlobPart, contentType: string, filename = "agent-artifact-33333333") {
  const blob = new Blob([payload], { type: contentType });
  return { blob, contentType, filename, byteSize: blob.size };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

function artifact(overrides: Partial<AgentArtifact> = {}): AgentArtifact {
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: ARTIFACT,
    project_id: PROJECT,
    session_id: SESSION,
    title: "example.md",
    kind: "markdown",
    path: "docs/example.md",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:00:00Z",
    revision: 1,
    version_count: 1,
    availability: "unchecked",
    lifecycle_state: "active",
    archived_at: null,
    removed_at: null,
    latest_version: {
      contract_version: "agent-artifact.v3",
      version_id: VERSION,
      artifact_id: ARTIFACT,
      version_number: 1,
      created_at: "2040-01-01T10:00:00Z",
      path: "docs/example.md",
      media_type: "text/markdown; charset=utf-8",
      preview_kind: "text",
      provenance: "reviewed_write",
      sha256: "5".repeat(64),
      byte_size: MARKDOWN_BYTES,
      source_turn_id: "6".repeat(32),
      source_event_seq: 7,
    },
    ...overrides,
  };
}

function detail(overrides: Partial<AgentArtifactDetail> = {}): AgentArtifactDetail {
  const head = artifact({ availability: "available", ...overrides });
  return { ...head, versions: [head.latest_version], ...overrides };
}

function mediaDetail({
  byteSize,
  kind,
  mediaType,
  path,
}: {
  byteSize: number;
  kind: "image" | "pdf";
  mediaType: "image/png" | "application/pdf";
  path: string;
}): AgentArtifactDetail {
  const latest = {
    ...artifact().latest_version,
    path,
    media_type: mediaType,
    preview_kind: kind,
    provenance: "verified_output" as const,
    byte_size: byteSize,
    source_turn_id: null,
    source_event_seq: null,
  };
  const head = artifact({
    availability: "available",
    title: path,
    kind,
    path,
    latest_version: latest,
  });
  return { ...head, availability: "available", versions: [latest] };
}

function documentDetail(
  format: "docx" | "xlsx" = "docx",
): AgentArtifactDetail {
  const path = format === "docx" ? "docs/synthetic-review.docx" : "data/synthetic-budget.xlsx";
  const mediaType = format === "docx"
    ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" as const
    : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" as const;
  const latest = {
    ...artifact().latest_version,
    path,
    media_type: mediaType,
    preview_kind: "document" as const,
    byte_size: 512,
  };
  const head = artifact({
    availability: "available",
    title: path.split("/").at(-1) ?? path,
    kind: "document",
    path,
    latest_version: latest,
  });
  return { ...head, availability: "available", versions: [latest] };
}

function documentPreview(
  source: AgentArtifactDetail,
  overrides: Partial<AgentDocumentPreview> = {},
): AgentDocumentPreview {
  return {
    contract_version: "agent-document-preview.v1",
    project_id: PROJECT,
    session_id: SESSION,
    artifact_id: ARTIFACT,
    version_id: source.latest_version.version_id,
    source_sha256: source.latest_version.sha256,
    source_byte_size: source.latest_version.byte_size,
    format: "docx",
    sections: [{
      index: 1,
      kind: "document",
      title: "Document",
      paragraphs: ["Synthetic design note"],
      rows: [{ cells: ["Status", "Reviewed"] }],
      truncated: false,
    }],
    omitted_features: ["media", "comments"],
    truncated: true,
    ...overrides,
  };
}

function lineageExport(
  source: AgentArtifactDetail = detail(),
  version = source.latest_version,
): AgentArtifactExport {
  return {
    contract_version: "agent-artifact-export.v1",
    exported_at: "2040-01-01T10:04:00Z",
    artifact: source,
    selected_version: version,
    evidence: {
      verification: "exact_current_workspace_readback",
      algorithm: "sha256",
      sha256: version.sha256,
      byte_size: version.byte_size,
      verified: true,
    },
    content_included: false,
    absolute_path_included: false,
    sensitivity: "sensitive_local_metadata",
  };
}

function renderPanel(overrides: {
  artifacts?: AgentArtifact[];
  counts?: AgentArtifactLifecycleCounts | null;
  getDetail?: PromptEnhancerTransport["getAgentArtifact"];
  exportArtifact?: PromptEnhancerTransport["exportAgentArtifact"];
  exportAvailable?: boolean;
  getDocumentPreview?: PromptEnhancerTransport["getAgentArtifactDocumentPreview"];
  getContent?: PromptEnhancerTransport["getAgentArtifactContent"];
  removeArtifact?: PromptEnhancerTransport["removeAgentArtifact"];
  updateArtifact?: PromptEnhancerTransport["updateAgentArtifact"];
  onCaptureCurrent?: (path: string) => void;
  onOpenFile?: (path: string) => void;
  onOpenSourceTurn?: (turnId: string) => boolean;
  onViewerReady?: () => void;
  onRevealFile?: (path: string) => void;
  onReviewChanges?: (path: string) => void;
  onRefresh?: () => void;
  onViewChange?: (view: "active" | "archived" | "removed") => void;
  openRequest?: {
    projectId: string;
    sessionId: string;
    artifactId: string;
    path: string;
    requestId: number;
  } | null;
  userPresenceAvailable?: boolean;
  view?: "active" | "archived" | "removed";
} = {}) {
  const getDetail = vi.fn<PromptEnhancerTransport["getAgentArtifact"]>(
    overrides.getDetail ?? (async () => detail()),
  );
  const getContent = vi.fn<PromptEnhancerTransport["getAgentArtifactContent"]>(
    overrides.getContent ?? (async () => ({
      ...content(MARKDOWN_TEXT, "text/plain"),
      contentType: "text/plain; charset=utf-8",
    })),
  );
  const exportArtifact = vi.fn<PromptEnhancerTransport["exportAgentArtifact"]>(
    overrides.exportArtifact ?? (async () => lineageExport()),
  );
  const getDocumentPreview = vi.fn<PromptEnhancerTransport["getAgentArtifactDocumentPreview"]>(
    overrides.getDocumentPreview ?? (async () => {
      throw new Error("Unexpected document preview request");
    }),
  );
  const artifacts = overrides.artifacts ?? [artifact()];
  const updateArtifact = vi.fn<PromptEnhancerTransport["updateAgentArtifact"]>(
    overrides.updateArtifact ?? (async () => artifact()),
  );
  const removeArtifact = vi.fn<PromptEnhancerTransport["removeAgentArtifact"]>(
    overrides.removeArtifact ?? (async () => artifact({
      lifecycle_state: "removed",
      archived_at: "2040-01-01T10:01:00Z",
      removed_at: "2040-01-01T10:02:00Z",
      updated_at: "2040-01-01T10:02:00Z",
      revision: 3,
    })),
  );
  const inferredCounts = artifacts.reduce<AgentArtifactLifecycleCounts>((result, item) => ({
    ...result,
    [item.lifecycle_state]: result[item.lifecycle_state] + 1,
    total: result.total + 1,
  }), { active: 0, archived: 0, removed: 0, total: 0 });
  const transport = {
    getAgentArtifact: getDetail,
    getAgentArtifactContent: getContent,
    getAgentArtifactDocumentPreview: getDocumentPreview,
    removeAgentArtifact: removeArtifact,
    updateAgentArtifact: updateArtifact,
    ...(overrides.exportAvailable === false ? {} : { exportAgentArtifact: exportArtifact }),
  };
  const panel = (projectId = PROJECT, sessionId = SESSION) => (
    <AgentArtifactsPanel
      artifacts={artifacts}
      counts={overrides.counts === undefined ? inferredCounts : overrides.counts}
      error=""
      loading={false}
      onCaptureCurrent={overrides.onCaptureCurrent}
      onOpenFile={overrides.onOpenFile}
      onOpenSourceTurn={overrides.onOpenSourceTurn}
      onViewerReady={overrides.onViewerReady}
      onRevealFile={overrides.onRevealFile}
      onRefresh={overrides.onRefresh ?? vi.fn()}
      onReviewChanges={overrides.onReviewChanges}
      onViewChange={overrides.onViewChange ?? vi.fn()}
      openRequest={overrides.openRequest}
      projectId={projectId}
      sessionId={sessionId}
      transport={transport}
      userPresenceAvailable={overrides.userPresenceAvailable ?? true}
      view={overrides.view ?? "active"}
    />
  );
  const rendered = render(panel());
  return {
    exportArtifact,
    getDetail,
    getDocumentPreview,
    getContent,
    rerenderScope: (projectId: string, sessionId: string) => rendered.rerender(panel(projectId, sessionId)),
    removeArtifact,
    unmount: rendered.unmount,
    updateArtifact,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentArtifactsPanel", () => {
  it("keeps a maximum returned artifact collection on exact bounded pages", () => {
    const artifacts = Array.from({ length: 120 }, (_, index) => {
      const artifactId = (index + 10).toString(16).padStart(32, "0");
      const versionId = (index + 500).toString(16).padStart(32, "0");
      return artifact({
        artifact_id: artifactId,
        title: `Synthetic artifact ${index.toString().padStart(3, "0")}`,
        path: `output/artifact-${index.toString().padStart(3, "0")}.md`,
        latest_version: {
          ...artifact().latest_version,
          artifact_id: artifactId,
          version_id: versionId,
          path: `output/artifact-${index.toString().padStart(3, "0")}.md`,
        },
      });
    });
    renderPanel({ artifacts });

    expect(screen.getAllByRole("article")).toHaveLength(50);
    expect(screen.getByText("Showing 1–50 of 120")).toBeVisible();
    expect(screen.getByText("Synthetic artifact 000")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing 51–100 of 120")).toBeVisible();
    expect(screen.queryByText("Synthetic artifact 000")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic artifact 050")).toBeVisible();
  });

  it("opens the exact producing turn and reports when retained history cannot supply it", () => {
    const onOpenSourceTurn = vi.fn<(turnId: string) => boolean>()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);
    renderPanel({ onOpenSourceTurn });

    const source = screen.getByRole("button", { name: "Go to producing turn for example.md" });
    fireEvent.click(source);
    expect(onOpenSourceTurn).toHaveBeenCalledExactlyOnceWith("6".repeat(32));
    expect(screen.queryByText(/not available in the loaded chat history/u)).not.toBeInTheDocument();

    fireEvent.click(source);
    expect(onOpenSourceTurn).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/not available in the loaded chat history/u)).toHaveAttribute("role", "status");
  });

  it("opens the exact artifact requested by a reviewed-path card", async () => {
    const getDetail = vi.fn().mockResolvedValue(detail());
    renderPanel({
      getDetail,
      openRequest: {
        projectId: PROJECT,
        sessionId: SESSION,
        artifactId: ARTIFACT,
        path: "docs/example.md",
        requestId: 17,
      },
    });

    expect(await screen.findByRole("dialog", { name: "example.md" })).toBeVisible();
    expect(getDetail).toHaveBeenCalledExactlyOnceWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      expect.any(AbortSignal),
    );
  });

  it("ignores an artifact-open request owned by another chat", async () => {
    const getDetail = vi.fn().mockResolvedValue(detail());
    renderPanel({
      getDetail,
      openRequest: {
        projectId: PROJECT,
        sessionId: "8".repeat(32),
        artifactId: ARTIFACT,
        path: "docs/example.md",
        requestId: 18,
      },
    });
    expect(screen.getByRole("button", { name: "Preview example.md" })).toBeVisible();
    await Promise.resolve();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(getDetail).not.toHaveBeenCalled();
  });

  it("renders a bounded Office projection and routes owned-file actions without fetching raw bytes", async () => {
    const source = documentDetail();
    const getContent = vi.fn();
    const onRevealFile = vi.fn();
    const onReviewChanges = vi.fn();
    const createObjectURL = vi.spyOn(URL, "createObjectURL");
    const getDocumentPreview = vi.fn().mockResolvedValue(documentPreview(source));
    renderPanel({
      artifacts: [source],
      getDetail: vi.fn().mockResolvedValue(source),
      getDocumentPreview,
      getContent,
      onRevealFile,
      onReviewChanges,
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-review.docx" }));
    expect(await screen.findByRole("region", {
      name: "Word document preview of synthetic-review.docx v1",
    })).toBeVisible();
    expect(screen.getByText("Synthetic design note")).toBeVisible();
    expect(screen.getByRole("table", { name: "Document table projection" })).toHaveTextContent("StatusReviewed");
    expect(screen.getByText("Not rendered: images and media, comments.")).toBeVisible();
    expect(screen.getByText(/bounded preview is truncated/u)).toBeVisible();
    expect(getDocumentPreview).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      source.latest_version,
      expect.any(AbortSignal),
    );
    expect(getContent).not.toHaveBeenCalled();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Open current file" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reveal in files" }));
    expect(onRevealFile).toHaveBeenCalledExactlyOnceWith("docs/synthetic-review.docx");

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-review.docx" }));
    expect(await screen.findByRole("region", {
      name: "Word document preview of synthetic-review.docx v1",
    })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(onReviewChanges).toHaveBeenCalledExactlyOnceWith("docs/synthetic-review.docx");
  });

  it("navigates a multi-sheet workbook without creating links or executable DOM", async () => {
    const source = documentDetail("xlsx");
    const preview = documentPreview(source, {
      format: "xlsx",
      omitted_features: ["external_links", "macros"],
      truncated: false,
      sections: [
        {
          index: 1,
          kind: "sheet",
          title: "Overview",
          paragraphs: [],
          rows: [{ cells: ["Metric", "Value"] }],
          truncated: false,
        },
        {
          index: 2,
          kind: "sheet",
          title: "Budget",
          paragraphs: [],
          rows: [{ cells: ["Synthetic total", "42"] }],
          truncated: false,
        },
      ],
    });
    renderPanel({
      artifacts: [source],
      getDetail: vi.fn().mockResolvedValue(source),
      getDocumentPreview: vi.fn().mockResolvedValue(preview),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-budget.xlsx" }));
    expect(await screen.findByRole("region", {
      name: "Excel workbook preview of synthetic-budget.xlsx v1",
    })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Budget/u }));
    expect(await screen.findByRole("table", { name: "Budget table projection" })).toHaveTextContent("Synthetic total42");
    expect(document.querySelector("a")).toBeNull();
    expect(document.querySelector("iframe")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });

  it("keeps exact document download available when safe projection fails", async () => {
    const source = documentDetail();
    const getContent = vi.fn();
    renderPanel({
      artifacts: [source],
      getDetail: vi.fn().mockResolvedValue(source),
      getDocumentPreview: vi.fn().mockRejectedValue(Object.assign(
        new Error("synthetic malformed XML"),
        { status: 422 },
      )),
      getContent,
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-review.docx" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be rendered as a bounded document preview",
    );
    expect(screen.getByRole("button", { name: "Download v1" })).toBeEnabled();
    expect(getContent).not.toHaveBeenCalled();
  });

  it("shows provenance cards and lazily revalidates an inert text preview", async () => {
    const onOpenFile = vi.fn();
    const onViewerReady = vi.fn();
    const { getDetail, getContent } = renderPanel({ onOpenFile, onViewerReady });
    expect(screen.getByText("Artifacts · 1")).toBeVisible();
    expect(screen.getByText(`Reviewed write · event 7 · v1 · rev 1 · ${MARKDOWN_BYTES} B`)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
    expect(getDetail).toHaveBeenCalledWith(PROJECT, SESSION, ARTIFACT, expect.any(AbortSignal));
    expect(getContent).toHaveBeenCalledWith(PROJECT, SESSION, ARTIFACT, VERSION, false, expect.any(AbortSignal));
    expect(onViewerReady).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Open current file" }));
    expect(onOpenFile).toHaveBeenCalledExactlyOnceWith("docs/example.md");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("labels a reviewed move and routes current-file actions to its new path", async () => {
    const first = artifact().latest_version;
    const moved = {
      ...first,
      version_id: VERSION_TWO,
      version_number: 2,
      created_at: "2040-01-01T10:05:00Z",
      path: "archive/example.md",
      provenance: "reviewed_move" as const,
      source_turn_id: null,
      source_event_seq: null,
    };
    const relocated = detail({
      path: moved.path,
      updated_at: moved.created_at,
      revision: 2,
      version_count: 2,
      latest_version: moved,
      versions: [first, moved],
    });
    const onOpenFile = vi.fn();
    const onReviewChanges = vi.fn();
    renderPanel({
      artifacts: [relocated],
      getDetail: vi.fn().mockResolvedValue(relocated),
      onOpenFile,
      onReviewChanges,
    });

    expect(screen.getByText(`Reviewed move · v2 · rev 2 · ${MARKDOWN_BYTES} B`)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open current file" }));
    expect(onOpenFile).toHaveBeenCalledExactlyOnceWith("archive/example.md");

    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(onReviewChanges).toHaveBeenCalledExactlyOnceWith("archive/example.md");
  });

  it("browses immutable version lineage and refuses historical bytes that no longer match", async () => {
    const first = artifact().latest_version;
    const latestText = "# Second revision\n";
    const latestBytes = new TextEncoder().encode(latestText).byteLength;
    const latest = {
      ...first,
      version_id: VERSION_TWO,
      version_number: 2,
      created_at: "2040-01-01T10:05:00Z",
      sha256: "8".repeat(64),
      byte_size: latestBytes,
      source_event_seq: 9,
    };
    const history = detail({
      revision: 2,
      version_count: 2,
      latest_version: latest,
      versions: [first, latest],
    });
    const getContent = vi.fn<PromptEnhancerTransport["getAgentArtifactContent"]>(
      async (_projectId, _sessionId, _artifactId, versionId) => {
        if (versionId === VERSION) {
          throw Object.assign(new Error("synthetic historical digest mismatch"), { status: 409 });
        }
        return {
          blob: new Blob([latestText], { type: "text/plain" }),
          contentType: "text/plain; charset=utf-8",
          filename: "agent-artifact-33333333",
          byteSize: latestBytes,
        };
      },
    );
    renderPanel({
      artifacts: [history],
      getDetail: vi.fn().mockResolvedValue(history),
      getContent,
      onOpenFile: vi.fn(),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Second revision" })).toBeVisible();
    expect(screen.getByLabelText("Artifact version")).toHaveValue(VERSION_TWO);
    expect(screen.getByText("v2 of 2")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download v2" })).toBeEnabled();

    const previewCalls = getContent.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Compare versions" }));
    const comparison = screen.getByRole("region", { name: "Artifact version metadata comparison" });
    expect(comparison).toHaveTextContent("Recorded lineage comparison");
    expect(comparison).toHaveTextContent("v1 → v2");
    expect(comparison).toHaveTextContent("Digest changed");
    expect(comparison).toHaveTextContent("Metadata comparison only");
    expect(screen.getByLabelText("Comparison artifact version")).toHaveValue(VERSION);
    expect(getContent).toHaveBeenCalledTimes(previewCalls);

    fireEvent.change(screen.getByLabelText("Artifact version"), { target: { value: VERSION } });
    expect(await screen.findByText(/current workspace bytes do not match recorded v1/u)).toBeVisible();
    expect(getContent).toHaveBeenCalledWith(
      PROJECT, SESSION, ARTIFACT, VERSION, false, expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: "Download v1" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Open current file" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Comparison artifact version")).toHaveValue(VERSION_TWO);

    fireEvent.change(screen.getByLabelText("Artifact version"), { target: { value: VERSION_TWO } });
    expect(await screen.findByRole("heading", { name: "Second revision" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open current file" })).toBeVisible();
  });

  it("renders Markdown structure while keeping HTML, links and remote images inert", async () => {
    const markdown = [
      "# Verified review",
      "",
      "[External reference](https://example.invalid/private-query)",
      "",
      "![Remote pixel](https://example.invalid/pixel.png)",
      "",
      "<script>globalThis.syntheticBad = true</script>",
    ].join("\n");
    const markdownBytes = new TextEncoder().encode(markdown).byteLength;
    const markdownVersion = { ...artifact().latest_version, byte_size: markdownBytes };
    const markdownDetail = detail({ latest_version: markdownVersion, versions: [markdownVersion] });
    renderPanel({
      artifacts: [{ ...artifact(), latest_version: markdownVersion }],
      getDetail: vi.fn().mockResolvedValue(markdownDetail),
      getContent: vi.fn().mockResolvedValue({
        blob: new Blob([markdown], { type: "text/plain" }),
        contentType: "text/plain; charset=utf-8",
        filename: "agent-artifact-33333333",
        byteSize: markdownBytes,
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    const rendered = await screen.findByRole("article", { name: "Rendered Markdown artifact" });
    expect(rendered).toContainElement(screen.getByRole("heading", { name: "Verified review" }));
    expect(rendered.querySelector("a")).toBeNull();
    expect(rendered.querySelector("img")).toBeNull();
    expect(rendered.querySelector("script")).toBeNull();
    expect(screen.getByText("External reference")).toHaveAttribute(
      "title",
      "Links stay inert in verified artifact previews",
    );
    expect(screen.getByText("Remote image omitted: Remote pixel")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByRole("button", { name: "Source" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Markdown source")).toHaveTextContent("https://example.invalid/private-query");
    expect(document.querySelector("script")).toBeNull();
  });

  it("does not fetch or download bytes when the recorded workspace revision is stale", async () => {
    const stale = detail({ availability: "stale" });
    const getContent = vi.fn();
    const onViewerReady = vi.fn();
    renderPanel({
      getDetail: vi.fn().mockResolvedValue(stale),
      getContent,
      onViewerReady,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByText(/changed after this version was recorded/u)).toBeVisible();
    expect(getContent).not.toHaveBeenCalled();
    expect(onViewerReady).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Download v1" })).toBeDisabled();
  });

  it("keeps download-only active content inert and downloads only on an explicit click", async () => {
    const activeDocument = "<script>synthetic()</script>";
    const activeDocumentBytes = new TextEncoder().encode(activeDocument).byteLength;
    const downloadOnly = detail({
      kind: "document",
      path: "report.html",
      title: "report.html",
      latest_version: {
        ...artifact().latest_version,
        path: "report.html",
        media_type: "application/octet-stream",
        preview_kind: "download_only",
        provenance: "verified_output",
        byte_size: activeDocumentBytes,
        source_turn_id: null,
        source_event_seq: null,
      },
    });
    downloadOnly.versions = [downloadOnly.latest_version];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-download");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const getContent = vi.fn().mockResolvedValue({
      blob: new Blob([activeDocument], { type: "application/octet-stream" }),
      contentType: "application/octet-stream",
      filename: "agent-artifact-33333333.html",
      byteSize: activeDocumentBytes,
    });
    renderPanel({
      artifacts: [artifact({ title: "report.html", kind: "document", path: "report.html", latest_version: downloadOnly.latest_version })],
      getDetail: vi.fn().mockResolvedValue(downloadOnly),
      getContent,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview report.html" }));
    expect(await screen.findByText(/stays inert in the app/u)).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(getContent).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Download v1" }));
    await waitFor(() => expect(getContent).toHaveBeenCalledWith(
      PROJECT, SESSION, ARTIFACT, VERSION, true, expect.any(AbortSignal),
    ));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-download"));
  });

  it("exports exact-readback lineage JSON separately from artifact bytes", async () => {
    const source = detail();
    const exportArtifact = vi.fn<PromptEnhancerTransport["exportAgentArtifact"]>(
      async () => lineageExport(source),
    );
    let downloadedName = "";
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloadedName = this.download;
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-lineage");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderPanel({ exportArtifact, getDetail: vi.fn().mockResolvedValue(source) });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export lineage v1" }));

    await waitFor(() => expect(exportArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      { expected_revision: 1, version_id: VERSION },
      expect.any(AbortSignal),
    ));
    expect(click).toHaveBeenCalledOnce();
    expect(downloadedName).toBe("agent-artifact-33333333-v1-lineage.json");
    const exportedBlob = createObjectURL.mock.calls[0]?.[0];
    expect(exportedBlob).toBeInstanceOf(Blob);
    const exportedText = await (exportedBlob as Blob).text();
    const exportedJson = JSON.parse(exportedText) as Record<string, unknown>;
    expect(exportedJson).toMatchObject({
      contract_version: "agent-artifact-export.v1",
      content_included: false,
      absolute_path_included: false,
      sensitivity: "sensitive_local_metadata",
    });
    expect(exportedText).not.toContain(MARKDOWN_TEXT.trim());
    expect(exportedText).not.toMatch(/[A-Za-z]:\\/u);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "contains sensitive metadata, but no artifact bytes or absolute workspace path",
    );
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-lineage"));
  });

  it("keeps preview and raw download usable when lineage export is unavailable", async () => {
    renderPanel({ exportAvailable: false });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));

    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Download v1" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Export lineage v1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export lineage v1" })).toHaveAttribute(
      "title",
      "Lineage export is unavailable in this app transport.",
    );
  });

  it("refuses contradictory lineage exports before creating a local file", async () => {
    const source = detail();
    const contradictory = {
      ...lineageExport(source),
      content_included: true,
    } as unknown as AgentArtifactExport;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const createObjectURL = vi.spyOn(URL, "createObjectURL");
    renderPanel({
      exportArtifact: vi.fn().mockResolvedValue(contradictory),
      getDetail: vi.fn().mockResolvedValue(source),
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export lineage v1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "lineage export did not match recorded v1 identity, revision, digest, size, or privacy flags",
    );
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Export lineage v1" })).toBeDisabled();
  });

  it("keeps a revision-conflicted lineage export recoverable and asks for refresh", async () => {
    const source = detail();
    renderPanel({
      exportArtifact: vi.fn().mockRejectedValue(
        new TransportError("Synthetic revision conflict", 409, "agent_artifact_revision_conflict"),
      ),
      getDetail: vi.fn().mockResolvedValue(source),
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export lineage v1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "changed in another view. Refresh its lineage before exporting",
    );
    expect(screen.getByRole("button", { name: "Export lineage v1" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();
  });

  it("reports a failed explicit download without changing the workspace", async () => {
    const getContent = vi.fn().mockResolvedValue({
      blob: new Blob(["# Synthetic artifact preview\n"], { type: "text/plain" }),
      contentType: "text/plain; charset=utf-8",
      filename: "agent-artifact-33333333",
      byteSize: 29,
    });
    renderPanel({ getContent });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();

    getContent.mockRejectedValueOnce(new Error("synthetic download failure"));
    fireEvent.click(screen.getByRole("button", { name: "Download v1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This verified version could not be prepared for download. The workspace was not changed.",
    );
    expect(screen.getByRole("button", { name: "Download v1" })).toBeEnabled();
  });

  it("invalidates a verified preview when explicit download discovers workspace staleness", async () => {
    const getContent = vi.fn<PromptEnhancerTransport["getAgentArtifactContent"]>()
      .mockResolvedValueOnce({
        ...content(MARKDOWN_TEXT, "text/plain"),
        contentType: "text/plain; charset=utf-8",
      })
      .mockRejectedValueOnce(Object.assign(new Error("synthetic digest mismatch"), { status: 409 }));
    renderPanel({ getContent });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Download v1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current workspace bytes do not match recorded v1",
    );
    expect(screen.queryByRole("heading", { name: "Synthetic artifact preview" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download v1" })).toBeDisabled();
    expect(getContent).toHaveBeenLastCalledWith(
      PROJECT, SESSION, ARTIFACT, VERSION, true, expect.any(AbortSignal),
    );
  });

  it("aborts and ignores a late explicit download when project or chat scope changes", async () => {
    const pending = deferred<AgentArtifactContent>();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-late-download");
    const getContent = vi.fn<PromptEnhancerTransport["getAgentArtifactContent"]>(
      async (_projectId, _sessionId, _artifactId, _versionId, download) => download
        ? pending.promise
        : {
            ...content(MARKDOWN_TEXT, "text/plain"),
            contentType: "text/plain; charset=utf-8",
          },
    );
    const { rerenderScope } = renderPanel({ getContent });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Download v1" }));

    await waitFor(() => expect(getContent.mock.calls.some((call) => call[4] === true)).toBe(true));
    const downloadCall = getContent.mock.calls.find((call) => call[4] === true);
    const signal = downloadCall?.[5];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    rerenderScope("9".repeat(32), SESSION);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(signal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve(content(MARKDOWN_TEXT, "application/octet-stream"));
      await pending.promise;
      await Promise.resolve();
    });
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
  });

  it("aborts and ignores a late explicit download when the viewer closes", async () => {
    const pending = deferred<AgentArtifactContent>();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-closed-download");
    const getContent = vi.fn<PromptEnhancerTransport["getAgentArtifactContent"]>(
      async (_projectId, _sessionId, _artifactId, _versionId, download) => download
        ? pending.promise
        : {
            ...content(MARKDOWN_TEXT, "text/plain"),
            contentType: "text/plain; charset=utf-8",
          },
    );
    renderPanel({ getContent });
    fireEvent.click(screen.getByRole("button", { name: "Preview example.md" }));
    expect(await screen.findByRole("heading", { name: "Synthetic artifact preview" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Download v1" }));

    await waitFor(() => expect(getContent.mock.calls.some((call) => call[4] === true)).toBe(true));
    const downloadCall = getContent.mock.calls.find((call) => call[4] === true);
    const signal = downloadCall?.[5];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Close artifact viewer" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(signal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve(content(MARKDOWN_TEXT, "application/octet-stream"));
      await pending.promise;
      await Promise.resolve();
    });
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
  });

  it("shows a truthful image decode state, provides fit and zoom controls, and releases its URL on close", async () => {
    const imageBytes = new Uint8Array([137, 80, 78, 71]);
    const image = mediaDetail({
      byteSize: imageBytes.byteLength,
      kind: "image",
      mediaType: "image/png",
      path: "synthetic-pixel.png",
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-image");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderPanel({
      artifacts: [image],
      getDetail: vi.fn().mockResolvedValue(image),
      getContent: vi.fn().mockResolvedValue(content(
        imageBytes,
        "image/png",
        "agent-artifact-33333333.png",
      )),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-pixel.png" }));
    const previewImage = await screen.findByRole("img", {
      name: "Preview of synthetic-pixel.png v1",
    });
    expect(screen.getByRole("status")).toHaveTextContent("Decoding the verified image preview");
    expect(screen.getByRole("button", { name: "Zoom in image" })).toBeDisabled();

    fireEvent.load(previewImage);
    await waitFor(() => expect(screen.queryByText(/Decoding the verified image preview/u)).not.toBeInTheDocument());
    expect(screen.getByRole("region", { name: "Image preview of synthetic-pixel.png v1" })).toHaveAttribute("data-state", "ready");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in image" }));
    expect(screen.getByRole("button", { name: "Fit image to viewer" })).toHaveTextContent("125%");
    expect(previewImage).toHaveStyle({ width: "125%" });
    fireEvent.click(screen.getByRole("button", { name: "Fit image to viewer" }));
    expect(previewImage).toHaveStyle({ width: "100%" });

    fireEvent.click(screen.getByRole("button", { name: "Close artifact viewer" }));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:synthetic-image"));
    expect(createObjectURL).toHaveBeenCalledOnce();
  });

  it("reports image decode failure without substituting content and keeps explicit download available", async () => {
    const imageBytes = new Uint8Array([137, 80, 78, 71]);
    const image = mediaDetail({
      byteSize: imageBytes.byteLength,
      kind: "image",
      mediaType: "image/png",
      path: "synthetic-invalid.png",
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-invalid-image");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const onViewerReady = vi.fn();
    renderPanel({
      artifacts: [image],
      getDetail: vi.fn().mockResolvedValue(image),
      getContent: vi.fn().mockResolvedValue(content(
        imageBytes,
        "image/png",
        "agent-artifact-33333333.png",
      )),
      onViewerReady,
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-invalid.png" }));
    const previewImage = await screen.findByRole("img", {
      name: "Preview of synthetic-invalid.png v1",
    });
    fireEvent.error(previewImage);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be decoded in the viewer");
    expect(screen.getByText(/preview failed · 4 B · v1/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Download v1" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Zoom in image" })).toBeDisabled();
    expect(onViewerReady).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close artifact viewer" }));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-invalid-image"));
  });

  it("hands verified PDF bytes to the local canvas renderer without creating a browser URL", async () => {
    const pdfBytes = new TextEncoder().encode("%PDF-1.7\n%%EOF\n");
    const pdf = mediaDetail({
      byteSize: pdfBytes.byteLength,
      kind: "pdf",
      mediaType: "application/pdf",
      path: "synthetic-report.pdf",
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:must-not-be-used-for-pdf");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderPanel({
      artifacts: [pdf],
      getDetail: vi.fn().mockResolvedValue(pdf),
      getContent: vi.fn().mockResolvedValue(content(
        pdfBytes,
        "application/pdf",
        "agent-artifact-33333333.pdf",
      )),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-report.pdf" }));
    expect(await screen.findByRole("region", { name: "PDF preview of synthetic-report.pdf v1" })).toHaveAttribute("data-state", "ready");
    expect(screen.getByRole("img", { name: "Rendered PDF page 1 of 1" })).toBeVisible();
    expect(createObjectURL).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Close artifact viewer" }));
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });

  it("fails closed before creating a URL when returned media metadata does not match the selected version", async () => {
    const imageBytes = new Uint8Array([137, 80, 78, 71]);
    const image = mediaDetail({
      byteSize: imageBytes.byteLength,
      kind: "image",
      mediaType: "image/png",
      path: "synthetic-mismatch.png",
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:must-not-exist");
    renderPanel({
      artifacts: [image],
      getDetail: vi.fn().mockResolvedValue(image),
      getContent: vi.fn().mockResolvedValue(content(
        imageBytes,
        "application/pdf",
        "agent-artifact-33333333.pdf",
      )),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-mismatch.png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "did not match its declared media type, size, or safe filename",
    );
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download v1" })).toBeDisabled();
  });

  it("revokes each image URL when versions change and when the viewer unmounts", async () => {
    const imageBytes = new Uint8Array([137, 80, 78, 71]);
    const first = mediaDetail({
      byteSize: imageBytes.byteLength,
      kind: "image",
      mediaType: "image/png",
      path: "synthetic-lineage.png",
    }).latest_version;
    const latest = {
      ...first,
      version_id: VERSION_TWO,
      version_number: 2,
      created_at: "2040-01-01T10:05:00Z",
      sha256: "8".repeat(64),
    };
    const history = detail({
      title: "synthetic-lineage.png",
      kind: "image",
      path: "synthetic-lineage.png",
      revision: 2,
      version_count: 2,
      latest_version: latest,
      versions: [first, latest],
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL")
      .mockReturnValueOnce("blob:synthetic-image-v2")
      .mockReturnValueOnce("blob:synthetic-image-v1");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const { unmount } = renderPanel({
      artifacts: [history],
      getDetail: vi.fn().mockResolvedValue(history),
      getContent: vi.fn().mockResolvedValue(content(
        imageBytes,
        "image/png",
        "agent-artifact-33333333.png",
      )),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-lineage.png" }));
    const firstRendered = await screen.findByRole("img", { name: "Preview of synthetic-lineage.png v2" });
    fireEvent.load(firstRendered);
    fireEvent.change(screen.getByLabelText("Artifact version"), { target: { value: VERSION } });
    const secondRendered = await screen.findByRole("img", { name: "Preview of synthetic-lineage.png v1" });
    fireEvent.load(secondRendered);
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-image-v2"));
    expect(createObjectURL).toHaveBeenCalledTimes(2);

    unmount();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-image-v1"));
  });

  it("closes and releases an artifact viewer immediately when project or chat scope changes", async () => {
    const imageBytes = new Uint8Array([137, 80, 78, 71]);
    const image = mediaDetail({
      byteSize: imageBytes.byteLength,
      kind: "image",
      mediaType: "image/png",
      path: "synthetic-scoped.png",
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-scoped-image");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const { rerenderScope } = renderPanel({
      artifacts: [image],
      getDetail: vi.fn().mockResolvedValue(image),
      getContent: vi.fn().mockResolvedValue(content(
        imageBytes,
        "image/png",
        "agent-artifact-33333333.png",
      )),
    });

    fireEvent.click(screen.getByRole("button", { name: "Preview synthetic-scoped.png" }));
    expect(await screen.findByRole("img", { name: "Preview of synthetic-scoped.png v1" })).toBeInTheDocument();
    rerenderScope("9".repeat(32), SESSION);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:synthetic-scoped-image"));
  });

  it("keeps keyboard focus inside the viewer and restores it when closed", async () => {
    renderPanel({ onOpenFile: vi.fn() });
    const view = screen.getByRole("button", { name: "Preview example.md" });
    view.focus();
    fireEvent.click(view);
    const close = await screen.findByRole("button", { name: "Close artifact viewer" });
    await waitFor(() => expect(close).toHaveFocus());

    const download = await screen.findByRole("button", { name: "Download v1" });
    download.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(download).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(view).toHaveFocus());
  });

  it("reports an empty retained output set without inventing artifacts", () => {
    renderPanel({ artifacts: [] });
    expect(screen.getByText(/A model statement alone is not a created file/u)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Preview/u })).not.toBeInTheDocument();
  });

  it("switches explicit lifecycle views and reports truthful counts", () => {
    const onViewChange = vi.fn();
    const removed = artifact({
      lifecycle_state: "removed",
      archived_at: "2040-01-01T10:01:00Z",
      removed_at: "2040-01-01T10:02:00Z",
      updated_at: "2040-01-01T10:02:00Z",
      revision: 3,
    });
    renderPanel({
      artifacts: [removed],
      counts: { active: 2, archived: 1, removed: 1, total: 4 },
      onViewChange,
      view: "removed",
    });

    expect(screen.getByRole("tab", { name: "Active 2" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Removed 1" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Archived 1" }));
    expect(onViewChange).toHaveBeenCalledExactlyOnceWith("archived");
    expect(screen.queryByRole("button", { name: "Preview example.md" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage example.md" })).toBeEnabled();
  });

  it("renames only the display label with the exact optimistic revision", async () => {
    const onRefresh = vi.fn();
    const updateArtifact = vi.fn<PromptEnhancerTransport["updateAgentArtifact"]>()
      .mockResolvedValue(artifact({ title: "Reviewed plan", revision: 2 }));
    const { updateArtifact: update } = renderPanel({ onRefresh, updateArtifact });

    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    const name = await screen.findByLabelText("Display name");
    fireEvent.change(name, { target: { value: "Reviewed plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      { expected_revision: 1, operation: "rename", title: "Reviewed plan" },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/workspace path and version lineage were not changed/u)).toBeVisible();
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("archives and restores records without using the removal confirmation path", async () => {
    const updateArtifact = vi.fn<PromptEnhancerTransport["updateAgentArtifact"]>()
      .mockResolvedValue(artifact({
        lifecycle_state: "archived",
        archived_at: "2040-01-01T10:01:00Z",
        updated_at: "2040-01-01T10:01:00Z",
        revision: 2,
      }));
    const activePanel = renderPanel({ updateArtifact });
    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    fireEvent.click(await screen.findByRole("button", { name: "Archive record" }));
    await waitFor(() => expect(activePanel.updateArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      { expected_revision: 1, operation: "archive" },
      expect.any(AbortSignal),
    ));

    activePanel.unmount();
    const archived = artifact({
      lifecycle_state: "archived",
      archived_at: "2040-01-01T10:01:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 2,
    });
    const archivedPanel = renderPanel({ artifacts: [archived], view: "archived" });
    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    fireEvent.click(await screen.findByRole("button", { name: "Restore to Active" }));
    await waitFor(() => expect(archivedPanel.updateArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      { expected_revision: 2, operation: "restore" },
      expect.any(AbortSignal),
    ));
  });

  it("keeps removal disabled without native confirmation and otherwise sends the exact recoverable command", async () => {
    const archived = artifact({
      lifecycle_state: "archived",
      archived_at: "2040-01-01T10:01:00Z",
      updated_at: "2040-01-01T10:01:00Z",
      revision: 2,
    });
    const unavailable = renderPanel({
      artifacts: [archived],
      userPresenceAvailable: false,
      view: "archived",
    });
    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    expect(await screen.findByRole("button", { name: "Move record to Removed" })).toBeDisabled();
    expect(screen.getByText(/native confirmation is unavailable/u)).toBeVisible();
    expect(unavailable.removeArtifact).not.toHaveBeenCalled();

    unavailable.unmount();
    const available = renderPanel({ artifacts: [archived], view: "archived" });
    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    fireEvent.click(await screen.findByRole("button", { name: "Move record to Removed" }));
    await waitFor(() => expect(available.removeArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      {
        expected_revision: 2,
        confirmation: "move_archived_artifact_record_to_removed",
      },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/record is recoverable and no workspace file was deleted/u)).toBeVisible();
  });

  it("recovers Removed to Archived and fails stale revisions closed", async () => {
    const removed = artifact({
      lifecycle_state: "removed",
      archived_at: "2040-01-01T10:01:00Z",
      removed_at: "2040-01-01T10:02:00Z",
      updated_at: "2040-01-01T10:02:00Z",
      revision: 3,
    });
    const updateArtifact = vi.fn<PromptEnhancerTransport["updateAgentArtifact"]>()
      .mockRejectedValue(new TransportError("conflict", 409, "agent_artifact_revision_conflict"));
    const rendered = renderPanel({ artifacts: [removed], updateArtifact, view: "removed" });
    fireEvent.click(screen.getByRole("button", { name: "Manage example.md" }));
    fireEvent.click(await screen.findByRole("button", { name: "Recover to Archived" }));

    await waitFor(() => expect(rendered.updateArtifact).toHaveBeenCalledWith(
      PROJECT,
      SESSION,
      ARTIFACT,
      { expected_revision: 3, operation: "recover" },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed in another view");
    expect(screen.getByRole("dialog", { name: "Manage example.md" })).toBeVisible();
  });

  it("routes stale current bytes into the reviewed new-version flow", () => {
    const onCaptureCurrent = vi.fn();
    renderPanel({
      artifacts: [artifact({ availability: "stale" })],
      onCaptureCurrent,
    });

    fireEvent.click(screen.getByRole("button", { name: "Review current workspace file for example.md" }));
    expect(onCaptureCurrent).toHaveBeenCalledExactlyOnceWith("docs/example.md");
  });
});
