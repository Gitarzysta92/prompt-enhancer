import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DownloadStatus, LocalModelCompatibilityCatalog, LocalModelRecord, LocalModelStatus, LocalModelsOverview, LocalRuntimeCoordinatorStatus, PromptEnhancerTransport, RemoteRepoFiles } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { LocalModelsPage, provenanceLine, safeOverview } from "./LocalModelsPage";

const REVISION = "0123456789abcdef0123456789abcdef01234567";
const DIGEST = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

function model(state: LocalModelStatus["runtime"]["state"] = "stopped"): LocalModelStatus {
  return {
    record: {
      alias: "qwen-27b-q4", display_name: "Qwen 27B Q4", format: "gguf", path: "D:/models/qwen.gguf",
      source_repo: "example-org/Example-GGUF", source_file: "qwen-q4_k_m.gguf", size_bytes: 16 * 1024 ** 3,
      sha256: null, source_revision: null, source_license: null, source_license_policy: null, provenance_verified: false,
      default_device: "split", default_gpu_layers: null, context_size: 8192, layer_count: 64, added_at: "2026-03-04T09:00:00Z",
    },
    runtime: { state, device: state === "running" ? "split" : null, gpu_layers: state === "running" ? 52 : null, context_size: state === "running" ? 8192 : null, started_at: null, last_error_code: null, pid: null },
    placement: {
      contract_version: "local-model-placement.v1",
      alias: "qwen-27b-q4",
      context_size: 8192,
      gpu_memory_free_mb: 15000,
      actual_offload_verified: false,
      options: [
        { device: "gpu", state: "available", reason_code: "gpu_estimate_fits", recommended_gpu_layers: 64, estimated_vram_required_mb: 14000 },
        { device: "split", state: "available", reason_code: "split_estimate_available", recommended_gpu_layers: 52, estimated_vram_required_mb: 13000 },
        { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
      ],
    },
    endpoint_path: "/v1/local-models/qwen-27b-q4/chat/completions",
  };
}

function overview(models: LocalModelStatus[] = [model()], runtime = true): LocalModelsOverview {
  return {
    contract_version: "local-models.v1" as const,
    hardware: { gpu_name: "Example GPU", gpu_memory_mb: 16384, gpu_memory_free_mb: 15000, ram_mb: 32768, llama_server_path: runtime ? "C:/tools/llama-server.exe" : null, llama_server_version: runtime ? "b1234" : null },
    runtime_available: runtime,
    storage_root: "D:/example/local-models",
    storage_free_bytes: 64 * 1024 ** 3,
    download_reserve_bytes: 512 * 1024 ** 2,
    download_ledger_error_code: null,
    models,
    downloads: [],
  };
}

function download(state: DownloadStatus["state"] = "downloading"): DownloadStatus {
  return {
    download_id: DIGEST,
    repo_id: "example-org/Example-GGUF",
    filename: "qwen-q4_k_m.gguf",
    alias: "qwen-q4",
    state,
    bytes_total: 16 * 1024 ** 3,
    bytes_done: state === "completed" ? 16 * 1024 ** 3 : 4 * 1024 ** 3,
    error_code: state === "failed" ? "download_failed" : null,
    started_at: "2026-08-30T10:00:00Z",
    updated_at: "2026-08-30T10:01:00Z",
    finished_at: ["completed", "failed", "cancelled"].includes(state) ? "2026-08-30T10:01:00Z" : null,
    status_revision: 7,
    attempt: 1,
    disk_required_bytes: 17 * 1024 ** 3,
    disk_free_bytes_at_start: 64 * 1024 ** 3,
    partial_retained: ["paused", "failed", "interrupted"].includes(state),
    cleanup_confirmed: state === "cancelled" ? true : null,
    transfer_adapter_version: "synthetic-transfer.v1",
    revision: REVISION,
    sha256: DIGEST,
  };
}

function remoteFiles(overrides: Partial<RemoteRepoFiles> = {}): RemoteRepoFiles {
  return {
    repo_id: "example-org/Example-GGUF",
    revision: REVISION,
    revision_pinned: true,
    license_id: "apache-2.0",
    license_admission: "allowed",
    license_policy_version: "local-model-license-policy.v1",
    gated: false,
    unavailable_reason: null,
    files: [
      { filename: "qwen-q4_k_m.gguf", size_bytes: 16 * 1024 ** 3, sha256: DIGEST, eligible: true, ineligible_reason: null },
      { filename: "qwen-q8_0.gguf", size_bytes: 28 * 1024 ** 3, sha256: null, eligible: false, ineligible_reason: "digest_unavailable" },
    ],
    ...overrides,
  };
}

function secondModel(state: LocalModelStatus["runtime"]["state"] = "stopped"): LocalModelStatus {
  const value = model(state);
  return {
    ...value,
    record: {
      ...value.record,
      alias: "example-model-b",
      display_name: "Example Model B",
      path: "D:/models/example-b.gguf",
      source_file: "example-b-q4_k_m.gguf",
    },
    placement: { ...value.placement, alias: "example-model-b" },
    endpoint_path: "/v1/local-models/example-model-b/chat/completions",
  };
}

function runtimeStatus(
  alias: string | null = null,
  overrides: Partial<LocalRuntimeCoordinatorStatus> = {},
): LocalRuntimeCoordinatorStatus {
  const selection = alias === null ? null : {
    alias,
    device: "split" as const,
    gpu_layers: 52,
    context_size: 8192,
  };
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision: 7,
    state: alias === null ? "idle" : "ready",
    requested: selection,
    served: selection === null ? null : {
      ...selection,
      pid: 4242,
      started_at: "2040-01-01T10:00:00Z",
    },
    active_requests: 0,
    cleanup: {
      state: "not_required",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: null,
      gpu_memory_free_after_mb: null,
      gpu_memory_released_mb: null,
    },
    capabilities: {
      probe_version: "local-runtime-multimodal-probe.v2",
      state: alias === null ? "not_probed" : "verified",
      text: alias !== null,
      tools: alias !== null,
      structured_output: false,
      vision: false,
      audio: false,
      recording: false,
      error_code: null,
    },
    context: {
      state: "unknown",
      used_tokens: null,
      limit_tokens: selection?.context_size ?? null,
      requested_output_tokens: null,
      available_output_tokens: null,
      source: "runtime_limit_only",
      scope: "runtime_limit",
      policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: selection === null ? "runtime_not_served" : "no_request_measured",
    },
    last_error_code: null,
    ...overrides,
  };
}

function transportWithOverview(getLocalModels: PromptEnhancerTransport["getLocalModels"]) {
  return {
    getLocalModels,
    activateLocalModel: vi.fn(),
    deactivateLocalModel: vi.fn(),
    removeLocalModel: vi.fn(),
    getLocalModelRemoteFiles: vi.fn(),
    startLocalModelDownload: vi.fn(),
    addLocalModel: vi.fn(),
    streamLocalModelChat: vi.fn(),
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

function namedOverview(name: string, models: LocalModelStatus[] = [model()]): LocalModelsOverview {
  const value = overview(models);
  return { ...value, hardware: { ...value.hardware, gpu_name: name } };
}

describe("LocalModelsPage", () => {
  it.each(["resolve", "reject"] as const)("ignores a superseded repository lookup that later %ss", async (completion) => {
    const first = deferred<RemoteRepoFiles>();
    const second = deferred<RemoteRepoFiles>();
    const getLocalModelRemoteFiles = vi.fn((_repo: string, _signal?: AbortSignal) => (
      getLocalModelRemoteFiles.mock.calls.length === 1 ? first.promise : second.promise
    ));
    const transport = { ...transportWithOverview(vi.fn(async () => overview())), getLocalModelRemoteFiles };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "example-org/First-GGUF" } });
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "example-org/Second-GGUF" } });
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await act(async () => { second.resolve(remoteFiles({ revision: "b".repeat(40) })); await second.promise; });
    expect(screen.getByText("b".repeat(40))).toBeVisible();
    expect(getLocalModelRemoteFiles.mock.calls[0][1]?.aborted).toBe(true);
    await act(async () => {
      if (completion === "resolve") first.resolve(remoteFiles());
      else first.reject(new Error("example-lookup-failure"));
      await first.promise.catch(() => undefined);
    });
    expect(screen.getByText("b".repeat(40))).toBeVisible();
    expect(screen.queryByText(REVISION)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Hugging Face repository")).toHaveValue("example-org/Second-GGUF");
  });

  it("explains empty-input actions and removes each prerequisite once its field is ready", async () => {
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview())),
      scanLocalModelFolder: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "" } });

    const showFiles = screen.getByRole("button", { name: "Show files" });
    const scanFolder = screen.getByRole("button", { name: "Scan folder" });
    const register = screen.getByRole("button", { name: "Register" });
    expect(showFiles).toBeDisabled();
    expect(showFiles).toHaveAccessibleDescription(/enter a Hugging Face repository/i);
    expect(scanFolder).toBeDisabled();
    expect(scanFolder).toHaveAccessibleDescription(/enter a local model folder/i);
    expect(register).toBeDisabled();
    expect(register).toHaveAccessibleDescription(/enter the absolute path to a local GGUF file/i);

    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "example-org/Example-GGUF" } });
    fireEvent.change(screen.getByLabelText("Model folder"), { target: { value: "D:\\example\\models" } });
    fireEvent.change(screen.getByLabelText("Local GGUF path"), { target: { value: "D:\\example\\models\\example.gguf" } });
    expect(showFiles).toBeEnabled();
    expect(showFiles).not.toHaveAttribute("aria-describedby");
    expect(scanFolder).toBeEnabled();
    expect(scanFolder).not.toHaveAttribute("aria-describedby");
    expect(register).toBeEnabled();
    expect(register).not.toHaveAttribute("aria-describedby");
  });

  it("explains why an already registered starting point cannot be looked up again", async () => {
    const installed = model();
    installed.record = {
      ...installed.record,
      source_file: "Qwen3.8-27B-Uncensored-FP8.i1-IQ3_M.gguf",
    };
    render(<LocalModelsPage transport={transportWithOverview(vi.fn(async () => overview([installed])))} />);
    await screen.findByText("Example GPU");

    const button = screen.getByRole("button", { name: "Installed" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(/exact model file is already registered/i);
  });

  it("clears file and download consent details as soon as the repository input changes", async () => {
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview())),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles()),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByRole("button", { name: /Download 16.0 GB/ });
    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "example-org/Other-GGUF" } });
    expect(screen.queryByRole("button", { name: /Download 16.0 GB/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Model file")).not.toBeInTheDocument();
    expect(screen.queryByText(REVISION)).not.toBeInTheDocument();
    expect(transport.startLocalModelDownload).not.toHaveBeenCalled();
  });

  it("invalidates a pending lookup on edit and does not publish it after transport replacement", async () => {
    const pending = deferred<RemoteRepoFiles>();
    const getLocalModelRemoteFiles = vi.fn((_repo: string, _signal?: AbortSignal) => pending.promise);
    const transport = { ...transportWithOverview(vi.fn(async () => overview())), getLocalModelRemoteFiles };
    const view = render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    expect(screen.getByText("Looking up repository…")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Hugging Face repository"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Show files" })).toBeDisabled();
    expect(screen.queryByText("Looking up repository…")).not.toBeInTheDocument();
    view.rerender(<LocalModelsPage transport={transportWithOverview(vi.fn(async () => overview()))} />);
    await screen.findByText("Example GPU");
    await act(async () => { pending.resolve(remoteFiles()); await pending.promise; });
    expect(getLocalModelRemoteFiles.mock.calls[0][1]?.aborted).toBe(true);
    expect(screen.queryByLabelText("Model file")).not.toBeInTheDocument();
  });

  it("validates the overview contract", () => {
    expect(safeOverview(overview())).toBe(true);
    expect(safeOverview({ contract_version: "other" })).toBe(false);
    const validDownload = { ...overview(), downloads: [download()] };
    expect(safeOverview(validDownload)).toBe(true);
    expect(safeOverview({ ...validDownload, downloads: [{ ...download(), state: "teleporting" }] })).toBe(false);
    expect(safeOverview({ ...validDownload, downloads: [{ ...download(), bytes_done: 17 * 1024 ** 3 }] })).toBe(false);
    const { updated_at: _updatedAt, ...withoutUpdatedAt } = download();
    expect(safeOverview({ ...validDownload, downloads: [withoutUpdatedAt] })).toBe(false);
    expect(safeOverview({ ...validDownload, storage_free_bytes: -1 })).toBe(false);
  });

  it("shows revision-checked pause and cancel controls for an active durable download", async () => {
    const active = download("downloading");
    const pauseLocalModelDownload = vi.fn(async () => ({ ...active, state: "pausing" as const, status_revision: 8 }));
    const cancelLocalModelDownload = vi.fn(async () => ({
      ...active,
      state: "cancelling" as const,
      status_revision: 8,
    }));
    const transport = {
      ...transportWithOverview(vi.fn(async () => ({ ...overview(), downloads: [active] }))),
      pauseLocalModelDownload,
      cancelLocalModelDownload,
    };
    render(<LocalModelsPage transport={transport} />);

    expect(await screen.findByRole("progressbar", { name: "qwen-q4_k_m.gguf download progress" })).toHaveAttribute("value", String(4 * 1024 ** 3));
    fireEvent.click(screen.getByRole("button", { name: "Pause qwen-q4_k_m.gguf download" }));
    await waitFor(() => expect(pauseLocalModelDownload).toHaveBeenCalledWith(DIGEST, 7));

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel qwen-q4_k_m.gguf download" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Cancel qwen-q4_k_m.gguf download" }));
    expect(cancelLocalModelDownload).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Cancel qwen-q4_k_m.gguf download" }));
    await waitFor(() => expect(cancelLocalModelDownload).toHaveBeenCalledWith(DIGEST, 7));
    confirm.mockRestore();
  });

  it.each([
    ["paused", "Resume", "resumeLocalModelDownload"],
    ["interrupted", "Resume", "resumeLocalModelDownload"],
    ["failed", "Retry", "retryLocalModelDownload"],
    ["cancelled", "Retry", "retryLocalModelDownload"],
  ] as const)("offers %s recovery through %s", async (state, label, method) => {
    const current = download(state);
    if (state === "cancelled") {
      current.bytes_done = 0;
      current.partial_retained = false;
      current.cleanup_confirmed = true;
    }
    const operation = vi.fn(async () => ({ ...current, state: "queued" as const, status_revision: 8 }));
    const transport = {
      ...transportWithOverview(vi.fn(async () => ({ ...overview(), downloads: [current] }))),
      resumeLocalModelDownload: method === "resumeLocalModelDownload" ? operation : vi.fn(),
      retryLocalModelDownload: method === "retryLocalModelDownload" ? operation : vi.fn(),
      cancelLocalModelDownload: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: `${label} qwen-q4_k_m.gguf download` }));
    await waitFor(() => expect(operation).toHaveBeenCalledWith(DIGEST, 7));
  });

  it("blocks a new download when the exact artifact plus reserve does not fit", async () => {
    const value = { ...overview(), storage_free_bytes: 1024 ** 3 };
    const transport = {
      ...transportWithOverview(vi.fn(async () => value)),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles()),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    const blocked = await screen.findByRole("button", { name: "Not enough disk space" });
    expect(blocked).toBeDisabled();
    expect(screen.getByText(/needs 16.5 GB including the safety reserve/i)).toBeVisible();
  });

  it("surfaces a durable-ledger recovery block without hiding installed models", async () => {
    render(<LocalModelsPage transport={transportWithOverview(vi.fn(async () => ({
      ...overview(),
      download_ledger_error_code: "download_ledger_invalid",
    })))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/download recovery ledger could not be verified/i);
    expect(screen.getByText("Qwen 27B Q4")).toBeVisible();
  });

  it("registers an explicit multimodal projector beside local weights", async () => {
    const addLocalModel = vi.fn(async () => model().record);
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview())),
      addLocalModel,
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");

    fireEvent.change(screen.getByLabelText("Local GGUF path"), {
      target: { value: "D:\\example\\models\\example-Q4_K_M.gguf" },
    });
    fireEvent.change(screen.getByLabelText("Local multimodal projector path"), {
      target: { value: "D:\\example\\models\\mmproj-example-f16.gguf" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(addLocalModel).toHaveBeenCalledWith({
      alias: "example-q4_k_m",
      path: "D:\\example\\models\\example-Q4_K_M.gguf",
      mmproj_path: "D:\\example\\models\\mmproj-example-f16.gguf",
      default_device: "split",
      context_size: 8192,
    }));
    expect(await screen.findByText("Registered.")).toBeVisible();
  });

  it("keeps the Models heading and labelled boundary while loading", () => {
    render(<LocalModelsPage transport={transportWithOverview(
      vi.fn(() => new Promise<LocalModelsOverview>(() => undefined)),
    )} />);

    expect(screen.getByRole("region", { name: "Models" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Models" })).toBeInTheDocument();
    expect(screen.getByText("Looking at this machine…")).toBeInTheDocument();
  });

  it("keeps the Models heading and labelled boundary when unavailable", async () => {
    render(<LocalModelsPage transport={transportWithOverview(
      vi.fn(async () => { throw new TransportError("unavailable", 404); }),
    )} />);

    await screen.findByText("Local models are not available in this runtime.");
    expect(screen.getByRole("region", { name: "Models" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Models" })).toBeInTheDocument();
  });

  it("keeps the Models heading and labelled boundary for invalid responses", async () => {
    render(<LocalModelsPage transport={transportWithOverview(
      vi.fn(async () => ({ contract_version: "other" } as unknown as LocalModelsOverview)),
    )} />);

    await screen.findByRole("alert");
    expect(screen.getByRole("region", { name: "Models" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Models" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The model list could not be verified.");
  });

  it("presents static model examples as neutral references instead of machine-specific recommendations", async () => {
    render(<LocalModelsPage transport={transportWithOverview(vi.fn(async () => overview()))} />);

    await screen.findByRole("heading", { name: "Common GGUF starting points" });
    expect(screen.queryByRole("heading", { name: "Recommended for this machine" })).toBeNull();
    expect(screen.getByText(/general reference examples, not recommendations or performance measurements for this machine/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/tok\/s/);
  });

  it("does not let a poll started before a command overwrite the command reload", async () => {
    vi.useFakeTimers();
    const initial = deferred<LocalModelsOverview>();
    const poll = deferred<LocalModelsOverview>();
    const activation = deferred<LocalModelStatus>();
    const commandReload = deferred<LocalModelsOverview>();
    const signals: AbortSignal[] = [];
    const getLocalModels = vi.fn((signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      return [initial.promise, poll.promise, commandReload.promise][getLocalModels.mock.calls.length - 1];
    });
    const transport = {
      ...transportWithOverview(getLocalModels),
      activateLocalModel: vi.fn(() => activation.promise),
    };
    const view = render(<LocalModelsPage transport={transport} />);

    try {
      await act(async () => { initial.resolve(namedOverview("Initial GPU")); await initial.promise; });
      expect(screen.getByText("Initial GPU")).toBeInTheDocument();

      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(getLocalModels).toHaveBeenCalledTimes(2);
      fireEvent.click(screen.getByRole("button", { name: "Activate" }));
      await act(async () => { activation.resolve(model("running")); await activation.promise; });

      expect(getLocalModels).toHaveBeenCalledTimes(3);
      expect(signals[1].aborted).toBe(true);
      await act(async () => {
        commandReload.resolve(namedOverview("Command GPU", [model("running")]));
        await commandReload.promise;
      });
      expect(screen.getByText("Command GPU")).toBeInTheDocument();
      expect(screen.getByText(/running · requested split · 52 GPU layers/)).toBeInTheDocument();

      await act(async () => { poll.resolve(namedOverview("Stale poll GPU")); await poll.promise; });
      expect(screen.getByText("Command GPU")).toBeInTheDocument();
      expect(screen.queryByText("Stale poll GPU")).toBeNull();
    } finally {
      view.unmount();
      vi.useRealTimers();
    }
  });

  it("keeps the current reload failure truthful when an older poll later succeeds", async () => {
    vi.useFakeTimers();
    const initial = deferred<LocalModelsOverview>();
    const poll = deferred<LocalModelsOverview>();
    const activation = deferred<LocalModelStatus>();
    const commandReload = deferred<LocalModelsOverview>();
    const getLocalModels = vi.fn(() => (
      [initial.promise, poll.promise, commandReload.promise][getLocalModels.mock.calls.length - 1]
    ));
    const transport = {
      ...transportWithOverview(getLocalModels),
      activateLocalModel: vi.fn(() => activation.promise),
    };
    const view = render(<LocalModelsPage transport={transport} />);

    try {
      await act(async () => { initial.resolve(namedOverview("Initial GPU")); await initial.promise; });
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      fireEvent.click(screen.getByRole("button", { name: "Activate" }));
      await act(async () => { activation.resolve(model("running")); await activation.promise; });
      expect(getLocalModels).toHaveBeenCalledTimes(3);

      await act(async () => {
        commandReload.reject(new TransportError("current reload failed", 500));
        await commandReload.promise.catch(() => undefined);
      });
      expect(screen.getByRole("alert")).toHaveTextContent("The model list could not be verified.");

      await act(async () => { poll.resolve(namedOverview("Stale poll GPU")); await poll.promise; });
      expect(screen.getByRole("alert")).toHaveTextContent("The model list could not be verified.");
      expect(screen.queryByText("Stale poll GPU")).toBeNull();
    } finally {
      view.unmount();
      vi.useRealTimers();
    }
  });

  it("aborts and ignores an unresolved overview load when unmounted", async () => {
    const pending = deferred<LocalModelsOverview>();
    let signal: AbortSignal | undefined;
    const getLocalModels = vi.fn((candidate?: AbortSignal) => {
      signal = candidate;
      return pending.promise;
    });
    const view = render(<LocalModelsPage transport={transportWithOverview(getLocalModels)} />);

    expect(getLocalModels).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { pending.resolve(namedOverview("Unmounted GPU")); await pending.promise; });
    expect(getLocalModels).toHaveBeenCalledTimes(1);
  });

  it("does not let an old transport context overwrite the current one", async () => {
    const previous = deferred<LocalModelsOverview>();
    const current = deferred<LocalModelsOverview>();
    let previousSignal: AbortSignal | undefined;
    const previousTransport = transportWithOverview(vi.fn((signal?: AbortSignal) => {
      previousSignal = signal;
      return previous.promise;
    }));
    const currentTransport = transportWithOverview(vi.fn(() => current.promise));
    const view = render(<LocalModelsPage transport={previousTransport} />);

    view.rerender(<LocalModelsPage transport={currentTransport} />);
    expect(previousSignal?.aborted).toBe(true);
    expect(screen.getByText("Looking at this machine…")).toBeInTheDocument();
    await act(async () => { current.resolve(namedOverview("Current context GPU")); await current.promise; });
    expect(screen.getByText("Current context GPU")).toBeInTheDocument();

    await act(async () => { previous.resolve(namedOverview("Previous context GPU")); await previous.promise; });
    expect(screen.getByText("Current context GPU")).toBeInTheDocument();
    expect(screen.queryByText("Previous context GPU")).toBeNull();
    view.unmount();
  });

  it("shows hardware, the model with its endpoint, and activates on the chosen device", async () => {
    let current = overview();
    const activateLocalModel = vi.fn(async (_alias: string, _request: { device?: "cpu" | "gpu" | "split" | null }) => {
      current = overview([model("running")]);
      return model("running");
    });
    const transport = {
      getLocalModels: vi.fn(async () => current),
      activateLocalModel,
      deactivateLocalModel: vi.fn(async () => model()),
      removeLocalModel: vi.fn(async () => undefined),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles()),
      startLocalModelDownload: vi.fn(),
      addLocalModel: vi.fn(),
      streamLocalModelChat: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    expect(screen.getByText("Qwen 27B Q4")).toBeTruthy();
    expect(screen.getByText("POST /v1/local-models/qwen-27b-q4/chat/completions")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Device for Qwen 27B Q4").querySelector("input[value='gpu']") as HTMLInputElement);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(activateLocalModel).toHaveBeenCalledWith("qwen-27b-q4", { device: "gpu", remember: true, fast_attention: true, tool_calling: true }));
    await screen.findByText(/running · requested split · 52 GPU layers/);

    // Adding from Hugging Face shows sizes and picks the 4-bit file by default.
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByLabelText("Model file");
    expect((screen.getByLabelText("Model file") as HTMLSelectElement).value).toBe("qwen-q4_k_m.gguf");
    expect(screen.getByRole("button", { name: /Download 16.0 GB/ })).toBeTruthy();
    // The immutable revision, digest and licence the person is confirming are all on screen.
    expect(screen.getByText(REVISION)).toBeTruthy();
    expect(screen.getByText(new RegExp(DIGEST))).toBeTruthy();
    expect(screen.getByText(/apache-2\.0 . admitted by this app's frozen download policy/)).toBeTruthy();
    // An installed model with nothing verified says so instead of implying safety.
    expect(screen.getByText(/Provenance unavailable/)).toBeTruthy();
  });

  it("disables unsupported accelerator choices and safely falls back to CPU", async () => {
    const blocked = model();
    blocked.placement = {
      ...blocked.placement,
      gpu_memory_free_mb: null,
      options: [
        { device: "gpu", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "split", state: "blocked", reason_code: "accelerator_evidence_unavailable", recommended_gpu_layers: null, estimated_vram_required_mb: null },
        { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
      ],
    };
    const activateLocalModel = vi.fn(async () => blocked);
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview([blocked]))),
      activateLocalModel,
    };
    render(<LocalModelsPage transport={transport} />);

    const group = await screen.findByRole("radiogroup", { name: "Device for Qwen 27B Q4" });
    const gpu = within(group).getByRole("radio", { name: "GPU" });
    const split = within(group).getByRole("radio", { name: "GPU / CPU" });
    expect(gpu).toBeDisabled();
    expect(gpu).toHaveAccessibleDescription(/no current accelerator and free-memory evidence/i);
    expect(split).toBeDisabled();
    expect(split).toHaveAccessibleDescription(/no current accelerator and free-memory evidence/i);
    expect(within(group).getByRole("radio", { name: "CPU" })).toBeChecked();
    expect(screen.getByText(/no current accelerator and free-memory evidence/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(activateLocalModel).toHaveBeenCalledWith(
      "qwen-27b-q4",
      { device: "cpu", remember: true, fast_attention: true, tool_calling: true },
    ));
  });

  it("uses the revision-bound shared coordinator and blocks overlapping lifecycle commands", async () => {
    const pending = deferred<LocalRuntimeCoordinatorStatus>();
    let currentRuntime = runtimeStatus();
    const switchLocalRuntime = vi.fn(() => pending.promise);
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview([model(), secondModel()]))),
      getLocalRuntime: vi.fn(async () => currentRuntime),
      switchLocalRuntime,
      stopLocalRuntime: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example Model B");

    const firstCard = screen.getByText("Qwen 27B Q4").closest("li");
    const secondCard = screen.getByText("Example Model B").closest("li");
    expect(firstCard).not.toBeNull();
    expect(secondCard).not.toBeNull();
    fireEvent.click(within(firstCard!).getByRole("button", { name: "Start shared runtime" }));

    await waitFor(() => expect(switchLocalRuntime).toHaveBeenCalledWith({
      alias: "qwen-27b-q4",
      expected_revision: 7,
      device: "split",
      gpu_layers: null,
      context_size: 8192,
      remember: true,
      fast_attention: true,
      tool_calling: true,
    }));
    expect(within(firstCard!).getByRole("button", { name: "Starting shared runtime…" })).toBeDisabled();
    expect(within(secondCard!).getByRole("button", { name: "Start shared runtime" })).toBeDisabled();

    currentRuntime = runtimeStatus("qwen-27b-q4", { revision: 8 });
    await act(async () => { pending.resolve(currentRuntime); await pending.promise; });
    await screen.findByText(/requested split placement.*actual offload is not measured/i);
  });

  it("unloads only the exact served runtime through the shared coordinator", async () => {
    let currentRuntime = runtimeStatus("qwen-27b-q4");
    const stopLocalRuntime = vi.fn(async () => {
      currentRuntime = runtimeStatus(null, { revision: 8 });
      return currentRuntime;
    });
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview([model("running"), secondModel()]))),
      getLocalRuntime: vi.fn(async () => currentRuntime),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime,
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example Model B");

    const servedCard = screen.getByText("Qwen 27B Q4").closest("li");
    const otherCard = screen.getByText("Example Model B").closest("li");
    expect(servedCard).not.toBeNull();
    expect(otherCard).not.toBeNull();
    expect(within(otherCard!).queryByRole("button", { name: "Unload shared runtime" })).toBeNull();
    expect(within(servedCard!).getByText(/Unload the shared runtime before removing/)).toBeVisible();
    expect(within(servedCard!).getByRole("button", { name: "Remove" })).toBeDisabled();
    fireEvent.click(within(servedCard!).getByRole("button", { name: "Unload shared runtime" }));

    await waitFor(() => expect(stopLocalRuntime).toHaveBeenCalledWith({
      alias: "qwen-27b-q4",
      expected_revision: 7,
    }));
    expect(await screen.findByText("Shared runtime stopped. Chats and model registration were not changed.")).toBeVisible();
  });

  it("surfaces cleanup quarantine and keeps every model launch disabled", async () => {
    const quarantined = runtimeStatus(null, {
      state: "cleanup_unknown",
      cleanup: {
        state: "unknown",
        process_exit_confirmed: true,
        gpu_memory_free_before_mb: null,
        gpu_memory_free_after_mb: null,
        gpu_memory_released_mb: null,
      },
      last_error_code: "runtime_cleanup_unconfirmed",
    });
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview([model(), secondModel()]))),
      getLocalRuntime: vi.fn(async () => quarantined),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/cleanup is unconfirmed/i);
    expect(screen.getAllByRole("button", { name: "Start shared runtime" })).toHaveLength(2);
    for (const button of screen.getAllByRole("button", { name: "Start shared runtime" })) {
      expect(button).toBeDisabled();
    }
    expect(transport.switchLocalRuntime).not.toHaveBeenCalled();
  });

  it("does not expose chat from a stale per-model running poll while the coordinator is not ready", async () => {
    const loading = runtimeStatus(null, {
      state: "loading",
      requested: {
        alias: "qwen-27b-q4",
        device: "split",
        gpu_layers: 52,
        context_size: 8192,
      },
    });
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview([model("running")]))),
      getLocalRuntime: vi.fn(async () => loading),
      switchLocalRuntime: vi.fn(),
      stopLocalRuntime: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);

    expect(await screen.findByText("Shared runtime loading")).toBeVisible();
    expect(screen.getByText(/Activate a model above to chat/)).toBeVisible();
    expect(screen.queryByLabelText("Chat model")).toBeNull();
    expect(screen.getByText("stopped")).toBeVisible();
  });

  it("explains a revision conflict instead of misreporting a missing runtime", async () => {
    const currentRuntime = runtimeStatus();
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview())),
      getLocalRuntime: vi.fn(async () => currentRuntime),
      switchLocalRuntime: vi.fn(async () => {
        throw new TransportError("redacted", 409, "runtime_revision_conflict");
      }),
      stopLocalRuntime: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Shared runtime stopped");

    fireEvent.click(screen.getByRole("button", { name: "Start shared runtime" }));

    expect(await screen.findByText(/changed in another view/i)).toBeVisible();
    expect(screen.queryByText(/llama-server is not installed/i)).toBeNull();
  });

  it("shows live compatibility separately from static GGUF identity", async () => {
    const receipt: LocalModelCompatibilityCatalog = {
      contract_version: "local-model-compatibility.v1",
      adapter: {
        adapter_id: "llama.cpp-openai-gguf",
        adapter_version: "llama.cpp-openai-gguf.v1",
        runtime_version: "synthetic-b9000",
        runtime_identity_state: "verified",
        runtime_binary_sha256: "c".repeat(64),
        capability_probe_version: "local-runtime-multimodal-probe.v2",
      },
      models: [{
        alias: "qwen-27b-q4",
        state: "supported",
        reason_code: "live_text_probe_verified",
        format: "gguf",
        architecture: "example-arch",
        tokenizer_model: "example-tokenizer",
        training_context_size: 32768,
        metadata_reader_version: "gguf-metadata.v1",
        artifact_identity_state: "unverified",
        artifact_sha256: null,
        source_revision: null,
        source_license: null,
        source_license_policy: null,
        execution_state: "verified",
        context_counter_state: "verified",
      }],
    };
    const transport = {
      ...transportWithOverview(vi.fn(async () => overview())),
      getLocalModelCompatibility: vi.fn(async () => receipt),
    };
    render(<LocalModelsPage transport={transport} />);
    expect(await screen.findByText(/Executable compatibility: supported · live text request verified/)).toBeVisible();
    expect(screen.getByText(/Architecture example-arch · tokenizer example-tokenizer · context counter verified/)).toBeVisible();
  });

  it("passes the displayed revision, digest and licence back as the confirmation", async () => {
    const startLocalModelDownload = vi.fn(async (_request: Parameters<PromptEnhancerTransport["startLocalModelDownload"]>[0]) => ({}) as never);
    const transport = {
      getLocalModels: vi.fn(async () => overview()),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles()),
      startLocalModelDownload, addLocalModel: vi.fn(), streamLocalModelChat: vi.fn(),
    };
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByLabelText("Model file");
    fireEvent.click(screen.getByRole("button", { name: /Download 16.0 GB/ }));
    await waitFor(() => expect(startLocalModelDownload).toHaveBeenCalledTimes(1));
    expect(startLocalModelDownload.mock.calls[0][0]).toEqual({
      repo_id: "example-org/Example-GGUF",
      filename: "qwen-q4_k_m.gguf",
      confirmed_size_bytes: 16 * 1024 ** 3,
      confirmed_revision: REVISION,
      confirmed_sha256: DIGEST,
      confirmed_license: "apache-2.0",
      alias: "qwen-q4_k_m",
      default_device: "split",
    });
    expect(confirm.mock.calls[0][0]).toContain(REVISION);
    expect(confirm.mock.calls[0][0]).toContain(DIGEST);
    expect(confirm.mock.calls[0][0]).toContain("apache-2.0");
    confirm.mockRestore();
  });

  it("refuses to offer a download when the licence is not admitted", async () => {
    const transport = {
      getLocalModels: vi.fn(async () => overview()),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles({ license_id: "example-community-1.0", license_admission: "unreviewed" })),
      startLocalModelDownload: vi.fn(), addLocalModel: vi.fn(), streamLocalModelChat: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByLabelText("Model file");
    const button = screen.getByRole("button", { name: "Download unavailable" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("keeps gated repositories on the manual registration path", async () => {
    const transport = {
      getLocalModels: vi.fn(async () => overview()),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles({
        gated: true,
        files: [{ filename: "qwen-q4_k_m.gguf", size_bytes: 16 * 1024 ** 3, sha256: DIGEST, eligible: false, ineligible_reason: "repository_gated" }],
      })),
      startLocalModelDownload: vi.fn(), addLocalModel: vi.fn(), streamLocalModelChat: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByText(/automated downloader is public-only/);
    expect((screen.getByRole("button", { name: "Download unavailable" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/cached Hugging Face login/)).toBeTruthy();
  });

  it("shows a repository that cannot be pinned as undownloadable", async () => {
    const transport = {
      getLocalModels: vi.fn(async () => overview()),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(async () => remoteFiles({
        revision: null, revision_pinned: false, license_id: null, license_admission: "unavailable",
        unavailable_reason: "revision_not_immutable", files: [],
      })),
      startLocalModelDownload: vi.fn(), addLocalModel: vi.fn(), streamLocalModelChat: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText("Example GPU");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    await screen.findByText(/did not name an immutable commit/);
    expect(screen.queryByLabelText("Model file")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Download/ })).toBeNull();
  });

  it("never claims provenance it does not have", () => {
    const base = model().record;
    expect(provenanceLine(base)).toMatch(/Provenance unavailable/);
    // A record carrying a digest but no verification is still unavailable, never "verified".
    expect(provenanceLine({ ...base, sha256: DIGEST, source_revision: REVISION } as LocalModelRecord)).toMatch(/Provenance unavailable/);
    const verified = { ...base, sha256: DIGEST, source_revision: REVISION, source_license: "apache-2.0", source_license_policy: "local-model-license-policy.v1", provenance_verified: true } as LocalModelRecord;
    expect(provenanceLine(verified)).toBe("Verified when downloaded · revision 0123456789ab · sha256 0123456789ab · licence apache-2.0 · policy local-model-license-policy.v1");
  });

  it("explains a missing runtime", async () => {
    const transport = {
      getLocalModels: vi.fn(async () => overview([], false)),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(), startLocalModelDownload: vi.fn(), addLocalModel: vi.fn(), streamLocalModelChat: vi.fn(),
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByText(/llama.cpp is not installed/);
    expect(screen.getByText(/No model yet/)).toBeTruthy();
    expect(screen.getByText(/Activate a model above to chat/)).toBeTruthy();
  });

  it("streams a chat reply from the running model with thinking off by default", async () => {
    const streamLocalModelChat = vi.fn(
      async (
        _alias: string,
        _request: { messages: { role: string; content: string }[]; enable_thinking?: boolean },
        onDelta: (delta: { content?: string; reasoning?: string }) => void,
      ) => {
        onDelta({ content: "feat: " });
        onDelta({ content: "add chat" });
        return { content: "feat: add chat", reasoning: "", finish_reason: "stop", elapsed_ms: 1200 };
      },
    );
    const transport = {
      getLocalModels: vi.fn(async () => overview([model("running")])),
      activateLocalModel: vi.fn(), deactivateLocalModel: vi.fn(), removeLocalModel: vi.fn(),
      getLocalModelRemoteFiles: vi.fn(), startLocalModelDownload: vi.fn(), addLocalModel: vi.fn(),
      streamLocalModelChat,
    };
    render(<LocalModelsPage transport={transport} />);
    await screen.findByLabelText("Chat model");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Write a commit message" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("feat: add chat");
    expect(streamLocalModelChat).toHaveBeenCalledTimes(1);
    const [alias, request] = streamLocalModelChat.mock.calls[0];
    expect(alias).toBe("qwen-27b-q4");
    expect(request.enable_thinking).toBe(false);
    expect(request.messages).toEqual([{ role: "user", content: "Write a commit message" }]);
    expect(screen.getByText(/1\.2 s/)).toBeTruthy();
    expect(screen.getAllByText(/\/v1\/local-models\/qwen-27b-q4\/v1/).length).toBeGreaterThanOrEqual(2);
  });
});
