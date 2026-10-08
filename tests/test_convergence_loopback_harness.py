"""Static safety guardrails for the production-build loopback browser gate."""

from __future__ import annotations

from pathlib import Path
import os
import re

from tests.support.convergence_loopback_runner import _repository_python


REPOSITORY = Path(__file__).resolve().parents[1]
FRONTEND = REPOSITORY / "frontend"
LOOPBACK_SPEC = FRONTEND / "e2e" / "loopback-built.spec.ts"
INTERCEPTED_SPEC = FRONTEND / "e2e" / "intercepted-contract.spec.ts"
LOOPBACK_CONFIG = FRONTEND / "playwright.loopback.config.ts"
RUNNER = REPOSITORY / "tests" / "support" / "convergence_loopback_runner.py"


def test_loopback_browser_gate_cannot_intercept_application_routes() -> None:
    source = LOOPBACK_SPEC.read_text(encoding="utf-8")

    assert len(re.findall(r"^\s*test\(\"", source, flags=re.MULTILINE)) >= 12
    for forbidden in (
        "page.route(",
        "context.route(",
        "routeFromHAR",
        "setContent(",
        "createSyntheticTransport",
    ):
        assert forbidden not in source


def test_loopback_config_requires_an_owned_origin_and_starts_no_web_server() -> None:
    source = LOOPBACK_CONFIG.read_text(encoding="utf-8")

    assert "PE_CONVERGENCE_BASE_URL" in source
    assert "127\\.0\\.0\\.1" in source
    assert "loopback-built.spec.ts" in source
    assert "webServer" not in source
    assert "retries: 0" in source
    assert "workers: 1" in source


def test_intercepted_contract_suite_is_named_for_what_it_proves() -> None:
    assert not (FRONTEND / "e2e" / "local-real.spec.ts").exists()
    assert not (FRONTEND / "playwright.local.config.ts").exists()
    assert "page.route(" in INTERCEPTED_SPEC.read_text(encoding="utf-8")
    package = (FRONTEND / "package.json").read_text(encoding="utf-8")
    assert "test:e2e:intercepted" in package
    assert "test:e2e:local" not in package


def test_runner_is_isolated_and_never_opens_child_console_windows() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert "TemporaryDirectory" in source
    assert "session_reader_enabled=False" in source
    assert "CodexInstalledSchemaProbe.probe" in source
    assert "create_codex_adapter = staticmethod(provider_access_forbidden)" in source
    assert "CREATE_NO_WINDOW" in source
    assert "shell=False" in source
    assert "model_runtimes_remaining" in source
    assert "temporary_state_removed" in source


def test_runner_finds_a_repository_virtual_environment_without_activation(
    tmp_path: Path,
) -> None:
    relative = (
        Path(".venv") / "Scripts" / "python.exe"
        if os.name == "nt"
        else Path(".venv") / "bin" / "python"
    )
    interpreter = tmp_path / relative
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"")

    assert _repository_python(tmp_path) == interpreter
