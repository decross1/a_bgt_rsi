// Day-4 additions to ChainTree: retrieval_context table + malformed
// tool_calls badge. The base render tests live in test_chain_tree.tsx.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChainTree from "../src/components/ChainTree";
import type { ChainNode } from "../src/types/schemas";

function wrapperNode(over: Partial<ChainNode> = {}): ChainNode {
  return {
    kind: "call",
    request_id: "wrap-1",
    parent_request_id: null,
    caller_tag: "wrapper",
    timestamp: "2026-05-20T12:00:00.000+00:00",
    latency_ms: 540,
    parse_error: false,
    embedded: false,
    raw: { request_id: "wrap-1", latency_ms: 540 },
    children: [],
    ...over,
  };
}

describe("ChainTree day-4 surfaces", () => {
  it("flags malformed tool_calls without silently format-fixing", () => {
    const root = wrapperNode({
      parse_error: true,
      tool_calls_malformed: true,
      raw: { request_id: "wrap-1", tool_calls: "[{\"name\": \"broken\"" },
    });
    render(<ChainTree root={root} />);
    expect(screen.getByText("malformed tool_calls")).toBeInTheDocument();
    expect(screen.getByText("parse error")).toBeInTheDocument();
  });

  it("shows the retrieval_context badge when the field is present", () => {
    const root = wrapperNode({
      retrieval_context: [
        { doc_id: "doc-A", content_hash: "abc123def456789", chunk_offset: 0, chunk_length: 512 },
        { doc_id: "doc-B", content_hash: "ffeeddccbbaa", chunk_offset: 512, chunk_length: 480 },
      ],
    });
    render(<ChainTree root={root} />);
    expect(screen.getByText("ctx 2")).toBeInTheDocument();
  });

  it("omits retrieval_context when the field is not present", () => {
    const root = wrapperNode({ retrieval_context: null });
    render(<ChainTree root={root} />);
    expect(screen.queryByText(/ctx \d/)).toBeNull();
  });
});
