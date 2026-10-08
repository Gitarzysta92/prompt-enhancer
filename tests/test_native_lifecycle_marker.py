"""Content-free native lifecycle marker regressions with synthetic state only."""

from __future__ import annotations

import json

import pytest

from prompt_enhancer.application.runtime_lifecycle import RuntimeComponent
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.native_lifecycle import (
    MAX_NATIVE_LIFECYCLE_BYTES,
    NATIVE_LIFECYCLE_CONTRACT,
    NativeLifecycleMarker,
    NativeLifecycleMarkerError,
    NativeWindowKind,
)
from prompt_enhancer.privacy import (
    PrivacyBoundaryError,
    write_private_text_atomic,
)


def _payload(path):
    encoded = path.read_bytes()
    assert len(encoded) <= MAX_NATIVE_LIFECYCLE_BYTES
    return json.loads(encoded.decode("utf-8"))


def test_marker_records_only_fixed_phases_and_a_clean_terminal_outcome(tmp_path) -> None:
    path = tmp_path / "diagnostics" / "native-agent-lifecycle.json"
    marker = NativeLifecycleMarker(path, NativeWindowKind.AGENT)

    marker.start()
    assert _payload(path) == {
        "cleanup_reason_code": None,
        "components": [],
        "contract": NATIVE_LIFECYCLE_CONTRACT,
        "phase": "starting",
        "previous": {"outcome": "absent", "phase": None},
        "reason_code": None,
        "terminal": False,
        "window": "agent",
    }
    marker.service_ready()
    marker.window_created()
    marker.window_closed()
    marker.stopped()

    terminal = _payload(path)
    assert terminal["phase"] == "stopped"
    assert terminal["terminal"] is True
    assert terminal["reason_code"] is None
    assert str(tmp_path) not in path.read_text(encoding="utf-8")

    following = NativeLifecycleMarker(path, NativeWindowKind.AGENT)
    following.start()
    assert _payload(path)["previous"] == {"outcome": "stopped", "phase": "stopped"}


def test_marker_carries_forward_a_nonterminal_previous_phase_as_interrupted(tmp_path) -> None:
    path = tmp_path / "diagnostics" / "native-agent-lifecycle.json"
    interrupted = NativeLifecycleMarker(path, NativeWindowKind.AGENT)
    interrupted.start()
    interrupted.service_ready()

    replacement = NativeLifecycleMarker(path, NativeWindowKind.AGENT)
    replacement.start()

    assert _payload(path)["previous"] == {
        "outcome": "interrupted",
        "phase": "service_ready",
    }


def test_marker_rejects_invalid_order_without_overwriting_last_evidence(tmp_path) -> None:
    path = tmp_path / "diagnostics" / "native-agent-lifecycle.json"
    marker = NativeLifecycleMarker(path, NativeWindowKind.AGENT)
    marker.start()

    with pytest.raises(NativeLifecycleMarkerError, match="invalid native lifecycle"):
        marker.window_created()

    assert _payload(path)["phase"] == "starting"


def test_failure_marker_filters_arbitrary_codes_and_components(tmp_path) -> None:
    path = tmp_path / "diagnostics" / "native-overlay-lifecycle.json"
    marker = NativeLifecycleMarker(path, NativeWindowKind.OVERLAY)
    marker.start()
    marker.failed(
        "SYNTHETIC_PRIVATE_REASON_CANARY",
        components=(
            RuntimeComponent.LOCAL_MODEL_SERVICE,
            "SYNTHETIC_PRIVATE_COMPONENT_CANARY",  # type: ignore[arg-type]
        ),
        cleanup_reason_code="SYNTHETIC_PRIVATE_CLEANUP_CANARY",
    )

    payload = _payload(path)
    assert payload["reason_code"] == "desktop_failed"
    assert payload["cleanup_reason_code"] is None
    assert payload["components"] == ["local_model_service"]
    assert "SYNTHETIC_PRIVATE" not in path.read_text(encoding="utf-8")


def test_invalid_previous_content_becomes_unknown_without_being_copied(tmp_path) -> None:
    path = tmp_path / "diagnostics" / "native-agent-lifecycle.json"
    write_private_text_atomic(path, '{"private":"SYNTHETIC_PRIVATE_PREVIOUS_CANARY"}')

    marker = NativeLifecycleMarker(path, NativeWindowKind.AGENT)
    marker.start()

    payload = _payload(path)
    assert payload["previous"] == {"outcome": "unknown", "phase": None}
    assert "SYNTHETIC_PRIVATE" not in path.read_text(encoding="utf-8")


def test_atomic_private_replace_preserves_prior_record_on_replace_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from prompt_enhancer import privacy

    path = tmp_path / "diagnostics" / "marker.json"
    write_private_text_atomic(path, "first-fixed-record")

    def fail_replace(*_args) -> None:
        raise OSError("SYNTHETIC_PRIVATE_REPLACE_CANARY")

    monkeypatch.setattr(privacy.os, "replace", fail_replace)
    with pytest.raises(PrivacyBoundaryError, match="atomically write") as caught:
        write_private_text_atomic(path, "second-fixed-record")

    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert path.read_text(encoding="utf-8") == "first-fixed-record\n"
    assert list(path.parent.glob("*.tmp")) == []


def test_settings_keep_agent_and_overlay_markers_separate(tmp_path) -> None:
    settings = AppSettings(home=tmp_path)

    assert settings.native_agent_lifecycle_path == (
        tmp_path / "diagnostics" / "native-agent-lifecycle.json"
    )
    assert settings.native_overlay_lifecycle_path == (
        tmp_path / "diagnostics" / "native-overlay-lifecycle.json"
    )
