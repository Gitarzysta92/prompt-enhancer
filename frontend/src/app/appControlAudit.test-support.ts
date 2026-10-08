function referencedText(element: Element, attribute: "aria-describedby" | "aria-labelledby"): string {
  return (element.getAttribute(attribute) ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
    .filter(Boolean)
    .join(" ");
}

function controlName(element: Element): string {
  return (
    element.getAttribute("aria-label")
    || referencedText(element, "aria-labelledby")
    || element.textContent?.trim()
    || element.getAttribute("name")
    || element.tagName.toLowerCase()
  ).replace(/\s+/g, " ");
}

function hasDisabledReason(element: HTMLElement): boolean {
  if ((element.getAttribute("title") ?? "").trim() !== "") return true;
  if (referencedText(element, "aria-describedby") !== "") return true;
  if (element.getAttribute("aria-busy") === "true") return true;
  if (/loading|saving|opening|starting|stopping|checking|refreshing|working/i.test(controlName(element))) {
    return true;
  }

  const fieldset = element.closest("fieldset[disabled]");
  return fieldset instanceof HTMLElement && (
    referencedText(fieldset, "aria-describedby") !== ""
    || (fieldset.getAttribute("title") ?? "").trim() !== ""
  );
}

export function auditControlSurface(root: HTMLElement): string[] {
  const disabledWithoutReason = Array.from(
    root.querySelectorAll<HTMLElement>("button:disabled, input:disabled, select:disabled, textarea:disabled"),
  )
    .filter((element) => !element.closest("[hidden], [aria-hidden='true']"))
    .filter((element) => !hasDisabledReason(element))
    .map((element) => `disabled ${element.tagName.toLowerCase()}: ${controlName(element)}`);

  const ambiguousNames = Array.from(root.querySelectorAll<HTMLElement>("button, a[href]"))
    .filter((element) => !element.closest("[hidden], [aria-hidden='true']"))
    .map((element) => ({ element, name: controlName(element) }))
    .filter(({ element, name }) => (
      name === element.tagName.toLowerCase()
      || /^[+×…•<>‹›\-]+$/.test(name)
    ))
    .map(({ element, name }) => `ambiguous ${element.tagName.toLowerCase()}: ${name}`);

  return [...disabledWithoutReason, ...ambiguousNames];
}
