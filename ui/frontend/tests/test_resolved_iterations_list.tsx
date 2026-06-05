// ResolvedIterationsList renders past iterations newest-first with
// novelty/critique badges, the topic, and a click handler that surfaces
// the selected iteration id to the parent so JournalScroll can load it.
//
// Beyond the original render/select/empty contract these tests cover the
// client-side bounding added on top of the unbounded endpoint: pagination
// (default 10 rows/page), composable filters (novelty class, critique
// verdict, free-text topic search over seed.topic), the "showing X of Y"
// count, and the poll-does-not-reset-the-user's-view invariant.
import {
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import { ITERATIONS_FIXTURE } from "../src/fixtures/loop_v0";
import type { IterationRecord } from "../src/types/schemas";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PAGE_SIZE = 10;

// Build N synthetic rows, newest-first by ended_at, cycling through the
// novelty/verdict classes so filters have something to bite on.
function makeRows(n: number): IterationRecord[] {
  const novelties = ["novel", "rediscovery", "unclear", "nonsense"] as const;
  const verdicts = ["survives", "restated", "falsified", "malformed"] as const;
  return Array.from({ length: n }, (_, i) => {
    // newest first: row 0 has the latest timestamp
    const day = String(28 - (i % 28)).padStart(2, "0");
    return {
      iteration_id: `iter-${String(i).padStart(3, "0")}`,
      started_at: `2026-05-${day}T10:00:00Z`,
      ended_at: `2026-05-${day}T10:05:00Z`,
      seed: { topic: `topic alpha ${i}`, source: "human" },
      novelty: { class: novelties[i % 4] },
      critique: { verdict: verdicts[i % 4] },
      journal_entry_path: `journal/iterations/${i}.md`,
    } satisfies IterationRecord;
  });
}

// Count rendered journal-row buttons (excludes filter/pager controls).
function visibleRowCount(): number {
  return screen.queryAllByRole("button", { name: /^load journal / }).length;
}

describe("ResolvedIterationsList — original contract", () => {
  it("renders rows with id, topic, novelty and verdict badges", () => {
    render(<ResolvedIterationsList initial={ITERATIONS_FIXTURE} />);
    for (const row of ITERATIONS_FIXTURE) {
      expect(screen.getByText(row.iteration_id)).toBeInTheDocument();
      if (row.seed?.topic) {
        expect(screen.getByText(row.seed.topic)).toBeInTheDocument();
      }
    }
    // Badge text values (e.g. "novel"/"rediscovery") also appear as <option>
    // labels in the filter selects, so scope these assertions to the row list.
    const list = within(screen.getByRole("list"));
    expect(list.getByText("rediscovery")).toBeInTheDocument();
    expect(list.getByText("novel")).toBeInTheDocument();
    expect(list.getByText("nonsense")).toBeInTheDocument();
    expect(list.getByText("survives")).toBeInTheDocument();
    expect(list.getByText("restated")).toBeInTheDocument();
  });

  it("invokes onSelect with the iteration id when a row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ResolvedIterationsList
        initial={ITERATIONS_FIXTURE}
        onSelect={onSelect}
      />,
    );
    const button = screen.getByLabelText(/load journal iter-2026-05-26-001/);
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledWith("iter-2026-05-26-001");
  });

  it("highlights the selected row", () => {
    render(
      <ResolvedIterationsList
        initial={ITERATIONS_FIXTURE}
        selectedId="iter-2026-05-26-001"
      />,
    );
    const btn = screen.getByLabelText(/load journal iter-2026-05-26-001/);
    expect(btn.className).toMatch(/emerald/);
  });

  it("shows the empty-state message when no iterations have completed yet", () => {
    render(<ResolvedIterationsList initial={[]} />);
    expect(screen.getByText(/No iterations yet/)).toBeInTheDocument();
  });
});

describe("ResolvedIterationsList — count", () => {
  it("shows the bare total with no filter active", () => {
    render(<ResolvedIterationsList initial={makeRows(23)} />);
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("23");
  });

  it("shows 'X of Y' when a filter narrows the set", () => {
    // 23 rows, classes cycle every 4 → "novel" appears at i=0,4,8,... → 6 rows
    render(<ResolvedIterationsList initial={makeRows(23)} />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("6 of 23");
  });
});

describe("ResolvedIterationsList — filtering", () => {
  it("filters by novelty class", () => {
    render(<ResolvedIterationsList initial={makeRows(8)} />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "nonsense" },
    });
    // i % 4 === 3 → i=3,7 → 2 rows
    expect(visibleRowCount()).toBe(2);
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("2 of 8");
  });

  it("filters by critique verdict", () => {
    render(<ResolvedIterationsList initial={makeRows(8)} />);
    fireEvent.change(screen.getByLabelText("filter by critique verdict"), {
      target: { value: "survives" },
    });
    // i % 4 === 0 → i=0,4 → 2 rows
    expect(visibleRowCount()).toBe(2);
  });

  it("filters by free-text topic search over seed.topic", () => {
    const rows = makeRows(6);
    rows[2].seed = { topic: "unique beauty contest topic", source: "human" };
    render(<ResolvedIterationsList initial={rows} />);
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "beauty" },
    });
    expect(visibleRowCount()).toBe(1);
    expect(
      screen.getByText("unique beauty contest topic"),
    ).toBeInTheDocument();
  });

  it("topic search is case-insensitive", () => {
    const rows = makeRows(6);
    rows[1].seed = { topic: "Nash Equilibrium", source: "human" };
    render(<ResolvedIterationsList initial={rows} />);
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "nash" },
    });
    expect(visibleRowCount()).toBe(1);
  });

  it("composes filters across all three dimensions", () => {
    const rows = makeRows(16);
    // novelty 'novel' is i % 4 === 0 → i=0,4,8,12 (verdict 'survives' too).
    // Give i=8 a distinctive topic so the conjunction lands on exactly it.
    rows[8].seed = { topic: "needle in the haystack", source: "human" };
    render(<ResolvedIterationsList initial={rows} />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    fireEvent.change(screen.getByLabelText("filter by critique verdict"), {
      target: { value: "survives" },
    });
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "needle" },
    });
    expect(visibleRowCount()).toBe(1);
    expect(screen.getByText("needle in the haystack")).toBeInTheDocument();
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("1 of 16");
  });

  it("shows an empty-filter message (not the no-iterations message) when nothing matches", () => {
    render(<ResolvedIterationsList initial={makeRows(8)} />);
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "zzz-no-such-topic" },
    });
    expect(screen.getByTestId("resolved-empty-filter")).toBeInTheDocument();
    expect(screen.queryByText(/No iterations yet/)).not.toBeInTheDocument();
    expect(visibleRowCount()).toBe(0);
  });

  it("clears all filters with the reset control", () => {
    render(<ResolvedIterationsList initial={makeRows(8)} />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "nonsense" },
    });
    expect(visibleRowCount()).toBe(2);
    fireEvent.click(screen.getByLabelText("clear filters"));
    expect(visibleRowCount()).toBe(8);
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("8");
  });
});

describe("ResolvedIterationsList — pagination", () => {
  it("caps the first page at the default page size and shows a pager", () => {
    render(<ResolvedIterationsList initial={makeRows(23)} />);
    expect(visibleRowCount()).toBe(PAGE_SIZE);
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 3",
    );
    // newest-first: first page leads with iter-000, last visible is iter-009
    expect(screen.getByText("iter-000")).toBeInTheDocument();
    expect(screen.queryByText("iter-010")).not.toBeInTheDocument();
  });

  it("does not render a pager when rows fit on one page", () => {
    render(<ResolvedIterationsList initial={makeRows(7)} />);
    expect(screen.queryByTestId("resolved-pager")).not.toBeInTheDocument();
    expect(visibleRowCount()).toBe(7);
  });

  it("disables prev on the first page and next on the last page", () => {
    render(<ResolvedIterationsList initial={makeRows(23)} />);
    expect(screen.getByLabelText("previous page")).toBeDisabled();
    expect(screen.getByLabelText("next page")).not.toBeDisabled();
    // walk to the last page (3 pages → click next twice)
    fireEvent.click(screen.getByLabelText("next page"));
    fireEvent.click(screen.getByLabelText("next page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 3 of 3",
    );
    // last page has 23 - 20 = 3 rows
    expect(visibleRowCount()).toBe(3);
    expect(screen.getByLabelText("next page")).toBeDisabled();
    expect(screen.getByLabelText("previous page")).not.toBeDisabled();
  });

  it("navigates to the next page newest-first", () => {
    render(<ResolvedIterationsList initial={makeRows(23)} />);
    fireEvent.click(screen.getByLabelText("next page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 3",
    );
    expect(screen.getByText("iter-010")).toBeInTheDocument();
    expect(screen.queryByText("iter-009")).not.toBeInTheDocument();
  });

  it("pagination applies to the FILTERED set", () => {
    // 50 rows; 'novel' (i % 4 === 0) → 13 rows → 2 pages of the filtered set
    render(<ResolvedIterationsList initial={makeRows(50)} />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("13 of 50");
    expect(visibleRowCount()).toBe(PAGE_SIZE);
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 2",
    );
    fireEvent.click(screen.getByLabelText("next page"));
    expect(visibleRowCount()).toBe(3); // 13 - 10
  });

  it("resets to the first page when a filter is applied", () => {
    render(<ResolvedIterationsList initial={makeRows(50)} />);
    fireEvent.click(screen.getByLabelText("next page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 5",
    );
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 2",
    );
  });

  it("handles page size > number of rows (single page, no pager)", () => {
    render(<ResolvedIterationsList initial={makeRows(3)} />);
    expect(visibleRowCount()).toBe(3);
    expect(screen.queryByTestId("resolved-pager")).not.toBeInTheDocument();
  });

  it("shows no pager at exactly PAGE_SIZE rows but a pager at PAGE_SIZE+1", () => {
    // strict threshold: filteredCount > PAGE_SIZE
    const exact = render(<ResolvedIterationsList initial={makeRows(PAGE_SIZE)} />);
    expect(screen.queryByTestId("resolved-pager")).not.toBeInTheDocument();
    expect(visibleRowCount()).toBe(PAGE_SIZE);
    exact.unmount();

    render(<ResolvedIterationsList initial={makeRows(PAGE_SIZE + 1)} />);
    expect(screen.getByTestId("resolved-pager")).toBeInTheDocument();
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 2",
    );
    expect(visibleRowCount()).toBe(PAGE_SIZE);
  });

  it("handles an empty filtered result on what was a later page", () => {
    render(<ResolvedIterationsList initial={makeRows(50)} />);
    fireEvent.click(screen.getByLabelText("next page")); // page 2
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "no-match-anywhere" },
    });
    expect(screen.getByTestId("resolved-empty-filter")).toBeInTheDocument();
    expect(visibleRowCount()).toBe(0);
    expect(screen.queryByTestId("resolved-pager")).not.toBeInTheDocument();
  });
});

describe("ResolvedIterationsList — selection across filter/page", () => {
  it("surfaces the selected row when a filter hides it", () => {
    const rows = makeRows(8);
    // select iter-003 (nonsense); filter to 'novel' which excludes it
    render(
      <ResolvedIterationsList initial={rows} selectedId="iter-003" />,
    );
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    const banner = screen.getByTestId("resolved-selected-hidden");
    expect(banner).toBeInTheDocument();
    expect(within(banner).getByText("iter-003")).toBeInTheDocument();
  });

  it("surfaces the selected row when pagination pages it out", () => {
    render(
      <ResolvedIterationsList initial={makeRows(23)} selectedId="iter-015" />,
    );
    // iter-015 is on page 2; we're on page 1 → hidden banner shows
    expect(screen.getByTestId("resolved-selected-hidden")).toBeInTheDocument();
  });

  it("does not show the hidden banner when the selected row is visible", () => {
    render(
      <ResolvedIterationsList initial={makeRows(23)} selectedId="iter-002" />,
    );
    expect(
      screen.queryByTestId("resolved-selected-hidden"),
    ).not.toBeInTheDocument();
  });

  it("the hidden-selection banner can clear the filter to reveal the row", () => {
    const rows = makeRows(8);
    render(<ResolvedIterationsList initial={rows} selectedId="iter-003" />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    const banner = screen.getByTestId("resolved-selected-hidden");
    // filter-excluded case offers a 'clear filters' action
    fireEvent.click(within(banner).getByText("clear filters"));
    expect(
      screen.queryByTestId("resolved-selected-hidden"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(/load journal iter-003/)).toBeInTheDocument();
  });

  it("distinguishes the filter-excluded banner copy from the paged-out copy", () => {
    // No filter active, selected row is on another page → 'on another page' copy
    const pagedOut = render(
      <ResolvedIterationsList initial={makeRows(23)} selectedId="iter-015" />,
    );
    expect(
      within(screen.getByTestId("resolved-selected-hidden")).getByText(
        /on another page/,
      ),
    ).toBeInTheDocument();
    pagedOut.unmount();

    // A filter excludes the selected row → 'hidden by the current filter' copy
    render(<ResolvedIterationsList initial={makeRows(8)} selectedId="iter-003" />);
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(
      within(screen.getByTestId("resolved-selected-hidden")).getByText(
        /hidden by the current filter/,
      ),
    ).toBeInTheDocument();
  });

  it("the paged-out banner's 'go to selected' navigates to the row's page (no filter)", () => {
    // 25 rows, no filter, select iter-022 which lives on page 3.
    render(
      <ResolvedIterationsList initial={makeRows(25)} selectedId="iter-022" />,
    );
    // we start on page 1; the row is hidden and the banner offers a jump.
    const banner = screen.getByTestId("resolved-selected-hidden");
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 3",
    );
    expect(
      screen.queryByLabelText(/load journal iter-022/),
    ).not.toBeInTheDocument();
    fireEvent.click(within(banner).getByText("go to selected"));
    // jump lands on page 3 and the previously-hidden row is now rendered.
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 3 of 3",
    );
    expect(screen.getByLabelText(/load journal iter-022/)).toBeInTheDocument();
    expect(
      screen.queryByTestId("resolved-selected-hidden"),
    ).not.toBeInTheDocument();
  });

  it("'go to selected' respects the active filter when the row survives it", () => {
    // 50 rows; filter to 'novel' (13 rows over 2 pages). iter-048 is novel
    // (48 % 4 === 0) and lands on filtered page 2. Selecting it while on page 1
    // should let the banner jump within the FILTERED set, not clear the filter.
    render(
      <ResolvedIterationsList initial={makeRows(50)} selectedId="iter-048" />,
    );
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    const banner = screen.getByTestId("resolved-selected-hidden");
    fireEvent.click(within(banner).getByText("go to selected"));
    // filter is still 'novel' and the row is now visible on filtered page 2.
    expect(
      (screen.getByLabelText("filter by novelty class") as HTMLSelectElement)
        .value,
    ).toBe("novel");
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 2",
    );
    expect(screen.getByLabelText(/load journal iter-048/)).toBeInTheDocument();
  });
});

describe("ResolvedIterationsList — preserved badges + null-safety", () => {
  it("renders the process_status pid badge and keeps it under filtering", () => {
    const rows = makeRows(8);
    // give a 'novel' row (i=0) a running process so it survives a 'novel' filter
    rows[0] = { ...rows[0], process_status: "running" };
    // give a 'nonsense' row (i=3) an error process, excluded by the filter
    rows[3] = { ...rows[3], process_status: "exited_error_1" };
    render(<ResolvedIterationsList initial={rows} />);
    // both badges visible before filtering
    expect(screen.getByText("pid running")).toBeInTheDocument();
    expect(screen.getByText("pid err 1")).toBeInTheDocument();
    // filter to 'novel' → only iter-000 survives, its pid badge persists,
    // the excluded row's badge is gone.
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(visibleRowCount()).toBe(2); // i=0,4 are novel
    expect(screen.getByText("pid running")).toBeInTheDocument();
    expect(screen.queryByText("pid err 1")).not.toBeInTheDocument();
  });

  it("tolerates rows with missing ended_at and missing novelty/critique", () => {
    const rows: IterationRecord[] = [
      {
        iteration_id: "iter-bare",
        started_at: "2026-05-28T10:00:00Z",
        ended_at: "",
        seed: { topic: "bare row", source: "human" },
        journal_entry_path: "journal/iterations/bare.md",
      } as IterationRecord,
      ...makeRows(3),
    ];
    render(<ResolvedIterationsList initial={rows} />);
    // the bare row renders (no crash) and shows the em-dash timestamp.
    expect(screen.getByLabelText(/load journal iter-bare/)).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    // a novelty filter only matches rows that carry that class; the bare row
    // (undefined novelty) is excluded rather than throwing.
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    expect(
      screen.queryByLabelText(/load journal iter-bare/),
    ).not.toBeInTheDocument();
  });
});

describe("ResolvedIterationsList — poll does not reset the user's view", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("a poll refresh preserves the active filter and current page", async () => {
    // Polling path (no `initial`) — mock the http call.
    const http = await import("../src/api/http");
    const first = makeRows(50);
    // A later poll returns one extra (newest) row prepended.
    const extra: IterationRecord = {
      iteration_id: "iter-NEW",
      started_at: "2026-05-29T10:00:00Z",
      ended_at: "2026-05-29T10:05:00Z",
      seed: { topic: "brand new topic", source: "human" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/new.md",
    };
    const spy = vi
      .spyOn(http, "getIterations")
      .mockResolvedValueOnce({ iterations: first })
      .mockResolvedValue({ iterations: [extra, ...first] });

    render(<ResolvedIterationsList pollMs={1000} />);
    // flush the initial load
    await vi.advanceTimersByTimeAsync(0);

    // user filters to 'novel' and moves to page 2
    fireEvent.change(screen.getByLabelText("filter by novelty class"), {
      target: { value: "novel" },
    });
    fireEvent.click(screen.getByLabelText("next page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 2",
    );

    // a poll fires; advance again to flush the resolved-promise microtasks so
    // the new rows render before we assert.
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(2);

    // filter is still 'novel' and the page index did not reset to 1
    expect(
      (screen.getByLabelText("filter by novelty class") as HTMLSelectElement)
        .value,
    ).toBe("novel");
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 2",
    );
    // count reflects the new total (51) under the same filter (14 novel now)
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("14 of 51");
  });

  it("a poll that SHRINKS the set clamps the page and prev recovers in one click", async () => {
    const http = await import("../src/api/http");
    const first = makeRows(50); // 5 pages
    const shrunk = makeRows(50).slice(0, 5); // 1 page after the poll
    const spy = vi
      .spyOn(http, "getIterations")
      .mockResolvedValueOnce({ iterations: first })
      .mockResolvedValue({ iterations: shrunk });

    render(<ResolvedIterationsList pollMs={1000} />);
    await vi.advanceTimersByTimeAsync(0);

    // walk to the last page (page 5) before the shrink.
    fireEvent.click(screen.getByLabelText("next page"));
    fireEvent.click(screen.getByLabelText("next page"));
    fireEvent.click(screen.getByLabelText("next page"));
    fireEvent.click(screen.getByLabelText("next page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 5 of 5",
    );

    // poll shrinks to a single page; safePage clamps to page 1.
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(0);
    expect(spy).toHaveBeenCalledTimes(2);
    // only one page now → the pager is gone and exactly 5 rows show.
    expect(screen.queryByTestId("resolved-pager")).not.toBeInTheDocument();
    expect(visibleRowCount()).toBe(5);
  });

  it("a poll that shrinks to a few pages leaves prev immediately effective (no dead clicks)", async () => {
    const http = await import("../src/api/http");
    const first = makeRows(50); // 5 pages
    const shrunk = makeRows(50).slice(0, 15); // 2 pages after the poll
    vi.spyOn(http, "getIterations")
      .mockResolvedValueOnce({ iterations: first })
      .mockResolvedValue({ iterations: shrunk });

    render(<ResolvedIterationsList pollMs={1000} />);
    await vi.advanceTimersByTimeAsync(0);

    // go to page 5 of the large set.
    for (let i = 0; i < 4; i++) {
      fireEvent.click(screen.getByLabelText("next page"));
    }
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 5 of 5",
    );

    // shrink to 2 pages; safePage clamps to page 2 (the new last page).
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 2 of 2",
    );
    // a SINGLE prev click must move to page 1 — proving the button is driven
    // off the clamped safePage, not the stale raw page (which was 4).
    fireEvent.click(screen.getByLabelText("previous page"));
    expect(screen.getByTestId("resolved-page-indicator")).toHaveTextContent(
      "page 1 of 2",
    );
  });

  it("preserves the topic input value and focus across a background poll", async () => {
    const http = await import("../src/api/http");
    const first = makeRows(6);
    const extra: IterationRecord = {
      iteration_id: "iter-NEW",
      started_at: "2026-05-29T10:00:00Z",
      ended_at: "2026-05-29T10:05:00Z",
      seed: { topic: "brand new topic", source: "human" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/new.md",
    };
    vi.spyOn(http, "getIterations")
      .mockResolvedValueOnce({ iterations: first })
      .mockResolvedValue({ iterations: [extra, ...first] });

    render(<ResolvedIterationsList pollMs={1000} />);
    await vi.advanceTimersByTimeAsync(0);

    const input = screen.getByLabelText("search topic") as HTMLInputElement;
    input.focus();
    fireEvent.change(input, { target: { value: "alpha" } });
    expect(input).toHaveFocus();

    // poll fires and prepends a row; the controlled input keeps its value and
    // the element keeps focus (it's a stable node, not remounted).
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(0);
    const after = screen.getByLabelText("search topic") as HTMLInputElement;
    expect(after.value).toBe("alpha");
    expect(after).toHaveFocus();
  });

  it("re-sorts out-of-order ended_at returned by a poll (newest first)", async () => {
    const http = await import("../src/api/http");
    // backend returns rows OUT of order: an older row first, newer row second.
    const older: IterationRecord = {
      iteration_id: "iter-OLD",
      started_at: "2026-05-20T10:00:00Z",
      ended_at: "2026-05-20T10:05:00Z",
      seed: { topic: "older", source: "human" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/old.md",
    };
    const newer: IterationRecord = {
      iteration_id: "iter-NEW",
      started_at: "2026-05-30T10:00:00Z",
      ended_at: "2026-05-30T10:05:00Z",
      seed: { topic: "newer", source: "human" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/new.md",
    };
    vi.spyOn(http, "getIterations").mockResolvedValue({
      iterations: [older, newer], // deliberately not newest-first
    });

    render(<ResolvedIterationsList pollMs={1000} />);
    await vi.advanceTimersByTimeAsync(0);

    // the component sorts by ended_at desc, so the newer row renders first.
    const buttons = screen.getAllByRole("button", {
      name: /^load journal iter-(OLD|NEW)/,
    });
    expect(buttons[0]).toHaveAccessibleName(/iter-NEW/);
    expect(buttons[1]).toHaveAccessibleName(/iter-OLD/);
  });
});
