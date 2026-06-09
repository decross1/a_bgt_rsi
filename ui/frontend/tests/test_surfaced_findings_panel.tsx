// SurfacedFindingsPanel renders memory/surfaced_findings.jsonl rows: each
// promoted finding's text, an AgentBadge provenance chip, and the iteration
// it came from. With initial=[] it shows the clean empty state. The `initial`
// prop bypasses polling so these render synchronously without mocking fetch
// (the ResolvedIterationsList idiom).
import { render, screen, within } from "@testing-library/react";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import { SURFACED_FINDINGS_FIXTURE } from "../src/fixtures/coordinator";
import { describe, expect, it } from "vitest";

describe("SurfacedFindingsPanel", () => {
  it("renders each finding's text, agent badge, and iteration id", () => {
    render(<SurfacedFindingsPanel initial={SURFACED_FINDINGS_FIXTURE} />);

    const panel = within(screen.getByTestId("surfaced-findings-panel"));

    // Every finding's text and source iteration is on screen.
    for (const finding of SURFACED_FINDINGS_FIXTURE) {
      expect(panel.getByText(finding.text)).toBeInTheDocument();
      if (finding.iteration_id) {
        expect(panel.getByText(finding.iteration_id)).toBeInTheDocument();
      }
    }

    // One provenance badge per finding (coordinator + nara in the fixture).
    const badges = panel.getAllByTestId("agent-badge");
    expect(badges).toHaveLength(SURFACED_FINDINGS_FIXTURE.length);
    expect(panel.getByText("coordinator")).toBeInTheDocument();
    expect(panel.getByText("nara")).toBeInTheDocument();
  });

  it("shows a clean empty state when there are no findings", () => {
    render(<SurfacedFindingsPanel initial={[]} />);

    expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
    expect(screen.getByText("No surfaced findings yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-badge")).not.toBeInTheDocument();
  });
});
