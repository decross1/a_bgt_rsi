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

  it("marks a synthesized tool node (null request_id) as not linkable", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE} />);
    const list = within(screen.getByTestId("activity-graph-nodes"));
    const tool = list.getByTestId("node-call-a::get_payoff_matrix::2");
    expect(tool.getAttribute("data-linkable")).toBe("false");
    expect(tool).toBeDisabled();
  });

  it("a node with a request_id links into /chain/req/:requestId", () => {
    let navigated: string | null = null;
    render(
      <MemoryRouter>
        <GraphNodeCell
          node={GRAPH_FIXTURE.nodes[1]}
          onOpen={(rid) => {
            navigated = `/chain/req/${rid}`;
          }}
        />
      </MemoryRouter>,
    );
    const cell = screen.getByTestId("node-call-a");
    expect(cell.getAttribute("title")).toContain("/chain/req/call-a");
    fireEvent.click(cell);
    expect(navigated).toBe("/chain/req/call-a");
  });

  it("navigates to the inspector on node click", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE} />);
    const list = within(screen.getByTestId("activity-graph-nodes"));
    fireEvent.click(list.getByTestId("node-call-a"));
    expect(screen.getByTestId("inspector-landing")).toBeInTheDocument();
  });

  it("renders an unavailable notice when the graph is absent", () => {
    renderWithRouter(<ActivityGraph data={GRAPH_FIXTURE_UNAVAILABLE} />);
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/logs\/orchestrator\.jsonl not found/),
    ).toBeInTheDocument();
  });
});
