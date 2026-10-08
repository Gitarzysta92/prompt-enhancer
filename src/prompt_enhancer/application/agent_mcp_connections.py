"""Durable, scoped credentials for the loopback Agent MCP endpoint.

Connection secrets are derived from the application's private API token and
are never stored.  The repository keeps only bounded connection metadata and
credential revisions, so rotation immediately invalidates the previous token
and revocation survives restart.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import re
import secrets
from threading import Lock
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .agent_controller_ownership import (
    AgentControllerOwnershipList,
    AgentControllerOwnershipRepository,
    AgentControllerOwnershipService,
)
from .agent_mcp_client_config import (
    AGENT_MCP_BEARER_ENV,
    AGENT_MCP_HTTP_PATH,
    AgentMcpClientConfigError,
    build_agent_mcp_client_configs,
    validate_agent_mcp_endpoint,
)


AGENT_MCP_CONNECTION_CONTRACT_VERSION = "agent-mcp-connection.v4"
AGENT_MCP_MANAGEMENT_CONTRACT_VERSION = "agent-mcp-management.v2"
AGENT_MCP_MANAGEMENT_PATH = "/v1/integrations/agent-mcp/connections"
AGENT_MCP_SCOPE_CONTRACT_VERSION = "agent-mcp-scope.v1"
AGENT_MCP_SETUP_CONTRACT_VERSION = "agent-mcp-client-setup.v1"
AGENT_MCP_TOOL_ACTIVITY_SEQUENCE_CONTRACT_VERSION = (
    "agent-mcp-tool-activity-sequence.v1"
)
AGENT_MCP_SETUP_PATH = "/v1/integrations/agent-mcp/setup"
AGENT_MCP_DEFAULT_EXPIRY_DAYS = 90
AGENT_MCP_MAX_EXPIRY_DAYS = 365
MAX_AGENT_MCP_CONNECTIONS = 16
MAX_AGENT_MCP_CONNECTION_LIST = 32

_ID_PATTERN = r"^[0-9a-f]{32}$"
_LABEL_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
_TOKEN_PATTERN = re.compile(
    r"^pemcp2\.([0-9a-f]{32})\.([1-9][0-9]{0,8})\.([A-Za-z0-9_-]{43})$"
)

AgentMcpClientKind = Literal["codex", "claude", "other"]
AgentMcpConnectionState = Literal["active", "expired", "revoked", "scope_missing"]
AgentMcpScopeState = Literal["bound", "missing"]
AgentMcpToolOutcome = Literal["succeeded", "failed"]
AgentMcpToolSource = Literal["external_client", "native_self_test"]


class AgentMcpConnectionError(RuntimeError):
    """Closed, content-free failure at the connection-authority boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _normalized_label(value: str) -> str:
    normalized = value.strip()
    if not _LABEL_PATTERN.fullmatch(normalized):
        raise ValueError("invalid connection label")
    return normalized


class CreateAgentMcpConnection(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    label: str
    client_kind: AgentMcpClientKind
    project_id: str = Field(pattern=_ID_PATTERN)
    allow_model_lifecycle: bool = Field(default=False, strict=True)
    expires_in_days: int = Field(
        default=AGENT_MCP_DEFAULT_EXPIRY_DAYS,
        strict=True,
        ge=1,
        le=AGENT_MCP_MAX_EXPIRY_DAYS,
    )

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _normalized_label(value)


class RotateAgentMcpConnection(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    expires_in_days: int = Field(
        default=AGENT_MCP_DEFAULT_EXPIRY_DAYS,
        strict=True,
        ge=1,
        le=AGENT_MCP_MAX_EXPIRY_DAYS,
    )


class RevokeAgentMcpConnection(StrictModel):
    expected_revision: int = Field(strict=True, ge=1)


class AgentMcpConnectionScope(StrictModel):
    """Exact project boundary carried by one direct-controller credential."""

    contract_version: Literal["agent-mcp-scope.v1"] = (
        AGENT_MCP_SCOPE_CONTRACT_VERSION
    )
    state: AgentMcpScopeState
    project_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    project_name: str | None = Field(default=None, min_length=1, max_length=120)
    catalog_access: Literal["project_only", "none"]
    chat_access: Literal["project_only", "none"]
    workspace_access: Literal["project_only", "none"]
    native_approval_inherited: Literal[False] = False

    @model_validator(mode="after")
    def coherent_scope(self) -> "AgentMcpConnectionScope":
        bound = self.project_id is not None and self.project_name is not None
        if self.state == "bound" and not bound:
            raise ValueError("bound Agent MCP scope needs a project")
        if self.state == "missing" and bound:
            raise ValueError("missing Agent MCP scope cannot name a project")
        expected_access = "project_only" if self.state == "bound" else "none"
        if (
            self.catalog_access != expected_access
            or self.chat_access != expected_access
            or self.workspace_access != expected_access
        ):
            raise ValueError("Agent MCP scope access is incoherent")
        return self


class AgentMcpConnection(StrictModel):
    contract_version: Literal["agent-mcp-connection.v4"] = (
        AGENT_MCP_CONNECTION_CONTRACT_VERSION
    )
    connection_id: str = Field(pattern=_ID_PATTERN)
    label: str
    client_kind: AgentMcpClientKind
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    last_tool_at: datetime | None
    last_tool_name: str | None = Field(
        default=None,
        pattern=r"^(?:agent_[a-z][a-z0-9_]{0,47}|unknown_tool)$",
    )
    last_tool_outcome: AgentMcpToolOutcome | None
    last_tool_source: AgentMcpToolSource | None
    last_auth_rejected_at: datetime | None
    revoked_at: datetime | None
    revision: int = Field(strict=True, ge=1)
    credential_revision: int = Field(strict=True, ge=1)
    allow_model_lifecycle: bool
    scope: AgentMcpConnectionScope
    state: AgentMcpConnectionState

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _normalized_label(value)

    @field_validator(
        "created_at",
        "updated_at",
        "expires_at",
        "last_used_at",
        "last_tool_at",
        "last_auth_rejected_at",
        "revoked_at",
    )
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def coherent_state(self) -> "AgentMcpConnection":
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("connection timestamps are incoherent")
        if self.last_used_at is not None and self.last_used_at < self.created_at:
            raise ValueError("last-use timestamp is incoherent")
        tool_values = (
            self.last_tool_at,
            self.last_tool_name,
            self.last_tool_outcome,
            self.last_tool_source,
        )
        if any(value is not None for value in tool_values) and not all(
            value is not None for value in tool_values
        ):
            raise ValueError("tool activity receipt is incomplete")
        if self.last_tool_at is not None and (
            self.last_tool_at < self.created_at or self.last_used_at is None
        ):
            raise ValueError("tool activity timestamp is incoherent")
        if (
            self.last_auth_rejected_at is not None
            and self.last_auth_rejected_at < self.created_at
        ):
            raise ValueError("authentication rejection timestamp is incoherent")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("revocation timestamp is incoherent")
        if self.state == "revoked" and self.revoked_at is None:
            raise ValueError("revoked connection needs a timestamp")
        if self.state != "revoked" and self.revoked_at is not None:
            raise ValueError("active or expired connection cannot be revoked")
        if self.scope.state == "missing" and self.state not in {"scope_missing", "revoked"}:
            raise ValueError("missing scope must keep connection authority inactive")
        if self.scope.state == "bound" and self.state == "scope_missing":
            raise ValueError("bound scope cannot report missing authority")
        return self


class AgentMcpToolActivitySequence(StrictModel):
    """Content-free current-process cursor for exact controller evidence."""

    contract_version: Literal["agent-mcp-tool-activity-sequence.v1"] = (
        AGENT_MCP_TOOL_ACTIVITY_SEQUENCE_CONTRACT_VERSION
    )
    connection_id: str = Field(pattern=_ID_PATTERN)
    credential_revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=0, le=9_007_199_254_740_991)
    tool_name: str | None = Field(
        default=None,
        pattern=r"^(?:agent_[a-z][a-z0-9_]{0,47}|unknown_tool)$",
    )
    tool_source: AgentMcpToolSource | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outcome: AgentMcpToolOutcome | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def coherent_activity(self) -> "AgentMcpToolActivitySequence":
        identity = (self.tool_name, self.tool_source, self.started_at)
        completion = (self.completed_at, self.outcome)
        if self.sequence == 0:
            if any(value is not None for value in (*identity, *completion)):
                raise ValueError("zero activity sequence cannot carry a tool")
            return self
        if any(value is None for value in identity):
            raise ValueError("tool admission receipt is incomplete")
        if (self.completed_at is None) != (self.outcome is None):
            raise ValueError("tool completion receipt is incomplete")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("tool activity timestamps are incoherent")
        return self


class AgentMcpConnectionList(StrictModel):
    contract_version: Literal["agent-mcp-management.v2"] = (
        AGENT_MCP_MANAGEMENT_CONTRACT_VERSION
    )
    activity_epoch: str = Field(pattern=_ID_PATTERN)
    connections: tuple[AgentMcpConnection, ...]
    active_count: int = Field(strict=True, ge=0, le=MAX_AGENT_MCP_CONNECTIONS)
    controller_ownerships: AgentControllerOwnershipList
    tool_activity_sequences: tuple[AgentMcpToolActivitySequence, ...]

    @model_validator(mode="after")
    def exact_activity_sequences(self) -> "AgentMcpConnectionList":
        expected = {
            (item.connection_id, item.credential_revision)
            for item in self.connections
        }
        actual = {
            (item.connection_id, item.credential_revision)
            for item in self.tool_activity_sequences
        }
        if (
            len(actual) != len(self.tool_activity_sequences)
            or actual != expected
        ):
            raise ValueError("tool activity sequences do not match connections")
        return self


class AgentMcpConnectionCredential(StrictModel):
    """One-time private response; the bearer and inline configs are not stored."""

    contract_version: Literal["agent-mcp-connection.v4"] = (
        AGENT_MCP_CONNECTION_CONTRACT_VERSION
    )
    connection: AgentMcpConnection
    endpoint_url: str
    bearer_token: str = Field(repr=False, min_length=80, max_length=160)
    codex_toml: str = Field(repr=False, min_length=1, max_length=4096)
    claude_json: str = Field(repr=False, min_length=1, max_length=4096)
    idempotent_replay: bool
    secret_stored_by_server: Literal[False] = False
    starts_process: Literal[False] = False
    starts_terminal: Literal[False] = False


class AgentMcpClientSetup(StrictModel):
    """Token-free client setup preview; grants no connection authority."""

    contract_version: Literal["agent-mcp-client-setup.v1"] = (
        AGENT_MCP_SETUP_CONTRACT_VERSION
    )
    endpoint_url: str
    bearer_token_env_var: Literal["PROMPT_ENHANCER_AGENT_MCP_TOKEN"] = (
        AGENT_MCP_BEARER_ENV
    )
    codex_toml: str = Field(min_length=1, max_length=4096)
    claude_json: str = Field(min_length=1, max_length=4096)
    codex_add_command: str = Field(min_length=1, max_length=4096)
    claude_add_command: str = Field(min_length=1, max_length=4096)
    credential_included: Literal[False] = False
    connection_authority_granted: Literal[False] = False
    native_connection_required: Literal[True] = True
    starts_process: Literal[False] = False
    starts_terminal: Literal[False] = False
    provider_configuration_changed: Literal[False] = False

    @model_validator(mode="after")
    def exact_generated_setup(self) -> "AgentMcpClientSetup":
        try:
            expected = build_agent_mcp_client_configs(self.endpoint_url)
        except AgentMcpClientConfigError:
            raise ValueError("Agent MCP setup endpoint is invalid") from None
        if (
            self.codex_toml != expected.codex_toml
            or self.claude_json != expected.claude_json
            or self.codex_add_command != expected.codex_add_command
            or self.claude_add_command != expected.claude_add_command
        ):
            raise ValueError("Agent MCP setup artifacts are incoherent")
        return self


class AgentMcpPrincipal(StrictModel):
    connection_id: str = Field(pattern=_ID_PATTERN)
    credential_revision: int = Field(strict=True, ge=1)
    client_kind: AgentMcpClientKind
    allow_model_lifecycle: bool
    project_id: str = Field(pattern=_ID_PATTERN)


class AgentMcpConnectionRepository(AgentControllerOwnershipRepository, Protocol):
    def create_connection(
        self,
        *,
        connection_id: str,
        request_id: str,
        request_fingerprint: str,
        label: str,
        client_kind: AgentMcpClientKind,
        scope_project_id: str,
        allow_model_lifecycle: bool,
        created_at: datetime,
        expires_at: datetime,
        active_limit: int,
    ) -> tuple[AgentMcpConnection, bool]: ...

    def list_connections(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> Sequence[AgentMcpConnection]: ...

    def get_connection(
        self,
        connection_id: str,
        *,
        now: datetime,
    ) -> AgentMcpConnection | None: ...

    def rotate_connection(
        self,
        connection_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        expected_revision: int,
        updated_at: datetime,
        expires_at: datetime,
    ) -> tuple[AgentMcpConnection, bool]: ...

    def revoke_connection(
        self,
        connection_id: str,
        *,
        expected_revision: int,
        revoked_at: datetime,
    ) -> tuple[AgentMcpConnection, bool]: ...

    def touch_connection(self, connection_id: str, *, used_at: datetime) -> None: ...

    def record_tool_call(
        self,
        connection_id: str,
        *,
        tool_name: str,
        outcome: AgentMcpToolOutcome,
        source: AgentMcpToolSource,
        observed_at: datetime,
    ) -> None: ...

    def record_auth_rejection(
        self,
        connection_id: str,
        *,
        rejected_at: datetime,
    ) -> None: ...


def _connection_state(
    *,
    expires_at: datetime,
    revoked_at: datetime | None,
    scope_project_id: str | None,
    scope_project_name: str | None,
    now: datetime,
) -> AgentMcpConnectionState:
    if revoked_at is not None:
        return "revoked"
    if scope_project_id is None or scope_project_name is None:
        return "scope_missing"
    if expires_at <= now:
        return "expired"
    return "active"


def _request_fingerprint(command: CreateAgentMcpConnection) -> str:
    canonical = json.dumps(
        command.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _rotation_fingerprint(command: RotateAgentMcpConnection) -> str:
    canonical = json.dumps(
        command.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _credential_document(
    connection: AgentMcpConnection,
    *,
    endpoint_url: str,
    bearer_token: str,
    idempotent_replay: bool,
) -> AgentMcpConnectionCredential:
    try:
        client_configs = build_agent_mcp_client_configs(endpoint_url)
    except AgentMcpClientConfigError as error:
        raise AgentMcpConnectionError(error.code) from None
    return AgentMcpConnectionCredential(
        connection=connection,
        endpoint_url=client_configs.endpoint_url,
        bearer_token=bearer_token,
        codex_toml=client_configs.codex_toml,
        claude_json=client_configs.claude_json,
        idempotent_replay=idempotent_replay,
    )


def build_agent_mcp_setup_document(endpoint_url: str) -> AgentMcpClientSetup:
    """Build an exact token-free preview without creating durable authority."""

    try:
        client_configs = build_agent_mcp_client_configs(endpoint_url)
    except AgentMcpClientConfigError as error:
        raise AgentMcpConnectionError(error.code) from None
    return AgentMcpClientSetup(
        endpoint_url=client_configs.endpoint_url,
        codex_toml=client_configs.codex_toml,
        claude_json=client_configs.claude_json,
        codex_add_command=client_configs.codex_add_command,
        claude_add_command=client_configs.claude_add_command,
    )


def _validated_endpoint(endpoint_url: str) -> str:
    try:
        return validate_agent_mcp_endpoint(endpoint_url)
    except AgentMcpClientConfigError as error:
        raise AgentMcpConnectionError(error.code) from None


class AgentMcpConnectionService:
    """Issue, rotate, authenticate, and revoke one-purpose MCP credentials."""

    def __init__(
        self,
        repository: AgentMcpConnectionRepository,
        *,
        token_pepper: str,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        activity_epoch_factory: Callable[[], str] | None = None,
    ) -> None:
        if len(token_pepper) < 32:
            raise ValueError("Agent MCP token pepper is too short")
        self._repository = repository
        self._pepper = token_pepper.encode("utf-8")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: secrets.token_hex(16))
        self._activity_epoch = (
            activity_epoch_factory()
            if activity_epoch_factory is not None
            else secrets.token_hex(16)
        )
        if re.fullmatch(_ID_PATTERN, self._activity_epoch) is None:
            raise ValueError("Agent MCP activity epoch is invalid")
        self._activity_lock = Lock()
        self._tool_activity_sequences: dict[
            tuple[str, int], AgentMcpToolActivitySequence
        ] = {}
        self._ownership = AgentControllerOwnershipService(
            repository,
            clock=self._clock,
        )

    @property
    def ownership(self) -> AgentControllerOwnershipService:
        return self._ownership

    def _now(self) -> datetime:
        return _utc(self._clock())

    def _token(
        self,
        connection_id: str,
        credential_revision: int,
        project_id: str,
    ) -> str:
        material = (
            f"prompt-enhancer-agent-mcp-token-v2:{connection_id}:"
            f"{credential_revision}:{project_id}"
        ).encode("ascii")
        digest = hmac.new(self._pepper, material, hashlib.sha256).digest()
        secret = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return f"pemcp2.{connection_id}.{credential_revision}.{secret}"

    def create(
        self,
        command: CreateAgentMcpConnection,
        *,
        endpoint_url: str,
    ) -> AgentMcpConnectionCredential:
        endpoint = _validated_endpoint(endpoint_url)
        now = self._now()
        connection, replay = self._repository.create_connection(
            connection_id=self._id(),
            request_id=command.request_id,
            request_fingerprint=_request_fingerprint(command),
            label=command.label,
            client_kind=command.client_kind,
            scope_project_id=command.project_id,
            allow_model_lifecycle=command.allow_model_lifecycle,
            created_at=now,
            expires_at=now + timedelta(days=command.expires_in_days),
            active_limit=MAX_AGENT_MCP_CONNECTIONS,
        )
        if connection.state != "active":
            raise AgentMcpConnectionError(
                "agent_mcp_connection_replay_inactive"
            )
        return _credential_document(
            connection,
            endpoint_url=endpoint,
            bearer_token=self._token(
                connection.connection_id,
                connection.credential_revision,
                command.project_id,
            ),
            idempotent_replay=replay,
        )

    def list(self) -> AgentMcpConnectionList:
        with self._activity_lock:
            now = self._now()
            connections = tuple(
                self._repository.list_connections(
                    now=now,
                    limit=MAX_AGENT_MCP_CONNECTION_LIST,
                )
            )
            current_keys = {
                (item.connection_id, item.credential_revision)
                for item in connections
            }
            self._tool_activity_sequences = {
                key: value
                for key, value in self._tool_activity_sequences.items()
                if key in current_keys
            }
            sequences = tuple(
                self._tool_activity_sequences.get(
                    (item.connection_id, item.credential_revision),
                    AgentMcpToolActivitySequence(
                        connection_id=item.connection_id,
                        credential_revision=item.credential_revision,
                        sequence=0,
                    ),
                )
                for item in connections
            )
            return AgentMcpConnectionList(
                activity_epoch=self._activity_epoch,
                connections=connections,
                active_count=sum(item.state == "active" for item in connections),
                controller_ownerships=self._ownership.list(),
                tool_activity_sequences=sequences,
            )

    def rotate(
        self,
        connection_id: str,
        command: RotateAgentMcpConnection,
        *,
        endpoint_url: str,
    ) -> AgentMcpConnectionCredential:
        if re.fullmatch(_ID_PATTERN, connection_id) is None:
            raise AgentMcpConnectionError("agent_mcp_connection_not_found")
        endpoint = _validated_endpoint(endpoint_url)
        now = self._now()
        connection, replay = self._repository.rotate_connection(
            connection_id,
            request_id=command.request_id,
            request_fingerprint=_rotation_fingerprint(command),
            expected_revision=command.expected_revision,
            updated_at=now,
            expires_at=now + timedelta(days=command.expires_in_days),
        )
        if connection.state != "active":
            raise AgentMcpConnectionError("agent_mcp_connection_inactive")
        project_id = connection.scope.project_id
        if project_id is None:
            raise AgentMcpConnectionError("agent_mcp_connection_inactive")
        return _credential_document(
            connection,
            endpoint_url=endpoint,
            bearer_token=self._token(
                connection.connection_id,
                connection.credential_revision,
                project_id,
            ),
            idempotent_replay=replay,
        )

    def revoke(
        self,
        connection_id: str,
        command: RevokeAgentMcpConnection,
    ) -> AgentMcpConnection:
        if re.fullmatch(_ID_PATTERN, connection_id) is None:
            raise AgentMcpConnectionError("agent_mcp_connection_not_found")
        connection, _replay = self._repository.revoke_connection(
            connection_id,
            expected_revision=command.expected_revision,
            revoked_at=self._now(),
        )
        return connection

    def authenticate(self, bearer_token: str) -> AgentMcpPrincipal:
        match = _TOKEN_PATTERN.fullmatch(bearer_token)
        if match is None:
            raise AgentMcpConnectionError("agent_mcp_authentication_failed")
        connection_id, revision_text, _secret = match.groups()
        credential_revision = int(revision_text)
        now = self._now()
        connection = self._repository.get_connection(connection_id, now=now)
        project_id = (
            connection.scope.project_id
            if connection is not None
            else None
        )
        expected = self._token(
            connection_id,
            credential_revision,
            project_id or "0" * 32,
        )
        secret_matches = hmac.compare_digest(
            bearer_token.encode("ascii"), expected.encode("ascii")
        )
        if (
            connection is None
            or connection.state != "active"
            or connection.credential_revision != credential_revision
            or not secret_matches
        ):
            if connection is not None and secret_matches:
                try:
                    self._repository.record_auth_rejection(
                        connection_id,
                        rejected_at=now,
                    )
                except AgentMcpConnectionError:
                    # Rejection evidence is best-effort. Authentication must
                    # stay closed and indistinguishable when storage is busy.
                    pass
            raise AgentMcpConnectionError("agent_mcp_authentication_failed")
        if project_id is None:
            raise AgentMcpConnectionError("agent_mcp_authentication_failed")
        self._repository.touch_connection(connection_id, used_at=now)
        return AgentMcpPrincipal(
            connection_id=connection.connection_id,
            credential_revision=connection.credential_revision,
            client_kind=connection.client_kind,
            allow_model_lifecycle=connection.allow_model_lifecycle,
            project_id=project_id,
        )

    @staticmethod
    def _validate_tool_activity(
        *,
        credential_revision: int,
        tool_name: str,
        source: AgentMcpToolSource,
    ) -> None:
        if not isinstance(credential_revision, int) or isinstance(
            credential_revision, bool
        ) or credential_revision < 1:
            raise AgentMcpConnectionError("agent_mcp_tool_activity_invalid")
        if re.fullmatch(
            r"(?:agent_[a-z][a-z0-9_]{0,47}|unknown_tool)", tool_name
        ) is None:
            raise AgentMcpConnectionError("agent_mcp_tool_activity_invalid")
        if source not in {"external_client", "native_self_test"}:
            raise AgentMcpConnectionError("agent_mcp_tool_activity_invalid")

    def begin_tool_call(
        self,
        connection_id: str,
        *,
        credential_revision: int,
        tool_name: str,
        source: AgentMcpToolSource,
    ) -> int:
        self._validate_tool_activity(
            credential_revision=credential_revision,
            tool_name=tool_name,
            source=source,
        )
        with self._activity_lock:
            started_at = self._now()
            connection = self._repository.get_connection(
                connection_id,
                now=started_at,
            )
            if (
                connection is None
                or connection.state != "active"
                or connection.credential_revision != credential_revision
            ):
                raise AgentMcpConnectionError("agent_mcp_tool_activity_stale")
            key = (connection_id, credential_revision)
            previous = self._tool_activity_sequences.get(key)
            sequence = 1 if previous is None else previous.sequence + 1
            if sequence > 9_007_199_254_740_991:
                raise AgentMcpConnectionError("agent_mcp_tool_activity_exhausted")
            self._tool_activity_sequences[key] = AgentMcpToolActivitySequence(
                connection_id=connection_id,
                credential_revision=credential_revision,
                sequence=sequence,
                tool_name=tool_name,
                tool_source=source,
                started_at=started_at,
            )
            return sequence

    def finish_tool_call(
        self,
        connection_id: str,
        *,
        credential_revision: int,
        sequence: int,
        tool_name: str,
        outcome: AgentMcpToolOutcome,
        source: AgentMcpToolSource,
    ) -> None:
        self._validate_tool_activity(
            credential_revision=credential_revision,
            tool_name=tool_name,
            source=source,
        )
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or not isinstance(outcome, str)
            or outcome not in {"succeeded", "failed"}
        ):
            raise AgentMcpConnectionError("agent_mcp_tool_activity_invalid")
        with self._activity_lock:
            key = (connection_id, credential_revision)
            admitted = self._tool_activity_sequences.get(key)
            if admitted is None or sequence > admitted.sequence:
                raise AgentMcpConnectionError("agent_mcp_tool_activity_stale")
            if sequence < admitted.sequence:
                # A newer concurrently admitted call owns the single bounded
                # public cursor. Its evidence must not be overwritten by a
                # late completion from the earlier call.
                return
            if (
                admitted.tool_name != tool_name
                or admitted.tool_source != source
                or admitted.completed_at is not None
            ):
                raise AgentMcpConnectionError("agent_mcp_tool_activity_stale")
            completed_at = self._now()
            connection = self._repository.get_connection(
                connection_id,
                now=completed_at,
            )
            if (
                connection is None
                or connection.state != "active"
                or connection.credential_revision != credential_revision
            ):
                raise AgentMcpConnectionError("agent_mcp_tool_activity_stale")
            self._repository.record_tool_call(
                connection_id,
                tool_name=tool_name,
                outcome=outcome,
                source=source,
                observed_at=completed_at,
            )
            confirmed = self._repository.get_connection(
                connection_id,
                now=completed_at,
            )
            if (
                confirmed is None
                or confirmed.state != "active"
                or confirmed.credential_revision != credential_revision
                or confirmed.last_tool_at != completed_at
                or confirmed.last_tool_name != tool_name
                or confirmed.last_tool_outcome != outcome
                or confirmed.last_tool_source != source
            ):
                raise AgentMcpConnectionError("agent_mcp_tool_activity_stale")
            self._tool_activity_sequences[key] = AgentMcpToolActivitySequence(
                connection_id=connection_id,
                credential_revision=credential_revision,
                sequence=sequence,
                tool_name=tool_name,
                tool_source=source,
                started_at=admitted.started_at,
                completed_at=completed_at,
                outcome=outcome,
            )

    def record_tool_call(
        self,
        connection_id: str,
        *,
        credential_revision: int,
        tool_name: str,
        outcome: AgentMcpToolOutcome,
        source: AgentMcpToolSource,
    ) -> None:
        sequence = self.begin_tool_call(
            connection_id,
            credential_revision=credential_revision,
            tool_name=tool_name,
            source=source,
        )
        self.finish_tool_call(
            connection_id,
            credential_revision=credential_revision,
            sequence=sequence,
            tool_name=tool_name,
            outcome=outcome,
            source=source,
        )


__all__ = (
    "AGENT_MCP_BEARER_ENV",
    "AGENT_MCP_CONNECTION_CONTRACT_VERSION",
    "AGENT_MCP_DEFAULT_EXPIRY_DAYS",
    "AGENT_MCP_HTTP_PATH",
    "AGENT_MCP_MANAGEMENT_CONTRACT_VERSION",
    "AGENT_MCP_MANAGEMENT_PATH",
    "AGENT_MCP_MAX_EXPIRY_DAYS",
    "AGENT_MCP_SCOPE_CONTRACT_VERSION",
    "AGENT_MCP_SETUP_CONTRACT_VERSION",
    "AGENT_MCP_SETUP_PATH",
    "AGENT_MCP_TOOL_ACTIVITY_SEQUENCE_CONTRACT_VERSION",
    "MAX_AGENT_MCP_CONNECTIONS",
    "AgentMcpClientKind",
    "AgentMcpClientSetup",
    "AgentMcpConnection",
    "AgentMcpConnectionCredential",
    "AgentMcpConnectionError",
    "AgentMcpConnectionList",
    "AgentMcpConnectionRepository",
    "AgentMcpConnectionService",
    "AgentMcpConnectionScope",
    "AgentMcpToolActivitySequence",
    "AgentMcpPrincipal",
    "AgentMcpToolOutcome",
    "AgentMcpToolSource",
    "CreateAgentMcpConnection",
    "RevokeAgentMcpConnection",
    "RotateAgentMcpConnection",
    "build_agent_mcp_setup_document",
    "_connection_state",
)
