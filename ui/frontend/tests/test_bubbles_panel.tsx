// BubblesPanel renders the coordinator's "raise to the human" channel from an
// `initial` list (no fetch mock needed — mirrors ResolvedIterationsList): each
// bubble shows its text, an agent badge, and a severity-toned row (raise=red,
// warn=amber, info=zinc). initial=[] renders the clean empty state.
import { render, screen, within } from "@testing-library/react";
import BubblesPanel from "../src/components/BubblesPanel";
import { BUBBLES_FIXTURE } from "../src/fixtures/coordinator";

describe("BubblesPanel", () => {
  it("renders each fixture bubble with text and an agent badge", () => {
    render(<BubblesPanel initial={BUBBLES_FIXTURE} />);
    expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();

    for (const bubble of BUBBLES_FIXTURE) {
      const row = screen.getByTestId(`bubble-${bubble.bubble_id}`);
      expect(row).toHaveTextContent(bubble.text);
      // Provenance: every row badges its actor.
      expect(within(row).getByTestId("agent-badge")).toHaveTextContent(
        bubble.agent!,
      );
    }
  });

  it("tones rows by severity: raise=red, warn=amber, info=zinc", () => {
    render(<BubblesPanel initial={BUBBLES_FIXTURE} />);

    // bub-...-001 is a "raise" — the prominent, human-now tier (red).
    const raise = screen.getByTestId("bubble-bub-2026-06-09-001");
    expect(raise).toHaveAttribute("data-severity", "raise");
    expect(raise.className).toContain("border-red-900/60");
    expect(within(raise).getByText("raise").className).toContain(
      "text-red-400",
    );

    // bub-...-002 is a "warn" — degraded, amber, not red.
    const warn = screen.getByTestId("bubble-bub-2026-06-09-002");
    expect(warn).toHaveAttribute("data-severity", "warn");
    expect(warn.className).toContain("border-amber-900/60");
    expect(within(warn).getByText("warn").className).toContain(
      "text-amber-400",
    );

    // bub-...-003 is an "info" — quiet zinc, not an alarm.
    const info = screen.getByTestId("bubble-bub-2026-06-09-003");
    expect(info).toHaveAttribute("data-severity", "info");
    expect(within(info).getByText("info").className).toContain(
      "text-zinc-400",
    );
  });

  it("renders a clean empty state when there are no bubbles", () => {
    render(<BubblesPanel initial={[]} />);
    expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-badge")).toBeNull();
  });
});
