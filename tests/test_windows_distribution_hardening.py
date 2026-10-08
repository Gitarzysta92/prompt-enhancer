from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys

from pydantic import SecretBytes, SecretStr
import pytest

from prompt_enhancer.application.build_evidence.manifest import (
    build_manifest,
    canonical_json,
    compare_manifests,
)
from prompt_enhancer.application.diagnostics import (
    BundleBudget,
    DiagnosticObservation,
    DiagnosticSection,
    DiagnosticValueKind,
    build_diagnostic_bundle,
)
from prompt_enhancer.application.egress import (
    EGRESS_REGISTRY,
    FUTURE_EGRESS_STATES,
    EgressClass,
    FutureEgressState,
)
from prompt_enhancer.application.maintenance.backup import (
    BackupEntry,
    BackupManifest,
    BackupPlanState,
    RestoreRejection,
    RestoreVerificationState,
    create_backup_manifest,
    plan_backup,
    verify_restore_manifest,
)
from prompt_enhancer.application.maintenance.inventory import (
    APPLICATION_PATH_INVENTORY,
    AppPathKind,
    AppPathRoot,
    ExportDisposition,
    PathSensitivity,
    validate_application_path_inventory,
)
from prompt_enhancer.application.owned_process import run_owned_process
from prompt_enhancer.application.paths import (
    HardeningState,
    PathInspectionState,
    PathRejection,
    validate_private_relative_parts,
)
from prompt_enhancer.application.resources import (
    ResourceAvailability,
    ResourceKind,
)
from prompt_enhancer.application.updates import (
    UpdateChannel,
    UpdateRejection,
    UpdateVerificationState,
    verify_update_manifest,
)
from prompt_enhancer.application.updates.ports import SignatureState
from prompt_enhancer.config import path_has_symlink_component
from prompt_enhancer.infrastructure.diagnostics import DeterministicDiagnosticRedactor
from prompt_enhancer.infrastructure.paths import (
    LocalPrivatePathHardener,
    inspect_path_components,
)
from prompt_enhancer.infrastructure.resources import (
    PACKAGED_RESOURCE_LAYOUT,
    PackageResourceResolver,
    StagedResourceResolver,
)
from prompt_enhancer.infrastructure.sqlite.online_backup import backup_open_database
from prompt_enhancer.infrastructure.updates import DevelopmentHmacManifestVerifier


_SOURCE_ROOT = Path(__file__).parents[1] / "src" / "prompt_enhancer"
_CHILD_ENVIRONMENT_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC",
)
_PROCESS_STDOUT_LIMIT = 256 * 1024
_PROCESS_STDERR_LIMIT = 64 * 1024
_PROCESS_TIMEOUT_SECONDS = 10


def _owned_child_environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in _CHILD_ENVIRONMENT_KEYS:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    if "SYSTEMROOT" not in environment and (value := os.environ.get("SystemRoot")):
        environment["SYSTEMROOT"] = value
    return environment


def _run_test_process(
    arguments: tuple[str, ...], *, cwd: Path, stdin_payload: bytes = b"",
):
    return run_owned_process(
        arguments,
        cwd=cwd,
        env=_owned_child_environment(),
        stdin_payload=stdin_payload,
        stdout_limit=_PROCESS_STDOUT_LIMIT,
        stderr_limit=_PROCESS_STDERR_LIMIT,
        timeout=_PROCESS_TIMEOUT_SECONDS,
        maximum_active_processes=1,
    )


def test_path_inspection_converts_os_errors_to_typed_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def denied(_path: Path):
        raise PermissionError("synthetic denial")

    monkeypatch.setattr(Path, "lstat", denied)
    inspection, checked = inspect_path_components(tmp_path / "private")

    assert inspection.state is PathInspectionState.UNVERIFIABLE
    assert inspection.rejection is PathRejection.INSPECTION_FAILED
    assert checked == 0
    assert path_has_symlink_component(tmp_path / "private") is True


@pytest.mark.parametrize(
    "failure",
    [
        NotADirectoryError("synthetic non-directory"),
        OSError(1921, "synthetic reparse inspection failure"),
        OSError(4390, "synthetic reparse tag failure"),
    ],
)
def test_path_inspection_fails_closed_for_other_os_error_classes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: OSError,
) -> None:
    def failed(_path: Path):
        raise failure

    monkeypatch.setattr(Path, "lstat", failed)

    inspection, _ = inspect_path_components(tmp_path / "private")

    assert inspection.state is PathInspectionState.UNVERIFIABLE
    assert inspection.rejection is PathRejection.INSPECTION_FAILED


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("..", "file"), PathRejection.TRAVERSAL_COMPONENT),
        (("report.txt:stream",), PathRejection.ALTERNATE_DATA_STREAM),
        (("name. ",), PathRejection.TRAILING_DOT_OR_SPACE),
        (("CON.txt",), PathRejection.RESERVED_DEVICE_NAME),
    ],
)
def test_private_relative_policy_rejects_windows_ambiguities(
    parts: tuple[str, ...], expected: PathRejection
) -> None:
    assert validate_private_relative_parts(parts) is expected


def test_windows_hardener_never_claims_posix_mode_is_a_dacl(tmp_path: Path) -> None:
    class _UnavailableDacl:
        def inspect(self, _path: Path) -> PathRejection:
            return PathRejection.WINDOWS_DACL_UNAVAILABLE

        def create_then_inspect(self, _path: Path) -> PathRejection:
            return PathRejection.WINDOWS_DACL_UNAVAILABLE

    target = tmp_path / "private"
    target.mkdir()
    target.chmod(0o700)

    report = LocalPrivatePathHardener(
        platform_name="nt",
        windows_private_directory=_UnavailableDacl(),
    ).inspect(target)

    assert report.state is HardeningState.UNVERIFIED
    assert report.reason is PathRejection.WINDOWS_DACL_UNAVAILABLE


def test_path_rejection_vocabulary_contains_no_paths() -> None:
    for reason in PathRejection:
        assert "/" not in reason.value
        assert "\\" not in reason.value
        assert ":" not in reason.value


def _stage_resource(root: Path, kind: ResourceKind, content: bytes = b"synthetic") -> Path:
    layout = PACKAGED_RESOURCE_LAYOUT[kind]
    target = root.joinpath(*layout.relative_parts)
    if layout.shape.value == "directory":
        target.mkdir(parents=True)
        (target / "index.html").write_bytes(content)
    else:
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
    return target


def test_staged_resource_resolver_is_bounded_and_missing_is_typed(tmp_path: Path) -> None:
    probe = _stage_resource(tmp_path, ResourceKind.ACCELERATOR_PROBE)
    resolver = StagedResourceResolver(tmp_path)

    found = resolver.resolve(ResourceKind.ACCELERATOR_PROBE)
    missing = resolver.resolve(ResourceKind.DASHBOARD_STATIC)

    assert found.availability is ResourceAvailability.AVAILABLE
    assert found.path == probe.resolve()
    assert missing.availability is ResourceAvailability.MISSING
    assert missing.path is None


def test_staged_resource_resolver_rejects_unverifiable_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from prompt_enhancer.infrastructure.resources import packaged as packaged_module
    from prompt_enhancer.application.paths import PathInspection

    monkeypatch.setattr(
        packaged_module,
        "inspect_path_components",
        lambda _path: (
            PathInspection(
                state=PathInspectionState.UNVERIFIABLE,
                rejection=PathRejection.INSPECTION_FAILED,
            ),
            0,
        ),
    )

    result = StagedResourceResolver(tmp_path).resolve(ResourceKind.ACCELERATOR_PROBE)

    assert result.availability is ResourceAvailability.REJECTED
    assert result.path is None


def test_real_package_resolves_probe_without_repository_parent_assumption() -> None:
    resolver = PackageResourceResolver()
    result = resolver.resolve(ResourceKind.ACCELERATOR_PROBE)

    assert result.availability is ResourceAvailability.AVAILABLE
    assert result.path is not None
    assert result.path.name == "probe_local_accelerator.py"


def test_dashboard_and_probe_callers_do_not_walk_repository_parents() -> None:
    bootstrap = (_SOURCE_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    compatibility = (
        _SOURCE_ROOT / "infrastructure" / "text_models" / "compatibility.py"
    ).read_text(encoding="utf-8")

    assert 'frontend" / "dist' not in bootstrap
    assert 'scripts" / "probe_local_accelerator.py' not in compatibility


def test_frontend_build_targets_the_ignored_package_resource_layout() -> None:
    repository = Path(__file__).parents[1]
    vite = (repository / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    ignore = (repository / ".gitignore").read_text(encoding="utf-8")
    packaging = (repository / "pyproject.toml").read_text(encoding="utf-8")

    assert 'outDir: "../src/prompt_enhancer/_resources/dashboard"' in vite
    assert "/src/prompt_enhancer/_resources/dashboard/" in ignore
    assert '"_resources/dashboard/**/*"' in packaging


def test_source_package_directories_are_not_swallowed_by_ignore_rules() -> None:
    repository = Path(__file__).parents[1]
    candidates = tuple(
        path.relative_to(repository).as_posix()
        for path in (repository / "src" / "prompt_enhancer").rglob("__init__.py")
    )
    completed = _run_test_process(
        ("git", "check-ignore", "--no-index", "--stdin"),
        cwd=repository,
        stdin_payload=("\n".join(candidates) + "\n").encode("utf-8"),
    )

    assert completed.returncode == 1, completed.stdout.decode("utf-8")
    assert completed.stdout == b""


def test_owned_test_process_forwards_bounded_handoff_without_raw_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    child_environment = {"PATH": "C:/example/bin", "TEMP": "C:/example/temp"}

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return object()

    monkeypatch.setattr(
        sys.modules[__name__], "_owned_child_environment", lambda: child_environment,
    )
    monkeypatch.setattr(sys.modules[__name__], "run_owned_process", run)

    result = _run_test_process(
        ("example-tool", "--synthetic"), cwd=tmp_path,
        stdin_payload=b"synthetic-input",
    )

    assert result is not None
    assert calls == [(('example-tool', '--synthetic'), {
        "cwd": tmp_path,
        "env": child_environment,
        "stdin_payload": b"synthetic-input",
        "stdout_limit": _PROCESS_STDOUT_LIMIT,
        "stderr_limit": _PROCESS_STDERR_LIMIT,
        "timeout": _PROCESS_TIMEOUT_SECONDS,
        "maximum_active_processes": 1,
    })]
    source = Path(__file__).read_text(encoding="utf-8")
    assert "subprocess" + ".run" not in source
    assert "import" + " subprocess" not in source


def test_application_path_inventory_enforces_sensitive_and_sqlite_policy() -> None:
    validate_application_path_inventory()
    identifiers = {entry.path_id for entry in APPLICATION_PATH_INVENTORY}

    assert {"metrics_database", "social_database", "api_token", "pseudonym_key"} <= identifiers
    assert all(
        entry.export is ExportDisposition.EXCLUDED
        for entry in APPLICATION_PATH_INVENTORY
        if entry.sensitivity is PathSensitivity.SECRET
    )
    for database in (
        entry
        for entry in APPLICATION_PATH_INVENTORY
        if entry.kind is AppPathKind.SQLITE_DATABASE
    ):
        children = {
            entry.relative_parts[-1]
            for entry in APPLICATION_PATH_INVENTORY
            if entry.parent_path_id == database.path_id
        }
        filename = database.relative_parts[-1]
        assert children == {f"{filename}-wal", f"{filename}-shm"}


def _joined_private_literal(node: ast.AST) -> tuple[AppPathRoot, tuple[str, ...]] | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "self" and node.attr == "home":
            return AppPathRoot.APP_HOME, ()
        return None
    if isinstance(node, ast.Name) and node.id in {"cache", "cache_root"}:
        return AppPathRoot.MODEL_CACHE, ()
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and isinstance(node.right.value, str)
    ):
        parent = _joined_private_literal(node.left)
        if parent is not None:
            return parent[0], (*parent[1], node.right.value)
    return None


def test_private_path_literals_in_runtime_code_are_inventory_bound(tmp_path: Path) -> None:
    from prompt_enhancer.config import AppSettings
    from prompt_enhancer.infrastructure.social.sqlite import SOCIAL_DATABASE_FILENAME

    settings = AppSettings(home=tmp_path)
    app_home_paths = {
        entry.relative_parts
        for entry in APPLICATION_PATH_INVENTORY
        if entry.root is AppPathRoot.APP_HOME
    }
    assert (settings.database_path.relative_to(settings.home).as_posix(),) in app_home_paths
    assert (settings.pseudonym_key_path.relative_to(settings.home).as_posix(),) in app_home_paths
    assert (settings.api_token_path.relative_to(settings.home).as_posix(),) in app_home_paths
    assert (SOCIAL_DATABASE_FILENAME,) in app_home_paths

    discovered: set[tuple[AppPathRoot, tuple[str, ...]]] = set()
    for relative_path in (
        Path("config.py"),
        Path("infrastructure/text_models/loader.py"),
        Path("infrastructure/text_models/model_ensemble.py"),
    ):
        tree = ast.parse((_SOURCE_ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            joined = _joined_private_literal(node)
            if joined is not None and joined[1]:
                discovered.add(joined)

    by_root = {
        root: tuple(entry for entry in APPLICATION_PATH_INVENTORY if entry.root is root)
        for root in AppPathRoot
    }
    uncovered = {
        (root.value, parts)
        for root, parts in discovered
        if not any(
            entry.relative_parts == parts
            or (
                entry.kind is AppPathKind.DIRECTORY
                and parts[: len(entry.relative_parts)] == entry.relative_parts
            )
            for entry in by_root[root]
        )
    }
    assert uncovered == set()


def _build_tree(root: Path, payload: bytes = b"synthetic artifact\n") -> None:
    (root / "package").mkdir(parents=True)
    (root / "package" / "module.py").write_bytes(payload)
    (root / "NOTICE.txt").write_bytes(b"public notice\n")


def _manifest(root: Path):
    return build_manifest(
        root,
        git_revision="a" * 40,
        tool_versions={"python": "3.11.9", "setuptools": "75.0.0"},
        lockfile_hashes={"uv.lock": "b" * 64},
    )


def test_public_build_manifest_is_byte_deterministic_and_has_no_host_path(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _build_tree(first_root)
    _build_tree(second_root)

    first = _manifest(first_root)
    second = _manifest(second_root)
    first_bytes = canonical_json(first)

    assert first_bytes == canonical_json(second)
    assert compare_manifests(first, second).identical is True
    assert str(tmp_path).encode("utf-8") not in first_bytes
    assert b"mtime" not in first_bytes.replace(b"filesystem_mtime", b"")
    assert first.distributable is False


def test_public_build_manifest_reports_exactly_one_changed_file(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _build_tree(first_root)
    _build_tree(second_root, payload=b"changed artifact\n")

    comparison = compare_manifests(_manifest(first_root), _manifest(second_root))

    assert comparison.identical is False
    assert [item.relative_path for item in comparison.differences] == ["package/module.py"]


def test_public_build_manifest_cli_compares_two_trees_without_host_paths(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _build_tree(first_root)
    _build_tree(second_root)

    completed = _run_test_process(
        (
            sys._base_executable,
            "scripts/build_public_manifest.py",
            str(first_root),
            "--compare-root",
            str(second_root),
            "--git-revision",
            "a" * 40,
            "--tool-version",
            "python=3.11.9",
            "--lockfile-hash",
            "uv.lock=" + "b" * 64,
        ),
        cwd=Path(__file__).parents[1],
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["identical"] is True
    assert str(tmp_path).encode() not in completed.stdout
    assert completed.stderr == b""


def test_diagnostic_bundle_redacts_canaries_omits_prose_and_matches_preview() -> None:
    observations = (
        DiagnosticObservation(section=DiagnosticSection.APPLICATION, event_code="config_loaded", fact_key="contact", value_kind=DiagnosticValueKind.STATE, value=SecretStr("user@example.invalid")),
        DiagnosticObservation(section=DiagnosticSection.PLATFORM, event_code="path_checked", fact_key="location", value_kind=DiagnosticValueKind.STATE, value=SecretStr(r"C:\Users\Example\project")),
        DiagnosticObservation(section=DiagnosticSection.LOCAL_MODELS, event_code="token_checked", fact_key="credential", value_kind=DiagnosticValueKind.STATE, value=SecretStr("EXAMPLE_REDACTION_CANARY_0000000000")),
        DiagnosticObservation(section=DiagnosticSection.DATABASE, event_code="exception_seen", fact_key="exception", value_kind=DiagnosticValueKind.STATE, value=SecretStr("synthetic prompt and output must not persist")),
        DiagnosticObservation(section=DiagnosticSection.PLATFORM, event_code="host_seen", fact_key="host", value_kind=DiagnosticValueKind.STATE, value=SecretStr("workstation-7.corp.example")),
        DiagnosticObservation(section=DiagnosticSection.APPLICATION, event_code="token_seen", fact_key="short_token", value_kind=DiagnosticValueKind.STATE, value=SecretStr("ghp_ab12cd34ef")),
        DiagnosticObservation(section=DiagnosticSection.PLATFORM, event_code="address_seen", fact_key="address", value_kind=DiagnosticValueKind.STATE, value=SecretStr("fe80::1")),
    )
    bundle = build_diagnostic_bundle(
        observations,
        budget=BundleBudget(),
        redactor=DeterministicDiagnosticRedactor(),
    )
    payload = bundle.bytes_for_local_write()

    assert hashlib.sha256(payload).hexdigest() == bundle.preview.sha256
    assert len(payload) == bundle.preview.byte_count
    assert b"user@example.invalid" not in payload
    assert b"Users" not in payload
    assert b"EXAMPLE_REDACTION_CANARY_0000000000" not in payload
    assert b"synthetic prompt" not in payload
    assert b"workstation-7.corp.example" not in payload
    assert b"ghp_ab12cd34ef" not in payload
    assert b"fe80::1" not in payload
    assert bundle.preview.omitted_observations == 4
    assert bundle.preview.truncated is True


def test_diagnostic_bundle_is_deterministic_and_budgeted() -> None:
    observations = tuple(
        DiagnosticObservation(
            section=DiagnosticSection.APPLICATION,
            event_code="state_observed",
            fact_key=f"count_{index}",
            value_kind=DiagnosticValueKind.COUNT,
            value=SecretStr(str(index)),
        )
        for index in range(40)
    )
    budget = BundleBudget(max_total_bytes=1_024, max_section_bytes=512)
    redactor = DeterministicDiagnosticRedactor()

    first = build_diagnostic_bundle(observations, budget=budget, redactor=redactor)
    second = build_diagnostic_bundle(observations, budget=budget, redactor=redactor)

    assert first.bytes_for_local_write() == second.bytes_for_local_write()
    assert len(first.bytes_for_local_write()) <= budget.max_total_bytes
    assert first.preview.truncated is True


def test_diagnostic_bundle_reports_more_than_preview_default_without_failure() -> None:
    observations = tuple(
        DiagnosticObservation(
            section=DiagnosticSection.APPLICATION,
            event_code="state_observed",
            fact_key="count_value",
            value_kind=DiagnosticValueKind.COUNT,
            value=SecretStr(str(index)),
        )
        for index in range(2_305)
    )

    bundle = build_diagnostic_bundle(
        observations,
        budget=BundleBudget(max_observations=1),
        redactor=DeterministicDiagnosticRedactor(),
    )

    assert bundle.preview.included_observations == 1
    assert bundle.preview.omitted_observations == 2_304
    assert bundle.preview.truncated is True


def test_diagnostic_contract_has_no_transport_surface() -> None:
    source = (_SOURCE_ROOT / "application" / "diagnostics" / "contracts.py").read_text(
        encoding="utf-8"
    ).casefold()
    for symbol in ("socket", "http", "url"):
        assert symbol not in source


class _RecordingVerifier:
    def __init__(self, state: SignatureState) -> None:
        self.state = state
        self.payloads: list[bytes] = []

    def verify(self, *, payload: bytes, signature: bytes, key_id: str) -> SignatureState:
        self.payloads.append(payload)
        return self.state


def _update_payload(
    *,
    now: datetime,
    release_version: str = "1.1.0",
    minimum_supported_version: str = "1.0.0",
    channel: str = "stable",
) -> bytes:
    return json.dumps(
        {
            "artifact_sha256": "c" * 64,
            "artifact_size_bytes": 1_024,
            "channel": channel,
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "minimum_supported_version": minimum_supported_version,
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "release_version": release_version,
            "schema_version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_update_verifier_accepts_only_after_raw_signature_verification() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    raw = _update_payload(now=now)
    verifier = _RecordingVerifier(SignatureState.VALID)

    result = verify_update_manifest(
        raw,
        signature=b"synthetic-signature",
        key_id="development-key",
        verifier=verifier,
        now=now,
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
    )

    assert result.state is UpdateVerificationState.ACCEPTED
    assert verifier.payloads == [raw]


def test_update_semantics_are_not_trusted_when_raw_signature_is_bad() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    expired = json.loads(_update_payload(now=now))
    expired["expires_at"] = (now - timedelta(days=1)).isoformat()
    raw = json.dumps(expired, separators=(",", ":"), sort_keys=True).encode()

    result = verify_update_manifest(
        raw,
        signature=b"bad",
        key_id="development-key",
        verifier=_RecordingVerifier(SignatureState.INVALID),
        now=now,
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
    )

    assert result.rejection is UpdateRejection.BAD_SIGNATURE
    assert result.manifest is None


def test_update_bounds_and_schema_reject_before_signature() -> None:
    verifier = _RecordingVerifier(SignatureState.VALID)
    now = datetime(2030, 1, 1, tzinfo=UTC)

    oversized = verify_update_manifest(
        b"x" * (32 * 1024 + 1), signature=b"x", key_id="key", verifier=verifier,
        now=now, installed_version="1.0.0", channel=UpdateChannel.STABLE,
    )
    invalid = verify_update_manifest(
        b'{"schema_version":1,"unexpected":true}', signature=b"x", key_id="key", verifier=verifier,
        now=now, installed_version="1.0.0", channel=UpdateChannel.STABLE,
    )

    assert oversized.rejection is UpdateRejection.MANIFEST_TOO_LARGE
    assert invalid.rejection is UpdateRejection.INVALID_SCHEMA
    assert verifier.payloads == []


@pytest.mark.parametrize(
    ("payload_changes", "installed_version", "channel", "expected"),
    [
        ({"published_at": "2030-01-02T00:00:00+00:00"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.NOT_YET_PUBLISHED),
        ({"expires_at": "2029-12-31T00:00:00+00:00"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.EXPIRED),
        ({"channel": "beta"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.CHANNEL_MISMATCH),
        ({"minimum_supported_version": "1.1.0"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.MINIMUM_VERSION_UNSUPPORTED),
        ({"release_version": "1.0.0"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.CURRENT_VERSION),
        ({"release_version": "0.9.0"}, "1.0.0", UpdateChannel.STABLE, UpdateRejection.DOWNGRADE),
    ],
)
def test_update_semantic_rejections_follow_valid_signature(
    payload_changes: dict[str, object],
    installed_version: str,
    channel: UpdateChannel,
    expected: UpdateRejection,
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    payload = json.loads(_update_payload(now=now))
    payload.update(payload_changes)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    verifier = _RecordingVerifier(SignatureState.VALID)

    result = verify_update_manifest(
        raw,
        signature=b"synthetic-signature",
        key_id="development-key",
        verifier=verifier,
        now=now,
        installed_version=installed_version,
        channel=channel,
    )

    assert result.rejection is expected
    assert verifier.payloads == [raw]


def test_update_rejects_unknown_key_and_duplicate_json_keys() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    raw = _update_payload(now=now)
    unknown = verify_update_manifest(
        raw,
        signature=b"synthetic-signature",
        key_id="unknown-key",
        verifier=_RecordingVerifier(SignatureState.UNKNOWN_KEY),
        now=now,
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
    )
    duplicate_verifier = _RecordingVerifier(SignatureState.VALID)
    duplicate = verify_update_manifest(
        b'{"schema_version":1,"schema_version":1}',
        signature=b"synthetic-signature",
        key_id="development-key",
        verifier=duplicate_verifier,
        now=now,
        installed_version="1.0.0",
        channel=UpdateChannel.STABLE,
    )

    assert unknown.rejection is UpdateRejection.UNKNOWN_KEY
    assert duplicate.rejection is UpdateRejection.INVALID_SCHEMA
    assert duplicate_verifier.payloads == []


def test_development_update_verifier_refuses_production_and_is_unregistered() -> None:
    with pytest.raises(RuntimeError, match="development_update_verifier_disabled"):
        DevelopmentHmacManifestVerifier(
            development_mode=False,
            keys={"development-key": SecretBytes(b"k" * 32)},
        )

    bootstrap = (_SOURCE_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    assert "DevelopmentHmacManifestVerifier" not in bootstrap


def test_development_update_verifier_uses_hmac_only_for_synthetic_tests() -> None:
    raw = b'{"synthetic":true}'
    key = b"k" * 32
    verifier = DevelopmentHmacManifestVerifier(
        development_mode=True,
        keys={"development-key": SecretBytes(key)},
    )
    signature = hmac.new(key, raw, hashlib.sha256).digest()

    assert verifier.verify(payload=raw, signature=signature, key_id="development-key") is SignatureState.VALID
    assert verifier.verify(payload=raw + b"x", signature=signature, key_id="development-key") is SignatureState.INVALID


def test_backup_plan_excludes_secrets_and_reports_encryption_unsupported() -> None:
    plan = plan_backup(encrypted=False)
    encrypted = plan_backup(encrypted=True)

    assert plan.state is BackupPlanState.READY
    assert "api_token" not in plan.path_ids
    assert "pseudonym_key" not in plan.path_ids
    assert all(not path_id.endswith(("_wal", "_shm")) for path_id in plan.path_ids)
    assert encrypted.state is BackupPlanState.UNSUPPORTED_ENCRYPTED_BACKUP
    assert encrypted.path_ids == ()


def test_restore_verifies_every_payload_before_approval() -> None:
    payloads = {
        "metrics_database": b"synthetic metrics backup",
        "social_database": b"synthetic social backup",
    }
    schemas = {"metrics_database": 40, "social_database": 1}
    manifest = create_backup_manifest(
        payloads,
        application_version="0.1.0",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
        sqlite_schema_versions=schemas,
    )
    raw = canonical_json(manifest)

    approved = verify_restore_manifest(
        raw,
        payloads=payloads,
        supported_sqlite_schema_versions=schemas,
    )
    tampered = dict(payloads)
    tampered["social_database"] = b"synthetic social backux"
    rejected = verify_restore_manifest(
        raw,
        payloads=tampered,
        supported_sqlite_schema_versions=schemas,
    )

    assert approved.state is RestoreVerificationState.APPROVED
    assert set(approved.approved_path_ids) == set(payloads)
    assert rejected.state is RestoreVerificationState.REJECTED
    assert rejected.rejection is RestoreRejection.ENTRY_HASH_MISMATCH
    assert rejected.approved_path_ids == ()


def test_restore_rejects_newer_schema_and_unknown_path() -> None:
    newer = b'{"encrypted":false,"entries":[],"schema_version":2}\n'
    unknown = BackupManifest(
        application_version="0.1.0",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
        entries=(
            BackupEntry(
                path_id="unknown_database",
                kind=AppPathKind.SQLITE_DATABASE,
                size_bytes=1,
                sha256=hashlib.sha256(b"x").hexdigest(),
                source_schema_version=1,
            ),
        )
    )

    assert verify_restore_manifest(
        newer,
        payloads={},
        supported_sqlite_schema_versions={},
    ).rejection is RestoreRejection.NEWER_SCHEMA_UNSUPPORTED
    assert verify_restore_manifest(
        canonical_json(unknown),
        payloads={"unknown_database": b"x"},
        supported_sqlite_schema_versions={"unknown_database": 1},
    ).rejection is RestoreRejection.UNKNOWN_PATH


def test_restore_rejects_newer_database_schema_before_approval() -> None:
    payloads = {"metrics_database": b"synthetic metrics backup"}
    manifest = create_backup_manifest(
        payloads,
        application_version="0.1.0",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
        sqlite_schema_versions={"metrics_database": 41},
    )

    result = verify_restore_manifest(
        canonical_json(manifest),
        payloads=payloads,
        supported_sqlite_schema_versions={"metrics_database": 40},
    )

    assert result.rejection is RestoreRejection.NEWER_SCHEMA_UNSUPPORTED
    assert result.approved_path_ids == ()


def test_sqlite_online_backup_produces_integrity_checked_snapshot() -> None:
    source = sqlite3.connect(":memory:")
    destination = sqlite3.connect(":memory:")
    try:
        source.execute("CREATE TABLE synthetic_events (event_id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        source.execute("INSERT INTO synthetic_events (state) VALUES ('ready')")
        source.commit()

        backup_open_database(source, destination)

        assert destination.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert destination.execute("SELECT state FROM synthetic_events").fetchone() == ("ready",)
    finally:
        destination.close()
        source.close()


def test_no_sqlite_database_copy_primitive_exists_in_source() -> None:
    for source_path in _SOURCE_ROOT.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert not (
            "shutil.copy" in source and ".sqlite3" in source
        ), source_path.relative_to(_SOURCE_ROOT).as_posix()


def test_exact_egress_registry_distinguishes_existing_and_unimplemented_capabilities() -> None:
    future_classes = set(FUTURE_EGRESS_STATES)
    assert future_classes == {
        EgressClass.SIGNED_UPDATE_ADVISORY,
        EgressClass.APPROVED_MODEL_DOWNLOAD,
        EgressClass.APPROVED_PROVIDER_REQUEST,
    }
    assert FUTURE_EGRESS_STATES == {
        EgressClass.SIGNED_UPDATE_ADVISORY: FutureEgressState.IMPLEMENTED_UNCOMPOSED,
        EgressClass.APPROVED_MODEL_DOWNLOAD: FutureEgressState.ACTIVE_EXPLICIT_APPROVAL,
        EgressClass.APPROVED_PROVIDER_REQUEST: FutureEgressState.IMPLEMENTED_UNCOMPOSED,
    }
    registrations = {entry.module: entry for entry in EGRESS_REGISTRY}
    assert registrations[
        "prompt_enhancer.infrastructure.text_models.loader"
    ].state is FutureEgressState.ACTIVE_EXPLICIT_APPROVAL
    assert registrations[
        "prompt_enhancer.infrastructure.estimator_runners.codex"
    ].state is FutureEgressState.IMPLEMENTED_UNCOMPOSED
    assert registrations[
        "prompt_enhancer.infrastructure.updates.https_manifest_source"
    ].state is FutureEgressState.IMPLEMENTED_UNCOMPOSED


def test_every_network_capable_source_module_is_egress_classified() -> None:
    capable: set[str] = set()
    for source_path in _SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                if names & {"socket", "urllib.request", "http.client", "httpx", "requests"}:
                    capable.add(
                        "prompt_enhancer."
                        + source_path.relative_to(_SOURCE_ROOT).with_suffix("").as_posix().replace("/", ".")
                    )
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "socket", "urllib.request", "http.client", "httpx", "requests"
            }:
                capable.add(
                    "prompt_enhancer."
                    + source_path.relative_to(_SOURCE_ROOT).with_suffix("").as_posix().replace("/", ".")
                )
    # This fixed inventory covers every direct network boundary. Four are
    # owned-loopback services: the desktop overlay (probe + open), the local
    # model runtime manager (free-port bind, health, chat proxy to its child),
    # the Claude Code prompt-check hook (posts to this app's loopback API), and
    # the no-proxy/no-redirect local Agent controller bridge.
    # Explicit external requests include the reviewed Prompt Check gateway and the shared-folder client (ADR 0018)
    # dials exactly the URL the person typed when joining a teammate's folder;
    # MCP Store discovery uses the documented Official Registry; a guarded
    # compatibility check dials only the exact reviewed HTTPS origin after
    # native confirmation; and the signed-update source is present but remains
    # uncomposed until owner-controlled release identity exists.
    allowed_loopback = {
        "prompt_enhancer.desktop_overlay",
        "prompt_enhancer.application.local_models",
        "prompt_enhancer.interfaces.hooks.prompt_check_hook",
        "prompt_enhancer.infrastructure.agent_controller_http",
    }
    allowed_approved = {
        "prompt_enhancer.infrastructure.litellm",
        "prompt_enhancer.application.shared_folders",
        "prompt_enhancer.infrastructure.mcp_registry",
        "prompt_enhancer.infrastructure.mcp_guarded_host",
    }
    allowed_uncomposed = {
        "prompt_enhancer.infrastructure.updates.https_manifest_source",
        "prompt_enhancer.infrastructure.updates.https_artifact_source",
    }
    registered_loopback = {
        entry.module
        for entry in EGRESS_REGISTRY
        if entry.module in allowed_loopback
        and entry.egress_class is EgressClass.LOOPBACK_OWNED_SERVICE
        and entry.state is FutureEgressState.ACTIVE_LOCAL_ONLY
    }
    registered_approved = {
        entry.module
        for entry in EGRESS_REGISTRY
        if entry.module in allowed_approved
        and entry.egress_class is EgressClass.APPROVED_PROVIDER_REQUEST
        and entry.state is FutureEgressState.ACTIVE_EXPLICIT_APPROVAL
    }
    registered_uncomposed = {
        entry.module
        for entry in EGRESS_REGISTRY
        if entry.module in allowed_uncomposed
        and entry.egress_class is EgressClass.SIGNED_UPDATE_ADVISORY
        and entry.state is FutureEgressState.IMPLEMENTED_UNCOMPOSED
    }

    assert (
        capable
        == registered_loopback | registered_approved | registered_uncomposed
        == allowed_loopback | allowed_approved | allowed_uncomposed
    )


def test_suite_guard_fails_before_non_loopback_connection() -> None:
    candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError, match="non_loopback_socket_forbidden"):
            candidate.connect(("192.0.2.1", 443))
    finally:
        candidate.close()
