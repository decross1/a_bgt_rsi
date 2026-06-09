// BubblesPanel renders the coordinator's "raise to the human" channel from an
// `initial` list (no fetch mock needed — mirrors ResolvedIterationsList). Each
// bubble row shows its `note`, its `run_id`, and a chip per raised `finding_id`
// (the EMIT row shape is {timestamp, run_id, finding_ids, note} — no per-bubble
// severity or agent). initial=[] renders the clean empty state.
import { render, screen, within } from "@testing-library/react";
import BubblesPanel from "../src/components/BubblesPanel";
import { BUBBLES_FIXTURE } from "../src/fixtures/coordinator";
import { describe, expect, it } from "vitest";

describe("BubblesPanel", () => {
  it("renders each bubble's note, run id, and finding-id chips", () => {
    render(<BubblesPanel initial={BUBBLES_FIXTURE} />);
    expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();

    BUBBLES_FIXTURE.forEach((bubble, i) => {
      const row = screen.getByTestId(`bubble-${i}`);
      expect(row).toHaveTextContent(bubble.note!);
      if (bubble.run_id) expect(row).toHaveTextContent(bubble.run_id);
      // Each raised finding id renders as a chip inside the row.
      for (const fid of bubble.finding_ids ?? []) {
        expect(within(row).getByText(fid)).toBeInTheDocument();
      }
    });
  });

  it("renders a clean empty state when there are no bubbles", () => {
    render(<BubblesPanel initial={[]} />);
    expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument();
  });
});
