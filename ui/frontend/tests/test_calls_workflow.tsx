import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { resetPollHub, refreshPoll } from "../src/api/pollhub";
import type { ModelIOCall, ModelIOResponse } from "../src/api/modelIO";
import ModelIO from "../src/routes/ModelIO";

const call = (
  requestId: string,
  model: string,
  callerTag: string,
  completionPreview: string,
): ModelIOCall => ({
  ts: `2026-09-08T03:0${requestId === "req-alpha" ? "1" : "2"}:00Z`,
  request_id: requestId,
  parent_request_id: "iter-exact",
  model,
  backend: model.startsWith("qwen") ? "vllm-qwen" : "vllm-gemma",
  caller_tag: callerTag,
  run_id: "run/exact",
  latency_ms: 875,
  input_tokens: 41,
  output_tokens: 13,
  prompt_preview: "Inspect the exact call",
  completion_preview: completionPreview,
  empty: false,
});

const ALPHA = call(
  "req-alpha",
  "gemma-4-26b-a4b",
  "nara.run_iteration",
  '{"tool":"lookup","arguments":{"id":"paper-1"}}',
);
const BETA = call(
  "req-beta",
  "qwen3.8-27b-nvfp4-mtp",
  "skeptic_battery",
  "A concise recorded answer",
);

const page = (calls: ModelIOCall[]): ModelIOResponse => ({
  calls,
  source: "logs/calls.jsonl",
  window_truncated: false,
  scanned_bytes: 512,
  max_scan_bytes: 16_777_216,
  generated_at: "2026-09-08T03:03:00Z",
});

const detail = (row: ModelIOCall, completion: string) => ({
  found: true,
  call: {
    timestamp: row.ts,
    request_id: row.request_id,
    parent_request_id: row.parent_request_id,
    model: row.model,
    backend: row.backend,
    caller_tag: row.caller_tag,
    run_id: row.run_id,
    prompt_messages: [
      { role: "system", content: "Preserve <|channel>analysis exactly." },
      { role: "user", content: "Inspect paper-1 byte-for-byte." },
    ],
    completion,
    usage: { input_tokens: row.input_tokens, output_tokens: row.output_tokens },
    temperature: 0,
    seed: 7,
  },
});

const response = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  }) as Response;

function stubCalls(
  list: (url: string) => ModelIOResponse = () => page([BETA, ALPHA]),
) {
  const mock = vi.fn(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/api/model_io/req-alpha"))
      return response(detail(ALPHA, "alpha exact completion"));
    if (url.includes("/api/model_io/req-beta"))
      return response(detail(BETA, "beta exact completion"));
    if (url.includes("/api/model_io")) return response(list(url));
    return response({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  resetPollHub();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("opens one exact record, reveals raw payload on demand, and restores focus", async () => {
  stubCalls();
  render(<ModelIO pollMs={600_000} />);

  const opener = await screen.findByRole("button", {
    name: /Open record req-alpha/,
  });
  expect(opener.tagName).toBe("BUTTON");
  expect(opener).toHaveAttribute("aria-expanded", "false");
  expect(opener).toHaveAttribute("aria-controls", "modelio-selected-context");
  expect(screen.getByText("Structured payload recorded")).toBeInTheDocument();
  expect(screen.queryByTestId("raw-record-content")).toBeNull();

  opener.focus();
  fireEvent.click(opener);
  const context = await screen.findByTestId("modelio-context");
  const close = within(context).getByRole("button", {
    name: /Back to calls.*Close record/,
  });
  await waitFor(() => expect(document.activeElement).toBe(close));
  expect(opener).toHaveAttribute("aria-expanded", "true");
  expect(await within(context).findByText("alpha exact completion"))
    .toBeInTheDocument();

  fireEvent.click(within(context).getByText("Raw record"));
  const raw = await within(context).findByTestId("raw-record-content");
  expect(raw).toHaveTextContent("Preserve <|channel>analysis exactly.");
  expect(raw).toHaveTextContent("Inspect paper-1 byte-for-byte.");
  expect(raw).toHaveTextContent("alpha exact completion");
  expect(raw).toHaveTextContent('"seed": 7');

  fireEvent.click(close);
  await waitFor(() => expect(screen.queryByTestId("modelio-context")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(opener));
});

it("keeps the selected exact record while a filter replaces the feed", async () => {
  stubCalls((url) =>
    new URL(url).searchParams.get("model") === "qwen"
      ? page([BETA])
      : page([BETA, ALPHA]),
  );
  render(<ModelIO pollMs={600_000} />);

  const opener = await screen.findByRole("button", {
    name: /Open record req-alpha/,
  });
  fireEvent.click(opener);
  expect(await screen.findByText("alpha exact completion")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("filter by model"), {
    target: { value: "qwen" },
  });
  await waitFor(() => expect(screen.getAllByTestId("modelio-row")).toHaveLength(1));
  expect(screen.getByTestId("selection-retained")).toBeInTheDocument();
  const context = screen.getByTestId("modelio-context");
  expect(within(context).getByText("req-alpha")).toBeInTheDocument();
  expect(within(context).getByText("alpha exact completion"))
    .toBeInTheDocument();
});

it("does not let a late detail response replace a newer selection", async () => {
  const alpha = deferred<ReturnType<typeof detail>>();
  const beta = deferred<ReturnType<typeof detail>>();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes("/api/model_io/req-alpha"))
        return response(await alpha.promise);
      if (url.includes("/api/model_io/req-beta"))
        return response(await beta.promise);
      if (url.includes("/api/model_io")) return response(page([BETA, ALPHA]));
      return response({ detail: "not found" }, 404);
    }),
  );
  render(<ModelIO pollMs={600_000} />);

  const alphaOpener = await screen.findByRole("button", {
    name: /Open record req-alpha/,
  });
  const betaOpener = screen.getByRole("button", {
    name: /Open record req-beta/,
  });
  alphaOpener.focus();
  fireEvent.click(alphaOpener);
  betaOpener.focus();
  fireEvent.click(betaOpener);

  await act(async () => beta.resolve(detail(BETA, "beta arrived first")));
  expect(await screen.findByText("beta arrived first")).toBeInTheDocument();
  await act(async () => alpha.resolve(detail(ALPHA, "alpha arrived late")));

  const context = screen.getByTestId("modelio-context");
  expect(within(context).getByText("req-beta")).toBeInTheDocument();
  expect(within(context).getByText("beta arrived first")).toBeInTheDocument();
  expect(within(context).queryByText("alpha arrived late")).toBeNull();

  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByTestId("modelio-context")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(betaOpener));
});


it.each([
  { found: true, call: { request_id: "wrong-id", completion: "WRONG SECRET" } },
  { found: false, call: { request_id: "req-alpha", completion: "WRONG SECRET" } },
  { found: true, call: [] },
  { found: true, call: { request_id: "req-alpha", prompt_messages: [null], completion: "WRONG SECRET" } },
])("withholds malformed or unbound exact detail without attributing its content: %j", async (body) => {
  vi.stubGlobal("fetch", vi.fn(async (input: unknown) => response(String(input).includes("/api/model_io/req-alpha") ? body : page([ALPHA]))));
  render(<ModelIO pollMs={600_000} />);
  fireEvent.click(await screen.findByRole("button", { name: /Open record req-alpha/ }));
  expect(await screen.findByText(/Exact record is unverified/)).toBeInTheDocument();
  expect(screen.queryByText("WRONG SECRET")).toBeNull();
  expect(screen.queryByTestId("call-expansion")).toBeNull();
  fireEvent.click(screen.getByText("Raw record"));
  expect(await screen.findByTestId("raw-record-content")).toHaveTextContent(JSON.stringify(body, null, 2).replace(/\s+/g, " "));
});

it("does not turn an omitted completion into a recorded empty output", async () => {
  const body = detail(ALPHA, "unused");
  delete (body.call as Partial<typeof body.call>).completion;
  vi.stubGlobal("fetch", vi.fn(async (input: unknown) => response(String(input).includes("/api/model_io/req-alpha") ? body : page([ALPHA]))));
  render(<ModelIO pollMs={600_000} />);
  fireEvent.click(await screen.findByRole("button", { name: /Open record req-alpha/ }));
  expect(await screen.findByText("Completion text was not supplied; this is not a recorded empty completion.")).toBeInTheDocument();
});


it.each([
  { fixture_malformed: true },
  { calls: [null] },
  { calls: [{ ...ALPHA, model: { forged: true } }] },
  { calls: [], threads: [null] },
  { calls: [], threads: [{ session_id: "t", turns: [null] }] },
])("refuses unreadable current feed %j without inferring zero or matching absence", async body => {
  vi.stubGlobal("fetch", vi.fn(async () => response(body)));
  render(<ModelIO pollMs={600_000} />);
  expect(await screen.findByText(/unreachable or unreadable/)).toBeInTheDocument();
  expect(screen.getByTestId("modelio-result-count")).toHaveTextContent("Count unavailable");
  expect(screen.queryByText("no calls match in the log tail.")).toBeNull();
});


it("retains the last good rows when a later 200 feed is unreadable", async () => {
  let body: unknown = page([ALPHA]);
  vi.stubGlobal("fetch", vi.fn(async () => response(body)));
  render(<ModelIO pollMs={600_000} />);
  await screen.findByRole("button", { name: /Open record req-alpha/ });
  body = { calls: null };
  await act(async () => { refreshPoll('modelio:calls:["","",""]'); });
  expect(await screen.findByText(/unreachable or unreadable/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Open record req-alpha/ })).toBeInTheDocument();
  expect(screen.getByTestId("modelio-result-count")).toHaveTextContent("1 visible record");
  expect(screen.getByTestId("modelio-freshness")).toHaveTextContent("Refresh failed");
});

it("refuses a malformed older page without inferring the beginning of the log", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: unknown) => response(String(input).includes("before_ts=") ? { calls: null } : { ...page([ALPHA]), next_before_ts: "2026-09-08T00:00:00Z", end_of_log: false })));
  render(<ModelIO pollMs={600_000} />);
  fireEvent.click(await screen.findByTestId("load-older"));
  expect(await screen.findByText("older-page fetch failed — the button retries.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Open record req-alpha/ })).toBeInTheDocument();
  expect(screen.queryByTestId("pager-end")).toBeNull();
});


it("labels retained rows as the previous filter while a new query is pending", async () => {
  let release!: (value: Response) => void;
  const pending = new Promise<Response>(resolve => { release = resolve; });
  const mock = vi.fn(async (input: unknown) => String(input).includes("model=qwen") ? pending : response(page([ALPHA])));
  vi.stubGlobal("fetch", mock);
  render(<ModelIO pollMs={600_000} />);
  await screen.findByRole("button", { name: /Open record req-alpha/ });
  fireEvent.change(screen.getByRole("textbox", { name: "filter by model" }), { target: { value: "qwen" } });
  expect(await screen.findByText(/Showing retained rows from the previous filter/)).toBeInTheDocument();
  expect(screen.getByTestId("modelio-result-count")).toHaveTextContent("1 retained record");
  await waitFor(() => expect(mock.mock.calls.some(([url]) => String(url).includes("model=qwen"))).toBe(true));
  expect(screen.getByTestId("modelio-result-count")).toHaveTextContent("1 retained record");
  await act(async () => { release(response(page([BETA]))); });
  await screen.findByRole("button", { name: /Open record req-beta/ });
  expect(screen.queryByText(/Showing retained rows from the previous filter/)).toBeNull();
  expect(screen.getByTestId("modelio-result-count")).toHaveTextContent("1 visible record");
});
