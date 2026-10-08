import { useMemo, useState } from "react";

import type { AgentDocumentPreview as DocumentPreview } from "../../shared/api/contracts";
import "./AgentDocumentPreview.css";

const FORMAT_LABELS: Record<DocumentPreview["format"], string> = {
  docx: "Word document",
  pptx: "PowerPoint presentation",
  xlsx: "Excel workbook",
  odt: "OpenDocument text",
};

const OMITTED_LABELS: Record<DocumentPreview["omitted_features"][number], string> = {
  comments: "comments",
  embedded_objects: "embedded objects",
  external_links: "external links",
  macros: "macros",
  media: "images and media",
  notes: "speaker notes",
};

export function AgentDocumentPreview({
  preview,
  title,
  versionNumber,
}: {
  preview: DocumentPreview;
  title: string;
  versionNumber: number;
}) {
  const [activeIndex, setActiveIndex] = useState(1);

  const active = useMemo(
    () => preview.sections.find((section) => section.index === activeIndex) ?? preview.sections[0],
    [activeIndex, preview.sections],
  );
  const showNavigator = preview.sections.length > 1;

  return (
    <section
      aria-label={`${FORMAT_LABELS[preview.format]} preview of ${title} v${versionNumber}`}
      className="agent-document-preview"
      data-format={preview.format}
    >
      <header className="agent-document-preview__header">
        <span>
          <strong>{FORMAT_LABELS[preview.format]}</strong>
          <small>Digest-verified local text projection · active content stays disabled</small>
        </span>
        <span className="agent-document-preview__format">{preview.format}</span>
      </header>

      {(preview.omitted_features.length > 0 || preview.truncated) && (
        <div className="agent-document-preview__notices">
          {preview.omitted_features.length > 0 && (
            <p role="note">
              Not rendered: {preview.omitted_features.map((feature) => OMITTED_LABELS[feature]).join(", ")}.
            </p>
          )}
          {preview.truncated && (
            <p role="status">This bounded preview is truncated. Download the verified file to inspect the complete document.</p>
          )}
        </div>
      )}

      <div className="agent-document-preview__body" data-has-navigation={showNavigator}>
        {showNavigator && (
          <nav aria-label={`${FORMAT_LABELS[preview.format]} sections`}>
            {preview.sections.map((section) => (
              <button
                aria-current={section.index === active.index ? "page" : undefined}
                className="agent-document-preview__section-button"
                key={section.index}
                onClick={() => setActiveIndex(section.index)}
                type="button"
              >
                <span>{section.kind}</span>
                <strong>{section.title}</strong>
              </button>
            ))}
          </nav>
        )}

        <article className="agent-document-preview__page" key={active.index}>
          <header>
            <small>{active.kind} {active.index} of {preview.sections.length}</small>
            <h3>{active.title}</h3>
          </header>
          {active.paragraphs.length > 0 && (
            <div className="agent-document-preview__paragraphs">
              {active.paragraphs.map((paragraph, index) => (
                <p key={`${active.index}-paragraph-${index}`}>{paragraph}</p>
              ))}
            </div>
          )}
          {active.rows.length > 0 && (
            <div className="agent-document-preview__table-wrap">
              <table aria-label={`${active.title} table projection`}>
                <tbody>
                  {active.rows.map((row, rowIndex) => (
                    <tr key={`${active.index}-row-${rowIndex}`}>
                      {row.cells.map((cell, cellIndex) => (
                        <td key={`${active.index}-row-${rowIndex}-cell-${cellIndex}`}>
                          {cell || <span aria-label="Empty cell">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {active.paragraphs.length === 0 && active.rows.length === 0 && (
            <p className="agent-document-preview__empty">No readable text was present in this section.</p>
          )}
          {active.truncated && (
            <p className="agent-document-preview__section-warning" role="status">
              This section reached the safe preview limit.
            </p>
          )}
        </article>
      </div>
    </section>
  );
}
