import type { CandidateListItem, CandidateSignal } from "../../shared/api/contracts";

export type { CandidateListItem, CandidateSignal };

export function candidateLabel(candidateId: string): string {
  return `Candidate ${candidateId.slice(0, 6)}`;
}

/** Session title, then project title, then the hash - so a person can recognise the task. */
export function candidateTitle(candidate: {
  candidate_id: string;
  session_display_name?: string | null;
  project_display_name?: string | null;
  session_ids: readonly string[];
}): string {
  const session = candidate.session_display_name?.trim();
  if (session) return session;
  const project = candidate.project_display_name?.trim();
  if (project) {
    const count = candidate.session_ids.length;
    return `${project} · ${count} session${count === 1 ? "" : "s"}`;
  }
  return candidateLabel(candidate.candidate_id);
}

export function evidenceDirectionLabel(direction: CandidateSignal["direction"]): string {
  if (direction === "supports_link") return "Supports grouping";
  if (direction === "supports_boundary") return "Supports a boundary";
  return "Unknown evidence";
}
