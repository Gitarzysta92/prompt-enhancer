import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentWorkspaceDiscovery,
  AgentWorkspaceDiscoveryFile,
  AgentWorkspaceGitChange,
  AgentWorkspaceSearchResult,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import "./AgentWorkspaceDiscoveryPanel.css";

const DISCOVERY_PAGE_SIZE = 50;

type DiscoveryTransport = Partial<Pick<
  PromptEnhancerTransport,
  "getAgentWorkspaceDiscovery" | "getAgentWorkspaceSearch"
>>;
type LoadState = "loading" | "ready" | "error" | "unavailable";
type SearchState = "idle" | "loading" | "ready" | "error" | "unavailable";

const INVENTORY_REASON: Record<AgentWorkspaceDiscovery["inventory_reasons"][number], string> = {
  deadline_reached: "The inventory deadline was reached.",
  depth_limit: "Some folders exceeded the bounded depth limit.",
  display_limit: "More files exist than this card can display.",
  entry_limit: "The bounded entry scan ended before enumeration completed.",
  excluded_directories: "Protected or generated directories were excluded.",
  link_or_reparse_entries: "Links or reparse points were not followed.",
  unavailable_entries: "Some entries could not be inspected safely.",
  unrepresentable_entries: "Some entry names could not be represented safely.",
};

const GIT_REASON: Record<AgentWorkspaceDiscovery["git_reasons"][number], string> = {
  command_cleanup_unconfirmed: "Earlier command cleanup is unconfirmed, so Git inspection is blocked.",
  command_in_progress: "An approved command currently owns the workspace command lane.",
  deadline_reached: "Git status exceeded its bounded deadline.",
  display_limit: "More Git changes exist than this card can display.",
  executable_unavailable: "A local Git executable is not available.",
  excluded_paths: "Some returned paths are protected or outside the supported inventory.",
  output_limit: "Git status exceeded its bounded output limit.",
  repository_changed: "Repository metadata changed during inspection; all output was discarded.",
  repository_layout_unsupported: "This repository layout can redirect outside the selected folder, so it was refused.",
  status_failed: "The local Git status command did not complete successfully.",
  status_invalid: "Git returned a status shape that could not be validated safely.",
  unrepresentable_paths: "Some Git paths could not be represented safely.",
};

const CHANGE_KIND: Record<AgentWorkspaceGitChange["kind"], string> = {
  added: "Added",
  conflicted: "Conflict",
  copied: "Copied",
  deleted: "Deleted",
  modified: "Modified",
  renamed: "Renamed",
  type_changed: "Type changed",
  unknown: "Changed",
  untracked: "Untracked",
};

function plural(value: number, one: string, many = `${one}s`): string {
  return `${value.toLocaleString()} ${value === 1 ? one : many}`;
}

function bytes(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function changeLocation(change: AgentWorkspaceGitChange): string {
  if (change.kind === "untracked") return "Untracked";
  if (change.staged && change.unstaged) return "Index + worktree";
  if (change.staged) return "Staged";
  if (change.unstaged) return "Unstaged";
  return "Observed";
}

export function AgentWorkspaceDiscoveryPanel({
  sessionId,
  transport,
  refreshKey,
  fileActionsDisabled,
  onOpenFile,
  onRootChanged,
}: {
  sessionId: string;
  transport: DiscoveryTransport;
  refreshKey: string | number;
  fileActionsDisabled: boolean;
  onOpenFile?: (path: string) => void;
  onRootChanged?: () => void;
}) {
  const [state, setState] = useState<LoadState>(transport.getAgentWorkspaceDiscovery ? "loading" : "unavailable");
  const [snapshot, setSnapshot] = useState<AgentWorkspaceDiscovery | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [query, setQuery] = useState("");
  const [contentQuery, setContentQuery] = useState("");
  const [globPattern, setGlobPattern] = useState("**/*");
  const [regexSearch, setRegexSearch] = useState(false);
  const [searchState, setSearchState] = useState<SearchState>(
    transport.getAgentWorkspaceSearch ? "idle" : "unavailable",
  );
  const [searchResult, setSearchResult] = useState<AgentWorkspaceSearchResult | null>(null);
  const [searchMessage, setSearchMessage] = useState("");
  const searchRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const load = transport.getAgentWorkspaceDiscovery;
    searchRequest.current?.abort();
    setQuery("");
    setContentQuery("");
    setGlobPattern("**/*");
    setRegexSearch(false);
    setSearchResult(null);
    setSearchMessage("");
    setSearchState(transport.getAgentWorkspaceSearch ? "idle" : "unavailable");
    setSnapshot(null);
    if (!load) {
      setState("unavailable");
      return undefined;
    }
    const controller = new AbortController();
    const requestedSession = sessionId;
    setState("loading");
    void Promise.resolve(load(sessionId, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || value.session_id !== requestedSession) return;
        setSnapshot(value);
        setState("ready");
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setSnapshot(null);
        if (caught instanceof TransportError && caught.reasonCode === "workspace_root_changed") {
          onRootChanged?.();
        }
        setState(caught instanceof TransportError && caught.status === 404 ? "unavailable" : "error");
      });
    return () => {
      controller.abort();
      searchRequest.current?.abort();
    };
  }, [onRootChanged, refreshKey, retryNonce, sessionId, transport]);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleFiles = useMemo(() => snapshot?.files.filter((file) => (
    !normalizedQuery || file.path.toLocaleLowerCase().includes(normalizedQuery)
  )) ?? [], [normalizedQuery, snapshot]);
  const fileByPath = useMemo(() => new Map(snapshot?.files.map((file) => [file.path, file]) ?? []), [snapshot]);
  const filePage = useBoundedListPage({
    itemCount: visibleFiles.length,
    pageSize: DISCOVERY_PAGE_SIZE,
    resetKey: `${sessionId}:${String(refreshKey)}:files:${normalizedQuery}`,
  });
  const gitChanges = snapshot?.git_changes ?? [];
  const gitPage = useBoundedListPage({
    itemCount: gitChanges.length,
    pageSize: DISCOVERY_PAGE_SIZE,
    resetKey: `${sessionId}:${String(refreshKey)}:git`,
  });
  const searchMatches = searchResult?.matches ?? [];
  const searchPage = useBoundedListPage({
    itemCount: searchMatches.length,
    pageSize: DISCOVERY_PAGE_SIZE,
    resetKey: `${sessionId}:search:${contentQuery}:${globPattern}:${String(regexSearch)}:${searchResult?.match_count ?? 0}`,
  });

  function canOpen(file: AgentWorkspaceDiscoveryFile | undefined, change?: AgentWorkspaceGitChange): boolean {
    return Boolean(
      onOpenFile
      && !fileActionsDisabled
      && file?.editable_candidate
      && change?.kind !== "deleted"
    );
  }

  async function searchContents(): Promise<void> {
    const search = transport.getAgentWorkspaceSearch;
    if (!search) {
      setSearchState("unavailable");
      return;
    }
    if (!contentQuery.trim()) {
      setSearchMessage("Enter text or a regular expression to search.");
      setSearchState("error");
      return;
    }
    if (!globPattern.trim()) {
      setSearchMessage("Enter a workspace-relative file pattern, such as **/*.ts.");
      setSearchState("error");
      return;
    }
    searchRequest.current?.abort();
    const controller = new AbortController();
    searchRequest.current = controller;
    const requestedSession = sessionId;
    setSearchResult(null);
    setSearchMessage("");
    setSearchState("loading");
    try {
      const result = await search(sessionId, {
        query: contentQuery,
        glob: globPattern,
        regex: regexSearch,
      }, controller.signal);
      if (controller.signal.aborted || result.session_id !== requestedSession) return;
      setSearchResult(result);
      setSearchState("ready");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setSearchResult(null);
      if (caught instanceof TransportError && caught.reasonCode === "workspace_root_changed") {
        onRootChanged?.();
      }
      setSearchMessage(
        caught instanceof TransportError && caught.reasonCode === "workspace_regex_invalid"
          ? "That regular expression is invalid. No search result was accepted."
          : caught instanceof TransportError && caught.reasonCode === "workspace_glob_invalid"
            ? "Use a root-relative pattern without traversal, a drive, or an embedded ** wildcard."
            : "Workspace search did not complete. No previous result is presented as current.",
      );
      setSearchState("error");
    }
  }

  return <section aria-label="Workspace discovery" className="agent-discovery">
    <header className="agent-discovery__header">
      <span>
        <small>SELECTED FOLDER · READ-ONLY MAP</small>
        <strong>Workspace discovery</strong>
      </span>
      <button
        className="button button--ghost"
        disabled={state === "loading" || transport.getAgentWorkspaceDiscovery === undefined}
        onClick={() => setRetryNonce((value) => value + 1)}
        type="button"
      >Refresh map</button>
    </header>

    {state === "loading" && <p role="status">Mapping application-readable files and local Git status…</p>}
    {state === "unavailable" && <p>This transport cannot load the selected-folder discovery map.</p>}
    {state === "error" && <div className="agent-discovery__error" role="alert">
      <span>The workspace map could not be refreshed. No previous result is presented as current.</span>
      <button className="button button--ghost" onClick={() => setRetryNonce((value) => value + 1)} type="button">Try again</button>
    </div>}

    {state === "ready" && snapshot && <>
      <div className="agent-discovery__summary">
        <span data-coverage={snapshot.inventory_coverage}>
          {snapshot.inventory_coverage === "complete" ? "Complete application-readable inventory" : "Partial application-readable inventory"}
        </span>
        <p>{plural(snapshot.observed_file_count, "file")} observed · {plural(snapshot.scanned_entry_count, "entry", "entries")} inspected</p>
      </div>

      {snapshot.inventory_reasons.length > 0 && <div className="agent-discovery__warnings" role="status">
        {snapshot.inventory_reasons.map((reason) => <span key={reason}>{INVENTORY_REASON[reason]}</span>)}
      </div>}

      <label className="agent-discovery__search">
        <span>Filter mapped files</span>
        <input
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder="Type a relative path"
          type="search"
          value={query}
        />
      </label>

      {visibleFiles.length === 0 ? <p className="agent-discovery__empty">
        {query
          ? "No mapped file matches this filter."
          : snapshot.inventory_coverage === "complete"
            ? "No application-readable files were found in the selected folder."
            : "No file could be shown; partial coverage does not establish that the folder is empty."}
      </p> : <ul aria-label="Mapped workspace files" className="agent-discovery__files">
        {visibleFiles.slice(filePage.start, filePage.end).map((file) => <li key={file.path}>
          <span>
            <code>{file.path}</code>
            <small>{bytes(file.byte_size)} · {file.editable_candidate ? "Editable text candidate" : "Read-only in this editor"}</small>
          </span>
          <button
            aria-label={`Open ${file.path}`}
            className="button button--ghost"
            disabled={!canOpen(file)}
            onClick={() => onOpenFile?.(file.path)}
            type="button"
          >Open</button>
        </li>)}
      </ul>}
      <BoundedListPager label="Mapped workspace file pages" page={filePage} />

      <section aria-label="Workspace text search" className="agent-discovery__content-search">
        <header>
          <span><small>BOUNDED UTF-8 SEARCH</small><strong>Search file contents</strong></span>
          {searchResult && <button
            className="button button--ghost"
            onClick={() => { setSearchResult(null); setSearchMessage(""); setSearchState("idle"); }}
            type="button"
          >Clear</button>}
        </header>
        <form onSubmit={(event) => { event.preventDefault(); void searchContents(); }}>
          <label>
            <span>Text or expression</span>
            <input
              aria-label="Search workspace contents"
              autoComplete="off"
              disabled={fileActionsDisabled || searchState === "loading"}
              maxLength={1024}
              onChange={(event) => { setContentQuery(event.currentTarget.value); setSearchMessage(""); }}
              placeholder="Search application-readable text"
              type="search"
              value={contentQuery}
            />
          </label>
          <label>
            <span>File pattern</span>
            <input
              aria-label="Workspace search file pattern"
              autoComplete="off"
              disabled={fileActionsDisabled || searchState === "loading"}
              maxLength={1024}
              onChange={(event) => { setGlobPattern(event.currentTarget.value); setSearchMessage(""); }}
              spellCheck={false}
              type="text"
              value={globPattern}
            />
          </label>
          <label className="agent-discovery__regex">
            <input
              checked={regexSearch}
              disabled={fileActionsDisabled || searchState === "loading"}
              onChange={(event) => { setRegexSearch(event.currentTarget.checked); setSearchMessage(""); }}
              type="checkbox"
            />
            <span>Regular expression</span>
          </label>
          <button
            className="button button--secondary"
            disabled={fileActionsDisabled || searchState === "loading" || !contentQuery.trim() || !globPattern.trim()}
            type="submit"
          >{searchState === "loading" ? "Searching…" : "Search"}</button>
        </form>
        <p>Search is read-only and bounded to admitted UTF-8 text. Generated folders, links, binary files, large scans, and slow regular expressions remain excluded or explicitly partial.</p>
        {searchState === "unavailable" && <p>This transport cannot search workspace contents.</p>}
        {searchState === "error" && <p className="agent-discovery__search-error" role="alert">{searchMessage}</p>}
        {searchState === "loading" && <p role="status">Searching the bounded workspace…</p>}
        {searchState === "ready" && searchResult && <>
          <div className="agent-discovery__search-summary" data-coverage={searchResult.coverage}>
            <strong>{plural(searchResult.match_count, "match", "matches")}</strong>
            <span>{plural(searchResult.scanned_entry_count, "entry", "entries")} scanned · {bytes(searchResult.inspected_byte_count)} inspected · {plural(searchResult.skipped_entry_count, "skipped entry", "skipped entries")}</span>
          </div>
          {searchResult.coverage === "partial" && <div className="agent-discovery__warnings" role="status">
            <strong>Partial search coverage</strong>
            {searchResult.reasons.map((reason) => <span key={reason}>{reason}</span>)}
          </div>}
          {searchResult.matches.length === 0 ? <p>No match was found in the inspected UTF-8 text scope.</p> : <ul aria-label="Workspace search results" className="agent-discovery__results">
            {searchMatches.slice(searchPage.start, searchPage.end).map((match) => {
              const file = fileByPath.get(match.path);
              return <li key={`${match.path}:${match.line_number}`}>
                <span>
                  <code>{match.path}:{match.line_number}</code>
                  <small>{match.preview || "(matching empty line)"}</small>
                </span>
                <button
                  aria-label={`Open search result ${match.path} line ${match.line_number}`}
                  className="button button--ghost"
                  disabled={!canOpen(file)}
                  onClick={() => onOpenFile?.(match.path)}
                  type="button"
                >Open</button>
              </li>;
            })}
          </ul>}
          <BoundedListPager label="Workspace search result pages" page={searchPage} />
        </>}
      </section>

      <section aria-label="Git status" className="agent-discovery__git">
        <header>
          <span><small>LOCAL METADATA</small><strong>Git status</strong></span>
          {snapshot.git_state === "available" && <em data-coverage={snapshot.git_coverage}>
            {snapshot.git_coverage === "complete" ? "Complete" : "Partial"}
          </em>}
        </header>
        {snapshot.git_state === "not_repository" && <p>No supported repository is rooted exactly at the selected folder.</p>}
        {snapshot.git_state === "unavailable" && <div className="agent-discovery__warnings" role="status">
          {snapshot.git_reasons.map((reason) => <span key={reason}>{GIT_REASON[reason]}</span>)}
        </div>}
        {snapshot.git_state === "available" && <>
          <p>{plural(snapshot.git_change_count ?? 0, "change")} reported by bounded porcelain status.</p>
          {snapshot.git_reasons.length > 0 && <div className="agent-discovery__warnings" role="status">
            {snapshot.git_reasons.map((reason) => <span key={reason}>{GIT_REASON[reason]}</span>)}
          </div>}
          {snapshot.git_changes.length === 0 ? <p>The supported repository currently reports no changes.</p> : <ul aria-label="Git changes" className="agent-discovery__changes">
            {gitChanges.slice(gitPage.start, gitPage.end).map((change) => {
              const file = fileByPath.get(change.path);
              return <li key={change.path}>
                <span className="agent-discovery__change-kind" data-kind={change.kind}>{CHANGE_KIND[change.kind]}</span>
                <span><code>{change.path}</code><small>{changeLocation(change)}</small></span>
                <button
                  aria-label={`Open Git change ${change.path}`}
                  className="button button--ghost"
                  disabled={!canOpen(file, change)}
                  onClick={() => onOpenFile?.(change.path)}
                  type="button"
                >Open</button>
              </li>;
            })}
          </ul>}
          <BoundedListPager label="Git change pages" page={gitPage} />
        </>}
      </section>

      <p className="agent-discovery__scope">
        This is a bounded, content-free snapshot of the selected folder. It exposes no branch, commit, remote, absolute path or file content. Only separately reviewed writes carry publication authority.
      </p>
    </>}
  </section>;
}
