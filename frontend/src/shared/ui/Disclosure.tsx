import { useId, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

/**
 * Button-driven disclosure. The trigger is a real `<button aria-expanded>`
 * bound to its panel by `aria-controls`, so it works by pointer, keyboard, and
 * screen reader alike. Collapsed panels stay mounted but `hidden`, so the
 * summary line never depends on hover and the height reserved above the panel
 * never changes when it opens.
 */
export function Disclosure({
  summary,
  detail,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  className = "",
  compact = false,
}: {
  summary: ReactNode;
  /** Always-visible secondary text next to the summary; never hover-only. */
  detail?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
  compact?: boolean;
}) {
  const panelId = useId();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolledOpen;
  const toggle = () => {
    const next = !open;
    if (controlledOpen === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  };
  return (
    <div className={`ui-disclosure${compact ? " ui-disclosure--compact" : ""}${className ? ` ${className}` : ""}`} data-open={open ? "true" : "false"}>
      <button
        aria-controls={panelId}
        aria-expanded={open}
        className="ui-disclosure__trigger"
        onClick={toggle}
        type="button"
      >
        <span className="ui-disclosure__chevron"><Icon name="chevron" /></span>
        <span className="ui-disclosure__summary">{summary}</span>
        {detail !== undefined && <span className="ui-disclosure__detail">{detail}</span>}
      </button>
      <div className="ui-disclosure__panel" hidden={!open} id={panelId}>
        {children}
      </div>
    </div>
  );
}
