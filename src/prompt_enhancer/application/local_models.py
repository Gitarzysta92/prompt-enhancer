"""Local model runtimes: registry, device choice, loopback endpoints (ADR 0013).

A person installs a model (GGUF weights), activates it on ``cpu``, ``gpu`` or
``split`` (partial GPU offload), and the app's global runtime coordinator owns
at most one llama.cpp ``llama-server`` on a loopback port. The app's authenticated
API proxies an OpenAI-compatible chat endpoint to it, so every installed
model is usable as a regular local LLM for small tasks and by the
model-judge lane. Inference stays on the machine and no runtime port is exposed
beyond loopback. Repository discovery and a user-confirmed model download are
explicit Hugging Face network operations. The automated path is public-only;
it passes ``token=False`` and never reads a cached Hugging Face login.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import errno
from functools import partial
import hashlib
import hmac
import http.client
import io
import ipaddress
import inspect
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Literal
import urllib.error
import urllib.request

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .model_reply import model_json_object
from .owned_process import run_owned_process
from .runtime_cancellation import current_runtime_cancellation


LOCAL_MODELS_CONTRACT_VERSION = "local-models.v1"
LOCAL_RUNTIME_COORDINATOR_CONTRACT_VERSION = "local-runtime-coordinator.v2"
LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION = "local-runtime-multimodal-probe.v2"
LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION = "local-model-compatibility.v1"
LOCAL_MODEL_PLACEMENT_CONTRACT_VERSION = "local-model-placement.v1"
LOCAL_MODEL_RUNTIME_ADAPTER_ID = "llama.cpp-openai-gguf"
LOCAL_MODEL_RUNTIME_ADAPTER_VERSION = "llama.cpp-openai-gguf.v1"
LOCAL_MODEL_METADATA_READER_VERSION = "gguf-metadata.v1"
REGISTRY_FILE_NAME = "registry.json"
DOWNLOAD_LEDGER_FILE_NAME = "downloads.json"
WEIGHTS_DIR_NAME = "weights"
LLAMA_SERVER_ENV = "PROMPT_ENHANCER_LLAMA_SERVER"
ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DEFAULT_CONTEXT_SIZE = 8192
MAX_CONTEXT_SIZE = 131072
HEALTH_TIMEOUT_SECONDS = 240
CHAT_TIMEOUT_SECONDS = 600
MAX_CHAT_BODY_BYTES = 24 * 1024 * 1024
#: Upper bound on one streamed reply so a runaway runtime cannot stream forever.
MAX_CHAT_STREAM_BYTES = 16 * 1024 * 1024
#: Names that the HTTP surface uses for fixed routes under /v1/local-models.
RESERVED_ALIASES = frozenset(
    {"openai", "downloads", "remote-files", "runtime", "scan-folder"}
)
#: How often the download worker samples the partial file for progress.
DOWNLOAD_PROGRESS_INTERVAL_SECONDS = 2.0
DOWNLOAD_LEDGER_PROGRESS_INTERVAL_SECONDS = 1.0
#: Free-space reserve kept after admitting a transfer.  Downloads are refused
#: before a network request unless the remaining artifact bytes plus this
#: reserve are currently available on the filesystem that owns the model root.
DOWNLOAD_DISK_RESERVE_BYTES = 512 * 1024 ** 2
#: The ledger is private local state, stored beside the already-sensitive model
#: registry and weights.  It contains no provider credentials or transcript text.
DOWNLOAD_LEDGER_CONTRACT_VERSION = "local-model-downloads.v1"
#: Versioned boundary around the one Hugging Face internal used for cooperative
#: cancellation.  The adapter validates both the package version and signature.
HUGGINGFACE_TRANSFER_ADAPTER_VERSION = "huggingface-hub-http-get-0.36.v1"
HUGGINGFACE_TRANSFER_COMPATIBLE_PREFIX = "0.36."
#: Rough per-layer budget used to estimate a split: weight bytes / layers plus
#: a fixed headroom for the KV cache and scratch buffers.
SPLIT_VRAM_HEADROOM_BYTES = 2 * 1024 ** 3
#: Chunk size for the post-download digest; the file is never held in memory.
DIGEST_CHUNK_BYTES = 4 * 1024 * 1024

#: A Hub commit oid: the only revision this app treats as immutable. Branch and
#: tag names ("main", "latest") are mutable and are never recorded as pinned.
COMMIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REPO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PORTABLE_GGUF_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,294}\.gguf$")
_WINDOWS_RESERVED_FILE_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)

# ``llama-server`` is a console-subsystem executable on Windows. Redirecting
# its standard handles does not stop Windows from creating a visible console;
# CREATE_NO_WINDOW is required at the process boundary. Keep the literal
# fallback so this policy remains testable on non-Windows CI where Python does
# not expose the Windows-only subprocess constant.
_WINDOWS_CREATE_NO_WINDOW = 0x08000000
_WINDOWS_OUT_OF_MEMORY_EXIT_CODES = frozenset({0xC0000017, 0xC000012D})
_RUNTIME_ENVIRONMENT_ALLOWLIST = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
    "CUDA_PATH", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER",
    "OMP_NUM_THREADS", "LANG", "LC_ALL",
})
_LLAMA_SERVER_VERSION_CACHE_LOCK = threading.Lock()
_LLAMA_SERVER_VERSION_CACHE: tuple[tuple[str, int, int], str | None] | None = None


def _runtime_creation_flags(platform_name: str | None = None) -> int:
    """Return the console-free spawn policy for a local model runtime."""

    if (platform_name or os.name) != "nt":
        return 0
    return int(
        getattr(subprocess, "CREATE_NO_WINDOW", _WINDOWS_CREATE_NO_WINDOW)
    )


def runtime_exit_failure_code(exit_code: int, *, platform_name: str | None = None) -> str:
    """Classify an unexpected runtime exit from objective process evidence only.

    Windows NTSTATUS values are sometimes surfaced as signed Python integers,
    so classification normalizes to the documented unsigned 32-bit value.  A
    signal or arbitrary non-zero exit is *not* claimed to be OOM without that
    exact evidence.
    """

    normalized = int(exit_code) & 0xFFFFFFFF
    if (platform_name or os.name) == "nt" and normalized in _WINDOWS_OUT_OF_MEMORY_EXIT_CODES:
        return "runtime_out_of_memory"
    return "runtime_exited" if int(exit_code) == 0 else "runtime_crashed"


def _runtime_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Pass runtime mechanics, never ambient provider credentials."""

    values = source if source is not None else os.environ
    return {
        key: value
        for key, value in values.items()
        if key.upper() in _RUNTIME_ENVIRONMENT_ALLOWLIST
    }

#: Frozen repository admission policy for downloadable weights, version tagged so a
#: record says which revision of the policy admitted it. This is an operational
#: allow-list for *this* repository's automated downloader, not a legal conclusion:
#: it does not interpret licence terms, does not cover a repository's own extra
#: conditions, and says nothing about how model output may be used. Anything not
#: listed as admitted fails closed and needs a human to fetch the weights by hand.
LICENSE_POLICY_VERSION = "local-model-license-policy.v1"
#: Identifiers reviewed as permissive enough to fetch without a case-by-case decision.
ADMITTED_LICENSE_IDS = frozenset({
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "cc-by-4.0",
    "mit",
    "mpl-2.0",
    "unlicense",
})
#: Identifiers reviewed and refused for the automated path: bespoke community terms,
#: non-commercial or no-derivative clauses, and the Hub's "no real identifier" values.
REFUSED_LICENSE_IDS = frozenset({
    "bigscience-openrail-m",
    "cc-by-nc-2.0",
    "cc-by-nc-4.0",
    "cc-by-nc-nd-4.0",
    "cc-by-nc-sa-4.0",
    "cc-by-nd-4.0",
    "creativeml-openrail-m",
    "deepfloyd-if-license",
    "gemma",
    "llama2",
    "llama3",
    "llama3.1",
    "llama3.2",
    "llama3.3",
    "llama4",
    "openrail",
    "openrail++",
    "other",
    "unknown",
})
_LICENSE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,39}$")


class ModelFormat(StrEnum):
    GGUF = "gguf"


class DeviceMode(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    SPLIT = "split"


class PlacementAdmissionState(StrEnum):
    """Whether a placement can start from the current hardware snapshot."""

    AVAILABLE = "available"
    BLOCKED = "blocked"
    RECHECK_REQUIRED = "recheck_required"


class PlacementAdmissionReason(StrEnum):
    """Closed, content-free reasons behind one placement decision."""

    CPU_AVAILABLE = "cpu_available"
    ACCELERATOR_EVIDENCE_UNAVAILABLE = "accelerator_evidence_unavailable"
    MODEL_SIZE_UNAVAILABLE = "model_size_unavailable"
    LAYER_COUNT_UNAVAILABLE = "layer_count_unavailable"
    CONTEXT_EXCEEDS_MODEL_METADATA = "context_exceeds_model_metadata"
    GPU_ESTIMATE_FITS = "gpu_estimate_fits"
    GPU_ESTIMATE_EXCEEDS_FREE_MEMORY = "gpu_estimate_exceeds_free_memory"
    SPLIT_ESTIMATE_AVAILABLE = "split_estimate_available"
    SPLIT_ESTIMATE_EXCEEDS_FREE_MEMORY = "split_estimate_exceeds_free_memory"
    OWNED_RUNTIME_REQUIRES_CLEANUP_RECHECK = "owned_runtime_requires_cleanup_recheck"


class LicenseAdmission(StrEnum):
    """Outcome of the frozen repository admission policy for one repository."""

    #: The declared identifier is on the reviewed allow-list.
    ALLOWED = "allowed"
    #: The declared identifier was reviewed and refused for the automated path.
    NOT_ALLOWED = "not_allowed"
    #: A well-formed identifier nobody has reviewed for this repository yet.
    UNREVIEWED = "unreviewed"
    #: No identifier at all, or the repository contradicts itself about it.
    UNAVAILABLE = "unavailable"


class RuntimeState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class RuntimeCoordinatorState(StrEnum):
    IDLE = "idle"
    DRAINING = "draining"
    UNLOADING = "unloading"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    CLEANUP_UNKNOWN = "cleanup_unknown"
    QUARANTINED = "quarantined"


class RuntimeCleanupState(StrEnum):
    NOT_REQUIRED = "not_required"
    MEASURED = "measured"
    UNKNOWN = "unknown"
    FAILED = "failed"


class RuntimeCapabilityState(StrEnum):
    NOT_PROBED = "not_probed"
    VERIFIED = "verified"
    FAILED = "failed"


class LocalModelCompatibilityState(StrEnum):
    """Executable compatibility for one exact installed artifact."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class LocalModelCompatibilityReason(StrEnum):
    """Closed, content-free reasons behind a compatibility state."""

    LIVE_TEXT_PROBE_VERIFIED = "live_text_probe_verified"
    MODEL_NOT_EXECUTED = "model_not_executed"
    LIVE_TEXT_PROBE_FAILED = "live_text_probe_failed"
    RUNTIME_EXECUTION_FAILED = "runtime_execution_failed"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    ARTIFACT_MISSING = "artifact_missing"


class ContextAdmissionReason(StrEnum):
    """Why exact request context is unavailable, or why it was refused."""

    RUNTIME_NOT_SERVED = "runtime_not_served"
    NO_REQUEST_MEASURED = "no_request_measured"
    INPUT_COUNTER_UNAVAILABLE = "input_counter_unavailable"
    INPUT_COUNTER_INVALID = "input_counter_invalid"
    INPUT_COUNTER_FAILED = "input_counter_failed"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"


class LocalModelRecord(StrictModel):
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    display_name: str = Field(min_length=1, max_length=120)
    format: ModelFormat = ModelFormat.GGUF
    path: str = Field(min_length=1, max_length=1024)
    #: Optional matching libmtmd projector selected explicitly by the owner.
    #: A name is never used to infer model capability; the live runtime is
    #: probed after launch before any media control is enabled.
    mmproj_path: str | None = Field(default=None, min_length=1, max_length=1024)
    mmproj_size_bytes: int | None = Field(default=None, ge=1)
    source_repo: str | None = Field(default=None, max_length=200)
    source_file: str | None = Field(default=None, max_length=300)
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    #: Immutable Hub commit the weights came from. None on a manually registered
    #: file and on registry entries written before provenance was recorded: the
    #: app shows those as "provenance unavailable" and never invents a value.
    source_revision: str | None = Field(default=None, pattern=COMMIT_REVISION_PATTERN.pattern)
    #: Repository licence identifier read from that same immutable revision.
    source_license: str | None = Field(default=None, max_length=40, pattern=_LICENSE_ID_PATTERN.pattern)
    #: Version of the frozen admission policy that admitted the download.
    source_license_policy: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    #: True only when this app downloaded the file and matched digest, size and
    #: GGUF identity against metadata bound to ``source_revision``.
    provenance_verified: bool = False
    default_device: DeviceMode = DeviceMode.SPLIT
    #: Remembered split offload (layers on the GPU); None = estimate from free VRAM.
    default_gpu_layers: int | None = Field(default=None, ge=0, le=4096)
    context_size: int = Field(default=DEFAULT_CONTEXT_SIZE, ge=512, le=MAX_CONTEXT_SIZE)
    layer_count: int | None = Field(default=None, ge=1, le=4096)
    #: Selected, bounded metadata read from this exact GGUF. Missing metadata
    #: remains unknown; file names and repository names are never used to infer it.
    architecture: str | None = Field(default=None, min_length=1, max_length=120)
    tokenizer_model: str | None = Field(default=None, min_length=1, max_length=120)
    training_context_size: int | None = Field(default=None, ge=1, le=16_777_216)
    metadata_reader_version: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    added_at: datetime

    @model_validator(mode="after")
    def verified_provenance_is_complete(self) -> LocalModelRecord:
        """A verified flag is never accepted without the complete receipt.

        Older and manually registered rows may legitimately contain a partial
        source hint while ``provenance_verified`` is false. They remain
        readable, but cannot be relabelled as verified by editing one boolean.
        """

        if (self.mmproj_path is None) is not (self.mmproj_size_bytes is None):
            raise ValueError("multimodal projector path and size must be paired")
        if not self.provenance_verified:
            return self
        required = (
            self.source_repo,
            self.source_file,
            self.sha256,
            self.source_revision,
            self.source_license,
            self.source_license_policy,
        )
        if any(value is None for value in required) or self.size_bytes is None or self.size_bytes <= 0:
            raise ValueError("verified model provenance requires the complete artifact receipt")
        if REPO_ID_PATTERN.fullmatch(self.source_repo or "") is None:
            raise ValueError("verified model provenance requires a valid source repository")
        if not _plain_gguf_name(self.source_file or ""):
            raise ValueError("verified model provenance requires a portable GGUF file name")
        return self


class HardwareSummary(StrictModel):
    gpu_name: str | None = None
    gpu_memory_mb: int | None = Field(default=None, ge=0)
    gpu_memory_free_mb: int | None = Field(default=None, ge=0)
    ram_mb: int | None = Field(default=None, ge=0)
    llama_server_path: str | None = None
    llama_server_version: str | None = None


class LocalModelPlacementOption(StrictModel):
    """One server-owned preflight estimate, never proof of actual offload."""

    device: DeviceMode
    state: PlacementAdmissionState
    reason_code: PlacementAdmissionReason
    recommended_gpu_layers: int | None = Field(default=None, ge=0, le=4096)
    estimated_vram_required_mb: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def coherent_option(self) -> LocalModelPlacementOption:
        if self.device is DeviceMode.CPU:
            if self.state is PlacementAdmissionState.AVAILABLE:
                if (
                    self.reason_code is not PlacementAdmissionReason.CPU_AVAILABLE
                    or self.recommended_gpu_layers != 0
                    or self.estimated_vram_required_mb not in {None, 0}
                ):
                    raise ValueError("available CPU placement must use zero offload")
            elif (
                self.state is not PlacementAdmissionState.BLOCKED
                or self.reason_code
                is not PlacementAdmissionReason.CONTEXT_EXCEEDS_MODEL_METADATA
                or self.recommended_gpu_layers is not None
                or self.estimated_vram_required_mb is not None
            ):
                raise ValueError("CPU placement can only be blocked by model context metadata")
            return self
        if self.state is PlacementAdmissionState.BLOCKED and self.recommended_gpu_layers is not None:
            raise ValueError("blocked placement cannot recommend GPU layers")
        if self.state is PlacementAdmissionState.RECHECK_REQUIRED:
            if (
                self.reason_code
                is not PlacementAdmissionReason.OWNED_RUNTIME_REQUIRES_CLEANUP_RECHECK
                or self.recommended_gpu_layers is not None
                or self.estimated_vram_required_mb is not None
            ):
                raise ValueError("conditional placement requires a cleanup recheck")
        if (
            self.device is DeviceMode.SPLIT
            and self.state is PlacementAdmissionState.AVAILABLE
            and (self.recommended_gpu_layers is None or self.recommended_gpu_layers <= 0)
        ):
            raise ValueError("available split placement requires a positive layer estimate")
        return self


class LocalModelPlacementAdmission(StrictModel):
    """Placement admission for one model, context limit and hardware snapshot.

    A healthy text probe verifies model execution only. llama.cpp does not
    currently return an app-verified device-placement receipt, so this contract
    keeps actual offload explicitly unverified even after a runtime is ready.
    """

    contract_version: Literal[LOCAL_MODEL_PLACEMENT_CONTRACT_VERSION] = (
        LOCAL_MODEL_PLACEMENT_CONTRACT_VERSION
    )
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    context_size: int = Field(ge=512, le=MAX_CONTEXT_SIZE)
    gpu_memory_free_mb: int | None = Field(default=None, ge=0)
    actual_offload_verified: Literal[False] = False
    options: tuple[LocalModelPlacementOption, ...]

    @model_validator(mode="after")
    def complete_device_set(self) -> LocalModelPlacementAdmission:
        if tuple(option.device for option in self.options) != (
            DeviceMode.GPU,
            DeviceMode.SPLIT,
            DeviceMode.CPU,
        ):
            raise ValueError("placement admission must contain GPU, split and CPU exactly once")
        return self


class RuntimeStatus(StrictModel):
    state: RuntimeState = RuntimeState.STOPPED
    device: DeviceMode | None = None
    gpu_layers: int | None = Field(default=None, ge=0)
    context_size: int | None = None
    started_at: datetime | None = None
    last_error_code: str | None = None
    pid: int | None = None
    #: Flash attention + 8-bit KV cache were on (falls back to plain when the runtime refuses them).
    fast_attention: bool | None = None
    #: The runtime was started with its chat template engine, so OpenAI-style tool calls work.
    tool_calling: bool | None = None


class LocalModelStatus(StrictModel):
    record: LocalModelRecord
    runtime: RuntimeStatus
    placement: LocalModelPlacementAdmission
    endpoint_path: str


class LocalModelsOverview(StrictModel):
    contract_version: Literal[LOCAL_MODELS_CONTRACT_VERSION] = LOCAL_MODELS_CONTRACT_VERSION
    hardware: HardwareSummary
    runtime_available: bool
    storage_root: str
    storage_free_bytes: int | None = Field(default=None, ge=0)
    download_reserve_bytes: int = Field(default=DOWNLOAD_DISK_RESERVE_BYTES, ge=0)
    download_ledger_error_code: str | None = None
    models: tuple[LocalModelStatus, ...]
    downloads: tuple["DownloadStatus", ...]


class LocalRuntimeSelection(StrictModel):
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    device: DeviceMode
    gpu_layers: int = Field(ge=0, le=4096)
    context_size: int = Field(ge=512, le=MAX_CONTEXT_SIZE)


class LocalRuntimeServedSelection(LocalRuntimeSelection):
    started_at: datetime
    pid: int = Field(ge=1)


class RuntimeCleanupReceipt(StrictModel):
    state: RuntimeCleanupState = RuntimeCleanupState.NOT_REQUIRED
    process_exit_confirmed: bool = True
    gpu_memory_free_before_mb: int | None = Field(default=None, ge=0)
    gpu_memory_free_after_mb: int | None = Field(default=None, ge=0)
    gpu_memory_released_mb: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def coherent_measurement(self) -> RuntimeCleanupReceipt:
        measurements = (
            self.gpu_memory_free_before_mb,
            self.gpu_memory_free_after_mb,
            self.gpu_memory_released_mb,
        )
        if self.state is RuntimeCleanupState.MEASURED:
            if not self.process_exit_confirmed or any(value is None for value in measurements):
                raise ValueError("measured cleanup requires process exit and complete GPU measurements")
            assert self.gpu_memory_free_before_mb is not None
            assert self.gpu_memory_free_after_mb is not None
            assert self.gpu_memory_released_mb is not None
            if self.gpu_memory_free_after_mb - self.gpu_memory_free_before_mb != self.gpu_memory_released_mb:
                raise ValueError("GPU cleanup delta is inconsistent")
        elif any(value is not None for value in measurements):
            raise ValueError("non-measured cleanup cannot expose GPU measurements")
        if self.state is RuntimeCleanupState.FAILED and self.process_exit_confirmed:
            raise ValueError("failed cleanup cannot claim process exit")
        return self


class RuntimeCapabilities(StrictModel):
    state: RuntimeCapabilityState = RuntimeCapabilityState.NOT_PROBED
    probe_version: Literal[LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION] = LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION
    text: bool = False
    tools: bool = False
    vision: bool = False
    audio: bool = False
    recording: bool = False
    structured_output: bool = False
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def coherent_probe(self) -> RuntimeCapabilities:
        if self.recording and not self.audio:
            raise ValueError("recording capability requires verified audio input")
        if self.state is RuntimeCapabilityState.VERIFIED:
            if not self.text or self.error_code is not None:
                raise ValueError("verified capabilities require text and no error")
        elif self.text or self.tools or self.vision or self.audio or self.recording or self.structured_output:
            raise ValueError("unverified capabilities cannot advertise support")
        if self.state is RuntimeCapabilityState.FAILED and self.error_code is None:
            raise ValueError("failed capability probe requires a closed error code")
        if self.state is RuntimeCapabilityState.NOT_PROBED and self.error_code is not None:
            raise ValueError("an unstarted capability probe cannot have an error")
        return self


class RuntimeContextStatus(StrictModel):
    """Truth about the last context preflight for the currently served model.

    ``used_tokens`` is only populated from llama.cpp's chat-template-aware
    ``/v1/chat/completions/input_tokens`` endpoint. The app deliberately does
    not substitute a character heuristic or a tokenizer from another model.
    """

    state: Literal["unknown", "known"] = "unknown"
    used_tokens: int | None = Field(default=None, ge=0, le=MAX_CHAT_BODY_BYTES)
    limit_tokens: int | None = Field(default=None, ge=512, le=MAX_CONTEXT_SIZE)
    requested_output_tokens: int | None = Field(default=None, ge=0)
    available_output_tokens: int | None = Field(
        default=None,
        ge=-MAX_CHAT_BODY_BYTES,
        le=MAX_CONTEXT_SIZE,
    )
    source: Literal["runtime_limit_only", "runtime_chat_input_tokens"] = "runtime_limit_only"
    scope: Literal["runtime_limit", "last_request"] = "runtime_limit"
    policy: Literal[
        "runtime_enforced",
        "exact_admitted",
        "exact_compacted",
        "exact_refused",
    ] = "runtime_enforced"
    compacted_messages: int = Field(default=0, ge=0, le=10_000)
    reason_code: ContextAdmissionReason | None = ContextAdmissionReason.RUNTIME_NOT_SERVED

    @model_validator(mode="after")
    def coherent_context_evidence(self) -> RuntimeContextStatus:
        if self.state == "unknown":
            if any(value is not None for value in (
                self.used_tokens,
                self.requested_output_tokens,
                self.available_output_tokens,
            )):
                raise ValueError("unknown context cannot expose request token values")
            if (
                self.source != "runtime_limit_only"
                or self.scope != "runtime_limit"
                or self.policy != "runtime_enforced"
                or self.compacted_messages != 0
                or self.reason_code not in {
                    ContextAdmissionReason.RUNTIME_NOT_SERVED,
                    ContextAdmissionReason.NO_REQUEST_MEASURED,
                    ContextAdmissionReason.INPUT_COUNTER_UNAVAILABLE,
                    ContextAdmissionReason.INPUT_COUNTER_INVALID,
                    ContextAdmissionReason.INPUT_COUNTER_FAILED,
                }
            ):
                raise ValueError("unknown context evidence is incoherent")
            return self
        if (
            self.used_tokens is None
            or self.limit_tokens is None
            or self.available_output_tokens != self.limit_tokens - self.used_tokens
            or self.source != "runtime_chat_input_tokens"
            or self.scope != "last_request"
            or self.policy == "runtime_enforced"
        ):
            raise ValueError("known context requires exact chat-template token evidence")
        overflow = self.available_output_tokens < 0 or (
            self.requested_output_tokens is not None
            and self.requested_output_tokens > self.available_output_tokens
        )
        if self.policy == "exact_refused":
            if not overflow or self.reason_code is not ContextAdmissionReason.CONTEXT_WINDOW_EXCEEDED:
                raise ValueError("refused context requires a measured overflow")
        elif overflow or self.reason_code is not None:
            raise ValueError("admitted context cannot contain an overflow or failure reason")
        if self.policy == "exact_compacted" and self.compacted_messages <= 0:
            raise ValueError("compacted context requires an omission count")
        if self.policy == "exact_admitted" and self.compacted_messages != 0:
            raise ValueError("plain admission cannot claim compacted messages")
        return self


class LocalModelRuntimeAdapter(StrictModel):
    adapter_id: Literal[LOCAL_MODEL_RUNTIME_ADAPTER_ID] = LOCAL_MODEL_RUNTIME_ADAPTER_ID
    adapter_version: Literal[LOCAL_MODEL_RUNTIME_ADAPTER_VERSION] = LOCAL_MODEL_RUNTIME_ADAPTER_VERSION
    runtime_version: str | None = Field(default=None, max_length=120)
    runtime_identity_state: Literal["verified", "unknown"]
    runtime_binary_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN.pattern)
    capability_probe_version: Literal[LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION] = LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION

    @model_validator(mode="after")
    def coherent_runtime_identity(self) -> LocalModelRuntimeAdapter:
        if (self.runtime_identity_state == "verified") != (self.runtime_binary_sha256 is not None):
            raise ValueError("runtime digest must match its identity state")
        return self


class LocalModelCompatibility(StrictModel):
    """Path-free executable compatibility receipt for one installed alias."""

    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    state: LocalModelCompatibilityState
    reason_code: LocalModelCompatibilityReason
    format: Literal["gguf"] = "gguf"
    architecture: str | None = Field(default=None, min_length=1, max_length=120)
    tokenizer_model: str | None = Field(default=None, min_length=1, max_length=120)
    training_context_size: int | None = Field(default=None, ge=1, le=16_777_216)
    metadata_reader_version: str | None = Field(default=None, max_length=64)
    artifact_identity_state: Literal["verified_at_admission", "unverified"]
    artifact_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN.pattern)
    source_revision: str | None = Field(default=None, pattern=COMMIT_REVISION_PATTERN.pattern)
    source_license: str | None = Field(default=None, max_length=40)
    source_license_policy: str | None = Field(default=None, max_length=64)
    execution_state: Literal["verified", "failed", "not_run"]
    context_counter_state: Literal["verified", "unsupported", "failed", "not_run"]

    @model_validator(mode="after")
    def coherent_compatibility(self) -> LocalModelCompatibility:
        if self.state is LocalModelCompatibilityState.SUPPORTED:
            if (
                self.reason_code is not LocalModelCompatibilityReason.LIVE_TEXT_PROBE_VERIFIED
                or self.execution_state != "verified"
            ):
                raise ValueError("supported compatibility requires a live text execution")
        elif self.execution_state == "verified":
            raise ValueError("verified execution must be reported as supported")
        if self.artifact_identity_state == "verified_at_admission":
            if any(value is None for value in (
                self.artifact_sha256,
                self.source_revision,
                self.source_license,
                self.source_license_policy,
            )):
                raise ValueError("verified artifact identity requires the complete receipt")
        elif any(value is not None for value in (
            self.artifact_sha256,
            self.source_revision,
            self.source_license,
            self.source_license_policy,
        )):
            raise ValueError("unverified artifact identity cannot expose pinned fields")
        return self


class LocalModelCompatibilityCatalog(StrictModel):
    contract_version: Literal[LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION] = LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION
    adapter: LocalModelRuntimeAdapter
    models: tuple[LocalModelCompatibility, ...]


class ChatInputTokenCount(StrictModel):
    """llama.cpp-compatible exact input-token response."""

    object: Literal["response.input_tokens"] = "response.input_tokens"
    input_tokens: int = Field(ge=0, le=MAX_CHAT_BODY_BYTES)


class LocalRuntimeCoordinatorStatus(StrictModel):
    contract_version: Literal[LOCAL_RUNTIME_COORDINATOR_CONTRACT_VERSION] = LOCAL_RUNTIME_COORDINATOR_CONTRACT_VERSION
    revision: int = Field(ge=0)
    state: RuntimeCoordinatorState
    requested: LocalRuntimeSelection | None = None
    served: LocalRuntimeServedSelection | None = None
    cleanup: RuntimeCleanupReceipt
    capabilities: RuntimeCapabilities
    context: RuntimeContextStatus
    active_requests: int = Field(ge=0)
    last_error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def coherent_state(self) -> LocalRuntimeCoordinatorStatus:
        if self.state is RuntimeCoordinatorState.READY:
            if self.served is None or self.capabilities.state is not RuntimeCapabilityState.VERIFIED:
                raise ValueError("ready coordinator requires a served, capability-verified runtime")
        if self.state is RuntimeCoordinatorState.IDLE and self.served is not None:
            raise ValueError("idle coordinator cannot expose a served runtime")
        if self.served is not None and self.context.limit_tokens != self.served.context_size:
            raise ValueError("context limit must match the served runtime")
        if self.served is None and self.context.limit_tokens is not None:
            raise ValueError("context limit requires a served runtime")
        if self.served is None and self.context.reason_code is not ContextAdmissionReason.RUNTIME_NOT_SERVED:
            raise ValueError("an unserved runtime cannot expose request context evidence")
        if self.served is not None and self.context.reason_code is ContextAdmissionReason.RUNTIME_NOT_SERVED:
            raise ValueError("a served runtime must distinguish unmeasured request context")
        return self


def _reject_reserved_alias(value: str) -> str:
    if value in RESERVED_ALIASES:
        raise ValueError("alias is reserved")
    return value


class AddLocalModel(StrictModel):
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    display_name: str | None = Field(default=None, max_length=120)
    path: str = Field(min_length=1, max_length=1024)
    mmproj_path: str | None = Field(default=None, min_length=1, max_length=1024)
    default_device: DeviceMode = DeviceMode.SPLIT
    context_size: int = Field(default=DEFAULT_CONTEXT_SIZE, ge=512, le=MAX_CONTEXT_SIZE)
    layer_count: int | None = Field(default=None, ge=1, le=4096)

    _alias_not_reserved = field_validator("alias")(_reject_reserved_alias)


class ScanFolderRequest(StrictModel):
    """Register every GGUF file found in a folder (one level deep) with a generated alias."""

    path: str = Field(min_length=1, max_length=1024)
    default_device: DeviceMode = DeviceMode.SPLIT


class ScanFolderResult(StrictModel):
    folder: str
    registered: tuple[LocalModelRecord, ...]
    skipped_existing: int = Field(ge=0)
    skipped_invalid: int = Field(ge=0)


class ActivateLocalModel(StrictModel):
    device: DeviceMode | None = None
    gpu_layers: int | None = Field(default=None, ge=0, le=4096)
    context_size: int | None = Field(default=None, ge=512, le=MAX_CONTEXT_SIZE)
    #: Keep this device / layer choice as the model's default for next time.
    remember: bool = False
    #: Flash attention with an 8-bit KV cache: ~2x prompt processing and less VRAM on CUDA; retried without on failure.
    fast_attention: bool = True
    #: Start the runtime's chat-template engine (``--jinja``) so tool calls follow the model's own format.
    tool_calling: bool = True


class SwitchLocalRuntime(ActivateLocalModel):
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    expected_revision: int = Field(ge=0)


class StopLocalRuntime(StrictModel):
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    expected_revision: int = Field(ge=0)


class DownloadRequest(StrictModel):
    """A download the person confirmed after seeing the file, size, revision, digest and licence.

    Every ``confirmed_*`` field is what the browser displayed. The service does not
    trust any of them: it re-resolves the repository identity from the Hub and
    refuses the download unless the server's answer matches the confirmation
    exactly, so a caller cannot substitute a repository, file, revision, digest,
    size or licence, and a repository that moved since the person looked is
    refused rather than silently fetched.
    """

    repo_id: str = Field(min_length=3, max_length=200, pattern=REPO_ID_PATTERN.pattern)
    filename: str = Field(min_length=1, max_length=300)
    confirmed_size_bytes: int = Field(ge=1)
    confirmed_revision: str = Field(pattern=COMMIT_REVISION_PATTERN.pattern)
    confirmed_sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    confirmed_license: str = Field(min_length=1, max_length=40)
    alias: str = Field(pattern=ALIAS_PATTERN.pattern)
    display_name: str | None = Field(default=None, max_length=120)
    default_device: DeviceMode = DeviceMode.SPLIT

    _alias_not_reserved = field_validator("alias")(_reject_reserved_alias)

    @field_validator("filename")
    @classmethod
    def plain_file_name(cls, value: str) -> str:
        if not _plain_gguf_name(value):
            raise ValueError("download must name one portable root-level .gguf file")
        return value


class DownloadStatus(StrictModel):
    download_id: str
    repo_id: str
    filename: str
    alias: str
    state: Literal[
        "queued",
        "downloading",
        "pausing",
        "paused",
        "cancelling",
        "cancelled",
        "completed",
        "failed",
        "interrupted",
    ]
    bytes_total: int = Field(ge=0)
    bytes_done: int = Field(ge=0)
    error_code: str | None = None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    status_revision: int = Field(default=0, ge=0)
    attempt: int = Field(default=0, ge=0)
    disk_required_bytes: int | None = Field(default=None, ge=0)
    disk_free_bytes_at_start: int | None = Field(default=None, ge=0)
    partial_retained: bool = False
    cleanup_confirmed: bool | None = None
    transfer_adapter_version: str | None = Field(default=None, max_length=80)
    #: The server-verified identity this download is bound to; two revisions or
    #: two digests of the same repository/file/alias are different downloads.
    revision: str | None = Field(default=None, pattern=COMMIT_REVISION_PATTERN.pattern)
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN.pattern)

    @model_validator(mode="after")
    def coherent_download_state(self) -> DownloadStatus:
        if self.bytes_done > self.bytes_total:
            raise ValueError("download progress exceeds the reviewed artifact")
        if self.partial_retained and self.bytes_done == 0:
            raise ValueError("a retained partial requires at least one byte")
        if self.state == "completed" and self.bytes_done != self.bytes_total:
            raise ValueError("a completed download must contain the reviewed byte count")
        if self.state == "cancelled" and (self.partial_retained or self.cleanup_confirmed is not True):
            raise ValueError("a cancelled download requires confirmed cleanup")
        return self


class DownloadCommandRequest(StrictModel):
    """Optimistic concurrency receipt for one explicit download command."""

    expected_status_revision: int = Field(ge=0)


class RemoteFile(StrictModel):
    filename: str
    size_bytes: int | None = None
    #: Expected content digest published for this file at ``RemoteRepoFiles.revision``.
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN.pattern)
    #: This app is willing to download the file: pinned revision, exact size, an
    #: expected digest bound to that revision, and an admitted licence.
    eligible: bool = False
    #: Closed code explaining an ineligible file; never repository text.
    ineligible_reason: str | None = None

    @model_validator(mode="after")
    def eligibility_is_coherent(self) -> RemoteFile:
        complete = self.size_bytes is not None and self.size_bytes > 0 and self.sha256 is not None
        if self.eligible != (complete and self.ineligible_reason is None):
            raise ValueError("remote file eligibility is inconsistent")
        if not self.eligible and self.ineligible_reason is None:
            raise ValueError("an ineligible remote file requires a closed reason")
        return self


class RemoteRepoFiles(StrictModel):
    repo_id: str
    #: Immutable commit oid the whole response is bound to, never a branch name.
    revision: str | None = Field(default=None, pattern=COMMIT_REVISION_PATTERN.pattern)
    #: True only when ``revision`` is a commit oid the Hub confirmed for itself.
    revision_pinned: bool = False
    license_id: str | None = Field(default=None, max_length=40)
    license_admission: LicenseAdmission = LicenseAdmission.UNAVAILABLE
    license_policy_version: str = LICENSE_POLICY_VERSION
    gated: bool | None = None
    #: Closed code set when the repository identity could not be resolved at all.
    unavailable_reason: str | None = None
    files: tuple[RemoteFile, ...] = ()

    @model_validator(mode="after")
    def repository_identity_is_coherent(self) -> RemoteRepoFiles:
        if self.revision_pinned:
            if self.revision is None or self.unavailable_reason is not None:
                raise ValueError("pinned repository identity is incomplete")
        elif self.revision is not None or self.files:
            raise ValueError("an unpinned repository cannot expose revision-bound files")
        if self.license_admission is LicenseAdmission.ALLOWED and self.license_id is None:
            raise ValueError("an admitted repository requires a license identifier")
        if any(file.eligible for file in self.files):
            if self.license_admission is not LicenseAdmission.ALLOWED or self.gated is True:
                raise ValueError("eligible files require an admitted, public repository")
        return self


@dataclass(slots=True)
class ChatUpstream:
    """One upstream chat reply: either a complete body or a line iterator over a server-sent event stream."""

    status_code: int
    content_type: str
    body: bytes | None = None
    lines: Iterator[bytes] | None = None
    cancel: Callable[[], None] | None = None
    read_usage_tail: Callable[[], object | None] | None = None


class _RuntimeSocketReader(io.RawIOBase):
    """One nonblocking reader with bounded cancellation checks on Windows too."""

    def __init__(self, sock: socket.socket, cancellation: threading.Event | None = None):
        super().__init__()
        self._cancelled = threading.Event()
        self._request_cancelled = cancellation
        self._socket: socket.socket | None = None
        self._timeout = sock.gettimeout()
        self._read_until: float | None = None
        owned = sock.dup()
        try:
            owned.setblocking(False)
        except OSError:
            owned.close()
            raise
        self._socket = owned

    def readable(self) -> bool:
        return True

    def set_read_timeout(self, seconds: float) -> None:
        # An absolute deadline also bounds a line dribbled over many reads.
        self._read_until = time.monotonic() + seconds

    def cancel(self) -> None:
        self._cancelled.set()

    def readinto(self, buffer) -> int:
        owned = self._socket
        if self.closed or owned is None:
            raise ValueError("runtime reader is closed")
        if not buffer:
            return 0
        deadline = self._read_until
        if deadline is None and self._timeout is not None:
            deadline = time.monotonic() + self._timeout
        while not self._cancelled.is_set() and not (self._request_cancelled is not None and self._request_cancelled.is_set()):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("runtime read deadline exceeded")
            ready, _, _ = select.select([owned], [], [], min(0.1, remaining) if remaining is not None else 0.1)
            if self._cancelled.is_set() or (self._request_cancelled is not None and self._request_cancelled.is_set()):
                break
            if ready:
                try:
                    return owned.recv_into(buffer)
                except BlockingIOError:
                    continue
        raise OSError("runtime read cancelled")

    def close(self) -> None:
        self.cancel()
        try:
            if self._socket is not None:
                self._socket.close()
        finally:
            super().close()


class _RuntimeHTTPResponse(http.client.HTTPResponse):
    """Keep standard HTTP framing over our owned, cancellable socket reader."""

    def __init__(self, sock, *args, cancellation=None, **kwargs):
        super().__init__(sock, *args, **kwargs)
        original = self.fp
        try:
            self._reader = _RuntimeSocketReader(sock, cancellation)
            self.fp = io.BufferedReader(self._reader)
        finally:
            original.close()

    def set_read_timeout(self, seconds: float) -> None:
        self._reader.set_read_timeout(seconds)

    def cancel_read(self) -> None:
        self._reader.cancel()
        self.close()


class _RuntimeHTTPConnection(http.client.HTTPConnection):
    response_class = _RuntimeHTTPResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._request_cancelled = current_runtime_cancellation()
        self.response_class = partial(_RuntimeHTTPResponse, cancellation=self._request_cancelled)

    def _check_cancelled(self) -> None:
        if self._request_cancelled is not None and self._request_cancelled.is_set():
            raise OSError("runtime request cancelled")

    def _deadline(self) -> float | None:
        timeout = self.timeout if isinstance(self.timeout, (int, float)) else socket.getdefaulttimeout()
        return None if timeout is None else time.monotonic() + timeout

    def _wait_writable(self, owned: socket.socket, deadline: float | None) -> None:
        while True:
            self._check_cancelled()
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError("runtime connection deadline exceeded")
            _, writable, exceptional = select.select([], [owned], [owned], min(0.1, remaining) if remaining is not None else 0.1)
            self._check_cancelled()
            if writable or exceptional:
                return

    def connect(self) -> None:
        if self._request_cancelled is None:
            return super().connect()
        self._check_cancelled()
        # Owned runtime destinations are numeric loopback addresses. Never let
        # cancellation introduce a blocking DNS lookup, proxy, or tunnel.
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError:
            raise OSError("runtime destination must be numeric loopback") from None
        if not address.is_loopback or self._tunnel_host:
            raise OSError("runtime destination must be numeric loopback")
        owned = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if self.source_address:
                owned.bind(self.source_address)
            owned.setblocking(False)
            result = owned.connect_ex((self.host, self.port))
            pending = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037}
            if result in pending:
                self._wait_writable(owned, self._deadline())
                result = owned.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if result not in {0, errno.EISCONN, 10056}:
                raise OSError(result, "runtime connection failed")
            self._check_cancelled()
            owned.settimeout(self.timeout if isinstance(self.timeout, (int, float)) else socket.getdefaulttimeout())
            self.sock = owned
        except BaseException:
            owned.close()
            raise

    def send(self, data) -> None:
        if self._request_cancelled is None:
            return super().send(data)
        self._check_cancelled()
        if self.sock is None:
            if not self.auto_open:
                raise http.client.NotConnected()
            self.connect()
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("runtime request upload must contain bytes")
        owned = self.sock
        timeout = owned.gettimeout()
        deadline = self._deadline()
        try:
            owned.setblocking(False)
            remaining = memoryview(data)
            while remaining:
                self._check_cancelled()
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("runtime upload deadline exceeded")
                try:
                    sent = owned.send(remaining)
                except BlockingIOError:
                    self._wait_writable(owned, deadline)
                    continue
                if sent == 0:
                    raise OSError("runtime connection closed during upload")
                remaining = remaining[sent:]
        finally:
            owned.settimeout(timeout)


class _RuntimeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(_RuntimeHTTPConnection, request)


def _read_usage_tail(response: object) -> object | None:
    """Read one metadata-only trailer, never more output or an unbounded wait.

    Some runtime versions send usage on the finish chunk; others send a separate
    empty-choices chunk. The normal Agent iterator still stops at its finish
    receipt. Only this owned HTTP adapter may look for the expected trailer.
    """
    limiter = getattr(response, "set_read_timeout", None)
    if not callable(limiter):
        return None
    deadline = time.monotonic() + 0.25
    received = 0
    try:
        for _ in range(32):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            limiter(remaining)
            line = response.readline(64_001 - received)  # type: ignore[attr-defined]
            if not line:
                return None
            received += len(line)
            if received > 64_000:
                return None
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                return None
            packet = model_json_object(data.decode("utf-8"), max_characters=64_000)
            if packet is None or packet.get("choices") != [] or "usage" not in packet:
                return None
            return packet["usage"]
    except (OSError, ValueError):
        return None
    return None


class _NoRuntimeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The owned runtime is one exact loopback destination. A redirect is
        # an upstream response, never permission to contact another service.
        return None


def _runtime_opener() -> urllib.request.OpenerDirector:
    # Never route local prompts or health probes through an OS/environment
    # proxy. This does not affect separately approved model downloads.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRuntimeRedirect(), _RuntimeHTTPHandler()
    )


def _relay_event_stream(response: object) -> Iterator[bytes]:
    """Yield the runtime's SSE lines unchanged, bounded in size; close upstream when the consumer stops."""

    sent = 0
    try:
        with response:  # type: ignore[attr-defined]
            for line in response:  # type: ignore[attr-defined]
                sent += len(line)
                if sent > MAX_CHAT_STREAM_BYTES:
                    yield b"data: [DONE]\n\n"
                    return
                yield line
    except (OSError, ValueError):
        return


class LocalModelError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc_now() -> datetime:
    return datetime.now(UTC)


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


RUNTIME_DIR_NAME = "runtimes"
MAX_LOCAL_PROBE_OUTPUT_BYTES = 64 * 1024
MAX_LOCAL_PROBE_PROCESSES = 4


def detect_llama_server(environment: dict[str, str] | None = None, *, app_home: Path | None = None, models_root: Path | None = None) -> Path | None:
    """Explicit path, then the models folder's runtimes, then the app home's, then PATH."""

    env = os.environ if environment is None else environment
    explicit = env.get(LLAMA_SERVER_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None
    for root in (models_root, app_home):
        if root is None:
            continue
        for name in ("llama-server.exe", "llama-server"):
            candidate = root / RUNTIME_DIR_NAME / "llama.cpp" / name
            if candidate.is_file():
                return candidate
    for name in ("llama-server", "llama-server.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _llama_server_probe_identity(llama_server: Path) -> tuple[str, int, int]:
    """Bind cached version evidence to one exact executable revision."""

    try:
        resolved = llama_server.resolve(strict=True)
        status = resolved.stat()
        return (str(resolved), int(status.st_size), int(status.st_mtime_ns))
    except OSError:
        return (str(llama_server.absolute()), -1, -1)


def _read_llama_server_version(
    llama_server: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess],
    hidden: dict[str, int],
) -> str | None:
    try:
        result = run(
            [str(llama_server), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden,
        )
        lines = (result.stdout or result.stderr or "").strip().splitlines()
        return lines[0][:80] if lines else None
    except Exception:
        return None


def _run_owned_local_probe(
    command: list[str],
    *,
    capture_output: bool,
    text: bool,
    timeout: float,
    check: bool,
    creationflags: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run a content-bounded identity probe inside the shared process owner."""

    if not capture_output or not text or check or creationflags not in {
        0,
        _runtime_creation_flags(),
    }:
        raise ValueError("local_probe_options_invalid")
    result = run_owned_process(
        command,
        cwd=None,
        env=_runtime_environment(),
        stdout_limit=MAX_LOCAL_PROBE_OUTPUT_BYTES,
        stderr_limit=MAX_LOCAL_PROBE_OUTPUT_BYTES,
        timeout=timeout,
        maximum_active_processes=MAX_LOCAL_PROBE_PROCESSES,
    )
    return subprocess.CompletedProcess(
        command,
        result.returncode,
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )


def _cached_llama_server_version(
    llama_server: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess],
    hidden: dict[str, int],
) -> str | None:
    """Probe one executable revision once instead of on every UI poll."""

    global _LLAMA_SERVER_VERSION_CACHE
    identity = _llama_server_probe_identity(llama_server)
    with _LLAMA_SERVER_VERSION_CACHE_LOCK:
        cached = _LLAMA_SERVER_VERSION_CACHE
        if cached is not None and cached[0] == identity:
            return cached[1]
        version = _read_llama_server_version(
            llama_server,
            run=run,
            hidden=hidden,
        )
        _LLAMA_SERVER_VERSION_CACHE = (identity, version)
        return version


def probe_hardware(
    *,
    llama_server: Path | None,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> HardwareSummary:
    runner = run or _run_owned_local_probe
    gpu_name = gpu_total = gpu_free = None
    hidden = {"creationflags": _runtime_creation_flags()} if os.name == "nt" else {}
    try:
        result = runner(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False, **hidden,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 3:
                gpu_name = parts[0][:80]
                gpu_total = int(float(parts[1]))
                gpu_free = int(float(parts[2]))
    except Exception:
        pass
    ram_mb = None
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                ram_mb = int(status.ullTotalPhys // (1024 * 1024))
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            ram_mb = int(pages * page_size // (1024 * 1024))
    except Exception:
        ram_mb = None
    version = None
    if llama_server is not None:
        version = (
            _cached_llama_server_version(
                llama_server,
                run=runner,
                hidden=hidden,
            )
            if run is None
            else _read_llama_server_version(
                llama_server,
                run=runner,
                hidden=hidden,
            )
        )
    return HardwareSummary(
        gpu_name=gpu_name,
        gpu_memory_mb=gpu_total,
        gpu_memory_free_mb=gpu_free,
        ram_mb=ram_mb,
        llama_server_path=str(llama_server) if llama_server else None,
        llama_server_version=version,
    )


def estimate_gpu_layers(*, size_bytes: int | None, layer_count: int | None, gpu_memory_free_mb: int | None, context_size: int) -> int:
    """Layers that should fit the free VRAM minus headroom; 0 when unknown."""

    if not size_bytes or not layer_count or not gpu_memory_free_mb:
        return 0
    per_layer = max(1, size_bytes // layer_count)
    headroom = SPLIT_VRAM_HEADROOM_BYTES + int(context_size) * 64 * 1024  # coarse KV allowance
    budget = gpu_memory_free_mb * 1024 * 1024 - headroom
    if budget <= 0:
        return 0
    return max(0, min(layer_count, int(budget // per_layer)))


def build_placement_admission(
    *,
    record: LocalModelRecord,
    hardware: HardwareSummary,
    context_size: int,
    owned_gpu_runtime_active: bool = False,
) -> LocalModelPlacementAdmission:
    """Build a conservative admission estimate from explicit local evidence.

    The result only decides whether the app may attempt the requested runtime
    arguments. It never upgrades those arguments into proof that llama.cpp
    actually placed tensors on the requested device.
    """

    context_unsupported = (
        record.training_context_size is not None
        and context_size > record.training_context_size
    )
    if context_unsupported:
        options = tuple(
            LocalModelPlacementOption(
                device=device,
                state=PlacementAdmissionState.BLOCKED,
                reason_code=PlacementAdmissionReason.CONTEXT_EXCEEDS_MODEL_METADATA,
            )
            for device in (DeviceMode.GPU, DeviceMode.SPLIT, DeviceMode.CPU)
        )
        return LocalModelPlacementAdmission(
            alias=record.alias,
            context_size=context_size,
            gpu_memory_free_mb=hardware.gpu_memory_free_mb,
            options=options,
        )

    cpu = LocalModelPlacementOption(
        device=DeviceMode.CPU,
        state=PlacementAdmissionState.AVAILABLE,
        reason_code=PlacementAdmissionReason.CPU_AVAILABLE,
        recommended_gpu_layers=0,
        estimated_vram_required_mb=0,
    )
    accelerator_observed = (
        hardware.gpu_name is not None
        and hardware.gpu_memory_free_mb is not None
    )
    if not accelerator_observed:
        unavailable = tuple(
            LocalModelPlacementOption(
                device=device,
                state=PlacementAdmissionState.BLOCKED,
                reason_code=PlacementAdmissionReason.ACCELERATOR_EVIDENCE_UNAVAILABLE,
            )
            for device in (DeviceMode.GPU, DeviceMode.SPLIT)
        )
        return LocalModelPlacementAdmission(
            alias=record.alias,
            context_size=context_size,
            gpu_memory_free_mb=hardware.gpu_memory_free_mb,
            options=(*unavailable, cpu),
        )

    if owned_gpu_runtime_active:
        conditional = tuple(
            LocalModelPlacementOption(
                device=device,
                state=PlacementAdmissionState.RECHECK_REQUIRED,
                reason_code=PlacementAdmissionReason.OWNED_RUNTIME_REQUIRES_CLEANUP_RECHECK,
            )
            for device in (DeviceMode.GPU, DeviceMode.SPLIT)
        )
        return LocalModelPlacementAdmission(
            alias=record.alias,
            context_size=context_size,
            gpu_memory_free_mb=hardware.gpu_memory_free_mb,
            options=(*conditional, cpu),
        )

    headroom = SPLIT_VRAM_HEADROOM_BYTES + int(context_size) * 64 * 1024
    if record.size_bytes:
        required_bytes = record.size_bytes + headroom
        required_mb = (required_bytes + 1024 ** 2 - 1) // 1024 ** 2
        gpu_fits = required_mb <= (hardware.gpu_memory_free_mb or 0)
        gpu = LocalModelPlacementOption(
            device=DeviceMode.GPU,
            state=(
                PlacementAdmissionState.AVAILABLE
                if gpu_fits
                else PlacementAdmissionState.BLOCKED
            ),
            reason_code=(
                PlacementAdmissionReason.GPU_ESTIMATE_FITS
                if gpu_fits
                else PlacementAdmissionReason.GPU_ESTIMATE_EXCEEDS_FREE_MEMORY
            ),
            recommended_gpu_layers=(record.layer_count if gpu_fits else None),
            estimated_vram_required_mb=required_mb,
        )
    else:
        gpu = LocalModelPlacementOption(
            device=DeviceMode.GPU,
            state=PlacementAdmissionState.BLOCKED,
            reason_code=PlacementAdmissionReason.MODEL_SIZE_UNAVAILABLE,
        )

    if record.layer_count is None:
        split = LocalModelPlacementOption(
            device=DeviceMode.SPLIT,
            state=PlacementAdmissionState.BLOCKED,
            reason_code=PlacementAdmissionReason.LAYER_COUNT_UNAVAILABLE,
        )
    elif not record.size_bytes:
        split = LocalModelPlacementOption(
            device=DeviceMode.SPLIT,
            state=PlacementAdmissionState.BLOCKED,
            reason_code=PlacementAdmissionReason.MODEL_SIZE_UNAVAILABLE,
        )
    else:
        recommended = estimate_gpu_layers(
            size_bytes=record.size_bytes,
            layer_count=record.layer_count,
            gpu_memory_free_mb=hardware.gpu_memory_free_mb,
            context_size=context_size,
        )
        per_layer = max(1, record.size_bytes // record.layer_count)
        split_required_mb = (
            headroom + per_layer * recommended + 1024 ** 2 - 1
        ) // 1024 ** 2
        split = LocalModelPlacementOption(
            device=DeviceMode.SPLIT,
            state=(
                PlacementAdmissionState.AVAILABLE
                if recommended > 0
                else PlacementAdmissionState.BLOCKED
            ),
            reason_code=(
                PlacementAdmissionReason.SPLIT_ESTIMATE_AVAILABLE
                if recommended > 0
                else PlacementAdmissionReason.SPLIT_ESTIMATE_EXCEEDS_FREE_MEMORY
            ),
            recommended_gpu_layers=recommended if recommended > 0 else None,
            estimated_vram_required_mb=split_required_mb if recommended > 0 else None,
        )
    return LocalModelPlacementAdmission(
        alias=record.alias,
        context_size=context_size,
        gpu_memory_free_mb=hardware.gpu_memory_free_mb,
        options=(gpu, split, cpu),
    )


_GGUF_MAGIC = b"GGUF"
_GGUF_HEADER_READ_LIMIT = 64 * 1024 * 1024
_GGUF_MAX_METADATA_ENTRIES = 100_000


@dataclass(frozen=True)
class GgufMetadata:
    """The small, selected GGUF identity needed by the runtime contract."""

    architecture: str | None = None
    tokenizer_model: str | None = None
    training_context_size: int | None = None
    layer_count: int | None = None


def _bounded_metadata_text(value: object, *, maximum: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > maximum or not candidate.isprintable():
        return None
    return candidate


def read_gguf_metadata(path: Path) -> GgufMetadata:
    """Read selected scalar GGUF metadata without loading tensors or arrays.

    The walker is byte-, entry-, and array-bounded. Malformed or missing
    values remain ``None``; a model name is never treated as metadata.
    """

    import struct

    architecture: str | None = None
    tokenizer_model: str | None = None
    context_candidates: dict[str, int] = {}
    layer_candidates: dict[str, int] = {}
    try:
        with path.open("rb") as handle:
            if handle.read(4) != _GGUF_MAGIC:
                return GgufMetadata()
            raw_version = handle.read(4)
            raw_counts = handle.read(16)
            if len(raw_version) != 4 or len(raw_counts) != 16:
                return GgufMetadata()
            version = struct.unpack("<I", raw_version)[0]
            if version < 2:
                return GgufMetadata()
            _tensor_count, kv_count = struct.unpack("<QQ", raw_counts)
            if kv_count > _GGUF_MAX_METADATA_ENTRIES:
                return GgufMetadata()
            consumed = [24]

            def take(count: int) -> bytes:
                if count < 0 or consumed[0] + count > _GGUF_HEADER_READ_LIMIT:
                    raise ValueError("gguf header read limit")
                data = handle.read(count)
                if len(data) != count:
                    raise ValueError("gguf header truncated")
                consumed[0] += count
                return data

            def read_string(*, capture: bool) -> str | None:
                length = struct.unpack("<Q", take(8))[0]
                raw = take(length)
                if not capture:
                    return None
                return raw.decode("utf-8", errors="strict")

            sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
            formats = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}

            def read_value(value_type: int, *, capture: bool = False):
                if value_type == 8:
                    return read_string(capture=capture)
                if value_type == 9:
                    element_type, count = struct.unpack("<IQ", take(12))
                    if count > _GGUF_MAX_METADATA_ENTRIES:
                        raise ValueError("gguf array count limit")
                    size = sizes.get(element_type)
                    if size is not None:
                        take(size * count)
                    elif element_type == 8:
                        for _ in range(count):
                            read_string(capture=False)
                    else:
                        raise ValueError("unsupported nested gguf array")
                    return None
                size = sizes.get(value_type)
                if size is None:
                    raise ValueError("unknown gguf value type")
                raw = take(size)
                return struct.unpack(formats[value_type], raw)[0] if capture else None

            for _ in range(kv_count):
                key = read_string(capture=True)
                if not isinstance(key, str):
                    raise ValueError("gguf metadata key unavailable")
                value_type = struct.unpack("<I", take(4))[0]
                selected = (
                    key in {"general.architecture", "tokenizer.ggml.model"}
                    or key.endswith(".block_count")
                    or key.endswith(".context_length")
                )
                value = read_value(value_type, capture=selected)
                if key == "general.architecture":
                    architecture = _bounded_metadata_text(value)
                elif key == "tokenizer.ggml.model":
                    tokenizer_model = _bounded_metadata_text(value)
                elif key.endswith(".block_count") and isinstance(value, int) and not isinstance(value, bool):
                    if 1 <= value <= 4096:
                        layer_candidates[key.removesuffix(".block_count")] = value
                elif key.endswith(".context_length") and isinstance(value, int) and not isinstance(value, bool):
                    if 1 <= value <= 16_777_216:
                        context_candidates[key.removesuffix(".context_length")] = value
    except (OSError, UnicodeDecodeError, ValueError, struct.error, OverflowError):
        return GgufMetadata()
    return GgufMetadata(
        architecture=architecture,
        tokenizer_model=tokenizer_model,
        training_context_size=(
            context_candidates.get(architecture)
            if architecture is not None
            else next(iter(context_candidates.values()), None)
        ),
        layer_count=(
            layer_candidates.get(architecture)
            if architecture is not None
            else next(iter(layer_candidates.values()), None)
        ),
    )


def read_gguf_layer_count(path: Path) -> int | None:
    """Backward-compatible block-count convenience wrapper."""

    return read_gguf_metadata(path).layer_count


def admit_license(license_id: str | None) -> LicenseAdmission:
    """Apply the frozen repository admission policy to one declared identifier."""

    if license_id is None:
        return LicenseAdmission.UNAVAILABLE
    if license_id in ADMITTED_LICENSE_IDS:
        return LicenseAdmission.ALLOWED
    if license_id in REFUSED_LICENSE_IDS:
        return LicenseAdmission.NOT_ALLOWED
    return LicenseAdmission.UNREVIEWED


def _attribute(source: object, name: str) -> object:
    """Read one field from a Hub dataclass or from the mapping it also behaves as."""

    value = getattr(source, name, None)
    if value is None and isinstance(source, dict):
        value = source.get(name)
    return value


def _commit_oid(value: object) -> str | None:
    """A 40-hex commit oid, or None for a branch name, a tag or anything malformed."""

    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if COMMIT_REVISION_PATTERN.fullmatch(candidate) else None


def _declared_license(info: object) -> str | None:
    """The one licence identifier the repository declares, or None when it declares
    none, several different ones, or something that is not an identifier."""

    declared: set[str] = set()
    card = _attribute(_attribute(info, "card_data") or {}, "license")
    for raw in (card if isinstance(card, list) else [card]):
        if isinstance(raw, str) and raw.strip():
            declared.add(raw.strip().lower())
    tags = _attribute(info, "tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("license:") and tag[8:].strip():
                declared.add(tag[8:].strip().lower())
    if len(declared) != 1:
        return None  # nothing declared, or the repository contradicts itself
    only = declared.pop()
    return only if _LICENSE_ID_PATTERN.fullmatch(only) else None


def _identity_unavailable(repo_id: str, reason: str) -> RemoteRepoFiles:
    """The fixed state returned whenever a repository's identity cannot be pinned.

    It is deliberately content-free: no revision, no files, one closed reason code.
    """

    return RemoteRepoFiles(
        repo_id=repo_id,
        revision=None,
        revision_pinned=False,
        license_id=None,
        license_admission=LicenseAdmission.UNAVAILABLE,
        gated=None,
        unavailable_reason=reason,
        files=(),
    )


def _plain_gguf_name(filename: str) -> bool:
    if PORTABLE_GGUF_NAME_PATTERN.fullmatch(filename) is None or ".." in filename:
        return False
    return filename.split(".", 1)[0].upper() not in _WINDOWS_RESERVED_FILE_STEMS


def resolve_repo_identity(repo_id: str, *, model_info: Callable[..., object]) -> RemoteRepoFiles:
    """Bind a repository's GGUF files to one immutable commit, with size, digest and licence.

    Two lookups: the first only to learn which commit the repository points at right
    now, the second addressed to that commit oid so every size, digest and licence in
    the answer comes from the exact revision a download would fetch. A repository that
    will not name a commit oid, or that answers a commit lookup with a different
    commit, yields the fixed unavailable state rather than a guess.
    """

    try:
        head = model_info(repo_id, files_metadata=True)
    except Exception:
        raise LocalModelError("remote_repo_unavailable") from None
    revision = _commit_oid(_attribute(head, "sha"))
    if revision is None:
        return _identity_unavailable(repo_id, "revision_not_immutable")
    try:
        pinned = model_info(repo_id, revision=revision, files_metadata=True)
    except Exception:
        raise LocalModelError("remote_repo_unavailable") from None
    if _commit_oid(_attribute(pinned, "sha")) != revision:
        return _identity_unavailable(repo_id, "revision_contradicted")

    license_id = _declared_license(pinned)
    admission = admit_license(license_id)
    gated_raw = _attribute(pinned, "gated")
    gated = bool(gated_raw) if gated_raw is not None else None
    siblings = _attribute(pinned, "siblings")
    files: list[RemoteFile] = []
    for sibling in siblings if isinstance(siblings, list) else []:
        name = _attribute(sibling, "rfilename")
        if not isinstance(name, str) or not name.endswith(".gguf"):
            continue
        size = _attribute(sibling, "size")
        digest = _attribute(_attribute(sibling, "lfs") or {}, "sha256")
        digest = digest.strip().lower() if isinstance(digest, str) else None
        if gated is True:
            reason = "repository_gated"
        elif admission is not LicenseAdmission.ALLOWED:
            reason = f"license_{admission.value}"
        elif not _plain_gguf_name(name):
            reason = "unsupported_file_path"
        elif not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            reason = "size_unavailable"
        elif digest is None or SHA256_PATTERN.fullmatch(digest) is None:
            reason = "digest_unavailable"
        else:
            reason = None
        files.append(
            RemoteFile(
                filename=name[:300],
                size_bytes=size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
                sha256=digest if digest is not None and SHA256_PATTERN.fullmatch(digest) else None,
                eligible=reason is None,
                ineligible_reason=reason,
            )
        )
    return RemoteRepoFiles(
        repo_id=repo_id,
        revision=revision,
        revision_pinned=True,
        license_id=license_id,
        license_admission=admission,
        gated=gated,
        unavailable_reason=None,
        files=tuple(sorted(files, key=lambda item: item.filename)),
    )


class VerifiedArtifact(StrictModel):
    """One Hub file the server itself resolved: the only thing a download may fetch."""

    repo_id: str = Field(pattern=REPO_ID_PATTERN.pattern)
    filename: str = Field(min_length=1, max_length=300)
    revision: str = Field(pattern=COMMIT_REVISION_PATTERN.pattern)
    sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    size_bytes: int = Field(ge=1)
    license_id: str = Field(min_length=1, max_length=40)


class _PersistedDownloadJob(StrictModel):
    request: DownloadRequest
    artifact: VerifiedArtifact
    status: DownloadStatus


class _DownloadLedger(StrictModel):
    contract_version: Literal[DOWNLOAD_LEDGER_CONTRACT_VERSION] = DOWNLOAD_LEDGER_CONTRACT_VERSION
    jobs: tuple[_PersistedDownloadJob, ...] = ()


class _DownloadPaused(Exception):
    """Internal cooperative stop that intentionally retains a bounded partial."""


class _DownloadCancelled(Exception):
    """Internal cooperative stop that requires exact owned-file cleanup."""


class _DownloadControl:
    def __init__(self) -> None:
        self.pause = threading.Event()
        self.cancel = threading.Event()

    def checkpoint(self) -> None:
        if self.cancel.is_set():
            raise _DownloadCancelled
        if self.pause.is_set():
            raise _DownloadPaused


class _DownloadProgressGate:
    """Minimal tqdm-compatible gate used by the version-gated Hub adapter."""

    def __init__(self, control: _DownloadControl) -> None:
        self._control = control

    def update(self, _amount: int) -> None:
        # huggingface_hub calls this immediately before writing each chunk.
        self._control.checkpoint()


class _TrackedDownloadFile:
    """Delegate a binary file while publishing only its bounded byte count."""

    def __init__(self, wrapped: object, publish: Callable[[int], None]) -> None:
        self._wrapped = wrapped
        self._publish = publish

    def write(self, value: bytes) -> int:
        written = self._wrapped.write(value)  # type: ignore[attr-defined]
        self._wrapped.flush()  # type: ignore[attr-defined]
        self._publish(int(self._wrapped.tell()))  # type: ignore[attr-defined]
        return int(written)

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


def _artifact_storage_directory(artifact: VerifiedArtifact) -> str:
    """A bounded directory identity that keeps mutable revisions apart."""

    identity = "\0".join((artifact.repo_id, artifact.revision)).encode("utf-8")
    return f"hf-{hashlib.sha256(identity).hexdigest()}"


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DIGEST_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class LocalModelRegistry:
    """JSON registry under the app home; aliases are the only identity."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._file = root / REGISTRY_FILE_NAME
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def weights_dir(self) -> Path:
        return self._root / WEIGHTS_DIR_NAME

    def _read(self) -> dict[str, LocalModelRecord]:
        if not self._file.is_file():
            return {}
        try:
            payload = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        records: dict[str, LocalModelRecord] = {}
        for item in payload.get("models", []) if isinstance(payload, dict) else []:
            try:
                record = LocalModelRecord.model_validate(item)
            except Exception:
                continue
            records[record.alias] = record
        return records

    def _write(self, records: dict[str, LocalModelRecord]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {"contract_version": LOCAL_MODELS_CONTRACT_VERSION, "models": [r.model_dump(mode="json") for r in records.values()]}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self._file)

    def list(self) -> tuple[LocalModelRecord, ...]:
        with self._lock:
            return tuple(sorted(self._read().values(), key=lambda r: r.alias))

    def get(self, alias: str) -> LocalModelRecord | None:
        with self._lock:
            return self._read().get(alias)

    def upsert(self, record: LocalModelRecord) -> None:
        with self._lock:
            records = self._read()
            records[record.alias] = record
            self._write(records)

    def remove(self, alias: str) -> bool:
        with self._lock:
            records = self._read()
            if alias not in records:
                return False
            del records[alias]
            self._write(records)
            return True


class LlamaServerProcess:
    """One running llama-server bound to loopback."""

    def __init__(
        self,
        *,
        process: object,
        port: int,
        status: RuntimeStatus,
        activation_generation: int,
    ) -> None:
        self.process = process
        self.port = port
        self.status = status
        self.activation_generation = activation_generation

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class _OwnedPosixRuntimeProcess:
    """Popen facade whose stop operations address the whole new process group."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self.pid = process.pid

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def terminate(self) -> None:
        os.killpg(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        os.killpg(self.pid, signal.SIGKILL)

    def tree_exited(self) -> bool:
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    @staticmethod
    def close() -> bool:
        return True


def _spawn_owned_runtime(command: list[str], **options: object) -> object:
    """Start the production runtime with atomic descendant ownership."""

    if os.name == "nt":
        from .local_command_windows import WindowsCommandJob

        if options.get("shell") is not False:
            raise OSError("runtime_spawn_policy_invalid")
        return WindowsCommandJob(
            command,
            cwd=None,
            env=_runtime_environment(),
            capture_output=False,
        )
    launch = dict(options)
    launch["start_new_session"] = True
    launch["env"] = _runtime_environment()
    process = subprocess.Popen(command, **launch)  # type: ignore[arg-type]
    return _OwnedPosixRuntimeProcess(process)


class LocalModelService:
    def __init__(
        self,
        root: Path,
        *,
        llama_server: Callable[[], Path | None] = detect_llama_server,
        hardware: Callable[[Path | None], HardwareSummary] | None = None,
        popen: Callable[..., object] | None = None,
        clock: Callable[[], datetime] = _utc_now,
        health_timeout_seconds: float = HEALTH_TIMEOUT_SECONDS,
        downloader: Callable[..., Path] | None = None,
        download_transfer: Callable[..., Path] | None = None,
        disk_usage: Callable[[Path], object] = shutil.disk_usage,
        download_join_timeout_seconds: float = 10.0,
        model_info: Callable[..., object] | None = None,
        capability_probe: Callable[[LlamaServerProcess, str, bool], RuntimeCapabilities] | None = None,
    ) -> None:
        self._registry = LocalModelRegistry(root)
        self._lock = threading.RLock()
        self._llama_server = llama_server
        self._hardware = hardware or (lambda binary: probe_hardware(llama_server=binary))
        self._popen = popen or _spawn_owned_runtime
        self._clock = clock
        self._health_timeout = health_timeout_seconds
        self._downloader = downloader
        self._download_transfer = download_transfer
        self._disk_usage = disk_usage
        self._download_join_timeout = max(0.1, download_join_timeout_seconds)
        self._model_info = model_info
        self._capability_probe = capability_probe or self._probe_runtime_capabilities
        self._processes: dict[str, LlamaServerProcess] = {}
        self._runtime_command_generations: dict[str, int] = {}
        self._global_runtime_command_generation = 0
        self._reaped_activation_generations: dict[str, int] = {}
        self._shutdown_generation = 0
        self._shutting_down = False
        self._failures: dict[str, str] = {}
        self._downloads: dict[str, DownloadStatus] = {}
        self._download_jobs: dict[str, _PersistedDownloadJob] = {}
        self._download_controls: dict[str, _DownloadControl] = {}
        self._download_workers: dict[str, threading.Thread] = {}
        self._download_progress_persisted_at: dict[str, float] = {}
        self._active_requests: dict[str, int] = {}
        # Per activation generation: an exact chat-input counter is only
        # advertised after that runtime endpoint returned a coherent receipt.
        self._context_counter_support: dict[str, tuple[
            int,
            Literal["verified", "unsupported", "failed"],
            ContextAdmissionReason | None,
        ]] = {}
        self._runtime_identity_cache: tuple[str, int, int, str] | None = None
        self._context_compaction_receipts: dict[
            str, list[tuple[int, float, int]]
        ] = {}
        self._coordinator = LocalRuntimeCoordinatorStatus(
            revision=0,
            state=RuntimeCoordinatorState.IDLE,
            requested=None,
            served=None,
            cleanup=RuntimeCleanupReceipt(),
            capabilities=RuntimeCapabilities(),
            context=RuntimeContextStatus(),
            active_requests=0,
            last_error_code=None,
        )
        self._load_download_ledger()

    # ----- registry -----

    @property
    def registry(self) -> LocalModelRegistry:
        return self._registry

    def add(self, request: AddLocalModel) -> LocalModelRecord:
        path = Path(request.path).expanduser()
        if not path.is_file() or path.suffix.lower() != ".gguf":
            raise LocalModelError("model_file_invalid")
        mmproj: Path | None = None
        if request.mmproj_path is not None:
            mmproj = Path(request.mmproj_path).expanduser()
            if (
                not mmproj.is_file()
                or mmproj.suffix.lower() != ".gguf"
                or mmproj.resolve() == path.resolve()
            ):
                raise LocalModelError("model_projector_invalid")
            try:
                with mmproj.open("rb") as projector_file:
                    projector_magic = projector_file.read(4)
                if projector_magic != b"GGUF":
                    raise LocalModelError("model_projector_invalid")
            except OSError:
                raise LocalModelError("model_projector_invalid") from None
        if self._registry.get(request.alias) is not None:
            raise LocalModelError("alias_exists")
        metadata = read_gguf_metadata(path)
        record = LocalModelRecord(
            alias=request.alias,
            display_name=request.display_name or path.stem[:120],
            path=str(path),
            mmproj_path=str(mmproj) if mmproj is not None else None,
            mmproj_size_bytes=mmproj.stat().st_size if mmproj is not None else None,
            size_bytes=path.stat().st_size,
            default_device=request.default_device,
            context_size=request.context_size,
            layer_count=request.layer_count or metadata.layer_count,
            architecture=metadata.architecture,
            tokenizer_model=metadata.tokenizer_model,
            training_context_size=metadata.training_context_size,
            metadata_reader_version=LOCAL_MODEL_METADATA_READER_VERSION,
            added_at=self._clock(),
        )
        self._registry.upsert(record)
        return record

    def scan_folder(self, request: ScanFolderRequest) -> ScanFolderResult:
        """Register the GGUF files in a folder; aliases come from the file names, existing paths are skipped."""

        folder = Path(request.path).expanduser()
        if not folder.is_dir():
            raise LocalModelError("folder_not_found")
        known_paths = {str(Path(record.path).resolve()) for record in self._registry.list()}
        known_aliases = {record.alias for record in self._registry.list()}
        registered: list[LocalModelRecord] = []
        skipped_existing = skipped_invalid = 0
        candidates = sorted(list(folder.glob("*.gguf")) + list(folder.glob("*/*.gguf")))[:200]
        for path in candidates:
            if not path.is_file():
                continue
            if path.name.casefold().startswith("mmproj"):
                skipped_invalid += 1
                continue
            if str(path.resolve()) in known_paths:
                skipped_existing += 1
                continue
            base = re.sub(r"[^a-z0-9._-]+", "-", path.stem.lower()).strip("-.")[:56] or "model"
            alias = base
            counter = 2
            while alias in known_aliases:
                alias = f"{base}-{counter}"
                counter += 1
            try:
                record = self.add(AddLocalModel(alias=alias, path=str(path), default_device=request.default_device))
            except (LocalModelError, ValueError):
                skipped_invalid += 1
                continue
            known_aliases.add(alias)
            known_paths.add(str(path.resolve()))
            registered.append(record)
        return ScanFolderResult(folder=str(folder), registered=tuple(registered), skipped_existing=skipped_existing, skipped_invalid=skipped_invalid)

    def remove(self, alias: str, *, delete_weights: bool = False) -> None:
        with self._lock:
            self.deactivate(alias)
            record = self._registry.get(alias)
            if record is None:
                raise LocalModelError("model_not_found")
            self._registry.remove(alias)
            if delete_weights:
                path = Path(record.path)
                try:
                    if self._registry.weights_dir.resolve() in path.resolve().parents:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ----- hardware / overview -----

    def hardware(self) -> HardwareSummary:
        return self._hardware(self._llama_server())

    def _storage_free_bytes(self) -> int | None:
        """Return filesystem free bytes without creating the model root."""

        candidate = self._registry.root
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        try:
            usage = self._disk_usage(candidate)
            value = getattr(usage, "free", None)
            if value is None and isinstance(usage, tuple) and len(usage) >= 3:
                value = usage[2]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            return value
        except (OSError, ValueError, TypeError):
            return None

    def overview(self) -> LocalModelsOverview:
        binary = self._llama_server()
        hardware = self._hardware(binary)
        with self._lock:
            downloads = tuple(self._downloads.values())
        return LocalModelsOverview(
            hardware=hardware,
            runtime_available=binary is not None,
            storage_root=str(self._registry.root),
            storage_free_bytes=self._storage_free_bytes(),
            download_ledger_error_code=self._download_ledger_error,
            models=tuple(
                self.status(record.alias, record=record, hardware=hardware)
                for record in self._registry.list()
            ),
            downloads=tuple(sorted(downloads, key=lambda d: d.started_at)),
        )

    def placement_admission(
        self,
        alias: str,
        *,
        context_size: int | None = None,
        hardware: HardwareSummary | None = None,
    ) -> LocalModelPlacementAdmission:
        """Return the current conservative placement decision for one alias."""

        record = self._registry.get(alias)
        if record is None:
            raise LocalModelError("model_not_found")
        resolved_context = context_size if context_size is not None else record.context_size
        if not 512 <= resolved_context <= MAX_CONTEXT_SIZE:
            raise LocalModelError("runtime_context_unsupported")
        with self._lock:
            owned_gpu_runtime_active = any(
                handle.process.poll() is None and (handle.status.gpu_layers or 0) > 0
                for handle in self._processes.values()
            )
        return build_placement_admission(
            record=record,
            hardware=hardware or self._hardware(self._llama_server()),
            context_size=resolved_context,
            owned_gpu_runtime_active=owned_gpu_runtime_active,
        )

    def compatibility_catalog(self) -> LocalModelCompatibilityCatalog:
        """Path-free compatibility truth for every installed alias.

        Static GGUF metadata describes identity only. ``supported`` is reserved
        for the exact alias currently served after its live text probe passed.
        """

        binary = self._llama_server()
        hardware = self._hardware(binary)
        coordinator = self.coordinator_status()
        models: list[LocalModelCompatibility] = []
        with self._lock:
            failures = dict(self._failures)
            counter_support = dict(self._context_counter_support)
            processes = dict(self._processes)
        for record in self._registry.list():
            handle = processes.get(record.alias)
            generation = handle.activation_generation if handle is not None else None
            cached_counter = counter_support.get(record.alias)
            context_counter_state: Literal["verified", "unsupported", "failed", "not_run"] = "not_run"
            if generation is not None and cached_counter is not None and cached_counter[0] == generation:
                context_counter_state = cached_counter[1]
            is_served = (
                coordinator.state is RuntimeCoordinatorState.READY
                and coordinator.served is not None
                and coordinator.served.alias == record.alias
                and coordinator.capabilities.state is RuntimeCapabilityState.VERIFIED
                and coordinator.capabilities.text
            )
            if not Path(record.path).is_file():
                state = LocalModelCompatibilityState.UNSUPPORTED
                reason = LocalModelCompatibilityReason.ARTIFACT_MISSING
                execution_state: Literal["verified", "failed", "not_run"] = "failed"
            elif is_served:
                state = LocalModelCompatibilityState.SUPPORTED
                reason = LocalModelCompatibilityReason.LIVE_TEXT_PROBE_VERIFIED
                execution_state = "verified"
            elif failures.get(record.alias) == "runtime_capability_probe_failed":
                state = LocalModelCompatibilityState.UNSUPPORTED
                reason = LocalModelCompatibilityReason.LIVE_TEXT_PROBE_FAILED
                execution_state = "failed"
            elif failures.get(record.alias) is not None:
                state = LocalModelCompatibilityState.UNKNOWN
                reason = LocalModelCompatibilityReason.RUNTIME_EXECUTION_FAILED
                execution_state = "failed"
            elif binary is None:
                state = LocalModelCompatibilityState.UNKNOWN
                reason = LocalModelCompatibilityReason.RUNTIME_UNAVAILABLE
                execution_state = "not_run"
            else:
                state = LocalModelCompatibilityState.UNKNOWN
                reason = LocalModelCompatibilityReason.MODEL_NOT_EXECUTED
                execution_state = "not_run"
            verified_identity = record.provenance_verified
            models.append(LocalModelCompatibility(
                alias=record.alias,
                state=state,
                reason_code=reason,
                architecture=record.architecture,
                tokenizer_model=record.tokenizer_model,
                training_context_size=record.training_context_size,
                metadata_reader_version=record.metadata_reader_version,
                artifact_identity_state=(
                    "verified_at_admission" if verified_identity else "unverified"
                ),
                artifact_sha256=record.sha256 if verified_identity else None,
                source_revision=record.source_revision if verified_identity else None,
                source_license=record.source_license if verified_identity else None,
                source_license_policy=record.source_license_policy if verified_identity else None,
                execution_state=execution_state,
                context_counter_state=context_counter_state,
            ))
        runtime_digest = self._runtime_binary_digest(binary)
        return LocalModelCompatibilityCatalog(
            adapter=LocalModelRuntimeAdapter(
                runtime_version=hardware.llama_server_version,
                runtime_identity_state="verified" if runtime_digest is not None else "unknown",
                runtime_binary_sha256=runtime_digest,
            ),
            models=tuple(models),
        )

    def _runtime_binary_digest(self, binary: Path | None) -> str | None:
        """Pin one exact runtime file without rehashing an unchanged binary."""

        if binary is None:
            return None
        try:
            resolved = binary.resolve()
            stat = resolved.stat()
            key = (str(resolved), stat.st_size, stat.st_mtime_ns)
            with self._lock:
                cached = self._runtime_identity_cache
                if cached is not None and cached[:3] == key:
                    return cached[3]
            digest = _digest_file(resolved)
        except OSError:
            return None
        with self._lock:
            self._runtime_identity_cache = (*key, digest)
        return digest

    @staticmethod
    def _unexpected_runtime_failure(handle: LlamaServerProcess) -> str | None:
        code = handle.process.poll()
        if code is None:
            return None
        return runtime_exit_failure_code(int(code))

    def _reap_unexpected_runtime_locked(
        self,
        alias: str,
        handle: LlamaServerProcess,
    ) -> str:
        failure = self._unexpected_runtime_failure(handle) or "runtime_exited"
        try:
            self._stop(handle)
        except LocalModelError:
            failure = "runtime_stop_failed"
        if self._processes.get(alias) is handle:
            del self._processes[alias]
        self._reaped_activation_generations[alias] = handle.activation_generation
        self._failures[alias] = failure
        return failure

    def status(
        self,
        alias: str,
        *,
        record: LocalModelRecord | None = None,
        hardware: HardwareSummary | None = None,
    ) -> LocalModelStatus:
        record = record or self._registry.get(alias)
        if record is None:
            raise LocalModelError("model_not_found")
        with self._lock:
            process = self._processes.get(alias)
            if process is not None:
                if process.process.poll() is not None:
                    failure = self._reap_unexpected_runtime_locked(alias, process)
                    runtime = RuntimeStatus(state=RuntimeState.FAILED, last_error_code=failure)
                    if (
                        self._coordinator.served is not None
                        and self._coordinator.served.alias == alias
                    ):
                        self._coordinator_update_locked(
                            state=(
                                RuntimeCoordinatorState.QUARANTINED
                                if failure == "runtime_stop_failed"
                                else RuntimeCoordinatorState.FAILED
                            ),
                            served=None,
                            capabilities=RuntimeCapabilities(
                                state=RuntimeCapabilityState.FAILED,
                                error_code=failure,
                            ),
                            context=RuntimeContextStatus(),
                            last_error_code=failure,
                        )
                else:
                    runtime = process.status
            else:
                failure = self._failures.get(alias)
                runtime = RuntimeStatus(state=RuntimeState.FAILED, last_error_code=failure) if failure else RuntimeStatus()
        placement = self.placement_admission(
            alias,
            context_size=record.context_size,
            hardware=hardware,
        )
        return LocalModelStatus(
            record=record,
            runtime=runtime,
            placement=placement,
            endpoint_path=f"/v1/local-models/{alias}/chat/completions",
        )

    def coordinator_status(self) -> LocalRuntimeCoordinatorStatus:
        with self._lock:
            served = self._coordinator.served
            if served is not None:
                handle = self._processes.get(served.alias)
                if handle is None or handle.process.poll() is not None:
                    failure = (
                        self._reap_unexpected_runtime_locked(served.alias, handle)
                        if handle is not None
                        else self._failures.get(served.alias, "runtime_exited")
                    )
                    self._coordinator_update_locked(
                        state=(
                            RuntimeCoordinatorState.QUARANTINED
                            if failure == "runtime_stop_failed"
                            else RuntimeCoordinatorState.FAILED
                        ),
                        served=None,
                        capabilities=RuntimeCapabilities(
                            state=RuntimeCapabilityState.FAILED,
                            error_code=failure,
                        ),
                        context=RuntimeContextStatus(),
                        last_error_code=failure,
                    )
            return self._coordinator.model_copy(
                update={"active_requests": sum(self._active_requests.values())}
            )

    def _coordinator_update_locked(self, **changes: object) -> None:
        self._coordinator = self._coordinator.model_copy(
            update={"revision": self._coordinator.revision + 1, **changes}
        )

    @staticmethod
    def _probe_payload(alias: str) -> bytes:
        return json.dumps(
            {
                "model": alias,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with OK. This is a synthetic local capability probe.",
                    }
                ],
                "temperature": 0,
                "max_tokens": 1,
                "stream": False,
            }
        ).encode("utf-8")

    @staticmethod
    def _media_probe_payload(alias: str, modality: Literal["image", "audio"]) -> bytes:
        if modality == "image":
            # Synthetic 1x1 PNG; no owner data is read or sent during probing.
            encoded = (
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
                "EQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            part: dict[str, object] = {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        else:
            # 50 ms of synthetic PCM silence, mono/16-bit/16 kHz.
            frames = b"\x00\x00" * 800
            wav = (
                b"RIFF"
                + (36 + len(frames)).to_bytes(4, "little")
                + b"WAVEfmt "
                + (16).to_bytes(4, "little")
                + (1).to_bytes(2, "little")
                + (1).to_bytes(2, "little")
                + (16_000).to_bytes(4, "little")
                + (32_000).to_bytes(4, "little")
                + (2).to_bytes(2, "little")
                + (16).to_bytes(2, "little")
                + b"data"
                + len(frames).to_bytes(4, "little")
                + frames
            )
            part = {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.b64encode(wav).decode("ascii"),
                    "format": "wav",
                },
            }
        return json.dumps(
            {
                "model": alias,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Reply with OK. Synthetic local media capability probe."},
                        part,
                    ],
                }],
                "temperature": 0,
                "max_tokens": 1,
                "stream": False,
            }
        ).encode("utf-8")

    @staticmethod
    def _probe_chat(handle: LlamaServerProcess, payload: bytes) -> bool:
        request = urllib.request.Request(
            f"{handle.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _runtime_opener().open(request, timeout=30) as response:
                if response.status != 200:
                    return False
                body = model_json_object(
                    response.read(64_001).decode("utf-8"), max_characters=64_000
                )
        except (OSError, UnicodeDecodeError, ValueError, urllib.error.URLError):
            return False
        choices = body.get("choices") if body is not None else None
        return isinstance(choices, list) and bool(choices)

    @staticmethod
    def _advertised_input_modalities(
        handle: LlamaServerProcess,
    ) -> tuple[frozenset[str], bool]:
        """Read only closed modality labels from llama.cpp's model endpoint.

        llama.cpp has exposed both an exact ``architecture.input_modalities``
        form and a generic ``capabilities: [\"multimodal\"]`` form across
        releases.  Unknown shapes fail closed and no model name is inspected.
        """

        request = urllib.request.Request(
            f"{handle.base_url}/v1/models",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with _runtime_opener().open(request, timeout=10) as response:
                if response.status != 200:
                    return frozenset(), False
                payload = model_json_object(
                    response.read(128_001).decode("utf-8"), max_characters=128_000
                )
        except (OSError, UnicodeDecodeError, ValueError, urllib.error.URLError):
            return frozenset(), False
        data = payload.get("data") if payload is not None else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return frozenset(), False
        entry = data[0]
        exact: set[str] = set()
        containers: list[dict[str, object]] = [entry]
        for key in ("architecture", "meta"):
            child = entry.get(key)
            if isinstance(child, dict):
                containers.append(child)
                nested = child.get("architecture")
                if isinstance(nested, dict):
                    containers.append(nested)
        for container in containers:
            for key in ("input_modalities", "modalities"):
                values = container.get(key)
                if isinstance(values, list):
                    exact.update(
                        value.casefold()
                        for value in values
                        if isinstance(value, str) and len(value) <= 32
                    )
        capabilities = entry.get("capabilities")
        capability_labels = {
            value.casefold()
            for value in capabilities
            if isinstance(value, str) and len(value) <= 32
        } if isinstance(capabilities, list) else set()
        generic = "multimodal" in capability_labels
        return frozenset(exact), generic

    def _probe_runtime_capabilities(
        self,
        handle: LlamaServerProcess,
        alias: str,
        tool_calling: bool,
    ) -> RuntimeCapabilities:
        if not self._probe_chat(handle, self._probe_payload(alias)):
            return RuntimeCapabilities(
                state=RuntimeCapabilityState.FAILED,
                error_code="runtime_capability_probe_failed",
            )
        modalities, generic_multimodal = self._advertised_input_modalities(handle)
        probe_image = generic_multimodal or bool({"image", "vision"} & modalities)
        probe_audio = generic_multimodal or "audio" in modalities
        vision = probe_image and self._probe_chat(
            handle, self._media_probe_payload(alias, "image")
        )
        audio = probe_audio and self._probe_chat(
            handle, self._media_probe_payload(alias, "audio")
        )
        return RuntimeCapabilities(
            state=RuntimeCapabilityState.VERIFIED,
            text=True,
            tools=tool_calling,
            vision=vision,
            audio=audio,
            recording=audio,
        )

    @staticmethod
    def _cleanup_receipt(
        before: HardwareSummary,
        after: HardwareSummary,
        *,
        gpu_cleanup_required: bool,
    ) -> RuntimeCleanupReceipt:
        if not gpu_cleanup_required:
            return RuntimeCleanupReceipt()
        before_free = before.gpu_memory_free_mb
        after_free = after.gpu_memory_free_mb
        if before_free is None or after_free is None or after_free < before_free:
            return RuntimeCleanupReceipt(
                state=RuntimeCleanupState.UNKNOWN,
                process_exit_confirmed=True,
            )
        return RuntimeCleanupReceipt(
            state=RuntimeCleanupState.MEASURED,
            process_exit_confirmed=True,
            gpu_memory_free_before_mb=before_free,
            gpu_memory_free_after_mb=after_free,
            gpu_memory_released_mb=after_free - before_free,
        )

    # ----- runtime -----

    def activate(
        self,
        alias: str,
        request: ActivateLocalModel | None = None,
        *,
        expected_revision: int | None = None,
    ) -> LocalModelStatus:
        request = request or ActivateLocalModel()
        with self._lock:
            if self._shutting_down:
                raise LocalModelError("runtime_shutdown_in_progress")
            if expected_revision is not None and expected_revision != self._coordinator.revision:
                raise LocalModelError("runtime_revision_conflict")
            if self._coordinator.state in {
                RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                RuntimeCoordinatorState.QUARANTINED,
            }:
                raise LocalModelError("runtime_quarantined")
            if self._coordinator.state in {
                RuntimeCoordinatorState.DRAINING,
                RuntimeCoordinatorState.UNLOADING,
            }:
                raise LocalModelError("runtime_busy")
            observed_shutdown_generation = self._shutdown_generation
            observed_command_generation = self._runtime_command_generations.get(alias, 0)
            observed_global_generation = self._global_runtime_command_generation
            owned_gpu_runtime_active = any(
                handle.process.poll() is None and (handle.status.gpu_layers or 0) > 0
                for handle in self._processes.values()
            )
        record = self._registry.get(alias)
        if record is None:
            raise LocalModelError("model_not_found")
        binary = self._llama_server()
        if binary is None:
            raise LocalModelError("runtime_unavailable")
        path = Path(record.path)
        if not path.is_file():
            raise LocalModelError("model_file_missing")
        mmproj_path = Path(record.mmproj_path) if record.mmproj_path is not None else None
        if mmproj_path is not None:
            if not mmproj_path.is_file():
                raise LocalModelError("model_projector_missing")
            try:
                with mmproj_path.open("rb") as projector_file:
                    projector_magic = projector_file.read(4)
            except OSError:
                raise LocalModelError("model_projector_invalid") from None
            if projector_magic != b"GGUF":
                raise LocalModelError("model_projector_invalid")
        device = request.device or record.default_device
        context = request.context_size or record.context_size
        if record.training_context_size is not None and context > record.training_context_size:
            raise LocalModelError("runtime_context_unsupported")
        requested_gpu_layers = request.gpu_layers
        if device is DeviceMode.CPU and requested_gpu_layers not in {None, 0}:
            raise LocalModelError("runtime_gpu_layers_invalid")
        if (
            device is DeviceMode.GPU
            and requested_gpu_layers is not None
            and requested_gpu_layers != 999
            and requested_gpu_layers != record.layer_count
        ):
            raise LocalModelError("runtime_gpu_layers_invalid")
        split_gpu_layers = (
            requested_gpu_layers
            if requested_gpu_layers is not None
            else record.default_gpu_layers
        )
        if device is DeviceMode.SPLIT and split_gpu_layers is not None and (
            split_gpu_layers <= 0
            or record.layer_count is None
            or split_gpu_layers > record.layer_count
        ):
            raise LocalModelError("runtime_gpu_layers_invalid")
        hardware_before = self._hardware(binary)
        admission_before = build_placement_admission(
            record=record,
            hardware=hardware_before,
            context_size=context,
            owned_gpu_runtime_active=owned_gpu_runtime_active,
        )
        option_before = next(
            option for option in admission_before.options if option.device is device
        )
        if option_before.state is PlacementAdmissionState.BLOCKED:
            raise LocalModelError("runtime_placement_unavailable")
        if (
            option_before.state is PlacementAdmissionState.AVAILABLE
            and device is DeviceMode.SPLIT
            and split_gpu_layers is not None
            and option_before.recommended_gpu_layers is not None
            and split_gpu_layers > option_before.recommended_gpu_layers
        ):
            raise LocalModelError("runtime_placement_unavailable")
        if device is DeviceMode.CPU:
            gpu_layers = 0
        elif device is DeviceMode.GPU:
            gpu_layers = request.gpu_layers if request.gpu_layers is not None else 999
        elif split_gpu_layers is not None:
            gpu_layers = split_gpu_layers
        else:
            # A running app-owned GPU process makes current free VRAM
            # conditional. Zero is only a private placeholder until cleanup is
            # confirmed and the authoritative estimate is recomputed below.
            gpu_layers = option_before.recommended_gpu_layers or 0
        selection = LocalRuntimeSelection(
            alias=alias,
            device=device,
            gpu_layers=gpu_layers,
            context_size=context,
        )
        with self._lock:
            if (
                self._shutdown_generation != observed_shutdown_generation
                or self._runtime_command_generations.get(alias, 0) != observed_command_generation
                or self._global_runtime_command_generation != observed_global_generation
            ):
                raise LocalModelError("runtime_activation_superseded")
            if expected_revision is not None and expected_revision != self._coordinator.revision:
                raise LocalModelError("runtime_revision_conflict")
            if self._coordinator.state in {
                RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                RuntimeCoordinatorState.QUARANTINED,
            }:
                raise LocalModelError("runtime_quarantined")
            if self._coordinator.state in {
                RuntimeCoordinatorState.DRAINING,
                RuntimeCoordinatorState.UNLOADING,
            }:
                raise LocalModelError("runtime_busy")
            activation_generation = observed_command_generation + 1
            self._runtime_command_generations[alias] = activation_generation
            self._global_runtime_command_generation += 1
            global_generation = self._global_runtime_command_generation
            if sum(self._active_requests.values()) > 0:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.DRAINING,
                    requested=selection,
                    last_error_code="runtime_busy",
                )
                raise LocalModelError("runtime_busy")
            previous = tuple(self._processes.items())
            gpu_cleanup_required = any(
                (handle.status.gpu_layers or 0) > 0 for _, handle in previous
            )
            if previous:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.UNLOADING,
                    requested=selection,
                    last_error_code=None,
                )
            try:
                for previous_alias, _handle in previous:
                    self._deactivate_locked(previous_alias)
            except LocalModelError:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.QUARANTINED,
                    requested=selection,
                    cleanup=RuntimeCleanupReceipt(
                        state=RuntimeCleanupState.FAILED,
                        process_exit_confirmed=False,
                    ),
                    last_error_code="runtime_stop_failed",
                )
                raise

        cleanup = RuntimeCleanupReceipt()
        hardware_after = hardware_before
        if previous:
            hardware_after = self._hardware(binary)
            cleanup = self._cleanup_receipt(
                hardware_before,
                hardware_after,
                gpu_cleanup_required=gpu_cleanup_required,
            )
        final_admission = build_placement_admission(
            record=record,
            hardware=hardware_after,
            context_size=context,
        )
        final_option = next(
            option for option in final_admission.options if option.device is device
        )
        if device is DeviceMode.CPU:
            gpu_layers = 0
        elif device is DeviceMode.GPU:
            gpu_layers = request.gpu_layers if request.gpu_layers is not None else 999
        elif split_gpu_layers is not None:
            gpu_layers = split_gpu_layers
        else:
            gpu_layers = final_option.recommended_gpu_layers or 0
        selection = LocalRuntimeSelection(
            alias=alias,
            device=device,
            gpu_layers=gpu_layers,
            context_size=context,
        )
        with self._lock:
            if (
                self._shutdown_generation != observed_shutdown_generation
                or self._global_runtime_command_generation != global_generation
                or self._runtime_command_generations.get(alias, 0) > activation_generation
            ):
                raise LocalModelError("runtime_activation_superseded")
            if cleanup.state is RuntimeCleanupState.UNKNOWN:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                    requested=selection,
                    served=None,
                    cleanup=cleanup,
                    capabilities=RuntimeCapabilities(),
                    context=RuntimeContextStatus(),
                    last_error_code="runtime_cleanup_unconfirmed",
                )
                raise LocalModelError("runtime_cleanup_unconfirmed")
            if final_option.state is not PlacementAdmissionState.AVAILABLE:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.FAILED,
                    requested=None,
                    served=None,
                    cleanup=cleanup,
                    capabilities=RuntimeCapabilities(),
                    context=RuntimeContextStatus(),
                    last_error_code="runtime_placement_unavailable",
                )
                raise LocalModelError("runtime_placement_unavailable")
            if (
                device is DeviceMode.SPLIT
                and split_gpu_layers is not None
                and final_option.recommended_gpu_layers is not None
                and split_gpu_layers > final_option.recommended_gpu_layers
            ):
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.FAILED,
                    requested=None,
                    served=None,
                    cleanup=cleanup,
                    capabilities=RuntimeCapabilities(),
                    context=RuntimeContextStatus(),
                    last_error_code="runtime_placement_unavailable",
                )
                raise LocalModelError("runtime_placement_unavailable")
            if request.remember:
                self._registry.upsert(
                    record.model_copy(
                        update={
                            "default_device": device,
                            "default_gpu_layers": (
                                gpu_layers
                                if device is DeviceMode.SPLIT
                                else record.default_gpu_layers
                            ),
                            "context_size": context,
                        }
                    )
                )
                record = self._registry.get(alias) or record
            self._coordinator_update_locked(
                state=RuntimeCoordinatorState.LOADING,
                requested=selection,
                served=None,
                cleanup=cleanup,
                capabilities=RuntimeCapabilities(),
                context=RuntimeContextStatus(),
                last_error_code=None,
            )

        attempts = [(request.fast_attention, request.tool_calling)]
        if request.fast_attention:
            attempts.append((False, request.tool_calling))
        last_error = "runtime_not_healthy"
        for attempt_index, (fast_attention, tool_calling) in enumerate(attempts):
            with self._lock:
                if (
                    self._shutdown_generation != observed_shutdown_generation
                    or self._global_runtime_command_generation != global_generation
                    or self._runtime_command_generations.get(alias, 0) > activation_generation
                ):
                    raise LocalModelError("runtime_activation_superseded")
                port = free_loopback_port()
                command = [
                    str(binary), "-m", str(path), "--host", "127.0.0.1", "--port", str(port),
                    "-ngl", str(gpu_layers), "-c", str(context), "--no-webui",
                ]
                if mmproj_path is not None:
                    command += ["--mmproj", str(mmproj_path)]
                if fast_attention:
                    command += ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]
                if tool_calling:
                    command.append("--jinja")
                started_at = self._clock()
                try:
                    process = self._popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        shell=False,
                        creationflags=_runtime_creation_flags(),
                    )
                except OSError:
                    self._failures[alias] = "runtime_spawn_failed"
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.FAILED,
                        last_error_code="runtime_spawn_failed",
                    )
                    raise LocalModelError("runtime_spawn_failed") from None
                handle = LlamaServerProcess(
                    process=process,
                    port=port,
                    activation_generation=activation_generation,
                    status=RuntimeStatus(
                        state=RuntimeState.STARTING,
                        device=device,
                        gpu_layers=gpu_layers,
                        context_size=context,
                        started_at=started_at,
                        pid=process.pid,
                        fast_attention=fast_attention,
                        tool_calling=tool_calling,
                    ),
                )
                self._processes[alias] = handle
                self._context_counter_support.pop(alias, None)
                self._reaped_activation_generations.pop(alias, None)
                self._failures.pop(alias, None)

            healthy = self._wait_healthy(handle)
            if healthy:
                capabilities = self._capability_probe(handle, alias, tool_calling)
            else:
                observed_exit = self._unexpected_runtime_failure(handle)
                capabilities = RuntimeCapabilities(
                    state=RuntimeCapabilityState.FAILED,
                    error_code=observed_exit or "runtime_not_healthy",
                )
            with self._lock:
                current = self._processes.get(alias)
                superseded = (
                    self._shutdown_generation != observed_shutdown_generation
                    or self._global_runtime_command_generation != global_generation
                    or self._runtime_command_generations.get(alias, 0) > activation_generation
                )
                if superseded:
                    self._stop(handle)
                    if current is handle:
                        del self._processes[alias]
                    raise LocalModelError("runtime_activation_superseded")
                if (
                    healthy
                    and capabilities.state is RuntimeCapabilityState.VERIFIED
                    and current is handle
                    and handle.process.poll() is None
                ):
                    handle.status = handle.status.model_copy(update={"state": RuntimeState.RUNNING})
                    served = LocalRuntimeServedSelection(
                        **selection.model_dump(),
                        started_at=started_at,
                        pid=process.pid,
                    )
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.READY,
                        requested=selection,
                        served=served,
                        capabilities=capabilities,
                        context=RuntimeContextStatus(
                            limit_tokens=context,
                            reason_code=ContextAdmissionReason.NO_REQUEST_MEASURED,
                        ),
                        last_error_code=None,
                    )
                    return self.status(alias, record=record)
                failure_code = capabilities.error_code or last_error
                before_failed_stop = self._hardware(binary)
                try:
                    self._stop(handle)
                except LocalModelError:
                    handle.status = handle.status.model_copy(
                        update={"state": RuntimeState.FAILED, "last_error_code": "runtime_stop_failed"}
                    )
                    self._failures[alias] = "runtime_stop_failed"
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.QUARANTINED,
                        cleanup=RuntimeCleanupReceipt(
                            state=RuntimeCleanupState.FAILED,
                            process_exit_confirmed=False,
                        ),
                        capabilities=capabilities,
                        last_error_code="runtime_stop_failed",
                    )
                    raise
                if self._processes.get(alias) is handle:
                    del self._processes[alias]
                self._failures[alias] = failure_code

            failed_cleanup = self._cleanup_receipt(
                before_failed_stop,
                self._hardware(binary),
                gpu_cleanup_required=gpu_layers > 0,
            )
            with self._lock:
                if failed_cleanup.state is RuntimeCleanupState.UNKNOWN:
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                        served=None,
                        cleanup=failed_cleanup,
                        capabilities=capabilities,
                        context=RuntimeContextStatus(),
                        last_error_code="runtime_cleanup_unconfirmed",
                    )
                    raise LocalModelError("runtime_cleanup_unconfirmed")
                if attempt_index + 1 < len(attempts):
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.LOADING,
                        served=None,
                        cleanup=failed_cleanup,
                        capabilities=RuntimeCapabilities(),
                        context=RuntimeContextStatus(),
                        last_error_code=None,
                    )
                    continue
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.FAILED,
                    served=None,
                    cleanup=failed_cleanup,
                    capabilities=capabilities,
                    context=RuntimeContextStatus(),
                    last_error_code=failure_code,
                )
                raise LocalModelError(failure_code)
        raise LocalModelError(last_error)

    def _wait_healthy(self, handle: LlamaServerProcess) -> bool:
        deadline = time.monotonic() + self._health_timeout
        while time.monotonic() < deadline:
            if handle.process.poll() is not None:
                return False
            try:
                with _runtime_opener().open(f"{handle.base_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.5)
        return False

    def deactivate(self, alias: str, *, expected_revision: int | None = None) -> None:
        """Stop the globally served runtime without racing an in-flight request.

        A GPU-backed runtime is not reported as clean until the process exit and
        a non-decreasing free-VRAM measurement are both observed.  When that
        evidence is unavailable the coordinator fails closed instead of loading
        another model on top of memory whose ownership is unknown.
        """

        binary = self._llama_server()
        with self._lock:
            if expected_revision is not None and expected_revision != self._coordinator.revision:
                raise LocalModelError("runtime_revision_conflict")
            if self._coordinator.state is RuntimeCoordinatorState.CLEANUP_UNKNOWN:
                raise LocalModelError("runtime_cleanup_unconfirmed")
            if self._coordinator.state is RuntimeCoordinatorState.UNLOADING:
                raise LocalModelError("runtime_busy")
            # Even before a process exists, this alias may have an activation in
            # its hardware-discovery phase.  Bump its generation so Stop wins.
            self._runtime_command_generations[alias] = (
                self._runtime_command_generations.get(alias, 0) + 1
            )
            handle = self._processes.get(alias)
            served = self._coordinator.served
            if handle is None:
                # Stopping a stale card must never stop a different model.
                if served is None and self._coordinator.state not in {
                    RuntimeCoordinatorState.QUARANTINED,
                    RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                }:
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.IDLE,
                        requested=None,
                        served=None,
                        cleanup=RuntimeCleanupReceipt(),
                        capabilities=RuntimeCapabilities(),
                        context=RuntimeContextStatus(),
                        last_error_code=None,
                    )
                return
            if sum(self._active_requests.values()) > 0:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.DRAINING,
                    requested=(
                        LocalRuntimeSelection(
                            alias=served.alias,
                            device=served.device,
                            gpu_layers=served.gpu_layers,
                            context_size=served.context_size,
                        )
                        if served is not None
                        else None
                    ),
                    last_error_code="runtime_busy",
                )
                raise LocalModelError("runtime_busy")
            self._global_runtime_command_generation += 1
            operation_generation = self._global_runtime_command_generation
            gpu_cleanup_required = (handle.status.gpu_layers or 0) > 0
            hardware_before = self._hardware(binary)
            self._coordinator_update_locked(
                state=RuntimeCoordinatorState.UNLOADING,
                requested=None,
                last_error_code=None,
            )
            try:
                self._deactivate_locked(alias)
            except LocalModelError:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.QUARANTINED,
                    cleanup=RuntimeCleanupReceipt(
                        state=RuntimeCleanupState.FAILED,
                        process_exit_confirmed=False,
                    ),
                    last_error_code="runtime_stop_failed",
                )
                raise

        cleanup = self._cleanup_receipt(
            hardware_before,
            self._hardware(binary),
            gpu_cleanup_required=gpu_cleanup_required,
        )
        with self._lock:
            if self._global_runtime_command_generation != operation_generation:
                return
            if cleanup.state is RuntimeCleanupState.UNKNOWN:
                self._coordinator_update_locked(
                    state=RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                    requested=None,
                    served=None,
                    cleanup=cleanup,
                    capabilities=RuntimeCapabilities(),
                    context=RuntimeContextStatus(),
                    last_error_code="runtime_cleanup_unconfirmed",
                )
                raise LocalModelError("runtime_cleanup_unconfirmed")
            self._coordinator_update_locked(
                state=RuntimeCoordinatorState.IDLE,
                requested=None,
                served=None,
                cleanup=cleanup,
                capabilities=RuntimeCapabilities(),
                context=RuntimeContextStatus(),
                last_error_code=None,
            )

    def switch_runtime(self, request: SwitchLocalRuntime) -> LocalRuntimeCoordinatorStatus:
        activation = ActivateLocalModel.model_validate(
            request.model_dump(exclude={"alias", "expected_revision"})
        )
        self.activate(
            request.alias,
            activation,
            expected_revision=request.expected_revision,
        )
        return self.coordinator_status()

    def stop_runtime(self, request: StopLocalRuntime) -> LocalRuntimeCoordinatorStatus:
        self.deactivate(request.alias, expected_revision=request.expected_revision)
        return self.coordinator_status()

    def _deactivate_locked(self, alias: str) -> None:
        """Stop one alias without superseding an activation's internal retry."""

        self._reaped_activation_generations.pop(alias, None)
        handle = self._processes.get(alias)
        if handle is not None:
            try:
                self._stop(handle)
            except LocalModelError:
                handle.status = handle.status.model_copy(
                    update={
                        "state": RuntimeState.FAILED,
                        "last_error_code": "runtime_stop_failed",
                    }
                )
                self._failures[alias] = "runtime_stop_failed"
                raise
            if self._processes.get(alias) is handle:
                del self._processes[alias]
        self._failures.pop(alias, None)

    @staticmethod
    def _stop(handle: LlamaServerProcess) -> None:
        process = handle.process
        initial_root = process.poll()
        initial_tree_exited = initial_root is not None
        initial_tree_probe = getattr(process, "tree_exited", None)
        if callable(initial_tree_probe):
            try:
                initial_tree_exited = bool(initial_tree_probe())
            except Exception:
                initial_tree_exited = False
        if initial_root is None or not initial_tree_exited:
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.wait(timeout=10)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=10)
                except Exception:
                    pass
        root_exited = process.poll() is not None
        tree_exited = True
        tree_probe = getattr(process, "tree_exited", None)
        if callable(tree_probe):
            try:
                tree_exited = bool(tree_probe())
            except Exception:
                tree_exited = False
        closed = True
        close = getattr(process, "close", None)
        if callable(close):
            try:
                closed = close() is not False
            except Exception:
                closed = False
        if not root_exited or not tree_exited or not closed:
            raise LocalModelError("runtime_stop_failed")

    def shutdown(self) -> None:
        failed = False
        download_workers: list[threading.Thread] = []
        with self._lock:
            self._shutting_down = True
            self._shutdown_generation += 1
            for download_id, worker in tuple(self._download_workers.items()):
                control = self._download_controls.get(download_id)
                if control is not None:
                    control.pause.set()
                job = self._download_jobs.get(download_id)
                if job is not None and job.status.state in {"queued", "downloading"}:
                    self._replace_download_status(
                        download_id,
                        state="pausing",
                        error_code=None,
                    )
                download_workers.append(worker)
            aliases = set(self._runtime_command_generations) | set(self._processes)
            for alias in aliases:
                self._runtime_command_generations[alias] = (
                    self._runtime_command_generations.get(alias, 0) + 1
                )
        deadline = time.monotonic() + self._download_join_timeout
        for worker in download_workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
            if worker.is_alive():
                failed = True
        with self._lock:
            for alias in list(self._processes):
                try:
                    self._deactivate_locked(alias)
                except LocalModelError:
                    failed = True
        if failed:
            raise LocalModelError("runtime_shutdown_failed")

    # ----- chat proxy -----

    def running_aliases(self) -> tuple[str, ...]:
        """The single capability-verified runtime exposed to OpenAI clients."""

        status = self.coordinator_status()
        if status.state is not RuntimeCoordinatorState.READY or status.served is None:
            return ()
        return (status.served.alias,)

    def _prepare_chat(self, alias: str, body: bytes) -> tuple[LlamaServerProcess, dict[str, object]]:
        if len(body) > MAX_CHAT_BODY_BYTES:
            raise LocalModelError("chat_body_too_large")
        with self._lock:
            handle = self._processes.get(alias)
            if handle is not None and handle.process.poll() is not None:
                failure = self._reap_unexpected_runtime_locked(alias, handle)
                if (
                    self._coordinator.served is not None
                    and self._coordinator.served.alias == alias
                ):
                    self._coordinator_update_locked(
                        state=(
                            RuntimeCoordinatorState.QUARANTINED
                            if failure == "runtime_stop_failed"
                            else RuntimeCoordinatorState.FAILED
                        ),
                        served=None,
                        capabilities=RuntimeCapabilities(
                            state=RuntimeCapabilityState.FAILED,
                            error_code=failure,
                        ),
                        context=RuntimeContextStatus(),
                        last_error_code=failure,
                    )
                handle = None
            if handle is None or handle.status.state is not RuntimeState.RUNNING:
                raise LocalModelError("model_not_active")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise LocalModelError("chat_body_invalid") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
            raise LocalModelError("chat_body_invalid")
        payload["model"] = alias
        return handle, payload

    @staticmethod
    def _requested_output_tokens(payload: dict[str, object]) -> int | None:
        value = payload.get(
            "max_completion_tokens",
            payload.get("max_tokens"),
        )
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise LocalModelError("chat_body_invalid")
        return value

    def _publish_context(
        self,
        alias: str,
        handle: LlamaServerProcess,
        context: RuntimeContextStatus,
    ) -> None:
        with self._lock:
            served = self._coordinator.served
            if (
                served is not None
                and served.alias == alias
                and self._processes.get(alias) is handle
                and handle.process.poll() is None
            ):
                self._coordinator_update_locked(context=context)

    @staticmethod
    def _context_request_fingerprint(payload: dict[str, object]) -> str:
        normalized = {
            key: value for key, value in payload.items()
            if key not in {"stream", "stream_options"}
        }
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _remember_context_compaction(
        self,
        handle: LlamaServerProcess,
        payload: dict[str, object],
        compacted_messages: int,
    ) -> None:
        if compacted_messages <= 0:
            return
        key = self._context_request_fingerprint(payload)
        now = time.monotonic()
        with self._lock:
            for receipt_key in tuple(self._context_compaction_receipts):
                current = [
                    receipt for receipt in self._context_compaction_receipts[receipt_key]
                    if receipt[1] > now
                ]
                if current:
                    self._context_compaction_receipts[receipt_key] = current
                else:
                    del self._context_compaction_receipts[receipt_key]
            if sum(map(len, self._context_compaction_receipts.values())) >= 128:
                self._context_compaction_receipts.clear()
            self._context_compaction_receipts.setdefault(key, []).append((
                handle.activation_generation,
                now + 30.0,
                compacted_messages,
            ))

    def _consume_context_compaction(
        self,
        handle: LlamaServerProcess,
        payload: dict[str, object],
    ) -> int:
        key = self._context_request_fingerprint(payload)
        now = time.monotonic()
        with self._lock:
            receipts = self._context_compaction_receipts.get(key, [])
            for index, (generation, expires_at, count) in enumerate(receipts):
                if generation == handle.activation_generation and expires_at > now:
                    receipts.pop(index)
                    if not receipts:
                        self._context_compaction_receipts.pop(key, None)
                    return count
            self._context_compaction_receipts.pop(key, None)
        return 0

    def _count_chat_input_tokens(
        self,
        alias: str,
        handle: LlamaServerProcess,
        payload: dict[str, object],
    ) -> tuple[int | None, ContextAdmissionReason | None]:
        """Ask the exact served runtime to apply its chat template and tokenize.

        Unsupported/malformed counter interfaces fail to a closed unknown
        state for this activation generation; they never trigger a fallback
        tokenizer or a character estimate.
        """

        with self._lock:
            cached = self._context_counter_support.get(alias)
            if cached is not None and cached[0] == handle.activation_generation:
                if cached[1] != "verified":
                    return None, cached[2] or ContextAdmissionReason.INPUT_COUNTER_FAILED
        request = urllib.request.Request(
            f"{handle.base_url}/v1/chat/completions/input_tokens",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._reserve_runtime_request(alias, handle)
        try:
            try:
                response = _runtime_opener().open(request, timeout=30)
            except urllib.error.HTTPError as error:
                with error:
                    error.read(65_537)
                support: Literal["unsupported", "failed"] = (
                    "unsupported" if error.code in {404, 405, 501} else "failed"
                )
                reason = (
                    ContextAdmissionReason.INPUT_COUNTER_UNAVAILABLE
                    if support == "unsupported"
                    else ContextAdmissionReason.INPUT_COUNTER_FAILED
                )
                with self._lock:
                    self._context_counter_support[alias] = (
                        handle.activation_generation,
                        support,
                        reason,
                    )
                return None, reason
            with response:
                raw = response.read(65_537)
                status = response.status
            if status != 200:
                with self._lock:
                    self._context_counter_support[alias] = (
                        handle.activation_generation,
                        "failed",
                        ContextAdmissionReason.INPUT_COUNTER_FAILED,
                    )
                return None, ContextAdmissionReason.INPUT_COUNTER_FAILED
            try:
                decoded = json.loads(raw.decode("utf-8")) if len(raw) <= 65_536 else None
            except (UnicodeDecodeError, ValueError):
                decoded = None
            tokens = decoded.get("input_tokens") if isinstance(decoded, dict) else None
            if (
                not isinstance(tokens, int)
                or isinstance(tokens, bool)
                or not 0 <= tokens <= MAX_CHAT_BODY_BYTES
            ):
                with self._lock:
                    self._context_counter_support[alias] = (
                        handle.activation_generation,
                        "failed",
                        ContextAdmissionReason.INPUT_COUNTER_INVALID,
                    )
                return None, ContextAdmissionReason.INPUT_COUNTER_INVALID
            with self._lock:
                self._context_counter_support[alias] = (
                    handle.activation_generation,
                    "verified",
                    None,
                )
            return tokens, None
        except (urllib.error.URLError, OSError):
            return None, ContextAdmissionReason.INPUT_COUNTER_FAILED
        finally:
            self._release_runtime_request(alias)

    def _context_preflight(
        self,
        alias: str,
        handle: LlamaServerProcess,
        payload: dict[str, object],
        *,
        compacted_messages: int,
        enforce: bool,
    ) -> RuntimeContextStatus:
        requested_output = self._requested_output_tokens(payload)
        limit = handle.status.context_size
        if limit is None:
            # A running handle without its configured limit is a contract
            # violation. Keep the value unknown and let the runtime reject.
            context = RuntimeContextStatus(
                reason_code=ContextAdmissionReason.INPUT_COUNTER_FAILED,
            )
            self._publish_context(alias, handle, context)
            return context
        used, failure = self._count_chat_input_tokens(alias, handle, payload)
        if used is None:
            context = RuntimeContextStatus(
                limit_tokens=limit,
                reason_code=failure or ContextAdmissionReason.INPUT_COUNTER_FAILED,
            )
            self._publish_context(alias, handle, context)
            return context
        available = limit - used
        overflow = available < 0 or (
            requested_output is not None and requested_output > available
        )
        context = RuntimeContextStatus(
            state="known",
            used_tokens=used,
            limit_tokens=limit,
            requested_output_tokens=requested_output,
            available_output_tokens=available,
            source="runtime_chat_input_tokens",
            scope="last_request",
            policy=(
                "exact_refused"
                if overflow
                else "exact_compacted"
                if compacted_messages > 0
                else "exact_admitted"
            ),
            compacted_messages=compacted_messages,
            reason_code=(
                ContextAdmissionReason.CONTEXT_WINDOW_EXCEEDED if overflow else None
            ),
        )
        self._publish_context(alias, handle, context)
        if overflow and enforce:
            raise LocalModelError("context_window_exceeded")
        return context

    def preflight_chat(
        self,
        alias: str,
        body: bytes,
        *,
        compacted_messages: int = 0,
    ) -> RuntimeContextStatus:
        """Measure one request without inference; unknown is explicit and safe."""

        handle, payload = self._prepare_chat(alias, body)
        context = self._context_preflight(
            alias,
            handle,
            payload,
            compacted_messages=compacted_messages,
            enforce=False,
        )
        if context.policy == "exact_compacted":
            self._remember_context_compaction(
                handle,
                payload,
                context.compacted_messages,
            )
        return context

    def chat_input_tokens(self, alias: str, body: bytes) -> ChatInputTokenCount:
        """Return the exact served chat-template token count or fail unknown."""

        context = self.preflight_chat(alias, body)
        if context.state != "known" or context.used_tokens is None:
            raise LocalModelError("input_tokens_unavailable")
        return ChatInputTokenCount(input_tokens=context.used_tokens)

    def _reserve_runtime_request(self, alias: str, handle: LlamaServerProcess) -> None:
        """Admit one inference only while the exact verified runtime is served."""

        with self._lock:
            served = self._coordinator.served
            if (
                self._coordinator.state is not RuntimeCoordinatorState.READY
                or self._coordinator.capabilities.state is not RuntimeCapabilityState.VERIFIED
                or served is None
                or served.alias != alias
                or self._processes.get(alias) is not handle
                or handle.process.poll() is not None
                or handle.status.state is not RuntimeState.RUNNING
            ):
                raise LocalModelError("model_not_active")
            self._active_requests[alias] = self._active_requests.get(alias, 0) + 1

    def _release_runtime_request(self, alias: str) -> None:
        with self._lock:
            remaining = self._active_requests.get(alias, 0) - 1
            if remaining > 0:
                self._active_requests[alias] = remaining
            else:
                self._active_requests.pop(alias, None)
            if (
                sum(self._active_requests.values()) == 0
                and self._coordinator.state is RuntimeCoordinatorState.DRAINING
                and self._coordinator.last_error_code == "runtime_busy"
            ):
                served = self._coordinator.served
                handle = self._processes.get(served.alias) if served is not None else None
                if (
                    served is not None
                    and handle is not None
                    and handle.process.poll() is None
                    and handle.status.state is RuntimeState.RUNNING
                ):
                    self._coordinator_update_locked(
                        state=RuntimeCoordinatorState.READY,
                        requested=LocalRuntimeSelection(
                            alias=served.alias,
                            device=served.device,
                            gpu_layers=served.gpu_layers,
                            context_size=served.context_size,
                        ),
                        last_error_code=None,
                    )
                else:
                    failure = (
                        self._reap_unexpected_runtime_locked(alias, handle)
                        if handle is not None and handle.process.poll() is not None
                        else self._failures.get(alias, "runtime_exited")
                    )
                    self._coordinator_update_locked(
                        state=(
                            RuntimeCoordinatorState.QUARANTINED
                            if failure == "runtime_stop_failed"
                            else RuntimeCoordinatorState.FAILED
                        ),
                        served=None,
                        capabilities=RuntimeCapabilities(
                            state=RuntimeCapabilityState.FAILED,
                            error_code=failure,
                        ),
                        context=RuntimeContextStatus(),
                        last_error_code=failure,
                    )

    def _complete_chat(
        self,
        alias: str,
        handle: LlamaServerProcess,
        payload: dict[str, object],
    ) -> tuple[int, bytes, str]:
        payload["stream"] = False
        request = urllib.request.Request(
            f"{handle.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._reserve_runtime_request(alias, handle)
        try:
            try:
                response = _runtime_opener().open(request, timeout=CHAT_TIMEOUT_SECONDS)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, response.read(), response.headers.get("Content-Type", "application/json")
        except (urllib.error.URLError, OSError):
            raise LocalModelError("runtime_unreachable") from None
        finally:
            self._release_runtime_request(alias)

    def chat(self, alias: str, body: bytes) -> tuple[int, bytes, str]:
        """Forward one OpenAI-compatible chat completion to the model's runtime (never streamed)."""

        # Every real LocalModelService has the exact preflight method. The
        # callable guard retains the synthetic, socket-only transport seam.
        handle, payload = self._prepare_chat(alias, body)
        preflight = getattr(self, "_context_preflight", None)
        if callable(preflight):
            consume = getattr(self, "_consume_context_compaction", None)
            compacted_messages = consume(handle, payload) if callable(consume) else 0
            preflight(
                alias,
                handle,
                payload,
                compacted_messages=compacted_messages,
                enforce=True,
            )
        return self._complete_chat(alias, handle, payload)

    def open_chat(self, alias: str, body: bytes) -> ChatUpstream:
        """Forward a chat completion; when the caller asked for ``stream`` the reply is relayed chunk by chunk.

        The upstream status and headers are read synchronously so failures (for example a context overflow,
        which llama.cpp reports as HTTP 400) come back as ordinary JSON errors rather than a broken stream.
        """

        handle, payload = self._prepare_chat(alias, body)
        preflight = getattr(self, "_context_preflight", None)
        if callable(preflight):
            consume = getattr(self, "_consume_context_compaction", None)
            compacted_messages = consume(handle, payload) if callable(consume) else 0
            preflight(
                alias,
                handle,
                payload,
                compacted_messages=compacted_messages,
                enforce=True,
            )
        wants_stream = payload.get("stream") is True
        if not wants_stream:
            status_code, reply, content_type = self._complete_chat(alias, handle, payload)
            return ChatUpstream(status_code=status_code, content_type=content_type, body=reply)
        request = urllib.request.Request(
            f"{handle.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        self._reserve_runtime_request(alias, handle)
        released = False
        release_lock = threading.Lock()

        def release_once() -> None:
            nonlocal released
            with release_lock:
                if released:
                    return
                released = True
            self._release_runtime_request(alias)

        try:
            try:
                response = _runtime_opener().open(request, timeout=CHAT_TIMEOUT_SECONDS)
            except urllib.error.HTTPError as error:
                with error:
                    release_once()
                    return ChatUpstream(
                        status_code=error.code,
                        content_type=error.headers.get("Content-Type", "application/json") if error.headers else "application/json",
                        body=error.read(),
                    )
            content_type = response.headers.get("Content-Type", "text/event-stream")
            if "text/event-stream" not in content_type:
                with response:
                    body = response.read()
                release_once()
                return ChatUpstream(status_code=response.status, content_type=content_type, body=body)
        except (urllib.error.URLError, OSError):
            release_once()
            raise LocalModelError("runtime_unreachable") from None

        def relay() -> Iterator[bytes]:
            try:
                yield from _relay_event_stream(response)
            finally:
                release_once()

        def cancel() -> None:
            try:
                cancel_read = getattr(response, "cancel_read", None)
                if callable(cancel_read):
                    cancel_read()
                else:
                    response.close()
            except (OSError, ValueError):
                pass
            finally:
                release_once()

        return ChatUpstream(
            status_code=response.status,
            content_type="text/event-stream",
            lines=relay(),
            cancel=cancel,
            read_usage_tail=lambda: _read_usage_tail(response),
        )

    # ----- downloads -----

    @property
    def _download_ledger_path(self) -> Path:
        return self._registry.root / DOWNLOAD_LEDGER_FILE_NAME

    @staticmethod
    def _download_id(request: DownloadRequest, artifact: VerifiedArtifact) -> str:
        # The identity includes the immutable revision and digest, so two
        # revisions or digests of the same repository/file/alias never collide.
        return hashlib.sha256(
            "\0".join(
                (
                    artifact.repo_id,
                    artifact.filename,
                    request.alias,
                    artifact.revision,
                    artifact.sha256,
                    artifact.license_id,
                    LICENSE_POLICY_VERSION,
                )
            ).encode("utf-8")
        ).hexdigest()

    def _target_directory(self, artifact: VerifiedArtifact) -> Path:
        return self._registry.weights_dir / _artifact_storage_directory(artifact)

    def _download_paths(self, artifact: VerifiedArtifact) -> tuple[Path, Path]:
        target = self._target_directory(artifact)
        return target / f"{artifact.filename}.partial", target / artifact.filename

    def _job_is_coherent(self, job: _PersistedDownloadJob) -> bool:
        status = job.status
        artifact = job.artifact
        request = job.request
        return (
            status.download_id == self._download_id(request, artifact)
            and status.repo_id == artifact.repo_id == request.repo_id
            and status.filename == artifact.filename == request.filename
            and status.alias == request.alias
            and status.bytes_total == artifact.size_bytes == request.confirmed_size_bytes
            and status.revision == artifact.revision == request.confirmed_revision
            and status.sha256 == artifact.sha256 == request.confirmed_sha256
            and artifact.license_id == request.confirmed_license.strip().lower()
        )

    def _persist_download_ledger_locked(self) -> None:
        if self._download_ledger_error is not None:
            raise LocalModelError(self._download_ledger_error)
        try:
            self._registry.root.mkdir(parents=True, exist_ok=True)
            ledger = _DownloadLedger(
                jobs=tuple(sorted(self._download_jobs.values(), key=lambda item: item.status.started_at))
            )
            temporary = self._download_ledger_path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self._download_ledger_path)
        except OSError:
            raise LocalModelError("download_ledger_unavailable") from None

    def _safe_partial_size(self, job: _PersistedDownloadJob) -> int:
        partial, _final = self._download_paths(job.artifact)
        try:
            if partial.is_symlink() or not partial.is_file():
                return 0
            resolved = Path(os.path.realpath(partial))
            root = Path(os.path.realpath(self._registry.weights_dir))
            if not resolved.is_relative_to(root) or resolved.name != f"{job.artifact.filename}.partial":
                return 0
            size = resolved.stat().st_size
            return size if 0 < size <= job.artifact.size_bytes else 0
        except OSError:
            return 0

    def _cleanup_download_files(self, job: _PersistedDownloadJob) -> bool:
        """Remove exactly one app-owned immutable-artifact directory.

        The directory name is derived from the server-verified repository and
        commit.  Containment is checked before deletion and a symlink is never
        followed.  Completed jobs never enter this method.
        """

        target = self._target_directory(job.artifact)
        try:
            root = Path(os.path.realpath(self._registry.weights_dir))
            parent = Path(os.path.realpath(target.parent))
            if parent != root or target.name != _artifact_storage_directory(job.artifact):
                return False
            if target.is_symlink():
                target.unlink(missing_ok=True)
            elif target.exists():
                shutil.rmtree(target)
            return not target.exists() and not target.is_symlink()
        except OSError:
            return False

    def _published_download_recovery_state(
        self,
        job: _PersistedDownloadJob,
    ) -> Literal["absent", "complete", "conflict"]:
        """Classify the registry/final-file boundary left by a crashed worker.

        The worker publishes the verified registry record immediately before it
        settles the download ledger.  A restart may therefore observe the first
        durable write without the second.  Only the exact record this worker
        would have written, backed by the exact reviewed bytes, can close that
        window as completed.  An occupied alias that does not match is owner
        data and is deliberately neither overwritten nor deleted here.
        """

        record = self._registry.get(job.request.alias)
        if record is None:
            return "absent"
        _partial, final = self._download_paths(job.artifact)
        try:
            verified_path = self._verify_downloaded_artifact(final, job.artifact)
            metadata = read_gguf_metadata(verified_path)
            expected = LocalModelRecord(
                alias=job.request.alias,
                display_name=(
                    job.request.display_name
                    or Path(job.artifact.filename).stem[:120]
                ),
                path=str(verified_path),
                source_repo=job.artifact.repo_id,
                source_file=job.artifact.filename,
                size_bytes=job.artifact.size_bytes,
                sha256=job.artifact.sha256,
                source_revision=job.artifact.revision,
                source_license=job.artifact.license_id,
                source_license_policy=LICENSE_POLICY_VERSION,
                provenance_verified=True,
                default_device=job.request.default_device,
                layer_count=metadata.layer_count,
                architecture=metadata.architecture,
                tokenizer_model=metadata.tokenizer_model,
                training_context_size=metadata.training_context_size,
                metadata_reader_version=LOCAL_MODEL_METADATA_READER_VERSION,
                added_at=record.added_at,
            )
        except Exception:  # noqa: BLE001 - startup exposes only a closed state
            return "conflict"
        if record.added_at < job.status.started_at or record != expected:
            return "conflict"
        return "complete"

    def _load_download_ledger(self) -> None:
        self._download_ledger_error: str | None = None
        path = self._download_ledger_path
        if not path.is_file():
            return
        try:
            ledger = _DownloadLedger.model_validate_json(path.read_text(encoding="utf-8"))
            if len({item.status.download_id for item in ledger.jobs}) != len(ledger.jobs):
                raise ValueError("duplicate download ids")
            if any(not self._job_is_coherent(item) for item in ledger.jobs):
                raise ValueError("incoherent download ledger")
        except (OSError, ValueError):
            # Preserve the unreadable file for local recovery and fail closed;
            # never overwrite it or leak validation input through an exception.
            self._download_ledger_error = "download_ledger_invalid"
            return

        changed = False
        with self._lock:
            for saved in ledger.jobs:
                job = saved
                status = saved.status
                if status.state == "cancelling":
                    cleaned = self._cleanup_download_files(saved)
                    status = status.model_copy(update={
                        "state": "cancelled" if cleaned else "failed",
                        "error_code": None if cleaned else "download_cleanup_failed",
                        "bytes_done": 0,
                        "partial_retained": False,
                        "cleanup_confirmed": cleaned,
                        "finished_at": self._clock(),
                        "updated_at": self._clock(),
                        "status_revision": status.status_revision + 1,
                    })
                    changed = True
                elif status.state in {"queued", "downloading", "pausing"}:
                    published = self._published_download_recovery_state(saved)
                    if published == "complete":
                        status = status.model_copy(update={
                            "state": "completed",
                            "error_code": None,
                            "bytes_done": saved.artifact.size_bytes,
                            "partial_retained": False,
                            "cleanup_confirmed": None,
                            "finished_at": self._clock(),
                            "updated_at": self._clock(),
                            "status_revision": status.status_revision + 1,
                        })
                    elif published == "conflict":
                        status = status.model_copy(update={
                            "state": "failed",
                            "error_code": "download_registry_conflict",
                            "bytes_done": 0,
                            "partial_retained": False,
                            "cleanup_confirmed": None,
                            "finished_at": self._clock(),
                            "updated_at": self._clock(),
                            "status_revision": status.status_revision + 1,
                        })
                    else:
                        partial_size = self._safe_partial_size(saved)
                        status = status.model_copy(update={
                            "state": "interrupted",
                            "error_code": "download_interrupted",
                            "bytes_done": partial_size,
                            "partial_retained": partial_size > 0,
                            "cleanup_confirmed": None,
                            "updated_at": self._clock(),
                            "status_revision": status.status_revision + 1,
                        })
                    changed = True
                elif status.state in {"paused", "interrupted", "failed"}:
                    partial_size = self._safe_partial_size(saved)
                    if partial_size != status.bytes_done or (partial_size > 0) != status.partial_retained:
                        status = status.model_copy(update={
                            "bytes_done": partial_size,
                            "partial_retained": partial_size > 0,
                            "updated_at": self._clock(),
                            "status_revision": status.status_revision + 1,
                        })
                        changed = True
                if status is not saved.status:
                    job = saved.model_copy(update={"status": status})
                self._download_jobs[status.download_id] = job
                self._downloads[status.download_id] = status
            if changed:
                self._persist_download_ledger_locked()

    def _replace_download_status(self, download_id: str, **changes: object) -> DownloadStatus:
        with self._lock:
            job = self._download_jobs.get(download_id)
            if job is None:
                raise LocalModelError("download_not_found")
            current = job.status
            update = {
                "updated_at": self._clock(),
                "status_revision": current.status_revision + 1,
                **changes,
            }
            status = current.model_copy(update=update)
            replacement = job.model_copy(update={"status": status})
            self._download_jobs[download_id] = replacement
            self._downloads[download_id] = status
            self._persist_download_ledger_locked()
            return status

    def _admit_download_disk(self, job: _PersistedDownloadJob) -> tuple[int | None, int]:
        remaining = max(0, job.artifact.size_bytes - self._safe_partial_size(job))
        required = remaining + DOWNLOAD_DISK_RESERVE_BYTES
        return self._storage_free_bytes(), required

    def _start_download_worker(self, download_id: str) -> DownloadStatus:
        with self._lock:
            if self._shutting_down:
                raise LocalModelError("runtime_shutdown_in_progress")
            job = self._download_jobs.get(download_id)
            if job is None:
                raise LocalModelError("download_not_found")
            if download_id in self._download_workers:
                return job.status
            control = _DownloadControl()
            status = self._replace_download_status(
                download_id,
                state="queued",
                error_code=None,
                finished_at=None,
                cleanup_confirmed=None,
                attempt=job.status.attempt + 1,
                transfer_adapter_version=(
                    HUGGINGFACE_TRANSFER_ADAPTER_VERSION
                    if self._download_transfer is None and self._downloader is None
                    else "injected-synthetic-transfer.v1"
                ),
            )
            worker = threading.Thread(
                target=self._run_download,
                args=(download_id, control),
                name=f"local-model-download-{job.request.alias}",
                daemon=True,
            )
            self._download_controls[download_id] = control
            self._download_workers[download_id] = worker
            worker.start()
            return status

    def _hub_model_info(self) -> Callable[..., object]:
        if self._model_info is not None:
            return self._model_info
        try:
            from huggingface_hub import HfApi
        except Exception:
            raise LocalModelError("huggingface_hub_unavailable") from None
        # Public-only until a separately reviewed, explicit token workflow
        # exists. Merely opening the Models page never reads a cached login.
        return HfApi(token=False).model_info

    def remote_files(self, repo_id: str) -> RemoteRepoFiles:
        """Browse a repository's GGUF files bound to one immutable commit."""

        return resolve_repo_identity(repo_id, model_info=self._hub_model_info())

    def _verified_artifact(self, request: DownloadRequest) -> VerifiedArtifact:
        """Re-resolve the repository server-side and accept only an exact match.

        The confirmation the person gave is compared field by field with what the
        Hub says now. Nothing the caller sent is carried into the download or the
        registry: the values used are the server's own.
        """

        identity = resolve_repo_identity(request.repo_id, model_info=self._hub_model_info())
        if not identity.revision_pinned or identity.revision is None:
            raise LocalModelError("provenance_unavailable")
        remote = next((item for item in identity.files if item.filename == request.filename), None)
        if remote is None or not remote.eligible or remote.sha256 is None or remote.size_bytes is None:
            raise LocalModelError("file_not_eligible")
        if identity.license_admission is not LicenseAdmission.ALLOWED or identity.license_id is None:
            raise LocalModelError("file_not_eligible")
        confirmed = (
            request.confirmed_revision.lower(),
            request.confirmed_sha256.lower(),
            request.confirmed_license.strip().lower(),
            request.confirmed_size_bytes,
        )
        resolved = (identity.revision, remote.sha256, identity.license_id, remote.size_bytes)
        if confirmed != resolved:
            raise LocalModelError("provenance_mismatch")
        return VerifiedArtifact(
            repo_id=identity.repo_id,
            filename=remote.filename,
            revision=identity.revision,
            sha256=remote.sha256,
            size_bytes=remote.size_bytes,
            license_id=identity.license_id,
        )

    def start_download(self, request: DownloadRequest) -> DownloadStatus:
        if self._download_ledger_error is not None:
            raise LocalModelError(self._download_ledger_error)
        if self._registry.get(request.alias) is not None:
            raise LocalModelError("alias_exists")
        artifact = self._verified_artifact(request)
        download_id = self._download_id(request, artifact)
        with self._lock:
            existing = self._downloads.get(download_id)
            if existing is not None:
                return existing
            if self._registry.get(request.alias) is not None or any(
                item.alias == request.alias and item.state not in {"completed", "cancelled"}
                for item in self._downloads.values()
            ):
                raise LocalModelError("alias_exists")
            status = DownloadStatus(
                download_id=download_id, repo_id=artifact.repo_id, filename=artifact.filename, alias=request.alias,
                state="queued", bytes_total=artifact.size_bytes, bytes_done=0,
                started_at=self._clock(), updated_at=self._clock(),
                revision=artifact.revision, sha256=artifact.sha256,
            )
            job = _PersistedDownloadJob(request=request, artifact=artifact, status=status)
            self._download_jobs[download_id] = job
            self._downloads[download_id] = status
            self._persist_download_ledger_locked()
        free, required = self._admit_download_disk(job)
        if free is None or free < required:
            return self._replace_download_status(
                download_id,
                state="failed",
                error_code="disk_space_unavailable" if free is None else "insufficient_disk_space",
                disk_required_bytes=required,
                disk_free_bytes_at_start=free,
                cleanup_confirmed=True,
                finished_at=self._clock(),
            )
        self._replace_download_status(
            download_id,
            disk_required_bytes=required,
            disk_free_bytes_at_start=free,
        )
        return self._start_download_worker(download_id)

    def _checked_download_job(self, download_id: str, expected_revision: int) -> _PersistedDownloadJob:
        with self._lock:
            job = self._download_jobs.get(download_id)
            if job is None:
                raise LocalModelError("download_not_found")
            if job.status.status_revision != expected_revision:
                raise LocalModelError("download_revision_conflict")
            return job

    def pause_download(self, download_id: str, *, expected_revision: int) -> DownloadStatus:
        job = self._checked_download_job(download_id, expected_revision)
        if job.status.state in {"paused", "pausing"}:
            return job.status
        if job.status.state not in {"queued", "downloading"}:
            raise LocalModelError("download_action_invalid")
        status = self._replace_download_status(download_id, state="pausing", error_code=None)
        with self._lock:
            control = self._download_controls.get(download_id)
            if control is None:
                return self._replace_download_status(
                    download_id,
                    state="interrupted",
                    error_code="download_interrupted",
                )
            control.pause.set()
        return status

    def _resume_or_retry(
        self,
        download_id: str,
        *,
        expected_revision: int,
        allowed_states: set[str],
    ) -> DownloadStatus:
        job = self._checked_download_job(download_id, expected_revision)
        if job.status.state not in allowed_states:
            raise LocalModelError("download_action_invalid")
        if self._registry.get(job.request.alias) is not None:
            raise LocalModelError("alias_exists")
        verified = self._verified_artifact(job.request)
        if verified != job.artifact:
            raise LocalModelError("provenance_mismatch")
        free, required = self._admit_download_disk(job)
        if free is None or free < required:
            return self._replace_download_status(
                download_id,
                state="failed",
                error_code="disk_space_unavailable" if free is None else "insufficient_disk_space",
                disk_required_bytes=required,
                disk_free_bytes_at_start=free,
                cleanup_confirmed=None,
                finished_at=self._clock(),
            )
        self._replace_download_status(
            download_id,
            disk_required_bytes=required,
            disk_free_bytes_at_start=free,
            partial_retained=self._safe_partial_size(job) > 0,
            finished_at=None,
        )
        return self._start_download_worker(download_id)

    def resume_download(self, download_id: str, *, expected_revision: int) -> DownloadStatus:
        return self._resume_or_retry(
            download_id,
            expected_revision=expected_revision,
            allowed_states={"paused", "interrupted"},
        )

    def retry_download(self, download_id: str, *, expected_revision: int) -> DownloadStatus:
        return self._resume_or_retry(
            download_id,
            expected_revision=expected_revision,
            allowed_states={"failed", "cancelled"},
        )

    def cancel_download(self, download_id: str, *, expected_revision: int) -> DownloadStatus:
        job = self._checked_download_job(download_id, expected_revision)
        if job.status.state == "cancelled":
            return job.status
        if job.status.state == "completed":
            raise LocalModelError("download_action_invalid")
        if job.status.state in {"queued", "downloading", "pausing", "cancelling"}:
            status = self._replace_download_status(download_id, state="cancelling", error_code=None)
            with self._lock:
                control = self._download_controls.get(download_id)
                if control is not None:
                    control.cancel.set()
                    return status
        cleaned = self._cleanup_download_files(job)
        return self._replace_download_status(
            download_id,
            state="cancelled" if cleaned else "failed",
            error_code=None if cleaned else "download_cleanup_failed",
            bytes_done=0,
            partial_retained=False,
            cleanup_confirmed=cleaned,
            finished_at=self._clock(),
        )

    def _publish_download_progress(self, download_id: str, amount: int) -> None:
        with self._lock:
            job = self._download_jobs.get(download_id)
            if job is None:
                raise _DownloadCancelled
            current = job.status
            # Transfer adapters report an absolute byte offset. Progress is
            # monotonic and deliberately does not advance the command revision:
            # otherwise a user could never reliably pause or cancel while chunks
            # are arriving between an overview read and the command request.
            bounded = max(
                current.bytes_done,
                min(max(0, int(amount)), job.artifact.size_bytes),
            )
            if bounded == current.bytes_done:
                return
            status = current.model_copy(update={
                "bytes_done": bounded,
                "partial_retained": bounded > 0,
                "updated_at": self._clock(),
            })
            self._download_jobs[download_id] = job.model_copy(update={"status": status})
            self._downloads[download_id] = status
            now = time.monotonic()
            if now - self._download_progress_persisted_at.get(download_id, 0.0) >= DOWNLOAD_LEDGER_PROGRESS_INTERVAL_SECONDS:
                self._persist_download_ledger_locked()
                self._download_progress_persisted_at[download_id] = now

    @staticmethod
    def _assert_hub_transfer_compatibility() -> tuple[object, object, object, object]:
        try:
            import huggingface_hub
            from huggingface_hub import get_hf_file_metadata, hf_hub_url
            from huggingface_hub.file_download import http_get
            from huggingface_hub.utils import build_hf_headers
        except Exception:
            raise LocalModelError("huggingface_hub_unavailable") from None
        if not str(getattr(huggingface_hub, "__version__", "")).startswith(
            HUGGINGFACE_TRANSFER_COMPATIBLE_PREFIX
        ):
            raise LocalModelError("download_adapter_incompatible")
        parameters = inspect.signature(http_get).parameters
        required = {"url", "temp_file", "resume_size", "headers", "expected_size", "_tqdm_bar"}
        if not required.issubset(parameters):
            raise LocalModelError("download_adapter_incompatible")
        return hf_hub_url, get_hf_file_metadata, http_get, build_hf_headers

    def _hub_download_transfer(
        self,
        *,
        artifact: VerifiedArtifact,
        partial_path: Path,
        resume_size: int,
        progress: Callable[[int], None],
        control: _DownloadControl,
    ) -> Path:
        """Pinned public-only transfer with cooperative pause and cancel.

        ``http_get`` is the sole internal Hub interface used.  Its package
        version and callable surface are checked above before any request; a
        dependency drift therefore fails closed instead of silently losing
        cancellation or progress behavior.
        """

        hf_hub_url, get_metadata, http_get, build_headers = self._assert_hub_transfer_compatibility()
        url = hf_hub_url(
            artifact.repo_id,
            artifact.filename,
            repo_type="model",
            revision=artifact.revision,
        )
        metadata = get_metadata(url, token=False)
        commit = str(getattr(metadata, "commit_hash", "")).lower()
        size = getattr(metadata, "size", None)
        location = getattr(metadata, "location", None)
        if commit != artifact.revision or size != artifact.size_bytes or not isinstance(location, str):
            raise LocalModelError("provenance_mismatch")
        control.checkpoint()
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        with partial_path.open("ab+") as raw:
            raw.seek(0, os.SEEK_END)
            actual_resume = raw.tell()
            if actual_resume != resume_size or actual_resume > artifact.size_bytes:
                raise LocalModelError("partial_invalid")
            tracked = _TrackedDownloadFile(raw, progress)
            http_get(
                location,
                tracked,
                resume_size=actual_resume,
                headers=build_headers(token=False),
                expected_size=artifact.size_bytes,
                displayed_filename=artifact.filename,
                _tqdm_bar=_DownloadProgressGate(control),
            )
        control.checkpoint()
        return partial_path

    def _verify_downloaded_artifact(self, path: Path, artifact: VerifiedArtifact) -> Path:
        """Check what actually landed on disk against the reviewed Hub identity.

        Containment, regular-file and GGUF expectations first, then the exact byte
        count, then the streamed digest compared in constant time. Every failure
        raises a closed code; the caller deletes the file and registers nothing.
        """

        if path.is_symlink() or not path.is_file():
            raise LocalModelError("artifact_rejected")
        resolved = Path(os.path.realpath(path))
        weights_root = Path(os.path.realpath(self._registry.weights_dir))
        if not resolved.is_relative_to(weights_root) or resolved.name != artifact.filename:
            raise LocalModelError("artifact_rejected")
        if resolved.is_symlink() or not resolved.is_file():
            raise LocalModelError("artifact_rejected")
        size = resolved.stat().st_size
        if size != artifact.size_bytes:
            raise LocalModelError("size_mismatch")
        with resolved.open("rb") as handle:
            if handle.read(len(_GGUF_MAGIC)) != _GGUF_MAGIC:
                raise LocalModelError("not_a_gguf_file")
        if not hmac.compare_digest(_digest_file(resolved), artifact.sha256):
            raise LocalModelError("hash_mismatch")
        return resolved

    @staticmethod
    def _download_failure_code(error: BaseException) -> str:
        """Map a downloader failure to a closed code by exception type only.

        Hub exception messages can carry repository text, so they are never read.
        """

        names = {cls.__name__ for cls in type(error).__mro__}
        if names & {"GatedRepoError", "RepositoryNotFoundError", "RevisionNotFoundError", "EntryNotFoundError"}:
            return "gated_or_unauthorized"
        return "download_failed"

    def _retain_legacy_partial(
        self,
        landed: Path | None,
        partial: Path,
        artifact: VerifiedArtifact,
    ) -> None:
        if landed is None or landed == partial:
            return
        try:
            if landed.is_symlink() or not landed.is_file():
                return
            resolved = Path(os.path.realpath(landed))
            target = Path(os.path.realpath(partial.parent))
            if resolved.parent != target or resolved.name != artifact.filename:
                return
            if not 0 < resolved.stat().st_size <= artifact.size_bytes:
                return
            partial.unlink(missing_ok=True)
            resolved.replace(partial)
        except OSError:
            return

    def _sample_legacy_download_progress(
        self,
        download_id: str,
        target: Path,
        filename: str,
        done: threading.Event,
    ) -> None:
        """Compatibility progress for injected/historical hf_hub_download seams."""

        incomplete = target / ".cache" / "huggingface" / "download"
        while not done.wait(DOWNLOAD_PROGRESS_INTERVAL_SECONDS):
            best = 0
            try:
                candidates = [target / filename]
                if incomplete.exists():
                    candidates.extend(incomplete.glob(f"{filename}*.incomplete"))
                for candidate in candidates:
                    try:
                        best = max(best, candidate.stat().st_size)
                    except OSError:
                        continue
            except OSError:
                best = 0
            if best:
                self._publish_download_progress(download_id, best)

    def _run_download(self, download_id: str, control: _DownloadControl) -> None:
        with self._lock:
            job = self._download_jobs.get(download_id)
        if job is None:
            return
        request, artifact = job.request, job.artifact
        partial, final = self._download_paths(artifact)
        landed: Path | None = None
        legacy_finished: threading.Event | None = None

        def publish_progress(amount: int) -> None:
            control.checkpoint()
            self._publish_download_progress(download_id, amount)

        try:
            self._replace_download_status(download_id, state="downloading", error_code=None)
            partial.parent.mkdir(parents=True, exist_ok=True)
            control.checkpoint()
            if final.is_file() and not final.is_symlink():
                # Recovery from a crash after the atomic publish but before the
                # registry/ledger commit; verification below remains mandatory.
                landed = final
            elif self._download_transfer is not None:
                landed = Path(self._download_transfer(
                    artifact=artifact,
                    partial_path=partial,
                    resume_size=self._safe_partial_size(job),
                    progress=publish_progress,
                    control=control,
                ))
            elif self._downloader is not None:
                legacy_finished = threading.Event()
                threading.Thread(
                    target=self._sample_legacy_download_progress,
                    args=(download_id, partial.parent, artifact.filename, legacy_finished),
                    name=f"local-model-download-progress-{request.alias}",
                    daemon=True,
                ).start()
                landed = Path(self._downloader(
                    repo_id=artifact.repo_id, filename=artifact.filename,
                    local_dir=partial.parent, revision=artifact.revision,
                ))
            else:
                landed = self._hub_download_transfer(
                    artifact=artifact,
                    partial_path=partial,
                    resume_size=self._safe_partial_size(job),
                    progress=publish_progress,
                    control=control,
                )
            control.checkpoint()
            if landed == partial:
                if self._safe_partial_size(job) != artifact.size_bytes:
                    raise LocalModelError("size_mismatch")
                final.unlink(missing_ok=True)
                partial.replace(final)
                landed = final
            verified_path = self._verify_downloaded_artifact(landed, artifact)
            metadata = read_gguf_metadata(verified_path)
            record = LocalModelRecord(
                alias=request.alias,
                display_name=request.display_name or Path(artifact.filename).stem[:120],
                path=str(verified_path),
                source_repo=artifact.repo_id,
                source_file=artifact.filename,
                size_bytes=artifact.size_bytes,
                sha256=artifact.sha256,
                source_revision=artifact.revision,
                source_license=artifact.license_id,
                source_license_policy=LICENSE_POLICY_VERSION,
                provenance_verified=True,
                default_device=request.default_device,
                layer_count=metadata.layer_count,
                architecture=metadata.architecture,
                tokenizer_model=metadata.tokenizer_model,
                training_context_size=metadata.training_context_size,
                metadata_reader_version=LOCAL_MODEL_METADATA_READER_VERSION,
                added_at=self._clock(),
            )
            self._registry.upsert(record)
            self._replace_download_status(
                download_id, state="completed", bytes_done=artifact.size_bytes,
                bytes_total=artifact.size_bytes, partial_retained=False,
                cleanup_confirmed=None, error_code=None, finished_at=self._clock(),
            )
        except _DownloadPaused:
            self._retain_legacy_partial(landed, partial, artifact)
            with self._lock:
                current = self._download_jobs.get(download_id)
            partial_size = self._safe_partial_size(current) if current is not None else 0
            self._replace_download_status(
                download_id,
                state="paused",
                error_code=None,
                bytes_done=partial_size,
                partial_retained=partial_size > 0,
                cleanup_confirmed=None,
                finished_at=None,
            )
        except _DownloadCancelled:
            with self._lock:
                current = self._download_jobs.get(download_id)
            cleaned = current is not None and self._cleanup_download_files(current)
            self._replace_download_status(
                download_id,
                state="cancelled" if cleaned else "failed",
                error_code=None if cleaned else "download_cleanup_failed",
                bytes_done=0,
                partial_retained=False,
                cleanup_confirmed=cleaned,
                finished_at=self._clock(),
            )
        except Exception as error:  # noqa: BLE001 - reported as a closed code, never as text
            code = error.code if isinstance(error, LocalModelError) else self._download_failure_code(error)
            with self._lock:
                current = self._download_jobs.get(download_id)
            retain_partial = code == "download_failed" and current is not None
            if retain_partial:
                self._retain_legacy_partial(landed, partial, artifact)
            partial_size = self._safe_partial_size(current) if retain_partial and current is not None else 0
            retained = partial_size > 0
            cleaned: bool | None = None
            if not retained and current is not None:
                cleaned = self._cleanup_download_files(current)
            self._replace_download_status(
                download_id,
                state="failed",
                error_code=code,
                bytes_done=partial_size,
                partial_retained=retained,
                cleanup_confirmed=None if retained else cleaned,
                finished_at=self._clock(),
            )
        finally:
            if legacy_finished is not None:
                legacy_finished.set()
            with self._lock:
                if self._download_controls.get(download_id) is control:
                    self._download_controls.pop(download_id, None)
                if self._download_workers.get(download_id) is threading.current_thread():
                    self._download_workers.pop(download_id, None)
                self._download_progress_persisted_at.pop(download_id, None)

    def _discard_unverified(self, path: Path | None) -> None:
        """Delete a file that failed verification so nothing can later register it."""

        if path is None:
            return
        try:
            if path.is_symlink():
                path.unlink(missing_ok=True)
                return
            resolved = Path(os.path.realpath(path))
            if resolved.is_relative_to(Path(os.path.realpath(self._registry.weights_dir))):
                resolved.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = (
    "ADMITTED_LICENSE_IDS",
    "ALIAS_PATTERN",
    "ActivateLocalModel",
    "ChatUpstream",
    "ChatInputTokenCount",
    "MAX_CHAT_STREAM_BYTES",
    "RESERVED_ALIASES",
    "AddLocalModel",
    "DeviceMode",
    "DOWNLOAD_DISK_RESERVE_BYTES",
    "DOWNLOAD_LEDGER_CONTRACT_VERSION",
    "DownloadCommandRequest",
    "DownloadRequest",
    "DownloadStatus",
    "HardwareSummary",
    "LICENSE_POLICY_VERSION",
    "LLAMA_SERVER_ENV",
    "RUNTIME_DIR_NAME",
    "LOCAL_MODELS_CONTRACT_VERSION",
    "LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION",
    "LOCAL_MODEL_PLACEMENT_CONTRACT_VERSION",
    "LOCAL_MODEL_METADATA_READER_VERSION",
    "LOCAL_MODEL_RUNTIME_ADAPTER_ID",
    "LOCAL_MODEL_RUNTIME_ADAPTER_VERSION",
    "LOCAL_RUNTIME_CAPABILITY_PROBE_VERSION",
    "LOCAL_RUNTIME_COORDINATOR_CONTRACT_VERSION",
    "LicenseAdmission",
    "LocalModelError",
    "LocalModelCompatibility",
    "LocalModelCompatibilityCatalog",
    "LocalModelCompatibilityReason",
    "LocalModelCompatibilityState",
    "LocalModelPlacementAdmission",
    "LocalModelPlacementOption",
    "LocalModelRuntimeAdapter",
    "LocalModelRecord",
    "LocalModelRegistry",
    "LocalModelService",
    "LocalModelStatus",
    "LocalModelsOverview",
    "LocalRuntimeCoordinatorStatus",
    "ModelFormat",
    "PlacementAdmissionReason",
    "PlacementAdmissionState",
    "REFUSED_LICENSE_IDS",
    "RemoteFile",
    "RemoteRepoFiles",
    "ScanFolderRequest",
    "ScanFolderResult",
    "RuntimeState",
    "RuntimeStatus",
    "RuntimeCapabilities",
    "RuntimeCapabilityState",
    "RuntimeCleanupReceipt",
    "RuntimeCleanupState",
    "RuntimeContextStatus",
    "ContextAdmissionReason",
    "GgufMetadata",
    "RuntimeCoordinatorState",
    "LocalRuntimeSelection",
    "LocalRuntimeServedSelection",
    "StopLocalRuntime",
    "SwitchLocalRuntime",
    "VerifiedArtifact",
    "runtime_exit_failure_code",
    "admit_license",
    "build_placement_admission",
    "detect_llama_server",
    "estimate_gpu_layers",
    "probe_hardware",
    "read_gguf_layer_count",
    "read_gguf_metadata",
    "resolve_repo_identity",
)
