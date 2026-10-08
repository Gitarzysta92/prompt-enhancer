"""Configuration with an enforced zero-cost, loopback-only Phase 1 profile."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import sys
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import CostMode, DataTier


class ConfigurationError(RuntimeError):
    """Raised when configuration would weaken a Phase 1 invariant."""


def lexical_absolute_path(value: Path) -> Path:
    """Make a path absolute without resolving symlink components."""

    expanded = value.expanduser()
    return Path(os.path.abspath(os.fspath(expanded)))


def path_has_symlink_component(value: Path) -> bool:
    """Treat symlink, reparse, and unverifiable components as unsafe."""

    # Kept as a compatibility boundary for existing adapters.  The platform
    # implementation returns a typed tri-state result and catches every OS
    # inspection error so callers neither fail open nor leak raw path errors.
    from .infrastructure.paths import path_has_symlink_or_reparse_component

    return path_has_symlink_or_reparse_component(value)


def default_app_home(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    explicit = env.get("PROMPT_ENHANCER_HOME")
    if explicit:
        return Path(explicit).expanduser()

    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA")
        if base:
            return Path(base) / "PromptEnhancer"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PromptEnhancer"
    else:
        base = env.get("XDG_DATA_HOME")
        if base:
            return Path(base) / "prompt-enhancer"
        return Path.home() / ".local" / "share" / "prompt-enhancer"

    return Path.home() / ".prompt-enhancer"


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AppSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    home: Path = Field(default_factory=default_app_home)
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    cost_mode: CostMode = CostMode.OFFLINE_ONLY
    data_tier: DataTier = DataTier.METADATA
    control_plane_development_api: bool = Field(
        default=False,
        description=(
            "Expose the in-memory team control-plane development routes on the "
            "loopback API. Off by default; it stores nothing durably, serves "
            "synthetic tenants only, and is not a team deployment."
        ),
    )
    paid_product_development_api: bool = Field(
        default=False,
        description=(
            "Permit an explicitly composed paid-product readiness receipt on "
            "the loopback API. Off by default; the flag alone mounts nothing "
            "and activates no identity, billing, or hosted-model provider."
        ),
    )
    session_reader_enabled: bool = Field(
        default=True,
        description=(
            "Owner-authorized on-demand reading of the owner's own sessions in "
            "the local dashboard (ADR 0011). On by default at the owner's "
            "direction; set PROMPT_ENHANCER_SESSION_READER=disabled to turn it "
            "off. The raw_transcripts capability reports the truth either way. "
            "Nothing is persisted."
        ),
    )
    social_development_api: bool = Field(
        default=False,
        description=(
            "Permit explicitly composed private-social development routes on "
            "the loopback API. Off by default; the flag alone creates no social "
            "identity, principal resolver, listener, remote binding, social "
            "database, or mutation authority."
        ),
    )

    @field_validator("home")
    @classmethod
    def normalize_home(cls, value: Path) -> Path:
        return lexical_absolute_path(value)

    @model_validator(mode="after")
    def enforce_phase_one_profile(self) -> AppSettings:
        if not is_loopback_host(self.host):
            raise ValueError("Phase 1 services must bind to a loopback address")
        if self.cost_mode is not CostMode.OFFLINE_ONLY:
            raise ValueError("Phase 1 permits only offline_only cost mode")
        if self.data_tier is not DataTier.METADATA:
            raise ValueError("Phase 1 permits only metadata storage")
        if self.control_plane_development_api and not is_loopback_host(self.host):
            raise ValueError("the control-plane development API stays on loopback")
        if self.paid_product_development_api and not is_loopback_host(self.host):
            raise ValueError("the paid-product development API stays on loopback")
        if self.social_development_api and not is_loopback_host(self.host):
            raise ValueError("the social development API stays on loopback")
        return self

    @property
    def database_path(self) -> Path:
        return self.home / "metrics.sqlite3"

    @property
    def application_update_staging_dir(self) -> Path:
        """Private fixed update-artifact staging root; never an install target."""

        return self.home / "application-updates"

    @property
    def agent_catalog_path(self) -> Path:
        """Sensitive owner-authored Agent project/session navigation metadata."""

        return self.home / "agent-catalog.sqlite3"

    @property
    def mcp_registry_cache_path(self) -> Path:
        """Normalized public MCP Registry metadata used for offline fallback."""

        return self.home / "mcp-registry-cache.json"

    @property
    def mcp_packages_dir(self) -> Path:
        """Isolated, application-owned MCP package trees and transient staging."""

        return self.home / "mcp-packages"

    @property
    def pseudonym_key_path(self) -> Path:
        return self.home / "pseudonym.key"

    @property
    def api_token_path(self) -> Path:
        return self.home / "api.token"

    @property
    def native_agent_lifecycle_path(self) -> Path:
        """Content-free latest native Agent lifecycle marker."""

        return self.home / "diagnostics" / "native-agent-lifecycle.json"

    @property
    def native_overlay_lifecycle_path(self) -> Path:
        """Content-free latest metrics-overlay lifecycle marker."""

        return self.home / "diagnostics" / "native-overlay-lifecycle.json"

    @property
    def claude_home_override_path(self) -> Path:
        """Optional owner-supplied Claude Code home, one line, private."""

        return self.home / "claude-home.path"

    @property
    def local_models_override_path(self) -> Path:
        """One-line private file naming where model weights and runtimes live."""

        return self.home / "local-models.path"

    @property
    def local_models_dir(self) -> Path:
        """Registry, weights and runtimes for local models (ADR 0013).

        Resolution: ``PROMPT_ENHANCER_LOCAL_MODELS_DIR``, then the override
        file under the app home, then ``<app home>/local-models``. Model
        weights are tens of gigabytes, so the owner can keep them on another
        drive without moving the rest of the app state.
        """

        explicit = os.environ.get("PROMPT_ENHANCER_LOCAL_MODELS_DIR")
        if explicit:
            return Path(explicit).expanduser()
        override = self.local_models_override_path
        try:
            if override.is_file():
                text = override.read_text(encoding="utf-8").strip().splitlines()
                if text and text[0].strip():
                    return Path(text[0].strip()).expanduser()
        except OSError:
            pass
        return self.home / "local-models"

    @property
    def otlp_ingest_token_path(self) -> Path:
        """Separate write-only token the Claude Code telemetry exporter presents."""

        return self.home / "otlp-ingest.token"

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> AppSettings:
        env = os.environ if environment is None else environment
        host = env.get("PROMPT_ENHANCER_HOST", "127.0.0.1")
        raw_port = env.get("PROMPT_ENHANCER_PORT", "8765")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ConfigurationError("PROMPT_ENHANCER_PORT must be an integer") from exc
        # Only the exact opt-in string enables the development control plane, so
        # a stray value such as "0", "false", or "maybe" leaves it disabled.
        control_plane = (
            env.get("PROMPT_ENHANCER_CONTROL_PLANE_DEV_API", "") == "enabled"
        )
        paid_product = (
            env.get("PROMPT_ENHANCER_PAID_PRODUCT_DEV_API", "") == "enabled"
        )
        social = env.get("PROMPT_ENHANCER_SOCIAL_DEV_API", "") == "enabled"
        session_reader = env.get("PROMPT_ENHANCER_SESSION_READER", "enabled") != "disabled"
        return cls(
            home=default_app_home(env),
            host=host,
            port=port,
            control_plane_development_api=control_plane,
            paid_product_development_api=paid_product,
            social_development_api=social,
            session_reader_enabled=session_reader,
        )


def prepare_app_home(settings: AppSettings) -> None:
    """Create private local state without revealing its absolute path."""

    try:
        from .application.paths import PathInspectionState
        from .infrastructure.paths import inspect_path_components

        before, _ = inspect_path_components(settings.home)
        if before.state is PathInspectionState.REPARSE_OR_SYMLINK:
            raise ConfigurationError(
                "application home cannot contain a symlink or reparse point"
            )
        if before.state is PathInspectionState.UNVERIFIABLE:
            raise ConfigurationError("application home components could not be verified")
        settings.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        after, _ = inspect_path_components(settings.home)
        if after.state is PathInspectionState.REPARSE_OR_SYMLINK:
            raise ConfigurationError(
                "application home cannot contain a symlink or reparse point"
            )
        if after.state is PathInspectionState.UNVERIFIABLE:
            raise ConfigurationError("application home components could not be verified")
        settings.home.chmod(0o700)
    except ConfigurationError:
        raise
    except OSError as exc:
        raise ConfigurationError("could not securely prepare application home") from exc
