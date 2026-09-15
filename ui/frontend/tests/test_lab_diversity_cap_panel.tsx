import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LabDiversityCapPanel } from "../src/components/LabDiversityCapPanel";

const sha = (letter: string) => letter.repeat(64);
const base = (status: string, results: unknown = null) => ({
  schema_version: "lab-diversity-cap-ui-progress/v1",
  observed_at: new Date().toISOString(), status,
  window_id: "qfn-ab-lab-diversity-cap-20260915-a",
  plan_raw_sha256: sha("a"), window_raw_sha256: sha("b"),
  replay_raw_sha256: results === null ? null : sha("c"), results,
  failure_reason_code: null,
  original_primary_scores_changed: false, private_content_exported: false,
  promotion_authorized: false, comparison_eligible: false,
});
const arm = (tokens: number, objective: number, protocol: number) => ({
  cap_tokens: tokens, condition_cells: 5, generator_calls: 15,
  generator_returned: 14, generator_timeout: 1,
  empty_visible_final: 3, length_reasoning_only_empty: 2,
  valid_proposals: 8, selector_calls: 5, selector_returned: 5,
  selector_timeout: 0, underlying_objective_success: objective,
  creditable_protocol_pass: protocol,
});
const results = {
  caps: { "384": arm(384, 1, 0), "1536": arm(1536, 2, 1) },
  paired_task_protocol_differences: {
    cap1536_pass_cap384_fail: 1, cap384_pass_cap1536_fail: 0,
    both_pass: 0, neither_pass: 4,
  },
  recorded_evaluator_elapsed_s: 111.5,
  source_replay: "publication_time_only",
};

describe("Mia diversity cap panel", () => {
  it("shows a frozen plan without inventing cap results", () => {
    render(<LabDiversityCapPanel data={base("prepared_unissued")} />);
    expect(screen.getByText(/no cap-study result has been admitted/i)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Mia diversity cap results/i })).not.toBeInTheDocument();
  });

  it("distinguishes incomplete closure from admission pending", () => {
    const { rerender } = render(<LabDiversityCapPanel data={base("incomplete_terminal")} />);
    expect(screen.getByText(/closed incomplete or failed/i)).toBeInTheDocument();
    rerender(<LabDiversityCapPanel data={base("awaiting_admission")} />);
    expect(screen.getByText(/awaiting independent raw-response and grade replay/i)).toBeInTheDocument();
  });

  it("names only a bound startup host-paging stop without presenting grades", () => {
    const { rerender } = render(<LabDiversityCapPanel data={{ ...base("incomplete_terminal"),
      failure_reason_code: "startup_host_swap_5s" }} />);
    expect(screen.getByText(/Startup host-paging guard stopped this attempt before evaluation; no cap-quality result/i)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Mia diversity cap results/i })).not.toBeInTheDocument();
    rerender(<LabDiversityCapPanel data={{ ...base("incomplete_terminal"),
      failure_reason_code: "candidate_oom" }} />);
    expect(screen.getByText(/Cap observation unavailable; all diagnostic counts are withheld/i)).toBeInTheDocument();
  });

  it("shows admitted objective and protocol counts with recorded timing provenance", () => {
    render(<LabDiversityCapPanel data={base("closed_replay_admitted", results)} />);
    expect(screen.getByRole("region", { name: /Mia diversity cap results/i })).toBeInTheDocument();
    expect(screen.getByText(/Evaluator time 111.5 s/)).toBeInTheDocument();
    expect(screen.getByText(/raw-response replay does not independently verify elapsed time/i)).toBeInTheDocument();
    expect(screen.getByText(/1,536 only 1; 384 only 0; both 0; neither 4/)).toBeInTheDocument();
    expect(screen.getByText(/does not rescore the original 126 cells/i)).toBeInTheDocument();
  });

  it("withholds a re-sealed count, claim or stale observation", () => {
    const { rerender } = render(<LabDiversityCapPanel data={base("closed_replay_admitted", results)} />);
    expect(screen.getByRole("region", { name: /Mia diversity cap results/i })).toBeInTheDocument();
    rerender(<LabDiversityCapPanel data={base("closed_replay_admitted", {
      ...results, caps: { ...results.caps, "1536": arm(1536, 1, 2) },
    })} />);
    expect(screen.queryByRole("region", { name: /Mia diversity cap results/i })).not.toBeInTheDocument();
    rerender(<LabDiversityCapPanel data={{ ...base("closed_replay_admitted", results),
      comparison_eligible: true }} />);
    expect(screen.queryByRole("region", { name: /Mia diversity cap results/i })).not.toBeInTheDocument();
    rerender(<LabDiversityCapPanel data={{ ...base("closed_replay_admitted", results),
      observed_at: new Date(Date.now() - 3_600_000).toISOString() }} />);
    expect(screen.queryByRole("region", { name: /Mia diversity cap results/i })).not.toBeInTheDocument();
  });
});
