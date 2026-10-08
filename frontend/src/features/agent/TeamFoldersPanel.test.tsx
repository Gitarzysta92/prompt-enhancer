import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PeerLink, SharedFolder } from "../../shared/api/contracts";
import { TeamFoldersPanel } from "./TeamFoldersPanel";

/**
 * All fixtures are synthetic: loopback URLs, reserved D:/example paths and an
 * obviously fake token. No real host, identity, session or credential.
 */
const CREATED_AT = "2040-01-01T00:00:00Z";
const SYNTHETIC_TOKEN = "synthetic-example-share-token";
const RAW_DETAIL = "synthetic-internal-failure-detail";

const share = (overrides: Partial<SharedFolder> = {}): SharedFolder => ({
  contract_version: "shared-folders.v1",
  created_at: CREATED_AT,
  name: "example-team-docs",
  path: "D:/example/team/docs",
  share_id: "share-example-1",
  share_token: null,
  ...overrides,
});

const link = (overrides: Partial<PeerLink> = {}): PeerLink => ({
  contract_version: "shared-folders.v1",
  joined_at: CREATED_AT,
  link_id: "link-example-1",
  name: "example-team-docs",
  share_id: "share-example-1",
  target: "D:/example/team/docs-copy",
  url: "http://127.0.0.1:8765",
  ...overrides,
});

const shareList = (...entries: SharedFolder[]) => ({ contract_version: "shared-folders.v1" as const, shares: entries });
const linkList = (...entries: PeerLink[]) => ({ contract_version: "shared-folders.v1" as const, links: entries });

type Shares = ReturnType<typeof shareList>;
type Links = ReturnType<typeof linkList>;

/** Answers calls in order and repeats the last step afterwards. */
function sequence<T>(steps: Array<() => Promise<T>>) {
  let index = 0;
  return vi.fn(async () => {
    const step = steps[Math.min(index, steps.length - 1)];
    index += 1;
    return step();
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

const failing = <T,>() => (): Promise<T> => Promise.reject(new Error(RAW_DETAIL));

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TeamFoldersPanel", () => {
  it("reports a failed initial load instead of an empty list, and recovers on Retry", async () => {
    const listSharedFolders = sequence<Shares>([failing<Shares>(), async () => shareList(share())]);
    const listPeerLinks = sequence<Links>([async () => linkList()]);

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders }} />);

    await screen.findByText("The team folder list could not be loaded.");
    expect(screen.queryByText("You are not sharing any folder yet.")).toBeNull();
    expect(screen.queryByText(new RegExp(RAW_DETAIL))).toBeNull();

    fireEvent.click(button("Retry"));

    expect(await screen.findByText("example-team-docs")).toBeTruthy();
  });

  it("distinguishes a successful empty result from a failed load", async () => {
    const empty = render(
      <TeamFoldersPanel transport={{ listPeerLinks: sequence<Links>([async () => linkList()]), listSharedFolders: sequence<Shares>([async () => shareList()]) }} />,
    );

    await screen.findByText("You are not sharing any folder yet.");
    await screen.findByText("You have not joined any folder yet.");
    expect(screen.queryByRole("alert")).toBeNull();
    empty.unmount();

    render(
      <TeamFoldersPanel transport={{ listPeerLinks: sequence<Links>([async () => linkList()]), listSharedFolders: sequence<Shares>([failing<Shares>()]) }} />,
    );

    await screen.findByText("The team folder list could not be loaded.");
    expect(screen.queryByText("You are not sharing any folder yet.")).toBeNull();
  });

  it("keeps the last known list and labels it stale when a later refresh fails", async () => {
    const listSharedFolders = sequence<Shares>([async () => shareList(share()), failing<Shares>()]);
    const listPeerLinks = sequence<Links>([async () => linkList(link())]);

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders }} />);
    await screen.findByText("D:/example/team/docs");

    fireEvent.click(button("Refresh"));

    await screen.findByText(/last list loaded successfully/);
    expect(screen.getByText("D:/example/team/docs")).toBeTruthy();
    expect(screen.getByText("D:/example/team/docs-copy")).toBeTruthy();
  });

  it("disables every action the transport does not offer and explains why", async () => {
    const listSharedFolders = sequence<Shares>([async () => shareList(share())]);
    const listPeerLinks = sequence<Links>([async () => linkList(link())]);

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders }} onUseAsWorkspace={() => {}} />);
    await screen.findByText("D:/example/team/docs");

    for (const name of ["Share", "Stop sharing", "Join", "Pull", "Push", "Leave"]) {
      const control = button(name);
      expect(control.disabled).toBe(true);
      expect(String(control.getAttribute("title"))).toContain("unavailable in this session");
    }
  });

  it("shows the issued token once and keeps the created share when the follow-up refresh fails", async () => {
    const created = share({ name: "example-new-share", path: "D:/example/team/new", share_id: "share-example-2", share_token: SYNTHETIC_TOKEN });
    const shareFolder = vi.fn(async () => created);
    const listSharedFolders = sequence<Shares>([async () => shareList(), failing<Shares>()]);
    const listPeerLinks = sequence<Links>([async () => linkList()]);

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders, shareFolder }} />);
    await screen.findByText("You are not sharing any folder yet.");

    fireEvent.change(screen.getByLabelText("Folder to share (absolute path)"), { target: { value: "D:/example/team/new" } });
    fireEvent.change(screen.getByLabelText("Share name"), { target: { value: "example-new-share" } });
    fireEvent.click(button("Share"));

    await screen.findByText(SYNTHETIC_TOKEN);
    await screen.findByText("example-new-share");
    await screen.findByText(/last list loaded successfully/);
    expect(screen.getByText("D:/example/team/new").closest("li")?.textContent).not.toContain(SYNTHETIC_TOKEN);

    fireEvent.click(button("Retry"));

    await waitFor(() => expect(listSharedFolders).toHaveBeenCalledTimes(3));
    expect(shareFolder).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(SYNTHETIC_TOKEN)).toHaveLength(1);
  });

  it("does not promise a one-time token when the share receipt contains none", async () => {
    const created = share({ share_token: null });
    const shareFolder = vi.fn(async () => created);
    render(<TeamFoldersPanel transport={{
      listSharedFolders: sequence<Shares>([async () => shareList(), async () => shareList(created)]),
      listPeerLinks: sequence<Links>([async () => linkList()]), shareFolder,
    }} />);
    await screen.findByText("You are not sharing any folder yet.");
    fireEvent.change(screen.getByLabelText("Folder to share (absolute path)"), { target: { value: "D:/example/team/new" } });
    fireEvent.change(screen.getByLabelText("Share name"), { target: { value: "example-new-share" } });
    fireEvent.click(button("Share"));
    expect(await screen.findByText(/no join token was returned/)).toBeVisible();
    expect(screen.queryByText(/token is shown once, below/)).toBeNull();
    expect(shareFolder).toHaveBeenCalledOnce();
  });

  it("reports pull counts and maps a push failure to a safe message", async () => {
    const listSharedFolders = sequence<Shares>([async () => shareList()]);
    const listPeerLinks = sequence<Links>([async () => linkList(link())]);
    const pullPeerLink = vi.fn(async () => ({ conflicts: 0, contract_version: "shared-folders.v1" as const, link_id: "link-example-1", pulled: 3, pushed: 0, skipped: 1 }));
    const pushPeerLink = vi.fn(async () => { throw new Error(RAW_DETAIL); });

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders, pullPeerLink, pushPeerLink }} />);
    await screen.findByText("D:/example/team/docs-copy");

    fireEvent.click(button("Pull"));
    await screen.findByText("Pulled 3 files (1 unchanged).");
    expect(pullPeerLink).toHaveBeenCalledWith("link-example-1", expect.any(AbortSignal));

    fireEvent.click(button("Push"));
    await screen.findByText("The sync did not complete.");
    expect(screen.queryByText(new RegExp(RAW_DETAIL))).toBeNull();
  });

  it("serializes revoke and leave, then reflects both removals", async () => {
    const gate = deferred<void>();
    const revokeSharedFolder = vi.fn(() => gate.promise);
    const leavePeerLink = vi.fn(async () => {});
    const listSharedFolders = sequence<Shares>([async () => shareList(share()), async () => shareList()]);
    const listPeerLinks = sequence<Links>([async () => linkList(link()), async () => linkList(link()), async () => linkList()]);

    render(<TeamFoldersPanel transport={{ leavePeerLink, listPeerLinks, listSharedFolders, revokeSharedFolder }} />);
    await screen.findByText("D:/example/team/docs");

    fireEvent.click(button("Stop sharing"));
    fireEvent.click(button("Leave"));

    expect(leavePeerLink).not.toHaveBeenCalled();
    expect(button("Leave").disabled).toBe(true);

    await act(async () => { gate.resolve(); await gate.promise; });
    await waitFor(() => expect(screen.queryByText("D:/example/team/docs")).toBeNull());

    fireEvent.click(button("Leave"));

    await waitFor(() => expect(leavePeerLink).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("D:/example/team/docs-copy")).toBeNull());
  });

  it("ignores a stale refresh that resolves after a newer one", async () => {
    const slow = deferred<Shares>();
    const listSharedFolders = sequence<Shares>([
      () => slow.promise,
      async () => shareList(share({ name: "example-new-list", share_id: "share-example-3" })),
    ]);
    const listPeerLinks = sequence<Links>([async () => linkList()]);

    render(<TeamFoldersPanel transport={{ listPeerLinks, listSharedFolders }} />);

    fireEvent.click(button("Refresh"));
    await screen.findByText("example-new-list");

    await act(async () => {
      slow.resolve(shareList(share({ name: "example-stale-list", share_id: "share-example-4" })));
      await slow.promise;
    });

    expect(screen.queryByText("example-stale-list")).toBeNull();
    expect(screen.getByText("example-new-list")).toBeTruthy();
  });

  it("does not publish an old connection's pending share or token into a replacement connection", async () => {
    const pending = deferred<SharedFolder>();
    const shareFolder = vi.fn((_path: string, _name: string, _signal?: AbortSignal) => pending.promise);
    const first = { listSharedFolders: vi.fn(async () => shareList()), listPeerLinks: vi.fn(async () => linkList()), shareFolder };
    const second = { listSharedFolders: vi.fn(async () => shareList()), listPeerLinks: vi.fn(async () => linkList()), shareFolder: vi.fn() };
    const view = render(<TeamFoldersPanel transport={first} />);
    await screen.findByText("You are not sharing any folder yet.");
    fireEvent.change(screen.getByLabelText("Folder to share (absolute path)"), { target: { value: "D:/example/team/docs" } });
    fireEvent.change(screen.getByLabelText("Share name"), { target: { value: "example-pending-share" } });
    fireEvent.click(button("Share"));
    view.rerender(<TeamFoldersPanel transport={second} />);
    await screen.findByText("You are not sharing any folder yet.");
    await act(async () => { pending.resolve(share({ name: "example-pending-share", share_token: SYNTHETIC_TOKEN })); await pending.promise; });
    expect(shareFolder.mock.calls[0][2]?.aborted).toBe(true);
    expect(screen.queryByText(SYNTHETIC_TOKEN)).not.toBeInTheDocument();
    expect(screen.queryByText("example-pending-share", { selector: "strong" })).not.toBeInTheDocument();
    expect(first.listSharedFolders).toHaveBeenCalledTimes(1);
    expect(second.shareFolder).not.toHaveBeenCalled();
  });

  it("reports a successful push and conflict copies without automatically repeating the exchange", async () => {
    const pushPeerLink = vi.fn(async () => ({ contract_version: "shared-folders.v1" as const, link_id: "link-example-1", pulled: 0, pushed: 2, skipped: 1, conflicts: 1 }));
    render(<TeamFoldersPanel transport={{ listSharedFolders: vi.fn(async () => shareList()), listPeerLinks: vi.fn(async () => linkList(link())), pushPeerLink }} />);
    await screen.findByText("D:/example/team/docs-copy");
    fireEvent.click(button("Push"));
    expect(await screen.findByText("Pushed 2 files, 1 kept as conflict copies on the other side (1 unchanged).")).toBeVisible();
    expect(pushPeerLink).toHaveBeenCalledTimes(1);
  });

  it.each(["success", "failure"] as const)("settles a refresh interrupted by a pull %s without repeating the transfer", async (outcome) => {
    const slow = deferred<Shares>();
    const listSharedFolders = sequence<Shares>([
      async () => shareList(share()),
      () => slow.promise,
      async () => shareList(share()),
    ]);
    const listPeerLinks = vi.fn(async () => linkList(link()));
    const pullPeerLink = vi.fn(async () => {
      if (outcome === "failure") throw new Error(RAW_DETAIL);
      return { contract_version: "shared-folders.v1" as const, link_id: "link-example-1", pulled: 1, pushed: 0, skipped: 0, conflicts: 0 };
    });
    render(<TeamFoldersPanel transport={{ listSharedFolders, listPeerLinks, pullPeerLink }} />);
    await screen.findByText("D:/example/team/docs-copy");
    fireEvent.click(button("Refresh"));
    await screen.findByText("Loading the team folder lists...");
    fireEvent.click(button("Pull"));
    await screen.findByText(outcome === "success" ? "Pulled 1 file (0 unchanged)." : "The sync did not complete.");
    await waitFor(() => expect(listSharedFolders).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByText("Loading the team folder lists...")).not.toBeInTheDocument());
    expect(button("Pull")).toBeEnabled();
    expect(pullPeerLink).toHaveBeenCalledTimes(1);
    await act(async () => { slow.resolve(shareList(share({ name: "example-obsolete-share" }))); await slow.promise; });
    expect(screen.queryByText("example-obsolete-share")).not.toBeInTheDocument();
  });

  it("recovers list loading after a failed share interrupted the initial read", async () => {
    const slow = deferred<Shares>();
    const listSharedFolders = sequence<Shares>([() => slow.promise, async () => shareList(share())]);
    const listPeerLinks = vi.fn(async () => linkList());
    const shareFolder = vi.fn(async () => { throw new Error(RAW_DETAIL); });
    render(<TeamFoldersPanel transport={{ listSharedFolders, listPeerLinks, shareFolder }} />);
    fireEvent.change(screen.getByLabelText("Folder to share (absolute path)"), { target: { value: "D:/example/team/new" } });
    fireEvent.change(screen.getByLabelText("Share name"), { target: { value: "example-new-share" } });
    fireEvent.click(button("Share"));
    await screen.findByText("The folder could not be shared.");
    await screen.findByText("D:/example/team/docs");
    expect(screen.queryByText("Loading the team folder lists...")).not.toBeInTheDocument();
    expect(shareFolder).toHaveBeenCalledTimes(1);
    await act(async () => { slow.resolve(shareList()); await slow.promise; });
    expect(screen.getByText("D:/example/team/docs")).toBeVisible();
  });

  it("explains an absent listing capability without presenting forms that cannot be used", () => {
    render(<TeamFoldersPanel transport={{ listSharedFolders: vi.fn() }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Team folders are unavailable");
    expect(screen.queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
  });
});
