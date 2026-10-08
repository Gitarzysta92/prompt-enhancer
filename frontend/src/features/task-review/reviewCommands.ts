import type {
  CandidateListItem,
  RejectionReason,
  ReviewCommand,
  TaskCategory,
} from "../../shared/api/contracts";

export function acceptCommand(
  item: CandidateListItem,
  taskCategory: TaskCategory,
): ReviewCommand {
  return {
    action: "accept",
    request: {
      candidate_id: item.candidate.candidate_id,
      expected_discovery_version: item.candidate.discovery_version,
      task_category: taskCategory,
    },
  };
}

export function rejectCommand(
  item: CandidateListItem,
  reason: RejectionReason,
): ReviewCommand {
  return {
    action: "reject",
    request: {
      candidate_id: item.candidate.candidate_id,
      expected_discovery_version: item.candidate.discovery_version,
      reason,
    },
  };
}

export function mergeCommand(
  items: CandidateListItem[],
  taskCategory: TaskCategory = "unknown",
): ReviewCommand {
  if (items.length < 2) throw new Error("At least two candidates are required");
  const versions = new Set(items.map((item) => item.candidate.discovery_version));
  if (versions.size !== 1) throw new Error("Selected candidates use different discovery versions");
  return {
    action: "merge",
    request: {
      candidate_ids: items.map((item) => item.candidate.candidate_id),
      expected_discovery_version: items[0].candidate.discovery_version,
      task_category: taskCategory,
    },
  };
}

export function splitCommand(
  item: CandidateListItem,
  assignments: Record<string, "a" | "b">,
): ReviewCommand {
  const partitions = (["a", "b"] as const)
    .map((group) =>
      item.candidate.session_ids.filter((sessionId) => assignments[sessionId] === group),
    )
    .filter((partition) => partition.length > 0);
  if (partitions.length !== 2) throw new Error("Both split groups need at least one session");
  return {
    action: "split",
    request: {
      candidate_id: item.candidate.candidate_id,
      expected_discovery_version: item.candidate.discovery_version,
      partitions,
      task_categories: ["unknown", "unknown"],
    },
  };
}
