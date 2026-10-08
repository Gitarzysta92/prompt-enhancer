export type IdempotentAction =
  | "accept"
  | "reject"
  | "merge"
  | "split"
  | "analysis"
  | "quality-analysis"
  | "quality-preview-approval"
  | "model-link-experiment"
  | "model-ensemble"
  | "declared-task-profile"
  | "task-lifecycle";

/** A content-free, collision-resistant key generated only for a local command. */
export function nextIdempotencyKey(action: IdempotentAction): string {
  return `dashboard-${action}-${globalThis.crypto.randomUUID()}`;
}
