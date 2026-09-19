import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  LocalModelTrace,
  LocalModelTraceResponse,
  ModelIOCall,
} from "../src/api/modelIO";
import {
  admitModelTraces,
  ModelActivityPanelView,
  traceSnippet,
} from "../src/components/ModelActivityPanel";

afterEach(() => vi.useRealTimers());

function trace(
  status: LocalModelTrace["status"] = "streaming",
  freshness: LocalModelTrace["freshness"]["state"] = "live",
): LocalModelTrace {
  const updated = new Date(Date.now() - 1000).toISOString();
  const started = new Date(Date.now() - 3000).toISOString();
  return {
    schema: "local-model-trace/v1",
    request_id: "a".repeat(32),
    model: "qwen3.8-flash-next-mia",
    backend: "flash",
    source: "flash-personal-client",
    started_at: started,
    updated_at: updated,
    elapsed_s: 2,
    prompt_preview: "Question",
    prompt_truncated: false,
    status,
    reasoning_content: "I should inspect the payoff matrix.",
    content: "The equilibrium is (D, D).",
    tool_calls: [{
      id: "call-1",
      type: "function",
      function: { name: "lookup_payoff", arguments: '{"row":2}' },
    }],
    usage: null,
    usage_truncated: false,
    finish_reason: status === "completed" ? "stop" : null,
    error: null,
    truncated: { reasoning_content: true, content: false, tool_calls: false },
    freshness: { state: freshness, age_s: freshness === "live" ? 1 : 20 },
  };
}

function response(row: LocalModelTrace): LocalModelTraceResponse {
  return {
    schema_version: 1,
    source: "logs/model_traces",
    available: true,
    traces: [row],
    skipped_files: 0,
    scan_truncated: false,
    generated_at: "2026-09-18T12:00:03Z",
  };
}

function call(): ModelIOCall {
  return {
    ts: new Date().toISOString(),
    request_id: "recorded-1",
    parent_request_id: null,
    model: "qwen3.8-flash-next-mia",
    backend: "flash",
    caller_tag: "personal.session",
    run_id: "smoke-1",
    latency_ms: 1200,
    input_tokens: 20,
    output_tokens: 8,
    prompt_preview: "Question",
    completion_preview: "A recorded answer",
    empty: false,
  };
}

function view(props: Parameters<typeof ModelActivityPanelView>[0]) {
  return render(<MemoryRouter><ModelActivityPanelView {...props} /></MemoryRouter>);
}

describe("local model activity panel", () => {
  it("shows a fresh streaming trace and expands emitted channels", () => {
    view({ traceResponse: response(trace()) });
    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("streaming");
    expect(screen.getByText("The equilibrium is (D, D).")).toBeInTheDocument();

    const details = screen.getByText("open emitted trace ▸").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(screen.getByText("I should inspect the payoff matrix.")).toBeInTheDocument();
    expect(screen.getByText("lookup_payoff")).toBeInTheDocument();
    expect(screen.getByText("Question")).toBeInTheDocument();
    expect(screen.getByTestId("local-trace-clipped")).toHaveTextContent("reasoning content");
  });

  it("never presents a fresh terminal snapshot or stale stream as generation", () => {
    const terminal = view({ traceResponse: response(trace("completed", "live")) });
    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("stream complete");
    expect(screen.getByTestId("local-trace-state")).not.toHaveTextContent("streaming");
    terminal.unmount();

    view({ traceResponse: response(trace("streaming", "stale")) });
    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("stale stream");
    expect(screen.getByText(/No fresh stream output has arrived/i)).toBeInTheDocument();
  });

  it("ages a retained streaming snapshot out locally even without a new response", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-18T12:00:03Z"));
    const mounted = view({ traceResponse: response(trace()) });
    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("streaming");
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("stale stream");
    mounted.unmount();
    vi.useRealTimers();
  });

  it("uses the newest emitted tail for the ticker snippet", () => {
    const row = trace();
    row.content = "";
    row.tool_calls = [];
    row.reasoning_content = `${"old ".repeat(100)}latest emitted reasoning`;
    const snippet = traceSnippet(row);
    expect(snippet.label).toBe("reasoning");
    expect(snippet.text).toMatch(/^…/);
    expect(snippet.text).toMatch(/latest emitted reasoning$/);
  });

  it("keeps paused identity, timing, and body on one snapshot when a new request arrives", () => {
    const first = trace();
    first.model = "first-model";
    first.content = "first answer";
    first.elapsed_s = 4;
    const mounted = view({ traceResponse: response(first) });
    const details = screen.getByText("open emitted trace ▸").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.click(screen.getByRole("button", { name: "Pause trace" }));

    const next = trace();
    next.request_id = "b".repeat(32);
    next.model = "second-model";
    next.content = "second answer";
    next.elapsed_s = 19;
    mounted.rerender(
      <MemoryRouter><ModelActivityPanelView traceResponse={response(next)} /></MemoryRouter>,
    );

    expect(screen.getByTestId("local-trace-state")).toHaveTextContent("paused snapshot");
    expect(screen.getByText("first-model")).toBeInTheDocument();
    expect(screen.getAllByText("first answer")).toHaveLength(2);
    expect(screen.queryByText("second-model")).toBeNull();
    expect(screen.getByText(/Newer stream output is available/)).toBeInTheDocument();
    expect(screen.getByText("4.0s")).toBeInTheDocument();
  });

  it("labels capture absence and retrieves an exact completed output on expansion", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        found: true,
        call: {
          request_id: "recorded-1",
          completion: "Exact completed answer",
        },
      }),
    } as Response)));
    view({
      traceResponse: { ...response(trace()), available: false, traces: [] },
      calls: [call()],
    });
    expect(screen.getByTestId("trace-not-enabled")).toHaveTextContent(
      "Uninstrumented requests do not appear as live traces",
    );
    const recorded = screen.getByTestId("recorded-model-call") as HTMLDetailsElement;
    recorded.open = true;
    fireEvent(recorded, new Event("toggle"));
    await waitFor(() => expect(screen.getByText("Exact completed answer")).toBeInTheDocument());
  });

  it("rejects a malformed 200 instead of showing an empty idle state", () => {
    expect(() => admitModelTraces({
      schema_version: 1,
      source: "logs/model_traces",
      available: true,
      traces: [{ status: "streaming" }],
      skipped_files: 0,
      generated_at: "2026-09-18T12:00:03Z",
    })).toThrow(/malformed/);
  });
});
