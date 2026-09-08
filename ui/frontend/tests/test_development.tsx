import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import LabTodo from "../src/components/LabTodo";
import DevelopmentNotice from "../src/components/DevelopmentNotice";
import { developmentReceipt } from "../src/data/developmentReceipt";

const clusters = [
  ...Array.from({ length: 77 }, (_, i) => ({ cluster_id: `open-zero-${i}`, status: "open", evidence_level: "L0" })),
  ...Array.from({ length: 3 }, (_, i) => ({ cluster_id: `open-one-${i}`, status: "open", evidence_level: "L1" })),
  ...Array.from({ length: 119 }, (_, i) => ({ cluster_id: `killed-zero-${i}`, status: "killed", evidence_level: "L0" })),
  { cluster_id: "killed-two", status: "killed", evidence_level: "L2" },
].map((c) => ({ ...c, last_event_ts: "2026-09-05T11:00:16Z" }));
const ladder = { clusters, counts: { open: 80, surfaced: 0, killed: 120 }, histogram: { L0: 77, L1: 3, L2: 0, L3: 0, L4: 0, L5: 0 }, agenda: [], next_owed: { L1: "valid experiment and independent confirmation" } };
const proposals = Array.from({ length: 23 }, (_, i) => ({ type: "agenda", proposal_id: `proposal-${i}`, topic: `Unresolved suggestion ${i}`, ts: "2026-08-30T05:30:02Z", status: "proposed", effective_status: "proposed" }));
const completeIntegrity = { complete: true, missing: false, truncated: false, errors: [] };
const frontier = { integrity: { agenda: completeIntegrity, agenda_status: completeIntegrity }, available: { agenda: true }, events: proposals, events_in_window: 23, windows: { agenda: { truncated: false } }, generated_at: "2026-09-05T11:05:00Z" };
const channel = { integrity: { schema: "lab-channel-timeline/v1", framing: "json-envelope", status: "framed", actor_labels: "recorded_not_authenticated" }, rows: [
  { kind: "nara", ts: "2026-09-05T06:36:34Z", message: "Recorded Nara reply" },
  { kind: "oracle", ts: "2026-09-05T07:00:00Z", message: "Engineering handoff" },
  { kind: "event", ts: "2026-09-05T11:00:16Z", message: "Newer derived runtime event" },
] };

let failReads = false;
let overrides: Record<string, unknown>;
let calls: string[];

beforeEach(() => {
  window.history.replaceState({}, "", "/development");
  failReads = false;
  overrides = {};
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin);
    calls.push(url.pathname + url.search);
    if (init?.method && init.method !== "GET") throw new Error("Unexpected write request");
    if (url.pathname === "/api/lab_todo") throw new Error("Heavy queue inspection forbidden");
    if (failReads) return new Response("offline", { status: 503 });
    if (url.pathname in overrides) {
      const value = overrides[url.pathname];
      return value === null ? new Response(null, { status: 204 }) : Response.json(value);
    }
    const bodies: Record<string, unknown> = {
      "/api/ladder": ladder,
      "/api/frontier_reviews": frontier,
      "/api/channel/timeline": channel,
      "/api/health": { ok: true, version: "loaded-backend-sha" },
      "/api/loop_alert": { level: "ok", updated_at: new Date().toISOString() },
    };
    return url.pathname in bodies ? Response.json(bodies[url.pathname]) : new Response("not found", { status: 404 });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); window.history.replaceState({}, "", "/"); });

async function ready() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Read latest snapshots" })).toBeEnabled());
}

describe("LAB014 provenance and StrictMode regressions", () => {
  it("uses integrity truncation even without legacy window metadata", async () => {
    overrides["/api/frontier_reviews"] = { ...frontier, windows: undefined, events_in_window: undefined,
      integrity: { ...frontier.integrity, agenda: { ...completeIntegrity, complete: false, truncated: true } } };
    render(<App />);
    await ready();
    expect(screen.getByText(/Partial feed window/)).toBeInTheDocument();
  });

  it.each([undefined, null, "unknown", ["accepted"]])("withholds counts for non-current effective status %j", async (effective_status) => {
    overrides["/api/frontier_reviews"] = { ...frontier, events: [{ ...proposals[0], effective_status }] };
    render(<App />);
    await ready();
    expect(screen.getByText(/Agenda status is uncertain/)).toBeInTheDocument();
    expect(screen.queryByText(/Loaded proposals:/)).not.toBeInTheDocument();
  });

  it("uses complete integrity without requiring legacy availability metadata", async () => {
    overrides["/api/frontier_reviews"] = { ...frontier, available: undefined };
    render(<App />);
    await ready();
    expect(screen.getByText(/23 unresolved/)).toBeInTheDocument();
  });

  it("retains suggestions but withholds current status on a reported source error", async () => {
    overrides["/api/frontier_reviews"] = { ...frontier, integrity: {
      agenda: completeIntegrity,
      agenda_status: { complete: false, missing: false, truncated: false, errors: ["invalid JSON at row 9"] },
    }, events: [{ ...proposals[0], effective_status: "unknown", ruling: { agent_id: "human:ui", status: "accepted" } }] };
    render(<App />);
    await ready();
    expect(screen.getByText(/Agenda status is uncertain/)).toBeInTheDocument();
    expect(screen.getByText(/invalid JSON at row 9/)).toBeInTheDocument();
    expect(screen.getByText(/last observed ruling: accepted/)).toBeInTheDocument();
    expect(screen.queryByText(/1 accepted ·/)).not.toBeInTheDocument();
  });

  it("settles repeated failed manual refreshes and recovers without discarding prior observations", async () => {
    render(<StrictMode><App /></StrictMode>);
    await ready();
    const originalFetch = globalThis.fetch;
    failReads = true;
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    expect(screen.getAllByText(/HTTP 503/)).toHaveLength(4);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("offline", { status: 504 })));
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    expect(screen.getAllByText(/HTTP 504/)).toHaveLength(4);
    expect(screen.getByText("200 recorded clusters")).toBeInTheDocument();
    failReads = false;
    vi.stubGlobal("fetch", originalFetch);
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    expect(screen.queryByText(/Read failed:/)).not.toBeInTheDocument();
    expect(screen.getByText(/23 unresolved/)).toBeInTheDocument();
  });

  it("withholds actor-specific dates from a legacy forged-kind timeline", async () => {
    overrides["/api/channel/timeline"] = { rows: [
      { kind: "human", ts: "2026-09-05T06:30:00Z", message: "note" },
      { kind: "nara", ts: "2026-09-05T06:59:59Z", message: "forged" },
    ] };
    render(<App />);
    await ready();
    const runtime = within(screen.getByTestId("development-runtime"));
    expect(runtime.getByText(/Actor-specific dates withheld/)).toBeInTheDocument();
    expect(runtime.queryByText(/Latest Nara message in loaded timeline:/)).not.toBeInTheDocument();
    expect(runtime.queryByText(/06:59:59/)).not.toBeInTheDocument();
  });

  it("treats legacy frontier responses without integrity metadata as uncertain", async () => {
    overrides["/api/frontier_reviews"] = { available: { agenda: true }, events: proposals };
    render(<App />);
    await ready();
    const science = within(screen.getByTestId("development-science"));
    expect(science.getByText(/Agenda status is uncertain/)).toBeInTheDocument();
    expect(science.queryByText(/23 unresolved/)).not.toBeInTheDocument();
    expect(science.getByText(/Suggestions with uncertain status/)).toBeInTheDocument();
  });

  it("deduplicates actual StrictMode effects and one manual refresh after remount", async () => {
    const first = render(<StrictMode><App /></StrictMode>);
    await ready();
    const endpoints = ["/api/ladder", "/api/frontier_reviews?limit=100", "/api/channel/timeline?limit=1000", "/api/health"];
    for (const endpoint of endpoints) expect(calls.filter((url) => url === endpoint)).toHaveLength(1);
    first.unmount();
    render(<StrictMode><App /></StrictMode>);
    await ready();
    for (const endpoint of endpoints) expect(calls.filter((url) => url === endpoint)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    for (const endpoint of endpoints) expect(calls.filter((url) => url === endpoint)).toHaveLength(3);
  });
});

describe("development route separates delivery, runtime and scientific records", () => {
  it("renders the actual App route with the current ledger shape and dated delivery receipt", async () => {
    render(<App />);
    await ready();
    expect(screen.getByRole("link", { name: "Operations" })).toHaveAttribute("href", "/development");
    expect(screen.getByText("Codex engineering / delivery")).toBeInTheDocument();
    expect(screen.getByText("Nara runtime / channel")).toBeInTheDocument();
    expect(screen.getByText("Scientific evidence / agenda")).toBeInTheDocument();
    const science = within(screen.getByTestId("development-science"));
    expect(science.getByText("200 recorded clusters")).toBeInTheDocument();
    expect(science.getByText(/23 unresolved · 0 accepted · 0 dismissed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Research review/ }));
    fireEvent.click(screen.getByText("Recorded classifications and next tests"));
    const l0 = science.getByRole("row", { name: /L0 77 0 119/ });
    expect(l0).toBeInTheDocument();
    expect(science.getByRole("row", { name: /L1 3 0 0 valid experiment and independent confirmation/ })).toBeInTheDocument();
    expect(science.getByRole("row", { name: /L2 0 0 1/ })).toBeInTheDocument();
    expect(screen.getByText(/Static receipt recorded 2026-09-05T22:51:41Z/)).toBeInTheDocument();
    expect(screen.getByText(/Published source at receipt:/)).toHaveTextContent(developmentReceipt.head);
    expect(screen.getByText(/not revalidated experiment eligibility/)).toBeInTheDocument();
    expect(screen.getByText(/Deployed frontend commit is not reported/)).toBeInTheDocument();
    expect(screen.getByTestId("development-runtime")).toHaveTextContent("Running backend revision: loaded-backend-sha");
    expect(screen.getByText(/Latest Nara message in loaded timeline:/)).toHaveTextContent("2026-09-05T06:36:34Z");
    expect(screen.getByText(/Latest Nara message in loaded timeline:/)).not.toHaveTextContent("11:00:16");
    expect(screen.getByText(/Latest channel turn in loaded timeline:/)).toHaveTextContent("2026-09-05T07:00:00Z");
    expect(screen.getByText(/Latest recorded cluster event/)).toHaveTextContent("2026-09-05T11:00:16Z");
    expect(screen.getByText(/Historical binding audit/)).toBeInTheDocument();
    expect(screen.getByText(/291 historical iterations/)).toHaveTextContent("144 mismatch, 147 unverifiable");
    expect(screen.getByText(/Qwen worker remains held/)).toBeInTheDocument();
    expect(calls).toContain("/api/frontier_reviews?limit=100");
    expect(calls).toContain("/api/channel/timeline?limit=1000");
    expect(calls.some((url) => /lab_todo|\/turn|\/delegate|\/accept|\/dismiss/.test(url))).toBe(false);
  });

  it("keeps previous observations after a failed refresh and names current state unknown", async () => {
    render(<App />);
    await ready();
    failReads = true;
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    expect(screen.getByText("200 recorded clusters")).toBeInTheDocument();
    expect(screen.getAllByText(/Showing the previous observation; current state is unknown/)).toHaveLength(4);
    expect(screen.getAllByText(/Browser read in progress: no/)).toHaveLength(4);
    expect(screen.getByText(/Frontier projection generated:/)).toHaveTextContent("2026-09-05T11:05:00Z");
  });

  it("does not substitute historical totals for missing or invalid current sources", async () => {
    overrides["/api/ladder"] = null;
    overrides["/api/frontier_reviews"] = { available: { agenda: false }, events: [] };
    overrides["/api/channel/timeline"] = { rows: [{ kind: "event", ts: "2026-09-05T11:00:16Z" }] };
    render(<App />);
    await ready();
    expect(screen.getByText(/Recorded counts unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/0 recorded clusters|198 recorded clusters|200 recorded clusters/)).not.toBeInTheDocument();
    expect(screen.getByText(/unresolved suggestions are not cleared/)).toBeInTheDocument();
    expect(screen.getByText(/Actor-specific dates withheld/)).toBeInTheDocument();
    expect(screen.getByText(/no message was found in that window/)).toBeInTheDocument();
  });

  it("rejects a foreign ladder body instead of silently displaying zero counts", async () => {
    overrides["/api/ladder"] = { clusters: [] };
    render(<App />);
    await ready();
    expect(screen.getByText(/Recorded counts missing or invalid/)).toBeInTheDocument();
    expect(screen.queryByText("0 recorded clusters")).not.toBeInTheDocument();
  });

  it("makes readiness reachable through the real keyboard command palette", async () => {
    render(<App />);
    await ready();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const palette = within(screen.getByTestId("command-palette"));
    fireEvent.click(palette.getByText("Operations delivery"));
    expect(window.location.pathname).toBe("/development");
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    expect(screen.getByTestId("development-page")).toBeInTheDocument();
  });

  it("does not confuse a truncated invocation log with a partial proposal window", async () => {
    overrides["/api/frontier_reviews"] = { ...frontier, windows: { agenda: { truncated: false }, calls: { truncated: true } } };
    render(<App />);
    await ready();
    expect(screen.getByText(/23 unresolved/)).toBeInTheDocument();
    expect(screen.queryByText(/Partial feed window/)).not.toBeInTheDocument();
  });

  it("keeps queue cache age, gap source age, rebuild activity and error separate without fetching", () => {
    render(<LabTodo initial={{
      generated_at: "2026-09-05T11:05:00Z", gaps_as_of: "2026-08-30T05:00:00Z", gaps_source: "last_cycle",
      cache_age_s: 180, refresh_error: "fixture rebuild failed", owed: [], agenda: [],
    }} />);
    const metadata = within(screen.getByTestId("lab-todo-source-state"));
    expect(metadata.getByText(/Queue payload generated:/)).toHaveTextContent("2026-09-05T11:05:00Z");
    expect(metadata.getByText(/Gap source timestamp:/)).toHaveTextContent("2026-08-30T05:00:00Z");
    expect(metadata.getByText(/Backend cache age at last read:/)).toHaveTextContent("180 seconds");
    expect(metadata.getByText(/Backend rebuild in progress:/)).toHaveTextContent("not reported by this endpoint");
    expect(metadata.getByText(/Last backend rebuild error:/)).toHaveTextContent("fixture rebuild failed");
    expect(calls).toEqual([]);
  });

  it("keeps older unresolved rows visible and respects effective human rulings in a partial window", async () => {
    overrides["/api/frontier_reviews"] = {
      ...frontier,
      events: [
        { ...proposals[0], ts: "2026-09-05T10:00:00Z", effective_status: "accepted" },
        ...proposals,
      ],
      events_in_window: 125,
      windows: { agenda: { truncated: true } },
    };
    render(<App />);
    await ready();
    expect(screen.getByText(/22 unresolved · 1 accepted · 0 dismissed/)).toBeInTheDocument();
    expect(screen.getByText(/Partial feed window/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Older unresolved suggestions (22)"));
    expect(screen.getByText("Unresolved suggestion 22")).toBeInTheDocument();
    expect(screen.queryByText("Unresolved suggestion 0")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept|dismiss/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Research review/ }));
    expect(screen.getByRole("link", { name: /Review suggestions and human ruling controls/ })).toHaveAttribute("href", "#frontier-reviews");
  });
});


describe("LAB017 visible delivery and loaded-source distinctions", () => {
  it("shows merged UI delivery separately from the older held package on the actual route", async () => {
    render(<App />);
    await ready();
    const engineering = within(screen.getByTestId("development-engineering"));
    expect(engineering.getByText("UI delivered: clearer provenance and stable thread history")).toBeInTheDocument();
    fireEvent.click(engineering.getByText("Historical UI delivery receipt"));
    expect(engineering.getByRole("link", { name: /Merged UI work — PR #5/ })).toHaveAttribute("href", "https://github.com/decross1/a_bgt_rsi/pull/5");
    expect(engineering.getByText(/UI source merge:/)).toHaveTextContent("858cfb10656cc370e3fdf0018a6e45fd5d05e997");
    expect(engineering.getByText(/Dated UI observation:/)).toHaveTextContent("not live deployment status");
    expect(engineering.getByText(/Earlier core package — PR #3 remains separate/)).toBeInTheDocument();
    fireEvent.click(engineering.getByText("Earlier package receipt and next evidence"));
    expect(engineering.getByRole("link", { name: /PR #3 package status/ })).toHaveAttribute("href", developmentReceipt.pr);
    expect(engineering.getByText(/Qwen worker remains held/)).toBeInTheDocument();
    expect(engineering.queryByRole("link", { name: /current delivery status/ })).not.toBeInTheDocument();
  });

  it("gives Pulse a dated UI outcome while keeping the separate core hold visible", () => {
    render(<DevelopmentNotice />);
    expect(screen.getByRole("link", { name: /UI delivered: clearer provenance and stable thread history/ })).toHaveAttribute("href", "/development");
    expect(screen.getByText(/PR #5 merged; PR #3 core work remains separate and held/)).toBeInTheDocument();
    expect(screen.getByText(/not live merge or deployment status/)).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("describes loaded legacy proposals as unverified rather than unavailable", async () => {
    overrides["/api/frontier_reviews"] = { available: { agenda: true }, events: proposals };
    render(<App />);
    await ready();
    const science = within(screen.getByTestId("development-science"));
    expect(science.getByText(/23 proposal records in this observation; current rulings unverified/)).toBeInTheDocument();
    expect(science.queryByText(/Proposal source unavailable/)).not.toBeInTheDocument();
    expect(science.queryByText(/23 unresolved/)).not.toBeInTheDocument();
    expect(science.getByText("Unresolved suggestion 22")).toBeInTheDocument();
    expect(calls.some((url) => /lab_todo|accept|dismiss/.test(url))).toBe(false);
  });

  it("retains the distinction after a failed refresh instead of claiming new source evidence", async () => {
    render(<App />);
    await ready();
    failReads = true;
    fireEvent.click(screen.getByRole("button", { name: "Read latest snapshots" }));
    await ready();
    const science = within(screen.getByTestId("development-science"));
    expect(science.getByText(/23 proposal records in this observation; current rulings unverified/)).toBeInTheDocument();
    expect(science.getAllByText(/Showing the previous observation; current state is unknown/)).toHaveLength(2);
    expect(science.queryByText(/23 unresolved/)).not.toBeInTheDocument();
  });
});


it("replaces the three report columns with one selected context and keeps evidence discoverable", async () => {
  render(<App />);
  await ready();
  expect(screen.getByTestId("development-engineering")).toBeVisible();
  expect(screen.getByTestId("development-runtime")).not.toBeVisible();
  expect(screen.getByTestId("development-science")).not.toBeVisible();
  expect(screen.queryByRole("region", { name: "Readiness at a glance" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Runtime observations/ }));
  expect(screen.getByTestId("development-runtime")).toBeVisible();
  expect(screen.getByTestId("development-engineering")).not.toBeVisible();
  expect(window.location.hash).toBe("#runtime-evidence");
  fireEvent.click(screen.getByRole("button", { name: /Research review/ }));
  expect(screen.getByTestId("development-science")).toBeVisible();
  expect(screen.getByRole("link", { name: /Inspect the ladder/ })).toHaveAttribute("href", "/ladder");
  expect(calls.some((path) => path.startsWith("/api/lab_todo"))).toBe(false);
});

it("opens the existing guarded review only on its explicit deep link and allows pausing updates", async () => {
  render(<App />);
  await ready();
  expect(screen.queryByRole("button", { name: "Pause review updates" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Open human review controls" }));
  expect(window.location.hash).toBe("#frontier-reviews");
  expect(screen.getByRole("region", { name: "Human review controls" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Pause review updates" }));
  expect(screen.getByRole("button", { name: "Resume review updates" })).toHaveAttribute("aria-pressed", "true");
  expect(calls.some((path) => /accept|dismiss/.test(path))).toBe(false);
});
