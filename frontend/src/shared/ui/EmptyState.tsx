import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

/**
 * Honest empty/closed state. `tone="closed"` is for capabilities the runtime
 * refuses to serve (fail-closed), distinct from "nothing here yet". The block
 * reserves a stable minimum height so swapping loading → empty → content does
 * not shift surrounding layout.
 */
export function EmptyState({
  title,
  description,
  icon = "info",
  tone = "empty",
  action,
  compact = false,
  role = "status",
}: {
  title: string;
  description?: ReactNode;
  icon?: IconName;
  tone?: "empty" | "closed";
  action?: ReactNode;
  compact?: boolean;
  role?: "status" | "note";
}) {
  return (
    <div
      className={`ui-empty-state${compact ? " ui-empty-state--compact" : ""}`}
      data-tone={tone}
      role={role}
    >
      <span aria-hidden="true" className="ui-empty-state__icon"><Icon name={tone === "closed" ? "lock" : icon} /></span>
      <strong>{title}</strong>
      {description !== undefined && <p>{description}</p>}
      {action !== undefined && <div className="ui-empty-state__action">{action}</div>}
    </div>
  );
}
