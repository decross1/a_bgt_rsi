// HealthSignalsPanel renders run_state/health_signals.jsonl rows — the
// degraded-but-not-broken signals (ml-intern 0-papers, qwen empty-content).
// Each row is amber (degraded ≠ down) and carries its detail + iteration. With
// initial=[] it shows the clean "workers nominal" empty state.
import { render, screen, within } from "@testing-library/react";
import HealthSignalsPanel from "../src/components/HealthSignalsPanel";
import { HEALTH_SIGNALS_FIXTURE } from "../src/fixtures/coordinator";
import { describe, expect, it } from "vitest";

describe("HealthSignalsPanel", () => {
  it("renders each degraded signal amber with its detail", () => {
    render(<HealthSignalsPanel initial={HEALTH_SIGNALS_FIXTURE} />);
    expect(screen.getByTestId("health-signals-panel")).toBeInTheDocument();

    HEALTH_SIGNALS_FIXTURE.forEach((sig, i) => {
      const row = screen.getByTestId(`health-signal-${i}`);
      // degraded ≠ broken → amber, never red.
      expect(row.className).toContain("amber");
      expect(row.className).not.toMatch(/border-red/);
      expect(row).toHaveTextContent(sig.detail as string);
    });

    // Both signal kinds are humanized into chips.
    expect(screen.getByText("ml-intern · 0 papers")).toBeInTheDocument();
    expect(screen.getByText("qwen · empty content")).toBeInTheDocument();
  });

  it("shows a clean empty state when workers are nominal", () => {
    render(<HealthSignalsPanel initial={[]} />);
    expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("health-signals-panel")).queryByTestId(
        "health-signal-0",
      ),
    ).toBeNull();
  });
});
