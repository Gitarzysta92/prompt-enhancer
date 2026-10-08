import { useEffect, useRef, useState } from "react";

import type {
  AgentMessageSearchMatch as AgentSavedMessageSearchHit,
  AgentMessageSearchRequest as AgentSavedMessageSearchRequest,
  AgentMessageSearchResult as AgentSavedMessageSearchPage,
} from "../../shared/api/agentMessageSearchContract";
import { TransportError } from "../../shared/api/httpTransport";
import "./AgentMessageSearchDialog.css";

export type { AgentSavedMessageSearchHit, AgentSavedMessageSearchPage, AgentSavedMessageSearchRequest };

export type AgentSavedMessageSearch = (
  request: AgentSavedMessageSearchRequest,
  signal?: AbortSignal,
) => Promise<AgentSavedMessageSearchPage>;

function focusable(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex='-1'])")];
}

export function AgentMessageSearchDialog({
  initialProjectId,
  onClose,
  onOpenMatch,
  search,
}: {
  initialProjectId: string | null;
  onClose: () => void;
  onOpenMatch: (match: AgentSavedMessageSearchHit, signal: AbortSignal) => Promise<boolean>;
  search: AgentSavedMessageSearch;
}) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | "project">(initialProjectId === null ? "all" : "project");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState<AgentSavedMessageSearchPage | null>(null);
  const [submitted, setSubmitted] = useState<{
    query: string; projectId: string | null; includeArchived: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [failedPage, setFailedPage] = useState<{ offset: number; snapshot?: string } | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const owner = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const dialogRef = useRef<HTMLFormElement | null>(null);
  const searchRef = useRef(search);
  const onOpenMatchRef = useRef(onOpenMatch);
  searchRef.current = search;
  onOpenMatchRef.current = onOpenMatch;

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLInputElement>("input[type='search']")?.focus();
    return () => controller.current?.abort();
  }, []);

  useEffect(() => {
    owner.current += 1;
    controller.current?.abort();
    setPage(null); setSubmitted(null); setError(""); setFailedPage(null); setRestartRequired(false); setBusy(false); setOpening(false);
  }, [initialProjectId, search]);

  const invalidateResults = () => {
    owner.current += 1;
    controller.current?.abort();
    setPage(null); setSubmitted(null); setError(""); setFailedPage(null); setRestartRequired(false); setBusy(false); setOpening(false);
  };

  const submit = (nextPage?: { offset: number; snapshot?: string }, force = false) => {
    if (!force && (busy || opening)) return;
    const nextSubmitted = nextPage === undefined
      ? { query: query.trim(), projectId: scope === "project" ? initialProjectId : null, includeArchived }
      : submitted;
    if (nextSubmitted === null || !nextSubmitted.query) return;
    const offset = nextPage?.offset ?? 0;
    const snapshot = nextPage?.snapshot;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const requestOwner = owner.current + 1;
    owner.current = requestOwner;
    // Freeze the exact request before dispatch so a failed first page can be retried.
    setSubmitted(nextSubmitted);
    setBusy(true);
    setError("");
    setFailedPage(null);
    setRestartRequired(false);
    void searchRef.current({
      query: nextSubmitted.query,
      projectId: nextSubmitted.projectId ?? undefined,
      includeArchived: nextSubmitted.includeArchived,
      limit: 20,
      offset,
      snapshot,
    }, next.signal).then((result) => {
      if (next.signal.aborted || owner.current !== requestOwner) return;
      if (offset > 0 && (page === null
        || result.snapshot !== page.snapshot
        || result.total !== page.total
        || result.limit !== page.limit
        || result.matches.some((match) => page.matches.some((existing) => existing.session_id === match.session_id)))) {
        setRestartRequired(true);
        setError("The saved-message result set changed while another page was loading. Search again from the first page.");
        setFailedPage(null);
        return;
      }
      setPage((current) => offset === 0 ? result : current === null ? result : {
        ...result,
        matches: [...current.matches, ...result.matches],
      });
    }).catch((caught: unknown) => {
      if (!next.signal.aborted && owner.current === requestOwner) {
        if (caught instanceof TransportError && caught.status === 409) {
          setRestartRequired(true);
          setError("Saved messages changed while this page was loading. Start this search again from the first page.");
          return;
        }
        setError("Saved-message search could not be completed. Your current results are unchanged; retry this exact search.");
        setFailedPage({ offset, snapshot });
      }
    }).finally(() => {
      if (owner.current === requestOwner) setBusy(false);
    });
  };

  const close = () => {
    owner.current += 1;
    controller.current?.abort();
    onClose();
  };

  const restartSearch = () => {
    invalidateResults();
    submit(undefined, true);
  };

  const openMatch = (match: AgentSavedMessageSearchHit) => {
    if (busy || opening) return;
    setError("");
    const requestOwner = owner.current + 1;
    owner.current = requestOwner;
    controller.current?.abort();
    setOpening(true);
    const openController = new AbortController();
    controller.current = openController;
    void onOpenMatchRef.current(match, openController.signal).then((opened) => {
      if (owner.current !== requestOwner) return;
      if (opened) close();
    }).catch(() => {
      if (owner.current === requestOwner) setError("The matching saved chat could not be opened. It may have changed or been deleted; search again.");
    }).finally(() => { if (owner.current === requestOwner) setOpening(false); });
  };

  return (
    <div className="agent-message-search__backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) close(); }}>
      <form aria-labelledby="agent-message-search-title" aria-modal="true" className="agent-message-search" onKeyDownCapture={(event) => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); return; }
        if (event.key !== "Tab") return;
        const items = focusable(event.currentTarget);
        if (items.length === 0) return;
        const first = items[0]; const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }} onSubmit={(event) => { event.preventDefault(); submit(); }} ref={dialogRef} role="dialog" tabIndex={-1}>
        <header><div><small>Retained local history only</small><h2 id="agent-message-search-title">Search saved messages</h2></div><button aria-label="Close saved-message search" className="button button--ghost" onClick={close} type="button">Close</button></header>
        <p>Searches opted-in retained message text only. It never starts a model, resumes a chat, sends a message, or searches metadata-only chats.</p>
        <label><span>Saved-message phrase</span><input autoComplete="off" maxLength={120} onChange={(event) => { setQuery(event.currentTarget.value); invalidateResults(); }} placeholder="Search retained messages" type="search" value={query} /></label>
        <fieldset><legend>Scope</legend><label><input checked={scope === "all"} name="agent-message-search-scope" onChange={() => { setScope("all"); invalidateResults(); }} type="radio" /> All projects</label><label><input checked={scope === "project"} disabled={initialProjectId === null} name="agent-message-search-scope" onChange={() => { setScope("project"); invalidateResults(); }} type="radio" /> Current project</label><label><input checked={includeArchived} onChange={(event) => { setIncludeArchived(event.currentTarget.checked); invalidateResults(); }} type="checkbox" /> Include archived chats</label></fieldset>
        <div className="agent-message-search__actions"><button className="button button--primary" disabled={busy || opening || query.trim().length === 0} type="submit">{busy ? "Searching…" : "Search saved messages"}</button></div>
        {error && <div className="agent-message-search__error" role="alert"><span>{error}</span>{restartRequired ? <button disabled={busy || opening} onClick={restartSearch} type="button">Start search again</button> : <button disabled={busy || opening || failedPage === null} onClick={() => { if (failedPage !== null) submit(failedPage); }} type="button">Retry search</button>}</div>}
        {page !== null && <section aria-live="polite" className="agent-message-search__results"><p>{restartRequired ? "These saved-message results are stale. Start the search again before opening a chat." : page.total === 0 ? "No retained saved message matches this phrase." : `${page.matches.length} of ${page.total} matching chats loaded.`}</p><ul>{page.matches.map((match) => <li key={match.session_id}><button disabled={busy || opening || restartRequired} onClick={() => openMatch(match)} type="button"><span><strong>{match.title}</strong><small>{match.project_name} · {match.role === "user" ? "You" : "Agent"}</small></span><q>{match.excerpt}</q><em>{opening ? "Opening matching saved message…" : "Open matching saved message"}</em></button></li>)}</ul>{page.next_offset !== null && <button className="button button--ghost" disabled={busy || opening || restartRequired} onClick={() => submit({ offset: page.next_offset!, snapshot: page.snapshot })} type="button">{busy ? "Loading…" : "Load more matches"}</button>}</section>}
      </form>
    </div>
  );
}
