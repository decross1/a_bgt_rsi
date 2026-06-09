// SurfacedFindingsPanel renders memory/surfaced_findings.jsonl rows (the
// promote_findings output): each finding's title, its novelty/critic verdict
// badges, and the source iteration it came from. With initial=[] it shows the
// clean empty state. The `initial` prop bypasses polling so these render
// synchronously without mocking fetch (the ResolvedIterationsList idiom).
import { render, screen, within } from "@testing-library/react";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import { SURFACED_FINDINGS_FIXTURE } from "../src/fixtures/coordinator";
import { describe, expect, it } from "vitest";

describe("SurfacedFindingsPanel", () => {
  it("renders each finding's title, verdict badges, and source iteration", () => {
    render(<SurfacedFindingsPanel initial={SURFACED_FINDINGS_FIXTURE} />);

    const panel = within(screen.getByTestId("surfaced-findings-panel"));

    // Every finding's title and source iteration is on screen.
    for (const finding of SURFACED_FINDINGS_FIXTURE) {
      expect(panel.getByText(finding.title!)).toBeInTheDocument();
      if (finding.source_iteration_id) {
        expect(panel.getByText(finding.source_iteration_id)).toBeInTheDocument();
      }
    }

    // The novelty + critic verdict badges from the fixture are surfaced
    // (novel/rediscovery + survives/restated across the two rows).
    expect(panel.getByText("novel")).toBeInTheDocument();
    expect(panel.getByText("rediscovery")).toBeInTheDocument();
    expect(panel.getByText("survives")).toBeInTheDocument();
    expect(panel.getByText("restated")).toBeInTheDocument();
  });

  it("shows a clean empty state when there are no findings", () => {
    render(<SurfacedFindingsPanel initial={[]} />);

    expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
    expect(screen.getByText("No surfaced findings yet.")).toBeInTheDocument();
  });
});
