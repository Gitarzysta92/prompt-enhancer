"""Authoritative classification of paths created by the application.

The inventory contains no absolute paths.  It describes policy only; resolving
entries against a private root is a separate platform responsibility.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ...domain import StrictModel
from ..paths import validate_private_relative_parts


class AppPathRoot(StrEnum):
    APP_HOME = "app_home"
    MODEL_CACHE = "model_cache"
    WEBVIEW_PROFILE = "webview_profile"
    TRANSFER_QUARANTINE = "transfer_quarantine"
    TEMPORARY_WORKSPACE = "temporary_workspace"


class AppPathKind(StrEnum):
    DIRECTORY = "directory"
    FILE = "file"
    SQLITE_DATABASE = "sqlite_database"
    SQLITE_SIDECAR = "sqlite_sidecar"


class PathSensitivity(StrEnum):
    PUBLIC = "public"
    DERIVED_SENSITIVE = "derived_sensitive"
    SECRET = "secret"


class ExportDisposition(StrEnum):
    EXCLUDED = "excluded"
    PROJECTION_ONLY = "projection_only"
    VERBATIM = "verbatim"


class EraseDisposition(StrEnum):
    ALWAYS_WITH_PARENT = "always_with_parent"
    SEPARATE_CHOICE = "separate_choice"
    RETAIN = "retain"


class BackupDisposition(StrEnum):
    EXCLUDED = "excluded"
    SQLITE_ONLINE = "sqlite_online"
    VERBATIM = "verbatim"


class AppPathSpec(StrictModel):
    path_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    root: AppPathRoot
    relative_parts: tuple[str, ...]
    kind: AppPathKind
    sensitivity: PathSensitivity
    export: ExportDisposition
    erase: EraseDisposition
    backup: BackupDisposition
    parent_path_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{2,63}$")
    justification: str = Field(min_length=8, max_length=240)

    @model_validator(mode="after")
    def enforce_policy(self) -> AppPathSpec:
        if not self.relative_parts or validate_private_relative_parts(self.relative_parts):
            raise ValueError("inventory path is not a safe portable relative path")
        if self.sensitivity is PathSensitivity.SECRET and self.export is not ExportDisposition.EXCLUDED:
            raise ValueError("secret paths cannot be exported")
        if self.kind is AppPathKind.SQLITE_SIDECAR and self.backup is not BackupDisposition.EXCLUDED:
            raise ValueError("SQLite sidecars are never copied into backups")
        if self.kind is AppPathKind.SQLITE_DATABASE and self.backup is not BackupDisposition.SQLITE_ONLINE:
            raise ValueError("SQLite databases require the online backup primitive")
        return self


def _spec(
    path_id: str,
    root: AppPathRoot,
    relative_parts: tuple[str, ...],
    kind: AppPathKind,
    sensitivity: PathSensitivity,
    export: ExportDisposition,
    erase: EraseDisposition,
    backup: BackupDisposition,
    justification: str,
    *,
    parent_path_id: str | None = None,
) -> AppPathSpec:
    return AppPathSpec(
        path_id=path_id,
        root=root,
        relative_parts=relative_parts,
        kind=kind,
        sensitivity=sensitivity,
        export=export,
        erase=erase,
        backup=backup,
        parent_path_id=parent_path_id,
        justification=justification,
    )


APPLICATION_PATH_INVENTORY: tuple[AppPathSpec, ...] = (
    _spec("metrics_database", AppPathRoot.APP_HOME, ("metrics.sqlite3",), AppPathKind.SQLITE_DATABASE, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.PROJECTION_ONLY, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.SQLITE_ONLINE, "Analyzer history is sensitive derived local data."),
    _spec("metrics_database_wal", AppPathRoot.APP_HOME, ("metrics.sqlite3-wal",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The WAL is erased with its analyzer database.", parent_path_id="metrics_database"),
    _spec("metrics_database_shm", AppPathRoot.APP_HOME, ("metrics.sqlite3-shm",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The SHM file is erased with its analyzer database.", parent_path_id="metrics_database"),
    _spec("agent_catalog_database", AppPathRoot.APP_HOME, ("agent-catalog.sqlite3",), AppPathKind.SQLITE_DATABASE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.SQLITE_ONLINE, "Authored Agent project names and workspace metadata remain private and are never exported or backed up."),
    _spec("agent_catalog_database_wal", AppPathRoot.APP_HOME, ("agent-catalog.sqlite3-wal",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The Agent catalog WAL is erased with its private database.", parent_path_id="agent_catalog_database"),
    _spec("agent_catalog_database_shm", AppPathRoot.APP_HOME, ("agent-catalog.sqlite3-shm",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The Agent catalog SHM file is erased with its private database.", parent_path_id="agent_catalog_database"),
    _spec("shared_folder_database", AppPathRoot.APP_HOME, ("shared-folders.sqlite3",), AppPathKind.SQLITE_DATABASE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.SQLITE_ONLINE, "Shared workspace locations, peer endpoints, and access material are private and never exported or backed up."),
    _spec("shared_folder_database_wal", AppPathRoot.APP_HOME, ("shared-folders.sqlite3-wal",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The shared-folder WAL is erased with its private database.", parent_path_id="shared_folder_database"),
    _spec("shared_folder_database_shm", AppPathRoot.APP_HOME, ("shared-folders.sqlite3-shm",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The shared-folder SHM file is erased with its private database.", parent_path_id="shared_folder_database"),
    _spec("central_annotation_database", AppPathRoot.APP_HOME, ("central-annotations.sqlite3",), AppPathKind.SQLITE_DATABASE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.SQLITE_ONLINE, "Submitted redacted windows and model labels remain sensitive derived data and are never exported or backed up."),
    _spec("central_annotation_database_wal", AppPathRoot.APP_HOME, ("central-annotations.sqlite3-wal",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The central-annotation WAL is erased with its private database.", parent_path_id="central_annotation_database"),
    _spec("central_annotation_database_shm", AppPathRoot.APP_HOME, ("central-annotations.sqlite3-shm",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The central-annotation SHM file is erased with its private database.", parent_path_id="central_annotation_database"),
    _spec("social_database", AppPathRoot.APP_HOME, ("social.sqlite3",), AppPathKind.SQLITE_DATABASE, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.PROJECTION_ONLY, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.SQLITE_ONLINE, "Social metadata has separate purpose and deletion controls."),
    _spec("social_database_wal", AppPathRoot.APP_HOME, ("social.sqlite3-wal",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The WAL is erased with its social database.", parent_path_id="social_database"),
    _spec("social_database_shm", AppPathRoot.APP_HOME, ("social.sqlite3-shm",), AppPathKind.SQLITE_SIDECAR, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The SHM file is erased with its social database.", parent_path_id="social_database"),
    _spec("pseudonym_key", AppPathRoot.APP_HOME, ("pseudonym.key",), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Local pseudonym key material is never exported or backed up."),
    _spec("api_token", AppPathRoot.APP_HOME, ("api.token",), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Loopback API bearer material is never exported or backed up."),
    _spec("mcp_registry_cache", AppPathRoot.APP_HOME, ("mcp-registry-cache.json",), AppPathKind.FILE, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Fetched MCP Registry metadata is disposable provenance-bound cache state and is never exported or backed up."),
    _spec("mcp_packages", AppPathRoot.APP_HOME, ("mcp-packages",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Reviewed MCP package bytes and isolated runtime trees are reacquirable executable state."),
    _spec("application_update_staging", AppPathRoot.APP_HOME, ("application-updates",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Signed update artifact and ledger bytes are private local staging evidence and are never exported or backed up."),
    _spec("otlp_ingest_token", AppPathRoot.APP_HOME, ("otlp-ingest.token",), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Write-only telemetry ingest bearer material is never exported or backed up."),
    _spec("claude_home_override", AppPathRoot.APP_HOME, ("claude-home.path",), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "An owner-supplied provider path is a private location and is never exported or backed up."),
    _spec("local_models", AppPathRoot.APP_HOME, ("local-models",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Local model registry and downloaded weights are large, reacquirable runtime state."),
    _spec("local_models_override", AppPathRoot.APP_HOME, ("local-models.path",), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "An owner-supplied storage path is a private location and is never exported or backed up."),
    _spec("model_hf_home", AppPathRoot.MODEL_CACHE, ("hf-home",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Hugging Face runtime state is isolated below the model cache."),
    _spec("model_hub_cache", AppPathRoot.MODEL_CACHE, ("hub",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Pinned public snapshots can be reacquired through approval."),
    _spec("model_assets_cache", AppPathRoot.MODEL_CACHE, ("assets",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Model-library assets are disposable local runtime state."),
    _spec("model_credentials_disabled", AppPathRoot.MODEL_CACHE, ("credentials-disabled",), AppPathKind.DIRECTORY, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "Credential lookup is redirected to an isolated disabled location."),
    _spec("model_token_disabled", AppPathRoot.MODEL_CACHE, ("credentials-disabled", "token"), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The disabled token target is never exported or backed up.", parent_path_id="model_credentials_disabled"),
    _spec("model_stored_tokens_disabled", AppPathRoot.MODEL_CACHE, ("credentials-disabled", "stored-tokens"), AppPathKind.FILE, PathSensitivity.SECRET, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "The disabled stored-token target is never exported or backed up.", parent_path_id="model_credentials_disabled"),
    _spec("sentence_transformers_cache", AppPathRoot.MODEL_CACHE, ("sentence-transformers",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Sentence-transformer artifacts are disposable local runtime state."),
    _spec("specialist_screen_cache", AppPathRoot.MODEL_CACHE, ("specialist-screen",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Specialist model snapshots remain isolated from application databases."),
    _spec("torch_inductor_cache", AppPathRoot.MODEL_CACHE, ("torch-inductor",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Compiled model kernels are disposable runtime state."),
    _spec("triton_cache", AppPathRoot.MODEL_CACHE, ("triton",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Compiled Triton kernels are disposable runtime state."),
    _spec("webview_profile", AppPathRoot.WEBVIEW_PROFILE, ("profile",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "Embedded browser state is local runtime material."),
    _spec("transfer_quarantine", AppPathRoot.TRANSFER_QUARANTINE, ("incoming",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Received file bytes remain separate from application metadata."),
    _spec("diagnostic_bundles", AppPathRoot.APP_HOME, ("diagnostics",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Local diagnostic artifacts require explicit preview and deletion."),
    _spec("local_backups", AppPathRoot.APP_HOME, ("backups",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.SEPARATE_CHOICE, BackupDisposition.EXCLUDED, "Portable backups are explicit user-created local artifacts."),
    _spec("estimator_runner_workspace", AppPathRoot.TEMPORARY_WORKSPACE, ("estimator-runner",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "Bounded estimator evidence workspaces are temporary and erased."),
    _spec("provider_schema_preflight_workspace", AppPathRoot.TEMPORARY_WORKSPACE, ("provider-schema-preflight",), AppPathKind.DIRECTORY, PathSensitivity.DERIVED_SENSITIVE, ExportDisposition.EXCLUDED, EraseDisposition.ALWAYS_WITH_PARENT, BackupDisposition.EXCLUDED, "Provider schema probes use isolated empty temporary homes."),
)


def validate_application_path_inventory(
    inventory: tuple[AppPathSpec, ...] = APPLICATION_PATH_INVENTORY,
) -> None:
    by_id = {entry.path_id: entry for entry in inventory}
    if len(by_id) != len(inventory):
        raise ValueError("duplicate application path identifier")
    for entry in inventory:
        if entry.parent_path_id is not None and entry.parent_path_id not in by_id:
            raise ValueError("inventory sidecar parent is missing")
        if entry.kind is AppPathKind.SQLITE_SIDECAR:
            parent = by_id[entry.parent_path_id or ""]
            if parent.kind is not AppPathKind.SQLITE_DATABASE:
                raise ValueError("SQLite sidecar parent is not a database")
    for database in (entry for entry in inventory if entry.kind is AppPathKind.SQLITE_DATABASE):
        children = {
            entry.relative_parts[-1]
            for entry in inventory
            if entry.parent_path_id == database.path_id
        }
        filename = database.relative_parts[-1]
        if children != {f"{filename}-wal", f"{filename}-shm"}:
            raise ValueError("SQLite inventory requires WAL and SHM entries")


validate_application_path_inventory()
