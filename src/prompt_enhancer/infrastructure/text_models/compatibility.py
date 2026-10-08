"""Sensitive-local hardware buckets and exploratory model resource fit.

This module never reads model-cache contents, provider/session data, machine
identifiers, or credentials. It performs no download, inference, selection, or
activation. Exact hardware observations are converted to coarse buckets before
they cross the discovery function boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from threading import Condition, Lock, Thread
from time import monotonic
from types import MappingProxyType

from ...application.owned_process import (
    OwnedProcess,
    process_tree_exited,
    start_owned_process,
    terminate_owned_process,
)
from ...application.resources import ResourceAvailability, ResourceKind
from ..resources import default_packaged_resource_resolver
from .loader import model_eval_cache_root, repository_root
from .manifests import (
    BGE_M3_LEGACY_BLOCKED,
    BLOCKED_TEXT_MODEL_MANIFESTS,
    TEXT_MODEL_MANIFESTS,
    ModelManifest,
)


MODEL_COMPATIBILITY_CATALOG_VERSION = "reviewed-model-resource-fit-v3"
HARDWARE_INVENTORY_VERSION = "bucketed-sensitive-hardware-inventory-v3"
RESOURCE_MEASUREMENT_VERSION = "reviewed-runtime-configurations-2026-08-v3"

# Reviewed class floors tolerate bounded firmware/driver reservations on the
# locked nominal 16 GiB RAM / 8 GiB CUDA target. They are not exact capacity
# claims and remain conservative at 15/16 of each nominal class.
MIN_SYSTEM_RAM_MIB = 15 * 1024
MIN_CUDA_VRAM_MIB = 15 * 512
MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB = 6_144
MODEL_CHILD_RSS_CEILING_MIB = 8_192
MAX_LOGICAL_CORE_COUNT = 4_096
MAX_RESOURCE_MIB = 1_048_576
MAX_DISK_MIB = 16_777_216
ACCELERATOR_PROBE_SCHEMA_VERSION = 1
ACCELERATOR_PROBE_TIMEOUT_SECONDS = 10
MAX_ACCELERATOR_PROBE_OUTPUT_BYTES = 2_048
ACCELERATOR_PROBE_TERMINATION_GRACE_SECONDS = 2.0
RUNTIME_INVENTORY_CACHE_TTL_SECONDS = 30.0


class CudaInventoryState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class HardwareDiscoveryReason(StrEnum):
    CPU_ARCHITECTURE_UNKNOWN = "cpu_architecture_unknown"
    LOGICAL_CORE_BUCKET_UNKNOWN = "logical_core_bucket_unknown"
    SYSTEM_RAM_BUCKET_UNKNOWN = "system_ram_bucket_unknown"
    CUDA_INVENTORY_UNKNOWN = "cuda_inventory_unknown"
    MODEL_CACHE_FREE_DISK_BUCKET_UNKNOWN = "model_cache_free_disk_bucket_unknown"


class ModelCompatibilityStatus(StrEnum):
    RESEARCH_ONLY = "research_only"
    UNAVAILABLE = "unavailable"


class ModelCompatibilityReason(StrEnum):
    EXPLORATORY_RESOURCE_FIT = "exploratory_resource_fit"
    RESOURCE_MEASUREMENT_MISSING = "resource_measurement_missing"
    HARDWARE_INVENTORY_UNKNOWN = "hardware_inventory_unknown"
    INSUFFICIENT_SYSTEM_RAM = "insufficient_system_ram"
    CUDA_UNAVAILABLE = "cuda_unavailable"
    CUDA_INVENTORY_UNKNOWN = "cuda_inventory_unknown"
    INSUFFICIENT_CUDA_VRAM = "insufficient_cuda_vram"
    CHILD_GPU_ALLOCATION_CEILING_EXCEEDED = (
        "child_gpu_allocation_ceiling_exceeded"
    )
    CHILD_RSS_CEILING_EXCEEDED = "child_rss_ceiling_exceeded"
    UNSAFE_PICKLE_ONLY = "unsafe_pickle_only"


class ResourceMeasurementState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"


class ModelCompatibilityCatalogUnavailableError(RuntimeError):
    """Fixed, content-free failure for an incoherent frozen registry."""

    def __init__(self) -> None:
        super().__init__("model_compatibility_catalog_unavailable")


_CPU_ARCHITECTURES = MappingProxyType(
    {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "i386": "x86",
        "i686": "x86",
        "x86": "x86",
        "armv7l": "arm32",
        "armv8l": "arm32",
    }
)
_CPU_ARCHITECTURE_BUCKETS = frozenset(_CPU_ARCHITECTURES.values())
_LOGICAL_CORE_BUCKETS = frozenset(
    {"1_to_4", "5_to_8", "9_to_16", "17_to_32", "33_to_64", "65_plus"}
)
_SYSTEM_RAM_BUCKET_FLOORS_MIB = MappingProxyType(
    {
        "below_16_gib_class": 0,
        "16_gib_class": MIN_SYSTEM_RAM_MIB,
        "32_gib_class": MIN_SYSTEM_RAM_MIB * 2,
        "64_gib_plus_class": MIN_SYSTEM_RAM_MIB * 4,
    }
)
_SYSTEM_RAM_BUCKETS = frozenset(_SYSTEM_RAM_BUCKET_FLOORS_MIB)
_CUDA_VRAM_BUCKET_FLOORS_MIB = MappingProxyType(
    {
        "below_8_gib_class": 0,
        "8_gib_class": MIN_CUDA_VRAM_MIB,
        "12_gib_class": MIN_CUDA_VRAM_MIB * 3 // 2,
        "16_gib_class": MIN_CUDA_VRAM_MIB * 2,
        "24_gib_plus_class": MIN_CUDA_VRAM_MIB * 3,
    }
)
_CUDA_VRAM_BUCKETS = frozenset(_CUDA_VRAM_BUCKET_FLOORS_MIB)
_CUDA_CAPABILITY_BUCKETS = frozenset({"pre_7", "7_x", "8_x", "9_plus"})
_DISK_BUCKETS = frozenset(
    {
        "under_10240_mib",
        "10240_to_51199_mib",
        "51200_to_102399_mib",
        "102400_plus_mib",
    }
)


@dataclass(frozen=True, slots=True)
class _AcceleratorProbe:
    cuda_state: CudaInventoryState
    cuda_total_memory_mib: int | None
    cuda_capability_major: int | None
    cuda_capability_minor: int | None
    mps_available: bool


def _unknown_accelerator_probe() -> _AcceleratorProbe:
    return _AcceleratorProbe(
        cuda_state=CudaInventoryState.UNKNOWN,
        cuda_total_memory_mib=None,
        cuda_capability_major=None,
        cuda_capability_minor=None,
        mps_available=False,
    )


@dataclass(frozen=True, slots=True)
class ModelRuntimeInventory:
    """Fail-closed bucketed hardware facts kept in memory on this device."""

    preferred_device: str
    cuda_state: CudaInventoryState
    cuda_available: bool | None
    mps_available: bool
    cpu_available: bool
    cpu_architecture_bucket: str | None
    logical_core_bucket: str | None
    system_ram_bucket: str | None
    cuda_vram_bucket: str | None
    cuda_capability_bucket: str | None
    model_cache_free_disk_bucket: str | None
    discovery_reason_codes: tuple[HardwareDiscoveryReason, ...]
    inventory_version: str = HARDWARE_INVENTORY_VERSION
    one_model_at_a_time: bool = True
    subprocess_isolation: bool = True
    raw_session_data_accepted: bool = False
    model_child_gpu_allocation_ceiling_mib: int = (
        MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB
    )
    model_child_rss_ceiling_mib: int = MODEL_CHILD_RSS_CEILING_MIB
    model_downloads_started: bool = False
    model_activation_allowed: bool = False
    sensitivity: str = "sensitive_derived"
    local_only: bool = True
    persisted: bool = False
    synced: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cuda_state, CudaInventoryState):
            raise ValueError("CUDA state must use the closed enum")
        if any(
            not isinstance(reason, HardwareDiscoveryReason)
            for reason in self.discovery_reason_codes
        ):
            raise ValueError("hardware reasons must use the closed enum")
        if not isinstance(self.mps_available, bool):
            raise ValueError("MPS availability must be boolean")
        if self.preferred_device not in {"cpu", "cuda", "mps"}:
            raise ValueError("preferred device is outside the closed vocabulary")
        if self.cpu_available is not True:
            raise ValueError("the running local process must retain CPU availability")
        if self.cpu_architecture_bucket not in _CPU_ARCHITECTURE_BUCKETS | {None}:
            raise ValueError("CPU architecture must be bucketed")
        if self.logical_core_bucket not in _LOGICAL_CORE_BUCKETS | {None}:
            raise ValueError("logical core count must be bucketed")
        if self.system_ram_bucket not in _SYSTEM_RAM_BUCKETS | {None}:
            raise ValueError("system RAM must be bucketed")
        if self.cuda_vram_bucket not in _CUDA_VRAM_BUCKETS | {None}:
            raise ValueError("CUDA memory must be bucketed")
        if self.cuda_capability_bucket not in _CUDA_CAPABILITY_BUCKETS | {None}:
            raise ValueError("CUDA capability must be bucketed")
        if self.model_cache_free_disk_bucket not in _DISK_BUCKETS | {None}:
            raise ValueError("cache free space must be bucketed")

        if self.cuda_state is CudaInventoryState.AVAILABLE:
            if (
                self.cuda_available is not True
                or self.cuda_vram_bucket is None
                or self.cuda_capability_bucket is None
                or self.preferred_device != "cuda"
            ):
                raise ValueError("available CUDA inventory must be complete")
        elif self.cuda_state is CudaInventoryState.UNAVAILABLE:
            if (
                self.cuda_available is not False
                or self.cuda_vram_bucket is not None
                or self.cuda_capability_bucket is not None
                or self.preferred_device == "cuda"
            ):
                raise ValueError("unavailable CUDA inventory is inconsistent")
        elif (
            self.cuda_available is not None
            or self.cuda_vram_bucket is not None
            or self.cuda_capability_bucket is not None
            or self.preferred_device == "cuda"
        ):
            raise ValueError("unknown CUDA inventory cannot claim observations")
        if self.preferred_device == "mps" and not self.mps_available:
            raise ValueError("preferred MPS device must be available")

        expected_reasons: set[HardwareDiscoveryReason] = set()
        if self.cpu_architecture_bucket is None:
            expected_reasons.add(HardwareDiscoveryReason.CPU_ARCHITECTURE_UNKNOWN)
        if self.logical_core_bucket is None:
            expected_reasons.add(HardwareDiscoveryReason.LOGICAL_CORE_BUCKET_UNKNOWN)
        if self.system_ram_bucket is None:
            expected_reasons.add(HardwareDiscoveryReason.SYSTEM_RAM_BUCKET_UNKNOWN)
        if self.cuda_state is CudaInventoryState.UNKNOWN:
            expected_reasons.add(HardwareDiscoveryReason.CUDA_INVENTORY_UNKNOWN)
        if self.model_cache_free_disk_bucket is None:
            expected_reasons.add(
                HardwareDiscoveryReason.MODEL_CACHE_FREE_DISK_BUCKET_UNKNOWN
            )
        canonical_reasons = tuple(
            sorted(expected_reasons, key=lambda reason: reason.value)
        )
        if self.discovery_reason_codes != canonical_reasons:
            raise ValueError("hardware unknown reasons must exactly match missing facts")
        if (
            self.inventory_version != HARDWARE_INVENTORY_VERSION
            or self.one_model_at_a_time is not True
            or self.subprocess_isolation is not True
            or self.raw_session_data_accepted is not False
            or self.model_child_gpu_allocation_ceiling_mib
            != MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB
            or self.model_child_rss_ceiling_mib != MODEL_CHILD_RSS_CEILING_MIB
            or self.model_downloads_started is not False
            or self.model_activation_allowed is not False
            or self.sensitivity != "sensitive_derived"
            or self.local_only is not True
            or self.persisted is not False
            or self.synced is not False
        ):
            raise ValueError("hardware privacy and execution invariants are fixed")


@dataclass(frozen=True, slots=True)
class ReviewedRuntimeConfiguration:
    configuration_key: str
    model_key: str
    role: str
    language_scope: str
    quantization: str
    dtype: str
    runtime: str
    measurement_method: str
    measurement_precision: str
    measurement_source: str
    observed_peak_gpu_allocation_mib: float | None
    observed_peak_child_rss_mib: float | None
    benchmark_key: str | None
    synthetic_case_count: int | None

    @property
    def measurement_state(self) -> ResourceMeasurementState:
        present = sum(
            value is not None
            for value in (
                self.observed_peak_gpu_allocation_mib,
                self.observed_peak_child_rss_mib,
            )
        )
        if present == 2:
            return ResourceMeasurementState.COMPLETE
        if present == 1:
            return ResourceMeasurementState.PARTIAL
        return ResourceMeasurementState.MISSING


@dataclass(frozen=True, slots=True)
class ModelCompatibilityEntry:
    configuration_key: str
    model_key: str
    repository_id: str
    revision: str
    task: str
    role: str
    language_scope: str
    license_spdx: str
    status: ModelCompatibilityStatus
    reason_codes: tuple[ModelCompatibilityReason, ...]
    quantization: str
    dtype: str
    runtime: str
    measurement_method: str
    measurement_precision: str
    measurement_source: str
    resource_measurement_state: ResourceMeasurementState
    observed_peak_gpu_allocation_mib: float | None
    observed_peak_child_rss_mib: float | None
    benchmark_key: str | None
    synthetic_case_count: int | None
    trust_remote_code: bool = False
    product_enabled: bool = False
    activation_allowed: bool = False
    download_allowed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, ModelCompatibilityStatus) or any(
            not isinstance(reason, ModelCompatibilityReason)
            for reason in self.reason_codes
        ):
            raise ValueError("catalog status and reasons must use closed enums")
        if self.quantization not in {"none", "bitsandbytes_nf4"}:
            raise ValueError("quantization must use the closed vocabulary")
        if self.measurement_method not in {
            "torch_cuda_max_memory_allocated",
            "documented_approximate_gpu_peak_only",
            "not_measured",
        } or self.measurement_precision not in {
            "observed_to_0_001_mib",
            "documented_approximate_0_01_gib",
            "not_measured",
        }:
            raise ValueError("measurement provenance must use closed vocabularies")
        measurements = (
            self.observed_peak_gpu_allocation_mib,
            self.observed_peak_child_rss_mib,
        )
        if any(
            value is not None and (not math.isfinite(value) or value < 0)
            for value in measurements
        ):
            raise ValueError("resource measurements must be finite and nonnegative")
        present = sum(value is not None for value in measurements)
        expected_state = (
            ResourceMeasurementState.COMPLETE
            if present == 2
            else ResourceMeasurementState.PARTIAL
            if present == 1
            else ResourceMeasurementState.MISSING
        )
        if self.resource_measurement_state is not expected_state:
            raise ValueError("resource measurement state is inconsistent")
        if self.measurement_method == "torch_cuda_max_memory_allocated" and (
            self.measurement_precision != "observed_to_0_001_mib"
            or self.observed_peak_gpu_allocation_mib is None
        ):
            raise ValueError("observed GPU allocation provenance is inconsistent")
        if self.measurement_method == "documented_approximate_gpu_peak_only" and (
            self.quantization != "bitsandbytes_nf4"
            or self.measurement_precision != "documented_approximate_0_01_gib"
            or self.measurement_source
            != "real_metrics_campaign_diagnostic_2026_08_17"
            or self.observed_peak_gpu_allocation_mib is None
            or self.observed_peak_child_rss_mib is not None
        ):
            raise ValueError("approximate GPU diagnostic provenance is inconsistent")
        if self.measurement_method == "not_measured" and (
            self.measurement_precision != "not_measured"
            or self.observed_peak_gpu_allocation_mib is not None
        ):
            raise ValueError("missing GPU measurement provenance is inconsistent")
        if (
            self.trust_remote_code is not False
            or self.product_enabled is not False
            or self.activation_allowed is not False
            or self.download_allowed is not False
        ):
            raise ValueError("exploratory catalog entries cannot enable execution")


@dataclass(frozen=True, slots=True)
class ModelCompatibilityCatalog:
    inventory: ModelRuntimeInventory
    models: tuple[ModelCompatibilityEntry, ...]
    catalog_version: str = MODEL_COMPATIBILITY_CATALOG_VERSION
    measurement_version: str = RESOURCE_MEASUREMENT_VERSION
    catalog_policy: str = "exploratory_resource_fit_only"
    content_free: bool = True
    session_data_read: bool = False
    cache_contents_read: bool = False
    downloads_started: bool = False
    activation_allowed: bool = False
    local_only: bool = True
    persisted: bool = False
    synced: bool = False

    def __post_init__(self) -> None:
        keys = tuple(entry.configuration_key for entry in self.models)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("runtime configurations must be unique and ordered")
        if (
            self.catalog_version != MODEL_COMPATIBILITY_CATALOG_VERSION
            or self.measurement_version != RESOURCE_MEASUREMENT_VERSION
            or self.catalog_policy != "exploratory_resource_fit_only"
            or self.content_free is not True
            or self.session_data_read is not False
            or self.cache_contents_read is not False
            or self.downloads_started is not False
            or self.activation_allowed is not False
            or self.local_only is not True
            or self.persisted is not False
            or self.synced is not False
        ):
            raise ValueError("catalog privacy and execution invariants are fixed")


def _configuration(
    model_key: str,
    role: str,
    allocation: float | None,
    benchmark: str | None,
    cases: int | None,
    *,
    dtype: str = "float32",
    source: str = "wp_11_local_candidates_v1",
    configuration_key: str | None = None,
) -> ReviewedRuntimeConfiguration:
    return ReviewedRuntimeConfiguration(
        configuration_key=(
            configuration_key or f"{model_key}_unquantized_cuda_screen_v1"
        ),
        model_key=model_key,
        role=role,
        language_scope="english_polish",
        quantization="none",
        dtype=dtype,
        runtime="pytorch_2_8_cuda_12_6_synthetic_screen",
        measurement_method=(
            "torch_cuda_max_memory_allocated"
            if allocation is not None
            else "not_measured"
        ),
        measurement_precision=(
            "observed_to_0_001_mib"
            if allocation is not None
            else "not_measured"
        ),
        measurement_source=source,
        observed_peak_gpu_allocation_mib=allocation,
        observed_peak_child_rss_mib=None,
        benchmark_key=benchmark,
        synthetic_case_count=cases,
    )


_REVIEWED_CONFIGURATIONS: tuple[ReviewedRuntimeConfiguration, ...] = (
    _configuration("bge_m3", "retrieval", 2_179.602, "bilingual_model_screen_v1", 12),
    _configuration(
        "bge_reranker_v2_m3",
        "reranking",
        2_194.156,
        "bilingual_model_screen_v1",
        12,
    ),
    _configuration("deberta_small_long_nli", "scoped_nli", None, None, None),
    _configuration(
        "mdeberta_xnli",
        "scoped_nli",
        1_121.560,
        "bilingual_model_screen_v1",
        18,
    ),
    _configuration("modernbert_base_zeroshot", "binary_nli", None, None, None),
    _configuration(
        "multilingual_e5_base",
        "retrieval",
        1_078.121,
        "bilingual_model_screen_v1",
        12,
    ),
    _configuration(
        "multilingual_e5_small",
        "retrieval",
        462.436,
        "bilingual_model_screen_v1",
        12,
    ),
    _configuration(
        "multilingual_minilmv2_l12_nli",
        "scoped_nli",
        463.791,
        "specialist-foundation-metrics-v2",
        24,
        source="p1_specialist_screen_v2",
    ),
    _configuration(
        "multilingual_minilmv2_l6_nli",
        "scoped_nli",
        423.177,
        "specialist-foundation-metrics-v2",
        24,
        source="p1_specialist_screen_v2",
    ),
    _configuration(
        "qwen3_4b_rubric",
        "structured_rubric",
        7_769.893,
        "bilingual_rubric_screen_v1",
        24,
        dtype="runtime_float16_or_bfloat16",
        configuration_key="qwen3_4b_rubric_full_precision_cuda_screen_v1",
    ),
    ReviewedRuntimeConfiguration(
        configuration_key="qwen3_4b_rubric_bitsandbytes_nf4_child_v1",
        model_key="qwen3_4b_rubric",
        role="structured_rubric",
        language_scope="english_polish",
        quantization="bitsandbytes_nf4",
        dtype="nf4_runtime_float16_or_bfloat16_compute",
        runtime="disposable_pytorch_cuda_child",
        measurement_method="documented_approximate_gpu_peak_only",
        measurement_precision="documented_approximate_0_01_gib",
        measurement_source="real_metrics_campaign_diagnostic_2026_08_17",
        observed_peak_gpu_allocation_mib=3_932.16,
        observed_peak_child_rss_mib=None,
        benchmark_key=None,
        synthetic_case_count=None,
    ),
    _configuration(
        "qwen3_embedding_06b",
        "retrieval",
        1_197.371,
        "bilingual_model_screen_v1",
        12,
        dtype="runtime_float16_or_bfloat16",
    ),
    _configuration(
        "qwen3_reranker_06b",
        "reranking",
        1_488.585,
        "bilingual_model_screen_v1",
        12,
        dtype="runtime_float16_or_bfloat16",
    ),
)


def _bounded_positive(value: object, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= maximum else None


def _bucket_logical_cores(value: int | None) -> str | None:
    if value is None:
        return None
    if value <= 4:
        return "1_to_4"
    if value <= 8:
        return "5_to_8"
    if value <= 16:
        return "9_to_16"
    if value <= 32:
        return "17_to_32"
    if value <= 64:
        return "33_to_64"
    return "65_plus"


def _bucket_system_ram(value: int | None) -> str | None:
    if value is None:
        return None
    selected = "below_16_gib_class"
    for bucket, floor in _SYSTEM_RAM_BUCKET_FLOORS_MIB.items():
        if value < floor:
            break
        selected = bucket
    return selected


def _bucket_cuda_vram(value: int | None) -> str | None:
    if value is None:
        return None
    selected = "below_8_gib_class"
    for bucket, floor in _CUDA_VRAM_BUCKET_FLOORS_MIB.items():
        if value < floor:
            break
        selected = bucket
    return selected


def _bucket_cuda_capability(major: int, minor: int) -> str | None:
    if not 1 <= major <= 99 or not 0 <= minor <= 99:
        return None
    if major < 7:
        return "pre_7"
    if major == 7:
        return "7_x"
    if major == 8:
        return "8_x"
    return "9_plus"


def _bucket_disk(value: int | None) -> str | None:
    if value is None:
        return None
    if value < 10_240:
        return "under_10240_mib"
    if value < 51_200:
        return "10240_to_51199_mib"
    if value < 102_400:
        return "51200_to_102399_mib"
    return "102400_plus_mib"


def _cpu_architecture_bucket() -> str | None:
    try:
        value = platform.machine().strip().casefold()
        return _CPU_ARCHITECTURES.get(value)
    except Exception:
        return None


def _system_ram_mib() -> int | None:
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return _bounded_positive(
                int(status.total_physical // (1024 * 1024)), MAX_RESOURCE_MIB
            )
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return _bounded_positive(
            int(page_size * page_count // (1024 * 1024)), MAX_RESOURCE_MIB
        )
    except Exception:
        return None


def _cache_free_disk_mib(cache_root: Path) -> int | None:
    try:
        root = repository_root().resolve()
        candidate = cache_root if cache_root.is_absolute() else root / cache_root
        candidate.relative_to(root)
        existing = candidate
        while not existing.exists() and existing != root:
            existing = existing.parent
        resolved = existing.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        free = shutil.disk_usage(existing).free // (1024 * 1024)
        return _bounded_positive(int(free), MAX_DISK_MIB)
    except Exception:
        return None


def _accelerator_probe_environment() -> dict[str, str]:
    allowed: dict[str, str] = {}
    for name in (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "CUDA_VISIBLE_DEVICES",
    ):
        value = os.environ.get(name)
        if value:
            allowed[name] = value
    allowed.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    return allowed


def _parse_accelerator_probe(payload: object) -> _AcceleratorProbe:
    keys = {
        "schema_version",
        "cuda_state",
        "cuda_total_memory_mib",
        "cuda_capability_major",
        "cuda_capability_minor",
        "mps_available",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("invalid accelerator probe")
    schema_version = payload["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != ACCELERATOR_PROBE_SCHEMA_VERSION
    ):
        raise ValueError("invalid accelerator probe")
    try:
        state = CudaInventoryState(payload["cuda_state"])
    except (TypeError, ValueError):
        raise ValueError("invalid accelerator probe") from None
    mps_available = payload["mps_available"]
    if not isinstance(mps_available, bool):
        raise ValueError("invalid accelerator probe")
    memory = payload["cuda_total_memory_mib"]
    major = payload["cuda_capability_major"]
    minor = payload["cuda_capability_minor"]
    if state is CudaInventoryState.AVAILABLE:
        bounded_memory = _bounded_positive(memory, MAX_RESOURCE_MIB)
        bounded_major = _bounded_positive(major, 99)
        if (
            bounded_memory is None
            or bounded_major is None
            or isinstance(minor, bool)
            or not isinstance(minor, int)
            or not 0 <= minor <= 99
        ):
            raise ValueError("invalid accelerator probe")
        return _AcceleratorProbe(
            cuda_state=state,
            cuda_total_memory_mib=bounded_memory,
            cuda_capability_major=bounded_major,
            cuda_capability_minor=minor,
            mps_available=mps_available,
        )
    if memory is not None or major is not None or minor is not None:
        raise ValueError("invalid accelerator probe")
    if state is CudaInventoryState.UNKNOWN and mps_available:
        raise ValueError("invalid accelerator probe")
    return _AcceleratorProbe(
        cuda_state=state,
        cuda_total_memory_mib=None,
        cuda_capability_major=None,
        cuda_capability_minor=None,
        mps_available=mps_available,
    )


def _start_accelerator_probe_process(
    command: list[str],
    *,
    root: Path,
    environment: dict[str, str],
) -> OwnedProcess:
    return start_owned_process(
        command,
        cwd=root,
        env=environment,
        capture_stdout=True,
        capture_stderr=False,
        maximum_active_processes=8,
    )


def _close_accelerator_probe_process(process: object) -> bool:
    close = getattr(process, "close", None)
    if callable(close):
        try:
            return bool(close())
        except Exception:
            return False
    stdout = getattr(process, "stdout", None)
    if stdout is not None:
        try:
            stdout.close()
        except (OSError, ValueError):
            return False
    return True


def _terminate_accelerator_probe_process_tree(process: OwnedProcess) -> bool:
    """Adapt the model-child lifecycle contract and positively reap the tree."""

    confirmed = terminate_owned_process(
        process,
        graceful_timeout=ACCELERATOR_PROBE_TERMINATION_GRACE_SECONDS,
        forced_timeout=ACCELERATOR_PROBE_TERMINATION_GRACE_SECONDS,
    )
    closed = _close_accelerator_probe_process(process)
    return confirmed and closed


def _read_bounded_accelerator_probe(
    command: list[str],
    *,
    root: Path,
    environment: dict[str, str],
    timeout_seconds: float = ACCELERATOR_PROBE_TIMEOUT_SECONDS,
) -> bytes | None:
    """Read at most 2,049 bytes while enforcing one total child deadline."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= ACCELERATOR_PROBE_TIMEOUT_SECONDS
    ):
        return None
    deadline = monotonic() + float(timeout_seconds)
    try:
        process = _start_accelerator_probe_process(
            command,
            root=root,
            environment=environment,
        )
    except OSError:
        return None
    if process.stdout is None:
        if not _terminate_accelerator_probe_process_tree(process):
            raise RuntimeError("accelerator_probe_cleanup_unconfirmed")
        return None

    captured = bytearray()
    read_failed: list[bool] = []

    def read_bounded() -> None:
        try:
            while len(captured) <= MAX_ACCELERATOR_PROBE_OUTPUT_BYTES:
                chunk = process.stdout.read(
                    MAX_ACCELERATOR_PROBE_OUTPUT_BYTES + 1 - len(captured)
                )
                if not chunk:
                    break
                captured.extend(chunk)
        except (OSError, ValueError):
            read_failed.append(True)

    reader = Thread(target=read_bounded, daemon=True)
    reader.start()
    reader.join(timeout=max(0.0, deadline - monotonic()))
    if reader.is_alive():
        cleanup_confirmed = _terminate_accelerator_probe_process_tree(process)
        reader.join(timeout=ACCELERATOR_PROBE_TERMINATION_GRACE_SECONDS)
        if not cleanup_confirmed:
            raise RuntimeError("accelerator_probe_cleanup_unconfirmed")
        return None
    output = bytes(captured)
    if read_failed or len(output) > MAX_ACCELERATOR_PROBE_OUTPUT_BYTES:
        if not _terminate_accelerator_probe_process_tree(process):
            raise RuntimeError("accelerator_probe_cleanup_unconfirmed")
        return None
    try:
        process.wait(timeout=max(0.0, deadline - monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        if not _terminate_accelerator_probe_process_tree(process):
            raise RuntimeError("accelerator_probe_cleanup_unconfirmed") from None
        return None
    return_code = process.returncode
    try:
        cleanup_confirmed = process_tree_exited(process)
    except Exception:
        cleanup_confirmed = False
    handles_closed = _close_accelerator_probe_process(process)
    if not cleanup_confirmed or not handles_closed or return_code is None:
        raise RuntimeError("accelerator_probe_cleanup_unconfirmed")
    return output if return_code == 0 else None


def _run_accelerator_probe() -> _AcceleratorProbe:
    """Run Torch discovery only in a sanitized, timeout-bounded child."""

    resource = default_packaged_resource_resolver().resolve(
        ResourceKind.ACCELERATOR_PROBE
    )
    if (
        resource.availability is not ResourceAvailability.AVAILABLE
        or resource.path is None
    ):
        return _unknown_accelerator_probe()
    script = resource.path
    try:
        output = _read_bounded_accelerator_probe(
            [sys.executable, "-I", str(script)],
            root=script.parent,
            environment=_accelerator_probe_environment(),
        )
        if output is None:
            return _unknown_accelerator_probe()
        payload = json.loads(output.decode("utf-8"))
        return _parse_accelerator_probe(payload)
    except Exception:
        return _unknown_accelerator_probe()


def discover_runtime_inventory(
    *, cache_root: Path | None = None
) -> ModelRuntimeInventory:
    """Return typed buckets; every discovery exception becomes typed unknown."""

    probe = _run_accelerator_probe()
    cuda_state = probe.cuda_state
    cuda_vram_bucket: str | None = None
    cuda_capability_bucket: str | None = None
    mps = probe.mps_available
    preferred = "cpu"
    try:
        if cuda_state is CudaInventoryState.AVAILABLE:
            cuda_vram_bucket = _bucket_cuda_vram(probe.cuda_total_memory_mib)
            cuda_capability_bucket = _bucket_cuda_capability(
                int(probe.cuda_capability_major),
                int(probe.cuda_capability_minor),
            )
            if cuda_vram_bucket is None or cuda_capability_bucket is None:
                raise ValueError("incomplete CUDA aggregate")
            preferred = "cuda"
        elif cuda_state is CudaInventoryState.UNAVAILABLE:
            preferred = "mps" if mps else "cpu"
        else:
            mps = False
    except Exception:
        cuda_state = CudaInventoryState.UNKNOWN
        cuda_vram_bucket = None
        cuda_capability_bucket = None
        mps = False
        preferred = "cpu"

    try:
        exact_cores = _bounded_positive(os.cpu_count(), MAX_LOGICAL_CORE_COUNT)
        logical_core_bucket = _bucket_logical_cores(exact_cores)
    except Exception:
        logical_core_bucket = None
    try:
        system_ram_bucket = _bucket_system_ram(_system_ram_mib())
    except Exception:
        system_ram_bucket = None
    try:
        disk_bucket = _bucket_disk(
            _cache_free_disk_mib(cache_root or model_eval_cache_root())
        )
    except Exception:
        disk_bucket = None
    cpu_bucket = _cpu_architecture_bucket()

    reasons: set[HardwareDiscoveryReason] = set()
    if cpu_bucket is None:
        reasons.add(HardwareDiscoveryReason.CPU_ARCHITECTURE_UNKNOWN)
    if logical_core_bucket is None:
        reasons.add(HardwareDiscoveryReason.LOGICAL_CORE_BUCKET_UNKNOWN)
    if system_ram_bucket is None:
        reasons.add(HardwareDiscoveryReason.SYSTEM_RAM_BUCKET_UNKNOWN)
    if cuda_state is CudaInventoryState.UNKNOWN:
        reasons.add(HardwareDiscoveryReason.CUDA_INVENTORY_UNKNOWN)
    if disk_bucket is None:
        reasons.add(HardwareDiscoveryReason.MODEL_CACHE_FREE_DISK_BUCKET_UNKNOWN)

    return ModelRuntimeInventory(
        preferred_device=preferred,
        cuda_state=cuda_state,
        cuda_available=(
            True
            if cuda_state is CudaInventoryState.AVAILABLE
            else False
            if cuda_state is CudaInventoryState.UNAVAILABLE
            else None
        ),
        mps_available=mps,
        cpu_available=True,
        cpu_architecture_bucket=cpu_bucket,
        logical_core_bucket=logical_core_bucket,
        system_ram_bucket=system_ram_bucket,
        cuda_vram_bucket=cuda_vram_bucket,
        cuda_capability_bucket=cuda_capability_bucket,
        model_cache_free_disk_bucket=disk_bucket,
        discovery_reason_codes=tuple(sorted(reasons, key=lambda reason: reason.value)),
    )


class _RuntimeInventoryCache:
    """Process-local bucket-only TTL cache with single-flight refresh."""

    def __init__(
        self,
        *,
        ttl_seconds: float = RUNTIME_INVENTORY_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("inventory cache TTL must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._condition = Condition(Lock())
        self._value: ModelRuntimeInventory | None = None
        self._stored_at = 0.0
        self._generation = 0
        self._loading = False

    def get(
        self,
        loader: Callable[[], ModelRuntimeInventory],
        *,
        force_refresh: bool = False,
    ) -> ModelRuntimeInventory:
        with self._condition:
            observed_generation = self._generation
            while self._loading:
                self._condition.wait()
                if (
                    self._generation != observed_generation
                    and self._value is not None
                ):
                    return self._value
            now = self._clock()
            age = now - self._stored_at
            if (
                not force_refresh
                and self._value is not None
                and 0 <= age < self._ttl_seconds
            ):
                return self._value
            self._loading = True
        try:
            value = loader()
            if not isinstance(value, ModelRuntimeInventory):
                raise TypeError("inventory loader returned an invalid value")
        except Exception:
            with self._condition:
                self._loading = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._value = value
            self._stored_at = self._clock()
            self._generation += 1
            self._loading = False
            self._condition.notify_all()
            return value

    def clear(self) -> None:
        with self._condition:
            self._value = None
            self._stored_at = 0.0
            self._generation += 1
            self._condition.notify_all()


_RUNTIME_INVENTORY_CACHE = _RuntimeInventoryCache()


def cached_runtime_inventory(
    *, force_refresh: bool = False
) -> ModelRuntimeInventory:
    """Share one nonpersisted bucket inventory across read-only consumers."""

    return _RUNTIME_INVENTORY_CACHE.get(
        discover_runtime_inventory,
        force_refresh=force_refresh,
    )


def _safe_manifests() -> dict[str, ModelManifest]:
    # Lazy import breaks the package cycle when specialist modules themselves
    # import the base text-model manifest type in a clean Python process.
    try:
        from ..specialist_screen.manifests import SPECIALIST_MODEL_MANIFESTS
    except Exception:
        raise ModelCompatibilityCatalogUnavailableError() from None

    manifests = {**TEXT_MODEL_MANIFESTS, **SPECIALIST_MODEL_MANIFESTS}
    configured = {item.model_key for item in _REVIEWED_CONFIGURATIONS}
    if set(manifests) != configured:
        raise ModelCompatibilityCatalogUnavailableError()
    return manifests


def _system_ram_sufficient(bucket: str | None) -> bool | None:
    if bucket is None:
        return None
    floor = _SYSTEM_RAM_BUCKET_FLOORS_MIB.get(bucket)
    return None if floor is None else floor >= MIN_SYSTEM_RAM_MIB


def _cuda_vram_sufficient(bucket: str | None) -> bool | None:
    if bucket is None:
        return None
    floor = _CUDA_VRAM_BUCKET_FLOORS_MIB.get(bucket)
    return None if floor is None else floor >= MIN_CUDA_VRAM_MIB


def _resource_status(
    inventory: ModelRuntimeInventory,
    resource: ReviewedRuntimeConfiguration,
) -> tuple[ModelCompatibilityStatus, tuple[ModelCompatibilityReason, ...]]:
    ram_sufficient = _system_ram_sufficient(inventory.system_ram_bucket)
    if ram_sufficient is None:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.HARDWARE_INVENTORY_UNKNOWN,
        )
    if not ram_sufficient:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.INSUFFICIENT_SYSTEM_RAM,
        )
    # Host inventory takes precedence over per-configuration observations. A
    # known oversized configuration must not hide that this host cannot run
    # any reviewed CUDA configuration or that its CUDA state is unknown.
    if inventory.cuda_state is CudaInventoryState.UNKNOWN:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.CUDA_INVENTORY_UNKNOWN,
        )
    if inventory.cuda_state is CudaInventoryState.UNAVAILABLE:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.CUDA_UNAVAILABLE,
        )
    vram_sufficient = _cuda_vram_sufficient(inventory.cuda_vram_bucket)
    if vram_sufficient is None:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.CUDA_INVENTORY_UNKNOWN,
        )
    if not vram_sufficient:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.INSUFFICIENT_CUDA_VRAM,
        )
    allocation = resource.observed_peak_gpu_allocation_mib
    rss = resource.observed_peak_child_rss_mib
    if (
        allocation is not None
        and allocation > MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB
    ):
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.CHILD_GPU_ALLOCATION_CEILING_EXCEEDED,
        )
    if rss is not None and rss > MODEL_CHILD_RSS_CEILING_MIB:
        return ModelCompatibilityStatus.UNAVAILABLE, (
            ModelCompatibilityReason.CHILD_RSS_CEILING_EXCEEDED,
        )
    if resource.measurement_state is not ResourceMeasurementState.COMPLETE:
        return ModelCompatibilityStatus.RESEARCH_ONLY, (
            ModelCompatibilityReason.RESOURCE_MEASUREMENT_MISSING,
        )
    return ModelCompatibilityStatus.RESEARCH_ONLY, (
        ModelCompatibilityReason.EXPLORATORY_RESOURCE_FIT,
    )


def build_model_compatibility_catalog(
    inventory: ModelRuntimeInventory,
) -> ModelCompatibilityCatalog:
    """Project resource fit without selecting or promoting any model."""

    manifests = _safe_manifests()
    entries: list[ModelCompatibilityEntry] = []
    for resource in _REVIEWED_CONFIGURATIONS:
        manifest = manifests[resource.model_key]
        status, reasons = _resource_status(inventory, resource)
        entries.append(
            ModelCompatibilityEntry(
                configuration_key=resource.configuration_key,
                model_key=resource.model_key,
                repository_id=manifest.repository_id,
                revision=manifest.revision,
                task=manifest.task.value,
                role=resource.role,
                language_scope=resource.language_scope,
                license_spdx=manifest.license_spdx,
                status=status,
                reason_codes=reasons,
                quantization=resource.quantization,
                dtype=resource.dtype,
                runtime=resource.runtime,
                measurement_method=resource.measurement_method,
                measurement_precision=resource.measurement_precision,
                measurement_source=resource.measurement_source,
                resource_measurement_state=resource.measurement_state,
                observed_peak_gpu_allocation_mib=(
                    resource.observed_peak_gpu_allocation_mib
                ),
                observed_peak_child_rss_mib=resource.observed_peak_child_rss_mib,
                benchmark_key=resource.benchmark_key,
                synthetic_case_count=resource.synthetic_case_count,
                trust_remote_code=manifest.trust_remote_code,
            )
        )

    if set(BLOCKED_TEXT_MODEL_MANIFESTS) != {BGE_M3_LEGACY_BLOCKED.key}:
        raise ModelCompatibilityCatalogUnavailableError()
    entries.append(
        ModelCompatibilityEntry(
            configuration_key="bge_m3_legacy_pickle_pin_blocked_v1",
            model_key=BGE_M3_LEGACY_BLOCKED.key,
            repository_id=BGE_M3_LEGACY_BLOCKED.repository_id,
            revision=BGE_M3_LEGACY_BLOCKED.revision,
            task="requirement_action_retrieval",
            role="retrieval",
            language_scope="english_polish",
            license_spdx=BGE_M3_LEGACY_BLOCKED.license_spdx,
            status=ModelCompatibilityStatus.UNAVAILABLE,
            reason_codes=(ModelCompatibilityReason.UNSAFE_PICKLE_ONLY,),
            quantization="none",
            dtype="unknown",
            runtime="not_runnable",
            measurement_method="not_measured",
            measurement_precision="not_measured",
            measurement_source="reviewed_artifact_gate_v1",
            resource_measurement_state=ResourceMeasurementState.MISSING,
            observed_peak_gpu_allocation_mib=None,
            observed_peak_child_rss_mib=None,
            benchmark_key=None,
            synthetic_case_count=None,
        )
    )
    return ModelCompatibilityCatalog(
        inventory=inventory,
        models=tuple(sorted(entries, key=lambda entry: entry.configuration_key)),
    )


__all__ = [
    "CudaInventoryState",
    "HARDWARE_INVENTORY_VERSION",
    "HardwareDiscoveryReason",
    "MIN_CUDA_VRAM_MIB",
    "MIN_SYSTEM_RAM_MIB",
    "MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB",
    "MODEL_CHILD_RSS_CEILING_MIB",
    "MODEL_COMPATIBILITY_CATALOG_VERSION",
    "ModelCompatibilityCatalog",
    "ModelCompatibilityCatalogUnavailableError",
    "ModelCompatibilityEntry",
    "ModelCompatibilityReason",
    "ModelCompatibilityStatus",
    "ModelRuntimeInventory",
    "ResourceMeasurementState",
    "build_model_compatibility_catalog",
    "cached_runtime_inventory",
    "discover_runtime_inventory",
]
