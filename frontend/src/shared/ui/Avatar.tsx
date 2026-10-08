/**
 * Initials avatar with an optional presence indicator. Presence is conveyed by
 * text (`presenceLabel`) for assistive technology and, when `showPresenceText`
 * is set, visibly next to the glyph, so it is never colour-only. `not_shared`
 * is a person who has not opted in to presence: it is neither online nor
 * offline and is rendered as its own state.
 */
export type PresenceState = "online" | "away" | "do_not_disturb" | "offline" | "not_shared";

export const PRESENCE_LABELS: Readonly<Record<PresenceState, string>> = {
  online: "Online",
  away: "Away",
  do_not_disturb: "Do not disturb",
  offline: "Offline",
  not_shared: "Presence not shared",
};

export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] ?? "" : "";
  return `${first}${last}`.toUpperCase();
}

export function Avatar({
  name,
  presence,
  size = "regular",
  showPresenceText = false,
}: {
  name: string;
  presence?: PresenceState;
  size?: "small" | "regular" | "large";
  showPresenceText?: boolean;
}) {
  return (
    <span className={`ui-avatar ui-avatar--${size}`} data-presence={presence}>
      <span aria-hidden="true" className="ui-avatar__glyph">{initialsFor(name)}</span>
      {presence !== undefined && (
        <>
          <span aria-hidden="true" className="ui-avatar__presence" />
          <span className={showPresenceText ? "ui-avatar__presence-text" : "sr-only"}>
            {PRESENCE_LABELS[presence]}
          </span>
        </>
      )}
    </span>
  );
}
