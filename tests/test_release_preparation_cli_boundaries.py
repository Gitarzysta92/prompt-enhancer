from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_frontend_dependencies as frontend_cli
from scripts import prepare_proxy_tools_wheel as proxy_cli
from scripts import prepare_windows_dependencies as windows_cli
from prompt_enhancer.infrastructure.frontend_dependency_preparation import (
    FrontendDependencyPreparationError,
)
from prompt_enhancer.infrastructure.proxy_tools_wheel_preparation import (
    ProxyToolsWheelPreparationError,
)
from prompt_enhancer.infrastructure.windows_dependency_preparation import (
    WindowsDependencyPreparationError,
    WindowsDependencyPreparationReport,
)
from prompt_enhancer.infrastructure.windows_wheel_inventory import WindowsWheelTarget


FRONTEND_ARGUMENTS = [
    "--frontend-root", "C:/example/frontend",
    "--source-manifest", "C:/example/source.json",
    "--source-manifest-size", "101",
    "--source-manifest-sha256", "1" * 64,
    "--node-executable", "C:/example/node.exe",
    "--node-size", "202",
    "--node-sha256", "2" * 64,
    "--node-version", "v22.1.0",
    "--npm-root", "C:/example/npm",
    "--npm-manifest", "C:/example/npm.json",
    "--npm-manifest-size", "303",
    "--npm-manifest-sha256", "3" * 64,
    "--npm-version", "10.1.0",
    "--destination", "C:/example/output",
]

PROXY_ARGUMENTS = [
    "--source-archive", "C:/example/proxy.tar.gz",
    "--python-executable", "C:/example/python.exe",
    "--python-sha256", "4" * 64,
    "--python-size-bytes", "404",
    "--python-version", "3.13.1",
    "--setuptools-wheel", "C:/example/setuptools.whl",
    "--destination", "C:/example/wheel-output",
]

WINDOWS_ARGUMENTS = [
    "--python-full-version", "3.13.1",
    "--architecture", "amd64",
    "--repository-root", "C:/example/repository",
]


def _proxy_result() -> SimpleNamespace:
    return SimpleNamespace(
        filename="proxy_tools-0.1.0-py3-none-any.whl",
        license_discrepancy_review_required=True,
        network_isolation_not_proven=True,
        python_sha256="4" * 64,
        python_size_bytes=404,
        python_version="3.13.1",
        python_runtime_dependencies_not_pinned=True,
        setuptools_sha256="5" * 64,
        setuptools_size_bytes=505,
        setuptools_version="84.0.0",
        sha256="6" * 64,
        size_bytes=606,
        source_date_epoch="1399328544",
        source_sha256="7" * 64,
        source_size_bytes=707,
    )


def test_frontend_cli_forwards_every_argument_and_preserves_limitations(monkeypatch, capsys):
    captured = {}
    receipt = {
        "contract": "frontend-dependency-preparation.v1",
        "independent_tarball_byte_proof": False,
        "licence_closure_claimed": False,
        "release_accepted": False,
    }

    def prepare(**kwargs):
        captured.update(kwargs)
        return receipt

    monkeypatch.setattr(frontend_cli, "prepare_frontend_dependencies", prepare)

    assert frontend_cli.main(FRONTEND_ARGUMENTS) == 0
    assert captured == {
        "frontend_root": Path("C:/example/frontend"),
        "source_manifest": Path("C:/example/source.json"),
        "source_manifest_size": 101,
        "source_manifest_sha256": "1" * 64,
        "node_executable": Path("C:/example/node.exe"),
        "node_size": 202,
        "node_sha256": "2" * 64,
        "node_version": "v22.1.0",
        "npm_root": Path("C:/example/npm"),
        "npm_manifest": Path("C:/example/npm.json"),
        "npm_manifest_size": 303,
        "npm_manifest_sha256": "3" * 64,
        "npm_version": "10.1.0",
        "destination": Path("C:/example/output"),
    }
    streams = capsys.readouterr()
    assert json.loads(streams.out) == receipt
    assert streams.err == ""


def test_windows_cli_forwards_every_argument_and_preserves_limitations(monkeypatch, capsys):
    exported = object()
    captured = {}
    report = WindowsDependencyPreparationReport(
        target=WindowsWheelTarget("3.13.1", "arm64"), registry_wheels=(),
        source_build_requirements=(), prepared_source_wheels=(),
        pyproject_sha256="1" * 64, lockfile_sha256="2" * 64,
        export_fingerprint="3" * 64, registry_export_fingerprint="4" * 64,
        unresolved_blockers=("example_review_required",), complete=False,
        release_accepted=False,
    )

    monkeypatch.setattr(
        windows_cli, "export_windows_desktop_requirements",
        lambda *, repository_root: exported if repository_root == Path("C:/example/repository") else None,
    )

    def prepare(**kwargs):
        captured.update(kwargs)
        return report

    monkeypatch.setattr(windows_cli, "prepare_windows_dependencies", prepare)
    arguments = [
        "--python-full-version", "3.13.1", "--architecture", "arm64",
        "--repository-root", "C:/example/repository",
        "--proxy-tools-wheel", "C:/example/proxy.whl",
        "--proxy-tools-provenance", "C:/example/provenance.json",
    ]

    assert windows_cli.main(arguments) == 0
    assert captured == {
        "export": exported,
        "lockfile": Path("C:/example/repository") / "uv.lock",
        "target": WindowsWheelTarget("3.13.1", "arm64"),
        "proxy_tools_wheel": Path("C:/example/proxy.whl"),
        "proxy_tools_provenance": Path("C:/example/provenance.json"),
    }
    streams = capsys.readouterr()
    output = json.loads(streams.out)
    assert streams.err == ""
    assert output["complete"] is False
    assert output["release_accepted"] is False
    assert output["unresolved_blockers"] == ["example_review_required"]


def test_proxy_cli_forwards_every_argument_and_preserves_limitations(monkeypatch, capsys):
    captured = {}

    def prepare(**kwargs):
        captured.update(kwargs)
        return _proxy_result()

    monkeypatch.setattr(proxy_cli, "prepare_proxy_tools_wheel", prepare)

    assert proxy_cli.main(PROXY_ARGUMENTS) == 0
    assert captured == {
        "source_archive": Path("C:/example/proxy.tar.gz"),
        "python_executable": Path("C:/example/python.exe"),
        "python_sha256": "4" * 64,
        "python_size_bytes": 404,
        "python_version": "3.13.1",
        "setuptools_wheel": Path("C:/example/setuptools.whl"),
        "destination": Path("C:/example/wheel-output"),
    }
    streams = capsys.readouterr()
    output = json.loads(streams.out)
    assert streams.err == ""
    assert output["license_discrepancy_review_required"] is True
    assert output["network_isolation_not_proven"] is True
    assert output["python_runtime_dependencies_not_pinned"] is True


@pytest.mark.parametrize(
    ("module", "arguments", "service_name", "failure", "option", "abbreviation"),
    [
        (frontend_cli, FRONTEND_ARGUMENTS, "prepare_frontend_dependencies",
         "frontend_dependency_preparation_failed", "--frontend-root", "--frontend-r"),
        (windows_cli, WINDOWS_ARGUMENTS, "prepare_windows_dependencies",
         "windows_dependency_preparation_failed", "--repository-root", "--repository-r"),
        (proxy_cli, PROXY_ARGUMENTS, "prepare_proxy_tools_wheel",
         "proxy_tools_wheel_preparation_failed", "--source-archive", "--source-a"),
    ],
)
def test_cli_rejects_abbreviated_options_without_invoking_service_or_echoing_input(
        monkeypatch, capsys, module, arguments, service_name, failure, option, abbreviation):
    invoked = False

    def service(**_kwargs):
        nonlocal invoked
        invoked = True
        return _proxy_result() if module is proxy_cli else {}

    monkeypatch.setattr(module, service_name, service)
    if module is windows_cli:
        def export(**_kwargs):
            nonlocal invoked
            invoked = True
            return object()

        monkeypatch.setattr(module, "export_windows_desktop_requirements", export)
        monkeypatch.setattr(module, "report_json", lambda _report: "{}")
    private_like_value = "EXAMPLE_PRIVATE_VALUE_DO_NOT_ECHO"
    changed = list(arguments)
    option_index = changed.index(option)
    changed[option_index:option_index + 2] = [abbreviation, private_like_value]

    expected_status = 1 if module is frontend_cli else 2
    assert module.main(changed) == expected_status
    captured = capsys.readouterr()
    assert not invoked
    if module is frontend_cli:
        assert captured.out == '{"passed": false, "error_code": "dependency_cli_invalid"}\n'
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert captured.err == failure + "\n"
    assert private_like_value not in captured.out + captured.err


@pytest.mark.parametrize(
    ("module", "arguments", "service_name", "failure"),
    [
        (frontend_cli, FRONTEND_ARGUMENTS, "prepare_frontend_dependencies",
         "frontend_dependency_preparation_failed"),
        (windows_cli, WINDOWS_ARGUMENTS, "prepare_windows_dependencies",
         "windows_dependency_preparation_failed"),
        (proxy_cli, PROXY_ARGUMENTS, "prepare_proxy_tools_wheel",
         "proxy_tools_wheel_preparation_failed"),
    ],
)
@pytest.mark.parametrize("case", ["unknown", "malformed"])
def test_cli_rejects_unknown_and_malformed_input_without_invoking_service_or_echoing_input(
        monkeypatch, capsys, module, arguments, service_name, failure, case):
    invoked = False

    def service(**_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(module, service_name, service)
    if module is windows_cli:
        def export(**_kwargs):
            nonlocal invoked
            invoked = True
            return object()

        monkeypatch.setattr(module, "export_windows_desktop_requirements", export)
    private_like_value = "EXAMPLE_PRIVATE_INVALID_DO_NOT_ECHO"
    changed = list(arguments)
    if case == "unknown":
        changed.extend(["--example-private-unknown", private_like_value])
    else:
        malformed_option = {
            frontend_cli: "--node-size",
            windows_cli: "--architecture",
            proxy_cli: "--python-size-bytes",
        }[module]
        changed[changed.index(malformed_option) + 1] = private_like_value

    expected_status = 1 if module is frontend_cli else 2
    assert module.main(changed) == expected_status
    captured = capsys.readouterr()
    assert not invoked
    if module is frontend_cli:
        assert captured.out == '{"passed": false, "error_code": "dependency_cli_invalid"}\n'
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert captured.err == failure + "\n"
    assert private_like_value not in captured.out + captured.err


@pytest.mark.parametrize(
    ("module", "arguments", "service_name", "error_type", "failure"),
    [
        (frontend_cli, FRONTEND_ARGUMENTS, "prepare_frontend_dependencies",
         FrontendDependencyPreparationError, "frontend_dependency_preparation_failed"),
        (windows_cli, ["--python-full-version", "3.13.1", "--architecture", "amd64"],
         "export_windows_desktop_requirements", WindowsDependencyPreparationError,
         "windows_dependency_preparation_failed"),
        (proxy_cli, PROXY_ARGUMENTS, "prepare_proxy_tools_wheel",
         ProxyToolsWheelPreparationError, "proxy_tools_wheel_preparation_failed"),
    ],
)
@pytest.mark.parametrize("unexpected", [False, True])
def test_cli_contains_known_and_unexpected_failures(
        monkeypatch, capsys, module, arguments, service_name, error_type, failure, unexpected):
    private_like_value = "EXAMPLE_PRIVATE_EXCEPTION_DO_NOT_ECHO"
    known_code = "dependency_install_failed" if module is frontend_cli else private_like_value
    raised = RuntimeError(private_like_value) if unexpected else error_type(known_code)

    def fail(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(module, service_name, fail)

    expected_status = 1 if module is frontend_cli else 2
    assert module.main(arguments) == expected_status
    captured = capsys.readouterr()
    if module is frontend_cli:
        expected_code = "dependency_preparation_failed" if unexpected else known_code
        assert captured.out == f'{{"passed": false, "error_code": "{expected_code}"}}\n'
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert captured.err == failure + "\n"
    assert private_like_value not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_frontend_cli_contains_unhashable_domain_error_argument(monkeypatch, capsys):
    def fail(**_kwargs):
        raise FrontendDependencyPreparationError(["EXAMPLE_PRIVATE_UNHASHABLE_DO_NOT_ECHO"])

    monkeypatch.setattr(frontend_cli, "prepare_frontend_dependencies", fail)

    assert frontend_cli.main(FRONTEND_ARGUMENTS) == 1
    captured = capsys.readouterr()
    assert captured.out == '{"passed": false, "error_code": "dependency_preparation_failed"}\n'
    assert captured.err == ""
    assert "EXAMPLE_PRIVATE_UNHASHABLE_DO_NOT_ECHO" not in captured.out


@pytest.mark.parametrize(
    ("module", "arguments", "service_name", "service_result", "serializer_name", "failure"),
    [
        (frontend_cli, FRONTEND_ARGUMENTS, "prepare_frontend_dependencies", {}, "json.dumps",
         "frontend_dependency_preparation_failed"),
        (windows_cli, ["--python-full-version", "3.13.1", "--architecture", "amd64"],
         "prepare_windows_dependencies", object(), "report_json",
         "windows_dependency_preparation_failed"),
        (proxy_cli, PROXY_ARGUMENTS, "prepare_proxy_tools_wheel", _proxy_result(), "json.dumps",
         "proxy_tools_wheel_preparation_failed"),
    ],
)
def test_cli_contains_serialization_failures_without_partial_success_output(
        monkeypatch, capsys, module, arguments, service_name, service_result, serializer_name, failure):
    if module is windows_cli:
        monkeypatch.setattr(module, "export_windows_desktop_requirements", lambda **_kwargs: object())
    monkeypatch.setattr(module, service_name, lambda **_kwargs: service_result)

    def fail_serialization(*_args, **_kwargs):
        raise RuntimeError("EXAMPLE_PRIVATE_SERIALIZATION_DO_NOT_ECHO")

    if serializer_name == "json.dumps":
        monkeypatch.setattr(module, "json", SimpleNamespace(dumps=fail_serialization))
    else:
        monkeypatch.setattr(module, serializer_name, fail_serialization)

    expected_status = 1 if module is frontend_cli else 2
    assert module.main(arguments) == expected_status
    captured = capsys.readouterr()
    if module is frontend_cli:
        assert captured.out == '{"passed": false, "error_code": "dependency_preparation_failed"}\n'
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert captured.err == failure + "\n"
    assert "Traceback" not in captured.out + captured.err
