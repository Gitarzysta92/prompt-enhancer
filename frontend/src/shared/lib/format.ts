export function shortId(value: string): string {
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

export function titleFromKey(value: string): string {
  const parts = value.split(/[._]+/).filter(Boolean);
  const visibleParts = parts[0] === "task" ? parts.slice(1) : parts;
  return visibleParts
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function formatPercent(value: number): string {
  if (value > 0 && value < 0.0001) return "<0.01%";
  if (value < 1 && value > 0.9999) return ">99.99%";
  return new Intl.NumberFormat("en", {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
