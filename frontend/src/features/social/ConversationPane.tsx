import { useEffect, useId, useRef, useState } from "react";
import type { Conversation, SocialMessage, SocialSnapshot } from "../../shared/api/socialHub";
import { Avatar } from "../../shared/ui/Avatar";
import { EmptyState } from "../../shared/ui/EmptyState";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";
import {
  canPerform,
  conversationMessages,
  conversationTitle,
  directConversationHasLiveFriendship,
  myRole,
  personById,
  personPresence,
  threadReplies,
  unreadCount,
  type SocialHubAction,
} from "./socialHubModel";
import { PAYLOAD_POLICY_COPY, ROLE_LABELS, shortUtcTime } from "./socialHubCopy";

const QUICK_REACTIONS: readonly { emoji: string; label: string }[] = [
  { emoji: "👍", label: "thumbs up" },
  { emoji: "✅", label: "check mark" },
  { emoji: "👀", label: "eyes" },
];

const threadTriggerId = (messageId: string): string => `social-thread-trigger-${messageId}`;

export function MessageItem({
  snapshot,
  conversation,
  message,
  dispatch,
  inThread = false,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
  message: SocialMessage;
  dispatch: (action: SocialHubAction) => void;
  inThread?: boolean;
}) {
  const author = personById(snapshot, message.author_id);
  const mine = message.author_id === snapshot.me_person_id;
  const replies = inThread ? [] : threadReplies(snapshot, message.id);
  const canReact = canPerform(snapshot, conversation, "react");
  const canThread = canPerform(snapshot, conversation, "start_thread");
  const headingId = `message-${message.id.slice(0, 8)}-${inThread ? "thread" : "top"}`;
  return (
    <li className="social-message" data-kind={message.kind} data-mine={mine ? "true" : "false"}>
      <article aria-labelledby={headingId}>
        <header className="social-message__header">
          <Avatar name={author?.display_name ?? "?"} presence={personPresence(author)} size="small" />
          <span className="social-message__author" id={headingId}>
            <strong>{author?.display_name ?? "Unknown author"}</strong>
            <small>{shortUtcTime(message.sent_at)}{message.kind === "system" ? " · system" : ""}{message.kind === "file_offer" ? " · file offer" : ""}</small>
          </span>
        </header>
        <p className="social-message__body">{message.body}</p>
        <div className="social-message__reactions">
          {message.reactions.map((reaction) => {
            const reacted = reaction.person_ids.includes(snapshot.me_person_id);
            const names = reaction.person_ids.map((id) => personById(snapshot, id)?.display_name ?? "Unknown").join(", ");
            return (
              <button
                aria-label={`${reaction.label}: ${reaction.person_ids.length} · ${names}${reacted ? " · you reacted" : ""}`}
                aria-pressed={reacted}
                className="social-reaction"
                disabled={!canReact}
                key={reaction.emoji}
                onClick={() => dispatch({ type: "toggle_reaction", messageId: message.id, emoji: reaction.emoji, label: reaction.label })}
                type="button"
              >
                <span aria-hidden="true">{reaction.emoji}</span> {reaction.person_ids.length}
              </button>
            );
          })}
          {canReact && message.kind !== "system" && (
            <span className="social-message__quick" role="group" aria-label={`Add reaction to message from ${author?.display_name ?? "unknown"}`}>
              {QUICK_REACTIONS.filter((quick) => !message.reactions.some((reaction) => reaction.emoji === quick.emoji)).map((quick) => (
                <button
                  aria-label={`React with ${quick.label}`}
                  className="social-reaction social-reaction--add"
                  key={quick.emoji}
                  onClick={() => dispatch({ type: "toggle_reaction", messageId: message.id, emoji: quick.emoji, label: quick.label })}
                  type="button"
                >
                  <span aria-hidden="true">{quick.emoji}</span>
                </button>
              ))}
            </span>
          )}
          {!inThread && message.kind !== "system" && (
            <button
              className="social-message__thread"
              disabled={!canThread && replies.length === 0}
              id={threadTriggerId(message.id)}
              onClick={() => dispatch({ type: "open_thread", rootId: message.id })}
              type="button"
            >
              <Icon name="split" />
              {replies.length === 0 ? (canThread ? "Start thread" : "Threads not permitted for your role") : `${replies.length} ${replies.length === 1 ? "reply" : "replies"}`}
            </button>
          )}
        </div>
      </article>
    </li>
  );
}

function Composer({
  snapshot,
  conversation,
  threadRootId,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
  threadRootId: string | null;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const role = myRole(snapshot, conversation);
  const friendshipActive = directConversationHasLiveFriendship(snapshot, conversation);
  const allowed = canPerform(snapshot, conversation, "post") && (threadRootId === null || canPerform(snapshot, conversation, "start_thread"));
  const label = threadRootId === null ? "Message (local demo, not delivered)" : "Thread reply (local demo, not delivered)";
  return (
    <form
      className="social-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (!allowed || draft.trim() === "") return;
        dispatch({ type: "send_message", conversationId: conversation.id, body: draft, threadRootId, at: now() });
        setDraft("");
      }}
    >
      <label className="sr-only" htmlFor={inputId}>{label}</label>
      <input
        aria-describedby={`${inputId}-hint`}
        disabled={!allowed}
        id={inputId}
        maxLength={280}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={allowed ? label : friendshipActive ? "Your role cannot post here" : "Direct messages require a current friendship"}
        type="text"
        value={draft}
      />
      <button
        aria-describedby={`${inputId}-hint`}
        className="button button--primary"
        disabled={!allowed || draft.trim() === ""}
        type="submit"
      >
        <Icon name="send" /> Add locally
      </button>
      <p className="social-composer__hint" id={`${inputId}-hint`}>
        {allowed
          ? `${draft.trim() === "" ? "Type a message to enable Add locally. " : "Ready to add this message locally. "}Posting as ${role === null ? "no role" : ROLE_LABELS[role]} · appended to this browser's memory only · never delivered · ${PAYLOAD_POLICY_COPY}`
          : friendshipActive
            ? `Your role (${role === null ? "not a member" : ROLE_LABELS[role]}) is not permitted to ${threadRootId === null ? "post" : "reply in threads"} here.`
            : "This direct conversation is read-only because direct-message operations require a current friendship."}
      </p>
    </form>
  );
}

/** Centre column: one conversation, its messages, and the local-only composer. */
export function ConversationPane({
  snapshot,
  conversation,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation | null;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const titleId = useId();
  if (conversation === null) {
    return (
      <section aria-label="Conversation" className="social-conversation">
        <EmptyState title="No conversation selected" description="Choose a chat from the rail to read it here." icon="chat" />
      </section>
    );
  }
  const messages = conversationMessages(snapshot, conversation.id).filter((message) => message.thread_root_id === null);
  const role = myRole(snapshot, conversation);
  const unread = unreadCount(snapshot, conversation);
  return (
    <section aria-labelledby={titleId} className="social-conversation" data-kind={conversation.kind}>
      <header className="social-conversation__header">
        <div>
          <p className="eyebrow">{conversation.kind === "dm" ? "Direct message · invite-only" : "Invite-only group · not discoverable"}</p>
          <h2 id={titleId}>{conversationTitle(snapshot, conversation)}</h2>
          {conversation.topic !== null && <p className="social-conversation__topic">{conversation.topic}</p>}
        </div>
        <div className="social-conversation__meta">
          <StatusPill tone="info">{role === null ? "Not a member" : `Your role · ${ROLE_LABELS[role]}`}</StatusPill>
          <StatusPill tone={unread > 0 ? "warning" : "neutral"}>{unread > 0 ? `${unread} unread` : "All read"}</StatusPill>
          {unread > 0 && (
            <button className="button button--compact button--secondary" onClick={() => dispatch({ type: "mark_conversation_read", conversationId: conversation.id })} type="button">
              Mark read
            </button>
          )}
        </div>
      </header>
      {messages.length === 0 ? (
        <EmptyState compact title="No messages yet" description="This conversation has zero messages in local state." icon="chat" />
      ) : (
        <ol aria-label={`Messages in ${conversationTitle(snapshot, conversation)}`} className="social-message-list">
          {messages.map((message) => (
            <MessageItem conversation={conversation} dispatch={dispatch} key={message.id} message={message} snapshot={snapshot} />
          ))}
        </ol>
      )}
      <Composer conversation={conversation} dispatch={dispatch} key={conversation.id} now={now} snapshot={snapshot} threadRootId={null} />
    </section>
  );
}

/** Right column thread view for one root message. */
export function ThreadPane({
  snapshot,
  conversation,
  rootId,
  dispatch,
  now,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
  rootId: string;
  dispatch: (action: SocialHubAction) => void;
  now: () => string;
}) {
  const titleId = useId();
  const paneRef = useRef<HTMLElement>(null);
  useEffect(() => {
    paneRef.current?.focus();
  }, [rootId]);
  const root = snapshot.messages.find((message) => message.id === rootId);
  if (root === undefined) return null;
  const replies = threadReplies(snapshot, rootId);
  return (
    <section aria-labelledby={titleId} className="social-thread" ref={paneRef} tabIndex={-1}>
      <header className="social-thread__header">
        <h3 id={titleId}>Thread · {replies.length} {replies.length === 1 ? "reply" : "replies"}</h3>
        <button
          aria-label="Close thread"
          className="social-thread__close"
          onClick={() => {
            dispatch({ type: "close_thread" });
            window.setTimeout(() => document.getElementById(threadTriggerId(rootId))?.focus(), 0);
          }}
          type="button"
        >
          <Icon name="x" />
        </button>
      </header>
      <ol aria-label="Thread messages" className="social-message-list social-message-list--thread">
        <MessageItem conversation={conversation} dispatch={dispatch} inThread message={root} snapshot={snapshot} />
        {replies.map((reply) => (
          <MessageItem conversation={conversation} dispatch={dispatch} inThread key={reply.id} message={reply} snapshot={snapshot} />
        ))}
      </ol>
      <Composer conversation={conversation} dispatch={dispatch} key={rootId} now={now} snapshot={snapshot} threadRootId={rootId} />
    </section>
  );
}
