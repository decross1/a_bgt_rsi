// /model-io perf pins (2026-08-18, owner: the page "is really struggling to
// load anything" — five build lanes each added their own fetching and nobody
// consolidated). These pin the consolidated behavior:
//
//  1. NO-BLANK-ON-REFETCH: a poll tick that fails keeps the rendered rows
//     (stale-while-revalidate) and says STALE — content never blanks;
//  2. EXPANSION SURVIVES TICKS: an expanded row and its fetched detail ride
//     out a payload-CHANGING poll tick, and the detail endpoint is fetched
//     exactly once per request_id (keyed cache, never per tick);
//  3. TITLE CACHE: useDocTitles never refetches known ids when its consumer
//     re-renders on later ticks;
//  4. PAUSE-ON-HIDDEN: a hidden tab fires ZERO requests; returning to
//     visibility refetches immediately;
//  5. NO-CHANGE TICK = NO COMMITS: an unchanged payload re-renders nothing
//     (pollhub identity + volatile-field stripping in the fetchers);
//  6. DEBOUNCED FILTER: typing N characters costs ONE table refetch and
//     never touches the strip/trace/frontier sources (a no-match filter
//     costs the backend a full 16 MiB scan — keystrokes must not) — and
//     (review fix 3) cycling filters never leaks pollhub entries;
//  7. FETCH DEADLINE (review fix 1): a hung request is ABORTED at 15s —
//     the source fails honestly instead of wedging;
//  8. PAGING GAP (review minor b): >PAGE_SIZE new rows landing in one tick
//     after paging began renders an explicit gap marker, never a silent
//     hole between the live page and the retained rows.
import { Profiler } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ModelIO from "../src/routes/ModelIO";
import { getModelIO } from "../src/api/modelIO";
import { pollHubEntryCount, resetPollHub } from "../src/api/pollhub";
import useDocTitles, {
  _resetDocTitlesForTests,
} from "../src/hooks/useDocTitles";

const row = (id: string, ts: string, preview: string) => ({
  ts,
  request_id: id,
  parent_request_id: null,
  model: "gemma-4-26b-a4b",
  backend: "vllm-gemma",
  caller_tag: "nara.run_iteration",
  run_id: null,
  latency_ms: 100,
  input_tokens: 10,
  output_tokens: 5,
  prompt_preview: "ask",
  completion_preview: preview,
  empty: false,
});

const CALLS = {
  calls: [
    row("req-3", "2026-08-18T01:00:02Z", "newest"),
    row("req-2", "2026-08-18T01:00:01Z", "middle"),
    row("req-1", "2026-08-18T01:00:00Z", "oldest"),
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
    prompt_messages: [{ role: "user", content: "the full ask" }],
    completion: "the full completion body",
    usage: { input_tokens: 10, output_tokens: 5 },
  },
};

const TRACE = {
  orchestrator_available: true,
  spawn_available: true,
  tasks: [],
  spawns: [],
  generated_at: "2026-08-18T01:00:03Z",
};

const ACTIVITY = {
  orchestrator_available: true,
  calls_available: true,
  chain: [
    {
      task_id: "t1",
      task_type: "experiment_trial",
      status: "passed",
      stage: "orchestrator_receipt",
      duration_ms: 0.2,
      ts: "2026-08-18T00:58:00Z",
      run_id: null,
    },
  ],
  subagent_groups: [],
  window_truncated: false,
  generated_at: "2026-08-18T01:00:03Z",
};

const FRONTIER = {
  available: true,
  calls: [],
  rows_in_window: 0,
  summary: {
    last_call_ts: null,
    calls_24h: 0,
    consecutive_nonzero_exit_by_vendor: {},
    vendors_down: [],
    down_streak_threshold: 3,
  },
  window_bytes: 262144,
  window_truncated: false,
  generated_at: "2026-08-18T01:00:03Z",
};

type Handler = (url: string) => { status: number; body: unknown };

// Per-bucket fetch counter + swappable handler; generated_at churns per
// response exactly like the real backend, so these pins also prove the
// fetchers' volatile-field stripping.
function stubCounted(initial: Handler) {
  const counts: Record<string, number> = {};
  const state = { handler: initial };
  const bucket = (url: string): string => {
    if (url.includes("/api/model_io/")) return "detail";
    if (url.includes("/api/model_io")) return "table";
    if (url.includes("/api/dispatch_trace")) return "trace";
    if (url.includes("/api/runtime_activity")) return "activity";
    if (url.includes("/api/frontier_calls")) return "frontier";
    if (url.includes("/api/doc_titles")) return "doc_titles";
    return "other";
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const u = String(url);
      counts[bucket(u)] = (counts[bucket(u)] ?? 0) + 1;
      const { status, body } = state.handler(u);
      return {
        ok: status >= 200 && status < 300,
        status,
        statusText: String(status),
        json: async () => body,
      } as Response;
    }),
  );
  return { counts, state };
}

const happy: Handler = (url) => {
  if (url.includes("/api/model_io/")) return { status: 200, body: DETAIL };
  if (url.includes("/api/model_io"))
    return {
      status: 200,
      body: { ...CALLS, generated_at: new Date().toISOString() },
    };
  if (url.includes("/api/dispatch_trace"))
    return {
      status: 200,
      body: { ...TRACE, generated_at: new Date().toISOString() },
    };
  if (url.includes("/api/runtime_activity"))
    return {
      status: 200,
      body: { ...ACTIVITY, generated_at: new Date().toISOString() },
    };
  if (url.includes("/api/frontier_calls"))
    return {
      status: 200,
      body: { ...FRONTIER, generated_at: new Date().toISOString() },
    };
  if (url.includes("/api/health"))
    return { status: 200, body: { version: "test" } };
  return { status: 404, body: { detail: "nope" } };
};

const settle = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

afterEach(() => {
  cleanup();
  // A test that shadowed document.visibilityState must hand the real
  // prototype getter back to the next test.
  delete (document as unknown as Record<string, unknown>).visibilityState;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  _resetDocTitlesForTests();
  resetPollHub(); // no snapshot/entry bleed between tests
});

it("keeps rendered rows and says STALE when a poll tick fails — never blanks", async () => {
  vi.useFakeTimers();
  const { state } = stubCounted(happy);
  render(<ModelIO />);
  await settle(500); // initial fetches + debounce settle
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(3);

  state.handler = (url) =>
    url.includes("/api/model_io") && !url.includes("/api/model_io/")
      ? { status: 500, body: { detail: "boom" } }
      : happy(url);
  await settle(6_000); // one table repoll (5s) + a heartbeat
  // Rows kept, stale note shown — the failed refetch blanked nothing.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(3);
  expect(
    screen.getByText(/unreachable — showing the last loaded rows/),
  ).toBeInTheDocument();
});

it("an expanded row + its detail survive a payload-CHANGING tick; detail fetched once", async () => {
  vi.useFakeTimers();
  const { counts, state } = stubCounted(happy);
  render(<ModelIO />);
  await settle(500);
  // Expand the oldest row (req-1) and let its detail land.
  fireEvent.click(screen.getAllByTestId("modelio-row")[2]);
  await settle(100);
  expect(screen.getByTestId("call-expansion")).toBeInTheDocument();
  expect(screen.getByText("the full completion body")).toBeInTheDocument();
  expect(counts.detail).toBe(1);

  // A NEW row arrives on the next poll (payload really changes).
  state.handler = (url) =>
    url.includes("/api/model_io") && !url.includes("/api/model_io/")
      ? {
          status: 200,
          body: {
            ...CALLS,
            calls: [
              row("req-4", "2026-08-18T01:00:05Z", "fresh arrival"),
              ...CALLS.calls,
            ],
            generated_at: new Date().toISOString(),
          },
        }
      : happy(url);
  await settle(6_000);
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(4);
  // The expansion is still open with its content, and the detail was NOT
  // refetched by the tick.
  expect(screen.getByTestId("call-expansion")).toBeInTheDocument();
  expect(screen.getByText("the full completion body")).toBeInTheDocument();
  expect(counts.detail).toBe(1);
});

it("useDocTitles never refetches known ids when its consumer re-renders", async () => {
  vi.useFakeTimers();
  const { counts, state } = stubCounted(happy);
  state.handler = (url) =>
    url.includes("/api/doc_titles")
      ? {
          status: 200,
          body: { "2604.15267": { title: "A Real Title", kind: "paper" } },
        }
      : happy(url);

  function Probe({ tick }: { tick: number }) {
    // A fresh array identity every render — the hook's want-key dedupe and
    // the module cache must still yield exactly one fetch.
    const titles = useDocTitles(["2604.15267"]);
    return (
      <div data-testid="probe">
        {tick}:{titles["2604.15267"]?.title ?? "bare"}
      </div>
    );
  }
  const view = render(<Probe tick={0} />);
  await settle(100);
  expect(screen.getByTestId("probe").textContent).toBe("0:A Real Title");
  expect(counts.doc_titles).toBe(1);
  // Simulated poll ticks re-render the consumer.
  for (let t = 1; t <= 3; t++) {
    view.rerender(<Probe tick={t} />);
    await settle(1_000);
  }
  expect(screen.getByTestId("probe").textContent).toBe("3:A Real Title");
  expect(counts.doc_titles).toBe(1);
});

it("a hidden tab polls NOTHING; returning to visibility refetches immediately", async () => {
  vi.useFakeTimers();
  const { counts } = stubCounted(happy);
  render(<ModelIO />);
  await settle(500);
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(3);

  let hidden = true;
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => (hidden ? "hidden" : "visible"),
  });
  document.dispatchEvent(new Event("visibilitychange"));
  const atHide = { ...counts };
  await settle(30_000); // six table periods + one strip period pass hidden
  expect(counts).toEqual(atHide); // zero fetches while hidden

  hidden = false;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(50);
  });
  // The overdue sources fired the moment the tab became visible.
  expect(counts.table).toBeGreaterThan(atHide.table);
});

it("an unchanged payload tick commits ZERO re-renders", async () => {
  vi.useFakeTimers();
  stubCounted(happy);
  let commits = 0;
  render(
    <Profiler id="modelio" onRender={() => commits++}>
      <ModelIO />
    </Profiler>,
  );
  await settle(1_500); // initial fetches + debounce settle + first repoll due
  const before = commits;
  // Two more table repolls land (5s cadence), same payload each time —
  // generated_at churn is stripped by the fetcher, so nothing notifies.
  for (let i = 0; i < 10; i++) await settle(1_000);
  expect(commits).toBe(before);
});

it("typing a 4-char filter costs ONE table refetch and never touches the other sources", async () => {
  vi.useFakeTimers();
  const { counts } = stubCounted(happy);
  const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
  render(<ModelIO />);
  await settle(500);
  const before = { ...counts };

  const input = screen.getByLabelText("filter by model");
  for (const partial of ["q", "qw", "qwe", "qwen"]) {
    fireEvent.change(input, { target: { value: partial } });
    await settle(100); // inter-keystroke gap < the 350ms debounce
  }
  await settle(600); // debounce fires once, after the last keystroke
  expect(counts.table).toBe(before.table + 1);
  expect(counts.activity).toBe(before.activity);
  expect(counts.trace).toBe(before.trace);
  expect(counts.frontier).toBe(before.frontier);
  // And the one refetch carried the FINAL query, not a prefix.
  const tableUrls = fetchMock.mock.calls
    .map((c) => String(c[0]))
    .filter((u) => u.includes("model="));
  expect(tableUrls).toHaveLength(1);
  expect(tableUrls[0]).toContain("model=qwen");
  // Review fix 3: the superseded filter key's entry was EVICTED — the hub
  // holds exactly the page's four live sources, not one per query typed.
  expect(pollHubEntryCount()).toBe(4);
});

it("aborts a hung getJSON fetch at the 15s deadline (AbortController, review fix 1)", async () => {
  vi.useFakeTimers();
  // A fetch that never settles on its own but honors its abort signal —
  // the hung-backend shape (/api/lab_todo measured >120s under load).
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_url: unknown, init?: { signal?: AbortSignal }) =>
        new Promise((_res, rej) => {
          init?.signal?.addEventListener("abort", () =>
            rej(init.signal?.reason ?? new Error("aborted")),
          );
        }),
    ),
  );
  const outcome = getModelIO().then(
    () => "resolved",
    (e) => String(e),
  );
  await settle(14_000);
  // Not yet: the deadline is 15s.
  await settle(2_000);
  const err = await outcome;
  expect(err).toContain("deadline");
  expect(err).toContain("15000ms");
});

it("marks the paging gap explicitly when >PAGE_SIZE new rows land in one tick (review minor b)", async () => {
  vi.useFakeTimers();
  const iso = (min: number) =>
    `2026-08-18T${String(Math.floor(min / 60)).padStart(2, "0")}:${String(
      min % 60,
    ).padStart(2, "0")}:00Z`;
  // Full PAGE_SIZE (20) pages, newest-first, disjoint id ranges.
  const page = (prefix: string, newestMin: number) => ({
    ...CALLS,
    calls: Array.from({ length: 20 }, (_, i) =>
      row(`${prefix}-${i}`, iso(newestMin - i), `${prefix} ${i}`),
    ),
  });
  const pageA = page("a", 60); // the live page at mount (01:00 … 00:41)
  const pageB = page("b", 30); // the older page behind load-older
  const pageC = page("c", 120); // a FULL page of brand-new rows (02:00 …)

  const { state } = stubCounted((url) => {
    if (url.includes("before_ts=")) return { status: 200, body: pageB };
    if (url.includes("/api/model_io") && !url.includes("/api/model_io/"))
      return { status: 200, body: pageA };
    return happy(url);
  });
  render(<ModelIO />);
  await settle(500);
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(20);

  fireEvent.click(screen.getByTestId("load-older"));
  await settle(100);
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(40);
  expect(screen.queryByTestId("page-gap")).toBeNull(); // contiguous so far

  // More than a page of new rows arrives between polls: the fresh page
  // shares NOTHING with the previous newest page — the rows between them
  // were never fetched and must not be silently omitted.
  state.handler = (url) => {
    if (url.includes("before_ts=")) return { status: 200, body: pageB };
    if (url.includes("/api/model_io") && !url.includes("/api/model_io/"))
      return { status: 200, body: pageC };
    return happy(url);
  };
  await settle(6_000); // one table repoll
  expect(screen.getByTestId("page-gap")).toBeInTheDocument();
  // Nothing was thrown away either: 20 fresh + 20 retained + 20 paged.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(60);

  // The marker's refresh restarts from the live page — gap closed, paged
  // rows (fetched under a now-stale boundary) dropped.
  fireEvent.click(screen.getByTestId("page-gap-refresh"));
  expect(screen.queryByTestId("page-gap")).toBeNull();
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(20);
});
