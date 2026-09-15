import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PayoffToolStudyPanel } from "../src/components/PayoffToolStudyPanel";

const sha = (letter: string) => letter.repeat(64);
const base = (status: string, results: unknown = null) => ({
  schema_version: "payoff-tool-study-ui-progress/v1",
  observed_at: new Date().toISOString(), status,
  window_id: "qfn-followon-payoff-tool-20260915-a",
  plan_raw_sha256: sha("a"), window_raw_sha256: sha("b"),
  admission_raw_sha256: results === null ? null : sha("c"), results,
  private_content_exported: false, comparison_eligible: false,
  promotion_authorized: false, trading_claim_authorized: false,
});
const scores = {
  declared_pairs: 6, declared_conditions_per_arm: 6, declared_slots: 18,
  issued_calls: 15,
  direct: { strict_shape: 3, strict_both_correct: 2 },
  tool: { native_calls_parsed: 4, native_calls_executed: 3,
    final_calls_issued: 3, causal_final_skips: 3,
    strict_shape: 2, strict_both_correct: 1 },
  recorded_evaluator_elapsed_s: 301.4,
  source_replay: "publication_time_only",
};

describe("payoff-tool diagnostic panel", () => {
  it("shows prepared and running states without arithmetic counts", () => {
    const { rerender } = render(<PayoffToolStudyPanel data={base("prepared_unissued")} />);
    expect(screen.getByText(/plan and resident window are prepared/i)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /payoff arithmetic results/i })).not.toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={base("execution_pending")} />);
    expect(screen.getByText(/running or awaiting its supervisor/i)).toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={{ ...base("prepared_unissued"),
      window_raw_sha256: null }} />);
    expect(screen.getByText(/observation unavailable; arithmetic counts are withheld/i)).toBeInTheDocument();
  });

  it("distinguishes terminal admission pending from an aborted window", () => {
    const { rerender } = render(<PayoffToolStudyPanel data={base("awaiting_admission")} />);
    expect(screen.getByText(/awaiting publication/i)).toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={base("aborted_unadmitted")} />);
    expect(screen.getByText(/no payoff-tool quality result is admitted/i)).toBeInTheDocument();
  });

  it("shows only six-pair arithmetic and actual native-call counts after admission", () => {
    render(<PayoffToolStudyPanel data={base("closed_admitted", scores)} />);
    expect(screen.getByRole("region", { name: /payoff arithmetic results/i })).toBeInTheDocument();
    expect(screen.getByText(/15 of 18 scheduled call slots were issued/i)).toBeInTheDocument();
    expect(screen.getByText(/Evaluator time 301.4 s excludes setup and restoration/i)).toBeInTheDocument();
    expect(screen.getByText(/calculator returns only the shared group return/i)).toBeInTheDocument();
    expect(screen.getByText(/do not establish strategy quality/i)).toBeInTheDocument();
  });

  it("withholds malformed denominators, causal skips and promotion claims", () => {
    const { rerender } = render(<PayoffToolStudyPanel data={base("closed_admitted", scores)} />);
    expect(screen.getByRole("region", { name: /payoff arithmetic results/i })).toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={base("closed_admitted", {
      ...scores, tool: { ...scores.tool, causal_final_skips: 2 },
    })} />);
    expect(screen.queryByRole("region", { name: /payoff arithmetic results/i })).not.toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={{ ...base("closed_admitted", scores),
      promotion_authorized: true }} />);
    expect(screen.queryByRole("region", { name: /payoff arithmetic results/i })).not.toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={base("closed_admitted", {
      ...scores, issued_calls: 14,
    })} />);
    expect(screen.queryByRole("region", { name: /payoff arithmetic results/i })).not.toBeInTheDocument();
    rerender(<PayoffToolStudyPanel data={base("closed_admitted", scores)} pollingFailed />);
    expect(screen.queryByRole("region", { name: /payoff arithmetic results/i })).not.toBeInTheDocument();
  });
});
