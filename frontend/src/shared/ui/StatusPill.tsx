import type { ReactNode } from "react";

export type PillTone = "neutral" | "unknown" | "positive" | "warning" | "info" | "danger";

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: PillTone;
}) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}
