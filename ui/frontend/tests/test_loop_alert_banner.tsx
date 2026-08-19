// LoopAlertBanner (2026-08-14 work order A): page-top surface over
// run_state/loop_alert.json. red = "LOOP STALLED" + reasons; amber = degraded
// list; ok & fresh = INVISIBLE; an updated_at older than ~26h renders the
// amber staleness note EVEN over "ok" (a silent cron is the failure this
// surface exists to catch). Absent flag / unknown level = nothing — the
// banner never invents an alert. Fixture renders via `initial` + a pinned
// `nowMs` (no fetch, deterministic staleness clock).
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LoopAlert } from "../src/types/schemas";

// Live-mode tests (residual fix 6): the banner now polls through the shared
// pollhub, so getLoopAlert is mocked at the module seam. The fixture tests
// below are untouched by this — `initial` renders never subscribe or fetch.
const M = vi.hoisted(() => ({ getLoopAlert: vi.fn() }));
vi.mock("../src/api/http", () => ({ getLoopAlert: M.getLoopAlert }));

import LoopAlertBanner from "../src/components/LoopAlertBanner";

// Pin "now" and derive fresh/stale timestamps from it.
const NOW = Date.parse("2026-08-15T12:00:00Z");
const FRESH = "2026-08-15T06:00:00Z"; // 6h old — inside the 26h window
const STALE = "2026-08-13T06:00:00Z"; // 54h old — well past 26h

describe("LoopAlertBanner", () => {
  it("renders nothing when the flag is absent (204 -> null)", () => {
    render(<LoopAlertBanner initial={null} nowMs={NOW} />);
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
  });

  it("red: LOOP STALLED + every reason, verbatim", () => {
    const alert: LoopAlert = {
      level: "red",
      reasons: ["no promote in 3 cycles", "qwen skeptic empty-content"],
      updated_at: FRESH,
    };
    render(<LoopAlertBanner initial={alert} nowMs={NOW} />);
    const banner = screen.getByTestId("loop-alert-banner");
    expect(banner).toHaveAttribute("data-level", "red");
    expect(screen.getByText("LOOP STALLED")).toBeInTheDocument();
    expect(screen.getByText("no promote in 3 cycles")).toBeInTheDocument();
    expect(screen.getByText("qwen skeptic empty-content")).toBeInTheDocument();
    // Fresh flag: no staleness note.
    expect(screen.queryByTestId("loop-alert-stale")).toBeNull();
  });

  it("amber: degraded list", () => {
    const alert: LoopAlert = {
      level: "amber",
      reasons: ["arxiv fetch 429-degraded"],
      updated_at: FRESH,
    };
    render(<LoopAlertBanner initial={alert} nowMs={NOW} />);
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "amber",
    );
    expect(screen.getByText("loop degraded")).toBeInTheDocument();
    expect(screen.getByText("arxiv fetch 429-degraded")).toBeInTheDocument();
  });

  it("ok & fresh: invisible — the calm state gets no chrome", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "ok", reasons: [], updated_at: FRESH }}
        nowMs={NOW}
      />,
    );
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
  });

  it("ok but STALE (>26h): amber 'no cycle telemetry since <ts>'", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "ok", reasons: [], updated_at: STALE }}
        nowMs={NOW}
      />,
    );
    const banner = screen.getByTestId("loop-alert-banner");
    expect(banner).toHaveAttribute("data-level", "amber");
    expect(screen.getByTestId("loop-alert-stale").textContent).toContain(
      `no cycle telemetry since ${STALE}`,
    );
  });

  it("red AND stale: stays red, staleness note appended", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "red", reasons: ["stalled"], updated_at: STALE }}
        nowMs={NOW}
      />,
    );
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "red",
    );
    expect(screen.getByText("LOOP STALLED")).toBeInTheDocument();
    expect(screen.getByTestId("loop-alert-stale")).toBeInTheDocument();
  });

  it("a flag with NO readable updated_at renders the honest amber note", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "ok", reasons: [] } as LoopAlert}
        nowMs={NOW}
      />,
    );
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "amber",
    );
    expect(screen.getByTestId("loop-alert-stale").textContent).toContain(
      "no readable updated_at",
    );
  });

  it("unknown level & fresh: nothing (never alarms off a shape it can't read)", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "purple", reasons: ["?"], updated_at: FRESH } as LoopAlert}
        nowMs={NOW}
      />,
    );
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
  });

  // ── the additive `gate` block (2026-08-19 review, NB2) ─────────────────
  // The producer names WHY a cycle was idle instead of leaving the owner with
  // an unexplained level. Silent-by-default while the gate is fresh; visible
  // once loop_health's age escalation has raised the level.

  it("a FRESH ok gate stays invisible — routine pacing gets no chrome", () => {
    render(
      <LoopAlertBanner
        initial={{
          level: "ok",
          reasons: ["loop_gated:budget"],
          updated_at: FRESH,
          gate: {
            reason: "budget",
            status: "daily_budget_paced",
            detail: "the loop is on its ration, not stuck",
            first_gated_at: "2026-08-15T11:00:00Z",
            consecutive: 2,
            age_s: 3600,
          },
        }}
        nowMs={NOW}
      />,
    );
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
    expect(screen.queryByTestId("loop-alert-gate")).toBeNull();
  });

  it("an AGED gate renders 'idle: <reason> for <age>' with the gate's own detail", () => {
    render(
      <LoopAlertBanner
        initial={{
          level: "amber",
          reasons: ["loop_gated:budget", "loop held by the budget gate for 5.0h"],
          updated_at: FRESH,
          gate: {
            reason: "budget",
            status: "daily_budget_paced",
            detail: "the daily executed-cycle budget gate refused this cycle",
            first_gated_at: "2026-08-15T07:00:00Z", // 5h before NOW
            consecutive: 5,
            age_s: 18000,
          },
        }}
        nowMs={NOW}
      />,
    );
    const gate = screen.getByTestId("loop-alert-gate");
    expect(gate.textContent).toContain("idle: budget for 5h");
    expect(gate.textContent).toContain("budget gate refused this cycle");
    // A HELD loop is idle, not stalled — the headline must not lie.
    expect(screen.getByText("LOOP IDLE — budget")).toBeInTheDocument();
    expect(screen.queryByText("LOOP STALLED")).toBeNull();
  });

  it("a gate escalated to RED is red, but still IDLE — never 'LOOP STALLED'", () => {
    render(
      <LoopAlertBanner
        initial={{
          level: "red",
          reasons: ["loop_gated:budget", "NO cycle has executed in that window"],
          updated_at: FRESH,
          gate: {
            reason: "budget",
            detail: "on its ration",
            first_gated_at: "2026-08-14T23:00:00Z", // 13h before NOW
            age_s: 46800,
          },
        }}
        nowMs={NOW}
      />,
    );
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "red",
    );
    expect(screen.getByTestId("loop-alert-gate").textContent).toContain(
      "idle: budget for 13h",
    );
    expect(screen.queryByText("LOOP STALLED")).toBeNull();
    expect(
      screen.getByText("NO cycle has executed in that window"),
    ).toBeInTheDocument();
  });

  it("a real stall (no gate block) keeps the LOOP STALLED headline", () => {
    render(
      <LoopAlertBanner
        initial={{ level: "red", reasons: ["loop_stalled"], updated_at: FRESH }}
        nowMs={NOW}
      />,
    );
    expect(screen.getByText("LOOP STALLED")).toBeInTheDocument();
    expect(screen.queryByTestId("loop-alert-gate")).toBeNull();
  });

  it("producer-owned gate degrades: a malformed block renders no idle line", () => {
    for (const gate of [null, "budget", [], {}, { reason: "" }, { reason: 7 }]) {
      cleanup();
      render(
        <LoopAlertBanner
          initial={
            { level: "red", reasons: ["loop_stalled"], updated_at: FRESH, gate } as
              unknown as LoopAlert
          }
          nowMs={NOW}
        />,
      );
      expect(screen.queryByTestId("loop-alert-gate")).toBeNull();
      expect(screen.getByText("LOOP STALLED")).toBeInTheDocument();
    }
  });

  it("a gate with no first_gated_at names the reason without inventing an age", () => {
    render(
      <LoopAlertBanner
        initial={{
          level: "amber",
          reasons: ["loop_gated:paused"],
          updated_at: FRESH,
          gate: { reason: "paused", detail: "the human kill switch is engaged" },
        }}
        nowMs={NOW}
      />,
    );
    const gate = screen.getByTestId("loop-alert-gate");
    expect(gate.textContent).toContain("idle: paused");
    expect(gate.textContent).not.toContain(" for ");
    expect(gate.textContent).toContain("human kill switch");
  });

  it("producer-owned reasons degrade: non-array -> no list, non-string entries dropped", () => {
    render(
      <LoopAlertBanner
        initial={
          {
            level: "red",
            reasons: [42, { a: 1 }, "real reason", null],
            updated_at: FRESH,
          } as unknown as LoopAlert
        }
        nowMs={NOW}
      />,
    );
    expect(screen.getByText("real reason")).toBeInTheDocument();
    expect(screen.getByTestId("loop-alert-reasons").children).toHaveLength(1);

    // Non-array reasons: banner still renders, just without a list.
    render(
      <LoopAlertBanner
        initial={
          { level: "amber", reasons: "not-a-list", updated_at: FRESH } as unknown as LoopAlert
        }
        nowMs={NOW}
      />,
    );
    expect(screen.getAllByTestId("loop-alert-banner").length).toBeGreaterThan(0);
  });
});

// ── Live mode over the shared pollhub (residual fix 6, 2026-08-18) ─────────
// The banner used to run a bare setInterval AND cleared an active alert on
// any failed poll (catch -> setAlert(null)) — a red "LOOP STALLED" vanished
// exactly when the backend was struggling. Pins: SWR keeps the last-known
// alert across failures with a stale marker; only an explicit ok/absent
// payload clears it; a source that never loaded alarms off nothing.
describe("LoopAlertBanner live polling (pollhub)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  const tickAsync = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  const freshRed = (): LoopAlert => ({
    level: "red",
    reasons: ["coordinator stalled"],
    updated_at: new Date(Date.now() - 60_000).toISOString(),
  });

  it("a FAILED poll never clears an active alert — kept, with a stale marker", async () => {
    M.getLoopAlert.mockResolvedValue(freshRed());
    render(<LoopAlertBanner pollMs={10_000} />);
    await tickAsync(0);
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "red",
    );
    expect(screen.queryByTestId("loop-alert-refresh-failing")).toBeNull();

    // The next poll FAILS: the alert must stay, marked stale — never vanish.
    M.getLoopAlert.mockRejectedValue(new Error("backend drowned"));
    await tickAsync(11_000);
    expect(screen.getByTestId("loop-alert-banner")).toHaveAttribute(
      "data-level",
      "red",
    );
    expect(screen.getByText("coordinator stalled")).toBeInTheDocument();
    expect(
      screen.getByTestId("loop-alert-refresh-failing").textContent,
    ).toContain("showing the last-known alert");

    // Only an EXPLICIT ok payload clears it.
    M.getLoopAlert.mockResolvedValue({
      level: "ok",
      reasons: [],
      updated_at: new Date(Date.now() - 60_000).toISOString(),
    });
    await tickAsync(11_000);
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
  });

  it("an explicit ABSENT payload (204 -> null) also clears the banner", async () => {
    M.getLoopAlert.mockResolvedValue(freshRed());
    render(<LoopAlertBanner pollMs={10_000} />);
    await tickAsync(0);
    expect(screen.getByTestId("loop-alert-banner")).toBeInTheDocument();

    M.getLoopAlert.mockResolvedValue(null);
    await tickAsync(11_000);
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
  });

  it("a source that NEVER loaded renders nothing, even while failing", async () => {
    // e.g. a version-skew 404: the banner never alarms off nothing.
    M.getLoopAlert.mockRejectedValue(new Error("404 Not Found"));
    render(<LoopAlertBanner pollMs={10_000} />);
    await tickAsync(11_000);
    expect(screen.queryByTestId("loop-alert-banner")).toBeNull();
    expect(screen.queryByTestId("loop-alert-refresh-failing")).toBeNull();
  });
});
