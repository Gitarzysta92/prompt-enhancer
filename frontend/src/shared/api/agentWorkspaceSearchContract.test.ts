import { describe, expect, it } from "vitest";
import {
  AgentWorkspaceSearchPayloadError,
  parseAgentWorkspaceSearchResult,
} from "./agentWorkspaceSearchContract";

const SESSION = "a".repeat(32);

type SearchPayload = {
  contract_version: string;
  session_id: string;
  scope: string;
  coverage: string;
  reasons: string[];
  reason_code: string | null;
  scanned_entry_count: number;
  inspected_byte_count: number;
  skipped_entry_count: number;
  match_count: number;
  matches: Array<{ path: string; line_number: number; preview: string }>;
  root?: string;
};

function result(): SearchPayload {
  return {
    contract_version: "local-agent-workspace-search.v1",
    session_id: SESSION,
    scope: "application_readable_utf8_text",
    coverage: "complete",
    reasons: [],
    reason_code: null,
    scanned_entry_count: 12,
    inspected_byte_count: 420,
    skipped_entry_count: 2,
    match_count: 2,
    matches: [
      { path: "README.md", line_number: 3, preview: "Synthetic match" },
      { path: "src/app.ts", line_number: 8, preview: "syntheticMatch();" },
    ],
  };
}

describe("workspace search response contract", () => {
  it("accepts canonical bounded matches and explicit scope evidence", () => {
    const parsed = parseAgentWorkspaceSearchResult(result(), SESSION);
    expect(parsed.coverage).toBe("complete");
    expect(parsed.matches.map((item) => `${item.path}:${item.line_number}`)).toEqual([
      "README.md:3",
      "src/app.ts:8",
    ]);
  });

  it("accepts partial coverage only with a bounded reason and code", () => {
    const value = result();
    value.coverage = "partial";
    value.reasons = ["match limit reached"];
    value.reason_code = "workspace_inspection_incomplete";
    expect(parseAgentWorkspaceSearchResult(value, SESSION).coverage).toBe("partial");
  });

  it.each([
    ["foreign session", (value: ReturnType<typeof result>) => { value.session_id = "b".repeat(32); }],
    ["absolute path", (value: ReturnType<typeof result>) => { value.matches[0].path = "C:/private.txt"; }],
    ["traversal", (value: ReturnType<typeof result>) => { value.matches[0].path = "../private.txt"; }],
    ["duplicate match", (value: ReturnType<typeof result>) => { value.matches[1] = { ...value.matches[0] }; }],
    ["wrong order", (value: ReturnType<typeof result>) => { value.matches.reverse(); }],
    ["wrong count", (value: ReturnType<typeof result>) => { value.match_count = 1; }],
    ["complete with reason", (value: ReturnType<typeof result>) => { value.reasons = ["match limit reached"]; }],
    ["partial without reason", (value: ReturnType<typeof result>) => { value.coverage = "partial"; value.reason_code = "workspace_inspection_incomplete"; }],
    ["multiline preview", (value: ReturnType<typeof result>) => { value.matches[0].preview = "one\ntwo"; }],
    ["terminal control preview", (value: ReturnType<typeof result>) => { value.matches[0].preview = "one\u001b[31m"; }],
    ["bidirectional control preview", (value: ReturnType<typeof result>) => { value.matches[0].preview = "one\u202etwo"; }],
    ["private extra", (value: ReturnType<typeof result>) => { value.root = "private"; }],
  ])("rejects %s", (_name, mutate) => {
    const value = result();
    mutate(value);
    expect(() => parseAgentWorkspaceSearchResult(value, SESSION)).toThrow(
      AgentWorkspaceSearchPayloadError,
    );
  });
});
