// ModelIO (/model-io) — the owner's "what is actually passing through the
// models" page. The load-bearing pins:
//
//  1. the table renders what the backend hands over — model badge, caller
//     tag, latency, in/out tokens — and flags an EMPTY completion loudly;
//  2. clicking a row fetches the FULL record and shows the role-labeled
//     prompt messages + the completion (the health panels can never show
//     this);
//  3. filters change the query the page polls with (server-side filtering);
//  4. degradations are honest: a version-skew 404 becomes the quiet
//     EndpointMissingNote, a failed poll keeps the last rows and says STALE,
//     and the main-log-only footnote is always present.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ModelIO, { ageOf } from "../src/routes/ModelIO";
import type {
  DispatchTraceResponse,
  ModelIOResponse,
} from "../src/api/modelIO";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const CALLS: ModelIOResponse = {
  calls: [
    {
      ts: "2026-08-18T01:00:02Z",
      request_id: "req-3",
      parent_request_id: null,
      model: "gemma-4-26b-a4b",
      backend: "vllm-gemma",
      caller_tag: "nara.meta_review",
      run_id: "iter-9",
      latency_ms: 812,
      input_tokens: 900,
      output_tokens: 0,
      prompt_preview: "Evaluate this",
      completion_preview: "",
      empty: true,
    },
    {
      ts: "2026-08-18T01:00:01Z",
      request_id: "req-2",
      parent_request_id: null,
      model: "qwen3.8-27b-nvfp4-mtp",
      backend: "vllm-qwen",
      caller_tag: "skeptic_battery",
      run_id: null,
      latency_ms: 421,
      input_tokens: 340,
      output_tokens: 55,
      prompt_preview: "Attack this claim",
      completion_preview: "The claim fails because",
      empty: false,
    },
    {
      ts: "2026-08-18T01:00:00Z",
      request_id: "req-1",
      parent_request_id: "iter-2026-08-18-001",
      model: "gemma-4-26b-a4b",
      backend: null,
      caller_tag: "nara.run_iteration",
      run_id: null,
      latency_ms: 4991,
      input_tokens: 822,
      output_tokens: 55,
      prompt_preview: "Evaluate this research topic",
      completion_preview: "I will query chroma",
      empty: false,
    },
  ],
  source: "logs/calls.jsonl",
  window_truncated: false,
  scanned_bytes: 4096,
  max_scan_bytes: 16777216,
  generated_at: "2026-08-18T01:00:03Z",
};

const DETAIL = {
  found: true,
  call: {
    timestamp: "2026-08-18T01:00:00Z",
    request_id: "req-1",
    model: "gemma-4-26b-a4b",
    caller_tag: "nara.run_iteration",
    temperature: 0,
    seed: null,
    prompt_messages: [
      { role: "system", content: "You are Nara, the research orchestrator." },
      { role: "user", content: "Evaluate this research topic: TFT dominance" },
    ],
    completion: "I will query chroma for prior art on TFT dominance.",
    usage: { input_tokens: 822, output_tokens: 55 },
  },
};

const TRACE: DispatchTraceResponse = {
  orchestrator_available: true,
  spawn_available: true,
  tasks: [
    {
      task_id: "exp012_FULL_s29",
      task_type: "experiment_trial",
      status: "passed",
      stage: "orchestrator_receipt",
      duration_ms: 0.2,
      ts: "2026-08-18T00:59:00Z",
      run_id: null,
    },
  ],
  spawns: [
    {
      spawn_id: "sprint-build-io-viewer",
      status: "spawned",
      ts: "2026-08-18T00:49:00Z",
      task_statement: "Model I/O viewer + agent-dispatch trace",
    },
  ],
  generated_at: "2026-08-18T01:00:03Z",
};

// Runtime-activity fixture with ages ANCHORED TO NOW so the rendered "3m"
// style ages are deterministic regardless of when the suite runs.
const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const ACTIVITY = {
  orchestrator_available: true,
  calls_available: true,
  chain: [
    {
      task_id: "exp012_FULL_s29_r0.84",
      task_type: "experiment_trial",
      status: "passed",
      stage: "orchestrator_receipt",
      duration_ms: 0.2,
      ts: minsAgo(2),
      run_id: null,
    },
    {
      task_id: "pd_match_017",
      task_type: "play_pd_match",
      status: "dispatched",
      stage: "orchestrator_dispatch",
      duration_ms: null,
      ts: minsAgo(9),
      run_id: null,
    },
  ],
  subagent_groups: [
    {
      family: "promotion_panel",
      label: "promotion panel (3 skeptics)",
      group_key: "promote_findings_d591099f",
      key_source: "run_id",
      calls: 12,
      models: ["qwen3.6-27b-nvfp4-mtp"],
      caller_tags: [
        "finding_promotion.synthesize",
        "subagent.finding_skeptic_1",
        "subagent.finding_skeptic_2",
        "subagent.finding_skeptic_3",
      ],
      first_ts: minsAgo(8),
      last_ts: minsAgo(3),
    },
    {
      family: "two_voice_session",
      label: "two-voice session",
      group_key: "finding_session_fs-a5f6dc7c7f70",
      key_source: "run_id",
      calls: 5,
      models: ["qwen3.6-27b-nvfp4-mtp"],
      caller_tags: ["finding_session_attacker", "finding_session_defender"],
      first_ts: minsAgo(30),
      last_ts: minsAgo(25),
    },
  ],
  window_truncated: false,
  generated_at: new Date().toISOString(),
};

type Routed = { status: number; body: unknown };

function stubRoutes(handler: (url: string) => Routed) {
  const mock = vi.fn(async (url: unknown) => {
    const { status, body } = handler(String(url));
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function happyHandler(url: string): Routed {
  if (url.includes("/api/model_io/")) return { status: 200, body: DETAIL };
  if (url.includes("/api/model_io")) return { status: 200, body: CALLS };
  if (url.includes("/api/dispatch_trace")) return { status: 200, body: TRACE };
  if (url.includes("/api/runtime_activity"))
    return { status: 200, body: ACTIVITY };
  if (url.includes("/api/health"))
    return { status: 200, body: { version: "abc1234" } };
  return { status: 404, body: { detail: "nope" } };
}

// ─── the table ──────────────────────────────────────────────────────────

it("renders one row per call with model badge, caller tag, latency, tokens", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  // Model badges (the gemma/qwen names verbatim, never re-derived).
  expect(screen.getAllByText("gemma-4-26b-a4b")).toHaveLength(2);
  expect(screen.getByText("qwen3.8-27b-nvfp4-mtp")).toBeInTheDocument();
  // Backend chips are pure passthrough — absent on req-1, present on req-2.
  expect(screen.getByText("vllm-qwen")).toBeInTheDocument();
  expect(screen.getByText("skeptic_battery")).toBeInTheDocument();
  expect(screen.getByText("4991ms")).toBeInTheDocument();
  expect(screen.getByText("822→55 tok")).toBeInTheDocument();
});

it("flags the EMPTY completion loudly, and only on the empty row", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  expect(screen.getAllByTestId("empty-flag")).toHaveLength(1);
});

// ─── expansion: the full prompt/completion reader ───────────────────────

it("expands a row into role-labeled prompt messages + the completion", async () => {
  const mock = stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getAllByTestId("modelio-row")[2]); // req-1
  await waitFor(() =>
    expect(screen.getByTestId("call-expansion")).toBeInTheDocument(),
  );
  // The detail endpoint was actually asked for the clicked request_id.
  expect(
    mock.mock.calls.some((c) => String(c[0]).includes("/api/model_io/req-1")),
  ).toBe(true);
  // Role labels + full (not preview) content, and the completion body.
  expect(screen.getByText("system")).toBeInTheDocument();
  expect(screen.getByText("user")).toBeInTheDocument();
  expect(
    screen.getByText(/You are Nara, the research orchestrator/),
  ).toBeInTheDocument();
  expect(screen.getByTestId("completion-body").textContent).toContain(
    "query chroma for prior art",
  );
  // Toggling again collapses it.
  fireEvent.click(screen.getAllByTestId("modelio-row")[2]);
  expect(screen.queryByTestId("call-expansion")).toBeNull();
});

it("says the full record is unavailable when the detail fetch fails", async () => {
  stubRoutes((url) =>
    url.includes("/api/model_io/")
      ? { status: 404, body: { detail: "out of window" } }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getAllByTestId("modelio-row")[0]);
  await waitFor(() =>
    expect(
      screen.getByText(/full record unavailable/),
    ).toBeInTheDocument(),
  );
});

// ─── filters + pause ────────────────────────────────────────────────────

it("re-polls with the filter as a query param", async () => {
  const mock = stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.change(screen.getByLabelText("filter by caller tag"), {
    target: { value: "skeptic" },
  });
  await waitFor(() =>
    expect(
      mock.mock.calls.some((c) =>
        String(c[0]).includes("caller_tag=skeptic"),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("filter by model"), {
    target: { value: "qwen" },
  });
  await waitFor(() =>
    expect(
      mock.mock.calls.some((c) => String(c[0]).includes("model=qwen")),
    ).toBe(true),
  );
});

it("pause toggles to resume and reports the paused state", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  const btn = screen.getByRole("button", { name: "pause" });
  fireEvent.click(btn);
  expect(screen.getByRole("button", { name: "resume" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByText("paused")).toBeInTheDocument();
});

// ─── the runtime activity strip (plane separation) ──────────────────────

it("renders ONE runtime strip: nara chain lines + subagent group cards", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("chain-line")).toHaveLength(2),
  );
  // Plane (a): chain lines are station name + age, one-line dense.
  expect(screen.getByText("nara chain")).toBeInTheDocument();
  expect(screen.getByText("experiment_trial")).toBeInTheDocument();
  expect(screen.getByText("play_pd_match")).toBeInTheDocument();
  expect(screen.getByText("2m")).toBeInTheDocument(); // ts anchored to now
  // Plane (b): one compact card per caller_tag-family group, with the
  // family label, model badge, call count, and last-activity age.
  expect(screen.getByText("subagent work")).toBeInTheDocument();
  expect(screen.getAllByTestId("subagent-group")).toHaveLength(2);
  expect(screen.getByText("promotion panel (3 skeptics)")).toBeInTheDocument();
  expect(screen.getByText("two-voice session")).toBeInTheDocument();
  expect(screen.getAllByText("qwen3.6-27b-nvfp4-mtp")).toHaveLength(2);
  expect(screen.getByText("12 calls")).toBeInTheDocument();
  expect(screen.getByText("3m")).toBeInTheDocument();
  // The old two verbose cards are gone.
  expect(screen.queryByTestId("trace-task-row")).toBeNull();
  expect(screen.queryByTestId("trace-spawn-row")).toBeNull();
});

it("keeps the dev spawn ledger behind an explicitly-labelled toggle, collapsed by default", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("chain-line")).toHaveLength(2),
  );
  // Collapsed by default: no dev rows and no contract prose anywhere.
  expect(screen.queryAllByTestId("dev-spawn-row")).toHaveLength(0);
  expect(
    screen.queryByText("Model I/O viewer + agent-dispatch trace"),
  ).toBeNull();
  // The toggle names the plane: dev-side Claude Code, not runtime agents.
  const toggle = screen.getByTestId("dev-spawn-toggle");
  expect(toggle.textContent).toContain(
    "build agents (dev — Claude Code workflow ledger)",
  );
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  // One-line entries: spawn_id + status chip + age — still no prose body.
  const rows = screen.getAllByTestId("dev-spawn-row");
  expect(rows).toHaveLength(1);
  expect(screen.getByText("sprint-build-io-viewer")).toBeInTheDocument();
  expect(screen.getByText("spawned")).toBeInTheDocument();
  expect(
    screen.queryByText("Model I/O viewer + agent-dispatch trace"),
  ).toBeNull();
  // Toggling again collapses it back.
  fireEvent.click(toggle);
  expect(screen.queryAllByTestId("dev-spawn-row")).toHaveLength(0);
});

it("says the runtime state is UNKNOWN when /api/runtime_activity never loads", async () => {
  stubRoutes((url) =>
    url.includes("/api/runtime_activity")
      ? { status: 404, body: { detail: "Not Found" } }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  expect(
    screen.getByText(/runtime state UNKNOWN, not idle/),
  ).toBeInTheDocument();
  expect(screen.queryAllByTestId("chain-line")).toHaveLength(0);
});

// ─── ageOf (compact ages: "3m") ─────────────────────────────────────────

it("ageOf renders compact ages and honest dashes", () => {
  const now = Date.parse("2026-08-18T12:00:00Z");
  expect(ageOf("2026-08-18T11:59:48Z", now)).toBe("12s");
  expect(ageOf("2026-08-18T11:57:00Z", now)).toBe("3m");
  expect(ageOf("2026-08-18T07:00:00Z", now)).toBe("5h");
  expect(ageOf("2026-08-13T12:00:00Z", now)).toBe("5d");
  expect(ageOf(null, now)).toBe("—");
  expect(ageOf("not-a-timestamp", now)).toBe("—");
});

// ─── honest degradations ────────────────────────────────────────────────

it("degrades a version-skew 404 to the quiet EndpointMissingNote", async () => {
  stubRoutes((url) =>
    url.includes("/api/health")
      ? { status: 200, body: { version: "abc1234" } }
      : { status: 404, body: { detail: "Not Found" } },
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getByTestId("endpoint-missing-note")).toBeInTheDocument(),
  );
});

it("keeps the last rows and says STALE when a later poll fails", async () => {
  let healthy = true;
  stubRoutes((url) =>
    healthy || !url.includes("/api/model_io")
      ? happyHandler(url)
      : { status: 500, body: { detail: "boom" } },
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  healthy = false;
  // A filter change forces an immediate refetch, which now fails.
  fireEvent.change(screen.getByLabelText("filter by run id"), {
    target: { value: "iter-9" },
  });
  await waitFor(() =>
    expect(screen.getByText(/unreachable — showing the last loaded rows/))
      .toBeInTheDocument(),
  );
  // The rows are kept, not blanked.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(3);
});

it("always states the main-log-only scope as a footnote", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  const note = await screen.findByTestId("modelio-footnote");
  expect(note.textContent).toContain("logs/calls.jsonl");
  expect(note.textContent).toContain("runs/*.calls.jsonl");
});
