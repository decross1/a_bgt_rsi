import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LabModelSupplementPanel } from "../src/components/LabModelSupplementPanel";

const sha = (letter: string) => letter.repeat(64);
const score = (declared: number, passed: number, wall: number) => ({
  declared, attempted: declared, returned: declared, timeout: 0, error: 0,
  cancelled: 0, passed, wall_s_including_failures: wall,
});
const pending = (kind: "fresh" | "context") => ({
  kind, pair_id: kind === "fresh" ? "qfn-ab-lab-fresh-20260915-a" :
    "qfn-ab-lab-context-20260915-a",
  status: "pending_publication", denominator_per_cohort: kind === "fresh" ? 12 : 36,
  plan_raw_sha256: null, publication_index_raw_sha256: null, cohorts: null,
  grade_replay: "not_available", promotion_authorized: false,
});
const admitted = (kind: "fresh" | "context", arms: Record<string, unknown>) => ({
  ...pending(kind), status: "complete_admitted_pair", plan_raw_sha256: sha("a"),
  publication_index_raw_sha256: sha("b"),
  grade_replay: kind === "fresh" ? "raw_sse_and_all_12_fresh_primary_grades_per_cohort" :
    "raw_sse_and_all_36_context_objective_grades_per_cohort",
  cohorts: arms,
});
const view = (fresh: unknown = pending("fresh"), context: unknown = pending("context")) => ({
  schema_version: "lab-model-supplement-progress/v1",
  observed_at: new Date().toISOString(), pairs: { fresh, context },
  original_scores_rebased: false, private_content_exported: false,
  promotion_authorized: false,
});

const freshArms = () => {
  const resident = { variant_id: "resident-role-bundle", elapsed_s: 120,
    scores: { total: score(12, 5, 120),
      by_kind: { science: score(6, 5, 60), coding: score(6, 0, 60) } },
    normalization_diagnostic: { coding_returned_attempted: 6,
      sandbox_passes_after_predeclared_transform: 6, never_replaces_primary_score: true } };
  const flash = { variant_id: "mia-925d7be6-mtp3-reduced47k-v2opt-v1", elapsed_s: 100,
    scores: { total: score(12, 8, 100),
      by_kind: { science: score(6, 6, 50), coding: score(6, 2, 50) } },
    normalization_diagnostic: { coding_returned_attempted: 6,
      sandbox_passes_after_predeclared_transform: 3, never_replaces_primary_score: true } };
  return { resident, flash };
};
const contextArms = () => {
  const byCapacity = Object.fromEntries(["8192", "16384", "32768"].map(cap =>
    [cap, score(12, 8, 12)]));
  const byPlacement = { early: score(12, 12, 12), middle: score(12, 6, 12),
    late: score(12, 6, 12) };
  const grid = Object.fromEntries(["8192", "16384", "32768"].map(cap => [cap, {
    early: score(4, 4, 4), middle: score(4, 2, 4), late: score(4, 2, 4),
  }]));
  const scores = { total: score(36, 24, 36), by_capacity: byCapacity,
    by_placement: byPlacement, by_capacity_placement: grid,
    measured_prompt_tokens_max_by_capacity: {
      "8192": 7000, "16384": 15000, "32768": 30000 } };
  return { resident: { variant_id: "resident-gemma", elapsed_s: 65,
    scores, configured_context_tokens: 32768,
    measured_prompt_tokens_max: 30000, output_reserve_tokens: 2048 },
    flash: { variant_id: "mia-925d7be6-mtp3-reduced47k-v2opt-v1", elapsed_s: 60,
      scores, configured_context_tokens: 32768,
      measured_prompt_tokens_max: 30000, output_reserve_tokens: 2048 } };
};

describe("LabModelSupplementPanel", () => {
  it("keeps both independent studies scoreless until exact publications exist", () => {
    render(<LabModelSupplementPanel data={view()} />);
    expect(screen.getByText(/Fresh pair publication pending/)).toBeInTheDocument();
    expect(screen.getByText(/Context pair publication pending/)).toBeInTheDocument();
    expect(screen.queryByText(/New quantitative games/)).not.toBeInTheDocument();
  });

  it("shows admitted fresh science and coding without rebasing primary grades", () => {
    render(<LabModelSupplementPanel data={view(admitted("fresh", freshArms()))} />);
    expect(screen.getByText("New quantitative games")).toBeInTheDocument();
    expect(screen.getByText("New one-file repairs")).toBeInTheDocument();
    expect(screen.getByText(/All fresh cells: resident 5 \/ 12, Flash 8 \/ 12/)).toBeInTheDocument();
    expect(screen.getByText(/resident 6\/6 returned coding attempts passed/)).toBeInTheDocument();
    expect(screen.getByText(/strict coding grades above are unchanged/)).toBeInTheDocument();
    expect(screen.getByText(/Context pair publication pending/)).toBeInTheDocument();
  });

  it("shows admitted 8K/16K/32K answer quality by capacity and position, not a 64K claim", () => {
    render(<LabModelSupplementPanel data={view(pending("fresh"),
      admitted("context", contextArms()))} />);
    expect(screen.getByText(/Each lane has 12 planned cells/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Context quality by total capacity/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Context quality by capacity and answer position/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Resident Gemma passed" })).toBeInTheDocument();
    expect(screen.getByText(/does not test Qwen 16K answer quality/)).toBeInTheDocument();
    expect(screen.getByText(/A prepared 64K packet or server flag is not a 64K quality result/)).toBeInTheDocument();
  });

  it("withholds tampered, stale, or failed admissions and scores", () => {
    const fresh = admitted("fresh", freshArms());
    const { rerender } = render(<LabModelSupplementPanel data={view(fresh)} />);
    expect(screen.getByText("New quantitative games")).toBeInTheDocument();
    rerender(<LabModelSupplementPanel data={view({ ...fresh,
      publication_index_raw_sha256: "unbound" })} />);
    expect(screen.queryByText("New quantitative games")).not.toBeInTheDocument();
    const alteredArms = freshArms();
    alteredArms.flash.scores.total.passed = 13;
    const altered = admitted("fresh", alteredArms);
    rerender(<LabModelSupplementPanel data={view(altered)} />);
    expect(screen.queryByText("New quantitative games")).not.toBeInTheDocument();
    rerender(<LabModelSupplementPanel data={{ ...view(fresh),
      observed_at: new Date(Date.now() - 10 * 60_000).toISOString() }} />);
    expect(screen.getByText(/Supplemental source observation unavailable/)).toBeInTheDocument();
    rerender(<LabModelSupplementPanel data={view(fresh)} pollingFailed />);
    expect(screen.getByText(/Supplemental source observation unavailable/)).toBeInTheDocument();
  });
});
