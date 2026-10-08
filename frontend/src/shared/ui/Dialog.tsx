import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";

const FOCUSABLE = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "summary",
  "[tabindex]",
].join(",");

const DIALOG_ROOT_ATTRIBUTE = "data-ui-dialog-root";
const DialogDepthContext = createContext(0);

type InertSnapshot = {
  element: HTMLElement;
  inertAttribute: string | null;
};

type DialogRegistration = {
  depth: number;
  root: HTMLElement;
  sequence: number;
};

let modalLockCount = 0;
let nextDialogSequence = 0;
let inertSnapshots = new Map<HTMLElement, InertSnapshot>();
let bodyOverflow = "";
let documentOverflow = "";
let bodyObserver: MutationObserver | null = null;
let restoreCandidates: Array<HTMLElement | null> = [];
const dialogRegistrations = new Map<HTMLElement, DialogRegistration>();

function isDialogRoot(element: Element): boolean {
  return element.hasAttribute(DIALOG_ROOT_ATTRIBUTE);
}

function isolateBodyElement(element: HTMLElement): void {
  if (isDialogRoot(element) || inertSnapshots.has(element)) return;
  inertSnapshots.set(element, {
    element,
    inertAttribute: element.getAttribute("inert"),
  });
  if (!element.hasAttribute("inert")) element.setAttribute("inert", "");
}

function acquireModalIsolation(): void {
  modalLockCount += 1;
  if (modalLockCount !== 1) return;

  bodyOverflow = document.body.style.overflow;
  documentOverflow = document.documentElement.style.overflow;
  restoreCandidates = [];
  document.body.style.overflow = "hidden";
  document.documentElement.style.overflow = "hidden";
  inertSnapshots = new Map();
  for (const child of document.body.children) {
    if (child instanceof HTMLElement) isolateBodyElement(child);
  }
  bodyObserver = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node instanceof HTMLElement && node.parentElement === document.body) {
          isolateBodyElement(node);
        }
      }
    }
  });
  bodyObserver.observe(document.body, { childList: true });
}

function releaseModalIsolation(): void {
  modalLockCount = Math.max(0, modalLockCount - 1);
  if (modalLockCount !== 0) return;

  bodyObserver?.disconnect();
  bodyObserver = null;
  for (const { element, inertAttribute } of inertSnapshots.values()) {
    if (inertAttribute === null) element.removeAttribute("inert");
    else element.setAttribute("inert", inertAttribute);
  }
  inertSnapshots.clear();
  document.body.style.overflow = bodyOverflow;
  document.documentElement.style.overflow = documentOverflow;
}

function orderedDialogRegistrations(): DialogRegistration[] {
  for (const [root] of dialogRegistrations) {
    if (!root.isConnected) dialogRegistrations.delete(root);
  }
  return [...dialogRegistrations.values()].sort((left, right) =>
    left.depth - right.depth || left.sequence - right.sequence);
}

function synchronizeDialogStack(): void {
  const ordered = orderedDialogRegistrations();
  ordered.forEach(({ root }, index) => {
    const topmost = index === ordered.length - 1;
    root.dataset.uiDialogLayer = String(900 + index);
    root.style.setProperty("--ui-dialog-layer", String(900 + index));
    const panel = root.querySelector<HTMLElement>("[role='dialog']");
    if (topmost) {
      root.removeAttribute("inert");
      root.removeAttribute("aria-hidden");
      panel?.setAttribute("aria-modal", "true");
    } else {
      root.setAttribute("inert", "");
      root.setAttribute("aria-hidden", "true");
      panel?.setAttribute("aria-modal", "false");
    }
  });
}

function topmostDialogRoot(): HTMLElement | null {
  const ordered = orderedDialogRegistrations();
  return ordered.at(-1)?.root ?? null;
}

function hasVisibleStyles(element: HTMLElement): boolean {
  for (let current: HTMLElement | null = element; current !== null; current = current.parentElement) {
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") {
      return false;
    }
  }
  return true;
}

function isAvailableFocusable(element: HTMLElement): boolean {
  return element.matches(FOCUSABLE)
    && element.tabIndex >= 0
    && element.getAttribute("aria-disabled") !== "true"
    && !(element instanceof HTMLInputElement && element.type === "hidden")
    && element.closest("[hidden], [inert], [aria-hidden='true']") === null
    && hasVisibleStyles(element);
}

function focusFirstAvailable(root: HTMLElement): void {
  const panel = root.querySelector<HTMLElement>("[role='dialog']");
  if (panel === null) return;
  const first = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].find(isAvailableFocusable);
  (first ?? panel).focus();
}

function restoreFocus(previous: HTMLElement | null): void {
  const remainingDialog = topmostDialogRoot();
  if (remainingDialog !== null) {
    if (previous?.isConnected && remainingDialog.contains(previous) && hasVisibleStyles(previous)) {
      previous.focus();
    } else {
      focusFirstAvailable(remainingDialog);
    }
    return;
  }
  if (modalLockCount !== 0) return;
  for (let index = restoreCandidates.length - 1; index >= 0; index -= 1) {
    const candidate = restoreCandidates[index];
    if (candidate?.isConnected
      && candidate.getAttribute("aria-disabled") !== "true"
      && !candidate.matches(":disabled")
      && candidate.closest("[hidden], [inert], [aria-hidden='true']") === null
      && hasVisibleStyles(candidate)) {
      candidate.focus();
      break;
    }
  }
  restoreCandidates = [];
}

/**
 * Modal dialog primitive: `role="dialog"`, `aria-modal`, labelled by its title,
 * described by an optional description, focus trapped inside, Escape closes,
 * and focus returns to the opener on close. It renders nothing while closed so
 * it can never reserve or shift layout, and the panel is a fixed viewport
 * overlay so opening it never reflows the surface beneath it.
 */
export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  tone = "neutral",
  closeLabel = "Close dialog",
  initialFocusRef,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  tone?: "neutral" | "danger";
  closeLabel?: string;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const depth = useContext(DialogDepthContext) + 1;
  const sequenceRef = useRef(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  // Latest handlers live in refs so re-renders while open (for example a
  // simulated transfer tick behind the dialog) never re-run focus management
  // and yank focus back to the initial control.
  const onCloseRef = useRef(onClose);
  const initialFocusRefRef = useRef(initialFocusRef);
  useEffect(() => {
    onCloseRef.current = onClose;
    initialFocusRefRef.current = initialFocusRef;
  });

  useLayoutEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement as HTMLElement | null;
    const root = rootRef.current;
    const panel = panelRef.current;
    if (root === null) return undefined;
    sequenceRef.current = ++nextDialogSequence;
    root.dataset.uiDialogSequence = String(sequenceRef.current);
    acquireModalIsolation();
    dialogRegistrations.set(root, {
      depth,
      root,
      sequence: sequenceRef.current,
    });
    synchronizeDialogStack();
    const requestedInitial = initialFocusRefRef.current?.current;
    const initial = requestedInitial !== undefined
      && requestedInitial !== null
      && panel?.contains(requestedInitial)
      && isAvailableFocusable(requestedInitial)
      ? requestedInitial
      : closeRef.current ?? panel;
    if (topmostDialogRoot() === root) initial?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (topmostDialogRoot() !== root) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || panel === null) return;
      const focusable = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)]
        .filter(isAvailableFocusable);
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const activeIndex = active instanceof HTMLElement ? focusable.indexOf(active) : -1;
      if (activeIndex === -1) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      dialogRegistrations.delete(root);
      synchronizeDialogStack();
      restoreCandidates.push(previous);
      releaseModalIsolation();
      restoreFocus(previous);
    };
  }, [depth, open]);

  if (!open || typeof document === "undefined") return null;
  return createPortal((
    <DialogDepthContext.Provider value={depth}>
      <div
        className="ui-dialog"
        data-tone={tone}
        data-ui-dialog-depth={depth}
        data-ui-dialog-root
        ref={rootRef}
      >
        <div aria-hidden="true" className="ui-dialog__scrim" onClick={onClose} />
        <div
          aria-describedby={description === undefined ? undefined : descriptionId}
          aria-labelledby={titleId}
          aria-modal="true"
          className="ui-dialog__panel"
          ref={panelRef}
          role="dialog"
          tabIndex={-1}
        >
          <header className="ui-dialog__header">
            <h2 id={titleId}>{title}</h2>
            <button
              aria-label={closeLabel}
              className="ui-dialog__close"
              onClick={onClose}
              ref={closeRef}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          {description !== undefined && (
            <p className="ui-dialog__description" id={descriptionId}>{description}</p>
          )}
          <div className="ui-dialog__body">{children}</div>
          {footer !== undefined && <footer className="ui-dialog__footer">{footer}</footer>}
        </div>
      </div>
    </DialogDepthContext.Provider>
  ), document.body);
}
