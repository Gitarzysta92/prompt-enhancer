import type { AgentEvent } from "../../shared/api/contracts";

export const TOOL_LABELS: Readonly<Record<string, string>> = {
  read_file: "Read file",
  list_dir: "List folder",
  search_text: "Search",
  write_file: "Write file",
  create_directory: "Create directory",
  move_directory: "Move directory",
  move_file: "Move file",
  trash_file: "Move file to Recycle Bin",
  run_command: "Run command",
  fetch_url: "Fetch URL",
};

export function summarizeArguments(
  tool: string | null | undefined,
  args: Record<string, unknown> | null | undefined,
): string {
  if (!args) return "";
  if (tool === "write_file" && Array.isArray(args.paths)) {
    const paths = args.paths.filter((path): path is string => typeof path === "string");
    const visible = paths.slice(0, 3).join(", ");
    const createCount = typeof args.create_count === "number" ? args.create_count : null;
    const editCount = typeof args.edit_count === "number" ? args.edit_count : null;
    const operations = createCount != null && editCount != null
      ? ` · ${createCount} create · ${editCount} edit`
      : "";
    return `${paths.length} files${operations}${visible ? `: ${visible}${paths.length > 3 ? ", …" : ""}` : ""}`;
  }
  if (tool === "read_file" || tool === "write_file" || tool === "create_directory" || tool === "trash_file") return String(args.path ?? "");
  if (tool === "move_file" || tool === "move_directory") return `${String(args.source_path ?? "")} → ${String(args.target_path ?? "")}`;
  if (tool === "list_dir") return String(args.path ?? ".");
  if (tool === "search_text") return `"${String(args.query ?? "")}"${args.glob ? ` in ${String(args.glob)}` : ""}`;
  if (tool === "run_command") return String(args.command ?? "");
  if (tool === "fetch_url") return String(args.url ?? "");
  return JSON.stringify(args).slice(0, 120);
}

export function approvalAction(tool: string | null | undefined): string {
  if (tool === "write_file") return "write";
  if (tool === "create_directory") return "create";
  if (tool === "move_file" || tool === "move_directory") return "move";
  if (tool === "trash_file") return "move to Recycle Bin";
  if (tool === "run_command") return "run";
  if (tool === "fetch_url") return "fetch";
  return "perform";
}

export function isExternalWriteProposal(event: AgentEvent | null | undefined): boolean {
  return event?.tool === "write_file"
    && event.arguments?.source === "external_controller";
}

export function isExternalWriteTransactionProposal(event: AgentEvent | null | undefined): boolean {
  return isExternalWriteProposal(event)
    && ["failure_atomic_existing_files", "failure_atomic_create_edit"].includes(
      String(event?.arguments?.transaction ?? ""),
    )
    && Array.isArray(event?.arguments?.paths);
}
