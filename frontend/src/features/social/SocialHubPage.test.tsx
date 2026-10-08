import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  createSyntheticSocialHubPort,
  createSyntheticSocialSnapshot,
  createUnavailableSocialHubPort,
  type SocialHubPort,
} from "../../shared/api/socialHub";
import { SocialHubPage } from "./SocialHubPage";

const NOW = "2040-02-03T09:30:00Z";
const PRIVATE_CANARY = "PRIVATE-SOCIAL-CANARY";

function renderPage(port: SocialHubPort, runtimeMode: "synthetic_demo" | "local_real" = "synthetic_demo", simulationIntervalMs = 20) {
  return render(<SocialHubPage now={() => NOW} port={port} runtimeMode={runtimeMode} simulationIntervalMs={simulationIntervalMs} />);
}

async function ready() {
  return screen.findByRole("group", { name: "Local social state summary" });
}

describe("SocialHubPage", () => {
  it("labels the synthetic demo as fictional and exposes friends, chats, requests, presence, and unread state", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    expect(screen.getByRole("heading", { name: "Social hub" })).toBeInTheDocument();
    const notice = screen.getByRole("note", { name: "Fictional synthetic demo" });
    expect(notice).toHaveTextContent(/Fictional synthetic demo/);
    expect(notice).toHaveTextContent(/nothing is delivered to another device, stored durably, synced, or encrypted/);
    const summary = screen.getByRole("group", { name: "Local social state summary" });
    expect(summary).toHaveTextContent("3 friends");
    expect(summary).toHaveTextContent("4 conversations");
    expect(summary).toHaveTextContent("6 unread");
    expect(summary).toHaveTextContent("Local state only · not delivered");

    const chats = screen.getByRole("list", { name: "Conversations" });
    expect(within(chats).getAllByRole("listitem")).toHaveLength(4);
    expect(within(chats).getByLabelText("3 unread")).toBeInTheDocument();
    expect(within(chats).getByRole("button", { name: /Alex Example/ })).toHaveAttribute("aria-current", "true");

    const tabs = screen.getByRole("tablist", { name: "Rail sections" });
    expect(within(tabs).getByRole("tab", { name: /Chats/ })).toHaveAttribute("aria-selected", "true");
    within(tabs).getByRole("tab", { name: /Friends/ }).click();
    const friends = await screen.findByRole("list", { name: "Friends" });
    expect(within(friends).getAllByRole("listitem")).toHaveLength(3);
    expect(within(friends).getByText("Alex Example")).toBeInTheDocument();
    expect(within(friends).getAllByText("Online").length).toBeGreaterThan(0);
    within(tabs).getByRole("tab", { name: /Requests/ }).click();
    const incoming = await screen.findByRole("list", { name: "Incoming friend requests" });
    expect(within(incoming).getByText("Dana Example")).toBeInTheDocument();
    within(incoming).getByRole("button", { name: "Accept" }).click();
    await waitFor(() => expect(screen.getByRole("group", { name: "Local social state summary" })).toHaveTextContent("4 friends"));
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/added as a friend in local demo state/);
    expect(document.body.textContent).not.toContain(PRIVATE_CANARY);
  });

  it("switches conversations, marks them read, adds local messages, reactions, and thread replies", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    const chats = screen.getByRole("list", { name: "Conversations" });
    within(chats).getByRole("button", { name: /#fixture-guild/ }).click();
    const conversation = await screen.findByRole("region", { name: "#fixture-guild" });
    expect(within(conversation).getByText("All read")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Local social state summary" })).toHaveTextContent("3 unread");
    expect(within(conversation).getByText(/Your role · Owner/)).toBeInTheDocument();

    const composer = within(conversation).getByLabelText("Message (local demo, not delivered)");
    const addLocally = within(conversation).getByRole("button", { name: /Add locally/ });
    expect(addLocally).toBeDisabled();
    expect(addLocally).toHaveAccessibleDescription(/Type a message to enable Add locally/i);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(composer, { target: { value: "Fixture local note" } });
    expect(addLocally).toBeEnabled();
    expect(addLocally).toHaveAccessibleDescription(/Ready to add this message locally/i);
    addLocally.click();
    expect(await within(conversation).findByText("Fixture local note")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/Nothing was delivered/);

    const thumbs = within(conversation).getByRole("button", { name: /^thumbs up: 2/ });
    thumbs.click();
    expect(await within(conversation).findByRole("button", { name: /^thumbs up: 3 .* you reacted/ })).toHaveAttribute("aria-pressed", "true");

    const threadTrigger = within(conversation).getByRole("button", { name: "2 replies" });
    threadTrigger.focus();
    threadTrigger.click();
    const thread = await screen.findByRole("region", { name: /Thread · 2 replies/ });
    await waitFor(() => expect(thread).toHaveFocus());
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/Thread opened · 2 replies/);
    const threadComposer = within(thread).getByLabelText("Thread reply (local demo, not delivered)");
    fireEvent.change(threadComposer, { target: { value: "Fixture third reply" } });
    within(thread).getByRole("button", { name: /Add locally/ }).click();
    expect(await screen.findByRole("region", { name: /Thread · 3 replies/ })).toBeInTheDocument();
    within(thread).getByRole("button", { name: "Close thread" }).click();
    const files = await screen.findByRole("region", { name: "Direct file sharing" });
    expect(files).toBeInTheDocument();
    const mismatch = within(files).getByRole("article", { name: "synthetic-integrity-mismatch.bin" });
    expect(mismatch).toHaveTextContent(/Integrity mismatch/);
    await waitFor(() => expect(threadTrigger).toHaveFocus());
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/Thread closed/);
  });

  it("blocks posting and file offers when the role lacks permission, with the reason as visible text", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    within(screen.getByRole("list", { name: "Conversations" })).getByRole("button", { name: /#release-notes/ }).click();
    const conversation = await screen.findByRole("region", { name: "#release-notes" });
    expect(within(conversation).getByPlaceholderText("Your role cannot post here")).toBeDisabled();
    expect(within(conversation).getByText(/is not permitted to post here/)).toBeInTheDocument();
    expect(screen.getByText("Your role in this conversation cannot offer files.")).toBeInTheDocument();
    screen.getByRole("button", { name: /Your permissions/ }).click();
    const matrix = await screen.findByLabelText("Permission matrix");
    expect(matrix).toHaveTextContent(/Post messages.*You cannot/);
    expect(matrix).toHaveTextContent(/React.*You can/);
  });

  it("searches people, channels, and messages", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("Search people, channels, and messages"), { target: { value: "evidence" } });
    const results = await screen.findByRole("region", { name: "Search results" });
    expect(within(results).getByRole("list", { name: "Matching messages" })).toBeInTheDocument();
    expect(within(results).getByRole("status")).toHaveTextContent(/messages/);
    fireEvent.change(screen.getByLabelText("Search people, channels, and messages"), { target: { value: "blake" } });
    expect(await within(screen.getByRole("region", { name: "Search results" })).findByRole("list", { name: "Matching people" })).toHaveTextContent("Blake Example");
    expect(within(screen.getByRole("region", { name: "Search results" })).getByRole("list", { name: "Matching conversations" })).toHaveTextContent("Blake Example");
  });

  it("runs the direct file-sharing flow: consent dialog → transferring → pause → resume → verified, plus revoke and expiry", async () => {
    {
      renderPage(createSyntheticSocialHubPort(), "synthetic_demo", 40);
      await ready();
      const files = screen.getByRole("region", { name: "Direct file sharing" });
      expect(files).toHaveTextContent(/No file is read from disk, no path is exposed, and no bytes exist/);
      const offers = within(files).getByRole("list", { name: "File offers" });
      const notes = within(offers).getByRole("article", { name: "synthetic-readiness-notes.md" });
      expect(notes).toHaveTextContent("Awaiting recipient consent");
      expect(within(notes).getByRole("progressbar")).toHaveAttribute("aria-valuetext", expect.stringContaining("amount unknown"));
      expect(notes).toHaveTextContent(/never traverse or rest on the coordination plane/);
      expect(notes).toHaveTextContent(/direct only, no relay, no TURN/);
      expect(notes).toHaveTextContent(/cannot recall bytes a recipient already downloaded/);

      within(notes).getByRole("button", { name: "Review and consent" }).click();
      const dialog = await screen.findByRole("dialog", { name: "Accept synthetic-readiness-notes.md?" });
      expect(dialog).toHaveAttribute("aria-modal", "true");
      expect(dialog).toHaveTextContent(/never receives a copy/);
      expect(within(dialog).getByRole("button", { name: "Grant consent" })).toHaveFocus();
      within(dialog).getByRole("button", { name: "Grant consent" }).click();
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() => expect(notes).toHaveTextContent("Transferring directly"));
      within(notes).getByRole("button", { name: /Pause/ }).click();
      await waitFor(() => expect(notes).toHaveTextContent("Paused"));
      const paused = within(notes).getByRole("progressbar").getAttribute("aria-valuenow");
      await new Promise((resolve) => setTimeout(resolve, 150));
      expect(within(notes).getByRole("progressbar")).toHaveAttribute("aria-valuenow", paused ?? "");
      within(notes).getByRole("button", { name: /Resume/ }).click();
      await waitFor(() => expect(notes).toHaveTextContent("Complete · integrity verified"), { timeout: 4000 });
      expect(notes).toHaveTextContent(/Integrity verified \(fixture digest\)/);
      expect(within(notes).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");

      const mine = within(offers).getByRole("article", { name: "synthetic-metric-summary.pdf" });
      within(mine).getByRole("button", { name: "Revoke offer" }).click();
      const revokeDialog = await screen.findByRole("dialog", { name: "Revoke synthetic-metric-summary.pdf?" });
      within(revokeDialog).getByRole("button", { name: "Revoke" }).click();
      await waitFor(() => expect(mine).toHaveTextContent("Revoked by owner"));
      expect(within(mine).queryByRole("button", { name: "Revoke offer" })).toBeNull();
    }
  });

  it("stops claiming an offer awaits consent once every recipient declined", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    const files = screen.getByRole("region", { name: "Direct file sharing" });
    const notes = within(files).getByRole("article", { name: "synthetic-readiness-notes.md" });
    expect(notes).toHaveTextContent("Awaiting recipient consent");
    within(notes).getByRole("button", { name: "Decline" }).click();
    await waitFor(() => expect(notes).toHaveTextContent("Declined by every recipient · no transfer can start"));
    expect(notes).not.toHaveTextContent("Awaiting recipient consent");
    expect(notes).toHaveTextContent(/no bytes were requested and none can move/);
    expect(notes).toHaveTextContent(/never waits on a server/);
    expect(notes).toHaveTextContent(/Consent declined/);
    expect(within(notes).getByRole("progressbar")).toHaveAttribute("aria-valuetext", expect.stringContaining("amount unknown"));
    expect(within(notes).queryByRole("button", { name: "Review and consent" })).toBeNull();
    expect(document.body.textContent).not.toContain(PRIVATE_CANARY);
  });

  it("shows owner-offline and expired offers honestly and lets an owner create a metadata-only offer", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    within(screen.getByRole("list", { name: "Conversations" })).getByRole("button", { name: /#fixture-guild/ }).click();
    await screen.findByRole("region", { name: "#fixture-guild" });
    const files = screen.getByRole("region", { name: "Direct file sharing" });
    const offline = within(files).getByRole("article", { name: "synthetic-evidence-list.csv" });
    expect(offline).toHaveTextContent("Owner offline · waiting");
    expect(within(offline).getByRole("button", { name: /Resume \(owner offline\)/ })).toBeDisabled();
    const expired = within(files).getByRole("article", { name: "synthetic-flow-board.png" });
    expect(expired).toHaveTextContent("Expired");
    expect(within(expired).queryByRole("button", { name: "Revoke offer" })).toBeNull();

    const form = within(files).getByRole("form", { name: "Offer a file (metadata only)" });
    expect(form).toHaveTextContent(/No file picker, path, or bytes are involved/);
    const offer = within(form).getByRole("button", { name: /Offer to 4 recipients/ });
    expect(offer).toBeDisabled();
    expect(offer).toHaveAccessibleDescription(/Enter a display name to enable/i);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(within(form).getByLabelText("Display name"), { target: { value: "synthetic-plan.md" } });
    within(form).getByRole("checkbox", { name: /Casey Example/ }).click();
    within(form).getByRole("button", { name: /Offer to 3 recipients/ }).click();
    const created = await within(files).findByRole("article", { name: "synthetic-plan.md" });
    expect(created).toHaveTextContent("Awaiting recipient consent");
    expect(created).toHaveTextContent("offered by you");
    expect(created).toHaveTextContent(/Consent pending/);
    expect(document.querySelector("input[type='file']")).toBeNull();
  });

  it("fails closed in the local loopback runtime with zero relationships, messages, and offers", async () => {
    renderPage(createUnavailableSocialHubPort(() => NOW), "local_real");
    const closedCopy = await screen.findByText("Social features are not served in this runtime");
    const closed = closedCopy.closest("[role='status']");
    expect(closed).not.toBeNull();
    expect(closed).toHaveTextContent("Social features are not served in this runtime");
    expect(closed).toHaveTextContent("0 friends · 0 relationships · 0 requests · 0 conversations · 0 messages · 0 file offers · presence not shared");
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("list", { name: "Conversations" })).toBeNull();
    expect(screen.queryByText(/Fictional synthetic demo/)).toBeNull();
    expect(screen.queryByRole("group", { name: /Your presence/ })).toBeNull();
    expect(screen.getByText(/Local runtime · no social service/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Example/);
    expect(document.body.textContent).not.toMatch(/Online|Offline|Away/);
  });

  it("makes presence an explicit coarse opt-in that is separate from analyzer activity and never shows not-shared as offline", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    const presence = screen.getByRole("group", { name: /Your presence · opt-in, coarse, self-declared/ });
    expect(presence).toHaveAttribute("data-presence-source", "self_declared_opt_in");
    expect(presence).toHaveTextContent(/never derived from analyzer activity/);
    expect(presence).toHaveTextContent(/“not shared” means a person has not opted in, which is not the same as offline/);
    const toggle = within(presence).getByRole("checkbox", { name: /Share a coarse presence level/ });
    const level = within(presence).getByRole("combobox", { name: "Level" });
    expect(toggle).toBeChecked();
    fireEvent.change(level, { target: { value: "away" } });
    await waitFor(() => expect(presence).toHaveTextContent(/Others currently see: Away/));
    // Finley has not opted in: rendered as "Presence not shared", never as offline.
    within(screen.getByRole("list", { name: "Conversations" })).getByRole("button", { name: /#fixture-guild/ }).click();
    await screen.findByRole("region", { name: "#fixture-guild" });
    const members = screen.getByRole("list", { name: "Conversation members" });
    const finley = within(members).getByText("Finley Example").closest("li")!;
    expect(finley).toHaveTextContent("Presence not shared");
    expect(finley).not.toHaveTextContent(/Offline/);
    expect(finley.querySelector(".ui-avatar")).toHaveAttribute("data-presence", "not_shared");
    // Turning sharing off is announced and shows "not shared" for me too.
    toggle.click();
    await waitFor(() => expect(presence).toHaveTextContent(/Others currently see: Presence not shared/));
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/not the same as offline/);
    expect(level).toBeDisabled();
    expect(level).toHaveValue("away");
    toggle.click();
    await waitFor(() => expect(presence).toHaveTextContent(/Others currently see: Away/));
    expect(level).toBeEnabled();
    expect(level).toHaveValue("away");
    // The friends tab labels presence as self-declared and not analyzer activity.
    within(screen.getByRole("tablist", { name: "Rail sections" })).getByRole("tab", { name: /Friends/ }).click();
    expect(await screen.findByText(/Presence · self-declared, coarse, opt-in · not analyzer activity/)).toBeInTheDocument();
  });

  it("defaults an unknown first presence opt-in to offline", async () => {
    const basePort = createSyntheticSocialHubPort();
    const base = createSyntheticSocialSnapshot();
    const snapshot = {
      ...base,
      people: base.people.map((person) => person.id === base.me_person_id
        ? { ...person, presence: { sharing: "not_shared" as const, level: null, source: "self_declared_opt_in" as const } }
        : person),
    };
    const port: SocialHubPort = { ...basePort, getSnapshot: async () => snapshot };
    renderPage(port);
    await ready();

    const presence = screen.getByRole("group", { name: /Your presence · opt-in, coarse, self-declared/ });
    const toggle = within(presence).getByRole("checkbox", { name: /Share a coarse presence level/ });
    const level = within(presence).getByRole("combobox", { name: "Level" });
    expect(toggle).not.toBeChecked();
    expect(level).toBeDisabled();
    expect(level).toHaveValue("offline");
    toggle.click();
    await waitFor(() => expect(presence).toHaveTextContent(/Others currently see: Offline/));
  });

  it("states the encryption, metadata, access, payload, transport, and data-control truths without offering fake controls", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    const summary = screen.getByRole("group", { name: "Local social state summary" });
    expect(summary).toHaveTextContent("Not end-to-end encrypted");
    expect(summary).toHaveTextContent("Invite-only groups · nothing discoverable");
    screen.getByRole("button", { name: /What this demo can and cannot promise/ }).click();
    const facts = await screen.findByLabelText("Social boundary facts");
    expect(facts).toHaveTextContent(/End-to-end encryption is not implemented in this demo/);
    expect(facts).toHaveTextContent(/relationship \(who talks to whom\), timing, availability, and size-class metadata/);
    expect(facts).toHaveTextContent(/never traverse or rest on it/);
    expect(facts).toHaveTextContent(/no public directory, no discoverable channel, and no join link/);
    expect(facts).toHaveTextContent(/never auto-inserts analyzer sessions, prompts, metrics, or explanations/);
    expect(facts).toHaveTextContent(/not inspection of text a person types/);
    expect(facts).toHaveTextContent(/no relay and no TURN/);
    expect(facts).toHaveTextContent(/No export or delete-my-data control is offered/);
    expect(screen.queryByRole("button", { name: /export|download my data|delete (my )?(account|data)/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /browse|discover|join|public/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /join|invite link/i })).toBeNull();
    expect(screen.queryByText(/^Public channel|Browse channels|Discover channels/i)).toBeNull();
    // Group headers and details say invite-only, never public.
    within(screen.getByRole("list", { name: "Conversations" })).getByRole("button", { name: /#fixture-guild/ }).click();
    const conversation = await screen.findByRole("region", { name: "#fixture-guild" });
    expect(conversation).toHaveTextContent("Invite-only group · not discoverable");
    expect(conversation).toHaveTextContent(/never auto-inserts analyzer sessions, prompts, metrics, or explanations/);
  });

  it("shows a truthful no-direct-path state for symmetric NAT/CGNAT and queues sender-offline offers on the sender's device", async () => {
    renderPage(createSyntheticSocialHubPort());
    await ready();
    within(screen.getByRole("list", { name: "Conversations" })).getByRole("button", { name: /Blake Example/ }).click();
    await screen.findByRole("region", { name: "Blake Example" });
    const files = screen.getByRole("region", { name: "Direct file sharing" });
    expect(files).toHaveTextContent(/no relay and no TURN/);
    const sketch = within(files).getByRole("article", { name: "synthetic-lane-sketch.svg" });
    expect(sketch).toHaveTextContent("No direct path · symmetric NAT/CGNAT");
    expect(sketch).toHaveTextContent(/No direct path \(CGNAT\) · no relay or TURN exists, so no bytes can move/);
    expect(within(sketch).getByRole("button", { name: /Resume \(no direct path\)/ })).toBeDisabled();
    expect(sketch).toHaveTextContent(/Blake Example: No direct path · CGNAT/);

    // Going offline keeps the offer form usable: the metadata offer is queued on this device.
    const presence = screen.getByRole("group", { name: /Your presence/ });
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(within(presence).getByRole("combobox", { name: "Level" }), { target: { value: "offline" } });
    const form = within(files).getByRole("form", { name: "Offer a file (metadata only)" });
    expect(form).toHaveTextContent(/queued on this device with a bounded expiry \(never on a server\)/);
    fireEvent.change(within(form).getByLabelText("Display name"), { target: { value: "synthetic-offline-notes.md" } });
    const submit = within(form).getByRole("button", { name: /Queue offer for 1 recipient/ });
    expect(submit).toBeEnabled();
    submit.click();
    const queued = await within(files).findByRole("article", { name: "synthetic-offline-notes.md" });
    expect(queued).toHaveTextContent("Queued on your device · you are not currently shared as online");
    expect(queued).toHaveTextContent(/never on a server/);
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/queued on this device because you are not currently shared as online/);
    // Back online: the queued offer becomes a live offer awaiting consent.
    fireEvent.change(within(presence).getByRole("combobox", { name: "Level" }), { target: { value: "online" } });
    await waitFor(() => expect(queued).toHaveTextContent("Awaiting recipient consent"));
    expect(document.querySelector("input[type='file']")).toBeNull();
  });

  it("never renders a private port failure and offers retry", async () => {
    const failing: SocialHubPort = {
      ...createSyntheticSocialHubPort(),
      async getCapabilities() {
        throw new Error(PRIVATE_CANARY);
      },
    };
    renderPage(failing);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/did not answer with a valid capability report/);
    expect(document.body.textContent).not.toContain(PRIVATE_CANARY);
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
