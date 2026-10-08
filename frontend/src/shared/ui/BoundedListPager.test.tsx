import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { BoundedListPager, useBoundedListPage } from "./BoundedListPager";

function Harness({ initialPreferred = null }: { initialPreferred?: number | null }) {
  const [scope, setScope] = useState("alpha");
  const [preferred, setPreferred] = useState<number | null>(initialPreferred);
  const items = Array.from({ length: 125 }, (_, index) => `${scope}-${index}`);
  const page = useBoundedListPage({
    itemCount: items.length,
    pageSize: 25,
    preferredIndex: preferred,
    resetKey: scope,
  });
  return <>
    <button onClick={() => setScope("beta")} type="button">Change scope</button>
    <button onClick={() => setPreferred(119)} type="button">Select late item</button>
    <ul>{items.slice(page.start, page.end).map((item) => <li key={item}>{item}</li>)}</ul>
    <BoundedListPager label="Synthetic rows" page={page} />
  </>;
}

describe("BoundedListPager", () => {
  it("keeps the mounted page bounded and exposes exact navigation counts", () => {
    render(<Harness />);

    expect(screen.getAllByRole("listitem")).toHaveLength(25);
    expect(screen.getByText("Showing 1–25 of 125")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("alpha-25")).toBeInTheDocument();
    expect(screen.queryByText("alpha-0")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 26–50 of 125")).toBeInTheDocument();
  });

  it("moves to a newly selected item and resets synchronously with its scope", () => {
    render(<Harness initialPreferred={52} />);

    expect(screen.getByText("alpha-52")).toBeInTheDocument();
    expect(screen.getByText("Showing 51–75 of 125")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select late item" }));
    expect(screen.getByText("alpha-119")).toBeInTheDocument();
    expect(screen.getByText("Showing 101–125 of 125")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change scope" }));
    expect(screen.getByText("beta-119")).toBeInTheDocument();
    expect(screen.queryByText("alpha-119")).not.toBeInTheDocument();
  });
});
