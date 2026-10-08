import type { ReactNode } from "react";
import { Icon } from "./Icon";

/**
 * Unmistakable "this is fiction" banner for synthetic demo surfaces. Every
 * social identity, message, and file below it is invented fixture data; the
 * banner names that in visible text so no screenshot or reader can mistake the
 * demo for a live account, delivery, or storage service.
 */
export function FictionalNotice({
  title = "Fictional synthetic demo",
  children,
  compact = false,
}: {
  title?: string;
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <div aria-label={title} className={`ui-fictional-notice${compact ? " ui-fictional-notice--compact" : ""}`} role="note">
      <span aria-hidden="true" className="ui-fictional-notice__icon"><Icon name="info" /></span>
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </div>
  );
}
