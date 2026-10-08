import type { AgentEvent } from "../../shared/api/contracts";

export type LoadedConversationMessageMatch = {
  eventIndex: number;
  eventSeq: number;
  role: "user" | "assistant";
};

export type LoadedConversationSearchableEvent = {
  event: AgentEvent;
  eventIndex: number;
};

function literalExpression(query: string, matchCase: boolean): RegExp | null {
  if (query === "") return null;
  const escaped = query.replace(/[\\^$.*+?()[\]{}|/]/gu, "\\$&");
  try {
    return new RegExp(escaped, matchCase ? "u" : "iu");
  } catch {
    return null;
  }
}

/**
 * Finds loaded message events without searching tool output or reasoning.
 * The result is intentionally one item per message, not per phrase occurrence.
 */
export function findLoadedConversationMessages(
  events: readonly AgentEvent[],
  query: string,
  matchCase: boolean,
): LoadedConversationMessageMatch[] {
  if (query === "") return [];
  return findLoadedConversationMessageCandidates(
    events.flatMap((event, eventIndex) => (
      event.kind === "user" || event.kind === "assistant"
        ? [{ event, eventIndex }]
        : []
    )),
    query,
    matchCase,
  );
}

export function findLoadedConversationMessageCandidates(
  events: readonly LoadedConversationSearchableEvent[],
  query: string,
  matchCase: boolean,
): LoadedConversationMessageMatch[] {
  const expression = literalExpression(query, matchCase);
  if (expression === null) return [];
  const matches: LoadedConversationMessageMatch[] = [];
  for (const { event, eventIndex } of events) {
    if ((event.kind !== "user" && event.kind !== "assistant") || !event.text) continue;
    if (!expression.test(event.text)) continue;
    matches.push({ eventIndex, eventSeq: event.seq, role: event.kind });
  }
  return matches;
}
