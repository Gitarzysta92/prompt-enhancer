import { providerLabel } from "../api/contracts";

/**
 * Names the provider a session or project came from. The label is a fixed
 * vocabulary keyed on the persisted provider code - never derived from session
 * content - and an unknown code renders as such instead of being hidden, so a
 * new provider is visible before this client learns its name.
 */
export function ProviderBadge({
  provider,
  compact = false,
}: {
  provider: unknown;
  compact?: boolean;
}) {
  const known = provider === "codex" || provider === "claude_code" || provider === "synthetic";
  const key = known ? (provider as string) : "unknown";
  return (
    <span
      aria-label={`Source: ${providerLabel(provider)}`}
      className={`provider-badge provider-badge--${key}${compact ? " provider-badge--compact" : ""}`}
      data-provider={key}
    >
      <span aria-hidden="true" className="provider-badge__dot" />
      {providerLabel(provider)}
    </span>
  );
}

/** Distinct providers among a set of rows, in stable display order. */
export function providersOf(rows: readonly { provider: unknown }[]): string[] {
  const order = ["codex", "claude_code", "synthetic"];
  const seen = new Set<string>();
  for (const row of rows) {
    seen.add(typeof row.provider === "string" ? row.provider : "unknown");
  }
  return [...seen].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia === -1 ? order.length : ia) - (ib === -1 ? order.length : ib) || a.localeCompare(b);
  });
}
