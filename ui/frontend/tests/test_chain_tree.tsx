// A synthetic chain renders the right number of nodes. ui_plan.md section 5.3.
import { render, screen } from "@testing-library/react";
import ChainTree from "../src/components/ChainTree";
import type { ChainNode } from "../src/types/schemas";

let idCounter = 0;
function call(callerTag: string, children: ChainNode[] = []): ChainNode {
  idCounter += 1;
  return {
    kind: "call",
    request_id: `${callerTag}-${idCounter}`,
    parent_request_id: null,
    caller_tag: callerTag,
    timestamp: null,
    latency_ms: 10,
    parse_error: false,
    raw: {},
    children,
  };
}

describe("ChainTree", () => {
  it("renders every node in the chain", () => {
    // dispatch -> worker -> [wrapper -> tool, wrapper]  = 5 nodes
    const root: ChainNode = {
      kind: "dispatch",
      request_id: "root",
      parent_request_id: null,
      task_id: "t1",
      task_type: "demo",
      status: "passed",
      timestamp: null,
      latency_ms: null,
      raw: {},
      children: [call("worker", [call("wrapper", [call("tool")]), call("wrapper")])],
    };
    render(<ChainTree root={root} />);
    expect(screen.getAllByTestId("chain-node")).toHaveLength(5);
  });

  it("renders an embedded tool call as a node with an embedded badge", () => {
    // ui_plan.md section 9 (resolved r4): embedded tool calls arrive as
    // synthesized kind="tool" children alongside the wrapper that owns them.
    const tool: ChainNode = {
      kind: "tool",
      request_id: null,
      parent_request_id: "wrapper-x",
      caller_tag: "semantic_scholar_search",
      timestamp: null,
      latency_ms: 88,
      embedded: true,
      raw: { name: "semantic_scholar_search" },
      children: [],
    };
    const root: ChainNode = {
      kind: "dispatch",
      request_id: "root",
      parent_request_id: null,
      task_id: "t3",
      timestamp: null,
      latency_ms: null,
      raw: {},
      children: [{ ...call("wrapper"), children: [tool] }],
    };
    render(<ChainTree root={root} />);
    // dispatch + wrapper + tool = 3 nodes
    expect(screen.getAllByTestId("chain-node")).toHaveLength(3);
    expect(screen.getByText("embedded")).toBeInTheDocument();
    expect(screen.getByText("tool · semantic_scholar_search")).toBeInTheDocument();
  });

  it("flags a parse-error node", () => {
    const root: ChainNode = {
      kind: "dispatch",
      request_id: "root",
      parent_request_id: null,
      task_id: "t2",
      timestamp: null,
      latency_ms: null,
      raw: {},
      children: [{ ...call("wrapper"), parse_error: true }],
    };
    render(<ChainTree root={root} />);
    expect(screen.getByText("parse error")).toBeInTheDocument();
  });
});
