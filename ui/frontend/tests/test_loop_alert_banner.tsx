// LoopAlertBanner (2026-08-14 work order A): page-top surface over
// run_state/loop_alert.json. red = "LOOP STALLED" + reasons; amber = degraded
// list; ok & fresh = INVISIBLE; an updated_at older than ~26h renders the
// amber staleness note EVEN over "ok" (a silent cron is the failure this
// surface exists to catch). Absent flag / unknown level = nothing — the
// banner never invents an alert. Fixture renders via `initial` + a pinned
// `nowMs` (no fetch, deterministic staleness clock).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LoopAlertBanner from "../src/components/LoopAlertBanner";
import type { LoopAlert } from "../src/types/schemas";

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
