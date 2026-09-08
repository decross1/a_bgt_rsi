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
import ModelIO, { ageOf, sanitizePreview } from "../src/routes/ModelIO";
import type { ModelIOResponse } from "../src/api/modelIO";

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
  const btn = screen.getByRole("button", { name: "Pause updates" });
  fireEvent.click(btn);
  expect(screen.getByRole("button", { name: "Resume updates" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByText("Only this page is paused")).toBeInTheDocument();
  expect(screen.getByTestId("modelio-freshness")).toHaveTextContent(
    /Updates paused · as of \d{2}:\d{2}:\d{2} UTC/,
  );
});

// Runtime and developer history now belong to the trace journey. Calls
// links there but does not mount those unrelated polling consumers.
it("links to trace history without mounting runtime or dispatch sources", async () => {
  const mock = stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  expect(screen.getByRole("link", { name: "Coordinator history" })).toHaveAttribute(
    "href",
    "/cycles",
  );
  const urls = mock.mock.calls.map((call) => String(call[0]));
  expect(urls.some((url) => url.includes("/api/runtime_activity"))).toBe(false);
  expect(urls.some((url) => url.includes("/api/dispatch_trace"))).toBe(false);
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

// ─── preview sanitization (owner 2026-08-18: the preview subtext "is
//     basically jibberish" — raw channel markup leaked into
//     completion_preview) ───────────────────────────────────────────────

// The owner's report, as the wrapper logs it (newlines; the row's CSS
// collapses them to the spaces the owner saw).
const OWNER_GIBBERISH =
  "thought\n<|channel>thought\n<channel|>This iteration investigated the " +
  "effect of memory depth on cooperation stability.";

it("sanitizePreview turns the owner's gibberish into clean thought prose", () => {
  const view = sanitizePreview(OWNER_GIBBERISH);
  expect(view).not.toBeNull();
  expect(view!.thought).toBe(true);
  expect(view!.text).toContain("This iteration investigated");
  // No raw channel token ever, and the stray lone label word is gone too.
  expect(view!.text).not.toMatch(/<\|?(channel|analysis|final|message)/i);
  expect(view!.text.startsWith("thought")).toBe(false);
});

it("sanitizePreview handles the space-collapsed form the owner pasted", () => {
  const view = sanitizePreview(
    "thought <|channel>thought <channel|>This iteration investigated...",
  );
  expect(view!.thought).toBe(true);
  expect(view!.text).toContain("This iteration investigated");
  expect(view!.text).not.toContain("<|channel>");
});

it("sanitizePreview shows ONLY the visible text when both channels exist", () => {
  const view = sanitizePreview(
    "<|channel>thought<channel|>secret reasoning<|final>\nThe verdict is NO.",
  );
  expect(view!.thought).toBe(false);
  expect(view!.text).toBe("The verdict is NO.");
  expect(view!.text).not.toContain("secret reasoning");
});

it("sanitizePreview strips a truncation-cut partial channel token", () => {
  expect(sanitizePreview("The run held at r=0.84 <|chan")!.text).toBe(
    "The run held at r=0.84",
  );
  expect(sanitizePreview("prose ends <channel|")!.text).toBe("prose ends");
  // Legit comparisons survive — a space/digit after "<" is not a token.
  expect(sanitizePreview("kept x < 5 in band")!.text).toBe(
    "kept x < 5 in band",
  );
});

it("sanitizePreview passes clean prose through and nulls markup-only/empty", () => {
  expect(sanitizePreview("plain prose")).toEqual({
    text: "plain prose",
    thought: false,
  });
  expect(sanitizePreview("")).toBeNull();
  expect(sanitizePreview(null)).toBeNull();
  expect(sanitizePreview(undefined)).toBeNull();
  // Nothing but markup → no preview, never a raw token.
  expect(sanitizePreview("<|channel|>")).toBeNull();
  expect(sanitizePreview("<|channel>thought")).toBeNull();
});

it("renders the gibberish preview as a thought chip + clean prose in the row", async () => {
  const gib = {
    ...CALLS,
    calls: [
      {
        ...CALLS.calls[1],
        request_id: "req-gib",
        completion_preview: OWNER_GIBBERISH,
      },
    ],
  };
  stubRoutes((url) =>
    url.includes("/api/model_io") && !url.includes("/api/model_io/")
      ? { status: 200, body: gib }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(1),
  );
  expect(screen.getByTestId("thought-chip")).toBeInTheDocument();
  const preview = screen.getByTestId("row-preview");
  expect(preview.textContent).toContain("This iteration investigated");
  expect(preview.textContent).not.toContain("<|channel>");
  expect(preview.textContent).not.toContain("<channel|>");
});

it("shows no thought chip on ordinary visible previews", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  expect(screen.queryByTestId("thought-chip")).toBeNull();
  expect(
    screen
      .getAllByTestId("row-preview")
      .some((el) => el.textContent === "The claim fails because"),
  ).toBe(true);
});

// ─── pagination (owner 2026-08-18: "show only last 20 interactions") ────

// NOTE (2026-08-19): these fixtures deliberately carry NO `next_before_ts`
// / `end_of_log` — they pin the VERSION-SKEW path, where a backend predating
// the paging coverage contract answers without them. That path is allowed to
// infer a boundary only because these payloads have no `threads`: with no
// thread there was no backfill walk, so the oldest call provably IS the
// page's fill point. The production contract path (stated boundary,
// interleaved rows, set-equality coverage) is pinned in
// tests/test_session_thread.tsx.

// A list-page URL (limit=20, no before_ts) vs an older-page URL.
const isListURL = (u: string) =>
  u.includes("/api/model_io?") && !u.includes("before_ts=");

const OLDER_ROW = {
  ...CALLS.calls[2],
  request_id: "req-0",
  ts: "2026-08-18T00:59:59Z",
  completion_preview: "an older completion",
};

it("fetches the newest page with limit=20 by default", async () => {
  const mock = stubRoutes(happyHandler);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  const listCalls = mock.mock.calls
    .map((c) => String(c[0]))
    .filter(isListURL);
  expect(listCalls.length).toBeGreaterThan(0);
  expect(listCalls.every((u) => u.includes("limit=20"))).toBe(true);
});

it("load older appends the next page via before_ts, deduped by request_id", async () => {
  const older = {
    ...CALLS,
    // A duplicate of an already-shown row must NOT render twice, and the
    // genuinely older row appends at the bottom.
    calls: [{ ...CALLS.calls[2] }, OLDER_ROW],
    window_truncated: false,
  };
  const mock = stubRoutes((url) =>
    url.includes("before_ts=")
      ? { status: 200, body: older }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(4),
  );
  // The request paged strictly older than the OLDEST visible row's ts.
  expect(
    mock.mock.calls.some((c) =>
      String(c[0]).includes(
        "before_ts=" + encodeURIComponent("2026-08-18T01:00:00Z"),
      ),
    ),
  ).toBe(true);
  // Appended below in order; the dupe rendered once.
  const rows = screen.getAllByTestId("modelio-row");
  expect(rows[3].textContent).toContain("an older completion");
  // 2 rows < PAGE_SIZE and not truncated → the log's beginning was reached.
  expect(screen.getByTestId("pager-end")).toBeInTheDocument();
  expect(screen.queryByTestId("load-older")).toBeNull();
});

it("reports 'older rows beyond scan window' when the byte cap stops paging", async () => {
  stubRoutes((url) =>
    url.includes("before_ts=")
      ? { status: 200, body: { ...CALLS, calls: [], window_truncated: true } }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getByTestId("pager-capped")).toBeInTheDocument(),
  );
  expect(screen.getByTestId("pager-capped").textContent).toContain(
    "older rows beyond scan window",
  );
  expect(screen.queryByTestId("load-older")).toBeNull();
  // The already-loaded rows stay on screen.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(3);
});

it("poll refresh keeps paged-older rows appended without duplicates", async () => {
  const older = { ...CALLS, calls: [OLDER_ROW], window_truncated: false };
  const mock = stubRoutes((url) =>
    url.includes("before_ts=")
      ? { status: 200, body: older }
      : happyHandler(url),
  );
  render(<ModelIO pollMs={60} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(4),
  );
  const listCallsBefore = mock.mock.calls.filter((c) =>
    isListURL(String(c[0])),
  ).length;
  // Wait for at least one more newest-page poll to land… (the pollhub
  // heartbeat paces repolls at 1s granularity, so a tiny pollMs still
  // waits out one heartbeat — hence the widened timeout).
  await waitFor(
    () =>
      expect(
        mock.mock.calls.filter((c) => isListURL(String(c[0]))).length,
      ).toBeGreaterThan(listCallsBefore),
    { timeout: 3000 },
  );
  // …still exactly 4 rows: newest page refreshed, older row kept once.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(4);
});

it("a filter change resets the paged-older rows and the pager state", async () => {
  const older = { ...CALLS, calls: [OLDER_ROW], window_truncated: false };
  stubRoutes((url) =>
    url.includes("before_ts=")
      ? { status: 200, body: older }
      : happyHandler(url),
  );
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(4),
  );
  fireEvent.change(screen.getByLabelText("filter by model"), {
    target: { value: "qwen" },
  });
  // Older pages were fetched under the OLD filter — dropped, and the
  // pager returns to its idle button.
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(3),
  );
  expect(screen.getByTestId("load-older")).toBeInTheDocument();
});


it("keeps call diagnostics separate from the single human-review destination", async () => {
  stubRoutes(happyHandler);
  render(<ModelIO />);
  await screen.findByTestId("modelio-table");
  expect(screen.getByRole("heading", { name: "Model I/O", level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Coordinator history" })).toHaveAttribute("href", "/cycles");
  expect(screen.getByRole("link", { name: "Open existing human review controls" })).toHaveAttribute("href", "/development#frontier-reviews");
  expect(screen.queryByTestId("agenda-accept")).not.toBeInTheDocument();
});

it("keeps the legacy suggestions anchor and query context as an explicit review handoff", async () => {
  window.history.replaceState({}, "", "/model-io?run_id=exact%2Fid#research-suggestions");
  try {
    stubRoutes(happyHandler);
    render(<ModelIO />);
    expect(document.getElementById("research-suggestions")).toHaveTextContent("Research suggestions and ruling history: Human reviews");
    expect(screen.getByRole("link", { name: "Open existing human review controls" })).toHaveAttribute("href", "/development?run_id=exact%2Fid#frontier-reviews");
    expect(screen.queryByTestId("agenda-accept")).not.toBeInTheDocument();
  } finally {
    window.history.replaceState({}, "", "/");
  }
});
