import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentDiffViewer, MAX_STRUCTURED_DIFF_LINES, parseAgentUnifiedDiff } from "./AgentDiffViewer";

const DIFF = [
  "--- a/src/example.ts",
  "+++ b/src/example.ts",
  "@@ -2,3 +2,4 @@",
  " context",
  "-old value",
  "+new value",
  "+another value",
  " context after",
  "@@ -10 +11 @@ second",
  "-last old",
  "+last new",
  "\\ No newline at end of file",
].join("\n");

describe("parseAgentUnifiedDiff", () => {
  it("derives exact hunk counts and old/new line numbers", () => {
    const parsed = parseAgentUnifiedDiff(DIFF);

    expect(parsed).toMatchObject({ addedLines: 3, removedLines: 2, hunkCount: 2, structureComplete: true });
    expect(parsed.lines.map(({ kind, oldLine, newLine }) => ({ kind, oldLine, newLine }))).toEqual([
      { kind: "metadata", oldLine: null, newLine: null },
      { kind: "metadata", oldLine: null, newLine: null },
      { kind: "hunk", oldLine: null, newLine: null },
      { kind: "context", oldLine: 2, newLine: 2 },
      { kind: "deletion", oldLine: 3, newLine: null },
      { kind: "addition", oldLine: null, newLine: 3 },
      { kind: "addition", oldLine: null, newLine: 4 },
      { kind: "context", oldLine: 4, newLine: 5 },
      { kind: "hunk", oldLine: null, newLine: null },
      { kind: "deletion", oldLine: 10, newLine: null },
      { kind: "addition", oldLine: null, newLine: 11 },
      { kind: "note", oldLine: null, newLine: null },
    ]);
  });

  it("keeps a non-unified payload visible as metadata without inventing counts", () => {
    expect(parseAgentUnifiedDiff("bounded review unavailable")).toEqual({
      lines: [{ content: "bounded review unavailable", kind: "metadata", oldLine: null, newLine: null }],
      addedLines: 0,
      removedLines: 0,
      hunkCount: 0,
      structureComplete: false,
    });
  });

  it("parses multiple file sections without confusing header-like deleted content", () => {
    const parsed = parseAgentUnifiedDiff([
      "--- a/first.txt",
      "+++ b/first.txt",
      "@@ -1 +1 @@",
      "--- header-like deleted text",
      "+first replacement",
      "--- a/second.txt",
      "+++ b/second.txt",
      "@@ -4 +4 @@",
      "-second old",
      "+second new",
    ].join("\n"));

    expect(parsed).toMatchObject({ addedLines: 2, removedLines: 2, hunkCount: 2, structureComplete: true });
    expect(parsed.lines[3]).toMatchObject({ kind: "deletion", oldLine: 1, newLine: null });
    expect(parsed.lines[5]).toMatchObject({ kind: "metadata", oldLine: null, newLine: null });
    expect(parsed.lines[6]).toMatchObject({ kind: "metadata", oldLine: null, newLine: null });
  });

  it("marks truncated hunks incomplete instead of presenting partial counts as exact", () => {
    const parsed = parseAgentUnifiedDiff("--- a/file\n+++ b/file\n@@ -1,2 +1,2 @@\n-old\n+new");

    expect(parsed).toMatchObject({ addedLines: 1, removedLines: 1, hunkCount: 1, structureComplete: false });
  });
});

describe("AgentDiffViewer", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("renders structured lines, a truthful summary, and keyboard-scrollable review", () => {
    render(<AgentDiffViewer diff={DIFF} label="Manual edit diff" />);

    expect(screen.getByLabelText("Diff summary: 3 added lines, 2 removed lines, 2 hunks")).toBeVisible();
    expect(screen.getByRole("region", { name: "Manual edit diff lines" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "Manual edit diff lines" })).toHaveAttribute("data-render-mode", "structured");
    expect(screen.getByLabelText("Old line 3")).toHaveTextContent("3");
    expect(screen.getByLabelText("New line 4")).toHaveTextContent("4");
    expect(screen.getByText("+another value").closest("tr")).toHaveAttribute("data-kind", "addition");
  });

  it("wraps only on request and copies the exact reviewed diff", async () => {
    render(<AgentDiffViewer diff={DIFF} label="Recovery diff" />);
    const figure = screen.getByRole("figure", { name: "Recovery diff" });
    const wrap = screen.getByRole("button", { name: "Wrap long lines" });

    expect(figure).toHaveAttribute("data-wrap", "false");
    fireEvent.click(wrap);
    expect(figure).toHaveAttribute("data-wrap", "true");
    expect(screen.getByRole("button", { name: "Keep lines unwrapped" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Copy exact diff for Recovery diff" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledExactlyOnceWith(DIFF);
  });

  it("discloses a contradictory server summary instead of replacing either count", () => {
    render(<AgentDiffViewer addedLines={9} diff={DIFF} label="Net diff" removedLines={8} />);

    expect(screen.getByRole("status")).toHaveTextContent("rendered diff contains +3 / −2 lines");
    expect(screen.getByRole("status")).toHaveTextContent("reviewed summary reports +9 / −8");
  });

  it("does not present zero additions or removals for an unstructured raw review", () => {
    render(<AgentDiffViewer diff={"-old\n+new"} label="Agent raw review" />);

    expect(screen.getByLabelText("Diff summary unavailable: no unified hunk headers")).toHaveTextContent("Counts unavailable · raw review");
    expect(screen.queryByLabelText(/Diff summary: 0 added lines/u)).not.toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Agent raw review" })).toHaveTextContent("+new");
    expect(screen.getByRole("region", { name: "Agent raw review lines" })).toHaveAttribute("data-render-mode", "raw");
  });

  it("renders an incomplete unified hunk as exact raw text with an explicit warning", () => {
    const diff = "--- a/file\n+++ b/file\n@@ -1,2 +1,2 @@\n-old\n+new";
    render(<AgentDiffViewer diff={diff} label="Truncated review" />);

    expect(screen.getByLabelText("Diff summary unavailable: unified hunk structure is incomplete")).toHaveTextContent("Counts unavailable · raw review");
    expect(screen.getByRole("status")).toHaveTextContent("hunk structure is incomplete");
    expect(screen.getByRole("region", { name: "Truncated review lines" })).toHaveAttribute("data-render-mode", "raw");
  });

  it("keeps very tall bounded diffs complete while avoiding thousands of table rows", () => {
    const additions = Array.from({ length: MAX_STRUCTURED_DIFF_LINES }, (_, index) => `+line ${index + 1}`);
    const diff = [
      "--- /dev/null",
      "+++ b/large.txt",
      `@@ -0,0 +1,${MAX_STRUCTURED_DIFF_LINES} @@`,
      ...additions,
    ].join("\n");
    render(<AgentDiffViewer diff={diff} label="Large bounded diff" />);

    const viewport = screen.getByRole("region", { name: "Large bounded diff lines" });
    expect(viewport).toHaveAttribute("data-render-mode", "raw");
    expect(viewport.querySelector("table")).not.toBeInTheDocument();
    expect(viewport).toHaveTextContent(`+line ${MAX_STRUCTURED_DIFF_LINES}`);
    expect(screen.getByRole("status")).toHaveTextContent(`limited to ${MAX_STRUCTURED_DIFF_LINES.toLocaleString()} lines`);
  });
});
