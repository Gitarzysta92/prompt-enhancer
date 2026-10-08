/**
 * Screen-reader announcement region. It is always mounted (so assistive
 * technology registers it before the first message) and visually hidden, so it
 * never reserves or shifts layout. Pass a new `message` to announce; an empty
 * string clears it. `assertive` is reserved for failures that block the task.
 */
export function LiveRegion({
  message,
  assertive = false,
}: {
  message: string;
  assertive?: boolean;
}) {
  return (
    <div
      aria-atomic="true"
      aria-live={assertive ? "assertive" : "polite"}
      className="sr-only"
      role={assertive ? "alert" : "status"}
    >
      {message}
    </div>
  );
}
