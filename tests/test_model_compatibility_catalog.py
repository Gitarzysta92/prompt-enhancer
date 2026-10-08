from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock
import time

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure import text_models as text_models_package
from prompt_enhancer.infrastructure.text_models import compatibility as catalog_module
from prompt_enhancer.infrastructure.text_models.compatibility import (
    CudaInventoryState,
    HardwareDiscoveryReason,
    MIN_CUDA_VRAM_MIB,
    MIN_SYSTEM_RAM_MIB,
    MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB,
    MODEL_CHILD_RSS_CEILING_MIB,
    ModelCompatibilityCatalogUnavailableError,
    ModelRuntimeInventory,
    ReviewedRuntimeConfiguration,
    build_model_compatibility_catalog,
    discover_runtime_inventory,
)
from prompt_enhancer.infrastructure.text_models.jobs import (
    LocalTextModelEvaluationService,
)


TOKEN = "example_model_compatibility_token_do_not_use_123456789"
ROOT = Path(__file__).resolve().parents[1]


def inventory(
    *,
    ram_bucket: str | None,
    cuda_state: CudaInventoryState,
    cuda_bucket: str | None,
) -> ModelRuntimeInventory:
    unknown = cuda_state is CudaInventoryState.UNKNOWN
    reasons = set()
    if ram_bucket is None:
        reasons.add(HardwareDiscoveryReason.SYSTEM_RAM_BUCKET_UNKNOWN)
    if unknown:
        reasons.add(HardwareDiscoveryReason.CUDA_INVENTORY_UNKNOWN)
    return ModelRuntimeInventory(
        preferred_device=(
            "cuda" if cuda_state is CudaInventoryState.AVAILABLE else "cpu"
        ),
        cuda_state=cuda_state,
        cuda_available=(
            True
            if cuda_state is CudaInventoryState.AVAILABLE
            else False
            if cuda_state is CudaInventoryState.UNAVAILABLE
            else None
        ),
        mps_available=False,
        cpu_available=True,
        cpu_architecture_bucket="x86_64",
        logical_core_bucket="9_to_16",
        system_ram_bucket=ram_bucket,
        cuda_vram_bucket=cuda_bucket,
        cuda_capability_bucket=(
            "8_x" if cuda_state is CudaInventoryState.AVAILABLE else None
        ),
        model_cache_free_disk_bucket="10240_to_51199_mib",
        discovery_reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
    )


def by_configuration(catalog):  # type: ignore[no-untyped-def]
    return {item.configuration_key: item for item in catalog.models}


def resource_configuration(
    *, allocation: float | None, rss: float | None
) -> ReviewedRuntimeConfiguration:
    return ReviewedRuntimeConfiguration(
        configuration_key="synthetic_resource_configuration_v1",
        model_key="multilingual_e5_small",
        role="retrieval",
        language_scope="english_polish",
        quantization="none",
        dtype="float32",
        runtime="synthetic_runtime_v1",
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
        measurement_source="synthetic_fixture_v1",
        observed_peak_gpu_allocation_mib=allocation,
        observed_peak_child_rss_mib=rss,
        benchmark_key="synthetic_benchmark_v1",
        synthetic_case_count=12,
    )


def test_8gb_vram_16gb_ram_returns_exploratory_resource_evidence_only() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="8_gib_class",
        )
    )
    serialized = repr(asdict(catalog)).casefold()

    assert {item.status.value for item in catalog.models} <= {
        "research_only",
        "unavailable",
    }
    for forbidden in ("validated", "recommended", "selected"):
        assert forbidden not in serialized
    assert all(not item.product_enabled for item in catalog.models)
    assert all(not item.activation_allowed for item in catalog.models)
    assert all(not item.download_allowed for item in catalog.models)


def test_cpu_8gb_ram_is_unavailable_without_inventing_resource_fit() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket="below_16_gib_class",
            cuda_state=CudaInventoryState.UNAVAILABLE,
            cuda_bucket=None,
        )
    )

    for item in catalog.models:
        if item.model_key == "bge_m3_legacy_pickle_pin":
            assert item.reason_codes == ("unsafe_pickle_only",)
        else:
            assert item.status == "unavailable"
            assert item.reason_codes == ("insufficient_system_ram",)


def test_16gb_vram_does_not_bypass_either_child_resource_ceiling() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="16_gib_class",
        )
    )
    models = by_configuration(catalog)
    full_precision = models["qwen3_4b_rubric_full_precision_cuda_screen_v1"]
    nf4 = models["qwen3_4b_rubric_bitsandbytes_nf4_child_v1"]

    assert full_precision.status == "unavailable"
    assert full_precision.reason_codes == (
        "child_gpu_allocation_ceiling_exceeded",
    )
    assert full_precision.observed_peak_gpu_allocation_mib == 7_769.893
    assert nf4.status == "research_only"
    assert nf4.resource_measurement_state == "partial"
    assert nf4.reason_codes == ("resource_measurement_missing",)
    assert nf4.measurement_method == "documented_approximate_gpu_peak_only"
    assert nf4.measurement_precision == "documented_approximate_0_01_gib"
    assert nf4.measurement_source == "real_metrics_campaign_diagnostic_2026_08_17"
    assert nf4.observed_peak_gpu_allocation_mib == 3_932.16
    assert nf4.observed_peak_child_rss_mib is None
    assert MODEL_CHILD_GPU_ALLOCATION_CEILING_MIB == 6_144
    assert MODEL_CHILD_RSS_CEILING_MIB == 8_192


def test_resource_gate_requires_gpu_allocation_and_child_rss() -> None:
    hardware = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )

    gpu_status, gpu_reasons = catalog_module._resource_status(
        hardware, resource_configuration(allocation=6_145, rss=1_000)
    )
    rss_status, rss_reasons = catalog_module._resource_status(
        hardware, resource_configuration(allocation=1_000, rss=8_193)
    )
    fit_status, fit_reasons = catalog_module._resource_status(
        hardware, resource_configuration(allocation=1_000, rss=2_000)
    )

    assert (gpu_status.value, gpu_reasons[0].value) == (
        "unavailable",
        "child_gpu_allocation_ceiling_exceeded",
    )
    assert (rss_status.value, rss_reasons[0].value) == (
        "unavailable",
        "child_rss_ceiling_exceeded",
    )
    assert (fit_status.value, fit_reasons[0].value) == (
        "research_only",
        "exploratory_resource_fit",
    )


@pytest.mark.parametrize(
    ("cuda_state", "cuda_bucket", "expected_reason"),
    (
        (CudaInventoryState.UNAVAILABLE, None, "cuda_unavailable"),
        (CudaInventoryState.UNKNOWN, None, "cuda_inventory_unknown"),
        (
            CudaInventoryState.AVAILABLE,
            "below_8_gib_class",
            "insufficient_cuda_vram",
        ),
    ),
)
@pytest.mark.parametrize(
    ("allocation", "rss"),
    ((None, None), (1_000.0, 2_000.0), (7_769.893, None)),
    ids=(
        "incomplete_measurement",
        "complete_measurement",
        "oversized_incomplete_configuration",
    ),
)
def test_hard_cuda_inventory_gates_precede_measurement_state(
    cuda_state: CudaInventoryState,
    cuda_bucket: str | None,
    expected_reason: str,
    allocation: float | None,
    rss: float | None,
) -> None:
    hardware = inventory(
        ram_bucket="16_gib_class",
        cuda_state=cuda_state,
        cuda_bucket=cuda_bucket,
    )

    status, reasons = catalog_module._resource_status(
        hardware,
        resource_configuration(allocation=allocation, rss=rss),
    )

    assert status.value == "unavailable"
    assert tuple(reason.value for reason in reasons) == (expected_reason,)


@pytest.mark.parametrize(
    ("allocation", "rss", "expected_reason"),
    (
        (None, None, "resource_measurement_missing"),
        (1_000.0, 2_000.0, "exploratory_resource_fit"),
    ),
    ids=("incomplete_measurement", "complete_measurement"),
)
def test_measurement_state_only_changes_research_reason_after_hard_gates_pass(
    allocation: float | None,
    rss: float | None,
    expected_reason: str,
) -> None:
    hardware = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )

    status, reasons = catalog_module._resource_status(
        hardware,
        resource_configuration(allocation=allocation, rss=rss),
    )

    assert status.value == "research_only"
    assert tuple(reason.value for reason in reasons) == (expected_reason,)


def test_runtime_configuration_provenance_never_calls_allocation_total_vram() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="8_gib_class",
        )
    )
    full_precision = by_configuration(catalog)[
        "qwen3_4b_rubric_full_precision_cuda_screen_v1"
    ]

    assert full_precision.quantization == "none"
    assert full_precision.dtype == "runtime_float16_or_bfloat16"
    assert full_precision.runtime == "pytorch_2_8_cuda_12_6_synthetic_screen"
    assert full_precision.measurement_method == "torch_cuda_max_memory_allocated"
    assert full_precision.measurement_precision == "observed_to_0_001_mib"
    keys = set(asdict(full_precision))
    assert "observed_peak_gpu_allocation_mib" in keys
    assert "observed_peak_child_rss_mib" in keys
    assert "observed_peak_cuda_mib" not in keys
    assert "total_vram" not in repr(asdict(full_precision)).casefold()


def test_unknown_inventory_remains_typed_unknown_and_selects_nothing() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket=None,
            cuda_state=CudaInventoryState.UNKNOWN,
            cuda_bucket=None,
        )
    )

    assert catalog.inventory.cuda_available is None
    safe = [
        item
        for item in catalog.models
        if item.model_key != "bge_m3_legacy_pickle_pin"
    ]
    assert {item.status.value for item in safe} == {"unavailable"}
    assert {item.reason_codes[0].value for item in safe} == {
        "hardware_inventory_unknown"
    }


def test_inventory_cross_field_and_privacy_invariants_fail_closed() -> None:
    base = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )
    values = asdict(base)

    with pytest.raises(ValueError, match="available CUDA inventory"):
        ModelRuntimeInventory(**{**values, "cuda_vram_bucket": None})
    with pytest.raises(ValueError, match="unknown reasons"):
        ModelRuntimeInventory(
            **{
                **values,
                "discovery_reason_codes": (
                    HardwareDiscoveryReason.CUDA_INVENTORY_UNKNOWN,
                ),
            }
        )
    with pytest.raises(ValueError, match="privacy and execution"):
        ModelRuntimeInventory(**{**values, "persisted": True})


@pytest.mark.parametrize(
    ("value", "bucket", "sufficient"),
    (
        (15_359, "below_16_gib_class", False),
        (15_360, "16_gib_class", True),
        (16_383, "16_gib_class", True),
    ),
)
def test_reviewed_16gib_ram_class_floor(
    value: int, bucket: str, sufficient: bool
) -> None:
    observed = catalog_module._bucket_system_ram(value)

    assert MIN_SYSTEM_RAM_MIB == 15_360
    assert text_models_package.MIN_SYSTEM_RAM_MIB == MIN_SYSTEM_RAM_MIB
    assert observed == bucket
    assert catalog_module._system_ram_sufficient(observed) is sufficient


@pytest.mark.parametrize(
    ("value", "bucket", "sufficient"),
    (
        (7_679, "below_8_gib_class", False),
        (7_680, "8_gib_class", True),
        (8_191, "8_gib_class", True),
    ),
)
def test_reviewed_8gib_cuda_class_floor(
    value: int, bucket: str, sufficient: bool
) -> None:
    observed = catalog_module._bucket_cuda_vram(value)

    assert MIN_CUDA_VRAM_MIB == 7_680
    assert text_models_package.MIN_CUDA_VRAM_MIB == MIN_CUDA_VRAM_MIB
    assert observed == bucket
    assert catalog_module._cuda_vram_sufficient(observed) is sufficient


def accelerator_probe_payload(
    *,
    state: str = "available",
    memory_mib: int | None = 8_191,
    major: int | None = 8,
    minor: int | None = 6,
    mps_available: bool = False,
) -> bytes:
    payload = {
        "schema_version": 1,
        "cuda_state": state,
        "cuda_total_memory_mib": memory_mib,
        "cuda_capability_major": major,
        "cuda_capability_minor": minor,
        "mps_available": mps_available,
    }
    return json.dumps(payload).encode("utf-8")


def test_hardware_discovery_buckets_exact_facts_and_marks_sensitive_local_state(
    monkeypatch,
) -> None:
    subprocess_call: dict[str, object] = {}

    def fake_read(command, **kwargs):  # type: ignore[no-untyped-def]
        subprocess_call["command"] = command
        subprocess_call["kwargs"] = kwargs
        return accelerator_probe_payload()

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(
        catalog_module, "_read_bounded_accelerator_probe", fake_read
    )
    monkeypatch.setattr(catalog_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(catalog_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(catalog_module, "_system_ram_mib", lambda: 16_383)
    monkeypatch.setattr(catalog_module, "_cache_free_disk_mib", lambda _path: 65_536)

    discovered = discover_runtime_inventory()
    values = asdict(discovered)

    assert discovered.cpu_architecture_bucket == "x86_64"
    assert discovered.logical_core_bucket == "9_to_16"
    assert discovered.system_ram_bucket == "16_gib_class"
    assert discovered.cuda_vram_bucket == "8_gib_class"
    assert discovered.cuda_capability_bucket == "8_x"
    assert discovered.model_cache_free_disk_bucket == "51200_to_102399_mib"
    assert discovered.sensitivity == "sensitive_derived"
    assert discovered.local_only is True
    assert discovered.persisted is False
    assert discovered.synced is False
    assert "torch" not in sys.modules
    assert subprocess_call["command"][1] == "-I"  # type: ignore[index]
    kwargs = subprocess_call["kwargs"]
    assert "HOME" not in kwargs["environment"]  # type: ignore[operator,index]
    assert "USERNAME" not in kwargs["environment"]  # type: ignore[operator,index]
    for exact in (
        "logical_core_count",
        "system_ram_mib",
        "cuda_memory_mb",
        "cuda_compute_capability",
        "model_cache_free_disk_mib",
    ):
        assert exact not in values


def test_assertion_and_discovery_exceptions_become_typed_unknown(monkeypatch) -> None:
    def failing_probe(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("synthetic-private-canary")

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(
        catalog_module, "_read_bounded_accelerator_probe", failing_probe
    )
    monkeypatch.setattr(catalog_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        catalog_module.os,
        "cpu_count",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic-private-canary")),
    )
    monkeypatch.setattr(catalog_module, "_system_ram_mib", lambda: 16_384)
    monkeypatch.setattr(catalog_module, "_cache_free_disk_mib", lambda _path: 65_536)

    discovered = discover_runtime_inventory()

    assert discovered.cuda_state == "unknown"
    assert discovered.cuda_available is None
    assert discovered.logical_core_bucket is None
    assert "cuda_inventory_unknown" in discovered.discovery_reason_codes
    assert "logical_core_bucket_unknown" in discovered.discovery_reason_codes
    assert "synthetic-private-canary" not in repr(asdict(discovered))
    assert "torch" not in sys.modules


@pytest.mark.parametrize(
    "output",
    (
        None,
        b'{"detail":"synthetic-private-canary"}',
        json.dumps(
                {
                    "schema_version": 1,
                    "cuda_state": "available",
                    "cuda_total_memory_mib": 8_191,
                    "cuda_capability_major": 8,
                    "cuda_capability_minor": 6,
                    "mps_available": False,
                    "device_name": "synthetic-private-canary",
                }
            ).encode("utf-8"),
        json.dumps(
                {
                    "schema_version": 1.0,
                    "cuda_state": "available",
                    "cuda_total_memory_mib": 8_191,
                    "cuda_capability_major": 8,
                    "cuda_capability_minor": 6,
                    "mps_available": False,
                }
            ).encode("utf-8"),
        b"x" * 2_049,
    ),
    ids=(
        "nonzero",
        "invalid_schema",
        "extra_identity_field",
        "noninteger_schema_version",
        "oversized",
    ),
)
def test_accelerator_child_failures_use_one_fixed_unknown_code(
    monkeypatch,
    output: bytes | None,
) -> None:
    monkeypatch.setattr(
        catalog_module,
        "_read_bounded_accelerator_probe",
        lambda *_args, **_kwargs: output,
    )
    monkeypatch.setattr(catalog_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(catalog_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(catalog_module, "_system_ram_mib", lambda: 15_360)
    monkeypatch.setattr(catalog_module, "_cache_free_disk_mib", lambda _path: 65_536)

    discovered = discover_runtime_inventory()

    assert discovered.cuda_state == "unknown"
    assert discovered.discovery_reason_codes == ("cuda_inventory_unknown",)
    assert "synthetic-private-canary" not in repr(asdict(discovered))


def test_accelerator_child_timeout_is_typed_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        catalog_module,
        "_read_bounded_accelerator_probe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(catalog_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(catalog_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(catalog_module, "_system_ram_mib", lambda: 15_360)
    monkeypatch.setattr(catalog_module, "_cache_free_disk_mib", lambda _path: 65_536)

    discovered = discover_runtime_inventory()

    assert discovered.cuda_state == "unknown"
    assert discovered.discovery_reason_codes == ("cuda_inventory_unknown",)


def test_accelerator_cleanup_unconfirmed_is_typed_unknown(monkeypatch) -> None:
    def cleanup_unconfirmed(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("accelerator_probe_cleanup_unconfirmed")

    monkeypatch.setattr(
        catalog_module,
        "_read_bounded_accelerator_probe",
        cleanup_unconfirmed,
    )
    monkeypatch.setattr(catalog_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(catalog_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(catalog_module, "_system_ram_mib", lambda: 15_360)
    monkeypatch.setattr(catalog_module, "_cache_free_disk_mib", lambda _path: 65_536)

    discovered = discover_runtime_inventory()

    assert discovered.cuda_state == "unknown"
    assert discovered.discovery_reason_codes == ("cuda_inventory_unknown",)


@pytest.mark.skipif(os.name != "nt", reason="Windows owned-job contract")
def test_windows_accelerator_cleanup_reaps_an_atomically_owned_descendant(
    tmp_path: Path,
) -> None:
    root_ready = tmp_path / "synthetic-root-ready"
    descendant_marker = tmp_path / "synthetic-descendant-survived"
    grandchild = (
        "import pathlib,time; time.sleep(0.5); "
        f"pathlib.Path({str(descendant_marker)!r}).write_text('synthetic','utf-8')"
    )
    script = tmp_path / "synthetic_natural_root_exit.py"
    script.write_text(
        "import pathlib,subprocess,sys,time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"{grandchild!r}], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"pathlib.Path({str(root_ready)!r}).write_text('synthetic','utf-8')\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    process = catalog_module._start_accelerator_probe_process(
        [sys.executable, "-I", str(script)],
        root=tmp_path,
        environment=catalog_module._accelerator_probe_environment(),
    )
    ready_deadline = time.monotonic() + 2.0
    while time.monotonic() < ready_deadline and not root_ready.exists():
        time.sleep(0.01)
    assert root_ready.exists()

    confirmed = catalog_module._terminate_accelerator_probe_process_tree(process)

    assert confirmed is True
    time.sleep(1.0)
    assert descendant_marker.exists() is False


def test_accelerator_reader_kills_child_after_2049_bytes(tmp_path) -> None:
    root_marker = tmp_path / "synthetic-overflow-root-survived"
    descendant_marker = tmp_path / "synthetic-overflow-descendant-survived"
    grandchild = (
        "import pathlib,time; time.sleep(1.5); "
        f"pathlib.Path({str(descendant_marker)!r}).write_text('unexpected','utf-8')"
    )
    script = tmp_path / "synthetic_oversized_probe.py"
    script.write_text(
        "import os,pathlib,subprocess,sys,time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"{grandchild!r}], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "try:\n"
        "    os.write(1, b'x' * (4 * 1024 * 1024))\n"
        "except OSError:\n"
        "    pass\n"
        f"pathlib.Path({str(root_marker)!r}).write_text('unexpected','utf-8')\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    try:
        output = catalog_module._read_bounded_accelerator_probe(
            [sys.executable, "-I", str(script)],
            root=tmp_path,
            environment=catalog_module._accelerator_probe_environment(),
            timeout_seconds=2.0,
        )
    except RuntimeError as error:
        assert os.name == "nt"
        assert str(error) == "accelerator_probe_cleanup_unconfirmed"
        output = None
    cleanup_elapsed = time.monotonic() - started

    assert output is None
    assert cleanup_elapsed < 4.0
    time.sleep(1.7)
    assert root_marker.exists() is False
    assert descendant_marker.exists() is False


def test_accelerator_reader_timeout_kills_the_synthetic_child_tree(
    tmp_path,
) -> None:
    root_marker = tmp_path / "synthetic-timeout-root-survived"
    descendant_marker = tmp_path / "synthetic-timeout-descendant-survived"
    grandchild = (
        "import pathlib,time; time.sleep(1.5); "
        f"pathlib.Path({str(descendant_marker)!r}).write_text('unexpected','utf-8')"
    )
    script = tmp_path / "synthetic_timeout_probe.py"
    script.write_text(
        "import pathlib,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(1.5)\n"
        f"pathlib.Path({str(root_marker)!r}).write_text('unexpected','utf-8')\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    try:
        output = catalog_module._read_bounded_accelerator_probe(
            [sys.executable, "-I", str(script)],
            root=tmp_path,
            environment=catalog_module._accelerator_probe_environment(),
            timeout_seconds=0.5,
        )
    except RuntimeError as error:
        assert os.name == "nt"
        assert str(error) == "accelerator_probe_cleanup_unconfirmed"
        output = None

    assert output is None
    time.sleep(1.7)
    assert root_marker.exists() is False
    assert descendant_marker.exists() is False


def test_runtime_inventory_cache_single_flights_concurrent_callers() -> None:
    cache = catalog_module._RuntimeInventoryCache(ttl_seconds=30.0)
    expected = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )
    loader_entered = Event()
    release_loader = Event()
    call_lock = Lock()
    calls = 0

    def loader() -> ModelRuntimeInventory:
        nonlocal calls
        with call_lock:
            calls += 1
        loader_entered.set()
        assert release_loader.wait(timeout=5)
        return expected

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cache.get, loader) for _ in range(8)]
        assert loader_entered.wait(timeout=5)
        release_loader.set()
        results = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert all(result is expected for result in results)


def test_runtime_inventory_cache_ttl_expiry_and_explicit_refresh() -> None:
    now = [100.0]
    cache = catalog_module._RuntimeInventoryCache(
        ttl_seconds=30.0,
        clock=lambda: now[0],
    )
    values = (
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="8_gib_class",
        ),
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="16_gib_class",
        ),
        inventory(
            ram_bucket=None,
            cuda_state=CudaInventoryState.UNKNOWN,
            cuda_bucket=None,
        ),
    )
    calls = 0

    def loader() -> ModelRuntimeInventory:
        nonlocal calls
        value = values[calls]
        calls += 1
        return value

    first = cache.get(loader)
    now[0] = 129.999
    within_ttl = cache.get(loader)
    now[0] = 130.0
    expired = cache.get(loader)
    refreshed = cache.get(loader, force_refresh=True)

    assert calls == 3
    assert within_ttl is first
    assert expired is values[1]
    assert refreshed is values[2]
    assert refreshed.cuda_state is CudaInventoryState.UNKNOWN
    assert refreshed.discovery_reason_codes == (
        HardwareDiscoveryReason.CUDA_INVENTORY_UNKNOWN,
        HardwareDiscoveryReason.SYSTEM_RAM_BUCKET_UNKNOWN,
    )


def test_runtime_and_compatibility_share_global_bucket_cache(monkeypatch) -> None:
    expected = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )
    calls = 0

    def discover() -> ModelRuntimeInventory:
        nonlocal calls
        calls += 1
        return expected

    monkeypatch.setattr(catalog_module, "discover_runtime_inventory", discover)
    catalog_module._RUNTIME_INVENTORY_CACHE.clear()
    service = LocalTextModelEvaluationService()
    try:
        runtime = service.inventory()
        catalog = service.compatibility_catalog()
        refreshed = service.inventory(force_refresh=True)
    finally:
        catalog_module._RUNTIME_INVENTORY_CACHE.clear()

    assert runtime is expected
    assert catalog.inventory is expected
    assert refreshed is expected
    assert calls == 2


def test_catalog_contract_contains_no_sensitive_identity_or_execution_controls() -> None:
    catalog = build_model_compatibility_catalog(
        inventory(
            ram_bucket="16_gib_class",
            cuda_state=CudaInventoryState.AVAILABLE,
            cuda_bucket="8_gib_class",
        )
    )
    serialized = repr(asdict(catalog)).casefold()

    for forbidden in (
        "username",
        "hostname",
        "serial_number",
        "home_path",
        "cache_path",
        "session_id",
        "prompt_text",
        "hf_token",
    ):
        assert forbidden not in serialized
    assert catalog.local_only is True
    assert catalog.persisted is False
    assert catalog.synced is False
    assert all(item.trust_remote_code is False for item in catalog.models)


def _subprocess_environment() -> dict[str, str]:
    environment = {
        "PYTHONPATH": "src",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def test_specialist_manifest_imports_in_a_clean_subprocess() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import prompt_enhancer.infrastructure.specialist_screen.manifests",
        ],
        cwd=ROOT,
        env=_subprocess_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == b""
    assert completed.stderr == b""


def test_specialist_cli_smoke_is_network_closed_and_import_safe() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_specialist_screen.py", "--smoke"],
        cwd=ROOT,
        env=_subprocess_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )

    assert completed.returncode in {0, 2}
    report = json.loads(completed.stdout.decode("utf-8"))
    assert report["synthetic_only"] is True
    assert report["activation_allowed"] is False
    assert report["promotion_allowed"] is False
    assert "download" not in report


def test_authenticated_api_is_get_only_private_bucketed_and_nonpromotional(
    tmp_path,
) -> None:
    fixed_inventory = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )

    class FixedInventoryService(LocalTextModelEvaluationService):
        def inventory(self) -> ModelRuntimeInventory:
            return fixed_inventory

    database = Database(tmp_path / "compatibility.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=database,
        api_token=TOKEN,
        model_evaluation_service=FixedInventoryService(),
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    with client:
        unauthorized = client.get("/v1/research/text-model-compatibility")
        response = client.get(
            "/v1/research/text-model-compatibility",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        runtime_response = client.get(
            "/v1/research/text-model-runtime",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        mutation = client.post(
            "/v1/research/text-model-compatibility",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert runtime_response.status_code == 200
    assert mutation.status_code == 405
    assert response.headers["cache-control"] == "no-store, private"
    assert runtime_response.headers["cache-control"] == "no-store, private"
    body = response.json()
    assert body["catalog_policy"] == "exploratory_resource_fit_only"
    assert body["local_only"] is True
    assert body["persisted"] is False
    assert body["synced"] is False
    assert body["inventory"]["sensitivity"] == "sensitive_derived"
    assert body["inventory"]["model_child_gpu_allocation_ceiling_mib"] == 6_144
    assert body["inventory"]["model_child_rss_ceiling_mib"] == 8_192
    serialized = response.text.casefold()
    for forbidden in (
        "validated",
        "recommended",
        "selected",
        "logical_core_count",
        "system_ram_mib",
        "cuda_memory_mb",
        "cuda_compute_capability",
        "model_cache_free_disk_mib",
    ):
        assert forbidden not in serialized


def test_registry_divergence_is_fixed_typed_unavailable(
    monkeypatch, tmp_path
) -> None:
    fixed_inventory = inventory(
        ram_bucket="16_gib_class",
        cuda_state=CudaInventoryState.AVAILABLE,
        cuda_bucket="8_gib_class",
    )

    class FixedInventoryService(LocalTextModelEvaluationService):
        def inventory(self) -> ModelRuntimeInventory:
            return fixed_inventory

    monkeypatch.setattr(catalog_module, "_REVIEWED_CONFIGURATIONS", ())
    with pytest.raises(
        ModelCompatibilityCatalogUnavailableError,
        match="^model_compatibility_catalog_unavailable$",
    ):
        build_model_compatibility_catalog(fixed_inventory)

    database = Database(tmp_path / "registry-divergence.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "registry-divergence-home"),
        database=database,
        api_token=TOKEN,
        model_evaluation_service=FixedInventoryService(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/research/text-model-compatibility",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "detail": {"code": "model_compatibility_catalog_unavailable"}
    }


def test_compatibility_openapi_has_no_mutation_or_activation_capability(tmp_path) -> None:
    database = Database(tmp_path / "schema.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "schema-home"),
        database=database,
        api_token=TOKEN,
        model_evaluation_service=LocalTextModelEvaluationService(),
    )
    schema = app.openapi()

    assert set(schema["paths"]["/v1/research/text-model-compatibility"]) == {"get"}
    unavailable = schema["paths"]["/v1/research/text-model-compatibility"][
        "get"
    ]["responses"]["503"]["content"]["application/json"]["schema"]
    assert unavailable == {
        "$ref": "#/components/schemas/ModelCompatibilityUnavailableResponseDto"
    }
    catalog = schema["components"]["schemas"]["ModelCompatibilityCatalogDto"]
    model = schema["components"]["schemas"]["ModelCompatibilityEntryDto"]
    inventory_schema = schema["components"]["schemas"]["ModelRuntimeInventoryDto"]
    assert catalog["additionalProperties"] is False
    assert model["additionalProperties"] is False
    assert catalog["properties"]["activation_allowed"]["const"] is False
    assert model["properties"]["activation_allowed"]["const"] is False
    assert model["properties"]["download_allowed"]["const"] is False
    assert model["properties"]["trust_remote_code"]["const"] is False
    assert inventory_schema["properties"]["persisted"]["const"] is False
