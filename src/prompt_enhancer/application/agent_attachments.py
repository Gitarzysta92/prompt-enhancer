"""Private, bounded attachment vault for authored local Agent chats."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import io
import struct
from typing import Protocol
import uuid
import wave
import zlib

from .agent_attachment_contracts import (
    AgentAttachment,
    AgentAttachmentDocumentPreview,
    AgentAttachmentKind,
    AgentAttachmentList,
    AgentAttachmentRetention,
    AgentMessageAttachment,
    MAX_AGENT_ATTACHMENT_MESSAGE_BYTES,
    MAX_AGENT_AUDIO_BYTES,
    MAX_AGENT_AUDIO_DURATION_MS,
    MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS,
    MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS,
    MAX_AGENT_IMAGE_BYTES,
    MAX_AGENT_IMAGE_DIMENSION,
    MAX_AGENT_IMAGE_PIXELS,
    MAX_AGENT_MESSAGE_ATTACHMENTS,
    StageAgentAttachment,
)
from .agent_attachment_documents import (
    AgentAttachmentDocumentError,
    AgentAttachmentDocumentProjection,
    document_model_part,
    project_agent_attachment_document,
)
from .agent_catalog import AgentCatalogError, AgentCatalogService, AgentRetentionPolicy
from .local_models import RuntimeCapabilities, RuntimeCapabilityState


STAGED_ATTACHMENT_LIFETIME = timedelta(hours=1)


class AgentAttachmentError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AgentAttachmentBlob:
    attachment: AgentAttachment
    payload: bytes


@dataclass(frozen=True, slots=True)
class AgentAttachmentContent:
    attachment: AgentAttachment
    payload: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class PreparedAgentAttachments:
    attachments: tuple[AgentMessageAttachment, ...]
    content_parts: tuple[dict[str, object], ...]


class AgentAttachmentRepository(Protocol):
    def purge_expired(self, now: datetime) -> None: ...

    def create(self, blob: AgentAttachmentBlob) -> AgentAttachment: ...

    def list_staged(self, session_id: str) -> tuple[AgentAttachment, ...]: ...

    def get(self, session_id: str, attachment_id: str) -> AgentAttachmentBlob | None: ...

    def mark_attached(
        self,
        session_id: str,
        attachment_ids: tuple[str, ...],
        event_seq: int,
    ) -> None: ...

    def delete(self, session_id: str, attachment_id: str, *, staged_only: bool) -> bool: ...


def _png_dimensions(payload: bytes) -> tuple[int, int] | None:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    width = height = None
    saw_idat = saw_iend = False
    chunk_count = 0
    while offset + 12 <= len(payload):
        chunk_count += 1
        if chunk_count > 20_000:
            return None
        length = int.from_bytes(payload[offset:offset + 4], "big")
        chunk_type = payload[offset + 4:offset + 8]
        end = offset + 12 + length
        if length > len(payload) or end > len(payload):
            return None
        chunk = payload[offset + 8:offset + 8 + length]
        expected_crc = int.from_bytes(payload[offset + 8 + length:end], "big")
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            return None
        if chunk_count == 1:
            if chunk_type != b"IHDR" or length != 13:
                return None
            width, height = struct.unpack(">II", chunk[:8])
        elif chunk_type == b"IHDR":
            return None
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or end != len(payload):
                return None
            saw_iend = True
            break
        offset = end
    if width is None or height is None or not saw_idat or not saw_iend:
        return None
    return width, height


def _jpeg_dimensions(payload: bytes) -> tuple[int, int] | None:
    if len(payload) < 4 or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        return None
    index = 2
    dimensions: tuple[int, int] | None = None
    sof = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while index + 1 < len(payload):
        if payload[index] != 0xFF:
            index += 1
            continue
        while index < len(payload) and payload[index] == 0xFF:
            index += 1
        if index >= len(payload):
            return None
        marker = payload[index]
        index += 1
        if marker == 0xD9:
            break
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(payload):
            return None
        length = int.from_bytes(payload[index:index + 2], "big")
        if length < 2 or index + length > len(payload):
            return None
        if marker in sof:
            if length < 8:
                return None
            height = int.from_bytes(payload[index + 3:index + 5], "big")
            width = int.from_bytes(payload[index + 5:index + 7], "big")
            dimensions = (width, height)
        if marker == 0xDA:
            # Entropy-coded scan data follows.  The terminal EOI check above
            # bounds it; dimensions must already have been declared by SOF.
            break
        index += length
    return dimensions


def _validated_image(payload: bytes, media_type: str) -> tuple[int, int]:
    if len(payload) > MAX_AGENT_IMAGE_BYTES:
        raise AgentAttachmentError("agent_attachment_too_large")
    dimensions = (
        _png_dimensions(payload)
        if media_type == "image/png"
        else _jpeg_dimensions(payload)
        if media_type == "image/jpeg"
        else None
    )
    if dimensions is None:
        raise AgentAttachmentError("agent_attachment_media_mismatch")
    width, height = dimensions
    if (
        width <= 0
        or height <= 0
        or width > MAX_AGENT_IMAGE_DIMENSION
        or height > MAX_AGENT_IMAGE_DIMENSION
        or width * height > MAX_AGENT_IMAGE_PIXELS
    ):
        raise AgentAttachmentError("agent_attachment_dimensions_unsupported")
    return dimensions


def _validated_wav(payload: bytes, media_type: str) -> tuple[int, int, int]:
    if media_type != "audio/wav":
        raise AgentAttachmentError("agent_attachment_media_unsupported")
    if len(payload) > MAX_AGENT_AUDIO_BYTES:
        raise AgentAttachmentError("agent_attachment_too_large")
    try:
        with wave.open(io.BytesIO(payload), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frames = reader.getnframes()
            compression = reader.getcomptype()
            decoded = reader.readframes(frames)
    except (EOFError, OSError, wave.Error):
        raise AgentAttachmentError("agent_attachment_media_mismatch") from None
    if (
        compression != "NONE"
        or channels not in {1, 2}
        or sample_width not in {1, 2, 3, 4}
        or not 8_000 <= sample_rate <= 48_000
        or frames <= 0
        or len(decoded) != frames * channels * sample_width
    ):
        raise AgentAttachmentError("agent_attachment_audio_unsupported")
    duration_ms = max(1, (frames * 1_000 + sample_rate - 1) // sample_rate)
    if duration_ms > MAX_AGENT_AUDIO_DURATION_MS:
        raise AgentAttachmentError("agent_attachment_duration_unsupported")
    return duration_ms, sample_rate, channels


def _suffix(media_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "audio/wav": ".wav"}[media_type]


def _document_projection(
    attachment: AgentAttachment,
    payload: bytes,
) -> AgentAttachmentDocumentProjection:
    try:
        projection = project_agent_attachment_document(
            display_name=attachment.display_name,
            media_type=attachment.media_type,
            payload=payload,
        )
    except AgentAttachmentDocumentError as error:
        raise AgentAttachmentError(error.code) from None
    if (
        attachment.kind != "document"
        or attachment.routing != "local_text_projection"
        or attachment.document_format != projection.document_format
        or attachment.projected_characters != len(projection.text)
        or attachment.projection_truncated is not projection.truncated
        or attachment.omitted_features != projection.omitted_features
    ):
        raise AgentAttachmentError("agent_attachment_corrupt")
    return projection


class AgentAttachmentService:
    def __init__(
        self,
        repository: AgentAttachmentRepository,
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
            raise AgentAttachmentError("agent_attachment_id_invalid")
        return value

    def _retention(self, session_id: str) -> AgentAttachmentRetention:
        try:
            record = self._catalog.get_session(session_id)
        except AgentCatalogError as error:
            raise AgentAttachmentError(error.code) from None
        return (
            "local_history"
            if record.retention_policy is AgentRetentionPolicy.LOCAL_HISTORY
            else "memory_only"
        )

    @staticmethod
    def _supports(kind: AgentAttachmentKind, capabilities: RuntimeCapabilities) -> bool:
        if capabilities.state is not RuntimeCapabilityState.VERIFIED:
            return False
        if kind == "image":
            return capabilities.vision
        if kind == "audio":
            return capabilities.audio
        return capabilities.text

    def stage(
        self,
        *,
        session_id: str,
        model_alias: str,
        capabilities: RuntimeCapabilities,
        command: StageAgentAttachment,
        media_type: str,
        payload: bytes,
    ) -> AgentAttachment:
        if not payload:
            raise AgentAttachmentError("agent_attachment_empty")
        if media_type in {"image/png", "image/jpeg"}:
            kind: AgentAttachmentKind = "image"
            width, height = _validated_image(payload, media_type)
            duration_ms = sample_rate = channels = None
            document_projection = None
        elif media_type == "audio/wav":
            kind = "audio"
            duration_ms, sample_rate, channels = _validated_wav(payload, media_type)
            width = height = None
            document_projection = None
        else:
            kind = "document"
            width = height = duration_ms = sample_rate = channels = None
            try:
                document_projection = project_agent_attachment_document(
                    display_name=command.display_name,
                    media_type=media_type,
                    payload=payload,
                )
            except AgentAttachmentDocumentError as error:
                raise AgentAttachmentError(error.code) from None
        if not self._supports(kind, capabilities):
            raise AgentAttachmentError(
                f"agent_attachment_{kind}_capability_unavailable"
            )
        now = self._clock()
        self._repository.purge_expired(now)
        attachment = AgentAttachment(
            attachment_id=self._id(),
            session_id=session_id,
            model_alias=model_alias,
            capability_probe_version=capabilities.probe_version,
            kind=kind,
            media_type=media_type,
            display_name=command.display_name,
            source=command.source,
            state="staged",
            retention=self._retention(session_id),
            created_at=now,
            expires_at=now + STAGED_ATTACHMENT_LIFETIME,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            width=width,
            height=height,
            duration_ms=duration_ms,
            sample_rate_hz=sample_rate,
            channels=channels,
            routing=(
                "local_text_projection"
                if document_projection is not None
                else "native_multimodal"
            ),
            document_format=(
                document_projection.document_format
                if document_projection is not None
                else None
            ),
            projected_characters=(
                len(document_projection.text)
                if document_projection is not None
                else None
            ),
            projection_truncated=(
                document_projection.truncated
                if document_projection is not None
                else None
            ),
            omitted_features=(
                document_projection.omitted_features
                if document_projection is not None
                else ()
            ),
        )
        return self._repository.create(AgentAttachmentBlob(attachment, payload))

    def list_staged(self, session_id: str) -> AgentAttachmentList:
        self._retention(session_id)
        self._repository.purge_expired(self._clock())
        return AgentAttachmentList(
            session_id=session_id,
            attachments=self._repository.list_staged(session_id),
        )

    def delete_staged(self, session_id: str, attachment_id: str) -> None:
        self._retention(session_id)
        if not self._repository.delete(session_id, attachment_id, staged_only=True):
            blob = self._repository.get(session_id, attachment_id)
            if blob is None:
                raise AgentAttachmentError("agent_attachment_not_found")
            raise AgentAttachmentError("agent_attachment_already_sent")

    def content(self, session_id: str, attachment_id: str) -> AgentAttachmentContent:
        self._retention(session_id)
        blob = self._repository.get(session_id, attachment_id)
        if blob is None:
            raise AgentAttachmentError("agent_attachment_not_found")
        if len(blob.payload) != blob.attachment.byte_size or hashlib.sha256(blob.payload).hexdigest() != blob.attachment.sha256:
            raise AgentAttachmentError("agent_attachment_corrupt")
        if blob.attachment.kind == "document":
            raise AgentAttachmentError("agent_attachment_content_preview_unsupported")
        return AgentAttachmentContent(
            attachment=blob.attachment,
            payload=blob.payload,
            filename=f"agent-attachment-{attachment_id[:8]}{_suffix(blob.attachment.media_type)}",
        )

    def document_preview(
        self,
        session_id: str,
        attachment_id: str,
    ) -> AgentAttachmentDocumentPreview:
        """Return only a bounded local text projection, never original bytes."""

        self._retention(session_id)
        blob = self._repository.get(session_id, attachment_id)
        if blob is None:
            raise AgentAttachmentError("agent_attachment_not_found")
        attachment = blob.attachment
        if attachment.kind != "document":
            raise AgentAttachmentError("agent_attachment_document_preview_unsupported")
        if (
            len(blob.payload) != attachment.byte_size
            or hashlib.sha256(blob.payload).hexdigest() != attachment.sha256
        ):
            raise AgentAttachmentError("agent_attachment_corrupt")
        projection = _document_projection(attachment, blob.payload)
        text = projection.text[:MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS]
        return AgentAttachmentDocumentPreview(
            session_id=session_id,
            attachment_id=attachment_id,
            sha256=attachment.sha256,
            media_type=attachment.media_type,
            document_format=projection.document_format,
            text=text,
            projected_characters=len(projection.text),
            projection_truncated=projection.truncated,
            preview_truncated=len(text) < len(projection.text),
            omitted_features=projection.omitted_features,
        )

    def prepare(
        self,
        *,
        session_id: str,
        attachment_ids: tuple[str, ...],
        model_alias: str,
        capabilities: RuntimeCapabilities,
    ) -> PreparedAgentAttachments:
        if len(attachment_ids) > MAX_AGENT_MESSAGE_ATTACHMENTS:
            raise AgentAttachmentError("agent_attachment_message_limit")
        if len(set(attachment_ids)) != len(attachment_ids):
            raise AgentAttachmentError("agent_attachment_duplicate")
        self._repository.purge_expired(self._clock())
        blobs: list[AgentAttachmentBlob] = []
        total = 0
        projected_characters = 0
        document_projections: dict[str, AgentAttachmentDocumentProjection] = {}
        for attachment_id in attachment_ids:
            blob = self._repository.get(session_id, attachment_id)
            if blob is None:
                raise AgentAttachmentError("agent_attachment_not_found")
            attachment = blob.attachment
            if attachment.state != "staged":
                raise AgentAttachmentError("agent_attachment_already_sent")
            if attachment.model_alias != model_alias:
                raise AgentAttachmentError("agent_attachment_model_changed")
            if not self._supports(attachment.kind, capabilities):
                raise AgentAttachmentError(
                    f"agent_attachment_{attachment.kind}_capability_unavailable"
                )
            if len(blob.payload) != attachment.byte_size or hashlib.sha256(blob.payload).hexdigest() != attachment.sha256:
                raise AgentAttachmentError("agent_attachment_corrupt")
            total += attachment.byte_size
            if total > MAX_AGENT_ATTACHMENT_MESSAGE_BYTES:
                raise AgentAttachmentError("agent_attachment_message_too_large")
            if attachment.kind == "document":
                projection = _document_projection(attachment, blob.payload)
                projected_characters += len(projection.text)
                if projected_characters > MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS:
                    raise AgentAttachmentError(
                        "agent_attachment_document_message_too_large"
                    )
                document_projections[attachment.attachment_id] = projection
            blobs.append(blob)
        parts: list[dict[str, object]] = []
        metadata: list[AgentMessageAttachment] = []
        for blob in blobs:
            attachment = blob.attachment
            if attachment.kind == "image":
                encoded = base64.b64encode(blob.payload).decode("ascii")
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{attachment.media_type};base64,{encoded}"},
                })
            elif attachment.kind == "audio":
                encoded = base64.b64encode(blob.payload).decode("ascii")
                parts.append({
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": "wav"},
                })
            else:
                parts.append(
                    document_model_part(
                        display_name=attachment.display_name,
                        media_type=attachment.media_type,
                        sha256=attachment.sha256,
                        projection=document_projections[attachment.attachment_id],
                    )
                )
            metadata.append(attachment.message_metadata())
        return PreparedAgentAttachments(tuple(metadata), tuple(parts))

    @staticmethod
    def _part(
        blob: AgentAttachmentBlob,
        document_projection: AgentAttachmentDocumentProjection | None = None,
    ) -> dict[str, object]:
        attachment = blob.attachment
        if attachment.kind == "image":
            encoded = base64.b64encode(blob.payload).decode("ascii")
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{attachment.media_type};base64,{encoded}"},
            }
        if attachment.kind == "audio":
            encoded = base64.b64encode(blob.payload).decode("ascii")
            return {
                "type": "input_audio",
                "input_audio": {"data": encoded, "format": "wav"},
            }
        if document_projection is None:
            raise AgentAttachmentError("agent_attachment_corrupt")
        return document_model_part(
            display_name=attachment.display_name,
            media_type=attachment.media_type,
            sha256=attachment.sha256,
            projection=document_projection,
        )

    def recover_content_parts(
        self,
        *,
        session_id: str,
        attachments: tuple[AgentMessageAttachment, ...],
    ) -> tuple[dict[str, object], ...]:
        """Rehydrate only exact durable references from the private vault."""

        parts: list[dict[str, object]] = []
        for metadata in attachments:
            blob = self._repository.get(session_id, metadata.attachment_id)
            if blob is None or blob.attachment.state != "attached":
                raise AgentAttachmentError("agent_attachment_not_found")
            if blob.attachment.message_metadata() != metadata:
                raise AgentAttachmentError("agent_attachment_corrupt")
            if (
                len(blob.payload) != metadata.byte_size
                or hashlib.sha256(blob.payload).hexdigest() != metadata.sha256
            ):
                raise AgentAttachmentError("agent_attachment_corrupt")
            projection = (
                _document_projection(blob.attachment, blob.payload)
                if blob.attachment.kind == "document"
                else None
            )
            parts.append(self._part(blob, projection))
        return tuple(parts)

    def settle_sent(
        self,
        *,
        session_id: str,
        attachment_ids: tuple[str, ...],
        event_seq: int,
        retention: AgentAttachmentRetention,
    ) -> None:
        if not attachment_ids:
            return
        if retention == "local_history":
            self._repository.mark_attached(session_id, attachment_ids, event_seq)
            return
        for attachment_id in attachment_ids:
            if not self._repository.delete(session_id, attachment_id, staged_only=True):
                raise AgentAttachmentError("agent_attachment_storage_unavailable")


__all__ = [
    "AgentAttachmentBlob",
    "AgentAttachmentContent",
    "AgentAttachmentError",
    "AgentAttachmentRepository",
    "AgentAttachmentService",
    "PreparedAgentAttachments",
    "STAGED_ATTACHMENT_LIFETIME",
]
