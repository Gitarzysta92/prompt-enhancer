import { useEffect, useId, useMemo, useReducer, useState } from "react";
import {
  isSocialHubError,
  socialCapabilityReportIsValid,
  socialSnapshotIsValid,
  type SocialCapabilityReport,
  type SocialHubPort,
  type SocialPresenceLevel,
  type SocialSnapshot,
} from "../../shared/api/socialHub";
import type { RuntimeDataMode } from "../../shared/platform/runtimeMode";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { Disclosure } from "../../shared/ui/Disclosure";
import { EmptyState } from "../../shared/ui/EmptyState";
import { FactList } from "../../shared/ui/FactList";
import { FictionalNotice } from "../../shared/ui/FictionalNotice";
import { Icon } from "../../shared/ui/Icon";
import { LiveRegion } from "../../shared/ui/LiveRegion";
import { StatusPill } from "../../shared/ui/StatusPill";
import { ConversationDetails } from "./ConversationDetails";
import { ConversationPane, ThreadPane } from "./ConversationPane";
import { FileSharePanel } from "./FileSharePanel";
import { SocialRail } from "./SocialRail";
import {
  DATA_CONTROLS_COPY,
  ENCRYPTION_COPY,
  GROUP_ACCESS_COPY,
  OFFLINE_OFFER_QUEUE_COPY,
  PAYLOAD_POLICY_COPY,
  PRESENCE_POLICY_COPY,
  REVOKE_COPY,
  SOCIAL_BOUNDARY_COPY,
  SOCIAL_ORIGIN_LABELS,
  SOCIAL_REASON_COPY,
} from "./socialHubCopy";
import {
  PRESENCE_VALUE_LABELS,
  TERMINAL_OFFER_STATES,
  conversationById,
  createSocialHubState,
  friends,
  personById,
  personPresence,
  socialHubReducer,
  totalUnread,
  type SocialHubAction,
} from "./socialHubModel";
import "./SocialHub.css";

const PRESENCE_LEVELS: readonly SocialPresenceLevel[] = ["online", "away", "do_not_disturb", "offline"];

/**
 * Explicit opt-in presence for the local principal. Its initial state comes
 * from explicit fixture/service consent; every change is a user action. The
 * level is coarse and self-declared, never inferred from analyzer activity.
 */
function PresenceControl({ snapshot, dispatch, now }: {
  snapshot: SocialSnapshot;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const checkboxId = useId();
  const selectId = useId();
  const me = personById(snapshot, snapshot.me_person_id);
  const sharing = me?.presence.sharing === "shared";
  const [lastExplicitLevel, setLastExplicitLevel] = useState<SocialPresenceLevel>(() => (
    me?.presence.sharing === "shared" && me.presence.level !== null ? me.presence.level : "offline"
  ));
  useEffect(() => {
    if (me?.presence.sharing === "shared" && me.presence.level !== null) {
      setLastExplicitLevel(me.presence.level);
    }
  }, [me?.presence.level, me?.presence.sharing]);
  const level = sharing && me?.presence.level !== null && me?.presence.level !== undefined
    ? me.presence.level
    : lastExplicitLevel;
  return (
    <fieldset className="social-presence" data-presence-source="self_declared_opt_in" data-sharing={sharing ? "shared" : "not_shared"}>
      <legend>Your presence · opt-in, coarse, self-declared</legend>
      <label className="social-presence__toggle" htmlFor={checkboxId}>
        <input
          checked={sharing}
          id={checkboxId}
          onChange={(event) => dispatch({ type: "set_presence", sharing: event.target.checked ? "shared" : "not_shared", level: event.target.checked ? level : null, at: now() })}
          type="checkbox"
        />
        <span>Share a coarse presence level with people in your conversations</span>
      </label>
      <label className="social-presence__level" htmlFor={selectId}>
        <span>Level</span>
        <select
          disabled={!sharing}
          id={selectId}
          onChange={(event) => {
            const next = event.target.value as SocialPresenceLevel;
            setLastExplicitLevel(next);
            dispatch({ type: "set_presence", sharing: "shared", level: next, at: now() });
          }}
          value={level}
        >
          {PRESENCE_LEVELS.map((candidate) => (
            <option key={candidate} value={candidate}>{PRESENCE_VALUE_LABELS[candidate]}</option>
          ))}
        </select>
      </label>
      <p className="social-presence__hint">
        Others currently see: <strong>{PRESENCE_VALUE_LABELS[personPresence(me)]}</strong>. {PRESENCE_POLICY_COPY}
      </p>
    </fieldset>
  );
}

/** What this demo — and a future service — can and cannot promise; stated as facts, never as controls. */
function TruthBoundary() {
  return (
    <Disclosure compact summary="What this demo can and cannot promise" detail="encryption · metadata · access · payloads">
      <FactList
        compact
        label="Social boundary facts"
        facts={[
          { term: "Encryption", detail: ENCRYPTION_COPY },
          { term: "Coordination plane sees", detail: "Relationship (who talks to whom), timing, availability, and size class — even in a future encrypted service. File bytes never traverse or rest on it." },
          { term: "Group access", detail: GROUP_ACCESS_COPY },
          { term: "Presence", detail: PRESENCE_POLICY_COPY },
          { term: "Analyzer content", detail: PAYLOAD_POLICY_COPY },
          { term: "File transport", detail: `Direct device-to-device only; no relay and no TURN. A symmetric NAT or CGNAT on either side is shown as “no direct path”. Owner must be online to transfer. ${OFFLINE_OFFER_QUEUE_COPY}` },
          { term: "Revoke", detail: REVOKE_COPY },
          { term: "Export / delete", detail: DATA_CONTROLS_COPY },
        ]}
      />
    </Disclosure>
  );
}

type LoadState =
  | { kind: "loading"; port: SocialHubPort }
  | { kind: "closed"; port: SocialHubPort; report: SocialCapabilityReport }
  | { kind: "failed"; port: SocialHubPort }
  | { kind: "ready"; port: SocialHubPort; report: SocialCapabilityReport; snapshot: SocialSnapshot };

export const SOCIAL_SIMULATION_INTERVAL_MS = 600;
const systemUtcNow = () => new Date().toISOString();

function SocialWorkspace({
  snapshot,
  now,
  simulationIntervalMs,
}: {
  snapshot: SocialSnapshot;
  now: () => string;
  simulationIntervalMs: number;
}) {
  const [state, dispatch] = useReducer(socialHubReducer, snapshot, createSocialHubState);
  const active = state.activeConversationId === null ? null : conversationById(state.snapshot, state.activeConversationId);
  const transferActive = state.snapshot.file_offers.some((offer) => offer.state === "transferring" || offer.state === "verifying");
  const clockedOffers = useMemo(
    () => state.snapshot.file_offers.filter((offer) => !TERMINAL_OFFER_STATES.has(offer.state)),
    [state.snapshot.file_offers],
  );

  useEffect(() => {
    if (clockedOffers.length === 0) return undefined;
    const at = now();
    const nowMs = Date.parse(at);
    const expiryDelay = Math.min(...clockedOffers
      .map((offer) => Date.parse(offer.expires_at) - nowMs)
      .filter(Number.isFinite));
    const requestedDelay = transferActive ? simulationIntervalMs : expiryDelay;
    if (!Number.isFinite(requestedDelay)) return undefined;
    // One controller clock advances transfers frequently and otherwise wakes
    // only at the nearest expiry; no per-offer polling loops are created.
    const delay = Math.max(0, Math.min(requestedDelay, 2_147_000_000));
    const timer = window.setTimeout(() => dispatch({ type: "tick_transfers", at: now() }), delay);
    return () => window.clearTimeout(timer);
  }, [clockedOffers, now, simulationIntervalMs, transferActive]);

  return (
    <>
      <LiveRegion message={state.notice} />
      <div className="social-hub__summary" role="group" aria-label="Local social state summary">
        <StatusPill tone="info">{friends(state.snapshot).length} friends</StatusPill>
        <StatusPill tone="info">{state.snapshot.conversations.length} conversations</StatusPill>
        <StatusPill tone={totalUnread(state.snapshot) > 0 ? "warning" : "neutral"}>{totalUnread(state.snapshot)} unread</StatusPill>
        <StatusPill tone="info">{state.snapshot.file_offers.length} file offers</StatusPill>
        <StatusPill tone="neutral">Local state only · not delivered</StatusPill>
        <StatusPill tone="neutral">Not end-to-end encrypted</StatusPill>
        <StatusPill tone="neutral">Invite-only groups · nothing discoverable</StatusPill>
      </div>
      <div className="social-hub__policies">
        <PresenceControl dispatch={dispatch} now={now} snapshot={state.snapshot} />
        <TruthBoundary />
      </div>
      <div className="social-hub__layout" data-thread={state.activeThreadRootId === null ? "closed" : "open"}>
        <SocialRail
          activeConversationId={state.activeConversationId}
          dispatch={dispatch}
          now={now}
          query={state.query}
          snapshot={state.snapshot}
        />
        <ConversationPane conversation={active} dispatch={dispatch} now={now} snapshot={state.snapshot} />
        <aside aria-label="Conversation details" className="social-hub__details">
          {active === null ? (
            <EmptyState compact title="No details" description="Select a conversation to see members, permissions, threads, and file offers." />
          ) : state.activeThreadRootId !== null ? (
            <ThreadPane conversation={active} dispatch={dispatch} now={now} rootId={state.activeThreadRootId} snapshot={state.snapshot} />
          ) : (
            <>
              <ConversationDetails conversation={active} key={`details-${active.id}`} snapshot={state.snapshot} />
              <FileSharePanel conversation={active} dispatch={dispatch} key={`files-${active.id}`} now={now} snapshot={state.snapshot} />
            </>
          )}
        </aside>
      </div>
    </>
  );
}

/**
 * Social hub route. Everything on this page comes through the typed social
 * port: the shell never guesses that friends, presence, delivery, storage, or
 * encryption exist. The local loopback runtime fails closed with zero people,
 * messages, and offers; the synthetic preview is labelled fictional above the
 * fold and every action mutates only local React state.
 */
export function SocialHubPage({
  port,
  runtimeMode,
  now = systemUtcNow,
  simulationIntervalMs = SOCIAL_SIMULATION_INTERVAL_MS,
}: {
  port: SocialHubPort;
  runtimeMode: RuntimeDataMode;
  /** Injected clock for deterministic tests. */
  now?: () => string;
  simulationIntervalMs?: number;
}) {
  const [load, setLoad] = useState<LoadState>({ kind: "loading", port });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoad({ kind: "loading", port });
    void (async () => {
      try {
        const report = await port.getCapabilities(controller.signal);
        if (controller.signal.aborted) return;
        if (!socialCapabilityReportIsValid(report, port)) {
          setLoad({ kind: "failed", port });
          return;
        }
        if (report.state !== "available" || report.origin !== port.origin) {
          setLoad({ kind: "closed", port, report });
          return;
        }
        const snapshot = await port.getSnapshot(controller.signal);
        if (controller.signal.aborted) return;
        if (!socialSnapshotIsValid(snapshot, port)) {
          setLoad({ kind: "failed", port });
          return;
        }
        setLoad({ kind: "ready", port, report, snapshot });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (isSocialHubError(error) && error.code === "social_not_served_by_this_runtime") {
          const report = await port.getCapabilities().catch(() => null);
          if (controller.signal.aborted) return;
          setLoad(report === null ? { kind: "failed", port } : { kind: "closed", port, report });
          return;
        }
        setLoad({ kind: "failed", port });
      }
    })();
    return () => controller.abort();
  }, [port, reloadToken]);

  const current: LoadState = load.port === port ? load : { kind: "loading", port };
  const originLabel = current.kind === "closed" || current.kind === "ready"
    ? SOCIAL_ORIGIN_LABELS[current.report.origin]
    : "Origin not reported yet";

  return (
    <section aria-labelledby="social-hub-title" className="social-hub" data-runtime={runtimeMode} data-load={current.kind}>
      <header className="page-header route-header social-hub__header">
        <div>
          <p className="eyebrow">Social</p>
          <h1 id="social-hub-title">Social hub</h1>
          <p>Friends, requests, direct messages, invite-only groups, opt-in presence, threads, reactions, and direct-only file sharing — all through one typed port that fails closed when no service exists. Not end-to-end encrypted; no public discovery; the analyzer never inserts analyzer content into a payload.</p>
        </div>
        <div className="page-header__meta">
          <span className="privacy-chip"><Icon name="lock" /> {originLabel}</span>
        </div>
      </header>

      {current.kind === "ready" && current.report.fictional && (
        <FictionalNotice>
          {SOCIAL_REASON_COPY[current.report.reason]} {SOCIAL_BOUNDARY_COPY}
        </FictionalNotice>
      )}

      {current.kind === "loading" && <LoadingState label="Checking the social port" />}
      {current.kind === "failed" && (
        <ErrorState
          message="The social port did not answer with a valid capability report or snapshot. Nothing is assumed: zero people, messages, and file offers are shown."
          onRetry={() => setReloadToken((value) => value + 1)}
        />
      )}
      {current.kind === "closed" && (
        <EmptyState
          description={(
            <>
              {SOCIAL_REASON_COPY[current.report.reason]}{" "}
              Exposed here: 0 friends · 0 relationships · 0 requests · 0 conversations · 0 messages · 0 file offers · presence not shared.
            </>
          )}
          role="status"
          title="Social features are not served in this runtime"
          tone="closed"
        />
      )}
      {current.kind === "ready" && (
        <SocialWorkspace
          key={current.snapshot.generated_at}
          now={now}
          simulationIntervalMs={simulationIntervalMs}
          snapshot={current.snapshot}
        />
      )}
    </section>
  );
}
