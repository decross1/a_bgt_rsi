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
