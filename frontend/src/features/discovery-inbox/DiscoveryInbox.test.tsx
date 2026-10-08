import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { DiscoveryInbox } from "./DiscoveryInbox";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

describe("DiscoveryInbox", () => {
  it("shows only the retryable error when the initial candidate load fails", async () => {
    const transport = createSyntheticTransport();
    transport.listCandidates = vi.fn(async () => {
      throw new Error("Synthetic candidate service unavailable");
    });

    render(
      <DiscoveryInbox
        navigate={vi.fn()}
        onUndecidedCountChange={vi.fn()}
        transport={transport}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic candidate service unavailable");
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Nothing in this view" })).toBeNull();
  });

  it("ignores an aborted initial failure after a newer filter load succeeds", async () => {
    const transport = createSyntheticTransport();
    const reviewedResponse = await transport.listCandidates("decided");
    const undecidedResponse = await transport.listCandidates("undecided");
    const initial = deferred<typeof undecidedResponse>();
    let firstUndecided = true;
    let initialSignal: AbortSignal | undefined;
    transport.listCandidates = vi.fn((status = "all", signal?: AbortSignal) => {
      if (status === "undecided" && firstUndecided) {
        firstUndecided = false;
        initialSignal = signal;
        return initial.promise;
      }
      return Promise.resolve(status === "decided" ? reviewedResponse : undecidedResponse);
    });

    render(
      <DiscoveryInbox
        navigate={vi.fn()}
        onUndecidedCountChange={vi.fn()}
        transport={transport}
      />,
    );
    await waitFor(() => expect(transport.listCandidates).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Reviewed" }));
    expect(await screen.findByRole("button", { name: /Candidate cccccc/ })).toBeVisible();
    expect(initialSignal?.aborted).toBe(true);

    await act(async () => {
      initial.reject(new Error("late synthetic failure"));
      await initial.promise.catch(() => undefined);
    });
    expect(screen.getByRole("button", { name: /Candidate cccccc/ })).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("loads the undecided review queue and supports merge selection", async () => {
    const onUndecidedCountChange = vi.fn();
    render(
      <DiscoveryInbox
        navigate={vi.fn()}
        onUndecidedCountChange={onUndecidedCountChange}
        transport={createSyntheticTransport()}
      />,
    );

    expect(await screen.findByRole("button", { name: /Candidate aaaaaa/ })).toBeVisible();
    expect(onUndecidedCountChange).toHaveBeenLastCalledWith(2);
    expect(screen.getByRole("button", { name: /Candidate bbbbbb/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Reviewed" }));
    expect(await screen.findByRole("button", { name: /Candidate cccccc/ })).toBeVisible();
    await waitFor(() =>
      expect(onUndecidedCountChange).toHaveBeenLastCalledWith(2),
    );
    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    expect(await screen.findByRole("button", { name: /Candidate aaaaaa/ })).toBeVisible();
    expect(onUndecidedCountChange).toHaveBeenLastCalledWith(2);

    const mergeBeforeSelection = screen.getByRole("button", { name: "Merge selected" });
    expect(mergeBeforeSelection).toBeDisabled();
    expect(mergeBeforeSelection).toHaveAccessibleDescription(/select at least two candidates/i);

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    const merge = screen.getByRole("button", { name: "Merge selected" });
    expect(merge).toBeEnabled();
    expect(merge).toHaveAccessibleDescription(/ready to review as one merge/i);
    fireEvent.click(merge);

    await waitFor(() =>
      expect(screen.getByText(/merge decision saved/i)).toBeVisible(),
    );
    await waitFor(() =>
      expect(onUndecidedCountChange).toHaveBeenLastCalledWith(0),
    );
  });
});
