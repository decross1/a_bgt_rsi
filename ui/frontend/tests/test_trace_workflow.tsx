import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Inspector from "../src/routes/Inspector";
import type { ChainNode, ChainResponse } from "../src/types/schemas";

const mocks = vi.hoisted(() => ({
  getChainByRequest: vi.fn(),
}));

vi.mock("../src/api/http", () => ({
  getChainByRequest: mocks.getChainByRequest,
}));

function syntheticNode(depth: number): ChainNode {
  return {
    kind: depth === 0 ? "dispatch" : "call",
    request_id: `synthetic-deep-${String(depth).padStart(2, "0")}`,
    parent_request_id: depth === 0 ? null : `synthetic-deep-${String(depth - 1).padStart(2, "0")}`,
    caller_tag: depth === 0 ? null : `synthetic-wrapper-${depth}`,
    task_id: depth === 0 ? "synthetic-browser-only" : undefined,
    task_type: depth === 0 ? "synthetic deep-tree fixture" : undefined,
    status: depth === 0 ? "passed" : undefined,
    timestamp: "2026-09-08T03:30:00Z",
    latency_ms: depth === 0 ? null : depth + 0.25,
    parse_error: false,
    raw: {
      fixture_scope: "synthetic browser qualification only",
      request_id: `synthetic-deep-${String(depth).padStart(2, "0")}`,
      depth,
      unbroken_value: depth === 19 ? "x".repeat(180) : undefined,
    },
    children: depth < 19 ? [syntheticNode(depth + 1)] : [],
  };
}

export const SYNTHETIC_DEEP_20_CHAIN: ChainResponse = {
  root_request_id: "synthetic-deep-00",
  found: true,
  malformed: false,
  root: syntheticNode(0),
  node_count: 20,
  total_latency_ms: 194.75,
  malformed_tool_calls: 0,
};

function GraphLanding() {
  const location = useLocation();
  const state = location.state as { focusNodeId?: unknown } | null;
  return <div data-testid="graph-return">graph return · {String(state?.focusNodeId ?? "no focus")}</div>;
}

function renderInspector(
  requestId = "dispatch-only-1",
  state?: { returnTo?: string; focusNodeId?: string },
) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: `/chain/req/${requestId}`, state }]}>
      <Routes>
        <Route path="/chain/req/:requestId" element={<Inspector />} />
        <Route path="/graph" element={<GraphLanding />} />
        <Route path="/cycles" element={<div data-testid="cycles-return">cycles return</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("trace map to exact request workflow", () => {
  beforeEach(() => {
    mocks.getChainByRequest.mockReset();
  });

  it("renders a dispatch 404 as an explicit no-indexed-call result with recovery", async () => {
    mocks.getChainByRequest.mockRejectedValue({
      status: 404,
      detail: "no call record for request_id 'dispatch-only-1'",
    });
    renderInspector("dispatch-only-1", { returnTo: "/graph?node=dispatch-1", focusNodeId: "dispatch-1" });

    const state = await screen.findByTestId("inspector-unindexed");
    expect(state).toHaveTextContent("No indexed call record");
    expect(state).toHaveTextContent(/does not establish whether its dispatch or underlying run succeeded or failed/i);
    expect(state).not.toHaveTextContent("HttpError");
    expect(mocks.getChainByRequest).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Back to recorded map" }));
    expect(screen.getByTestId("graph-return")).toHaveTextContent("dispatch-1");
  });

  it("keeps backend failure separate from an unindexed request", async () => {
    mocks.getChainByRequest.mockRejectedValue({ status: 500, detail: "call index unavailable" });
    renderInspector("call-500");

    const state = await screen.findByTestId("inspector-error");
    expect(state).toHaveTextContent("Request inspector unavailable");
    expect(state).not.toHaveTextContent("No indexed call record");
    expect(state).toHaveTextContent("call index unavailable");
  });

  it("renders a synthetic 20-level chain with capped indentation and exact raw records", async () => {
    mocks.getChainByRequest.mockResolvedValue(SYNTHETIC_DEEP_20_CHAIN);
    renderInspector("synthetic-deep-00", { returnTo: "/cycles" });

    const nodes = await screen.findAllByTestId("chain-node");
    expect(nodes).toHaveLength(20);
    const rows = document.querySelectorAll<HTMLElement>(".trace-chain-row");
    expect(rows[19].style.paddingInlineStart).toBe("80px");
    expect(screen.getByText("194.8 ms")).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Raw JSONL and exact identifiers/));
    const raw = await screen.findByTestId("inspector-raw-jsonl");
    expect(raw.textContent?.split("\n")).toHaveLength(20);
    expect(raw).toHaveTextContent("synthetic-deep-19");
    expect(raw).toHaveTextContent("synthetic browser qualification only");
  });

  it("does not turn a found response without a root into an empty chain", async () => {
    mocks.getChainByRequest.mockResolvedValue({
      found: true,
      malformed: false,
      root: null,
      node_count: 0,
      total_latency_ms: 0,
    } satisfies ChainResponse);
    renderInspector("rootless");

    const state = await screen.findByTestId("inspector-malformed-response");
    expect(state).toHaveTextContent("no readable chain");
    expect(state).toHaveTextContent(/not presented as an empty chain/i);
  });

  it("retries only after the explicit recovery action", async () => {
    mocks.getChainByRequest
      .mockRejectedValueOnce({ status: 404, detail: "no call record" })
      .mockResolvedValueOnce(SYNTHETIC_DEEP_20_CHAIN);
    renderInspector("synthetic-deep-00");

    await screen.findByTestId("inspector-unindexed");
    expect(mocks.getChainByRequest).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry lookup" }));
    await waitFor(() => expect(screen.getAllByTestId("chain-node")).toHaveLength(20));
    expect(mocks.getChainByRequest).toHaveBeenCalledTimes(2);
  });
});
