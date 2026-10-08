import type { ReactNode } from "react";

/**
 * One term/detail pair. A `null` detail is rendered as an explicit "not
 * reported" texture instead of an empty cell, so an absent fact can never read
 * as a zero, a blank, or a silently omitted row.
 */
export interface Fact {
  term: string;
  detail: ReactNode | null;
  /** Copy for a `null` detail; defaults to "Not reported". */
  missingLabel?: string;
}

/**
 * Definition-list primitive shared by metric cards, social detail panes, and
 * task-flow drawers. It reserves nothing asynchronously: the caller passes the
 * complete fact set, so the list never grows after mount.
 */
export function FactList({
  facts,
  label,
  compact = false,
  className = "",
}: {
  facts: readonly Fact[];
  label?: string;
  compact?: boolean;
  className?: string;
}) {
  return (
    <dl
      aria-label={label}
      className={`fact-list${compact ? " fact-list--compact" : ""}${className ? ` ${className}` : ""}`}
    >
      {facts.map((fact) => (
        <div data-unknown={fact.detail === null ? "true" : undefined} key={fact.term}>
          <dt>{fact.term}</dt>
          <dd>{fact.detail === null ? (fact.missingLabel ?? "Not reported") : fact.detail}</dd>
        </div>
      ))}
    </dl>
  );
}
