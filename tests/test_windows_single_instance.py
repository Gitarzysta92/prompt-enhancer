from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from types import SimpleNamespace

import pytest

from prompt_enhancer.infrastructure import windows_single_instance as single


class _Kernel:
    def __init__(self, *, handle: int = 41, closes: bool = True) -> None:
        self.handle = handle
        self.closes = closes
        self.created: list[tuple[object, bool, str]] = []
        self.closed: list[int] = []

    def CreateMutexW(self, security: object, owned: bool, name: str) -> int:
        self.created.append((security, owned, name))
        return self.handle

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return self.closes


def test_primary_lease_is_released_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(single.sys, "platform", "win32")
    kernel = _Kernel()
    resets: list[int] = []

    lease = single.acquire_windows_instance(
        "Local\\PromptEnhancer.SyntheticPrimary.v1",
        kernel=kernel,
        get_last_error=lambda: 0,
        set_last_error=resets.append,
    )

    assert lease is not None
    assert kernel.created == [(None, False, "Local\\PromptEnhancer.SyntheticPrimary.v1")]
    assert resets == [0]
    assert kernel.closed == []
    lease.close()
    lease.close()
    assert kernel.closed == [41]


def test_duplicate_is_closed_and_never_returns_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(single.sys, "platform", "win32")
    kernel = _Kernel(handle=52)

    lease = single.acquire_windows_instance(
        "Local\\PromptEnhancer.SyntheticDuplicate.v1",
        kernel=kernel,
        get_last_error=lambda: single.ERROR_ALREADY_EXISTS,
        set_last_error=lambda _value: None,
    )

    assert lease is None
    assert kernel.closed == [52]


@pytest.mark.parametrize(
    ("kernel", "last_error"),
    [
        (_Kernel(handle=0), 0),
        (_Kernel(handle=63, closes=False), single.ERROR_ALREADY_EXISTS),
    ],
)
def test_acquire_failures_are_fixed_and_content_free(
    monkeypatch: pytest.MonkeyPatch,
    kernel: _Kernel,
    last_error: int,
) -> None:
    monkeypatch.setattr(single.sys, "platform", "win32")

    with pytest.raises(single.WindowsSingleInstanceError) as caught:
        single.acquire_windows_instance(
            "Local\\PromptEnhancer.SyntheticFailure.v1",
            kernel=kernel,
            get_last_error=lambda: last_error,
            set_last_error=lambda _value: None,
        )

    assert str(caught.value) in {
        "single_instance_acquire_failed",
        "single_instance_release_failed",
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_invalid_names_and_non_windows_callers_never_touch_native_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _Kernel()
    monkeypatch.setattr(single.sys, "platform", "linux")
    with pytest.raises(single.WindowsSingleInstanceError, match="platform_unsupported"):
        single.acquire_windows_instance("Local\\PromptEnhancer.Synthetic.v1", kernel=kernel)
    assert kernel.created == []

    monkeypatch.setattr(single.sys, "platform", "win32")
    with pytest.raises(single.WindowsSingleInstanceError, match="name_invalid"):
        single.acquire_windows_instance("example", kernel=kernel)
    assert kernel.created == []


def test_focus_waits_for_exact_window_then_restores_and_activates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(single.sys, "platform", "win32")
    clock = SimpleNamespace(value=0.0)
    calls: list[tuple[str, object]] = []
    windows = iter((0, 0, 77))

    class _User:
        def FindWindowW(self, class_name: object, title: str) -> int:
            calls.append(("find", (class_name, title)))
            return next(windows)

        def IsIconic(self, window: int) -> bool:
            calls.append(("iconic", window))
            return True

        def ShowWindow(self, window: int, action: int) -> bool:
            calls.append(("show", (window, action)))
            return True

        def SetForegroundWindow(self, window: int) -> bool:
            calls.append(("focus", window))
            return True

    def advance(seconds: float) -> None:
        clock.value += seconds

    assert single.focus_existing_window(
        "Prompt Enhancer - Agent workspace",
        timeout_seconds=1,
        poll_seconds=0.1,
        user=_User(),
        monotonic=lambda: clock.value,
        sleep=advance,
    ) is True
    assert calls[-3:] == [
        ("iconic", 77),
        ("show", (77, single.SW_RESTORE)),
        ("focus", 77),
    ]


def test_focus_timeout_is_bounded_and_never_launches_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(single.sys, "platform", "win32")
    clock = SimpleNamespace(value=0.0)
    finds = 0

    class _User:
        def FindWindowW(self, _class_name: object, _title: str) -> int:
            nonlocal finds
            finds += 1
            return 0

    assert single.focus_existing_window(
        "Prompt Enhancer - Agent workspace",
        timeout_seconds=0.2,
        poll_seconds=0.05,
        user=_User(),
        monotonic=lambda: clock.value,
        sleep=lambda seconds: setattr(clock, "value", clock.value + seconds),
    ) is False
    assert 2 <= finds <= 6
    assert clock.value == pytest.approx(0.2)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex contract")
def test_real_named_mutex_excludes_a_hidden_child_then_releases() -> None:
    name = f"Local\\PromptEnhancer.SyntheticProbe.{secrets.token_hex(8)}"
    lease = single.acquire_windows_instance(name)
    assert lease is not None
    probe = Path(__file__).parent / "support" / "windows_single_instance_probe.py"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    first = subprocess.run(
        [sys.executable, str(probe), name],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=flags,
        check=False,
        env=environment,
    )
    assert first.returncode == 0
    assert json.loads(first.stdout) == {
        "contract": "windows-single-instance-probe.v1",
        "primary": False,
    }

    lease.close()
    second = subprocess.run(
        [sys.executable, str(probe), name],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=flags,
        check=False,
        env=environment,
    )
    assert second.returncode == 0
    assert json.loads(second.stdout) == {
        "contract": "windows-single-instance-probe.v1",
        "primary": True,
    }
