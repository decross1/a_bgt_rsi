// NowBoard — the D-047 multi-run board on /activity (handoff Task 1). One
// card per run from GET /api/activity/active_runs: kind chip, label,
// current_step, progress, stale-heartbeat amber past 120s (a legacy_mirror
// run is judged on its freshest timestamp), an honest empty state, and the
// quiet EndpointMissingNote on a version-skew 404. All run docs here are
// CONSTRUCTED (explicitly synthetic), shaped exactly like
// run_state/active_runs/*.json; fetches are stubbed — no live backend.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import NowBoard, { staleRefMs } from "../src/components/NowBoard";
import type { ActiveRun } from "../src/types/activity";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// Fixed clock; timestamps are aged relative to it.
const NOW = Date.parse("2026-06-10T12:00:00.000Z");
const FRESH = "2026-06-10T11:59:30.000Z"; // 30s ago — inside the 120s window
const STALE = "2026-06-10T11:55:00.000Z"; // 300s ago — past the 120s window

const REGISTRY_RUN: ActiveRun = {
  run_id: "exp009_cournot_0610",
  kind: "experiment",
  label: "exp009 cournot duopoly",
  started_at: "2026-06-10T11:30:00.000Z",
  current_step: "play_round",
  step_started_at: "2026-06-10T11:58:00.000Z",
  progress: { done: 4, total: 12, unit: "rounds" },
  heartbeat_at: FRESH,
};

describe("NowBoard cards", () => {
  it("renders one card per run: kind chip, label, current_step, progress", () => {
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          runs: [
            REGISTRY_RUN,
            {
              run_id: "coordinator_ab12cd34",
              kind: "coordinator",
              label: "coordinator cycle",
              started_at: "2026-06-10T11:59:00.000Z",
              heartbeat_at: FRESH,
            },
          ],
          skipped: 0,
        }}
      />,
    );
    const board = screen.getByTestId("now-board");
    expect(board).toHaveTextContent("2 registered runs");
    const card = screen.getByTestId("now-run-exp009_cournot_0610");
    expect(card).toHaveTextContent("experiment");
    expect(card).toHaveTextContent("exp009 cournot duopoly");
    expect(card).toHaveTextContent("play_round");
    expect(card).toHaveTextContent("4/12 rounds");
    expect(card).toHaveAttribute("data-stale", "false");
    // Unknown-to-this-build kinds render RAW (never filtered/normalized).
    expect(screen.getByTestId("now-run-coordinator_ab12cd34")).toHaveTextContent(
      "coordinator",
    );
  });

  it("stale heartbeat (now - heartbeat_at > 120s) renders the amber state", () => {
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          runs: [{ ...REGISTRY_RUN, heartbeat_at: STALE }],
          skipped: 0,
        }}
      />,
    );
    const card = screen.getByTestId("now-run-exp009_cournot_0610");
    expect(card).toHaveAttribute("data-stale", "true");
    expect(card.className).toContain("amber");
    expect(
      screen.getByTestId("now-run-stale-exp009_cournot_0610"),
    ).toHaveTextContent(/stale heartbeat/i);
  });

  it("a registry run WITHOUT heartbeat_at makes no staleness claim", () => {
    // Old timestamps but no heartbeat field: unknown is not stale — the
    // board must not invent a verdict it has no signal for.
    const { heartbeat_at: _omitted, ...rest } = REGISTRY_RUN;
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          runs: [{ ...rest, started_at: STALE, step_started_at: STALE }],
          skipped: 0,
        }}
      />,
    );
    expect(screen.getByTestId("now-run-exp009_cournot_0610")).toHaveAttribute(
      "data-stale",
      "false",
    );
  });

  it("legacy_mirror run is judged on its FRESHEST timestamp", () => {
    // Pre-D-047 mirror wrap: no heartbeat semantics. An old started_at with
    // a fresh step_started_at is a LIVE run (freshest wins)…
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          runs: [
            {
              run_id: "exp003-legacy",
              kind: "experiment",
              label: "exp003 paraphrase probe",
              started_at: STALE,
              step_started_at: FRESH,
              legacy_mirror: true,
            },
          ],
          skipped: 0,
        }}
      />,
    );
    const fresh = screen.getByTestId("now-run-exp003-legacy");
    expect(fresh).toHaveAttribute("data-stale", "false");
    expect(screen.getByTestId("legacy-mirror-chip")).toHaveTextContent(
      /legacy mirror/i,
    );
  });

  it("legacy_mirror with every timestamp old IS stale", () => {
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          runs: [
            {
              run_id: "exp003-legacy",
              kind: "experiment",
              label: "exp003 paraphrase probe",
              started_at: STALE,
              step_started_at: STALE,
              legacy_mirror: true,
            },
          ],
          skipped: 0,
        }}
      />,
    );
    expect(screen.getByTestId("now-run-exp003-legacy")).toHaveAttribute(
      "data-stale",
      "true",
    );
  });

  it("empty runs render the honest empty state — never an invented run", () => {
    render(<NowBoard nowMs={NOW} initial={{ runs: [], skipped: 0 }} />);
    expect(screen.getByTestId("now-board-empty")).toHaveTextContent(
      /no registered runs/i,
    );
    expect(document.querySelectorAll('[data-testid^="now-run-"]')).toHaveLength(0);
  });

  it("initial={null} (no payload) renders nothing at all", () => {
    const { container } = render(<NowBoard nowMs={NOW} initial={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("surfaces the backend's skipped count and drops malformed run entries", () => {
    render(
      <NowBoard
        nowMs={NOW}
        initial={{
          // Malformed rows a degraded payload could carry — dropped, not a crash.
          runs: [null, "not-a-run", REGISTRY_RUN] as unknown as ActiveRun[],
          skipped: 2,
        }}
      />,
    );
    expect(screen.getByTestId("now-board-skipped")).toHaveTextContent(
      "2 unreadable run files skipped",
    );
    expect(document.querySelectorAll('[data-testid^="now-run-"]')).toHaveLength(1);
  });
});

describe("NowBoard version skew / errors (self-poll, stubbed fetch)", () => {
  it("a 404 on /api/activity/active_runs renders the quiet skew note, never red", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: RequestInfo | URL) => {
        const u = String(url);
        if (u.includes("/api/health")) {
          return {
            ok: true,
            status: 200,
            statusText: "OK",
            json: async () => ({
              ok: true,
              hostname: "spark",
              telemetry_last_seen: null,
              version: "73b431b",
            }),
          } as Response;
        }
        return {
          ok: false,
          status: 404,
          statusText: "Not Found",
          json: async () => ({ detail: "Not Found" }),
        } as Response;
      }),
    );
    render(<NowBoard live nowMs={NOW} />);
    const note = await waitFor(() =>
      screen.getByTestId("endpoint-missing-note"),
    );
    expect(note).toHaveTextContent("/api/activity/active_runs");
    expect(note).toHaveTextContent(/endpoint not in this backend build/);
    await waitFor(() => expect(note).toHaveTextContent("sha 73b431b"));
    expect(note.className).not.toContain("red");
    expect(screen.queryByTestId("now-board-error")).toBeNull();
  });

  it("a 500 stays a red error — not the skew note", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({ detail: "registry unreadable" }),
      } as Response),
    );
    render(<NowBoard live nowMs={NOW} />);
    const err = await waitFor(() => screen.getByTestId("now-board-error"));
    expect(err).toHaveTextContent("500");
    expect(err.className).toContain("red");
    expect(screen.queryByTestId("endpoint-missing-note")).toBeNull();
  });

  it("a 200 payload renders the board from the live poll", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        json: async () => ({
          runs: [REGISTRY_RUN],
          skipped: 0,
          generated_at: FRESH,
        }),
      } as Response),
    );
    render(<NowBoard live nowMs={NOW} />);
    await waitFor(() =>
      expect(
        screen.getByTestId("now-run-exp009_cournot_0610"),
      ).toBeInTheDocument(),
    );
  });

  it("does not fetch when not live (static render gate)", () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const { container } = render(<NowBoard nowMs={NOW} />);
    expect(spy).not.toHaveBeenCalled();
    expect(container.firstChild).toBeNull();
  });
});

describe("staleRefMs", () => {
  it("registry run: heartbeat_at only; absent/unparseable -> null", () => {
    expect(staleRefMs(REGISTRY_RUN)).toBe(Date.parse(FRESH));
    const { heartbeat_at: _omitted, ...rest } = REGISTRY_RUN;
    expect(staleRefMs(rest as ActiveRun)).toBeNull();
    expect(
      staleRefMs({ ...REGISTRY_RUN, heartbeat_at: "not-a-time" }),
    ).toBeNull();
  });

  it("legacy_mirror: freshest of heartbeat/step_started/started", () => {
    expect(
      staleRefMs({
        run_id: "r",
        kind: "experiment",
        label: "l",
        started_at: STALE,
        step_started_at: FRESH,
        legacy_mirror: true,
      }),
    ).toBe(Date.parse(FRESH));
    expect(
      staleRefMs({
        run_id: "r",
        kind: "experiment",
        label: "l",
        started_at: STALE,
        legacy_mirror: true,
      }),
    ).toBe(Date.parse(STALE));
  });
});
