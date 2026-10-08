import { useId, useRef, useState } from "react";
import type { Conversation, FileShareOffer, SocialSnapshot } from "../../shared/api/socialHub";
import { Dialog } from "../../shared/ui/Dialog";
import { EmptyState } from "../../shared/ui/EmptyState";
import { FactList } from "../../shared/ui/FactList";
import { Icon } from "../../shared/ui/Icon";
import { ProgressMeter, type ProgressMeterState } from "../../shared/ui/ProgressMeter";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";
import {
  DIRECT_PATH_LABELS,
  OFFER_DECLINED_BY_ALL_LABEL,
  OFFER_STATE_LABELS,
  PRESENCE_VALUE_LABELS,
  TERMINAL_OFFER_STATES,
  canPerform,
  directConversationHasLiveFriendship,
  offerBytesReceived,
  offerDeclinedByEveryRecipient,
  offerDirectPathBlocked,
  personById,
  personIsOnline,
  personPresence,
  type SocialHubAction,
} from "./socialHubModel";
import {
  CONSENT_LABELS,
  FILE_SHARING_BOUNDARY_COPY,
  INTEGRITY_LABELS,
  OFFLINE_OFFER_QUEUE_COPY,
  REVOKE_COPY,
  formatBytes,
  shortUtcTime,
} from "./socialHubCopy";
import {
  DirectTransferPrototypePanel,
  syntheticDirectTransferPrototypeIsAvailable,
} from "./directTransfer/DirectTransferPrototypePanel";

const OFFER_TONES: Readonly<Record<FileShareOffer["state"], PillTone>> = {
  awaiting_consent: "info",
  transferring: "positive",
  paused: "warning",
  verifying: "info",
  complete: "positive",
  integrity_mismatch: "danger",
  revoked: "danger",
  expired: "neutral",
  owner_offline: "warning",
  queued_on_sender: "warning",
  direct_path_unavailable: "warning",
};

function meterState(offer: FileShareOffer): ProgressMeterState {
  switch (offer.state) {
    case "transferring":
    case "verifying":
      return "active";
    case "paused":
    case "owner_offline":
    case "queued_on_sender":
    case "direct_path_unavailable":
      return "paused";
    case "complete":
      return "complete";
    case "revoked":
    case "expired":
    case "integrity_mismatch":
      return "stopped";
    default:
      return "idle";
  }
}

const EXPIRY_HOURS = 24;

function plusHours(iso: string, hours: number): string {
  const date = new Date(iso);
  date.setUTCHours(date.getUTCHours() + hours);
  return date.toISOString();
}

export function FileOfferCard({
  snapshot,
  offer,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  offer: FileShareOffer;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const [confirming, setConfirming] = useState<"consent" | "revoke" | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const owner = personById(snapshot, offer.owner_id);
  const mine = offer.owner_id === snapshot.me_person_id;
  const me = offer.recipients.find((recipient) => recipient.person_id === snapshot.me_person_id) ?? null;
  const ownerOnline = personIsOnline(owner);
  const pathBlocked = offerDirectPathBlocked(snapshot, offer);
  const resumable = ownerOnline && pathBlocked === null;
  const received = offerBytesReceived(offer);
  const expired = offer.state === "expired";
  const terminal = TERMINAL_OFFER_STATES.has(offer.state);
  // Every recipient declined: the wire state still reads "awaiting consent"
  // because the port has no declined state, but nobody is left who could
  // consent, so the card must not imply a transfer could still start.
  const declinedByAll = !terminal && offerDeclinedByEveryRecipient(offer);
  const titleId = `offer-${offer.id.slice(0, 8)}`;
  const detail = declinedByAll
    ? `Every recipient declined · no bytes were requested and none can move; the offer simply expires ${shortUtcTime(offer.expires_at)} and never waits on a server`
    : offer.state === "awaiting_consent"
    ? "No bytes move until a recipient consents"
    : offer.state === "owner_offline"
      ? "Owner offline · the offer waits on the owner's device; nothing is queued on a server"
      : offer.state === "queued_on_sender"
        ? `Queued on your device while you are not currently shared as online · expires ${shortUtcTime(offer.expires_at)} · never on a server`
        : offer.state === "direct_path_unavailable"
          ? `No direct path (${pathBlocked === "unavailable_cgnat" ? "CGNAT" : pathBlocked === "unavailable_symmetric_nat" ? "symmetric NAT" : "NAT"}) · no relay or TURN exists, so no bytes can move`
          : received === null
            ? "Amount transferred is unknown"
            : `${formatBytes(received)} of ${formatBytes(offer.file.size_bytes)} · ${OFFER_STATE_LABELS[offer.state].toLowerCase()}`;
  const ownerPresence = PRESENCE_VALUE_LABELS[personPresence(owner)].toLowerCase();
  return (
    <li
      className="social-offer"
      data-consent={declinedByAll ? "declined_by_every_recipient" : undefined}
      data-owner={mine ? "me" : "other"}
      data-state={offer.state}
    >
      <article aria-labelledby={titleId}>
        <header className="social-offer__header">
          <span aria-hidden="true" className="social-offer__glyph"><Icon name="file" /></span>
          <span className="social-offer__title">
            <strong id={titleId}>{offer.file.display_name}</strong>
            <small>{formatBytes(offer.file.size_bytes)} · {offer.file.media_type} · {mine ? "offered by you" : `offered by ${owner?.display_name ?? "unknown"}`}</small>
          </span>
          <StatusPill tone={declinedByAll ? "neutral" : OFFER_TONES[offer.state]}>
            {declinedByAll ? OFFER_DECLINED_BY_ALL_LABEL : OFFER_STATE_LABELS[offer.state]}
          </StatusPill>
        </header>
        <ProgressMeter
          compact
          detail={detail}
          label="Direct transfer"
          max={offer.file.size_bytes}
          state={declinedByAll ? "stopped" : meterState(offer)}
          value={offer.state === "awaiting_consent" || declinedByAll ? null : received}
        />
        <FactList
          compact
          label={`${offer.file.display_name} details`}
          facts={[
            { term: "Owner availability", detail: owner === null ? null : `${owner.display_name} · presence ${ownerPresence} (self-declared, opt-in) · owner must be online for a direct transfer` },
            { term: "Direct path", detail: `${owner === null ? "Owner path unknown" : `Owner: ${DIRECT_PATH_LABELS[owner.direct_path]}`}; ${offer.recipients.map((recipient) => {
              const person = personById(snapshot, recipient.person_id);
              return `${person?.display_name ?? "Unknown"}: ${person === null ? "not probed" : DIRECT_PATH_LABELS[person.direct_path]}`;
            }).join("; ")} · direct only, no relay, no TURN` },
            { term: "Recipients", detail: offer.recipients.map((recipient) => `${personById(snapshot, recipient.person_id)?.display_name ?? "Unknown"} · ${CONSENT_LABELS[recipient.consent]} · ${INTEGRITY_LABELS[recipient.integrity]}`).join("; ") },
            { term: "Expiry", detail: `${expired ? "Expired" : "Expires"} ${shortUtcTime(offer.expires_at)} · bounded; a sender-offline offer waits only on the sender's device` },
            { term: "Storage", detail: "Bytes go directly device-to-device; they never traverse or rest on the coordination plane, which sees only relationship, timing, availability, and size-class metadata" },
            { term: "Revoke", detail: REVOKE_COPY },
            { term: "Fixture digest", detail: `${offer.file.digest_hex.slice(0, 16)}… (fictional; not a hash of real bytes)` },
          ]}
        />
        <div className="social-offer__actions">
          {me !== null && me.consent === "pending" && !terminal && (
            <>
              <button className="button button--compact button--primary" onClick={() => setConfirming("consent")} type="button">
                Review and consent
              </button>
              <button className="button button--compact button--secondary" onClick={() => dispatch({ type: "decline_consent", offerId: offer.id })} type="button">
                Decline
              </button>
            </>
          )}
          {offer.state === "transferring" && (
            <button className="button button--compact button--secondary" onClick={() => dispatch({ type: "pause_transfer", offerId: offer.id })} type="button">
              <Icon name="pause" /> Pause
            </button>
          )}
          {(offer.state === "paused" || offer.state === "owner_offline" || offer.state === "direct_path_unavailable") && (
            <button
              className="button button--compact button--secondary"
              disabled={!resumable}
              onClick={() => dispatch({ type: "resume_transfer", offerId: offer.id, at: now() })}
              type="button"
            >
              <Icon name="play" /> {!ownerOnline ? "Resume (owner offline)" : pathBlocked !== null ? "Resume (no direct path)" : "Resume"}
            </button>
          )}
          {mine && !terminal && (
            <button className="button button--compact button--danger-ghost" onClick={() => setConfirming("revoke")} type="button">
              Revoke offer
            </button>
          )}
        </div>
      </article>
      <Dialog
        description="Consent is recorded on this device only. Granting it lets the simulated direct transfer begin while the owner is online; the coordination service never receives a copy."
        footer={(
          <>
            <button className="button button--secondary" onClick={() => setConfirming(null)} type="button">Cancel</button>
            <button
              className="button button--primary"
              onClick={() => { dispatch({ type: "grant_consent", offerId: offer.id, at: now() }); setConfirming(null); }}
              ref={confirmRef}
              type="button"
            >
              Grant consent
            </button>
          </>
        )}
        initialFocusRef={confirmRef}
        onClose={() => setConfirming(null)}
        open={confirming === "consent"}
        title={`Accept ${offer.file.display_name}?`}
      >
        <FactList
          facts={[
            { term: "From", detail: owner?.display_name ?? null },
            { term: "Size", detail: formatBytes(offer.file.size_bytes) },
            { term: "Media type", detail: offer.file.media_type },
            { term: "Expires", detail: shortUtcTime(offer.expires_at) },
            { term: "Integrity", detail: "Checked against the fixture digest after the simulated transfer completes" },
          ]}
        />
      </Dialog>
      <Dialog
        description={`Revoking stops any further simulated transfer and marks the offer revoked for recipients. ${REVOKE_COPY} Nothing was ever stored by the coordination service.`}
        footer={(
          <>
            <button className="button button--secondary" onClick={() => setConfirming(null)} type="button">Keep offer</button>
            <button
              className="button button--danger-ghost"
              onClick={() => { dispatch({ type: "revoke_offer", offerId: offer.id }); setConfirming(null); }}
              type="button"
            >
              Revoke
            </button>
          </>
        )}
        onClose={() => setConfirming(null)}
        open={confirming === "revoke"}
        title={`Revoke ${offer.file.display_name}?`}
        tone="danger"
      >
        <p>Recipients: {offer.recipients.map((recipient) => personById(snapshot, recipient.person_id)?.display_name ?? "Unknown").join(", ")}.</p>
      </Dialog>
    </li>
  );
}

function OfferForm({
  snapshot,
  conversation,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const nameId = useId();
  const sizeId = useId();
  const typeId = useId();
  const [displayName, setDisplayName] = useState("");
  const [sizeMb, setSizeMb] = useState("4");
  const [mediaType, setMediaType] = useState("application/pdf");
  const candidates = conversation.members.filter((member) => member.person_id !== snapshot.me_person_id);
  const [selected, setSelected] = useState<readonly string[]>(() => candidates.map((member) => member.person_id));
  const meOnline = personIsOnline(personById(snapshot, snapshot.me_person_id));
  const size = Number.parseFloat(sizeMb);
  const valid = displayName.trim() !== "" && Number.isFinite(size) && size > 0 && selected.length > 0;
  const validationHint = displayName.trim() === ""
    ? "Enter a display name to enable the metadata-only offer."
    : !Number.isFinite(size) || size <= 0
      ? "Enter a size greater than zero to enable the metadata-only offer."
      : selected.length === 0
        ? "Select at least one recipient to enable the metadata-only offer."
        : "Required metadata and recipient scope are ready.";
  const senderStateHint = meOnline
    ? "You are online, so a direct transfer could start once a recipient consents and a direct path exists."
    : "You are not currently shared as online: the metadata offer is queued on this device with a bounded expiry (never on a server), and bytes move only after you explicitly share an online state.";
  const submitHint = `${validationHint} ${senderStateHint}`;
  return (
    <form
      aria-describedby={`${nameId}-boundary`}
      aria-label="Offer a file (metadata only)"
      className="social-offer-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        const at = now();
        dispatch({
          type: "create_offer",
          conversationId: conversation.id,
          displayName,
          sizeBytes: Math.round(size * 1024 * 1024),
          mediaType,
          recipientIds: selected,
          at,
          expiresAt: plusHours(at, EXPIRY_HOURS),
        });
        setDisplayName("");
      }}
    >
      <p className="social-offer-form__boundary" id={`${nameId}-boundary`}>
        Describe a file by name, size, and type. No file picker, path, or bytes are involved; recipients must consent, and the offer expires after {EXPIRY_HOURS} hours. {OFFLINE_OFFER_QUEUE_COPY}
      </p>
      <div className="social-offer-form__grid">
        <label className="field">
          <span>Display name</span>
          <input id={nameId} maxLength={80} onChange={(event) => setDisplayName(event.target.value)} placeholder="synthetic-notes.pdf" type="text" value={displayName} />
        </label>
        <label className="field">
          <span>Size (MB)</span>
          <input id={sizeId} inputMode="decimal" min="0.1" onChange={(event) => setSizeMb(event.target.value)} step="0.1" type="number" value={sizeMb} />
        </label>
        <label className="field">
          <span>Media type</span>
          <input id={typeId} maxLength={60} onChange={(event) => setMediaType(event.target.value)} type="text" value={mediaType} />
        </label>
      </div>
      <fieldset className="social-offer-form__recipients">
        <legend>Recipient scope</legend>
        {candidates.map((member) => {
          const person = personById(snapshot, member.person_id);
          const checked = selected.includes(member.person_id);
          return (
            <label key={member.person_id}>
              <input
                checked={checked}
                onChange={() => setSelected(checked ? selected.filter((id) => id !== member.person_id) : [...selected, member.person_id])}
                type="checkbox"
              />
              <span>
                {person?.display_name ?? "Unknown"} · {PRESENCE_VALUE_LABELS[personPresence(person)].toLowerCase()}
                {person === null ? "" : ` · ${DIRECT_PATH_LABELS[person.direct_path].toLowerCase()}`}
              </span>
            </label>
          );
        })}
      </fieldset>
      <div className="social-offer-form__submit">
        <button
          aria-describedby={`${nameId}-boundary ${nameId}-submit-hint`}
          className="button button--primary"
          disabled={!valid}
          type="submit"
        >
          <Icon name="file" /> {meOnline ? "Offer to" : "Queue offer for"} {selected.length} {selected.length === 1 ? "recipient" : "recipients"}
        </button>
        <span data-sender-online={meOnline ? "true" : "false"} id={`${nameId}-submit-hint`}>
          {submitHint}
        </span>
      </div>
    </form>
  );
}

/** File sharing for one conversation: offers, transfer controls, and the metadata-only offer form. */
export function FileSharePanel({
  snapshot,
  conversation,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const offers = snapshot.file_offers
    .filter((offer) => offer.conversation_id === conversation.id)
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
  const canShare = canPerform(snapshot, conversation, "share_files");
  const friendshipActive = directConversationHasLiveFriendship(snapshot, conversation);
  const prototypeAvailable = syntheticDirectTransferPrototypeIsAvailable({ snapshot });
  return (
    <section aria-label="Direct file sharing" className="social-files">
      <header className="social-files__header">
        <h3>Direct file sharing</h3>
        <p role="note">
          {prototypeAvailable
            ? "The offer cards remain a metadata-only UI simulation. The separately labelled opt-in lab below can move generated fixture bytes between two in-page peers; it never reads a real file and is unavailable in local-real mode."
            : FILE_SHARING_BOUNDARY_COPY}
        </p>
      </header>
      {prototypeAvailable ? <DirectTransferPrototypePanel snapshot={snapshot} /> : null}
      {offers.length === 0 ? (
        <EmptyState compact icon="file" title="No file offers" description="Zero offers exist in this conversation's local state." />
      ) : (
        <ul aria-label="File offers" className="social-offer-list">
          {offers.map((offer) => (
            <FileOfferCard dispatch={dispatch} key={offer.id} now={now} offer={offer} snapshot={snapshot} />
          ))}
        </ul>
      )}
      {canShare ? (
        <OfferForm conversation={conversation} dispatch={dispatch} now={now} snapshot={snapshot} />
      ) : (
        <p className="social-files__blocked" role="note">
          {friendshipActive
            ? "Your role in this conversation cannot offer files."
            : "Direct file offers require a current friendship; this conversation is read-only."}
        </p>
      )}
    </section>
  );
}
