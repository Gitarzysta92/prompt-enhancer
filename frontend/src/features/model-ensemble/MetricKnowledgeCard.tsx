import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { MetricContextFactList } from "./MetricContextFactList";
import type { MetricContextFacts } from "./metricContextFacts";
import {
  metricHelpV2,
  metricHelpV2DefinitionLabel,
  type MetricHelpProjectionVersion,
  type MetricInspectorSentences,
} from "./metricHelpV2";

/**
 * One knowledge-card controller per workspace. A target is {surface, metricKey};
 * at most one card is visible across every trigger surface (axis strip and
 * exact-value board). Triggers get `aria-describedby` pointing at an always
 * present hidden one-sentence description, so semantics never depend on the
 * visible card. The visible card is a viewport-clamped overlay: opening it
 * never changes the radar/workspace layout.
 */
export type MetricKnowledgeSurface =
  | "strip"
  | "board"
  | "team-board"
  | "team-compact"
  | "team-members";
export interface MetricKnowledgeTarget { surface: MetricKnowledgeSurface; metricKey: string }

export interface MetricKnowledgeAnchor {
  bottom: number;
  left: number;
  right: number;
  top: number;
  /** Scroll offsets captured with the viewport-relative rectangle. */
  viewportScrollX?: number;
  viewportScrollY?: number;
}

export interface MetricKnowledgeCardController {
  idPrefix: string;
  target: MetricKnowledgeTarget | null;
  pinned: boolean;
  /** True only when the open target belongs to the current owning context. */
  contextIsCurrent: boolean;
  /** Plain viewport coordinates only; never retain the originating DOM node. */
  anchor?: MetricKnowledgeAnchor | null;
  preview: (target: MetricKnowledgeTarget, anchor?: MetricKnowledgeAnchor) => void;
  unpreview: (target: MetricKnowledgeTarget) => void;
  togglePin: (target: MetricKnowledgeTarget, anchor?: MetricKnowledgeAnchor) => void;
  dismiss: () => void;
}

export const METRIC_KNOWLEDGE_CARD_LEAVE_DELAY_MS = 150;

/**
 * Rich, structured, pinnable explainer/knowledge content is a non-modal
 * `region` (named by `aria-label`), never a `tooltip`: tooltip content is
 * expected to be plain, transient text and is not navigable by assistive
 * technology, while these cards carry sections, definition lists and links.
 */
export const METRIC_CARD_ROLE = "region" as const;

const same = (left: MetricKnowledgeTarget | null, right: MetricKnowledgeTarget): boolean =>
  left !== null && left.surface === right.surface && left.metricKey === right.metricKey;

const targetIdentity = (target: MetricKnowledgeTarget): string => `${target.surface}:${target.metricKey}`;

export const metricKnowledgeAnchorFromElement = (element: Element): MetricKnowledgeAnchor => {
  const rect = element.getBoundingClientRect();
  return {
    bottom: rect.bottom,
    left: rect.left,
    right: rect.right,
    top: rect.top,
    viewportScrollX: typeof window === "undefined" ? 0 : window.scrollX,
    viewportScrollY: typeof window === "undefined" ? 0 : window.scrollY,
  };
};

/**
 * Position the card outside its trigger row. The earlier fixed bottom-right
 * placement could cover later axis controls, making valid metrics impossible
 * to select with a pointer even though keyboard/unit tests still passed.
 */
export function metricKnowledgeCardViewportStyle(
  controller: Pick<MetricKnowledgeCardController, "anchor">,
  preferredWidth = 360,
): CSSProperties | undefined {
  const anchor = controller.anchor;
  if (anchor == null || typeof window === "undefined") return undefined;
  const margin = 12;
  const gap = 8;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const scrollDeltaX = (anchor.viewportScrollX ?? window.scrollX) - window.scrollX;
  const scrollDeltaY = (anchor.viewportScrollY ?? window.scrollY) - window.scrollY;
  const anchorLeft = anchor.left + scrollDeltaX;
  const anchorTop = anchor.top + scrollDeltaY;
  const anchorBottom = anchor.bottom + scrollDeltaY;
  const width = Math.max(0, Math.min(preferredWidth, viewportWidth - margin * 2));
  const left = Math.max(margin, Math.min(anchorLeft, viewportWidth - margin - width));
  if (anchorBottom <= margin || anchorTop >= viewportHeight - margin) {
    return {
      bottom: "auto",
      left,
      maxHeight: Math.max(0, viewportHeight - margin * 2),
      right: "auto",
      top: margin,
    };
  }
  const below = Math.max(0, viewportHeight - anchorBottom - gap - margin);
  const above = Math.max(0, anchorTop - gap - margin);
  const placeBelow = below >= Math.min(240, viewportHeight * 0.45) || below >= above;
  const availableHeight = placeBelow ? below : above;
  // Extremely short viewports cannot keep the overlay outside the trigger and
  // still expose meaningful content. In that case keep the complete card
  // inside the viewport and let its own scroller preserve every field.
  if (availableHeight < 96) {
    return {
      bottom: "auto",
      left,
      maxHeight: Math.max(0, viewportHeight - margin * 2),
      right: "auto",
      top: margin,
    };
  }
  return {
    bottom: placeBelow ? "auto" : viewportHeight - anchorTop + gap,
    left,
    maxHeight: Math.min(availableHeight, viewportHeight - margin * 2),
    right: "auto",
    top: placeBelow ? anchorBottom + gap : "auto",
  };
}

/** Re-render an open viewport overlay after zoom/resize/scroll changes. */
export function useMetricKnowledgeOverlayViewport(active: boolean): void {
  const [, setRevision] = useState(0);
  useEffect(() => {
    if (!active || typeof window === "undefined") return undefined;
    const update = () => setRevision((current) => current + 1);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [active]);
}

export type MetricCardContextIdentity = string | number;

export function useMetricKnowledgeCardController(
  contextIdentity: MetricCardContextIdentity,
): MetricKnowledgeCardController {
  const idPrefix = useId();
  const [state, setState] = useState<{
    target: MetricKnowledgeTarget | null;
    pinned: boolean;
    anchor: MetricKnowledgeAnchor | null;
    contextIdentity: MetricCardContextIdentity;
  }>({ target: null, pinned: false, anchor: null, contextIdentity });
  const leaveTimer = useRef<number | null>(null);
  const recentAnchors = useRef(new Map<string, MetricKnowledgeAnchor>());
  const clearLeave = () => {
    if (leaveTimer.current !== null) {
      window.clearTimeout(leaveTimer.current);
      leaveTimer.current = null;
    }
  };
  const preview = useCallback((target: MetricKnowledgeTarget, anchor?: MetricKnowledgeAnchor) => {
    clearLeave();
    if (anchor !== undefined) recentAnchors.current.set(targetIdentity(target), anchor);
    setState((current) => current.pinned && Object.is(current.contextIdentity, contextIdentity) ? current : {
      target,
      pinned: false,
      anchor: anchor ?? (Object.is(current.contextIdentity, contextIdentity) && same(current.target, target)
        ? current.anchor
        : null),
      contextIdentity,
    });
  }, [contextIdentity]);
  const unpreview = useCallback((target: MetricKnowledgeTarget) => {
    clearLeave();
    leaveTimer.current = window.setTimeout(() => {
      setState((current) => current.pinned || !Object.is(current.contextIdentity, contextIdentity) || !same(current.target, target)
        ? current
        : { target: null, pinned: false, anchor: null, contextIdentity });
    }, METRIC_KNOWLEDGE_CARD_LEAVE_DELAY_MS);
  }, [contextIdentity]);
  const togglePin = useCallback((target: MetricKnowledgeTarget, anchor?: MetricKnowledgeAnchor) => {
    clearLeave();
    const recentAnchor = recentAnchors.current.get(targetIdentity(target));
    setState((current) => current.pinned
      && Object.is(current.contextIdentity, contextIdentity)
      && same(current.target, target)
      ? { target: null, pinned: false, anchor: null, contextIdentity }
      : {
        target,
        pinned: true,
        anchor: anchor ?? recentAnchor ?? (Object.is(current.contextIdentity, contextIdentity) && same(current.target, target)
          ? current.anchor
          : null),
        contextIdentity,
      });
  }, [contextIdentity]);
  const dismiss = useCallback(() => {
    clearLeave();
    setState({ target: null, pinned: false, anchor: null, contextIdentity });
  }, [contextIdentity]);
  const contextIsCurrent = Object.is(state.contextIdentity, contextIdentity);
  useLayoutEffect(() => {
    if (contextIsCurrent) return;
    recentAnchors.current.clear();
    dismiss();
  }, [contextIsCurrent, dismiss]);
  useEffect(() => {
    if (state.target === null) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dismiss, state.target]);
  useEffect(() => () => clearLeave(), []);
  return {
    idPrefix,
    target: contextIsCurrent ? state.target : null,
    pinned: contextIsCurrent && state.pinned,
    contextIsCurrent,
    anchor: contextIsCurrent ? state.anchor : null,
    preview,
    unpreview,
    togglePin,
    dismiss,
  };
}

export function metricKnowledgeDescriptionId(controller: Pick<MetricKnowledgeCardController, "idPrefix">, metricKey: string): string {
  return `${controller.idPrefix}help-${metricKey.replaceAll(".", "-")}`;
}

export function metricKnowledgeCardId(
  controller: Pick<MetricKnowledgeCardController, "idPrefix">,
  surface: MetricKnowledgeSurface,
  metricKey: string,
): string {
  return `${controller.idPrefix}help-card-${surface}-${metricKey.replaceAll(".", "-")}`;
}

/** Trigger props for the accessible controls (buttons/tiles) that describe a metric. */
export function metricKnowledgeCardTriggerProps(
  controller: MetricKnowledgeCardController,
  surface: MetricKnowledgeSurface,
  metricKey: string,
) {
  const target = { surface, metricKey };
  const open = same(controller.target, target);
  return {
    "aria-controls": metricKnowledgeCardId(controller, surface, metricKey),
    "aria-describedby": metricKnowledgeDescriptionId(controller, metricKey),
    "aria-expanded": open,
    "data-help-open": open ? (controller.pinned ? "pinned" : "preview") : undefined,
    onPointerEnter: (event: ReactPointerEvent<HTMLElement>) =>
      controller.preview(target, metricKnowledgeAnchorFromElement(event.currentTarget)),
    // Touch does not guarantee a preceding pointer-enter. Capture its anchor
    // before the consumer's click handler toggles the pinned state.
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) =>
      controller.preview(target, metricKnowledgeAnchorFromElement(event.currentTarget)),
    onPointerLeave: () => controller.unpreview(target),
    onFocus: (event: FocusEvent<HTMLElement>) =>
      controller.preview(target, metricKnowledgeAnchorFromElement(event.currentTarget)),
    onBlur: () => controller.unpreview(target),
  } as const;
}

export interface MetricKnowledgeEntry {
  key: string;
  label: string;
  status: string;
  /** Exact sealed projection selecting frozen historical or current help. */
  projectionVersion?: MetricHelpProjectionVersion | null;
  /** Exact receipt state and authority projected by metricAxisModel. */
  guidance?: MetricInspectorSentences;
  /** Scope · contributors · model · evidence context; rendered in full and compact cards alike. */
  context?: MetricContextFacts;
}

/** Always-present hidden one-sentence descriptions referenced by every trigger. */
export function MetricKnowledgeDescriptions({ controller, entries }: {
  controller: MetricKnowledgeCardController;
  entries: readonly MetricKnowledgeEntry[];
}) {
  return (
    <div className="metric-knowledge-descriptions" hidden>
      {entries.map((entry) => (
        <span id={metricKnowledgeDescriptionId(controller, entry.key)} key={entry.key}>
          {entry.label}: {entry.guidance === undefined
            ? metricHelpV2(entry.key, "en", entry.projectionVersion ?? null)?.entry.meaning ?? "No knowledge card is registered for this metric key."
            : `${entry.guidance.meaning} ${entry.guidance.action}`}
          {entry.context === undefined ? "" : ` Scope: ${entry.context.label}.`}
        </span>
      ))}
    </div>
  );
}

/** Viewport overlay slot for one surface; renders the single open card, if it targets this surface. */
export function MetricKnowledgeCardSlot({ controller, surface, entries, compact = false }: {
  controller: MetricKnowledgeCardController;
  surface: MetricKnowledgeSurface;
  entries: readonly MetricKnowledgeEntry[];
  compact?: boolean;
}) {
  const target = controller.target;
  const entry = target !== null && target.surface === surface
    ? entries.find((candidate) => candidate.key === target.metricKey) ?? null
    : null;
  const staleTarget = target !== null && target.surface === surface && entry === null;
  useMetricKnowledgeOverlayViewport(entry !== null);
  useEffect(() => {
    // A pinned key can disappear when the user changes lens.  Dismiss it so
    // the next pointer/focus preview is never blocked by an invisible target.
    if (staleTarget) controller.dismiss();
  }, [controller.dismiss, staleTarget]);
  if (entry === null) return <div className="metric-knowledge-slot" data-surface={surface} />;
  const help = metricHelpV2(entry.key, "en", entry.projectionVersion ?? null);
  const definitionLabel = help === null ? null : metricHelpV2DefinitionLabel(help);
  const definitionHeading = definitionLabel === null
    ? null
    : `${definitionLabel.charAt(0).toUpperCase()}${definitionLabel.slice(1)}`;
  const pinned = controller.pinned;
  const cardId = metricKnowledgeCardId(controller, surface, entry.key);
  const cardHeadingId = `${cardId}-heading`;
  return (
    <div className="metric-knowledge-slot" data-surface={surface}>
      <div
        aria-labelledby={cardHeadingId}
        className={`metric-knowledge-card metric-knowledge-card--viewport${compact ? " metric-knowledge-card--compact" : ""}`}
        data-metric-key={entry.key}
        data-pinned={pinned ? "true" : "false"}
        data-projection-version={entry.projectionVersion ?? undefined}
        data-state={entry.guidance?.state}
        data-suppression-reason={entry.guidance?.suppressionReason ?? undefined}
        data-comparability={entry.guidance?.comparabilityState ?? undefined}
        id={cardId}
        onBlurCapture={() => controller.unpreview({ surface, metricKey: entry.key })}
        onFocusCapture={() => controller.preview({ surface, metricKey: entry.key })}
        onPointerEnter={() => controller.preview({ surface, metricKey: entry.key })}
        onPointerLeave={() => controller.unpreview({ surface, metricKey: entry.key })}
        role={METRIC_CARD_ROLE}
        style={metricKnowledgeCardViewportStyle(controller, compact ? 320 : 360)}
        tabIndex={0}
      >
        <header role="presentation">
          <strong aria-label={`${entry.label} knowledge card`} id={cardHeadingId}>{entry.label}</strong>
          <span>{entry.status}</span>
        </header>
        {entry.guidance !== undefined && (
          <section aria-label="Current metric guidance" className="metric-knowledge-card__guidance">
            <p><b>Current state.</b> {entry.guidance.meaning}</p>
            <p><b>Next action.</b> {entry.guidance.action}</p>
            <dl>
              <div><dt>Guidance basis</dt><dd>{entry.guidance.basis}</dd></div>
              <div><dt>Evidence authority</dt><dd>{entry.guidance.evidenceAuthority ?? "Not reported by this receipt"}</dd></div>
              <div><dt>Explanation code</dt><dd>{entry.guidance.explanationCode ?? "None"}</dd></div>
              <div><dt>Suppression</dt><dd>{entry.guidance.suppressionReason ?? "None"}</dd></div>
              <div><dt>Comparability</dt><dd>{entry.guidance.comparabilityState ?? "Not exposed"}</dd></div>
            </dl>
          </section>
        )}
        {entry.context !== undefined && <MetricContextFactList compact={compact} context={entry.context} />}
        {help === null ? (
          <p>No knowledge card is registered for this metric key.</p>
        ) : (
          <>
            <p>
              <b>{definitionHeading} definition.</b> {help.entry.meaning}
            </p>
            <dl>
              <div><dt>Question</dt><dd>{help.entry.question}</dd></div>
              <div><dt>Unit</dt><dd>{help.entry.observationUnit}</dd></div>
              <div><dt>Direction</dt><dd>{help.entry.direction}</dd></div>
              <div><dt>Counts</dt><dd>{help.entry.counts}</dd></div>
              <div><dt>Does not count</dt><dd>{help.entry.doesNotCount}</dd></div>
              {entry.guidance === undefined && (
                <div><dt>Candidate definition evidence notes</dt><dd>{help.entry.objectiveEvidence}</dd></div>
              )}
            </dl>
            {help.measurement !== null && (
              <p className="metric-knowledge-card__measurement">
                <b>{help.definitionScope !== "historical_candidate"
                  ? `${definitionHeading} measurement (definition v${help.measurement.definitionVersion}).`
                  : `Current measurement (shipped definition v${help.measurement.definitionVersion}).`}</b> {help.measurement.method} {help.measurement.limitation}
              </p>
            )}
          </>
        )}
        <footer>{pinned ? "Pinned · Esc closes" : "Click or tap the control to pin · Esc closes"} · {help?.version ?? "unversioned"} · {help?.definitionScope === "historical_candidate" || help === null ? "candidate definition shown separately from its shipped measurement method" : `${definitionLabel} definition shown with projection-specific measurement metadata`}</footer>
      </div>
    </div>
  );
}
