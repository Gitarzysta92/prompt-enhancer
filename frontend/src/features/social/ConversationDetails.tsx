import type { Conversation, SocialSnapshot } from "../../shared/api/socialHub";
import { SOCIAL_PERMISSION_ACTIONS } from "../../shared/api/socialHub";
import { Avatar } from "../../shared/ui/Avatar";
import { Disclosure } from "../../shared/ui/Disclosure";
import { FactList } from "../../shared/ui/FactList";
import { DIRECT_PATH_LABELS, canPerform, myRole, personById, personPresence } from "./socialHubModel";
import { GROUP_ACCESS_COPY, PERMISSION_LABELS, ROLE_LABELS } from "./socialHubCopy";

/**
 * Members, roles, and the role → permission matrix for one conversation.
 * "You can / cannot" is rendered as visible text per action so a blocked
 * composer or share button is never a mystery.
 */
export function ConversationDetails({
  snapshot,
  conversation,
}: {
  snapshot: SocialSnapshot;
  conversation: Conversation;
}) {
  const role = myRole(snapshot, conversation);
  return (
    <div className="social-details">
      <Disclosure
        compact
        defaultOpen
        detail={`${conversation.members.length} · invite-only`}
        summary="Members and roles"
      >
        <p className="social-details__access" data-access={conversation.access} data-discoverable={String(conversation.discoverable)}>
          {conversation.kind === "dm" ? "Direct message · two members" : "Invite-only group · finite member list"} · not public, not discoverable. {GROUP_ACCESS_COPY}
        </p>
        <ul aria-label="Conversation members" className="social-members">
          {conversation.members.map((member) => {
            const person = personById(snapshot, member.person_id);
            return (
              <li key={member.person_id}>
                <Avatar name={person?.display_name ?? "?"} presence={personPresence(person)} showPresenceText size="small" />
                <span className="social-members__body">
                  <strong>{person?.display_name ?? "Unknown"}</strong>
                  <small>{ROLE_LABELS[member.role]}{person?.is_me ? " · you" : ""}{person === null ? "" : ` · ${DIRECT_PATH_LABELS[person.direct_path]}`}</small>
                </span>
              </li>
            );
          })}
        </ul>
      </Disclosure>
      <Disclosure
        compact
        detail={role === null ? "Not a member" : ROLE_LABELS[role]}
        summary="Your permissions"
      >
        <FactList
          compact
          label="Permission matrix"
          facts={SOCIAL_PERMISSION_ACTIONS.map((action) => ({
            term: PERMISSION_LABELS[action],
            detail: `${canPerform(snapshot, conversation, action) ? "You can" : "You cannot"} · roles: ${
              conversation.permissions[action].length === 0
                ? "none"
                : conversation.permissions[action].map((allowed) => ROLE_LABELS[allowed]).join(", ")
            }`,
          }))}
        />
      </Disclosure>
    </div>
  );
}
