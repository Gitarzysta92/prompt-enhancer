import { useMemo, useState } from "react";

import { AgentCopyButton } from "./AgentCopyButton";
import "./AgentDiffViewer.css";

export type AgentDiffLineKind = "metadata" | "hunk" | "addition" | "deletion" | "context" | "note";

export type AgentDiffLine = {
  content: string;
  kind: AgentDiffLineKind;
  oldLine: number | null;
  newLine: number | null;
};

export type ParsedAgentDiff = {
  lines: AgentDiffLine[];
  addedLines: number;
  removedLines: number;
  hunkCount: number;
  structureComplete: boolean;
};

const HUNK_HEADER = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/u;
export const MAX_STRUCTURED_DIFF_LINES = 2_000;

export function parseAgentUnifiedDiff(diff: string): ParsedAgentDiff {
  let oldLine: number | null = null;
  let newLine: number | null = null;
  let oldRemaining = 0;
  let newRemaining = 0;
  let addedLines = 0;
  let removedLines = 0;
  let hunkCount = 0;
  let structureComplete = true;

  const lines: AgentDiffLine[] = [];
  for (const content of diff.split("\n")) {
    const hunk = HUNK_HEADER.exec(content);
    if (hunk) {
      if (hunkCount > 0 && (oldRemaining !== 0 || newRemaining !== 0)) structureComplete = false;
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[3]);
      oldRemaining = hunk[2] === undefined ? 1 : Number(hunk[2]);
      newRemaining = hunk[4] === undefined ? 1 : Number(hunk[4]);
      hunkCount += 1;
      lines.push({ content, kind: "hunk", oldLine: null, newLine: null });
      continue;
    }

    if (content.startsWith("\\ No newline at end of file")) {
      lines.push({ content, kind: "note", oldLine: null, newLine: null });
      continue;
    }
    if (oldLine === null || newLine === null) {
      lines.push({ content, kind: "metadata", oldLine: null, newLine: null });
      continue;
    }

    let rendered: AgentDiffLine;
    if (content.startsWith("+") && newRemaining > 0) {
      rendered = { content, kind: "addition", oldLine: null, newLine };
      newLine += 1;
      newRemaining -= 1;
      addedLines += 1;
    } else if (content.startsWith("-") && oldRemaining > 0) {
      rendered = { content, kind: "deletion", oldLine, newLine: null };
      oldLine += 1;
      oldRemaining -= 1;
      removedLines += 1;
    } else if (content.startsWith(" ") && oldRemaining > 0 && newRemaining > 0) {
      rendered = { content, kind: "context", oldLine, newLine };
      oldLine += 1;
      newLine += 1;
      oldRemaining -= 1;
      newRemaining -= 1;
    } else {
      rendered = { content, kind: "note", oldLine: null, newLine: null };
      structureComplete = false;
    }
    lines.push(rendered);
    if (oldRemaining === 0 && newRemaining === 0) {
      oldLine = null;
      newLine = null;
    }
  }

  if (oldRemaining !== 0 || newRemaining !== 0) structureComplete = false;
  return {
    lines,
    addedLines,
    removedLines,
    hunkCount,
    structureComplete: hunkCount > 0 && structureComplete,
  };
}

function lineLabel(value: number, singular: string): string {
  return `${value} ${value === 1 ? singular : `${singular}s`}`;
}

export function AgentDiffViewer({
  diff,
  label,
  addedLines,
  removedLines,
  compact = false,
}: {
  diff: string;
  label: string;
  addedLines?: number | null;
  removedLines?: number | null;
  compact?: boolean;
}) {
  const [wrapLines, setWrapLines] = useState(false);
  const parsed = useMemo(() => parseAgentUnifiedDiff(diff), [diff]);
  const reportedCounts = typeof addedLines === "number" && typeof removedLines === "number"
    ? { addedLines, removedLines }
    : null;
  const countsMismatch = reportedCounts !== null
    && parsed.structureComplete
    && (reportedCounts.addedLines !== parsed.addedLines || reportedCounts.removedLines !== parsed.removedLines);
  const summaryLabel = parsed.structureComplete
    ? `Diff summary: ${lineLabel(parsed.addedLines, "added line")}, ${lineLabel(parsed.removedLines, "removed line")}, ${lineLabel(parsed.hunkCount, "hunk")}`
    : reportedCounts !== null
      ? `Reviewed summary: ${lineLabel(reportedCounts.addedLines, "added line")}, ${lineLabel(reportedCounts.removedLines, "removed line")}; unified hunk structure unavailable`
      : parsed.hunkCount > 0
        ? "Diff summary unavailable: unified hunk structure is incomplete"
        : "Diff summary unavailable: no unified hunk headers";
  const structuredRenderingAvailable = parsed.structureComplete
    && parsed.lines.length <= MAX_STRUCTURED_DIFF_LINES;

  return <figure
    aria-label={label}
    className="agent-diff-viewer"
    data-compact={compact || undefined}
    data-wrap={wrapLines}
  >
    <figcaption className="agent-diff-viewer__toolbar">
      <span
        aria-label={summaryLabel}
        className="agent-diff-viewer__summary"
      >
        {parsed.structureComplete ? <>
          <strong data-kind="addition">+{parsed.addedLines}</strong>
          <strong data-kind="deletion">−{parsed.removedLines}</strong>
          <span>{lineLabel(parsed.hunkCount, "hunk")}</span>
        </> : reportedCounts !== null ? <>
          <strong data-kind="addition">+{reportedCounts.addedLines}</strong>
          <strong data-kind="deletion">−{reportedCounts.removedLines}</strong>
          <span>Raw review</span>
        </> : <span>Counts unavailable · raw review</span>}
      </span>
      <span className="agent-diff-viewer__actions">
        <button
          aria-pressed={wrapLines}
          className="agent-diff-viewer__toggle"
          onClick={() => setWrapLines((value) => !value)}
          type="button"
        >{wrapLines ? "Keep lines unwrapped" : "Wrap long lines"}</button>
        <AgentCopyButton label={`Copy exact diff for ${label}`} value={diff} />
      </span>
    </figcaption>

    {countsMismatch && reportedCounts !== null && <p className="agent-diff-viewer__mismatch" role="status">
      The rendered diff contains +{parsed.addedLines} / −{parsed.removedLines} lines, while the reviewed summary reports +{reportedCounts.addedLines} / −{reportedCounts.removedLines}. The exact diff remains visible; no count is silently substituted.
    </p>}

    {parsed.hunkCount > 0 && !parsed.structureComplete && <p className="agent-diff-viewer__render-limit" role="status">
      The unified hunk structure is incomplete. Line numbers and derived counts are not presented as authoritative; the exact raw review remains visible below.
    </p>}
    {parsed.structureComplete && !structuredRenderingAvailable && <p className="agent-diff-viewer__render-limit" role="status">
      Structured line rendering is limited to {MAX_STRUCTURED_DIFF_LINES.toLocaleString()} lines. The complete bounded diff remains available below as exact raw text.
    </p>}

    <div
      aria-label={`${label} lines`}
      className="agent-diff-viewer__viewport"
      data-render-mode={structuredRenderingAvailable ? "structured" : "raw"}
      role="region"
      tabIndex={0}
    >
      {structuredRenderingAvailable ? <table>
        <caption className="sr-only">{label}</caption>
        <thead className="sr-only">
          <tr><th>Old line</th><th>New line</th><th>Diff content</th></tr>
        </thead>
        <tbody>
          {parsed.lines.map((line, index) => <tr data-kind={line.kind} key={`${index}:${line.content}`}>
            <td aria-label={line.oldLine === null ? "No old line" : `Old line ${line.oldLine}`} className="agent-diff-viewer__line-number">{line.oldLine ?? ""}</td>
            <td aria-label={line.newLine === null ? "No new line" : `New line ${line.newLine}`} className="agent-diff-viewer__line-number">{line.newLine ?? ""}</td>
            <td className="agent-diff-viewer__content"><code>{line.content || "\u00a0"}</code></td>
          </tr>)}
        </tbody>
      </table> : <pre className="agent-diff-viewer__raw">{diff}</pre>}
    </div>
  </figure>;
}
