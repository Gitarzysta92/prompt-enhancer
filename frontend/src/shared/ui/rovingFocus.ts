/**
 * Arrow-key navigation for a row of aria-pressed buttons. Tab remains usable;
 * arrows, Home, and End provide the expected compact-widget interaction.
 *
 * Framework-free: it only needs the keydown event's `currentTarget` container,
 * so any feature (radar strips, exact-value boards, stage constellations, or a
 * future team view) can reuse the same keyboard contract.
 */
export function moveRovingFocus(
  event: { key: string; currentTarget: HTMLElement; preventDefault(): void },
  select?: (index: number) => void,
): void {
  const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
  if (buttons.length === 0) return;
  const current = buttons.findIndex((button) => button === event.currentTarget.ownerDocument.activeElement);
  let next: number;
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
      next = current < 0 ? 0 : (current + 1) % buttons.length;
      break;
    case "ArrowLeft":
    case "ArrowUp":
      next = current < 0 ? buttons.length - 1 : (current - 1 + buttons.length) % buttons.length;
      break;
    case "Home":
      next = 0;
      break;
    case "End":
      next = buttons.length - 1;
      break;
    default:
      return;
  }
  event.preventDefault();
  buttons[next].focus();
  select?.(next);
}
