import { useEffect, useRef, useState } from "react";

import "./AgentCopyButton.css";

type CopyState = "idle" | "copied" | "failed" | "unavailable";

export function AgentCopyButton({
  className = "",
  label,
  value,
}: {
  className?: string;
  label: string;
  value: string;
}) {
  const [state, setState] = useState<CopyState>("idle");
  const resetTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
  }, []);

  function showState(next: Exclude<CopyState, "idle">): void {
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
    setState(next);
    resetTimer.current = window.setTimeout(() => {
      setState("idle");
      resetTimer.current = null;
    }, 2_000);
  }

  async function copy(): Promise<void> {
    const writeText = typeof navigator === "undefined" ? undefined : navigator.clipboard?.writeText;
    if (writeText === undefined) {
      showState("unavailable");
      return;
    }
    try {
      await writeText.call(navigator.clipboard, value);
      showState("copied");
    } catch {
      showState("failed");
    }
  }

  const visibleLabel = state === "copied"
    ? "Copied"
    : state === "failed"
      ? "Copy failed"
      : state === "unavailable"
        ? "Copy unavailable"
        : "Copy";

  return (
    <button
      aria-label={state === "idle" ? label : `${label}: ${visibleLabel.toLowerCase()}`}
      className={`agent-copy-button ${className}`.trim()}
      data-copy-state={state}
      onClick={() => void copy()}
      type="button"
    >
      {visibleLabel}
    </button>
  );
}
