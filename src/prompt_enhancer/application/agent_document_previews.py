"""Bounded, inert previews for validated modern office-document containers.

The previewer never invokes an office application, shell, browser, converter,
macro runtime, relationship target, or network service. It extracts a small
text/table projection from admitted ZIP/XML formats and reports omitted active
or non-textual features explicitly.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import re
import stat
from typing import Iterator, Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from pydantic import Field, model_validator

from ..domain import StrictModel


AGENT_DOCUMENT_PREVIEW_CONTRACT_VERSION = "agent-document-preview.v1"
MAX_DOCUMENT_ARCHIVE_ENTRIES = 2_048
MAX_DOCUMENT_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_PART_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_PREVIEW_SECTIONS = 64
MAX_DOCUMENT_PREVIEW_PARAGRAPHS = 240
MAX_DOCUMENT_PREVIEW_ROWS = 400
MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW = 32
MAX_DOCUMENT_PREVIEW_CHARACTERS = 100_000
MAX_DOCUMENT_PREVIEW_TEXT_ITEM = 2_000
MAX_SHARED_STRINGS = 10_000
MAX_COMPRESSION_RATIO = 1_000
MAX_RELATIONSHIP_PARTS = 256
MAX_RELATIONSHIP_BYTES = 4 * 1024 * 1024

_ID_PATTERN = r"^[0-9a-f]{32}$"
_SHA_PATTERN = r"^[0-9a-f]{64}$"

AgentDocumentFormat = Literal["docx", "pptx", "xlsx", "odt"]
AgentDocumentSectionKind = Literal["document", "slide", "sheet"]
AgentDocumentOmittedFeature = Literal[
    "comments",
    "embedded_objects",
    "external_links",
    "macros",
    "media",
    "notes",
]

DOCUMENT_MEDIA_TYPES: dict[AgentDocumentFormat, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "odt": "application/vnd.oasis.opendocument.text",
}

_SUFFIX_FORMAT: dict[str, AgentDocumentFormat] = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".odt": "odt",
}
_REQUIRED_PARTS: dict[AgentDocumentFormat, frozenset[str]] = {
    "docx": frozenset({"[Content_Types].xml", "word/document.xml"}),
    "pptx": frozenset({"[Content_Types].xml", "ppt/presentation.xml"}),
    "xlsx": frozenset({"[Content_Types].xml", "xl/workbook.xml"}),
    "odt": frozenset({"mimetype", "content.xml"}),
}
_PART_NUMBER = re.compile(r"(\d+)(?=\.xml$)")

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


class AgentDocumentPreviewRow(StrictModel):
    cells: tuple[str, ...] = Field(max_length=MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW)


class AgentDocumentPreviewSection(StrictModel):
    index: int = Field(strict=True, ge=1, le=MAX_DOCUMENT_PREVIEW_SECTIONS)
    kind: AgentDocumentSectionKind
    title: str = Field(min_length=1, max_length=120)
    paragraphs: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_DOCUMENT_PREVIEW_PARAGRAPHS,
    )
    rows: tuple[AgentDocumentPreviewRow, ...] = Field(
        default=(),
        max_length=MAX_DOCUMENT_PREVIEW_ROWS,
    )
    truncated: bool = False

    @model_validator(mode="after")
    def bounded_text(self) -> "AgentDocumentPreviewSection":
        values = (*self.paragraphs, *(cell for row in self.rows for cell in row.cells))
        if any(len(value) > MAX_DOCUMENT_PREVIEW_TEXT_ITEM for value in values):
            raise ValueError("document preview text item too long")
        return self


class AgentDocumentPreview(StrictModel):
    contract_version: Literal["agent-document-preview.v1"] = (
        AGENT_DOCUMENT_PREVIEW_CONTRACT_VERSION
    )
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    artifact_id: str = Field(pattern=_ID_PATTERN)
    version_id: str = Field(pattern=_ID_PATTERN)
    source_sha256: str = Field(pattern=_SHA_PATTERN)
    source_byte_size: int = Field(strict=True, ge=1, le=24 * 1024 * 1024)
    format: AgentDocumentFormat
    sections: tuple[AgentDocumentPreviewSection, ...] = Field(
        min_length=1,
        max_length=MAX_DOCUMENT_PREVIEW_SECTIONS,
    )
    omitted_features: tuple[AgentDocumentOmittedFeature, ...] = Field(
        default=(),
        max_length=6,
    )
    truncated: bool = False

    @model_validator(mode="after")
    def coherent_projection(self) -> "AgentDocumentPreview":
        if tuple(section.index for section in self.sections) != tuple(
            range(1, len(self.sections) + 1)
        ):
            raise ValueError("document preview sections are not contiguous")
        if tuple(dict.fromkeys(self.omitted_features)) != self.omitted_features:
            raise ValueError("document preview omitted features are not unique")
        return self


class AgentDocumentPreviewError(RuntimeError):
    pass


def _safe_member(info: ZipInfo) -> bool:
    name = info.filename
    path = PurePosixPath(name)
    mode = (info.external_attr >> 16) & 0o170000
    return (
        0 < len(name) <= 1_024
        and not name.startswith("/")
        and "\\" not in name
        and ":" not in name
        and all(part not in {"", ".", ".."} for part in path.parts)
        and not (info.flag_bits & 0x1)
        and mode != stat.S_IFLNK
        and info.compress_type in {ZIP_STORED, ZIP_DEFLATED}
        and info.file_size >= 0
        and info.compress_size >= 0
        and (
            info.file_size == 0
            or info.compress_size > 0
            and info.file_size <= info.compress_size * MAX_COMPRESSION_RATIO
        )
    )


@contextmanager
def _validated_archive(payload: bytes) -> Iterator[ZipFile]:
    try:
        with ZipFile(BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or len(infos) > MAX_DOCUMENT_ARCHIVE_ENTRIES
                or len(names) != len(set(names))
                or any(not _safe_member(info) for info in infos)
                or sum(info.file_size for info in infos) > MAX_DOCUMENT_UNCOMPRESSED_BYTES
            ):
                raise AgentDocumentPreviewError("document_container_unsafe")
            yield archive
    except (BadZipFile, OSError, RuntimeError, ValueError) as error:
        if isinstance(error, AgentDocumentPreviewError):
            raise
        raise AgentDocumentPreviewError("document_container_invalid") from None


def _read_part(archive: ZipFile, name: str, *, limit: int = MAX_DOCUMENT_PART_BYTES) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise AgentDocumentPreviewError("document_part_missing") from None
    if info.is_dir() or info.file_size > limit:
        raise AgentDocumentPreviewError("document_part_too_large")
    try:
        payload = archive.read(info)
    except (BadZipFile, OSError, RuntimeError, ValueError):
        raise AgentDocumentPreviewError("document_part_invalid") from None
    if len(payload) != info.file_size:
        raise AgentDocumentPreviewError("document_part_changed")
    return payload


def _format_in_archive(
    archive: ZipFile,
    path: str,
) -> AgentDocumentFormat | None:
    suffix = PurePosixPath(path).suffix.casefold()
    document_format = _SUFFIX_FORMAT.get(suffix)
    if document_format is None:
        return None
    names = set(archive.namelist())
    if not _REQUIRED_PARTS[document_format].issubset(names):
        return None
    if document_format == "odt":
        mimetype = _read_part(archive, "mimetype", limit=256)
        if mimetype != DOCUMENT_MEDIA_TYPES["odt"].encode("ascii"):
            return None
    return document_format


def classify_document_container(
    path: str,
    payload: bytes,
) -> tuple[AgentDocumentFormat, str] | None:
    if PurePosixPath(path).suffix.casefold() not in _SUFFIX_FORMAT:
        return None
    try:
        with _validated_archive(payload) as archive:
            document_format = _format_in_archive(archive, path)
    except AgentDocumentPreviewError:
        return None
    if document_format is None:
        return None
    return document_format, DOCUMENT_MEDIA_TYPES[document_format]


@dataclass(slots=True)
class _PreviewBudget:
    characters: int = 0
    rows: int = 0
    truncated: bool = False

    def text(self, value: str) -> str | None:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            return None
        remaining = MAX_DOCUMENT_PREVIEW_CHARACTERS - self.characters
        if remaining <= 0:
            self.truncated = True
            return None
        maximum = min(MAX_DOCUMENT_PREVIEW_TEXT_ITEM, remaining)
        if len(normalized) > maximum:
            normalized = normalized[:maximum].rstrip() + "…"
            self.truncated = True
        self.characters += len(normalized)
        return normalized

    def may_add_row(self) -> bool:
        if self.rows >= MAX_DOCUMENT_PREVIEW_ROWS:
            self.truncated = True
            return False
        self.rows += 1
        return True


def _xml(payload: bytes) -> ElementTree.Element:
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, flags=re.IGNORECASE):
        raise AgentDocumentPreviewError("document_xml_active_declaration")
    try:
        return ElementTree.fromstring(payload)
    except (ElementTree.ParseError, ValueError):
        raise AgentDocumentPreviewError("document_xml_invalid") from None


def _paragraph_text(element: ElementTree.Element, tag: str, budget: _PreviewBudget) -> str | None:
    return budget.text("".join(node.text or "" for node in element.iter(tag)))


def _docx_preview(archive: ZipFile, budget: _PreviewBudget) -> tuple[AgentDocumentPreviewSection, ...]:
    root = _xml(_read_part(archive, "word/document.xml"))
    body = root.find(f"{_W}body")
    if body is None:
        raise AgentDocumentPreviewError("document_body_missing")
    paragraphs: list[str] = []
    rows: list[AgentDocumentPreviewRow] = []
    section_truncated = False
    for child in body:
        if child.tag == f"{_W}p":
            value = _paragraph_text(child, f"{_W}t", budget)
            if value is not None:
                if len(paragraphs) >= MAX_DOCUMENT_PREVIEW_PARAGRAPHS:
                    section_truncated = budget.truncated = True
                else:
                    paragraphs.append(value)
        elif child.tag == f"{_W}tbl":
            for row in child.findall(f"{_W}tr"):
                if not budget.may_add_row():
                    section_truncated = True
                    break
                cells: list[str] = []
                for cell in row.findall(f"{_W}tc")[:MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW]:
                    value = _paragraph_text(cell, f"{_W}t", budget)
                    cells.append(value or "")
                rows.append(AgentDocumentPreviewRow(cells=tuple(cells)))
        if budget.characters >= MAX_DOCUMENT_PREVIEW_CHARACTERS:
            section_truncated = True
            break
    return (AgentDocumentPreviewSection(
        index=1,
        kind="document",
        title="Document",
        paragraphs=tuple(paragraphs),
        rows=tuple(rows),
        truncated=section_truncated,
    ),)


def _numbered_parts(names: set[str], prefix: str) -> list[str]:
    matching = [name for name in names if name.startswith(prefix) and name.endswith(".xml")]
    return sorted(
        matching,
        key=lambda name: int(match.group(1)) if (match := _PART_NUMBER.search(name)) else 0,
    )


def _pptx_preview(archive: ZipFile, budget: _PreviewBudget) -> tuple[AgentDocumentPreviewSection, ...]:
    parts = _numbered_parts(set(archive.namelist()), "ppt/slides/slide")
    sections: list[AgentDocumentPreviewSection] = []
    for index, part in enumerate(parts[:MAX_DOCUMENT_PREVIEW_SECTIONS], start=1):
        root = _xml(_read_part(archive, part))
        paragraphs: list[str] = []
        section_truncated = False
        for paragraph in root.iter(f"{_A}p"):
            value = _paragraph_text(paragraph, f"{_A}t", budget)
            if value is None:
                continue
            if len(paragraphs) >= MAX_DOCUMENT_PREVIEW_PARAGRAPHS:
                section_truncated = budget.truncated = True
                break
            paragraphs.append(value)
        sections.append(AgentDocumentPreviewSection(
            index=index,
            kind="slide",
            title=f"Slide {index}",
            paragraphs=tuple(paragraphs),
            truncated=section_truncated,
        ))
        if budget.characters >= MAX_DOCUMENT_PREVIEW_CHARACTERS:
            break
    if len(parts) > len(sections):
        budget.truncated = True
    return tuple(sections) or (AgentDocumentPreviewSection(
        index=1,
        kind="slide",
        title="Presentation",
    ),)


def _shared_strings(archive: ZipFile, budget: _PreviewBudget) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = _xml(_read_part(archive, "xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(f"{_S}si")[:MAX_SHARED_STRINGS]:
        normalized = " ".join("".join(node.text or "" for node in item.iter(f"{_S}t")).split())
        if len(normalized) > MAX_DOCUMENT_PREVIEW_TEXT_ITEM:
            budget.truncated = True
        values.append(normalized[:MAX_DOCUMENT_PREVIEW_TEXT_ITEM])
    if len(root.findall(f"{_S}si")) > len(values):
        budget.truncated = True
    return tuple(values)


def _sheet_names(archive: ZipFile) -> tuple[str, ...]:
    root = _xml(_read_part(archive, "xl/workbook.xml"))
    return tuple(
        name
        for sheet in root.iter(f"{_S}sheet")
        if (name := sheet.attrib.get("name", "").strip())
    )


def _cell_text(
    cell: ElementTree.Element,
    shared: tuple[str, ...],
    budget: _PreviewBudget,
) -> str:
    formula = cell.findtext(f"{_S}f")
    raw = cell.findtext(f"{_S}v") or ""
    kind = cell.attrib.get("t")
    if kind == "s" and raw.isdigit() and int(raw) < len(shared):
        raw = shared[int(raw)]
    elif kind == "inlineStr":
        raw = "".join(node.text or "" for node in cell.iter(f"{_S}t"))
    elif kind == "b":
        raw = "TRUE" if raw == "1" else "FALSE"
    value = f"={formula} → {raw}" if formula and raw else f"={formula}" if formula else raw
    return budget.text(value) or ""


def _xlsx_preview(archive: ZipFile, budget: _PreviewBudget) -> tuple[AgentDocumentPreviewSection, ...]:
    names = set(archive.namelist())
    parts = _numbered_parts(names, "xl/worksheets/sheet")
    titles = _sheet_names(archive)
    shared = _shared_strings(archive, budget)
    sections: list[AgentDocumentPreviewSection] = []
    for index, part in enumerate(parts[:MAX_DOCUMENT_PREVIEW_SECTIONS], start=1):
        root = _xml(_read_part(archive, part))
        rows: list[AgentDocumentPreviewRow] = []
        section_truncated = False
        for row in root.iter(f"{_S}row"):
            if not budget.may_add_row():
                section_truncated = True
                break
            source_cells = list(row.findall(f"{_S}c"))
            if len(source_cells) > MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW:
                section_truncated = budget.truncated = True
            cells = tuple(
                _cell_text(cell, shared, budget)
                for cell in source_cells[:MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW]
            )
            rows.append(AgentDocumentPreviewRow(cells=cells))
            if budget.characters >= MAX_DOCUMENT_PREVIEW_CHARACTERS:
                section_truncated = True
                break
        sections.append(AgentDocumentPreviewSection(
            index=index,
            kind="sheet",
            title=(titles[index - 1] if index <= len(titles) else f"Sheet {index}")[:120],
            rows=tuple(rows),
            truncated=section_truncated,
        ))
        if budget.rows >= MAX_DOCUMENT_PREVIEW_ROWS or budget.characters >= MAX_DOCUMENT_PREVIEW_CHARACTERS:
            break
    if len(parts) > len(sections):
        budget.truncated = True
    return tuple(sections) or (AgentDocumentPreviewSection(
        index=1,
        kind="sheet",
        title="Workbook",
    ),)


def _odt_preview(archive: ZipFile, budget: _PreviewBudget) -> tuple[AgentDocumentPreviewSection, ...]:
    root = _xml(_read_part(archive, "content.xml"))
    body = root.find(f"{_OFFICE}body")
    if body is None:
        raise AgentDocumentPreviewError("document_body_missing")
    paragraphs: list[str] = []
    rows: list[AgentDocumentPreviewRow] = []
    section_truncated = False
    parents = {
        child: parent
        for parent in body.iter()
        for child in parent
    }

    def inside_table(element: ElementTree.Element) -> bool:
        parent = parents.get(element)
        while parent is not None:
            if parent.tag in {f"{_TABLE}table", f"{_TABLE}table-cell"}:
                return True
            parent = parents.get(parent)
        return False

    for element in body.iter():
        if element.tag in {f"{_TEXT}p", f"{_TEXT}h"} and not inside_table(element):
            value = budget.text("".join(element.itertext()))
            if value is not None:
                if len(paragraphs) >= MAX_DOCUMENT_PREVIEW_PARAGRAPHS:
                    section_truncated = budget.truncated = True
                    break
                paragraphs.append(value)
        elif element.tag == f"{_TABLE}table-row":
            if not budget.may_add_row():
                section_truncated = True
                break
            source_cells = list(element.findall(f"{_TABLE}table-cell"))
            if len(source_cells) > MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW:
                section_truncated = budget.truncated = True
            cells = tuple(
                budget.text("".join(cell.itertext())) or ""
                for cell in source_cells[:MAX_DOCUMENT_PREVIEW_CELLS_PER_ROW]
            )
            rows.append(AgentDocumentPreviewRow(cells=cells))
        if budget.characters >= MAX_DOCUMENT_PREVIEW_CHARACTERS:
            section_truncated = True
            break
    return (AgentDocumentPreviewSection(
        index=1,
        kind="document",
        title="Document",
        paragraphs=tuple(paragraphs),
        rows=tuple(rows),
        truncated=section_truncated,
    ),)


def _external_relationship_present(archive: ZipFile) -> bool:
    relationship_parts = [
        info
        for info in archive.infolist()
        if info.filename.casefold().endswith(".rels")
    ]
    if len(relationship_parts) > MAX_RELATIONSHIP_PARTS:
        return True
    if sum(info.file_size for info in relationship_parts) > MAX_RELATIONSHIP_BYTES:
        return True
    for info in relationship_parts:
        try:
            root = _xml(_read_part(archive, info.filename, limit=MAX_RELATIONSHIP_BYTES))
        except AgentDocumentPreviewError:
            return True
        if any(
            value.casefold() == "external"
            for element in root.iter()
            for key, value in element.attrib.items()
            if key.casefold().endswith("targetmode")
        ):
            return True
    if "content.xml" in archive.namelist():
        try:
            root = _xml(_read_part(archive, "content.xml"))
        except AgentDocumentPreviewError:
            return True
        if any(
            re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", value, flags=re.IGNORECASE)
            for element in root.iter()
            for key, value in element.attrib.items()
            if key.casefold().endswith("href")
        ):
            return True
    return False


def _omitted_features(archive: ZipFile) -> tuple[AgentDocumentOmittedFeature, ...]:
    names = tuple(name.casefold() for name in archive.namelist())
    omitted: list[AgentDocumentOmittedFeature] = []
    if any("comments" in name for name in names):
        omitted.append("comments")
    if any("/embeddings/" in name or "oleobject" in name for name in names):
        omitted.append("embedded_objects")
    if any("externallinks" in name for name in names) or _external_relationship_present(archive):
        omitted.append("external_links")
    if any(name.endswith("vbaproject.bin") for name in names):
        omitted.append("macros")
    if any("notesslides" in name or "notesmaster" in name for name in names):
        omitted.append("notes")
    if any("/media/" in name for name in names):
        omitted.append("media")
    return tuple(omitted)


def build_document_preview(
    *,
    project_id: str,
    session_id: str,
    artifact_id: str,
    version_id: str,
    source_sha256: str,
    source_byte_size: int,
    path: str,
    payload: bytes,
) -> AgentDocumentPreview:
    with _validated_archive(payload) as archive:
        document_format = _format_in_archive(archive, path)
        if document_format is None:
            raise AgentDocumentPreviewError("document_format_unsupported")
        budget = _PreviewBudget()
        if document_format == "docx":
            sections = _docx_preview(archive, budget)
        elif document_format == "pptx":
            sections = _pptx_preview(archive, budget)
        elif document_format == "xlsx":
            sections = _xlsx_preview(archive, budget)
        else:
            sections = _odt_preview(archive, budget)
        omitted = _omitted_features(archive)
    return AgentDocumentPreview(
        project_id=project_id,
        session_id=session_id,
        artifact_id=artifact_id,
        version_id=version_id,
        source_sha256=source_sha256,
        source_byte_size=source_byte_size,
        format=document_format,
        sections=sections,
        omitted_features=omitted,
        truncated=budget.truncated or any(section.truncated for section in sections),
    )


__all__ = (
    "AGENT_DOCUMENT_PREVIEW_CONTRACT_VERSION",
    "DOCUMENT_MEDIA_TYPES",
    "AgentDocumentFormat",
    "AgentDocumentOmittedFeature",
    "AgentDocumentPreview",
    "AgentDocumentPreviewError",
    "AgentDocumentPreviewRow",
    "AgentDocumentPreviewSection",
    "AgentDocumentSectionKind",
    "build_document_preview",
    "classify_document_container",
)
