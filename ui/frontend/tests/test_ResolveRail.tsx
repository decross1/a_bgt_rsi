// ResolveRail (Part C) — the persistent right-side navigator for the /todo
// cockpit backlog. These tests pin the contract (rule 4 — no coerced near-miss):
//   - GROUP BY KIND with counts (gate_verdict -> gate-verdicts, finding_review
//     -> findings, else -> other);
//   - NEAR-DUP CLUSTERING: a set of long-shared-prefix titles collapses into ONE
//     cluster with the right ×N count and expands to its members; distinct
//     titles stay separate singletons;
//   - FILTER + SEARCH narrow the visible rows (by title AND by id); an empty
//     result is legible;
//   - SELECTION: clicking a row fires onSelect(id); the selectedId row is marked;
//   - ROBUSTNESS: hostile items (missing id / object title / null) neither crash
//     nor leak "[object Object]".
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolveRail from "../src/components/todo/ResolveRail";
import type { HumanTodoItem } from "../src/types/schemas";

afterEach(() => cleanup());

// Five findings whose titles share a long common prefix (the cron's near-dups)
// + one distinct finding singleton, two distinct gate-verdicts, one "other".
const CLUSTER_PREFIX =
  "In repeated public goods games with noisy contribution observation";
const ITEMS: HumanTodoItem[] = [
  { kind: "gate_verdict", id: "gv-1", title: "Iteration loop_v0_a sign-off" },
  { kind: "gate_verdict", id: "gv-2", title: "Iteration loop_v0_b sign-off" },
  { kind: "finding_review", id: "fc-1", title: `${CLUSTER_PREFIX}, variant one` },
  { kind: "finding_review", id: "fc-2", title: `${CLUSTER_PREFIX}, variant two` },
  { kind: "finding_review", id: "fc-3", title: `${CLUSTER_PREFIX}, variant three` },
  { kind: "finding_review", id: "fc-4", title: `${CLUSTER_PREFIX}, variant four` },
  { kind: "finding_review", id: "fc-5", title: `${CLUSTER_PREFIX}, variant five` },
  {
    kind: "finding_review",
    id: "fs-1",
    title: "Under asymmetric information, sealed-bid auctions overbid",
  },
  { kind: "bubble_unacked", id: "ob-1", title: "Coordinator bubble: cycle 3 raised" },
];

function noop() {
  /* selection sink */
}

describe("ResolveRail — grouping", () => {
  it("groups items by kind with per-group counts", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);
    expect(screen.getByTestId("resolve-rail")).toBeInTheDocument();

    // gate_verdict -> "gate-verdicts" group, 2 items.
    expect(screen.getByTestId("resolve-group-iteration")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-group-count-iteration")).toHaveTextContent("2");
    // finding_review -> "findings" group, 6 items (5 clustered + 1 singleton).
    expect(screen.getByTestId("resolve-group-finding")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-group-count-finding")).toHaveTextContent("6");
    // everything else -> "other" group, 1 item.
    expect(screen.getByTestId("resolve-group-other")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-group-count-other")).toHaveTextContent("1");

    // The rail's total badge reflects all (coerced) open items.
    expect(screen.getByTestId("resolve-rail-total")).toHaveTextContent("9");
  });
});

describe("ResolveRail — near-dup clustering", () => {
  it("collapses long-shared-prefix titles into one ×N cluster and expands to members", () => {
    const onSelect = vi.fn();
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={onSelect} />);

    // The 5 near-dups collapse into ONE cluster (rep = first member fc-1) with a
    // ×5 badge; collapsed, the members are NOT in the DOM.
    const header = screen.getByTestId("resolve-cluster-header-fc-1");
    expect(header).toBeInTheDocument();
    expect(screen.getByTestId("resolve-cluster-count-fc-1")).toHaveTextContent("×5");
    expect(screen.queryByTestId("resolve-row-fc-1")).toBeNull();
    expect(screen.queryByTestId("resolve-row-fc-5")).toBeNull();

    // Clicking the header EXPANDS (it does not select).
    fireEvent.click(header);
    expect(onSelect).not.toHaveBeenCalled();
    for (const id of ["fc-1", "fc-2", "fc-3", "fc-4", "fc-5"]) {
      expect(screen.getByTestId(`resolve-row-${id}`)).toBeInTheDocument();
    }
  });

  it("keeps distinct titles as separate singletons (no false merge)", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);

    // The two distinct gate-verdicts are singletons, not a cluster.
    expect(screen.getByTestId("resolve-row-gv-1")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-row-gv-2")).toBeInTheDocument();
    expect(screen.queryByTestId("resolve-cluster-gv-1")).toBeNull();
    // The distinct finding sits beside the cluster as its own singleton.
    expect(screen.getByTestId("resolve-row-fs-1")).toBeInTheDocument();
  });
});

describe("ResolveRail — filter + search", () => {
  it("search narrows by title", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);
    fireEvent.change(screen.getByTestId("resolve-search"), {
      target: { value: "asymmetric" },
    });
    expect(screen.getByTestId("resolve-row-fs-1")).toBeInTheDocument();
    expect(screen.queryByTestId("resolve-cluster-fc-1")).toBeNull();
    expect(screen.queryByTestId("resolve-row-gv-1")).toBeNull();
  });

  it("search narrows by id", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);
    fireEvent.change(screen.getByTestId("resolve-search"), {
      target: { value: "gv-2" },
    });
    expect(screen.getByTestId("resolve-row-gv-2")).toBeInTheDocument();
    expect(screen.queryByTestId("resolve-row-gv-1")).toBeNull();
    expect(screen.queryByTestId("resolve-group-finding")).toBeNull();
  });

  it("shows a legible empty state when nothing matches", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);
    fireEvent.change(screen.getByTestId("resolve-search"), {
      target: { value: "zzz-no-such-item" },
    });
    expect(screen.getByTestId("resolve-rail-empty")).toHaveTextContent(/no items match/i);
  });

  it("kind filter narrows to one group", () => {
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={noop} />);
    fireEvent.click(screen.getByTestId("resolve-filter-iteration"));
    expect(screen.getByTestId("resolve-group-iteration")).toBeInTheDocument();
    expect(screen.queryByTestId("resolve-group-finding")).toBeNull();
    expect(screen.queryByTestId("resolve-group-other")).toBeNull();
  });
});

describe("ResolveRail — selection", () => {
  it("clicking a singleton row fires onSelect with its id", () => {
    const onSelect = vi.fn();
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("resolve-row-gv-1"));
    expect(onSelect).toHaveBeenCalledWith("gv-1");
  });

  it("clicking an expanded cluster member fires onSelect with the member id", () => {
    const onSelect = vi.fn();
    render(<ResolveRail items={ITEMS} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("resolve-cluster-header-fc-1"));
    fireEvent.click(screen.getByTestId("resolve-row-fc-3"));
    expect(onSelect).toHaveBeenCalledWith("fc-3");
  });

  it("marks the selectedId row with aria-current", () => {
    render(<ResolveRail items={ITEMS} selectedId="gv-1" onSelect={noop} />);
    expect(screen.getByTestId("resolve-row-gv-1")).toHaveAttribute("aria-current", "true");
    expect(screen.getByTestId("resolve-row-gv-2")).not.toHaveAttribute("aria-current");
  });

  it("force-opens and marks the cluster that holds the selected member", () => {
    render(<ResolveRail items={ITEMS} selectedId="fc-3" onSelect={noop} />);
    // Selecting a member surfaces it (the cluster is force-open) + marks both
    // the member row and its cluster header.
    const member = screen.getByTestId("resolve-row-fc-3");
    expect(member).toHaveAttribute("aria-current", "true");
    expect(screen.getByTestId("resolve-cluster-header-fc-1")).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});

describe("ResolveRail — robustness (house doctrine)", () => {
  it("drops hostile items, never crashes, never leaks [object Object]", () => {
    const hostile = [
      null,
      42,
      "a-bare-string",
      { kind: "finding_review" }, // no id -> dropped
      { kind: "finding_review", id: "" }, // empty id -> dropped
      { kind: "finding_review", id: "h1", title: { nested: true } }, // object title
      { kind: "gate_verdict", id: "h2", title: null }, // null title
      { kind: "finding_review", id: "ok-1", title: "a valid finding" },
    ] as unknown as HumanTodoItem[];

    expect(() =>
      render(<ResolveRail items={hostile} selectedId={null} onSelect={noop} />),
    ).not.toThrow();

    // id-less / empty-id / non-object elements are dropped (3 survive: h1,h2,ok-1).
    expect(screen.getByTestId("resolve-rail-total")).toHaveTextContent("3");
    // Object/null titles degrade to a legible row keyed by id — no raw object child.
    expect(screen.getByTestId("resolve-row-h1")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-row-h2")).toBeInTheDocument();
    expect(screen.getByTestId("resolve-row-ok-1")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("[object Object]");
    // The object-title row shows its id, not the object.
    expect(within(screen.getByTestId("resolve-row-h1")).getByText("h1")).toBeInTheDocument();
  });
});
