"""Immutable, evidence-backed artifacts for authored local Agent chats.

Artifact metadata may be derived only from a reviewed write receipt or an
explicit native capture.  Bytes remain in the admitted workspace: every read
opens the exact relative path through the no-follow workspace boundary and
revalidates its digest before returning content.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
from typing import Literal, Protocol
import uuid

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .agent_document_previews import (
    DOCUMENT_MEDIA_TYPES,
    AgentDocumentPreview,
    AgentDocumentPreviewError,
    build_document_preview,
    classify_document_container,
)
from .agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentRetentionPolicy,
)
from .local_agent_receipts import AgentWriteReceipt
from .local_workspace_io import WorkspaceIO


AGENT_ARTIFACT_CONTRACT_VERSION = "agent-artifact.v3"
AGENT_ARTIFACT_PAGE_CONTRACT_VERSION = "agent-artifact-page.v1"
AGENT_ARTIFACT_CAPTURE_PREVIEW_CONTRACT_VERSION = (
    "agent-artifact-capture-preview.v1"
)
AGENT_ARTIFACT_EXPORT_CONTRACT_VERSION = "agent-artifact-export.v1"
MAX_AGENT_ARTIFACTS_PER_SESSION = 500
MAX_AGENT_ARTIFACT_VERSIONS_PER_SESSION = 2_000
MAX_AGENT_ARTIFACT_BYTES = 24 * 1024 * 1024
MAX_AGENT_ARTIFACT_LIST = 200
MAX_AGENT_ARTIFACT_PAGE_SIZE = 100
MAX_IMAGE_DIMENSION = 8_192
MAX_IMAGE_PIXELS = 33_554_432

_ID_PATTERN = r"^[0-9a-f]{32}$"
_SHA_PATTERN = r"^[0-9a-f]{64}$"

AgentArtifactKind = Literal[
    "code",
    "markdown",
    "text",
    "data",
    "image",
    "pdf",
    "document",
    "binary",
]
AgentArtifactPreviewKind = Literal[
    "text",
    "image",
    "pdf",
    "document",
    "download_only",
]
AgentArtifactProvenance = Literal[
    "reviewed_write",
    "reviewed_move",
    "verified_output",
    "generated_unverified",
    "external_effect_unknown",
]
AgentArtifactAvailability = Literal[
    "unchecked",
    "available",
    "stale",
    "missing",
    "malformed",
]
AgentArtifactLifecycleState = Literal["active", "archived", "removed"]
AgentArtifactListView = Literal["active", "archived", "removed", "all"]


class AgentArtifactError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _relative_path(value: str) -> str:
    windows, posix = PureWindowsPath(value), PurePosixPath(value)
    if (
        value in {".", ".."}
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("invalid artifact workspace path")
    return value


def _optional_title(value: str | None) -> str | None:
    if value is not None and (not value.strip() or value != value.strip()):
        raise ValueError("artifact title must be non-empty and trimmed")
    return value


def _default_title(path: str) -> str:
    return PurePosixPath(path).name[:120]


class PreviewAgentArtifactCapture(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    title: str | None = Field(default=None, min_length=1, max_length=120)

    _path = field_validator("path")(_relative_path)
    _title = field_validator("title")(_optional_title)


class CaptureAgentArtifact(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    expected_sha256: str = Field(pattern=_SHA_PATTERN)
    expected_byte_size: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACT_BYTES)
    title: str | None = Field(default=None, min_length=1, max_length=120)

    _path = field_validator("path")(_relative_path)
    _title = field_validator("title")(_optional_title)


class UpdateAgentArtifact(StrictModel):
    expected_revision: int = Field(strict=True, ge=1)
    operation: Literal["rename", "archive", "restore", "recover"]
    title: str | None = Field(default=None, min_length=1, max_length=120)

    _title = field_validator("title")(_optional_title)

    @model_validator(mode="after")
    def coherent_operation(self) -> "UpdateAgentArtifact":
        if (self.operation == "rename") != (self.title is not None):
            raise ValueError("artifact rename requires exactly one new title")
        return self


class RemoveAgentArtifact(StrictModel):
    expected_revision: int = Field(strict=True, ge=1)
    confirmation: Literal["move_archived_artifact_record_to_removed"]


class ExportAgentArtifact(StrictModel):
    """Select one exact artifact revision and version for a metadata export."""

    expected_revision: int = Field(strict=True, ge=1)
    version_id: str = Field(pattern=_ID_PATTERN)


class AgentArtifactCapturePreview(StrictModel):
    contract_version: Literal["agent-artifact-capture-preview.v1"] = (
        AGENT_ARTIFACT_CAPTURE_PREVIEW_CONTRACT_VERSION
    )
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=1024)
    title: str = Field(min_length=1, max_length=120)
    kind: AgentArtifactKind
    media_type: str = Field(min_length=1, max_length=128)
    preview_kind: AgentArtifactPreviewKind
    sha256: str = Field(pattern=_SHA_PATTERN)
    byte_size: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACT_BYTES)
    requires_native_confirmation: Literal[True] = True
    file_content_included: Literal[False] = False

    _path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def coherent_classification(self) -> "AgentArtifactCapturePreview":
        if (
            self.preview_kind == "image"
            and not self.media_type.startswith("image/")
        ) or (
            self.preview_kind == "pdf"
            and self.media_type != "application/pdf"
        ) or (
            self.preview_kind == "document"
            and self.media_type not in DOCUMENT_MEDIA_TYPES.values()
        ) or (
            self.preview_kind == "download_only"
            and self.media_type != "application/octet-stream"
        ):
            raise ValueError("artifact capture classification is incoherent")
        return self


class AgentArtifactVersion(StrictModel):
    contract_version: Literal["agent-artifact.v3"] = AGENT_ARTIFACT_CONTRACT_VERSION
    version_id: str = Field(pattern=_ID_PATTERN)
    artifact_id: str = Field(pattern=_ID_PATTERN)
    version_number: int = Field(strict=True, ge=1)
    created_at: datetime
    path: str = Field(min_length=1, max_length=1024)
    media_type: str = Field(min_length=1, max_length=128)
    preview_kind: AgentArtifactPreviewKind
    provenance: AgentArtifactProvenance
    sha256: str = Field(pattern=_SHA_PATTERN)
    byte_size: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACT_BYTES)
    source_turn_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    source_event_seq: int | None = Field(default=None, strict=True, ge=1)

    _path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def coherent_source(self) -> "AgentArtifactVersion":
        if self.provenance == "reviewed_write" and self.source_event_seq is None:
            raise ValueError("reviewed artifact versions require event provenance")
        if self.provenance == "reviewed_move" and (
            self.source_turn_id is not None or self.source_event_seq is not None
        ):
            raise ValueError("reviewed move versions do not claim conversation provenance")
        return self


class AgentArtifact(StrictModel):
    contract_version: Literal["agent-artifact.v3"] = AGENT_ARTIFACT_CONTRACT_VERSION
    artifact_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    kind: AgentArtifactKind
    path: str = Field(min_length=1, max_length=1024)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(strict=True, ge=1)
    version_count: int = Field(strict=True, ge=1)
    lifecycle_state: AgentArtifactLifecycleState = "active"
    archived_at: datetime | None = None
    removed_at: datetime | None = None
    availability: AgentArtifactAvailability = "unchecked"
    latest_version: AgentArtifactVersion

    _path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def coherent_latest(self) -> "AgentArtifact":
        if (
            self.latest_version.artifact_id != self.artifact_id
            or self.latest_version.path != self.path
            or self.latest_version.version_number != self.version_count
            or self.revision < self.version_count
            or self.updated_at < self.created_at
        ):
            raise ValueError("artifact head does not match its latest version")
        expected_state: AgentArtifactLifecycleState = (
            "removed"
            if self.removed_at is not None
            else "archived"
            if self.archived_at is not None
            else "active"
        )
        if (
            self.lifecycle_state != expected_state
            or (self.removed_at is not None and self.archived_at is None)
            or (
                self.archived_at is not None
                and self.archived_at < self.created_at
            )
            or (
                self.removed_at is not None
                and self.archived_at is not None
                and self.removed_at < self.archived_at
            )
            or (
                self.archived_at is not None
                and self.updated_at < self.archived_at
            )
            or (
                self.removed_at is not None
                and self.updated_at < self.removed_at
            )
        ):
            raise ValueError("artifact lifecycle is incoherent")
        return self


class AgentArtifactDetail(AgentArtifact):
    versions: tuple[AgentArtifactVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_versions(self) -> "AgentArtifactDetail":
        if (
            len(self.versions) != self.version_count
            or tuple(version.version_number for version in self.versions)
            != tuple(range(1, self.version_count + 1))
            or self.versions[-1] != self.latest_version
        ):
            raise ValueError("artifact version lineage is incomplete")
        return self


class AgentArtifactExportEvidence(StrictModel):
    verification: Literal["exact_current_workspace_readback"] = (
        "exact_current_workspace_readback"
    )
    algorithm: Literal["sha256"] = "sha256"
    sha256: str = Field(pattern=_SHA_PATTERN)
    byte_size: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACT_BYTES)
    verified: Literal[True] = True


class AgentArtifactExport(StrictModel):
    """Portable lineage metadata created only after exact local byte read-back.

    The export deliberately contains no file bytes and no absolute workspace
    path.  The separately labelled Download action remains the only byte export.
    """

    contract_version: Literal["agent-artifact-export.v1"] = (
        AGENT_ARTIFACT_EXPORT_CONTRACT_VERSION
    )
    exported_at: datetime
    artifact: AgentArtifactDetail
    selected_version: AgentArtifactVersion
    evidence: AgentArtifactExportEvidence
    content_included: Literal[False] = False
    absolute_path_included: Literal[False] = False
    sensitivity: Literal["sensitive_local_metadata"] = "sensitive_local_metadata"

    @model_validator(mode="after")
    def coherent_lineage(self) -> "AgentArtifactExport":
        selected = tuple(
            version
            for version in self.artifact.versions
            if version.version_id == self.selected_version.version_id
        )
        if (
            len(selected) != 1
            or selected[0] != self.selected_version
            or self.evidence.sha256 != self.selected_version.sha256
            or self.evidence.byte_size != self.selected_version.byte_size
            or self.artifact.lifecycle_state == "removed"
        ):
            raise ValueError("artifact export evidence does not match its lineage")
        return self


class AgentArtifactLifecycleCounts(StrictModel):
    active: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)
    archived: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)
    removed: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)
    total: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)

    @model_validator(mode="after")
    def coherent_total(self) -> "AgentArtifactLifecycleCounts":
        if self.total != self.active + self.archived + self.removed:
            raise ValueError("artifact lifecycle counts are incoherent")
        return self


class AgentArtifactList(StrictModel):
    contract_version: Literal["agent-artifact.v3"] = AGENT_ARTIFACT_CONTRACT_VERSION
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    view: AgentArtifactListView = "active"
    counts: AgentArtifactLifecycleCounts
    artifacts: tuple[AgentArtifact, ...]

    @model_validator(mode="after")
    def coherent_view(self) -> "AgentArtifactList":
        if self.view != "all" and any(
            artifact.lifecycle_state != self.view for artifact in self.artifacts
        ):
            raise ValueError("artifact list contains an item outside its lifecycle view")
        count = self.counts.total if self.view == "all" else getattr(self.counts, self.view)
        if len(self.artifacts) > count:
            raise ValueError("artifact list exceeds its lifecycle count")
        return self


class AgentArtifactPage(StrictModel):
    contract_version: Literal["agent-artifact-page.v1"] = (
        AGENT_ARTIFACT_PAGE_CONTRACT_VERSION
    )
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    view: AgentArtifactListView = "active"
    snapshot: str = Field(pattern=_SHA_PATTERN)
    limit: int = Field(strict=True, ge=1, le=MAX_AGENT_ARTIFACT_PAGE_SIZE)
    offset: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)
    total: int = Field(strict=True, ge=0, le=MAX_AGENT_ARTIFACTS_PER_SESSION)
    next_offset: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=MAX_AGENT_ARTIFACTS_PER_SESSION,
    )
    complete: bool
    counts: AgentArtifactLifecycleCounts
    artifacts: tuple[AgentArtifact, ...] = Field(
        max_length=MAX_AGENT_ARTIFACT_PAGE_SIZE
    )

    @model_validator(mode="after")
    def coherent_page(self) -> "AgentArtifactPage":
        expected_total = (
            self.counts.total
            if self.view == "all"
            else getattr(self.counts, self.view)
        )
        if self.total != expected_total or self.offset > self.total:
            raise ValueError("artifact page total is incoherent")
        expected_count = min(self.limit, self.total - self.offset)
        if len(self.artifacts) != expected_count:
            raise ValueError("artifact page does not contain the exact requested slice")
        expected_next = (
            self.offset + len(self.artifacts)
            if self.offset + len(self.artifacts) < self.total
            else None
        )
        if self.next_offset != expected_next or self.complete != (expected_next is None):
            raise ValueError("artifact page continuation metadata is incoherent")
        if self.view != "all" and any(
            artifact.lifecycle_state != self.view for artifact in self.artifacts
        ):
            raise ValueError("artifact page contains an item outside its lifecycle view")
        if len({artifact.artifact_id for artifact in self.artifacts}) != len(
            self.artifacts
        ):
            raise ValueError("artifact page contains duplicate identifiers")
        return self


@dataclass(frozen=True, slots=True)
class AgentArtifactContent:
    version: AgentArtifactVersion
    payload: bytes
    content_type: str
    filename: str


class AgentArtifactRepository(Protocol):
    def upsert_version(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
        title: str,
        kind: AgentArtifactKind,
        version: AgentArtifactVersion,
    ) -> AgentArtifact: ...

    def list_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
    ) -> tuple[tuple[AgentArtifact, ...], AgentArtifactLifecycleCounts]: ...

    def page_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[
        tuple[AgentArtifact, ...],
        AgentArtifactLifecycleCounts,
        int,
        str,
    ]: ...

    def get_artifact_by_path(
        self,
        *,
        project_id: str,
        session_id: str,
        path: str,
    ) -> AgentArtifact | None: ...

    def relocate_version(
        self,
        *,
        project_id: str,
        session_id: str,
        source_path: str,
        target_path: str,
        expected_artifact_id: str,
        expected_artifact_revision: int,
        title: str,
        kind: AgentArtifactKind,
        version: AgentArtifactVersion,
    ) -> AgentArtifact: ...

    def get_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
    ) -> AgentArtifactDetail | None: ...

    def get_version(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
    ) -> AgentArtifactVersion | None: ...

    def update_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: UpdateAgentArtifact,
        changed_at: datetime,
    ) -> AgentArtifact: ...

    def remove_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        expected_revision: int,
        removed_at: datetime,
    ) -> AgentArtifact: ...


_CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".java",
    ".js", ".jsx", ".kt", ".lua", ".php", ".ps1", ".py", ".rb", ".rs",
    ".scss", ".sh", ".sql", ".swift", ".toml", ".ts", ".tsx", ".vue",
}
_DATA_SUFFIXES = {".csv", ".json", ".jsonl", ".tsv", ".yaml", ".yml"}
_DOCUMENT_SUFFIXES = {".doc", ".docx", ".odt", ".ppt", ".pptx", ".xls", ".xlsx"}
_ACTIVE_SUFFIXES = {".html", ".htm", ".svg", ".xml"}


def _path_classification(path: str) -> tuple[AgentArtifactKind, str, AgentArtifactPreviewKind]:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in {".md", ".markdown"}:
        return "markdown", "text/markdown; charset=utf-8", "text"
    if suffix in _CODE_SUFFIXES:
        return "code", "text/plain; charset=utf-8", "text"
    if suffix in _DATA_SUFFIXES:
        return "data", "text/plain; charset=utf-8", "text"
    if suffix == ".pdf":
        return "pdf", "application/pdf", "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".gif"}:
        media = {".png": "image/png", ".gif": "image/gif"}.get(suffix, "image/jpeg")
        return "image", media, "image"
    if suffix in _DOCUMENT_SUFFIXES:
        return "document", "application/octet-stream", "download_only"
    if suffix in _ACTIVE_SUFFIXES:
        return "document", "application/octet-stream", "download_only"
    return "text", "text/plain; charset=utf-8", "text"


def _validated_image_type(payload: bytes) -> str | None:
    width: int | None = None
    height: int | None = None
    media: str | None = None
    if len(payload) >= 24 and payload.startswith(b"\x89PNG\r\n\x1a\n") and payload[12:16] == b"IHDR":
        width, height = struct.unpack(">II", payload[16:24])
        media = "image/png"
    elif len(payload) >= 10 and payload[:6] in {b"GIF87a", b"GIF89a"}:
        width, height = struct.unpack("<HH", payload[6:10])
        media = "image/gif"
    elif len(payload) >= 4 and payload.startswith(b"\xff\xd8"):
        index = 2
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while index + 4 <= len(payload):
            if payload[index] != 0xFF:
                index += 1
                continue
            while index < len(payload) and payload[index] == 0xFF:
                index += 1
            if index >= len(payload):
                break
            marker = payload[index]
            index += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(payload):
                break
            length = int.from_bytes(payload[index:index + 2], "big")
            if length < 2 or index + length > len(payload):
                break
            if marker in sof and length >= 7:
                height = int.from_bytes(payload[index + 3:index + 5], "big")
                width = int.from_bytes(payload[index + 5:index + 7], "big")
                media = "image/jpeg"
                break
            index += length
    if (
        media is None
        or width is None
        or height is None
        or width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        return None
    return media


def _validated_pdf(payload: bytes) -> bool:
    """Admit only a bounded, unencrypted PDF-shaped revision for rendering.

    This is deliberately a conservative admission check, not a PDF parser.
    The pinned local PDF.js renderer remains the structural parser.  Encryption
    is refused before bytes reach that renderer so it can never open a password
    workflow, while malformed or truncated PDF-looking files stay available
    only through the explicit inert download path.
    """

    if len(payload) < 20 or payload[5:8] not in {
        b"1.0", b"1.1", b"1.2", b"1.3", b"1.4",
        b"1.5", b"1.6", b"1.7", b"2.0",
    }:
        return False
    if not payload.startswith(b"%PDF-") or payload[8:9] not in {b"\r", b"\n"}:
        return False
    eof = payload.rfind(b"%%EOF")
    if eof < 9 or eof < len(payload) - 1_024:
        return False
    if payload[eof + len(b"%%EOF"):].strip(b" \t\r\n\f\x00"):
        return False
    # A standard or cross-reference-stream trailer names the encryption
    # dictionary with /Encrypt. Refuse conservatively even if that byte pattern
    # occurs in an unusual stream: false-negative encryption is the unsafe side.
    encrypted = payload.find(b"/Encrypt")
    while encrypted >= 0:
        boundary = encrypted + len(b"/Encrypt")
        if boundary == len(payload) or payload[boundary] in b" \t\r\n\f\x00()<>[]{}/%":
            return False
        encrypted = payload.find(b"/Encrypt", boundary)
    # Every useful PDF has at least one indirect object. Requiring a terminated
    # object catches common header/EOF spoofing without attempting active repair.
    return b" obj" in payload[9:eof] and b"endobj" in payload[9:eof]


def _classification(path: str, payload: bytes) -> tuple[AgentArtifactKind, str, AgentArtifactPreviewKind]:
    image_type = _validated_image_type(payload)
    if image_type is not None:
        return "image", image_type, "image"
    if _validated_pdf(payload):
        return "pdf", "application/pdf", "pdf"
    document = classify_document_container(path, payload)
    if document is not None:
        document_format, media_type = document
        if DOCUMENT_MEDIA_TYPES[document_format] != media_type:
            return "document", "application/octet-stream", "download_only"
        return "document", media_type, "document"
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        kind, media_type, preview = _path_classification(path)
        if kind == "document":
            return kind, media_type, preview
        return "binary", "application/octet-stream", "download_only"
    if "\x00" in text:
        return "binary", "application/octet-stream", "download_only"
    kind, media_type, preview = _path_classification(path)
    if kind in {"image", "pdf"}:
        return "binary", "application/octet-stream", "download_only"
    return kind, media_type, preview


class AgentArtifactService:
    def __init__(
        self,
        repository: AgentArtifactRepository,
        catalog: AgentCatalogService,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def _id(self) -> str:
        value = self._id_factory()
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            raise AgentArtifactError("agent_artifact_id_invalid")
        return value

    def _session(self, project_id: str, session_id: str):
        try:
            record = self._catalog.get_session(session_id)
        except AgentCatalogError as error:
            raise AgentArtifactError(error.code) from None
        if record.project_id != project_id:
            raise AgentArtifactError("agent_catalog_session_not_found")
        if record.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY:
            raise AgentArtifactError("agent_artifact_retention_required")
        return record

    def sync_reviewed_writes(self, *, project_id: str, session_id: str) -> None:
        self._session(project_id, session_id)
        try:
            history = self._catalog.load_history(project_id=project_id, session_id=session_id)
        except AgentCatalogError as error:
            raise AgentArtifactError(error.code) from None
        for event in history.events:
            receipt = event.write_receipt
            if (
                event.kind != "tool_result"
                or receipt is None
                or receipt.state != "verified"
                or receipt.after_sha256 is None
                or receipt.byte_size is None
            ):
                continue
            kind, media_type, preview_kind = _path_classification(receipt.path)
            # Reviewed ``write_file`` receipts prove an exact UTF-8 byte
            # revision, but they do not prove that a binary-looking suffix is
            # a well-formed image or PDF.  Keep those receipts downloadable
            # until an explicit capture validates the file magic and bounds.
            if kind in {"image", "pdf"}:
                kind = "binary"
                media_type = "application/octet-stream"
                preview_kind = "download_only"
            created_at = event.at
            version_id = self._id()
            artifact_id = self._id()
            version = AgentArtifactVersion(
                version_id=version_id,
                artifact_id=artifact_id,
                version_number=1,
                created_at=created_at,
                path=receipt.path,
                media_type=media_type,
                preview_kind=preview_kind,
                provenance="reviewed_write",
                sha256=receipt.after_sha256,
                byte_size=receipt.byte_size,
                source_turn_id=event.turn_id,
                source_event_seq=event.seq,
            )
            try:
                self._repository.upsert_version(
                    project_id=project_id,
                    session_id=session_id,
                    artifact_id=artifact_id,
                    version_id=version_id,
                    title=PurePosixPath(receipt.path).name,
                    kind=kind,
                    version=version,
                )
            except AgentArtifactError as error:
                if error.code not in {
                    "agent_artifact_source_exists",
                    "agent_artifact_removed",
                }:
                    raise

    def relocate_reviewed_file(
        self,
        *,
        project_id: str,
        session_id: str,
        workspace: Path,
        source_path: str,
        target_path: str,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> AgentArtifact | None:
        """Advance one exact tracked artifact after a verified reviewed move.

        A move is represented as another immutable version rather than a
        rewrite of earlier provenance. Files whose latest artifact revision no
        longer matches the reviewed bytes are intentionally left untouched.
        """

        self._session(project_id, session_id)
        try:
            source_path = _relative_path(source_path)
            target_path = _relative_path(target_path)
        except ValueError:
            raise AgentArtifactError("agent_artifact_path_invalid") from None
        if source_path == target_path:
            raise AgentArtifactError("agent_artifact_relocation_invalid")
        self.sync_reviewed_writes(project_id=project_id, session_id=session_id)
        source = self._repository.get_artifact_by_path(
            project_id=project_id,
            session_id=session_id,
            path=source_path,
        )
        if source is None:
            return None
        if (
            source.latest_version.sha256 != expected_sha256
            or source.latest_version.byte_size != expected_byte_size
        ):
            return None

        try:
            payload = self._read(workspace, target_path)
        except AgentArtifactError:
            raise AgentArtifactError("agent_artifact_relocation_unverified") from None
        if (
            len(payload) != expected_byte_size
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise AgentArtifactError("agent_artifact_relocation_unverified")
        kind, media_type, preview_kind = _classification(target_path, payload)
        created_at = self._clock()
        version = AgentArtifactVersion(
            version_id=self._id(),
            artifact_id=source.artifact_id,
            version_number=source.version_count + 1,
            created_at=created_at,
            path=target_path,
            media_type=media_type,
            preview_kind=preview_kind,
            provenance="reviewed_move",
            sha256=expected_sha256,
            byte_size=expected_byte_size,
        )
        title = (
            _default_title(target_path)
            if source.title == _default_title(source_path)
            else source.title
        )
        try:
            return self._repository.relocate_version(
                project_id=project_id,
                session_id=session_id,
                source_path=source_path,
                target_path=target_path,
                expected_artifact_id=source.artifact_id,
                expected_artifact_revision=source.revision,
                title=title,
                kind=kind,
                version=version,
            )
        except AgentArtifactError as error:
            if error.code.startswith("agent_artifact_relocation_"):
                raise
            raise AgentArtifactError("agent_artifact_relocation_unverified") from None

    def list_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView = "active",
        limit: int = MAX_AGENT_ARTIFACT_LIST,
    ) -> AgentArtifactList:
        self.sync_reviewed_writes(project_id=project_id, session_id=session_id)
        artifacts, counts = self._repository.list_artifacts(
            project_id=project_id,
            session_id=session_id,
            view=view,
            limit=min(MAX_AGENT_ARTIFACT_LIST, max(1, limit)),
        )
        return AgentArtifactList(
            project_id=project_id,
            session_id=session_id,
            view=view,
            counts=counts,
            artifacts=artifacts,
        )

    def page_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView = "active",
        limit: int = MAX_AGENT_ARTIFACT_PAGE_SIZE,
        offset: int = 0,
        snapshot: str | None = None,
    ) -> AgentArtifactPage:
        if limit < 1 or limit > MAX_AGENT_ARTIFACT_PAGE_SIZE:
            raise AgentArtifactError("agent_artifact_page_invalid")
        if offset < 0 or offset > MAX_AGENT_ARTIFACTS_PER_SESSION:
            raise AgentArtifactError("agent_artifact_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentArtifactError("agent_artifact_page_snapshot_required")
        self.sync_reviewed_writes(project_id=project_id, session_id=session_id)
        artifacts, counts, total, current_snapshot = self._repository.page_artifacts(
            project_id=project_id,
            session_id=session_id,
            view=view,
            limit=limit,
            offset=offset,
            snapshot=snapshot,
        )
        next_offset = offset + len(artifacts) if offset + len(artifacts) < total else None
        return AgentArtifactPage(
            project_id=project_id,
            session_id=session_id,
            view=view,
            snapshot=current_snapshot,
            limit=limit,
            offset=offset,
            total=total,
            next_offset=next_offset,
            complete=next_offset is None,
            counts=counts,
            artifacts=artifacts,
        )

    def update_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: UpdateAgentArtifact,
    ) -> AgentArtifact:
        self._session(project_id, session_id)
        return self._repository.update_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            command=command,
            changed_at=self._clock(),
        )

    def remove_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: RemoveAgentArtifact,
    ) -> AgentArtifact:
        self._session(project_id, session_id)
        return self._repository.remove_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            expected_revision=command.expected_revision,
            removed_at=self._clock(),
        )

    def get_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        workspace: Path,
    ) -> AgentArtifactDetail:
        self.sync_reviewed_writes(project_id=project_id, session_id=session_id)
        detail = self._repository.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )
        if detail is None:
            raise AgentArtifactError("agent_artifact_not_found")
        if detail.lifecycle_state == "removed":
            raise AgentArtifactError("agent_artifact_removed")
        availability = self._availability(workspace, detail.latest_version)
        return detail.model_copy(update={"availability": availability})

    def capture(
        self,
        *,
        project_id: str,
        session_id: str,
        workspace: Path,
        command: CaptureAgentArtifact,
    ) -> AgentArtifactDetail:
        self._session(project_id, session_id)
        payload = self._read(workspace, command.path)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != command.expected_sha256 or len(payload) != command.expected_byte_size:
            raise AgentArtifactError("agent_artifact_revision_changed")
        kind, media_type, preview_kind = _classification(command.path, payload)
        now = self._clock()
        artifact_id = self._id()
        version_id = self._id()
        version = AgentArtifactVersion(
            version_id=version_id,
            artifact_id=artifact_id,
            version_number=1,
            created_at=now,
            path=command.path,
            media_type=media_type,
            preview_kind=preview_kind,
            provenance="verified_output",
            sha256=digest,
            byte_size=len(payload),
        )
        stored = self._repository.upsert_version(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=version_id,
            title=command.title or _default_title(command.path),
            kind=kind,
            version=version,
        )
        detail = self._repository.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=stored.artifact_id,
        )
        if detail is None:
            raise AgentArtifactError("agent_artifact_storage_unavailable")
        return detail.model_copy(update={"availability": "available"})

    def preview_capture(
        self,
        *,
        project_id: str,
        session_id: str,
        workspace: Path,
        command: PreviewAgentArtifactCapture,
    ) -> AgentArtifactCapturePreview:
        """Inspect one exact workspace revision without returning its bytes."""

        self._session(project_id, session_id)
        existing = self._repository.get_artifact_by_path(
            project_id=project_id,
            session_id=session_id,
            path=command.path,
        )
        if existing is not None and existing.lifecycle_state == "removed":
            raise AgentArtifactError("agent_artifact_removed")
        payload = self._read(workspace, command.path)
        kind, media_type, preview_kind = _classification(command.path, payload)
        return AgentArtifactCapturePreview(
            project_id=project_id,
            session_id=session_id,
            path=command.path,
            title=command.title or _default_title(command.path),
            kind=kind,
            media_type=media_type,
            preview_kind=preview_kind,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    def content(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
        workspace: Path,
        download: bool,
    ) -> AgentArtifactContent:
        self._session(project_id, session_id)
        artifact = self._repository.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )
        if artifact is None:
            raise AgentArtifactError("agent_artifact_not_found")
        if artifact.lifecycle_state == "removed":
            raise AgentArtifactError("agent_artifact_removed")
        version = self._repository.get_version(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=version_id,
        )
        if version is None:
            raise AgentArtifactError("agent_artifact_version_not_found")
        payload = self._read(workspace, version.path)
        if len(payload) != version.byte_size or hashlib.sha256(payload).hexdigest() != version.sha256:
            raise AgentArtifactError("agent_artifact_stale")
        kind, media_type, preview_kind = _classification(version.path, payload)
        if preview_kind != version.preview_kind or kind == "binary" and version.preview_kind != "download_only":
            raise AgentArtifactError("agent_artifact_malformed")
        if not download and preview_kind in {"document", "download_only"}:
            raise AgentArtifactError("agent_artifact_preview_unsupported")
        content_type = "application/octet-stream" if download else (
            "text/plain; charset=utf-8" if preview_kind == "text" else media_type
        )
        candidate_suffix = PurePosixPath(version.path).suffix
        suffix = (
            candidate_suffix
            if download
            and 2 <= len(candidate_suffix) <= 16
            and candidate_suffix[0] == "."
            and candidate_suffix[1:].isascii()
            and candidate_suffix[1:].isalnum()
            else ""
        )
        return AgentArtifactContent(
            version=version,
            payload=payload,
            content_type=content_type,
            filename=f"agent-artifact-{artifact_id[:8]}{suffix}",
        )

    def export_lineage(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        workspace: Path,
        command: ExportAgentArtifact,
    ) -> AgentArtifactExport:
        """Export metadata only after re-reading the exact selected bytes."""

        detail = self.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            workspace=workspace,
        )
        if detail.revision != command.expected_revision:
            raise AgentArtifactError("agent_artifact_revision_conflict")
        selected = next(
            (
                version
                for version in detail.versions
                if version.version_id == command.version_id
            ),
            None,
        )
        if selected is None:
            raise AgentArtifactError("agent_artifact_version_not_found")
        content = self.content(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=selected.version_id,
            workspace=workspace,
            download=True,
        )
        if content.version != selected:
            raise AgentArtifactError("agent_artifact_stale")
        current = self.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            workspace=workspace,
        )
        if current.revision != command.expected_revision:
            raise AgentArtifactError("agent_artifact_revision_conflict")
        if current != detail:
            if current.availability != detail.availability:
                raise AgentArtifactError("agent_artifact_stale")
            raise AgentArtifactError("agent_artifact_revision_conflict")
        return AgentArtifactExport(
            exported_at=self._clock(),
            artifact=detail,
            selected_version=selected,
            evidence=AgentArtifactExportEvidence(
                sha256=hashlib.sha256(content.payload).hexdigest(),
                byte_size=len(content.payload),
            ),
        )

    def document_preview(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
        workspace: Path,
    ) -> AgentDocumentPreview:
        self._session(project_id, session_id)
        artifact = self._repository.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )
        if artifact is None:
            raise AgentArtifactError("agent_artifact_not_found")
        if artifact.lifecycle_state == "removed":
            raise AgentArtifactError("agent_artifact_removed")
        version = self._repository.get_version(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=version_id,
        )
        if version is None:
            raise AgentArtifactError("agent_artifact_version_not_found")
        payload = self._read(workspace, version.path)
        if len(payload) != version.byte_size or hashlib.sha256(payload).hexdigest() != version.sha256:
            raise AgentArtifactError("agent_artifact_stale")
        kind, media_type, preview_kind = _classification(version.path, payload)
        if (
            kind != "document"
            or preview_kind != "document"
            or preview_kind != version.preview_kind
            or media_type != version.media_type
        ):
            raise AgentArtifactError("agent_artifact_preview_unsupported")
        try:
            return build_document_preview(
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
                version_id=version_id,
                source_sha256=version.sha256,
                source_byte_size=version.byte_size,
                path=version.path,
                payload=payload,
            )
        except AgentDocumentPreviewError:
            raise AgentArtifactError("agent_artifact_malformed") from None

    @staticmethod
    def _read(workspace: Path, relative_path: str) -> bytes:
        try:
            inspected = WorkspaceIO(workspace).read(
                workspace / Path(*PurePosixPath(relative_path).parts),
                limit=MAX_AGENT_ARTIFACT_BYTES,
            )
            return inspected.payload
        except Exception as error:
            if isinstance(error, (FileNotFoundError, NotADirectoryError)):
                raise AgentArtifactError("agent_artifact_missing") from None
            code = getattr(error, "code", "agent_artifact_unavailable")
            if code in {"workspace_file_unavailable", "workspace_path_not_found"}:
                raise AgentArtifactError("agent_artifact_missing") from None
            if code == "workspace_file_too_large":
                raise AgentArtifactError("agent_artifact_too_large") from None
            if code in {
                "path_outside_workspace",
                "workspace_link_or_reparse_refused",
                "workspace_root_changed",
                "workspace_file_changed",
            }:
                raise AgentArtifactError(code) from None
            if isinstance(error, AgentArtifactError):
                raise
            raise AgentArtifactError("agent_artifact_unavailable") from None

    def _availability(
        self,
        workspace: Path,
        version: AgentArtifactVersion,
    ) -> AgentArtifactAvailability:
        try:
            payload = self._read(workspace, version.path)
        except AgentArtifactError as error:
            return "missing" if error.code == "agent_artifact_missing" else "stale"
        if len(payload) != version.byte_size or hashlib.sha256(payload).hexdigest() != version.sha256:
            return "stale"
        kind, _media_type, preview_kind = _classification(version.path, payload)
        if kind == "binary" and version.preview_kind != "download_only":
            return "malformed"
        if preview_kind != version.preview_kind:
            return "malformed"
        return "available"


__all__ = (
    "AGENT_ARTIFACT_CONTRACT_VERSION",
    "AGENT_ARTIFACT_PAGE_CONTRACT_VERSION",
    "AGENT_ARTIFACT_CAPTURE_PREVIEW_CONTRACT_VERSION",
    "AGENT_ARTIFACT_EXPORT_CONTRACT_VERSION",
    "MAX_AGENT_ARTIFACTS_PER_SESSION",
    "MAX_AGENT_ARTIFACT_VERSIONS_PER_SESSION",
    "MAX_AGENT_ARTIFACT_BYTES",
    "MAX_AGENT_ARTIFACT_PAGE_SIZE",
    "AgentArtifact",
    "AgentArtifactAvailability",
    "AgentArtifactCapturePreview",
    "AgentArtifactContent",
    "AgentArtifactExport",
    "AgentArtifactExportEvidence",
    "AgentArtifactDetail",
    "AgentArtifactError",
    "AgentArtifactKind",
    "AgentArtifactLifecycleCounts",
    "AgentArtifactLifecycleState",
    "AgentArtifactList",
    "AgentArtifactListView",
    "AgentArtifactPage",
    "AgentArtifactPreviewKind",
    "AgentArtifactProvenance",
    "AgentArtifactRepository",
    "AgentArtifactService",
    "AgentArtifactVersion",
    "AgentDocumentPreview",
    "CaptureAgentArtifact",
    "ExportAgentArtifact",
    "PreviewAgentArtifactCapture",
    "RemoveAgentArtifact",
    "UpdateAgentArtifact",
)
