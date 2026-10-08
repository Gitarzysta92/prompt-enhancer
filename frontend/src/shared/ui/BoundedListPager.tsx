import { useEffect, useMemo, useState } from "react";

import "./BoundedListPager.css";

type PageState = {
  page: number;
  preferredIndex: number | null;
  resetKey: string;
};

export type BoundedListPage = {
  end: number;
  first: number;
  last: number;
  next: () => void;
  page: number;
  pageCount: number;
  previous: () => void;
  setPage: (page: number) => void;
  start: number;
  total: number;
};

function boundedPage(page: number, pageCount: number): number {
  return Math.max(0, Math.min(pageCount - 1, page));
}

export function useBoundedListPage({
  itemCount,
  pageSize,
  preferredIndex = null,
  resetKey,
}: {
  itemCount: number;
  pageSize: number;
  preferredIndex?: number | null;
  resetKey: string;
}): BoundedListPage {
  const safePageSize = Math.max(1, Math.floor(pageSize));
  const pageCount = Math.max(1, Math.ceil(itemCount / safePageSize));
  const preferredPage = preferredIndex === null || preferredIndex < 0
    ? 0
    : boundedPage(Math.floor(preferredIndex / safePageSize), pageCount);
  const [state, setState] = useState<PageState>(() => ({
    page: preferredPage,
    preferredIndex,
    resetKey,
  }));
  const identityChanged = state.resetKey !== resetKey
    || state.preferredIndex !== preferredIndex;
  const page = identityChanged
    ? preferredPage
    : boundedPage(state.page, pageCount);

  useEffect(() => {
    if (!identityChanged && state.page === page) return;
    setState({ page, preferredIndex, resetKey });
  }, [identityChanged, page, preferredIndex, resetKey, state.page]);

  const setPage = (next: number) => {
    setState({
      page: boundedPage(next, pageCount),
      preferredIndex,
      resetKey,
    });
  };
  const start = page * safePageSize;
  const end = Math.min(itemCount, start + safePageSize);

  return useMemo(() => ({
    end,
    first: itemCount === 0 ? 0 : start + 1,
    last: end,
    next: () => setPage(page + 1),
    page,
    pageCount,
    previous: () => setPage(page - 1),
    setPage,
    start,
    total: itemCount,
  }), [end, itemCount, page, pageCount, preferredIndex, resetKey, start]);
}

export function BoundedListPager({
  label,
  page,
}: {
  label: string;
  page: BoundedListPage;
}) {
  if (page.total <= 0 || page.pageCount <= 1) return null;
  return (
    <nav aria-label={label} className="bounded-list-pager">
      <button
        className="button button--ghost"
        disabled={page.page === 0}
        onClick={page.previous}
        type="button"
      >Earlier</button>
      <span aria-live="polite">
        Showing {page.first.toLocaleString("en-US")}–{page.last.toLocaleString("en-US")} of {page.total.toLocaleString("en-US")}
      </span>
      <button
        className="button button--ghost"
        disabled={page.page >= page.pageCount - 1}
        onClick={page.next}
        type="button"
      >Later</button>
    </nav>
  );
}
