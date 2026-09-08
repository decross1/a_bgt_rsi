// /graph — ActivityGraph tests (the S3 thin-page home of the graph). @xyflow/react does not mount custom node
// labels under jsdom, so the graph exposes an sr-only node list of the same
// GraphNodeCell cells; the asserted color + deep-link contract lives there.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it } from "vitest";
import ActivityGraph, { GraphNodeCell } from "../src/components/ActivityGraph";
import {
  GRAPH_FIXTURE,
  GRAPH_FIXTURE_UNAVAILABLE,
} from "../src/fixtures/activity";

// @xyflow/react reaches for ResizeObserver on mount; jsdom lacks it.
// Polyfill a no-op here (test-local — does not touch the shared setup).
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

function renderWithRouter(ui: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={["/graph"]}>
      <Routes>
        <Route path="/graph" element={ui} />
        <Route
          path="/chain/req/:requestId"
          element={<div data-testid="inspector-landing">inspector</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ActivityGraph", () => {
  it("renders a node per chain entry with status-driven color classes", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE} />);
    // Scope to the sr-only node list so the assertion does not depend on
    // @xyflow/react's (jsdom-fragile) node measurement/rendering.
    const list = within(screen.getByTestId("activity-graph-nodes"));
    // dispatch root is 'active' -> sky.
    const dispatch = list.getByTestId("node-root-1");
    expect(dispatch.className).toMatch(/sky/);
    expect(dispatch.getAttribute("data-kind")).toBe("dispatch");
    // wrapper call is 'ok' -> emerald.
    const call = list.getByTestId("node-call-a");
    expect(call.className).toMatch(/emerald/);
  });

  it("preserves the absence of a request id on a synthesized tool node", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE} />);
    const list = within(screen.getByTestId("activity-graph-nodes"));
    const tool = list.getByTestId("node-call-a::get_payoff_matrix::2");
    expect(tool.getAttribute("data-request-id")).toBe("");
    expect(tool).toHaveAccessibleName(/get_payoff_matrix · tool · seq-1/i);
  });

  it("selects a node without claiming its request id is indexed", () => {
    let selected: string | null = null;
    render(
      <MemoryRouter>
        <GraphNodeCell
          node={GRAPH_FIXTURE.nodes[1]}
          onSelect={(nodeId: string) => {
            selected = nodeId;
          }}
        />
      </MemoryRouter>,
    );
    const cell = screen.getByTestId("node-call-a");
    expect(cell.getAttribute("data-request-id")).toBe("call-a");
    expect(cell.getAttribute("title")).toBe("Select this recorded node");
    fireEvent.click(cell);
    expect(selected).toBe("call-a");
  });

  it("offers an explicit indexed-call lookup only after node selection", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE} />);
    const list = within(screen.getByTestId("activity-graph-nodes"));
    fireEvent.click(list.getByTestId("node-call-a"));
    const context = screen.getByRole("complementary", { name: "Selected map record" });
    expect(within(context).getByText(GRAPH_FIXTURE.nodes[1].task_id!)).toBeInTheDocument();
    expect(within(context).getByText(GRAPH_FIXTURE.nodes[1].request_id!)).toBeInTheDocument();
    expect(screen.getByText(/does not guarantee an indexed call record/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Look up indexed call" }));
    expect(screen.getByTestId("inspector-landing")).toBeInTheDocument();
  });

  it("renders an unavailable notice when the graph is absent", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE_UNAVAILABLE} />);
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/orchestrator\.jsonl absent/)).toBeInTheDocument();
  });

  it("uses a truthful list when the response has no recorded edges", () => {
    renderWithRouter(
      <ActivityGraph
        data={{
          ...GRAPH_FIXTURE,
          detail: "full",
          nodes: GRAPH_FIXTURE.nodes.filter((node) => node.kind === "dispatch"),
          edges: [],
        }}
      />,
    );
    expect(screen.getByTestId("activity-graph-zero-edge")).toHaveTextContent("No recorded relationships");
    expect(screen.getByTestId("activity-graph-no-descendants")).toBeInTheDocument();
    expect(screen.queryByTestId("activity-graph")).toBeNull();
  });
});


it("keeps malformed optional node identifiers readable as rejected raw evidence", () => {
  const bad = { ...GRAPH_FIXTURE.nodes[0], id: "bad-id", task_id: { hostile: "object identity" } };
  expect(() => renderWithRouter(<ActivityGraph data={{ ...GRAPH_FIXTURE, edges: [], nodes: [bad, GRAPH_FIXTURE.nodes[1]] as never }} />)).not.toThrow();
  expect(screen.getByTestId("activity-graph-excluded")).toHaveTextContent("1");
  expect(screen.getAllByTestId(/^node-/)).toHaveLength(1);
  expect(screen.getByText(/Unreadable or ambiguous source items/)).toBeInTheDocument();
});

it("does not call duplicate-identity records an empty map or select one arbitrarily", () => {
  const a = { ...GRAPH_FIXTURE.nodes[0], id: "duplicate", label: "first source record" };
  const b = { ...a, label: "second source record" };
  renderWithRouter(<ActivityGraph data={{ ...GRAPH_FIXTURE, edges: [], nodes: [a,b] }} />);
  expect(screen.queryByTestId("activity-graph-empty")).toBeNull();
  expect(screen.queryByRole("link", { name: "Look up indexed call" })).toBeNull();
  expect(screen.queryAllByTestId(/^node-/)).toHaveLength(0);
  expect(screen.getByTestId("activity-graph-excluded")).toHaveTextContent("2");
});
