import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DeviceMode,
  DownloadStatus,
  LocalModelRecord,
  LocalModelCompatibility,
  LocalModelCompatibilityCatalog,
  LocalModelStatus,
  LocalModelsOverview,
  LocalRuntimeCoordinatorStatus,
  PromptEnhancerTransport,
  RemoteRepoFiles,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Icon } from "../../shared/ui/Icon";
import { LocalModelChatPanel } from "./LocalModelChatPanel";
import "./LocalModelsPage.css";

const RECOMMENDED_REPO = "mradermacher/Qwen3.8-27B-Uncensored-FP8-i1-GGUF";
/**
 * Common starting points only, not recommendations derived from detected hardware:
 * picking one just runs the same server-side lookup as typing the repository by hand.
 * Sizes here are rough reference notes for choosing a quantization; nothing
 * is downloaded until the server has resolved an immutable revision, digest and licence
 * for the exact file and the person has confirmed all of them.
 */
const RECOMMENDED: readonly { repo: string; file: string; label: string; note: string; sizeGb: number }[] = [
  { repo: "mradermacher/Qwen3.8-27B-Uncensored-FP8-i1-GGUF", file: "Qwen3.8-27B-Uncensored-FP8.i1-IQ3_M.gguf", label: "Qwen3.8-27B uncensored · IQ3_M", note: "reference: about 12.8 GB of weights; a 16 GB GPU may fit them only if runtime overhead also fits", sizeGb: 12.8 },
  { repo: "mradermacher/Qwen3.8-27B-Uncensored-FP8-i1-GGUF", file: "Qwen3.8-27B-Uncensored-FP8.i1-IQ4_XS.gguf", label: "Qwen3.8-27B uncensored · IQ4_XS", note: "reference: about 15.3 GB of weights; a 16 GB GPU commonly needs a GPU/CPU split after overhead", sizeGb: 15.3 },
  { repo: "mradermacher/Qwen3.8-27B-Uncensored-FP8-i1-GGUF", file: "Qwen3.8-27B-Uncensored-FP8.i1-Q4_K_M.gguf", label: "Qwen3.8-27B uncensored · Q4_K_M", note: "reference: about 16.8 GB of weights; this typically exceeds 16 GB VRAM and needs a GPU/CPU split", sizeGb: 16.8 },
];
const LICENSE_ADMISSION_TEXT: Readonly<Record<string, string>> = {
  allowed: "admitted by this app's frozen download policy",
  not_allowed: "reviewed and refused by this app's frozen download policy",
  unreviewed: "not reviewed for this app's automated download policy",
  unavailable: "not declared, or the repository contradicts itself",
};
const INELIGIBLE_TEXT: Readonly<Record<string, string>> = {
  license_not_allowed: "licence refused by the download policy",
  license_unreviewed: "licence not reviewed - fetch these weights by hand",
  license_unavailable: "no licence declared at this revision",
  size_unavailable: "the Hub published no exact size for this file",
  digest_unavailable: "the Hub published no sha256 for this file",
  unsupported_file_path: "not a plain file at the repository root",
  repository_gated: "the public-only downloader does not use a cached Hugging Face login",
};
const IDENTITY_UNAVAILABLE_TEXT: Readonly<Record<string, string>> = {
  revision_not_immutable: "the Hub did not name an immutable commit for this repository",
  revision_contradicted: "the Hub answered the commit lookup with a different commit",
};
const DEVICES: readonly { value: DeviceMode; title: string; hint: string }[] = [
  { value: "gpu", title: "GPU", hint: "Requests full GPU offload after a conservative memory preflight" },
  { value: "split", title: "GPU / CPU", hint: "Requests the admitted layer estimate and keeps the rest on CPU" },
  { value: "cpu", title: "CPU", hint: "No offload; slow but always works" },
];
const PLACEMENT_REASON_TEXT: Readonly<Record<string, string>> = {
  cpu_available: "CPU execution is available; no GPU offload is requested.",
  accelerator_evidence_unavailable: "Blocked: no current accelerator and free-memory evidence was detected.",
  model_size_unavailable: "Blocked: model size is unavailable, so VRAM fit cannot be estimated.",
  layer_count_unavailable: "Blocked: GGUF layer count is unavailable, so a split cannot be bounded.",
  context_exceeds_model_metadata: "Blocked: this context exceeds the model's verified GGUF training-context metadata.",
  gpu_estimate_fits: "Preflight estimate fits current free VRAM; actual offload is not measured.",
  gpu_estimate_exceeds_free_memory: "Blocked: estimated weights, context and safety headroom exceed current free VRAM.",
  split_estimate_available: "A bounded GPU-layer estimate is available; actual offload is not measured.",
  split_estimate_exceeds_free_memory: "Blocked: no model layer fits after context and safety headroom.",
  owned_runtime_requires_cleanup_recheck: "Conditional: unload the app-owned GPU runtime, verify cleanup, then recheck free VRAM.",
};

const DOWNLOAD_STATES = new Set<DownloadStatus["state"]>([
  "queued", "downloading", "pausing", "paused", "cancelling",
  "cancelled", "completed", "failed", "interrupted",
]);
const DOWNLOAD_ERROR_TEXT: Readonly<Record<string, string>> = {
  insufficient_disk_space: "not enough verified free disk space",
  disk_space_unavailable: "free disk space could not be verified",
  download_interrupted: "the app stopped before this transfer completed",
  download_failed: "the network transfer failed; a bounded partial may be reusable",
  download_cleanup_failed: "owned partial cleanup could not be confirmed",
  download_registry_conflict: "the registered alias or published model bytes no longer match this reviewed download",
  download_adapter_incompatible: "the installed Hub adapter is not compatible with safe pause and cancel",
  provenance_mismatch: "the immutable repository identity changed",
  hash_mismatch: "the downloaded bytes did not match the reviewed digest",
  size_mismatch: "the downloaded byte count did not match the reviewed size",
};

const COMPATIBILITY_REASON_TEXT: Readonly<Record<string, string>> = {
  live_text_probe_verified: "live text request verified",
  model_not_executed: "not executed with this runtime yet",
  live_text_probe_failed: "live text request failed",
  runtime_execution_failed: "runtime execution failed",
  runtime_unavailable: "llama.cpp runtime unavailable",
  artifact_missing: "artifact missing",
};

type OverviewLoadKind = "poll" | "reload";

interface ActiveOverviewLoad {
  context: number;
  controller: AbortController;
  generation: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isDownloadStatus(value: unknown): value is DownloadStatus {
  if (!isRecord(value)
    || typeof value.download_id !== "string" || !/^[0-9a-f]{64}$/.test(value.download_id)
    || typeof value.repo_id !== "string"
    || typeof value.filename !== "string"
    || typeof value.alias !== "string"
    || typeof value.state !== "string" || !DOWNLOAD_STATES.has(value.state as DownloadStatus["state"])
    || !isNonnegativeInteger(value.bytes_total)
    || !isNonnegativeInteger(value.bytes_done)
    || value.bytes_done > value.bytes_total
    || !isNullableString(value.error_code ?? null)
    || typeof value.started_at !== "string"
    || typeof value.updated_at !== "string"
    || !isNullableString(value.finished_at ?? null)
    || !isNonnegativeInteger(value.status_revision)
    || !isNonnegativeInteger(value.attempt)
    || !(value.disk_required_bytes === null || value.disk_required_bytes === undefined || isNonnegativeInteger(value.disk_required_bytes))
    || !(value.disk_free_bytes_at_start === null || value.disk_free_bytes_at_start === undefined || isNonnegativeInteger(value.disk_free_bytes_at_start))
    || typeof value.partial_retained !== "boolean"
    || !(value.cleanup_confirmed === null || value.cleanup_confirmed === undefined || typeof value.cleanup_confirmed === "boolean")
    || !(value.transfer_adapter_version === null || value.transfer_adapter_version === undefined || typeof value.transfer_adapter_version === "string")
    || !(value.revision === null || value.revision === undefined || (typeof value.revision === "string" && /^[0-9a-f]{40}$/.test(value.revision)))
    || !(value.sha256 === null || value.sha256 === undefined || (typeof value.sha256 === "string" && /^[0-9a-f]{64}$/.test(value.sha256)))) {
    return false;
  }
  if (value.state === "completed" && value.bytes_done !== value.bytes_total) return false;
  if (value.partial_retained && value.bytes_done === 0) return false;
  return value.state !== "cancelled" || (value.bytes_done === 0 && value.partial_retained === false && value.cleanup_confirmed === true);
}

export function safeOverview(value: unknown): value is LocalModelsOverview {
  return isRecord(value)
    && value.contract_version === "local-models.v1"
    && Array.isArray(value.models)
    && value.models.every((model) => isRecord(model)
      && isRecord(model.placement)
      && model.placement.contract_version === "local-model-placement.v1"
      && model.placement.actual_offload_verified === false
      && Array.isArray(model.placement.options)
      && model.placement.options.length === 3)
    && Array.isArray(value.downloads)
    && value.downloads.every(isDownloadStatus)
    && (value.storage_free_bytes === null || isNonnegativeInteger(value.storage_free_bytes))
    && isNonnegativeInteger(value.download_reserve_bytes)
    && (value.download_ledger_error_code === null || typeof value.download_ledger_error_code === "string")
    && isRecord(value.hardware);
}

function gb(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "unknown size";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function mb(value: number | null | undefined): string {
  if (value === null || value === undefined) return "unknown";
  return `${(value / 1024).toFixed(1)} GB`;
}

function shortId(value: string | null | undefined, size = 12): string {
  return value ? value.slice(0, size) : "unavailable";
}

/** Provenance recorded for an installed model, or an explicit "unavailable". */
export function provenanceLine(record: LocalModelRecord): string {
  if (
    !record.provenance_verified
    || !record.source_revision
    || !record.sha256
    || !record.source_license
    || !record.source_license_policy
  ) {
    return "Provenance unavailable - registered without a verified Hugging Face revision, digest or licence.";
  }
  return `Verified when downloaded · revision ${shortId(record.source_revision)} · sha256 ${shortId(record.sha256)} · licence ${record.source_license} · policy ${record.source_license_policy}`;
}

function defaultAlias(filename: string): string {
  return filename.toLowerCase().replace(/\.gguf$/, "").replace(/[^a-z0-9._-]+/g, "-").replace(/^[^a-z0-9]+/, "").slice(0, 60) || "model";
}

function coordinatorStateLabel(state: LocalRuntimeCoordinatorStatus["state"]): string {
  return {
    idle: "stopped",
    draining: "waiting for an active request",
    unloading: "unloading",
    loading: "loading",
    ready: "ready",
    failed: "needs attention",
    cleanup_unknown: "cleanup unconfirmed",
    quarantined: "quarantined",
  }[state];
}

function operationFailure(caught: unknown, label: string): string {
  const status = caught instanceof TransportError ? caught.status : null;
  const reason = caught instanceof TransportError ? caught.reasonCode : null;
  if (label.startsWith("download-")) {
    if (reason === "download_revision_conflict") {
      return "This download changed in another view. Its durable state was reloaded; review it before trying again.";
    }
    if (reason === "download_cleanup_failed") {
      return "The transfer stopped, but deletion of its owned partial could not be confirmed. The download remains blocked for review.";
    }
    if (reason === "provenance_mismatch" || reason === "file_not_eligible") {
      return "The repository no longer matches the immutable revision, digest, size, or licence you confirmed. Look it up again before retrying.";
    }
    return "That download command could not be confirmed. Its current durable state was reloaded.";
  }
  if (label === "download") {
    return status === 409
      ? "The download was refused and nothing was downloaded or registered: the repository's revision, digest or licence no longer matches what you confirmed, the file is not admitted by the download policy, or that alias already exists. Look the repository up again."
      : "The download did not start. Nothing was downloaded or registered.";
  }
  if (reason === "runtime_busy") {
    return "A model request is still active. Finish or stop it before switching or unloading the shared runtime.";
  }
  if (reason === "runtime_revision_conflict") {
    return "The shared runtime changed in another view. Its current state was reloaded; review it before trying again.";
  }
  if (reason === "runtime_cleanup_unconfirmed") {
    return "The old process exited, but GPU-memory cleanup could not be verified. No replacement model was loaded.";
  }
  if (reason === "runtime_quarantined" || reason === "runtime_stop_failed") {
    return "The previous runtime did not confirm a safe stop. New launches remain quarantined.";
  }
  if (reason === "runtime_activation_superseded") {
    return "A newer runtime command replaced this one. The current shared state was reloaded.";
  }
  if (reason === "runtime_shutdown_in_progress") {
    return "The app is shutting down its owned runtime. Wait for the local service to restart before loading a model.";
  }
  if (reason === "runtime_capability_probe_failed" || reason === "runtime_not_healthy") {
    return "The process started but did not pass its local text-capability check, so it was not marked ready.";
  }
  if (reason === "runtime_out_of_memory") {
    return "The runtime exited with an exact Windows out-of-memory status. Choose CPU, a smaller context, or fewer GPU layers before retrying.";
  }
  if (reason === "runtime_crashed") {
    return "The runtime process exited unexpectedly. Its owned process tree was stopped before another launch can begin.";
  }
  if (reason === "runtime_unavailable") {
    return "llama-server is not installed or is not available to this app.";
  }
  if (status === 422) return "That is not a usable GGUF file or folder.";
  if (status === 502) return "The runtime process did not become healthy. No model was marked ready.";
  if (status === 409) return "The operation conflicted with current local state. The latest state was reloaded.";
  return "That operation did not complete. The latest local state was reloaded.";
}

function LocalModelsHeader() {
  return (
    <header className="local-models__head route-header">
      <div>
        <p className="eyebrow">Local models · on this machine only</p>
        <h1 id="local-models-title">Models</h1>
        <p className="local-models__lede">
          Install models once, then request GPU, CPU, or split placement for the one app-owned shared runtime.
          Placement is admitted from current hardware evidence and rechecked after cleanup; actual tensor offload is
          not measured. Each alias keeps a local endpoint, but only the capability-verified served model accepts
          chat requests. Prompts and responses stay on this machine; looking up or downloading a Hub model is an
          explicit Hugging Face request.
        </p>
      </div>
    </header>
  );
}

/**
 * Installed local models: hardware, runtime detection, revision-bound shared
 * runtime selection and the loopback endpoint each model gets. Adding a model from
 * Hugging Face shows file sizes first and downloads only after a confirmation.
 */
export function LocalModelsPage({
  transport,
}: {
  transport: Pick<
    PromptEnhancerTransport,
    "getLocalModels" | "activateLocalModel" | "deactivateLocalModel" | "removeLocalModel" | "getLocalModelRemoteFiles" | "startLocalModelDownload" | "addLocalModel" | "streamLocalModelChat"
  > & Partial<Pick<
    PromptEnhancerTransport,
    "scanLocalModelFolder" | "getLocalModelCompatibility" | "getLocalRuntime" | "switchLocalRuntime" | "stopLocalRuntime"
    | "pauseLocalModelDownload" | "resumeLocalModelDownload" | "retryLocalModelDownload" | "cancelLocalModelDownload"
  >>;
}) {
  const [overview, setOverview] = useState<LocalModelsOverview | null>(null);
  const [compatibility, setCompatibility] = useState<LocalModelCompatibilityCatalog | null>(null);
  const [runtime, setRuntime] = useState<LocalRuntimeCoordinatorStatus | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [busy, setBusy] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [devices, setDevices] = useState<Record<string, DeviceMode>>({});
  const [layers, setLayers] = useState<Record<string, string>>({});
  const [repoId, setRepoId] = useState(RECOMMENDED_REPO);
  const [remote, setRemote] = useState<RemoteRepoFiles | null>(null);
  const [remoteError, setRemoteError] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);
  const [chosenFile, setChosenFile] = useState<string>("");
  const [alias, setAlias] = useState<string>("");
  const [localPath, setLocalPath] = useState<string>("");
  const [mmprojPath, setMmprojPath] = useState<string>("");
  const [folderPath, setFolderPath] = useState<string>("");
  const mounted = useRef(false);
  const contextGeneration = useRef(0);
  const loadGeneration = useRef(0);
  const commandGeneration = useRef(0);
  const activeLoad = useRef<ActiveOverviewLoad | null>(null);
  const activeLookup = useRef<AbortController | null>(null);
  const coordinatedLifecycle = transport.getLocalRuntime !== undefined
    && transport.switchLocalRuntime !== undefined
    && transport.stopLocalRuntime !== undefined;

  const isCurrentContext = useCallback((context: number) => (
    mounted.current && contextGeneration.current === context
  ), []);

  const load = useCallback(async (kind: OverviewLoadKind, context: number) => {
    if (!isCurrentContext(context)) return;
    if (kind === "poll" && activeLoad.current !== null) return;

    activeLoad.current?.controller.abort();
    const ticket: ActiveOverviewLoad = {
      context,
      controller: new AbortController(),
      generation: loadGeneration.current + 1,
    };
    loadGeneration.current = ticket.generation;
    activeLoad.current = ticket;
    const ownsResult = () => (
      isCurrentContext(context)
      && !ticket.controller.signal.aborted
      && activeLoad.current === ticket
      && loadGeneration.current === ticket.generation
    );
    try {
      const [value, compatibilityValue, runtimeValue] = await Promise.all([
        transport.getLocalModels(ticket.controller.signal),
        transport.getLocalModelCompatibility?.(ticket.controller.signal).catch(() => null)
          ?? Promise.resolve(null),
        coordinatedLifecycle
          ? transport.getLocalRuntime!(ticket.controller.signal)
          : Promise.resolve(null),
      ]);
      if (!ownsResult()) return;
      if (!safeOverview(value)) { setState("error"); return; }
      setOverview(value);
      setCompatibility(compatibilityValue);
      setRuntime(runtimeValue);
      setState("ready");
    } catch (caught) {
      if (!ownsResult()) return;
      setState(caught instanceof TransportError && caught.status === 404 ? "unavailable" : "error");
    } finally {
      if (activeLoad.current === ticket) activeLoad.current = null;
    }
  }, [coordinatedLifecycle, isCurrentContext, transport]);

  useEffect(() => {
    const context = contextGeneration.current + 1;
    contextGeneration.current = context;
    mounted.current = true;
    commandGeneration.current += 1;
    activeLoad.current?.controller.abort();
    activeLoad.current = null;
    setOverview(null);
    setCompatibility(null);
    setRuntime(null);
    setState("loading");
    setBusy("");
    setMessage("");
    setRemote(null);
    setRemoteError("");
    setLookupBusy(false);
    setChosenFile("");
    void load("reload", context);
    const handle = window.setInterval(() => void load("poll", context), 5000);
    return () => {
      window.clearInterval(handle);
      if (contextGeneration.current === context) {
        mounted.current = false;
        commandGeneration.current += 1;
        activeLookup.current?.abort();
        activeLookup.current = null;
      }
      if (activeLoad.current?.context === context) {
        activeLoad.current.controller.abort();
        activeLoad.current = null;
      }
    };
  }, [load]);

  async function run(label: string, action: () => Promise<unknown>, okMessage: string | null) {
    const context = contextGeneration.current;
    const command = commandGeneration.current + 1;
    commandGeneration.current = command;
    if (!isCurrentContext(context)) return;
    setBusy(label);
    setMessage("");
    try {
      await action();
      if (!isCurrentContext(context) || commandGeneration.current !== command) return;
      if (okMessage) setMessage(okMessage);
      await load("reload", context);
    } catch (caught) {
      if (!isCurrentContext(context) || commandGeneration.current !== command) return;
      setMessage(operationFailure(caught, label));
    } finally {
      if (isCurrentContext(context) && commandGeneration.current === command) setBusy("");
    }
  }

  function commandDownload(
    action: "pause" | "resume" | "retry" | "cancel",
    download: DownloadStatus,
  ) {
    if (action === "cancel" && !window.confirm(
      `Cancel ${download.filename}? Its app-owned partial bytes will be deleted; installed models and unrelated files are not changed.`,
    )) return;
    const execute = () => {
      if (action === "pause" && transport.pauseLocalModelDownload) {
        return transport.pauseLocalModelDownload(download.download_id, download.status_revision);
      }
      if (action === "resume" && transport.resumeLocalModelDownload) {
        return transport.resumeLocalModelDownload(download.download_id, download.status_revision);
      }
      if (action === "retry" && transport.retryLocalModelDownload) {
        return transport.retryLocalModelDownload(download.download_id, download.status_revision);
      }
      if (action === "cancel" && transport.cancelLocalModelDownload) {
        return transport.cancelLocalModelDownload(download.download_id, download.status_revision);
      }
      return Promise.reject(new Error("download command unavailable"));
    };
    const success = {
      pause: "Pause requested. The current network chunk will stop before more bytes are written.",
      resume: "Resume requested from the verified local partial.",
      retry: "Retry requested after a fresh provenance and disk-space check.",
      cancel: "Cancellation requested. Completion waits for partial-file cleanup.",
    }[action];
    void run(`download-${action}`, execute, success);
  }

  function changeRepository(value: string) {
    activeLookup.current?.abort();
    activeLookup.current = null;
    setLookupBusy(false);
    setRepoId(value);
    setRemoteError("");
    setRemote(null);
    setChosenFile("");
    setAlias("");
  }

  async function lookupRemote(repo?: string, preferFile?: string) {
    const target = (repo ?? repoId).trim();
    changeRepository(target);
    if (!target) return;
    const context = contextGeneration.current;
    const controller = new AbortController();
    activeLookup.current = controller;
    const ownsResult = () => isCurrentContext(context) && activeLookup.current === controller && !controller.signal.aborted;
    setLookupBusy(true);
    try {
      const files = await transport.getLocalModelRemoteFiles(target, controller.signal);
      if (!ownsResult()) return;
      setRemote(files);
      const eligible = files.files.filter((f) => f.eligible);
      const preferred = preferFile ? files.files.find((f) => f.filename === preferFile) : undefined;
      const pick = preferred
        ?? eligible.find((f) => /q4_k_m/i.test(f.filename))
        ?? eligible.find((f) => /iq4|q4/i.test(f.filename))
        ?? eligible[0]
        ?? files.files[0];
      if (pick) { setChosenFile(pick.filename); setAlias(defaultAlias(pick.filename)); }
    } catch (caught) {
      if (!ownsResult()) return;
      setRemoteError(caught instanceof TransportError && caught.status === 409
        ? "huggingface_hub is not installed in this environment (pip install -e \".[models]\")."
        : "The repository could not be read. Check the id, or accept its terms on Hugging Face while logged in.");
    } finally {
      if (ownsResult()) { activeLookup.current = null; setLookupBusy(false); }
    }
  }

  const selectedRemote = remote?.files.find((f) => f.filename === chosenFile) ?? null;
  const requiredDownloadBytes = selectedRemote?.size_bytes && overview
    ? selectedRemote.size_bytes + overview.download_reserve_bytes
    : null;
  const storageFitsDownload = Boolean(
    overview
    && requiredDownloadBytes !== null
    && overview.storage_free_bytes !== null
    && overview.storage_free_bytes !== undefined
    && overview.storage_free_bytes >= requiredDownloadBytes,
  );
  const downloadIdentityEligible = Boolean(
    remote?.revision_pinned && remote.revision && remote.license_id
    && remote.gated !== true
    && remote.license_admission === "allowed"
    && selectedRemote?.eligible && selectedRemote.sha256 && selectedRemote.size_bytes,
  );
  const downloadable = Boolean(
    downloadIdentityEligible
    && storageFitsDownload
    && overview?.download_ledger_error_code === null,
  );

  if (state === "loading") {
    return (
      <section aria-labelledby="local-models-title" className="local-models">
        <LocalModelsHeader />
        <p className="local-models__note">Looking at this machine…</p>
      </section>
    );
  }
  if (state === "unavailable") {
    return (
      <section aria-labelledby="local-models-title" className="local-models">
        <LocalModelsHeader />
        <p className="local-models__note">Local models are not available in this runtime.</p>
      </section>
    );
  }
  if (state === "error" || !overview) {
    return (
      <section aria-labelledby="local-models-title" className="local-models">
        <LocalModelsHeader />
        <p className="local-models__note" role="alert">The model list could not be verified.</p>
        <button className="button button--ghost" onClick={() => { setState("loading"); void load("reload", contextGeneration.current); }} type="button">Retry model list</button>
      </section>
    );
  }

  const hw = overview.hardware;
  const coordinatorTransition = runtime?.state === "draining"
    || runtime?.state === "unloading"
    || runtime?.state === "loading";
  const coordinatorCleanupBlocked = runtime?.state === "cleanup_unknown"
    || runtime?.state === "quarantined";
  const coordinatorMutationBlocked = coordinatedLifecycle && (
    runtime === null
    || coordinatorTransition
    || coordinatorCleanupBlocked
    || (runtime.active_requests ?? 0) > 0
  );
  const displayedModels = coordinatedLifecycle && runtime
    ? overview.models.map((item) => {
        const served = runtime.state === "ready" && runtime.served?.alias === item.record.alias;
        if (served && runtime.served) {
          return {
            ...item,
            runtime: {
              state: "running" as const,
              device: runtime.served.device,
              gpu_layers: runtime.served.gpu_layers,
              context_size: runtime.served.context_size,
              started_at: runtime.served.started_at,
              last_error_code: null,
              pid: runtime.served.pid,
              fast_attention: item.runtime.fast_attention,
              tool_calling: item.runtime.tool_calling,
            },
          };
        }
        const failed = runtime.state === "failed" && runtime.requested?.alias === item.record.alias;
        return {
          ...item,
          runtime: {
            state: failed ? "failed" as const : "stopped" as const,
            device: null,
            gpu_layers: null,
            context_size: null,
            started_at: null,
            last_error_code: failed ? runtime.last_error_code : null,
            pid: null,
            fast_attention: null,
            tool_calling: null,
          },
        };
      })
    : overview.models;
  return (
    <section aria-labelledby="local-models-title" className="local-models">
      <LocalModelsHeader />

      <div className="local-models__grid">
        <article className="local-models__card">
          <h2>Hardware</h2>
          <dl>
            <div><dt>GPU</dt><dd>{hw.gpu_name ?? "none detected"}</dd></div>
            <div><dt>VRAM</dt><dd>{hw.gpu_memory_mb ? `${mb(hw.gpu_memory_free_mb)} free of ${mb(hw.gpu_memory_mb)}` : "—"}</dd></div>
            <div><dt>RAM</dt><dd>{mb(hw.ram_mb)}</dd></div>
          </dl>
          <p className="local-models__hint">
            Device controls use the server's current model-size, layer-count, context and free-memory preflight.
            A successful text probe confirms execution, not the physical tensor placement.
          </p>
          <p className="local-models__hint">Storage: <code>{overview.storage_root}</code> (set <code>PROMPT_ENHANCER_LOCAL_MODELS_DIR</code> or the <code>local-models.path</code> file in the app home to keep weights on another drive).</p>
        </article>
        <article className="local-models__card" data-state={overview.runtime_available ? "ok" : "missing"}>
          <h2>Runtime</h2>
          {overview.runtime_available ? (
            <dl>
              <div><dt>llama-server</dt><dd><code>{hw.llama_server_path}</code></dd></div>
              <div><dt>Version</dt><dd>{hw.llama_server_version ?? "unknown"}</dd></div>
              <div><dt>Adapter</dt><dd>{compatibility?.adapter.adapter_version ?? "compatibility receipt unavailable"}</dd></div>
              <div><dt>Binary identity</dt><dd>{compatibility?.adapter.runtime_binary_sha256
                ? `sha256 ${shortId(compatibility.adapter.runtime_binary_sha256)}`
                : "unknown"}</dd></div>
            </dl>
          ) : (
            <>
              <p><strong>llama.cpp is not installed</strong> (no <code>llama-server</code> on PATH).</p>
              <p className="local-models__hint">
                Install the official llama.cpp release for Windows with CUDA, then either put <code>llama-server.exe</code> on your PATH or set
                <code> PROMPT_ENHANCER_LLAMA_SERVER</code> to its full path and restart the app. The app never downloads or runs a binary on its own.
              </p>
            </>
          )}
        </article>
      </div>

      {overview.download_ledger_error_code && (
        <p className="local-models__note" role="alert">
          The durable download recovery ledger could not be verified. Installed models remain visible, but new transfers and recovery commands are blocked so the unreadable local record is not overwritten.
        </p>
      )}

      {coordinatedLifecycle && runtime && (
        <article
          aria-label="Shared model runtime lifecycle"
          className="local-models__coordinator"
          data-state={runtime.state}
        >
          <header>
            <span>
              <small>One app-owned process</small>
              <strong>Shared runtime {coordinatorStateLabel(runtime.state)}</strong>
            </span>
            <span className="local-models__state">Revision {runtime.revision}</span>
          </header>
          <dl>
            <div><dt>Requested</dt><dd>{runtime.requested?.alias ?? "None"}</dd></div>
            <div><dt>Served</dt><dd>{runtime.served?.alias ?? "None"}</dd></div>
            <div><dt>Active requests</dt><dd>{runtime.active_requests}</dd></div>
            <div><dt>Cleanup</dt><dd>{runtime.cleanup.state.replaceAll("_", " ")}</dd></div>
            <div><dt>Placement evidence</dt><dd>Runtime arguments only · actual offload not measured</dd></div>
          </dl>
          {runtime.state === "draining" && (
            <p role="status">An inference request is still active. Switching and unloading remain disabled until it settles.</p>
          )}
          {runtime.state === "loading" && (
            <p role="status">The selected process is starting and must pass health and text-capability checks before it is ready.</p>
          )}
          {runtime.state === "unloading" && (
            <p role="status">The previous process is unloading. A replacement cannot start until cleanup evidence settles.</p>
          )}
          {coordinatorCleanupBlocked && (
            <p role="alert">Runtime cleanup is unconfirmed. No model can start until process and accelerator-memory ownership are resolved.</p>
          )}
        </article>
      )}

      <section aria-labelledby="installed-models-title" className="local-models__section">
        <h2 id="installed-models-title">Installed models</h2>
        {displayedModels.length === 0 && <p className="local-models__note">No model yet. Add one below.</p>}
        <ul className="local-models__list">
          {displayedModels.map((item: LocalModelStatus, modelIndex) => {
            const preferredDevice = devices[item.record.alias] ?? item.record.default_device;
            const preferredPlacement = item.placement.options.find(
              (option) => option.device === preferredDevice,
            );
            const fallbackPlacement = item.placement.options.find(
              (option) => option.state !== "blocked",
            );
            const device = preferredPlacement?.state === "blocked"
              ? fallbackPlacement?.device ?? preferredDevice
              : preferredDevice;
            const selectedPlacement = item.placement.options.find(
              (option) => option.device === device,
            ) ?? null;
            const rawLayers = (layers[item.record.alias] ?? "").trim();
            const parsedLayers = /^[0-9]+$/u.test(rawLayers) ? Number(rawLayers) : null;
            const maximumLayers = selectedPlacement?.recommended_gpu_layers ?? null;
            const layerInputInvalid = device === "split" && rawLayers !== "" && (
              parsedLayers === null
              || parsedLayers < 1
              || maximumLayers === null
              || parsedLayers > maximumLayers
            );
            const blockedPlacementSummary = item.placement.options
              .filter((option) => option.state === "blocked")
              .map((option) => {
                const label = DEVICES.find((candidate) => candidate.value === option.device)?.title ?? option.device;
                return `${label} unavailable: ${PLACEMENT_REASON_TEXT[option.reason_code]}`;
              })
              .join(" ");
            const running = item.runtime.state === "running";
            const servedByCoordinator = coordinatedLifecycle
              ? runtime?.served?.alias === item.record.alias
              : running;
            const startBusyKey = `runtime:start:${item.record.alias}`;
            const stopBusyKey = `runtime:stop:${item.record.alias}`;
            const lifecycleDisabled = busy !== ""
              || !overview.runtime_available
              || coordinatorMutationBlocked;
            const placementNoteId = `local-model-placement-${modelIndex}`;
            const compatibilityItem: LocalModelCompatibility | null = compatibility?.models.find(
              (model) => model.alias === item.record.alias,
            ) ?? null;
            return (
              <li key={item.record.alias} className="local-models__model" data-state={item.runtime.state}>
                <div className="local-models__model-head">
                  <div>
                    <strong>{item.record.display_name}</strong>
                    <small>{item.record.alias} · {gb(item.record.size_bytes)}{item.record.source_repo ? ` · ${item.record.source_repo}` : ""}</small>
                    <small className="local-models__provenance" data-verified={item.record.provenance_verified ? "yes" : "no"}>{provenanceLine(item.record)}</small>
                    <small className="local-models__compatibility" data-state={compatibilityItem?.state ?? "unknown"}>
                      Executable compatibility: {compatibilityItem
                        ? `${compatibilityItem.state} · ${COMPATIBILITY_REASON_TEXT[compatibilityItem.reason_code] ?? compatibilityItem.reason_code}`
                        : "unknown · compatibility receipt unavailable"}
                    </small>
                    <small>
                      Architecture {compatibilityItem?.architecture ?? item.record.architecture ?? "unknown"}
                      {` · tokenizer ${compatibilityItem?.tokenizer_model ?? item.record.tokenizer_model ?? "unknown"}`}
                      {compatibilityItem ? ` · context counter ${compatibilityItem.context_counter_state.replaceAll("_", " ")}` : ""}
                    </small>
                  </div>
                  <span className={`local-models__state local-models__state--${item.runtime.state}`}>
                    {item.runtime.state}{item.runtime.device ? ` · requested ${item.runtime.device}${item.runtime.gpu_layers !== null && item.runtime.gpu_layers !== undefined ? ` · ${item.runtime.gpu_layers} GPU layers` : ""}` : ""}
                  </span>
                </div>
                <div className="local-models__device" role="radiogroup" aria-label={`Device for ${item.record.display_name}`}>
                  {DEVICES.map((option) => {
                    const admission = item.placement.options.find(
                      (candidate) => candidate.device === option.value,
                    );
                    const blocked = admission?.state === "blocked";
                    return (
                      <label
                        key={option.value}
                        className={`${device === option.value ? "is-chosen" : ""}${blocked ? " is-blocked" : ""}`.trim()}
                        title={`${option.hint}. ${admission ? PLACEMENT_REASON_TEXT[admission.reason_code] : "Admission evidence unavailable."}`}
                      >
                        <input
                          aria-describedby={lifecycleDisabled || blocked ? placementNoteId : undefined}
                          checked={device === option.value}
                          disabled={lifecycleDisabled || blocked}
                          name={`device-${item.record.alias}`}
                          onChange={() => setDevices((prev) => ({ ...prev, [item.record.alias]: option.value }))}
                          type="radio"
                          value={option.value}
                        />
                        <span>{option.title}</span>
                      </label>
                    );
                  })}
                </div>
                <p className="local-models__placement-note" data-state={selectedPlacement?.state ?? "blocked"} id={placementNoteId}>
                  {selectedPlacement
                    ? PLACEMENT_REASON_TEXT[selectedPlacement.reason_code]
                    : "Placement admission evidence is unavailable."}
                  {selectedPlacement?.recommended_gpu_layers !== null
                    && selectedPlacement?.recommended_gpu_layers !== undefined
                    && device !== "cpu"
                    ? ` Recommended maximum: ${selectedPlacement.recommended_gpu_layers} GPU layers.`
                    : ""}
                  {blockedPlacementSummary ? ` ${blockedPlacementSummary}` : ""}
                  {lifecycleDisabled
                    ? busy !== ""
                      ? " Wait for the current model operation to finish before changing placement."
                      : !overview.runtime_available
                        ? " Placement cannot be changed because the local model runtime is unavailable."
                        : " Placement cannot be changed until the shared runtime transition or cleanup is resolved."
                    : ""}
                </p>
                {device === "split" && (
                  <label className="local-models__layers">
                    <span>GPU layers{item.record.layer_count ? ` of ${item.record.layer_count}` : ""} (blank = admitted estimate{item.record.default_gpu_layers !== null && item.record.default_gpu_layers !== undefined ? `, remembered ${item.record.default_gpu_layers}` : ""})</span>
                    <input
                      aria-label={`GPU layers for ${item.record.display_name}`}
                      aria-invalid={layerInputInvalid}
                      disabled={lifecycleDisabled || selectedPlacement?.state !== "available"}
                      inputMode="numeric"
                      max={maximumLayers ?? undefined}
                      min={1}
                      onChange={(e) => setLayers((prev) => ({ ...prev, [item.record.alias]: e.currentTarget.value }))}
                      placeholder={item.record.default_gpu_layers !== null && item.record.default_gpu_layers !== undefined ? String(item.record.default_gpu_layers) : "auto"}
                      type="number"
                      value={layers[item.record.alias] ?? ""}
                    />
                  </label>
                )}
                <div className="local-models__actions">
                  <button
                    className="button button--primary"
                    disabled={lifecycleDisabled || selectedPlacement?.state === "blocked" || layerInputInvalid}
                    onClick={() => {
                      const gpuLayers = device === "cpu"
                        ? 0
                        : device === "split" && parsedLayers !== null
                          ? parsedLayers
                          : null;
                      if (coordinatedLifecycle && runtime && transport.switchLocalRuntime) {
                        void run(startBusyKey, () => transport.switchLocalRuntime!({
                          alias: item.record.alias,
                          expected_revision: runtime.revision,
                          device,
                          gpu_layers: gpuLayers,
                          context_size: item.record.context_size,
                          remember: true,
                          fast_attention: true,
                          tool_calling: true,
                        }), `Shared runtime ready: ${item.record.display_name}; requested ${device} placement. Text execution is verified, but actual offload is not measured.`);
                        return;
                      }
                      const request = {
                        device,
                        remember: true,
                        fast_attention: true,
                        tool_calling: true,
                        ...(device === "split" && gpuLayers !== null ? { gpu_layers: gpuLayers } : {}),
                      };
                      void run(item.record.alias, () => transport.activateLocalModel(item.record.alias, request), `${item.record.display_name} is running with requested ${device} placement. Actual offload is not measured.`);
                    }}
                    type="button"
                  >
                    {coordinatedLifecycle
                      ? busy === startBusyKey
                        ? "Starting shared runtime…"
                        : runtime?.served
                          ? servedByCoordinator ? "Restart shared runtime" : "Switch shared runtime"
                          : "Start shared runtime"
                      : busy === item.record.alias ? "Starting…" : running ? "Restart" : "Activate"}
                  </button>
                  {coordinatedLifecycle ? servedByCoordinator && runtime && transport.stopLocalRuntime ? (
                    <button
                      className="button button--ghost"
                      disabled={lifecycleDisabled}
                      onClick={() => void run(stopBusyKey, () => transport.stopLocalRuntime!({
                        alias: item.record.alias,
                        expected_revision: runtime.revision,
                      }), "Shared runtime stopped. Chats and model registration were not changed.")}
                      type="button"
                    >
                      {busy === stopBusyKey ? "Unloading shared runtime…" : "Unload shared runtime"}
                    </button>
                  ) : null : (
                    <button className="button button--ghost" disabled={busy !== "" || !running} onClick={() => void run(item.record.alias, () => transport.deactivateLocalModel(item.record.alias), `${item.record.display_name} stopped.`)} type="button">
                      Deactivate
                    </button>
                  )}
                  <button className="button button--ghost" disabled={busy !== "" || coordinatorMutationBlocked || (coordinatedLifecycle && servedByCoordinator)} onClick={() => { if (window.confirm(`Remove ${item.record.display_name} from the registry? The weights stay on disk.`)) void run(item.record.alias, () => transport.removeLocalModel(item.record.alias, false), "Removed."); }} type="button">
                    Remove
                  </button>
                </div>
                {coordinatedLifecycle && servedByCoordinator && (
                  <p className="local-models__hint">Unload the shared runtime before removing this model registration.</p>
                )}
                <p className="local-models__endpoint">
                  Endpoint: <code>POST {item.endpoint_path}</code> (OpenAI chat format, <code>stream: true</code> supported; app token as header or bearer) · base URL for OpenAI clients: <code>/v1/local-models/{item.record.alias}/v1</code>
                  {item.runtime.last_error_code ? <span className="local-models__error"> · last error: {item.runtime.last_error_code.replace(/_/g, " ")}</span> : null}
                </p>
              </li>
            );
          })}
        </ul>
      </section>

      <LocalModelChatPanel models={displayedModels} transport={transport} />

      <section aria-labelledby="add-model-title" className="local-models__section">
        <h2 id="add-model-title">Add a model</h2>
        <div className="local-models__recommended">
          <h3>Common GGUF starting points</h3>
          <ul>
            {RECOMMENDED.map((item, recommendationIndex) => {
              const installed = overview.models.some((m) => m.record.source_file === item.file);
              const disabledReasonId = `local-model-recommendation-disabled-${recommendationIndex}`;
              return (
                <li key={item.file}>
                  <div>
                    <strong>{item.label}</strong>
                    <small>{item.note} · {item.repo}</small>
                  </div>
                  <button
                    aria-describedby={installed || busy !== "" ? disabledReasonId : undefined}
                    className="button button--ghost"
                    disabled={installed || busy !== ""}
                    onClick={() => void lookupRemote(item.repo, item.file)}
                    type="button"
                  >
                    {installed ? "Installed" : "Look up"}
                  </button>
                  {(installed || busy !== "") && (
                    <small className="sr-only" id={disabledReasonId}>
                      {installed ? "This exact model file is already registered." : "Wait for the current model operation to finish."}
                    </small>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="local-models__hint">
            These are general reference examples, not recommendations or performance measurements for this machine. Compare the
            hardware summary above with the exact pinned file size. Nothing downloads from this list: choosing one looks the repository up, and the
            download button below only appears once the server has pinned an immutable revision, an exact size, a sha256
            and an admitted licence for the file you picked. Other repositories: paste any GGUF repo id below.
          </p>
        </div>
        <div className="local-models__add">
          <label>
            <span>Hugging Face repository (GGUF)</span>
            <span className="local-models__inline">
              <input aria-label="Hugging Face repository" onChange={(e) => changeRepository(e.currentTarget.value)} type="text" value={repoId} />
              <button aria-describedby={lookupBusy || !repoId.trim() ? "local-model-repository-requirement" : undefined} className="button button--ghost" disabled={lookupBusy || !repoId.trim()} onClick={() => void lookupRemote()} type="button">Show files</button>
            </span>
            <small className="sr-only" id="local-model-repository-requirement">{lookupBusy ? "Wait for the current repository lookup to finish." : "Enter a Hugging Face repository before showing its files."}</small>
          </label>
          {lookupBusy && <p className="local-models__note" role="status">Looking up repository…</p>}
          {remoteError && <p className="local-models__error" role="alert">{remoteError}</p>}
          {remote && !remote.revision_pinned && (
            <p className="local-models__error" role="alert">
              This repository cannot be pinned, so nothing here can be downloaded:{" "}
              {IDENTITY_UNAVAILABLE_TEXT[remote.unavailable_reason ?? ""] ?? "its identity could not be resolved"}.
            </p>
          )}
          {remote && remote.revision_pinned && (
            <>
              <dl className="local-models__provenance-card">
                <div><dt>Repository</dt><dd>{remote.repo_id}</dd></div>
                <div><dt>Revision</dt><dd><code>{remote.revision}</code> (immutable commit)</dd></div>
                <div>
                  <dt>Licence</dt>
                  <dd>
                    {remote.license_id ?? "not declared"} · {LICENSE_ADMISSION_TEXT[remote.license_admission] ?? remote.license_admission}
                    {" "}(<code>{remote.license_policy_version}</code>)
                  </dd>
                </div>
              </dl>
              <label>
                <span>File (4-bit is a common starting point; verify fit)</span>
                <select aria-label="Model file" onChange={(e) => { setChosenFile(e.currentTarget.value); setAlias(defaultAlias(e.currentTarget.value)); }} value={chosenFile}>
                  {remote.files.map((f) => (
                    <option key={f.filename} value={f.filename}>
                      {f.filename} · {gb(f.size_bytes)}{f.eligible ? "" : " · not downloadable"}
                    </option>
                  ))}
                </select>
              </label>
              {selectedRemote && (
                <p className="local-models__hint" data-eligible={selectedRemote.eligible ? "yes" : "no"}>
                  {selectedRemote.eligible
                    ? `sha256 ${selectedRemote.sha256} · exactly ${selectedRemote.size_bytes} bytes at this revision; the file is verified against both after downloading.`
                    : `This file cannot be downloaded by the app: ${INELIGIBLE_TEXT[selectedRemote.ineligible_reason ?? ""] ?? "its identity could not be bound to this revision"}.`}
                </p>
              )}
              {downloadIdentityEligible && requiredDownloadBytes !== null && (
                <p className="local-models__hint" data-capacity={storageFitsDownload ? "admitted" : "blocked"}>
                  {overview.storage_free_bytes === null || overview.storage_free_bytes === undefined
                    ? `Disk-space evidence is unavailable. The backend will not start a ${gb(selectedRemote?.size_bytes)} transfer without it.`
                    : storageFitsDownload
                      ? `${gb(overview.storage_free_bytes)} free; this transfer needs ${gb(requiredDownloadBytes)} including the safety reserve.`
                      : `This transfer needs ${gb(requiredDownloadBytes)} including the safety reserve, but only ${gb(overview.storage_free_bytes)} is free.`}
                </p>
              )}
              <label>
                <span>Alias (endpoint name)</span>
                <input aria-label="Alias" onChange={(e) => setAlias(e.currentTarget.value)} type="text" value={alias} />
              </label>
              {remote.gated && <p className="local-models__hint">This repository is gated. The app's automated downloader is public-only and will not use a cached login. If you accept the provider's terms, download the GGUF yourself and register the local file below.</p>}
              <button
                className="button button--primary"
                disabled={!downloadable || !alias || busy !== ""}
                onClick={() => {
                  if (!downloadable || !remote.revision || !remote.license_id || !selectedRemote?.sha256 || !selectedRemote.size_bytes) return;
                  const confirmed = [
                    `Download ${selectedRemote.filename} (${gb(selectedRemote.size_bytes)}, exactly ${selectedRemote.size_bytes} bytes) from ${remote.repo_id}?`,
                    `Revision: ${remote.revision}`,
                    `sha256: ${selectedRemote.sha256}`,
                    `Licence: ${remote.license_id} (${remote.license_policy_version})`,
                  ].join("\n");
                  if (!window.confirm(confirmed)) return;
                  void run("download", () => transport.startLocalModelDownload({
                    repo_id: remote.repo_id,
                    filename: selectedRemote.filename,
                    confirmed_size_bytes: selectedRemote.size_bytes ?? 0,
                    confirmed_revision: remote.revision ?? "",
                    confirmed_sha256: selectedRemote.sha256 ?? "",
                    confirmed_license: remote.license_id ?? "",
                    alias,
                    default_device: "split",
                  }), "Download started; it appears below and in the list when finished.");
                }}
                type="button"
              >
                {downloadable
                  ? `Download ${gb(selectedRemote?.size_bytes)}`
                  : overview.download_ledger_error_code
                    ? "Download recovery blocked"
                    : downloadIdentityEligible && overview.storage_free_bytes === null
                      ? "Disk space unavailable"
                      : downloadIdentityEligible && !storageFitsDownload
                        ? "Not enough disk space"
                        : "Download unavailable"}
              </button>
            </>
          )}
          {transport.scanLocalModelFolder && (
            <label>
              <span>…or point at a folder: every GGUF in it (one level deep) gets registered, nothing is moved</span>
              <span className="local-models__inline">
                <input aria-label="Model folder" onChange={(e) => setFolderPath(e.currentTarget.value)} placeholder="for example D:\\models" type="text" value={folderPath} />
                <button aria-describedby={!folderPath.trim() || busy !== "" ? "local-model-folder-requirement" : undefined} className="button button--ghost" disabled={!folderPath.trim() || busy !== ""} onClick={() => void run("scan", async () => { const result = await transport.scanLocalModelFolder!(folderPath.trim()); setMessage(`${result.registered.length} registered, ${result.skipped_existing} already known, ${result.skipped_invalid} skipped.`); }, null)} type="button">Scan folder</button>
              </span>
              <small className="sr-only" id="local-model-folder-requirement">{busy !== "" ? "Wait for the current model operation to finish." : "Enter a local model folder before scanning it."}</small>
            </label>
          )}
          <label>
            <span>…or register a GGUF file already on this machine</span>
            <span className="local-models__inline">
              <input aria-label="Local GGUF path" onChange={(e) => setLocalPath(e.currentTarget.value)} placeholder="for example D:\\models\\example-q4_k_m.gguf" type="text" value={localPath} />
              <button aria-describedby={!localPath.trim() || busy !== "" ? "local-model-file-requirement" : undefined} className="button button--ghost" disabled={!localPath.trim() || busy !== ""} onClick={() => void run("add", () => transport.addLocalModel({ alias: defaultAlias(localPath.trim().split(/[\\/]/).pop() ?? "model"), path: localPath.trim(), mmproj_path: mmprojPath.trim() || null, default_device: "split", context_size: 8192 }), "Registered.")} type="button">Register</button>
            </span>
            <small className="sr-only" id="local-model-file-requirement">{busy !== "" ? "Wait for the current model operation to finish." : "Enter the absolute path to a local GGUF file before registering it."}</small>
          </label>
          <label>
            <span>Matching multimodal projector (optional, explicit)</span>
            <input
              aria-describedby="local-mmproj-help"
              aria-label="Local multimodal projector path"
              onChange={(event) => setMmprojPath(event.currentTarget.value)}
              placeholder="for example D:\\models\\mmproj-example-f16.gguf"
              type="text"
              value={mmprojPath}
            />
            <small id="local-mmproj-help">Required for image or audio input. The live llama.cpp runtime is still probed before those controls are enabled.</small>
          </label>
        </div>
        {overview.downloads.length > 0 && (
          <ul className="local-models__downloads" aria-label="Downloads">
            {overview.downloads.map((d) => {
              const mayPause = ["queued", "downloading"].includes(d.state) && transport.pauseLocalModelDownload;
              const mayResume = ["paused", "interrupted"].includes(d.state) && transport.resumeLocalModelDownload;
              const mayRetry = ["failed", "cancelled"].includes(d.state) && transport.retryLocalModelDownload;
              const mayCancel = ["queued", "downloading", "pausing", "paused", "interrupted", "failed"].includes(d.state)
                && transport.cancelLocalModelDownload;
              const transition = ["pausing", "cancelling"].includes(d.state);
              return (
                <li key={d.download_id} data-state={d.state}>
                  <Icon name={d.state === "completed" ? "check" : d.state === "paused" ? "pause" : ["failed", "interrupted", "cancelled"].includes(d.state) ? "x" : "clock"} />
                  <div className="local-models__download-body">
                    <span>
                      <strong>{d.filename}</strong> · {d.state.replaceAll("_", " ")} · attempt {d.attempt}
                      {d.error_code ? ` · ${DOWNLOAD_ERROR_TEXT[d.error_code] ?? d.error_code.replaceAll("_", " ")}` : ""}
                    </span>
                    <progress
                      aria-label={`${d.filename} download progress`}
                      max={d.bytes_total || 1}
                      value={d.bytes_done}
                    />
                    <small>
                      {gb(d.bytes_done)} of {gb(d.bytes_total)}
                      {d.partial_retained ? " · resumable partial retained" : ""}
                      {d.revision ? ` · revision ${shortId(d.revision)}` : ""}
                      {d.sha256 ? ` · sha256 ${shortId(d.sha256)}` : ""}
                    </small>
                  </div>
                  <div className="local-models__download-actions">
                    {mayPause && <button aria-label={`Pause ${d.filename} download`} className="button button--ghost" disabled={busy !== ""} onClick={() => commandDownload("pause", d)} type="button">Pause</button>}
                    {mayResume && <button aria-label={`Resume ${d.filename} download`} className="button button--ghost" disabled={busy !== ""} onClick={() => commandDownload("resume", d)} type="button">Resume</button>}
                    {mayRetry && <button aria-label={`Retry ${d.filename} download`} className="button button--ghost" disabled={busy !== ""} onClick={() => commandDownload("retry", d)} type="button">Retry</button>}
                    {mayCancel && <button aria-label={`Cancel ${d.filename} download`} className="button button--ghost" disabled={busy !== "" || d.state === "pausing"} onClick={() => commandDownload("cancel", d)} type="button">Cancel</button>}
                    {transition && <small aria-live="polite">{d.state === "pausing" ? "Pausing safely…" : "Cleaning partial…"}</small>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <p className="local-models__message" aria-live="polite" role="status">{message}</p>
    </section>
  );
}
