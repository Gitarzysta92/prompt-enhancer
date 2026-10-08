"""Synthetic safety and projection tests for Agent office-document previews."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from prompt_enhancer.application.agent_document_previews import (
    AgentDocumentPreviewError,
    build_document_preview,
    classify_document_container,
)


PROJECT_ID = "1" * 32
SESSION_ID = "2" * 32
ARTIFACT_ID = "3" * 32
VERSION_ID = "4" * 32
SOURCE_SHA = "5" * 64


def _archive(parts: tuple[tuple[str, bytes, int], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, payload, compression in parts:
            archive.writestr(name, payload, compress_type=compression)
    return output.getvalue()


def _docx(
    *,
    active_declaration: bool = False,
    external_relationship: bool = False,
    malformed: bool = False,
    unsafe_name: str | None = None,
) -> bytes:
    document = b"<broken" if malformed else b"""<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Synthetic document heading</w:t></w:r></w:p>
    <w:tbl><w:tr>
      <w:tc><w:p><w:r><w:t>Alpha</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>Beta</w:t></w:r></w:p></w:tc>
    </w:tr></w:tbl>
  </w:body>
</w:document>"""
    if active_declaration:
        document = b"""<?xml version="1.0"?>
<!DOCTYPE w:document [<!ENTITY synthetic "active declaration">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>&synthetic;</w:t></w:r></w:p></w:body>
</w:document>"""
    parts = [
        ("[Content_Types].xml", b"<Types/>", ZIP_DEFLATED),
        ("word/document.xml", document, ZIP_DEFLATED),
        ("word/comments.xml", b"<comments/>", ZIP_DEFLATED),
        ("word/vbaProject.bin", b"synthetic inert macro bytes", ZIP_STORED),
        ("word/media/image1.png", b"synthetic inert media bytes", ZIP_STORED),
        ("word/embeddings/object1.bin", b"synthetic inert object bytes", ZIP_STORED),
    ]
    if unsafe_name is not None:
        parts.append((unsafe_name, b"synthetic unsafe member", ZIP_STORED))
    if external_relationship:
        parts.append((
            "word/_rels/document.xml.rels",
            b"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="urn:synthetic" Target="https://example.invalid/private" TargetMode="External"/>
</Relationships>""",
            ZIP_DEFLATED,
        ))
    return _archive(tuple(parts))


def _pptx() -> bytes:
    slide = lambda text: f"""<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p>
 </p:txBody></p:sp></p:spTree></p:cSld></p:sld>""".encode()
    return _archive((
        ("[Content_Types].xml", b"<Types/>", ZIP_DEFLATED),
        ("ppt/presentation.xml", b"<p:presentation xmlns:p=\"urn:synthetic\"/>", ZIP_DEFLATED),
        ("ppt/slides/slide1.xml", slide("First synthetic slide"), ZIP_DEFLATED),
        ("ppt/slides/slide2.xml", slide("Second synthetic slide"), ZIP_DEFLATED),
        ("ppt/notesSlides/notesSlide1.xml", b"<notes/>", ZIP_DEFLATED),
    ))


def _xlsx() -> bytes:
    workbook = b"""<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheets><sheet name="Synthetic totals" sheetId="1"/></sheets></workbook>"""
    strings = b"""<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<si><t>Label</t></si><si><t>Value</t></si></sst>"""
    sheet = b"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
<row r="2"><c r="A2" t="inlineStr"><is><t>Fictional</t></is></c>
<c r="B2"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>"""
    return _archive((
        ("[Content_Types].xml", b"<Types/>", ZIP_DEFLATED),
        ("xl/workbook.xml", workbook, ZIP_DEFLATED),
        ("xl/sharedStrings.xml", strings, ZIP_DEFLATED),
        ("xl/worksheets/sheet1.xml", sheet, ZIP_DEFLATED),
        ("xl/externalLinks/externalLink1.xml", b"<externalLink/>", ZIP_DEFLATED),
    ))


def _odt() -> bytes:
    content = b"""<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
 <office:body><office:text><text:h>Synthetic ODT</text:h>
 <text:p>Local preview only.</text:p>
 <table:table><table:table-row>
  <table:table-cell><text:p>Cell Alpha</text:p></table:table-cell>
  <table:table-cell><text:p>Cell Beta</text:p></table:table-cell>
 </table:table-row></table:table>
 </office:text></office:body>
</office:document-content>"""
    return _archive((
        ("mimetype", b"application/vnd.oasis.opendocument.text", ZIP_STORED),
        ("content.xml", content, ZIP_DEFLATED),
    ))


def _preview(path: str, payload: bytes):
    return build_document_preview(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        version_id=VERSION_ID,
        source_sha256=SOURCE_SHA,
        source_byte_size=len(payload),
        path=path,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("path", "payload", "expected_format", "expected_media"),
    (
        (
            "report.docx",
            _docx(),
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "slides.pptx",
            _pptx(),
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "table.xlsx",
            _xlsx(),
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "notes.odt",
            _odt(),
            "odt",
            "application/vnd.oasis.opendocument.text",
        ),
    ),
)
def test_classifies_only_valid_matching_modern_document_containers(
    path: str,
    payload: bytes,
    expected_format: str,
    expected_media: str,
) -> None:
    assert classify_document_container(path, payload) == (
        expected_format,
        expected_media,
    )
    assert classify_document_container("wrong.txt", payload) is None


def test_docx_preview_extracts_text_and_table_but_only_reports_active_parts() -> None:
    preview = _preview("report.docx", _docx())

    assert preview.format == "docx"
    assert preview.sections[0].paragraphs == ("Synthetic document heading",)
    assert preview.sections[0].rows[0].cells == ("Alpha", "Beta")
    assert preview.omitted_features == (
        "comments",
        "embedded_objects",
        "macros",
        "media",
    )
    assert preview.truncated is False


def test_pptx_preview_is_slide_bounded_and_never_reads_notes() -> None:
    preview = _preview("slides.pptx", _pptx())

    assert [section.title for section in preview.sections] == ["Slide 1", "Slide 2"]
    assert preview.sections[0].paragraphs == ("First synthetic slide",)
    assert all("notes" not in paragraph.casefold() for section in preview.sections for paragraph in section.paragraphs)
    assert preview.omitted_features == ("notes",)


def test_xlsx_preview_projects_inert_values_and_reports_external_links() -> None:
    preview = _preview("table.xlsx", _xlsx())

    assert preview.sections[0].title == "Synthetic totals"
    assert preview.sections[0].rows[0].cells == ("Label", "Value")
    assert preview.sections[0].rows[1].cells == ("Fictional", "=1+1 → 2")
    assert preview.omitted_features == ("external_links",)


def test_odt_preview_projects_text_without_invoking_an_office_runtime() -> None:
    preview = _preview("notes.odt", _odt())

    assert preview.format == "odt"
    assert preview.sections[0].paragraphs == ("Synthetic ODT", "Local preview only.")
    assert preview.sections[0].rows[0].cells == ("Cell Alpha", "Cell Beta")


def test_external_relationship_is_reported_but_never_resolved() -> None:
    preview = _preview(
        "report.docx",
        _docx(external_relationship=True),
    )

    assert "external_links" in preview.omitted_features
    assert all(
        "example.invalid" not in text
        for section in preview.sections
        for text in section.paragraphs
    )


def test_xml_active_declarations_fail_closed_before_entity_expansion() -> None:
    payload = _docx(active_declaration=True)

    with pytest.raises(AgentDocumentPreviewError) as blocked:
        _preview("report.docx", payload)
    assert str(blocked.value) == "document_xml_active_declaration"


@pytest.mark.parametrize("unsafe_name", ("../outside.xml", "/absolute.xml", "word:other.xml"))
def test_archive_member_traversal_and_non_posix_names_fail_closed(unsafe_name: str) -> None:
    payload = _docx(unsafe_name=unsafe_name)

    assert classify_document_container("report.docx", payload) is None
    with pytest.raises(AgentDocumentPreviewError):
        _preview("report.docx", payload)


def test_malformed_selected_xml_fails_closed_after_container_classification() -> None:
    payload = _docx(malformed=True)

    assert classify_document_container("report.docx", payload) is not None
    with pytest.raises(AgentDocumentPreviewError) as malformed:
        _preview("report.docx", payload)
    assert str(malformed.value) == "document_xml_invalid"


def test_extreme_compression_ratio_is_rejected_before_decompression() -> None:
    parts = (
        ("[Content_Types].xml", b"<Types/>", ZIP_DEFLATED),
        ("word/document.xml", b"A" * (4 * 1024 * 1024), ZIP_DEFLATED),
    )
    payload = _archive(parts)

    assert classify_document_container("report.docx", payload) is None
    with pytest.raises(AgentDocumentPreviewError):
        _preview("report.docx", payload)


def test_symlink_archive_member_is_rejected() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<w:document xmlns:w=\"urn:test\"/>")
        link = ZipInfo("word/link")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, b"synthetic-target")
    payload = output.getvalue()

    assert classify_document_container("report.docx", payload) is None
    with pytest.raises(AgentDocumentPreviewError):
        _preview("report.docx", payload)
