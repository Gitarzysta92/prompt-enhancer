import { useCallback, useEffect, useRef, useState } from "react";
import type { PeerLink, PromptEnhancerTransport, SharedFolder } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import "./TeamFoldersPanel.css";

type TransportSlice = Partial<
  Pick<
    PromptEnhancerTransport,
    "shareFolder" | "listSharedFolders" | "revokeSharedFolder" | "joinSharedFolder" | "listPeerLinks" | "leavePeerLink" | "pullPeerLink" | "pushPeerLink"
  >
>;

type ListStatus = "loading" | "ready" | "error";

/** Placeholders stay on loopback / reserved example paths - never a real host or folder. */
const PEER_URL_PLACEHOLDER = "http://127.0.0.1:8765";
const SHARE_PATH_PLACEHOLDER = "D:/example/team/docs";
const TARGET_PATH_PLACEHOLDER = "D:/example/team/docs-copy";
const PUSH_PEER_NAME = "this-machine";

const unavailable = (action: string) =>
  `${action} is unavailable in this session: the connected backend does not offer this operation.`;

const fileCount = (count: number) => `${count} file${count === 1 ? "" : "s"}`;

/** Never surface raw exception text - map to a small set of safe explanations. */
function safeMessage(caught: unknown, fallback: string): string {
  const status = caught instanceof TransportError ? caught.status : null;
  if (status === 401) return "The share token was not accepted (revoked or mistyped).";
  if (status === 403) return "That folder cannot be shared.";
  if (status === 404) return "That share is no longer available on the other side.";
  if (status === 422) return "Check the folder path and URL - something in the form is not valid.";
  if (status === 502) return "The peer could not be reached.";
  return fallback;
}

/** A token is shown once at creation time and is never kept in list state. */
const withoutToken = (entry: SharedFolder): SharedFolder => ({ ...entry, share_token: null });

/**
 * Team folders (ADR 0018): share one folder with a token, or join a teammate's
 * folder and work in your local copy - a live-folder collaboration mode beside
 * git. The joined copy is an ordinary agent workspace.
 *
 * Every exchange is explicit (Share / Join / Pull / Push), each action is
 * disabled unless the transport really offers it, mutations are serialized, and
 * a failed refresh keeps the last known list instead of showing a blank panel.
 */
export function TeamFoldersPanel({ transport, onUseAsWorkspace }: { transport: TransportSlice; onUseAsWorkspace?: (path: string) => void }) {
  const [shares, setShares] = useState<SharedFolder[] | null>(null);
  const [links, setLinks] = useState<PeerLink[] | null>(null);
  const [listStatus, setListStatus] = useState<ListStatus>("loading");
  const [listError, setListError] = useState("");
  const [stale, setStale] = useState(false);
  const [freshToken, setFreshToken] = useState<{ shareId: string; token: string } | null>(null);
  const [sharePath, setSharePath] = useState("");
  const [shareName, setShareName] = useState("");
  const [joinUrl, setJoinUrl] = useState("");
  const [joinShareId, setJoinShareId] = useState("");
  const [joinToken, setJoinToken] = useState("");
  const [joinTarget, setJoinTarget] = useState("");
  const [status, setStatus] = useState("");
  const [actionError, setActionError] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const refreshSeq = useRef(0);
  const mutationSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const mutationAbortRef = useRef<AbortController | null>(null);

  const listShares = transport.listSharedFolders;
  const listLinks = transport.listPeerLinks;
  const canList = Boolean(listShares && listLinks);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!listShares || !listLinks) return;
    const seq = refreshSeq.current + 1;
    refreshSeq.current = seq;
    const mutations = mutationSeq.current;
    // A refresh is discarded when it was superseded, aborted, unmounted, or when
    // a mutation changed the local state after this request left.
    const outdated = () =>
      !mountedRef.current || Boolean(signal?.aborted) || seq !== refreshSeq.current || mutations !== mutationSeq.current;
    setListStatus("loading");
    try {
      const [shareList, linkList] = await Promise.all([listShares(signal), listLinks(signal)]);
      if (outdated()) return;
      setShares(shareList.shares.filter((entry) => !entry.revoked_at).map(withoutToken));
      setLinks([...linkList.links]);
      setListError("");
      setStale(false);
      setListStatus("ready");
    } catch (caught) {
      if (outdated()) return;
      setListError(safeMessage(caught, "The team folder list could not be loaded."));
      setStale(true);
      setListStatus("error");
    }
  }, [listLinks, listShares]);

  const startRefresh = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    await refresh(controller.signal);
  }, [refresh]);

  const runMutation = useCallback(async (options: { fallback: string; label: string; run: (owns: () => boolean, signal: AbortSignal) => Promise<string | null> }) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const sequence = ++mutationSeq.current;
    const controller = new AbortController();
    mutationAbortRef.current = controller;
    const owns = () => mountedRef.current && mutationSeq.current === sequence && !controller.signal.aborted;
    abortRef.current?.abort();
    setPending(options.label);
    setStatus("");
    setActionError("");
    try {
      const message = await options.run(owns, controller.signal);
      if (!owns()) return;
      if (message) setStatus(message);
    } catch (caught) {
      if (owns()) setActionError(safeMessage(caught, options.fallback));
    } finally {
      // Every action invalidates an in-flight list read. Replace that read even
      // after a failed action or a transfer, otherwise loading can stay stuck.
      // This only reloads metadata; it never repeats Share, Join, Pull or Push.
      if (owns()) await startRefresh();
      if (owns()) {
        busyRef.current = false;
        mutationAbortRef.current = null;
        setPending(null);
      }
    }
  }, [startRefresh]);

  useEffect(() => {
    mountedRef.current = true;
    busyRef.current = false;
    setPending(null);
    setShares(null);
    setLinks(null);
    setFreshToken(null);
    setJoinToken("");
    setListError("");
    setStale(false);
    setListStatus("loading");
    setStatus("");
    setActionError("");
    return () => {
      mountedRef.current = false;
      refreshSeq.current += 1;
      mutationSeq.current += 1;
      abortRef.current?.abort();
      mutationAbortRef.current?.abort();
    };
  }, [transport]);

  useEffect(() => {
    if (!canList) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [canList, refresh, transport]);

  if (!canList) {
    return (
      <section aria-labelledby="team-folders-title" className="team-folders">
        <h2 id="team-folders-title">Team folders</h2>
        <p className="team-folders__boundary" role="status">
          Team folders are unavailable in this session: the connected backend does not offer the shared-folder listing, so
          existing shares and joined folders cannot be shown. Nothing was shared, joined or synced.
        </p>
      </section>
    );
  }

  const busy = pending !== null;
  const canShare = Boolean(transport.shareFolder);
  const canRevoke = Boolean(transport.revokeSharedFolder);
  const canJoin = Boolean(transport.joinSharedFolder);
  const canPull = Boolean(transport.pullPeerLink);
  const canPush = Boolean(transport.pushPeerLink);
  const canLeave = Boolean(transport.leavePeerLink);
  const shareReady = sharePath.trim().length > 0 && shareName.trim().length > 0;
  const joinReady = [joinUrl, joinShareId, joinToken, joinTarget].every((value) => value.trim().length > 0);

  const doShare = () => {
    const shareFolder = transport.shareFolder;
    const path = sharePath.trim();
    const name = shareName.trim();
    if (!shareFolder || !path || !name) return;
    void runMutation({
      fallback: "The folder could not be shared.",
      label: "Sharing the folder...",
      run: async (owns, signal) => {
        const created = await shareFolder(path, name, signal);
        if (!owns()) return null;
        // Kept locally so the new share survives a failing refresh; the token is
        // stripped here and only lives in the one-time banner below.
        setShares((previous) => [...(previous ?? []).filter((entry) => entry.share_id !== created.share_id), withoutToken(created)]);
        setFreshToken(created.share_token ? { shareId: created.share_id, token: created.share_token } : null);
        setSharePath("");
        setShareName("");
        return created.share_token
          ? `"${created.name}" is shared. The token is shown once, below.`
          : `"${created.name}" is shared, but no join token was returned. New peers cannot join without a token; no token can be displayed or copied here.`;
      },
    });
  };

  const doRevoke = (shareId: string) => {
    const revokeSharedFolder = transport.revokeSharedFolder;
    if (!revokeSharedFolder) return;
    void runMutation({
      fallback: "The share could not be revoked.",
      label: "Stopping the share...",
      run: async (owns, signal) => {
        await revokeSharedFolder(shareId, signal);
        if (!owns()) return null;
        setShares((previous) => (previous ?? []).filter((entry) => entry.share_id !== shareId));
        setFreshToken((previous) => (previous?.shareId === shareId ? null : previous));
        return "Sharing stopped. The old token no longer works.";
      },
    });
  };

  const doJoin = () => {
    const joinSharedFolder = transport.joinSharedFolder;
    const url = joinUrl.trim();
    const shareId = joinShareId.trim();
    const token = joinToken.trim();
    const target = joinTarget.trim();
    if (!joinSharedFolder || !url || !shareId || !token || !target) return;
    void runMutation({
      fallback: "The folder could not be joined.",
      label: "Joining the folder...",
      run: async (owns, signal) => {
        const created = await joinSharedFolder(url, shareId, token, target, signal);
        if (!owns()) return null;
        setLinks((previous) => [...(previous ?? []).filter((entry) => entry.link_id !== created.link_id), created]);
        setJoinUrl("");
        setJoinShareId("");
        setJoinToken("");
        setJoinTarget("");
        return "Joined. Press Pull to mirror the folder into your copy - nothing syncs on its own.";
      },
    });
  };

  const doPull = (linkId: string) => {
    const pullPeerLink = transport.pullPeerLink;
    if (!pullPeerLink) return;
    void runMutation({
      fallback: "The sync did not complete.",
      label: "Pulling changes...",
      run: async (_owns, signal) => {
        const report = await pullPeerLink(linkId, signal);
        return `Pulled ${fileCount(report.pulled)} (${report.skipped} unchanged).`;
      },
    });
  };

  const doPush = (linkId: string) => {
    const pushPeerLink = transport.pushPeerLink;
    if (!pushPeerLink) return;
    void runMutation({
      fallback: "The sync did not complete.",
      label: "Pushing changes...",
      run: async (_owns, signal) => {
        const report = await pushPeerLink(linkId, PUSH_PEER_NAME, signal);
        const conflicts = report.conflicts ? `, ${report.conflicts} kept as conflict copies on the other side` : "";
        return `Pushed ${fileCount(report.pushed)}${conflicts} (${report.skipped} unchanged).`;
      },
    });
  };

  const doLeave = (linkId: string) => {
    const leavePeerLink = transport.leavePeerLink;
    if (!leavePeerLink) return;
    void runMutation({
      fallback: "The link could not be removed.",
      label: "Leaving the folder...",
      run: async (owns, signal) => {
        await leavePeerLink(linkId, signal);
        if (!owns()) return null;
        setLinks((previous) => (previous ?? []).filter((entry) => entry.link_id !== linkId));
        return "Left the folder. Your local copy stays on disk.";
      },
    });
  };

  return (
    <section aria-labelledby="team-folders-title" className="team-folders">
      <h2 id="team-folders-title">Team folders</h2>
      <p className="team-folders__note">
        Share one folder (a token is shown once - hand it to your teammate), or join theirs. Agents on both sides work in their
        local copy; simultaneous edits survive as conflict copies. Nothing moves on its own: every exchange needs an explicit
        Share, Join, Pull or Push.
      </p>

      <div className="team-folders__toolbar">
        <h3>Shared and joined folders</h3>
        <button className="button button--ghost" disabled={busy} onClick={() => void startRefresh()} type="button">
          {listStatus === "error" ? "Retry" : "Refresh"}
        </button>
      </div>
      {listStatus === "loading" && <p className="team-folders__message" role="status">Loading the team folder lists...</p>}
      {listStatus === "error" && <p className="team-folders__error" role="alert">{listError}</p>}
      {listStatus === "error" && stale && shares !== null && (
        <p className="team-folders__stale">Showing the last list loaded successfully - it may be out of date.</p>
      )}

      <form className="team-folders__form" onSubmit={(e) => { e.preventDefault(); doShare(); }}>
        <h4>Share a folder</h4>
        <label htmlFor="team-folders-share-path">Folder to share (absolute path)</label>
        <input
          disabled={busy}
          id="team-folders-share-path"
          onChange={(e) => setSharePath(e.currentTarget.value)}
          placeholder={SHARE_PATH_PLACEHOLDER}
          type="text"
          value={sharePath}
        />
        <label htmlFor="team-folders-share-name">Share name</label>
        <input
          disabled={busy}
          id="team-folders-share-name"
          onChange={(e) => setShareName(e.currentTarget.value)}
          placeholder="example-team-docs"
          type="text"
          value={shareName}
        />
        <button
          className="button button--ghost"
          disabled={busy || !canShare || !shareReady}
          title={canShare ? undefined : unavailable("Sharing a folder")}
          type="submit"
        >
          Share
        </button>
        {!canShare && <p className="team-folders__unavailable">{unavailable("Sharing a folder")}</p>}
      </form>
      {freshToken && (
        <div className="team-folders__token" role="alert">
          <p>Share token (shown once): <code>{freshToken.token}</code></p>
          <p>
            Share id: <code>{freshToken.shareId}</code> - hand both to your teammate over a channel you trust, together with
            this machine&apos;s address. The token is never repeated and never appears in the list below.
          </p>
          <button className="button button--ghost" onClick={() => setFreshToken(null)} type="button">Hide token</button>
        </div>
      )}

      <div className="team-folders__section">
        <h4>Folders you share</h4>
        {shares !== null && shares.length === 0 && listStatus !== "error" && (
          <p className="team-folders__empty">You are not sharing any folder yet.</p>
        )}
        {shares !== null && shares.length > 0 && (
          <ul className="team-folders__list">
            {shares.map((entry) => (
              <li key={entry.share_id}>
                <span><strong>{entry.name}</strong> <code>{entry.path}</code></span>
                <span className="team-folders__actions">
                  <button
                    className="button button--ghost"
                    disabled={busy || !canRevoke}
                    onClick={() => doRevoke(entry.share_id)}
                    title={canRevoke ? undefined : unavailable("Stopping a share")}
                    type="button"
                  >
                    Stop sharing
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form className="team-folders__form" onSubmit={(e) => { e.preventDefault(); doJoin(); }}>
        <h4>Join a teammate&apos;s folder</h4>
        <label htmlFor="team-folders-join-url">Teammate URL</label>
        <input
          disabled={busy}
          id="team-folders-join-url"
          onChange={(e) => setJoinUrl(e.currentTarget.value)}
          placeholder={PEER_URL_PLACEHOLDER}
          type="text"
          value={joinUrl}
        />
        <label htmlFor="team-folders-join-share-id">Share id</label>
        <input
          disabled={busy}
          id="team-folders-join-share-id"
          onChange={(e) => setJoinShareId(e.currentTarget.value)}
          placeholder="Share id from your teammate"
          type="text"
          value={joinShareId}
        />
        <label htmlFor="team-folders-join-token">Share token</label>
        <input
          disabled={busy}
          id="team-folders-join-token"
          onChange={(e) => setJoinToken(e.currentTarget.value)}
          placeholder="Share token from your teammate"
          type="password"
          value={joinToken}
        />
        <label htmlFor="team-folders-join-target">Local folder for your copy</label>
        <input
          disabled={busy}
          id="team-folders-join-target"
          onChange={(e) => setJoinTarget(e.currentTarget.value)}
          placeholder={TARGET_PATH_PLACEHOLDER}
          type="text"
          value={joinTarget}
        />
        <button
          className="button button--ghost"
          disabled={busy || !canJoin || !joinReady}
          title={canJoin ? undefined : unavailable("Joining a folder")}
          type="submit"
        >
          Join
        </button>
        {!canJoin && <p className="team-folders__unavailable">{unavailable("Joining a folder")}</p>}
      </form>

      <div className="team-folders__section">
        <h4>Folders you joined</h4>
        {links !== null && links.length === 0 && listStatus !== "error" && (
          <p className="team-folders__empty">You have not joined any folder yet.</p>
        )}
        {links !== null && links.length > 0 && (
          <ul className="team-folders__list">
            {links.map((entry) => (
              <li key={entry.link_id}>
                <span><strong>{entry.name ?? "folder"}</strong> <code>{entry.target}</code></span>
                <span className="team-folders__actions">
                  <button
                    className="button button--ghost"
                    disabled={busy || !canPull}
                    onClick={() => doPull(entry.link_id)}
                    title={canPull ? undefined : unavailable("Pulling changes")}
                    type="button"
                  >
                    Pull
                  </button>
                  <button
                    className="button button--ghost"
                    disabled={busy || !canPush}
                    onClick={() => doPush(entry.link_id)}
                    title={canPush ? undefined : unavailable("Pushing changes")}
                    type="button"
                  >
                    Push
                  </button>
                  {onUseAsWorkspace && (
                    <button className="button button--ghost" disabled={busy} onClick={() => onUseAsWorkspace(entry.target)} type="button">
                      Use as workspace
                    </button>
                  )}
                  <button
                    className="button button--ghost"
                    disabled={busy || !canLeave}
                    onClick={() => doLeave(entry.link_id)}
                    title={canLeave ? undefined : unavailable("Leaving a folder")}
                    type="button"
                  >
                    Leave
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {pending && <p className="team-folders__pending" role="status">{pending}</p>}
      {status && <p className="team-folders__message" role="status">{status}</p>}
      {actionError && <p className="team-folders__error" role="alert">{actionError}</p>}
    </section>
  );
}
