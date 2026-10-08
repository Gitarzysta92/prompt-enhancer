"""Store-05b: adversarial synthetic MCPB installation boundaries."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import zipfile

from pydantic import SecretStr
import pytest

from prompt_enhancer.application.mcp_guarded_host import (
    McpGuardedHostError,
    McpHostProbeResult,
)
from prompt_enhancer.application.mcp_local_packages import (
    McpLocalPackageInstallerError,
    McpLocalPackageLaunchExpectation,
)
from prompt_enhancer.application.mcp_registry_catalog import (
    McpRegistryResolvedLocalEnvironment,
    McpRegistryResolvedLocalPackage,
)
from prompt_enhancer.infrastructure.mcp_package_installer import (
    MAX_MCPB_ARTIFACT_BYTES,
    McpbPackageInstaller,
)


MANAGEMENT_ID = "9" * 32
UNINSTALL_ID = "8" * 32
UPDATE_ID = "7" * 32


def _manifest(**overrides) -> dict[str, object]:  # noqa: ANN003
    value: dict[str, object] = {
        "manifest_version": "0.3",
        "name": "synthetic-mcpb",
        "version": "1.0.0",
        "description": "A fictional local MCP server used only in tests.",
        "author": {"name": "Example Publisher"},
        "license": "MIT",
        "server": {
            "type": "binary",
            "entry_point": "server/synthetic.exe",
            "mcp_config": {
                "command": "server/synthetic.exe",
                "args": ["--fixture", "data/example.json"],
                "env": {"EXAMPLE_MODE": "synthetic"},
            },
        },
    }
    value.update(overrides)
    return value


def _archive(
    *,
    manifest: dict[str, object] | None = None,
    extra: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest or _manifest(), separators=(",", ":")),
        )
        executable = zipfile.ZipInfo("server/synthetic.exe")
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(executable, b"synthetic executable fixture")
        archive.writestr("data/example.json", b'{"fixture":true}\n')
        for name, payload in extra:
            archive.writestr(name, payload)
    return output.getvalue()


def _package(
    payload: bytes,
    *,
    version: str = "1.0.0",
    runtime_arguments: tuple[SecretStr, ...] = (),
    package_arguments: tuple[SecretStr, ...] = (),
    environment: tuple[McpRegistryResolvedLocalEnvironment, ...] = (),
) -> McpRegistryResolvedLocalPackage:
    return McpRegistryResolvedLocalPackage(
        catalog_id="1" * 32,
        option_id="2" * 32,
        plan_revision="3" * 64,
        package_identifier=SecretStr(
            "https://github.com/example/synthetic/releases/download/"
            f"v{version}/synthetic.mcpb"
        ),
        package_version=version,
        file_sha256=hashlib.sha256(payload).hexdigest(),
        runtime_arguments=runtime_arguments,
        package_arguments=package_arguments,
        environment=environment,
    )


class _Downloader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[int] = []

    def fetch(self, url: SecretStr, *, maximum_bytes: int) -> bytes:
        assert url.get_secret_value().endswith("synthetic.mcpb")
        self.calls.append(maximum_bytes)
        return self.payload


class _Host:
    def __init__(self) -> None:
        self.connections = []
        self.error: McpGuardedHostError | None = None
        self.mutate_tree = False

    def probe(self, connection):  # noqa: ANN001
        self.connections.append(connection)
        if self.error is not None:
            raise self.error
        if self.mutate_tree:
            Path(connection.working_directory, "probe-created.txt").write_text(
                "synthetic mutation",
                encoding="utf-8",
            )
        return McpHostProbeResult(
            transport="stdio",
            protocol_version="2026-07-28",
            tool_count=2,
            schema_digest="a" * 64,
            elapsed_ms=35,
            process_started=True,
            process_tree_cleanup="verified",
        )


def _installer(tmp_path: Path, payload: bytes, host: _Host | None = None):
    downloader = _Downloader(payload)
    observed = host or _Host()
    return (
        McpbPackageInstaller(tmp_path / "mcp-packages", downloader, observed),
        downloader,
        observed,
    )


def test_mcpb_is_verified_probed_published_and_rollback_is_digest_bound(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, downloader, host = _installer(tmp_path, payload)

    result = installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)

    assert result.artifact_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.artifact_bytes == len(payload)
    assert result.manifest_version == "0.3"
    assert result.license_state == "declared"
    assert result.runtime_kind == "binary"
    assert result.probe.process_tree_cleanup == "verified"
    assert downloader.calls == [MAX_MCPB_ARTIFACT_BYTES]
    assert len(host.connections) == 1
    connection = host.connections[0]
    assert connection.management_id == MANAGEMENT_ID
    assert Path(connection.executable).name == "synthetic.exe"
    assert connection.environment == {"EXAMPLE_MODE": "synthetic"}
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    assert final.is_dir()
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())

    assert installer.rollback_publication(
        management_id=MANAGEMENT_ID,
        expected_tree_digest="f" * 64,
    ) is False
    assert final.is_dir()
    assert installer.rollback_publication(
        management_id=MANAGEMENT_ID,
        expected_tree_digest=result.tree_digest,
    ) is True
    assert not final.exists()


def test_registry_launch_values_are_transient_argv_env_and_rederived_on_start(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, host = _installer(tmp_path, payload)
    secret_value = "synthetic-vault-token"
    configured = _package(
        payload,
        runtime_arguments=(SecretStr("--runtime=bounded"),),
        package_arguments=(SecretStr("--scope=synthetic-tenant"),),
        environment=(
            McpRegistryResolvedLocalEnvironment(
                name="EXAMPLE_TOKEN",
                value=SecretStr(secret_value),
            ),
        ),
    )

    installed = installer.install_and_probe(
        configured,
        management_id=MANAGEMENT_ID,
    )

    connection = host.connections[0]
    assert connection.arguments[0] == "--runtime=bounded"
    assert connection.arguments[-1] == "--scope=synthetic-tenant"
    assert connection.environment == {
        "EXAMPLE_MODE": "synthetic",
        "EXAMPLE_TOKEN": secret_value,
    }
    assert secret_value not in repr(configured)
    assert secret_value not in configured.model_dump_json()
    assert secret_value not in repr(connection)

    resolved = installer.resolve_installed_connection(
        management_id=MANAGEMENT_ID,
        expected=McpLocalPackageLaunchExpectation(
            tree_digest=installed.tree_digest,
            manifest_digest=installed.manifest_digest,
            manifest_version=installed.manifest_version,
            runtime_kind=installed.runtime_kind,
            runtime_version=installed.runtime_version,
        ),
        configuration=configured,
    )
    assert resolved.arguments[0] == connection.arguments[0]
    assert Path(resolved.arguments[2]).name == Path(connection.arguments[2]).name
    assert resolved.arguments[-1] == connection.arguments[-1]
    assert resolved.environment == connection.environment


def test_registry_environment_collision_and_control_injection_fail_before_probe(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, host = _installer(tmp_path, payload)
    collision = _package(
        payload,
        environment=(
            McpRegistryResolvedLocalEnvironment(
                name="EXAMPLE_MODE",
                value=SecretStr("publisher-shadow"),
            ),
        ),
    )
    with pytest.raises(McpLocalPackageInstallerError) as duplicate:
        installer.install_and_probe(collision, management_id=MANAGEMENT_ID)
    assert duplicate.value.code == "mcp_package_environment_unsupported"
    assert host.connections == []

    injected = _package(
        payload,
        package_arguments=(SecretStr("--scope=alpha\nbeta"),),
    )
    with pytest.raises(McpLocalPackageInstallerError) as rejected:
        installer.install_and_probe(injected, management_id=MANAGEMENT_ID)
    assert rejected.value.code == "mcp_package_configuration_invalid"
    assert host.connections == []


def test_mcpb_configuration_is_inspected_without_execution_then_resolved_from_vault(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "synthetic-workspace"
    manifest = _manifest(
        user_config={
            "WORKSPACE": {
                "type": "directory",
                "required": True,
                "description": "Synthetic path; content is never persisted.",
            },
            "ACCESS_TOKEN": {
                "type": "string",
                "required": True,
                "sensitive": True,
            },
            "RETRY_LIMIT": {
                "type": "number",
                "required": False,
                "default": 3,
                "min": 1,
                "max": 5,
            },
        },
        server={
            "type": "binary",
            "entry_point": "server/synthetic.exe",
            "mcp_config": {
                "command": "server/synthetic.exe",
                "args": [
                    "--workspace",
                    "${user_config.WORKSPACE}",
                    "--retries=${user_config.RETRY_LIMIT}",
                ],
                "env": {"SYNTHETIC_ACCESS_TOKEN": "${user_config.ACCESS_TOKEN}"},
            },
        },
    )
    payload = _archive(manifest=manifest)
    installer, downloader, host = _installer(tmp_path, payload)
    inspection_package = _package(payload).model_copy(
        update={"execution_configuration_state": "inspection_only"}
    )

    inspection = installer.inspect_configuration(
        inspection_package,
        management_id=MANAGEMENT_ID,
    )

    assert inspection.artifact_sha256 == hashlib.sha256(payload).hexdigest()
    assert inspection.archive_retained is False
    assert inspection.process_started is False
    assert {item.key for item in inspection.requirements} == {
        "WORKSPACE",
        "ACCESS_TOKEN",
        "RETRY_LIMIT",
    }
    requirements = {item.key: item for item in inspection.requirements}
    assert requirements["WORKSPACE"].location == "package_argument"
    assert requirements["WORKSPACE"].format == "filepath"
    assert requirements["WORKSPACE"].user_value_needed is True
    assert requirements["ACCESS_TOKEN"].location == "environment_variable"
    assert requirements["ACCESS_TOKEN"].secret is True
    assert requirements["RETRY_LIMIT"].default_declared is True
    assert host.connections == []
    assert downloader.calls == [MAX_MCPB_ARTIFACT_BYTES]
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())

    configured_values = {
        "WORKSPACE": SecretStr(str(workspace)),
        "ACCESS_TOKEN": SecretStr("synthetic-inspection-token"),
    }
    installed = installer.install_and_probe(
        _package(payload),
        management_id=MANAGEMENT_ID,
        user_configuration=configured_values,
    )

    assert len(host.connections) == 1
    connection = host.connections[0]
    assert connection.arguments == (
        "--workspace",
        str(workspace),
        "--retries=3",
    )
    assert connection.environment == {
        "SYNTHETIC_ACCESS_TOKEN": "synthetic-inspection-token"
    }
    assert "synthetic-inspection-token" not in repr(configured_values)
    assert "synthetic-inspection-token" not in repr(connection)

    resolved = installer.resolve_installed_connection(
        management_id=MANAGEMENT_ID,
        expected=McpLocalPackageLaunchExpectation(
            tree_digest=installed.tree_digest,
            manifest_digest=installed.manifest_digest,
            manifest_version=installed.manifest_version,
            runtime_kind=installed.runtime_kind,
            runtime_version=installed.runtime_version,
        ),
        user_configuration=configured_values,
    )
    assert resolved.arguments == connection.arguments
    assert resolved.environment == connection.environment


def test_mcpb_configuration_inspection_and_install_states_are_not_interchangeable(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, host = _installer(tmp_path, payload)
    resolved = _package(payload)
    inspection_only = resolved.model_copy(
        update={"execution_configuration_state": "inspection_only"}
    )

    with pytest.raises(McpLocalPackageInstallerError) as wrong_inspection_state:
        installer.inspect_configuration(resolved, management_id=MANAGEMENT_ID)
    assert wrong_inspection_state.value.code == "mcp_package_identity_invalid"

    with pytest.raises(McpLocalPackageInstallerError) as wrong_install_state:
        installer.install_and_probe(inspection_only, management_id=MANAGEMENT_ID)
    assert wrong_install_state.value.code == "mcp_package_identity_invalid"
    assert host.connections == []


@pytest.mark.parametrize(
    ("user_config", "args", "env", "code"),
    (
        (
            {"UNUSED": {"type": "string", "required": True}},
            (),
            {},
            "mcp_package_user_configuration_invalid",
        ),
        (
            {
                "TOKEN": {
                    "type": "string",
                    "required": True,
                    "sensitive": True,
                }
            },
            ("${user_config.TOKEN}",),
            {},
            "mcp_package_sensitive_configuration_unsupported",
        ),
        (
            {"VALUE": {"type": "string", "required": True}},
            ("${user_config.VALUE}",),
            {"VALUE": "${user_config.VALUE}"},
            "mcp_package_user_configuration_unsupported",
        ),
        (
            {
                "VALUE": {
                    "type": "string",
                    "required": True,
                    "multiple": True,
                }
            },
            ("${user_config.VALUE}",),
            {},
            "mcp_package_user_configuration_unsupported",
        ),
    ),
)
def test_mcpb_configuration_inspection_rejects_ambiguous_or_leaky_contracts(
    tmp_path: Path,
    user_config: dict[str, object],
    args: tuple[str, ...],
    env: dict[str, str],
    code: str,
) -> None:
    payload = _archive(
        manifest=_manifest(
            user_config=user_config,
            server={
                "type": "binary",
                "entry_point": "server/synthetic.exe",
                "mcp_config": {
                    "command": "server/synthetic.exe",
                    "args": list(args),
                    "env": env,
                },
            },
        )
    )
    installer, _downloader, host = _installer(tmp_path, payload)

    with pytest.raises(McpLocalPackageInstallerError) as failure:
        installer.inspect_configuration(
            _package(payload).model_copy(
                update={"execution_configuration_state": "inspection_only"}
            ),
            management_id=MANAGEMENT_ID,
        )

    assert failure.value.code == code
    assert host.connections == []
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())


def test_mcpb_install_requires_the_exact_reviewed_configuration_set(
    tmp_path: Path,
) -> None:
    payload = _archive(
        manifest=_manifest(
            user_config={
                "TOKEN": {
                    "type": "string",
                    "required": True,
                    "sensitive": True,
                }
            },
            server={
                "type": "binary",
                "entry_point": "server/synthetic.exe",
                "mcp_config": {
                    "command": "server/synthetic.exe",
                    "env": {"SYNTHETIC_TOKEN": "${user_config.TOKEN}"},
                },
            },
        )
    )
    installer, _downloader, host = _installer(tmp_path, payload)

    with pytest.raises(McpLocalPackageInstallerError) as missing:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    assert missing.value.code == "mcp_package_user_configuration_required"

    with pytest.raises(McpLocalPackageInstallerError) as extra:
        installer.install_and_probe(
            _package(payload),
            management_id=MANAGEMENT_ID,
            user_configuration={
                "TOKEN": SecretStr("synthetic-token"),
                "EXTRA": SecretStr("synthetic-extra"),
            },
        )
    assert extra.value.code == "mcp_package_user_configuration_required"
    assert host.connections == []


def test_installed_connection_is_rederived_read_only_and_evidence_bound(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, downloader, host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload),
        management_id=MANAGEMENT_ID,
    )
    expectation = McpLocalPackageLaunchExpectation(
        tree_digest=installed.tree_digest,
        manifest_digest=installed.manifest_digest,
        manifest_version=installed.manifest_version,
        runtime_kind=installed.runtime_kind,
        runtime_version=installed.runtime_version,
    )
    before_downloads = list(downloader.calls)
    before_probes = list(host.connections)

    connection = installer.resolve_installed_connection(
        management_id=MANAGEMENT_ID,
        expected=expectation,
    )

    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    assert connection.management_id == MANAGEMENT_ID
    assert Path(connection.executable) == final / "server" / "synthetic.exe"
    assert connection.arguments == ("--fixture", str(final / "data" / "example.json"))
    assert connection.environment == {"EXAMPLE_MODE": "synthetic"}
    assert connection.working_directory == str(final)
    assert downloader.calls == before_downloads
    assert host.connections == before_probes


def test_installed_connection_resolution_is_inert_when_package_is_absent(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, downloader, host = _installer(tmp_path, payload)
    packages_root = tmp_path / "mcp-packages"
    expectation = McpLocalPackageLaunchExpectation(
        tree_digest="a" * 64,
        manifest_digest="b" * 64,
        manifest_version="0.3",
        runtime_kind="binary",
        runtime_version=None,
    )

    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_install_required",
    ):
        installer.resolve_installed_connection(
            management_id=MANAGEMENT_ID,
            expected=expectation,
        )

    assert not packages_root.exists()
    assert downloader.calls == []
    assert host.connections == []


def test_installed_connection_refuses_tree_manifest_and_runtime_drift(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload),
        management_id=MANAGEMENT_ID,
    )
    exact = McpLocalPackageLaunchExpectation(
        tree_digest=installed.tree_digest,
        manifest_digest=installed.manifest_digest,
        manifest_version=installed.manifest_version,
        runtime_kind=installed.runtime_kind,
        runtime_version=installed.runtime_version,
    )
    probes = list(host.connections)

    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_manifest_evidence_mismatch",
    ) as manifest_mismatch:
        installer.resolve_installed_connection(
            management_id=MANAGEMENT_ID,
            expected=exact.model_copy(update={"manifest_digest": "e" * 64}),
        )
    assert manifest_mismatch.value.cleanup_required is True

    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_runtime_changed",
    ):
        installer.resolve_installed_connection(
            management_id=MANAGEMENT_ID,
            expected=exact.model_copy(
                update={"runtime_kind": "python", "runtime_version": "3.11.0"}
            ),
        )

    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    (final / "data" / "example.json").write_text(
        '{"fixture":"changed"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_installed_tree_changed",
    ) as tree_changed:
        installer.resolve_installed_connection(
            management_id=MANAGEMENT_ID,
            expected=exact,
        )
    assert tree_changed.value.cleanup_required is True
    assert host.connections == probes


@pytest.mark.parametrize(
    ("payload_factory", "code"),
    (
        (
            lambda: _archive(extra=(("../escape.txt", b"blocked"),)),
            "mcp_package_archive_path_invalid",
        ),
        (
            lambda: _archive(extra=(("DATA/example.json", b"collision"),)),
            "mcp_package_archive_path_collision",
        ),
        (
            lambda: _archive(
                manifest=_manifest(license=""),
            ),
            "mcp_package_license_not_declared",
        ),
        (
            lambda: _archive(
                manifest=_manifest(user_config={"token": {"required": True}}),
            ),
            "mcp_package_user_configuration_invalid",
        ),
        (
            lambda: _archive(
                manifest=_manifest(
                    server={
                        "type": "binary",
                        "entry_point": "server/synthetic.exe",
                        "mcp_config": {"command": "powershell.exe"},
                    }
                ),
            ),
            "mcp_package_command_unsupported",
        ),
    ),
)
def test_mcpb_rejects_unsafe_or_unreviewable_archives(
    tmp_path: Path,
    payload_factory,
    code: str,
) -> None:
    payload = payload_factory()
    installer, _downloader, host = _installer(tmp_path, payload)
    with pytest.raises(McpLocalPackageInstallerError) as failure:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    assert failure.value.code == code
    assert not (tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID).exists()
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())
    if code != "mcp_package_command_unsupported":
        assert host.connections == []


def test_mcpb_integrity_failure_never_extracts_or_starts(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, host = _installer(tmp_path, payload)
    package = _package(payload).model_copy(update={"file_sha256": "0" * 64})
    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_integrity_mismatch",
    ):
        installer.install_and_probe(package, management_id=MANAGEMENT_ID)
    assert host.connections == []
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())


def test_mcpb_probe_failure_removes_staging_but_cleanup_uncertainty_is_preserved(
    tmp_path: Path,
) -> None:
    payload = _archive()
    host = _Host()
    host.error = McpGuardedHostError("mcp_host_protocol_unsupported")
    installer, _downloader, _host = _installer(tmp_path, payload, host)
    with pytest.raises(McpLocalPackageInstallerError) as ordinary:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    assert ordinary.value.code == "mcp_host_protocol_unsupported"
    assert ordinary.value.cleanup_required is False
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())

    host.error = McpGuardedHostError("mcp_host_cleanup_unconfirmed")
    with pytest.raises(McpLocalPackageInstallerError) as uncertain:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    assert uncertain.value.code == "mcp_host_cleanup_unconfirmed"
    assert uncertain.value.cleanup_required is True
    assert uncertain.value.process_tree_cleanup == "unconfirmed"


def test_mcpb_never_publishes_a_tree_modified_by_its_probe_process(
    tmp_path: Path,
) -> None:
    payload = _archive()
    host = _Host()
    host.mutate_tree = True
    installer, _downloader, _host = _installer(tmp_path, payload, host)

    with pytest.raises(McpLocalPackageInstallerError) as failure:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)

    assert failure.value.code == "mcp_package_probe_modified_tree"
    assert failure.value.cleanup_required is False
    assert len(host.connections) == 1
    assert not (tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID).exists()
    assert not any((tmp_path / "mcp-packages" / ".staging").iterdir())


def test_mcpb_existing_publication_fails_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, _host = _installer(tmp_path, payload)
    result = installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    with pytest.raises(McpLocalPackageInstallerError) as duplicate:
        installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    assert duplicate.value.code == "mcp_package_existing_tree_requires_cleanup"
    assert duplicate.value.cleanup_required is True
    assert installer.rollback_publication(
        management_id=MANAGEMENT_ID,
        expected_tree_digest=result.tree_digest,
    ) is True


def test_mcpb_uninstall_is_digest_bound_quarantined_retryable_and_reversible(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, _host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload), management_id=MANAGEMENT_ID
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    held = tmp_path / "mcp-packages" / ".quarantine" / UNINSTALL_ID

    prepared = installer.prepare_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )

    assert prepared.tree_digest == installed.tree_digest
    assert not final.exists()
    assert held.is_dir()
    assert installer.prepare_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) == prepared
    assert installer.rollback_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) is True
    assert final.is_dir()
    assert not held.exists()

    installer.prepare_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    assert installer.commit_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) is True
    assert installer.commit_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) is True
    assert not final.exists()
    assert not held.exists()


def test_mcpb_uninstall_refuses_changed_or_ambiguous_trees(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, _host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload), management_id=MANAGEMENT_ID
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    (final / "unexpected.txt").write_text("synthetic drift", encoding="utf-8")

    with pytest.raises(McpLocalPackageInstallerError) as changed:
        installer.prepare_uninstall(
            management_id=MANAGEMENT_ID,
            operation_id=UNINSTALL_ID,
            expected_tree_digest=installed.tree_digest,
        )

    assert changed.value.code == "mcp_package_installed_tree_changed"
    assert changed.value.cleanup_required is True
    assert final.is_dir()

    (final / "unexpected.txt").unlink()
    installer.prepare_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    held = tmp_path / "mcp-packages" / ".quarantine" / UNINSTALL_ID
    (held / "unexpected.txt").write_text("synthetic drift", encoding="utf-8")
    assert installer.commit_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) is False
    assert installer.rollback_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    ) is False
    assert held.is_dir()
    assert not final.exists()


def test_mcpb_update_stages_probes_publishes_and_can_restore_exact_current(
    tmp_path: Path,
) -> None:
    current_payload = _archive()
    target_payload = _archive(
        extra=(("data/update-marker.json", b'{"version":2}\n'),),
    )
    installer, downloader, host = _installer(tmp_path, current_payload)
    current = installer.install_and_probe(
        _package(current_payload),
        management_id=MANAGEMENT_ID,
    )
    downloader.payload = target_payload

    staged = installer.stage_update(
        _package(target_payload, version="2.0.0"),
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
    )

    root = tmp_path / "mcp-packages"
    final = root / "installed" / MANAGEMENT_ID
    target_stage = root / ".staging" / UPDATE_ID
    rollback = root / ".rollback" / MANAGEMENT_ID
    assert staged.tree_digest != current.tree_digest
    assert target_stage.is_dir()
    assert not rollback.exists()
    assert not (final / "data" / "update-marker.json").exists()
    assert len(host.connections) == 2
    assert host.connections[-1].working_directory == str(target_stage)

    published = installer.publish_update(
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
        expected_target_tree_digest=staged.tree_digest,
    )

    assert published.target_tree_digest == staged.tree_digest
    assert published.rollback_tree_digest == current.tree_digest
    assert (final / "data" / "update-marker.json").is_file()
    assert rollback.is_dir()
    assert not target_stage.exists()
    assert installer.publish_update(
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
        expected_target_tree_digest=staged.tree_digest,
    ) == published

    assert installer.rollback_update_publication(
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
        expected_target_tree_digest=staged.tree_digest,
    ) is True
    assert final.is_dir()
    assert not (final / "data" / "update-marker.json").exists()
    assert not rollback.exists()
    assert not target_stage.exists()


def test_mcpb_rollback_swap_is_reversible_and_generation_cleanup_is_exact(
    tmp_path: Path,
) -> None:
    current_payload = _archive()
    target_payload = _archive(
        extra=(("data/update-marker.json", b'{"version":2}\n'),),
    )
    installer, downloader, _host = _installer(tmp_path, current_payload)
    current = installer.install_and_probe(
        _package(current_payload),
        management_id=MANAGEMENT_ID,
    )
    downloader.payload = target_payload
    staged = installer.stage_update(
        _package(target_payload, version="2.0.0"),
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
    )
    installer.publish_update(
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
        expected_target_tree_digest=staged.tree_digest,
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    rollback = tmp_path / "mcp-packages" / ".rollback" / MANAGEMENT_ID

    assert installer.swap_rollback_generation(
        management_id=MANAGEMENT_ID,
        operation_id="6" * 32,
        expected_current_tree_digest=staged.tree_digest,
        expected_rollback_tree_digest=current.tree_digest,
    ) is True
    assert not (final / "data" / "update-marker.json").exists()
    assert (rollback / "data" / "update-marker.json").is_file()
    assert installer.swap_rollback_generation(
        management_id=MANAGEMENT_ID,
        operation_id="5" * 32,
        expected_current_tree_digest=current.tree_digest,
        expected_rollback_tree_digest=staged.tree_digest,
    ) is True
    assert (final / "data" / "update-marker.json").is_file()
    assert not (rollback / "data" / "update-marker.json").exists()

    cleanup = installer.cleanup_rollback_generation(
        management_id=MANAGEMENT_ID,
        operation_id="4" * 32,
        expected_tree_digest=current.tree_digest,
    )
    assert cleanup.filesystem_changed is True
    assert not rollback.exists()
    replay = installer.cleanup_rollback_generation(
        management_id=MANAGEMENT_ID,
        operation_id="4" * 32,
        expected_tree_digest=current.tree_digest,
    )
    assert replay.filesystem_changed is False
    assert (final / "data" / "update-marker.json").is_file()


@pytest.mark.parametrize("crash_point", ("after_current_move", "after_target_move"))
@pytest.mark.parametrize("direction", ("restore_database_current", "finish_swap"))
def test_mcpb_rollback_swap_recovers_each_atomic_transition_state(
    tmp_path: Path,
    crash_point: str,
    direction: str,
) -> None:
    current_payload = _archive()
    target_payload = _archive(
        extra=(("data/update-marker.json", b'{"version":2}\n'),),
    )
    installer, downloader, _host = _installer(tmp_path, current_payload)
    current = installer.install_and_probe(
        _package(current_payload),
        management_id=MANAGEMENT_ID,
    )
    downloader.payload = target_payload
    target = installer.stage_update(
        _package(target_payload, version="2.0.0"),
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
    )
    installer.publish_update(
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
        expected_target_tree_digest=target.tree_digest,
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    held = tmp_path / "mcp-packages" / ".rollback" / MANAGEMENT_ID
    operation_id = "6" * 32
    transition = tmp_path / "mcp-packages" / ".quarantine" / operation_id
    final.replace(transition)
    if crash_point == "after_target_move":
        held.replace(final)

    if direction == "restore_database_current":
        expected_current = current.tree_digest
        expected_rollback = target.tree_digest
        marker_in_final = True
    else:
        expected_current = target.tree_digest
        expected_rollback = current.tree_digest
        marker_in_final = False
    assert installer.swap_rollback_generation(
        management_id=MANAGEMENT_ID,
        operation_id=operation_id,
        expected_current_tree_digest=expected_current,
        expected_rollback_tree_digest=expected_rollback,
    ) is True
    assert not transition.exists()
    assert (final / "data" / "update-marker.json").exists() is marker_in_final
    assert (held / "data" / "update-marker.json").exists() is not marker_in_final


def test_mcpb_update_refuses_target_drift_without_overwrite(
    tmp_path: Path,
) -> None:
    current_payload = _archive()
    target_payload = _archive(
        extra=(("data/update-marker.json", b'{"version":2}\n'),),
    )
    installer, downloader, _host = _installer(tmp_path, current_payload)
    current = installer.install_and_probe(
        _package(current_payload),
        management_id=MANAGEMENT_ID,
    )
    downloader.payload = target_payload
    staged = installer.stage_update(
        _package(target_payload, version="2.0.0"),
        management_id=MANAGEMENT_ID,
        operation_id=UPDATE_ID,
        expected_current_tree_digest=current.tree_digest,
    )
    target_stage = tmp_path / "mcp-packages" / ".staging" / UPDATE_ID
    (target_stage / "external-change.txt").write_text(
        "synthetic external mutation",
        encoding="utf-8",
    )

    with pytest.raises(
        McpLocalPackageInstallerError,
        match="mcp_package_update_target_changed",
    ) as changed:
        installer.publish_update(
            management_id=MANAGEMENT_ID,
            operation_id=UPDATE_ID,
            expected_current_tree_digest=current.tree_digest,
            expected_target_tree_digest=staged.tree_digest,
        )
    assert changed.value.cleanup_required is True
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    assert final.is_dir()
    assert target_stage.is_dir()
    assert not (tmp_path / "mcp-packages" / ".rollback" / MANAGEMENT_ID).exists()


def test_mcpb_interrupted_uninstall_cleanup_handles_each_recoverable_disk_state(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, _host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload), management_id=MANAGEMENT_ID
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    held = tmp_path / "mcp-packages" / ".quarantine" / UNINSTALL_ID

    from_installed = installer.complete_interrupted_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    assert from_installed.filesystem_changed is True
    assert from_installed.package_presence == "absent"
    assert from_installed.process_started is False
    assert not final.exists()
    assert not held.exists()

    already_absent = installer.complete_interrupted_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    assert already_absent.filesystem_changed is False
    assert already_absent.package_presence == "absent"

    installer.install_and_probe(_package(payload), management_id=MANAGEMENT_ID)
    installer.prepare_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    from_quarantine = installer.complete_interrupted_uninstall(
        management_id=MANAGEMENT_ID,
        operation_id=UNINSTALL_ID,
        expected_tree_digest=installed.tree_digest,
    )
    assert from_quarantine.filesystem_changed is True
    assert not final.exists()
    assert not held.exists()


def test_mcpb_interrupted_uninstall_cleanup_refuses_tree_drift(
    tmp_path: Path,
) -> None:
    payload = _archive()
    installer, _downloader, _host = _installer(tmp_path, payload)
    installed = installer.install_and_probe(
        _package(payload), management_id=MANAGEMENT_ID
    )
    final = tmp_path / "mcp-packages" / "installed" / MANAGEMENT_ID
    (final / "unexpected.txt").write_text("synthetic drift", encoding="utf-8")

    with pytest.raises(McpLocalPackageInstallerError) as changed:
        installer.complete_interrupted_uninstall(
            management_id=MANAGEMENT_ID,
            operation_id=UNINSTALL_ID,
            expected_tree_digest=installed.tree_digest,
        )

    assert changed.value.code == "mcp_package_installed_tree_changed"
    assert changed.value.cleanup_required is True
    assert final.is_dir()
