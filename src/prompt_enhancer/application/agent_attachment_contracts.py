"""Strict public contracts for private local Agent message attachments.

Attachment bytes never appear in these contracts.  The public metadata is
safe to place in the bounded Agent event journal; payloads stay behind the
dedicated local attachment repository.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel


AGENT_ATTACHMENT_CONTRACT_VERSION = "agent-attachment.v2"
LEGACY_AGENT_ATTACHMENT_CONTRACT_VERSION = "agent-attachment.v1"
AGENT_ATTACHMENT_DOCUMENT_PREVIEW_CONTRACT_VERSION = (
    "agent-attachment-document-preview.v1"
)
MAX_AGENT_MESSAGE_ATTACHMENTS = 4
MAX_AGENT_STAGED_ATTACHMENTS = 16
MAX_AGENT_ATTACHMENT_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_AGENT_ATTACHMENT_SESSION_BYTES = 64 * 1024 * 1024
MAX_AGENT_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AGENT_AUDIO_BYTES = 12 * 1024 * 1024
MAX_AGENT_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_AGENT_TEXT_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS = 100_000
MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS = 12_000
MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS = 200_000
MAX_AGENT_IMAGE_DIMENSION = 8_192
MAX_AGENT_IMAGE_PIXELS = 33_554_432
MAX_AGENT_AUDIO_DURATION_MS = 5 * 60 * 1_000
MAX_AGENT_ATTACHMENT_NAME_CHARS = 120
MAX_AGENT_ATTACHMENT_BASE64_CHARS = ((MAX_AGENT_AUDIO_BYTES + 2) // 3) * 4

_ID_PATTERN = r"^[0-9a-f]{32}$"
_SHA_PATTERN = r"^[0-9a-f]{64}$"

AgentAttachmentKind = Literal["image", "audio", "document"]
AgentAttachmentSource = Literal["file", "microphone", "external_agent"]
AgentAttachmentState = Literal["staged", "attached"]
AgentAttachmentRetention = Literal["memory_only", "local_history"]
AgentAttachmentRouting = Literal["native_multimodal", "local_text_projection"]
AgentAttachmentDocumentFormat = Literal[
    "plain_text",
    "markdown",
    "json",
    "csv",
    "tsv",
    "docx",
    "pptx",
    "xlsx",
    "odt",
]
AgentAttachmentOmittedFeature = Literal[
    "comments",
    "embedded_objects",
    "external_links",
    "macros",
    "media",
    "notes",
]
AgentAttachmentMediaType = Literal[
    "image/png",
    "image/jpeg",
    "audio/wav",
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.text",
]

AGENT_DOCUMENT_MEDIA_TYPES: dict[AgentAttachmentDocumentFormat, AgentAttachmentMediaType] = {
    "plain_text": "text/plain",
    "markdown": "text/markdown",
    "json": "application/json",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "odt": "application/vnd.oasis.opendocument.text",
}


def safe_attachment_name(value: str) -> str:
    """Return a display-only basename; never admit a path or control text."""

    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > MAX_AGENT_ATTACHMENT_NAME_CHARS
        or "/" in candidate
        or "\\" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        raise ValueError("invalid attachment display name")
    return candidate


class StageAgentAttachment(StrictModel):
    display_name: str = Field(min_length=1, max_length=MAX_AGENT_ATTACHMENT_NAME_CHARS)
    source: AgentAttachmentSource = "file"

    _display_name = field_validator("display_name")(safe_attachment_name)


class StageInlineAgentAttachment(StrictModel):
    """One path-free attachment supplied by an authenticated controller.

    The caller declares byte length and digest so the loopback endpoint can
    reject truncated, altered, or ambiguously encoded tool arguments before
    the private attachment vault sees them.  The request deliberately has no
    filesystem path, URL, attachment identifier, or source-authority field.
    """

    display_name: str = Field(min_length=1, max_length=MAX_AGENT_ATTACHMENT_NAME_CHARS)
    media_type: AgentAttachmentMediaType
    byte_size: int = Field(strict=True, ge=1, le=MAX_AGENT_AUDIO_BYTES)
    sha256: str = Field(pattern=_SHA_PATTERN)
    data_base64: str = Field(min_length=4, max_length=MAX_AGENT_ATTACHMENT_BASE64_CHARS)

    _display_name = field_validator("display_name")(safe_attachment_name)

    @model_validator(mode="after")
    def coherent_encoding(self) -> "StageInlineAgentAttachment":
        if len(self.data_base64) != ((self.byte_size + 2) // 3) * 4:
            raise ValueError("attachment base64 length does not match byte size")
        try:
            encoded = self.data_base64.encode("ascii")
            payload = base64.b64decode(encoded, validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            raise ValueError("attachment base64 is invalid") from None
        if (
            len(payload) != self.byte_size
            or hashlib.sha256(payload).hexdigest() != self.sha256
        ):
            raise ValueError("attachment integrity declaration does not match payload")
        return self

    def payload(self) -> bytes:
        """Decode the already-validated bounded payload for local admission."""

        return base64.b64decode(self.data_base64.encode("ascii"), validate=True)


class AgentMessageAttachment(StrictModel):
    """Payload-free identity retained beside one user message."""

    contract_version: Literal["agent-attachment.v2"] = AGENT_ATTACHMENT_CONTRACT_VERSION
    attachment_id: str = Field(pattern=_ID_PATTERN)
    kind: AgentAttachmentKind
    media_type: AgentAttachmentMediaType
    display_name: str = Field(min_length=1, max_length=MAX_AGENT_ATTACHMENT_NAME_CHARS)
    sha256: str = Field(pattern=_SHA_PATTERN)
    byte_size: int = Field(strict=True, ge=1, le=MAX_AGENT_AUDIO_BYTES)
    width: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_IMAGE_DIMENSION)
    height: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_IMAGE_DIMENSION)
    duration_ms: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_AUDIO_DURATION_MS)
    sample_rate_hz: int | None = Field(default=None, strict=True, ge=8_000, le=48_000)
    channels: int | None = Field(default=None, strict=True, ge=1, le=2)
    routing: AgentAttachmentRouting = "native_multimodal"
    document_format: AgentAttachmentDocumentFormat | None = None
    projected_characters: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS,
    )
    projection_truncated: bool | None = None
    omitted_features: tuple[AgentAttachmentOmittedFeature, ...] = Field(
        default=(),
        max_length=6,
    )
    context_tokens: None = None
    context_cost_source: Literal["runtime_unreported"] = "runtime_unreported"

    _display_name = field_validator("display_name")(safe_attachment_name)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_media_metadata(cls, value: Any) -> Any:
        """Normalize retained v1 image/audio metadata without rewriting history."""

        if not isinstance(value, dict) or value.get("contract_version") != (
            LEGACY_AGENT_ATTACHMENT_CONTRACT_VERSION
        ):
            return value
        new_fields = {
            "routing",
            "document_format",
            "projected_characters",
            "projection_truncated",
            "omitted_features",
        }
        if any(field in value for field in new_fields):
            raise ValueError("legacy attachment metadata contains v2 fields")
        normalized = dict(value)
        normalized.update(
            contract_version=AGENT_ATTACHMENT_CONTRACT_VERSION,
            routing="native_multimodal",
            document_format=None,
            projected_characters=None,
            projection_truncated=None,
            omitted_features=(),
        )
        return normalized

    @model_validator(mode="after")
    def coherent_media(self) -> "AgentMessageAttachment":
        image_metadata = (self.width, self.height)
        audio_metadata = (self.duration_ms, self.sample_rate_hz, self.channels)
        if self.kind == "image":
            if self.media_type not in {"image/png", "image/jpeg"}:
                raise ValueError("image attachment media type is invalid")
            if any(value is None for value in image_metadata) or any(
                value is not None for value in audio_metadata
            ):
                raise ValueError("image attachment metadata is inconsistent")
            assert self.width is not None and self.height is not None
            if self.width * self.height > MAX_AGENT_IMAGE_PIXELS:
                raise ValueError("image attachment pixel count is too large")
            if self.byte_size > MAX_AGENT_IMAGE_BYTES:
                raise ValueError("image attachment byte count is too large")
            if (
                self.routing != "native_multimodal"
                or self.document_format is not None
                or self.projected_characters is not None
                or self.projection_truncated is not None
                or self.omitted_features
            ):
                raise ValueError("image attachment routing is inconsistent")
        elif self.kind == "audio":
            if self.media_type != "audio/wav":
                raise ValueError("audio attachment media type is invalid")
            if any(value is not None for value in image_metadata) or any(
                value is None for value in audio_metadata
            ):
                raise ValueError("audio attachment metadata is inconsistent")
            if (
                self.routing != "native_multimodal"
                or self.document_format is not None
                or self.projected_characters is not None
                or self.projection_truncated is not None
                or self.omitted_features
            ):
                raise ValueError("audio attachment routing is inconsistent")
        else:
            if (
                self.media_type not in set(AGENT_DOCUMENT_MEDIA_TYPES.values())
                or any(value is not None for value in (*image_metadata, *audio_metadata))
                or self.routing != "local_text_projection"
                or self.document_format is None
                or self.projected_characters is None
                or self.projection_truncated is None
                or AGENT_DOCUMENT_MEDIA_TYPES[self.document_format] != self.media_type
                or self.byte_size > MAX_AGENT_DOCUMENT_BYTES
            ):
                raise ValueError("document attachment metadata is inconsistent")
            if self.document_format in {"plain_text", "markdown", "json", "csv", "tsv"}:
                if self.omitted_features:
                    raise ValueError("plain document cannot report omitted container features")
            elif tuple(dict.fromkeys(self.omitted_features)) != self.omitted_features:
                raise ValueError("document omitted features must be unique")
        return self


class AgentAttachment(AgentMessageAttachment):
    """One private staged or message-bound attachment in the local vault."""

    session_id: str = Field(pattern=_ID_PATTERN)
    model_alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    capability_probe_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    source: AgentAttachmentSource
    state: AgentAttachmentState
    retention: AgentAttachmentRetention
    created_at: datetime
    expires_at: datetime | None = None
    attached_event_seq: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def coherent_state(self) -> "AgentAttachment":
        if self.state == "staged":
            if self.expires_at is None or self.attached_event_seq is not None:
                raise ValueError("staged attachment state is inconsistent")
        elif self.attached_event_seq is None:
            raise ValueError("attached attachment requires its user event")
        if self.retention == "local_history" and self.state == "attached" and self.expires_at is not None:
            raise ValueError("durable attached content must not silently expire")
        return self

    def message_metadata(self) -> AgentMessageAttachment:
        return AgentMessageAttachment.model_validate(
            self.model_dump(
                include=set(AgentMessageAttachment.model_fields),
                mode="json",
            )
        )


class AgentAttachmentDocumentPreview(StrictModel):
    """Private, no-store excerpt of one locally projected document."""

    contract_version: Literal["agent-attachment-document-preview.v1"] = (
        AGENT_ATTACHMENT_DOCUMENT_PREVIEW_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=_ID_PATTERN)
    attachment_id: str = Field(pattern=_ID_PATTERN)
    sha256: str = Field(pattern=_SHA_PATTERN)
    media_type: AgentAttachmentMediaType
    document_format: AgentAttachmentDocumentFormat
    text: str = Field(min_length=1, max_length=MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS)
    projected_characters: int = Field(
        strict=True,
        ge=1,
        le=MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS,
    )
    projection_truncated: bool
    preview_truncated: bool
    omitted_features: tuple[AgentAttachmentOmittedFeature, ...] = Field(
        default=(),
        max_length=6,
    )

    @model_validator(mode="after")
    def coherent_preview(self) -> "AgentAttachmentDocumentPreview":
        if (
            AGENT_DOCUMENT_MEDIA_TYPES[self.document_format] != self.media_type
            or len(self.text) > self.projected_characters
            or self.preview_truncated is not (
                self.projected_characters > len(self.text)
            )
            or tuple(dict.fromkeys(self.omitted_features)) != self.omitted_features
        ):
            raise ValueError("document attachment preview is inconsistent")
        return self


class AgentAttachmentList(StrictModel):
    contract_version: Literal["agent-attachment.v2"] = AGENT_ATTACHMENT_CONTRACT_VERSION
    session_id: str = Field(pattern=_ID_PATTERN)
    attachments: tuple[AgentAttachment, ...]


__all__ = [
    "AGENT_ATTACHMENT_CONTRACT_VERSION",
    "AGENT_ATTACHMENT_DOCUMENT_PREVIEW_CONTRACT_VERSION",
    "AGENT_DOCUMENT_MEDIA_TYPES",
    "AgentAttachment",
    "AgentAttachmentDocumentPreview",
    "AgentAttachmentDocumentFormat",
    "AgentAttachmentKind",
    "AgentAttachmentList",
    "AgentAttachmentMediaType",
    "AgentAttachmentOmittedFeature",
    "AgentAttachmentRetention",
    "AgentAttachmentRouting",
    "AgentAttachmentSource",
    "AgentMessageAttachment",
    "MAX_AGENT_ATTACHMENT_MESSAGE_BYTES",
    "MAX_AGENT_ATTACHMENT_BASE64_CHARS",
    "MAX_AGENT_ATTACHMENT_SESSION_BYTES",
    "MAX_AGENT_AUDIO_BYTES",
    "MAX_AGENT_AUDIO_DURATION_MS",
    "MAX_AGENT_DOCUMENT_BYTES",
    "MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS",
    "MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS",
    "MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS",
    "MAX_AGENT_TEXT_DOCUMENT_BYTES",
    "MAX_AGENT_IMAGE_BYTES",
    "MAX_AGENT_IMAGE_DIMENSION",
    "MAX_AGENT_IMAGE_PIXELS",
    "MAX_AGENT_MESSAGE_ATTACHMENTS",
    "MAX_AGENT_STAGED_ATTACHMENTS",
    "StageAgentAttachment",
    "StageInlineAgentAttachment",
    "LEGACY_AGENT_ATTACHMENT_CONTRACT_VERSION",
    "safe_attachment_name",
]
