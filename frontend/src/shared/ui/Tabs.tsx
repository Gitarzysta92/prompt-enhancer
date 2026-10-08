import { useEffect, useState } from "react";
import { moveRovingFocus } from "./rovingFocus";

export interface TabDescriptor<Id extends string> {
  id: Id;
  label: string;
  /** Visible secondary text (count, hint); never hover-only. */
  detail?: string;
  /** Optional numeric badge such as an unread count. */
  badge?: number;
  badgeLabel?: string;
}

/**
 * Roving-focus tab strip. Tabs are `role="tab"` buttons inside a labelled
 * `role="tablist"`; the caller renders the matching `role="tabpanel"` with
 * `id={tabPanelId(idPrefix, id)}` and `aria-labelledby={tabId(idPrefix, id)}`.
 * Arrow keys move focus and selection; Tab leaves the strip.
 */
export function tabId(prefix: string, id: string): string {
  return `${prefix}-tab-${id}`;
}

export function tabPanelId(prefix: string, id: string): string {
  return `${prefix}-panel-${id}`;
}

export function TabList<Id extends string>({
  idPrefix,
  label,
  tabs,
  value,
  onChange,
  activationMode = "automatic",
  compact = false,
  className = "",
}: {
  idPrefix: string;
  label: string;
  tabs: readonly TabDescriptor<Id>[];
  value: Id;
  onChange: (id: Id) => void;
  activationMode?: "automatic" | "manual";
  compact?: boolean;
  className?: string;
}) {
  const [focusedValue, setFocusedValue] = useState<Id>(value);
  useEffect(() => setFocusedValue(value), [value]);

  return (
    <div
      aria-label={label}
      aria-orientation="horizontal"
      className={`ui-tabs${compact ? " ui-tabs--compact" : ""}${className ? ` ${className}` : ""}`}
      onKeyDown={(event) => {
        if (event.key === "ArrowUp" || event.key === "ArrowDown") return;
        moveRovingFocus(event, (index) => {
          const id = tabs[index].id;
          setFocusedValue(id);
          if (activationMode === "automatic") onChange(id);
        });
      }}
      role="tablist"
    >
      {tabs.map((tab) => {
        const selected = tab.id === value;
        return (
          <button
            aria-controls={tabPanelId(idPrefix, tab.id)}
            aria-selected={selected}
            className="ui-tabs__tab"
            id={tabId(idPrefix, tab.id)}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            onFocus={() => setFocusedValue(tab.id)}
            role="tab"
            tabIndex={(activationMode === "manual" ? tab.id === focusedValue : selected) ? 0 : -1}
            type="button"
          >
            <span>{tab.label}</span>
            {tab.detail !== undefined && <small>{tab.detail}</small>}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span aria-label={tab.badgeLabel ?? `${tab.badge} unread`} className="ui-tabs__badge">{tab.badge}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
