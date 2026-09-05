import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import LabTodo from "../src/components/LabTodo";
import { developmentReceipt } from "../src/data/developmentReceipt";

const clusters = [
  ...Array.from({ length: 77 }, (_, i) => ({ cluster_id: `open-zero-${i}`, status: "open", evidence_level: "L0" })),
  ...Array.from({ length: 3 }, (_, i) => ({ cluster_id: `open-one-${i}`, status: "open", evidence_level: "L1" })),
  ...Array.from({ length: 119 }, (_, i) => ({ cluster_id: `killed-zero-${i}`, status: "killed", evidence_level: "L0" })),
  { cluster_id: "killed-two", status: "killed", evidence_level: "L2" },
].map((c) => ({ ...c, last_event_ts: "2026-09-05T11:00:16Z" }));
const ladder = { clusters, counts: { open: 80, surfaced: 0, killed: 120 }, histogram: { L0: 77, L1: 3, L2: 0, L3: 0, L4: 0, L5: 0 }, agenda: [], next_owed: { L1: "valid experiment and independent confirmation" } };
const proposals = Array.from({ length: 23 }, (_, i) => ({ type: "agenda", proposal_id: `proposal-${i}`, topic: `Unresolved suggestion ${i}`, ts: "2026-08-30T05:30:02Z", status: "proposed", effective_status: "proposed" }));
const frontier = { available: { agenda: true }, events: proposals, events_in_window: 23, windows: { agenda: { truncated: false } }, generated_at: "2026-09-05T11:05:00Z" };
const channel = { rows: [
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

describe("development route separates delivery, runtime and scientific records", () => {
  it("renders the actual App route with the current ledger shape and dated delivery receipt", async () => {
    render(<App />);
    await ready();
    expect(screen.getByRole("link", { name: "development" })).toHaveAttribute("href", "/development");
    expect(screen.getByText("Codex engineering / delivery")).toBeInTheDocument();
    expect(screen.getByText("Nara runtime / channel")).toBeInTheDocument();
    expect(screen.getByText("Scientific evidence / agenda")).toBeInTheDocument();
    const science = within(screen.getByTestId("development-science"));
    expect(science.getByText("200 recorded clusters")).toBeInTheDocument();
    expect(science.getByText(/23 unresolved · 0 accepted · 0 dismissed/)).toBeInTheDocument();
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
    expect(screen.getByText(/Latest Nara message in loaded timeline:/)).toHaveTextContent("not reported");
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
    fireEvent.click(palette.getByText("development"));
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
    expect(screen.getByRole("link", { name: /human ruling controls/ })).toHaveAttribute("href", "/model-io");
  });
});
