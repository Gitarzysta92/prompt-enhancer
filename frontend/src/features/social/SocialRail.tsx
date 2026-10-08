import { useId, useState } from "react";
import type { SocialSnapshot } from "../../shared/api/socialHub";
import { Avatar } from "../../shared/ui/Avatar";
import { EmptyState } from "../../shared/ui/EmptyState";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";
import { TabList, tabId, tabPanelId } from "../../shared/ui/Tabs";
import {
  PRESENCE_VALUE_LABELS,
  conversationTitle,
  friends,
  pendingRequests,
  personById,
  personPresence,
  searchSnapshot,
  totalUnread,
  unreadCount,
  type SocialHubAction,
} from "./socialHubModel";
import { PRESENCE_POLICY_COPY, shortUtcTime } from "./socialHubCopy";

/** Presence pill tone: not-shared is neutral and distinct from offline, never a warning or an "off" state. */
function presenceTone(presence: ReturnType<typeof personPresence>) {
  switch (presence) {
    case "online": return "positive" as const;
    case "offline": return "neutral" as const;
    case "not_shared": return "neutral" as const;
    default: return "warning" as const;
  }
}

type RailTab = "conversations" | "friends" | "requests";

/**
 * Left rail: search, conversations with unread counts, friends with presence,
 * and friend requests. Every list item is a real button; presence and unread
 * state are visible text plus SR text, never colour-only or hover-only.
 */
export function SocialRail({
  snapshot,
  activeConversationId,
  query,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  activeConversationId: string | null;
  query: string;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const idPrefix = useId();
  const searchId = useId();
  const [tab, setTab] = useState<RailTab>("conversations");
  const incoming = pendingRequests(snapshot, "incoming");
  const outgoing = pendingRequests(snapshot, "outgoing");
  const friendList = friends(snapshot);
  const results = searchSnapshot(snapshot, query);
  const searching = query.trim() !== "";
  const unread = totalUnread(snapshot);

  return (
    <aside aria-label="People and conversations" className="social-rail">
      <div className="social-rail__search">
        <label className="sr-only" htmlFor={searchId}>Search people, channels, and messages</label>
        <span aria-hidden="true" className="social-rail__search-icon"><Icon name="search" /></span>
        <input
          autoComplete="off"
          id={searchId}
          onChange={(event) => dispatch({ type: "set_query", query: event.target.value })}
          placeholder="Search people, channels, messages"
          type="search"
          value={query}
        />
        {searching && (
          <button aria-label="Clear search" className="social-rail__clear" onClick={() => dispatch({ type: "set_query", query: "" })} type="button">
            <Icon name="x" />
          </button>
        )}
      </div>

      {searching ? (
        <section aria-label="Search results" className="social-rail__results">
          <p className="social-rail__results-count" role="status">
            {results.people.length + results.conversations.length + results.messages.length === 0
              ? `No fixture match for “${query.trim()}”.`
              : `${results.people.length} people · ${results.conversations.length} conversations · ${results.messages.length} messages`}
          </p>
          {results.people.length > 0 && (
            <ul aria-label="Matching people" className="social-list">
              {results.people.map((person) => (
                <li key={person.id}>
                  <div className="social-list__row">
                    <Avatar name={person.display_name} presence={personPresence(person)} size="small" />
                    <span className="social-list__body">
                      <strong>{person.display_name}</strong>
                      <small>{person.handle}</small>
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {results.conversations.length > 0 && (
            <ul aria-label="Matching conversations" className="social-list">
              {results.conversations.map((conversation) => (
                <li key={conversation.id}>
                  <button className="social-list__row" onClick={() => dispatch({ type: "select_conversation", conversationId: conversation.id })} type="button">
                    <span className="social-list__glyph"><Icon name={conversation.kind === "dm" ? "chat" : "users"} /></span>
                    <span className="social-list__body">
                      <strong>{conversationTitle(snapshot, conversation)}</strong>
                      <small>{conversation.kind === "dm" ? "Direct message" : conversation.topic ?? "Invite-only group"}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {results.messages.length > 0 && (
            <ul aria-label="Matching messages" className="social-list">
              {results.messages.map((message) => {
                const conversation = snapshot.conversations.find((candidate) => candidate.id === message.conversation_id);
                return (
                  <li key={message.id}>
                    <button
                      className="social-list__row"
                      onClick={() => {
                        dispatch({ type: "select_conversation", conversationId: message.conversation_id });
                        if (message.thread_root_id !== null) dispatch({ type: "open_thread", rootId: message.thread_root_id });
                      }}
                      type="button"
                    >
                      <span className="social-list__glyph"><Icon name="chat" /></span>
                      <span className="social-list__body">
                        <strong>{personById(snapshot, message.author_id)?.display_name ?? "Unknown author"} · {conversation === undefined ? "Conversation" : conversationTitle(snapshot, conversation)}</strong>
                        <small>{message.body}</small>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ) : (
        <>
          <TabList<RailTab>
            compact
            idPrefix={idPrefix}
            label="Rail sections"
            onChange={setTab}
            tabs={[
              { id: "conversations", label: "Chats", badge: unread, badgeLabel: `${unread} unread messages` },
              { id: "friends", label: "Friends", detail: `${friendList.length}` },
              { id: "requests", label: "Requests", badge: incoming.length, badgeLabel: `${incoming.length} incoming friend requests` },
            ]}
            value={tab}
          />

          <div
            aria-labelledby={tabId(idPrefix, "conversations")}
            className="social-rail__panel"
            hidden={tab !== "conversations"}
            id={tabPanelId(idPrefix, "conversations")}
            role="tabpanel"
          >
            {snapshot.conversations.length === 0 ? (
              <EmptyState compact title="No conversations" description="Zero conversations are exposed in this runtime." />
            ) : (
              <ul aria-label="Conversations" className="social-list">
                {snapshot.conversations.map((conversation) => {
                  const count = unreadCount(snapshot, conversation);
                  const active = conversation.id === activeConversationId;
                  return (
                    <li key={conversation.id}>
                      <button
                        aria-current={active ? "true" : undefined}
                        className="social-list__row"
                        data-unread={count > 0 ? "true" : "false"}
                        onClick={() => dispatch({ type: "select_conversation", conversationId: conversation.id })}
                        type="button"
                      >
                        <span className="social-list__glyph"><Icon name={conversation.kind === "dm" ? "chat" : "users"} /></span>
                        <span className="social-list__body">
                          <strong>{conversationTitle(snapshot, conversation)}</strong>
                          <small>
                            {conversation.kind === "dm" ? "Direct message" : `Invite-only · ${conversation.members.length} members`}
                            {conversation.muted ? " · muted" : ""}
                          </small>
                        </span>
                        <span className="social-list__meta">
                          {count > 0
                            ? <span aria-label={`${count} unread`} className="social-unread">{count}</span>
                            : <span className="sr-only">All read</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div
            aria-labelledby={tabId(idPrefix, "friends")}
            className="social-rail__panel"
            hidden={tab !== "friends"}
            id={tabPanelId(idPrefix, "friends")}
            role="tabpanel"
          >
            {friendList.length === 0 ? (
              <EmptyState compact title="No friends" description="Zero relationships are exposed in this runtime." />
            ) : (
              <ul aria-label="Friends" className="social-list">
                {friendList.map((person) => (
                  <li key={person.id}>
                    <div className="social-list__row">
                      <Avatar name={person.display_name} presence={personPresence(person)} size="small" showPresenceText={false} />
                      <span className="social-list__body">
                        <strong>{person.display_name}</strong>
                        <small>{person.handle}</small>
                      </span>
                      <span className="social-list__meta">
                        <StatusPill tone={presenceTone(personPresence(person))}>
                          {PRESENCE_VALUE_LABELS[personPresence(person)]}
                        </StatusPill>
                        <button
                          aria-label={`Remove ${person.display_name} from friends`}
                          className="button button--compact button--secondary"
                          onClick={() => dispatch({ type: "remove_friend", personId: person.id })}
                          type="button"
                        >
                          Remove
                        </button>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="social-rail__hint" data-presence-policy="opt_in_coarse_not_analyzer">
              Presence · self-declared, coarse, opt-in · not analyzer activity. {PRESENCE_POLICY_COPY}
            </p>
          </div>

          <div
            aria-labelledby={tabId(idPrefix, "requests")}
            className="social-rail__panel"
            hidden={tab !== "requests"}
            id={tabPanelId(idPrefix, "requests")}
            role="tabpanel"
          >
            {incoming.length === 0 && outgoing.length === 0 ? (
              <EmptyState compact title="No pending requests" description="Zero requests are exposed in this runtime." />
            ) : (
              <>
                {incoming.length > 0 && (
                  <ul aria-label="Incoming friend requests" className="social-list">
                    {incoming.map((request) => {
                      const person = personById(snapshot, request.person_id);
                      return (
                        <li key={request.id}>
                          <div className="social-list__row social-list__row--stacked">
                            <div className="social-list__row">
                              <Avatar name={person?.display_name ?? "?"} presence={personPresence(person)} size="small" />
                              <span className="social-list__body">
                                <strong>{person?.display_name ?? "Unknown"}</strong>
                                <small>Incoming · {shortUtcTime(request.sent_at)}{request.note ? ` · ${request.note}` : ""}</small>
                              </span>
                            </div>
                            <div className="social-list__actions">
                              <button className="button button--compact button--primary" onClick={() => dispatch({ type: "accept_request", requestId: request.id, at: now() })} type="button">
                                Accept
                              </button>
                              <button className="button button--compact button--secondary" onClick={() => dispatch({ type: "decline_request", requestId: request.id })} type="button">
                                Decline
                              </button>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {outgoing.length > 0 && (
                  <ul aria-label="Outgoing friend requests" className="social-list">
                    {outgoing.map((request) => {
                      const person = personById(snapshot, request.person_id);
                      return (
                        <li key={request.id}>
                          <div className="social-list__row social-list__row--stacked">
                            <div className="social-list__row">
                              <Avatar name={person?.display_name ?? "?"} presence={personPresence(person)} size="small" />
                              <span className="social-list__body">
                                <strong>{person?.display_name ?? "Unknown"}</strong>
                                <small>Outgoing · pending since {shortUtcTime(request.sent_at)}</small>
                              </span>
                            </div>
                            <div className="social-list__actions">
                              <button className="button button--compact button--secondary" onClick={() => dispatch({ type: "withdraw_request", requestId: request.id })} type="button">
                                Withdraw
                              </button>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </>
            )}
            <p className="social-rail__hint">Accepting, declining, or withdrawing changes local demo state only.</p>
          </div>
        </>
      )}
    </aside>
  );
}
