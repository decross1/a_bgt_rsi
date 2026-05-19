// VllmPanel's MTP acceptance tile: null reads "MTP off / metric absent" in
// gray; a present rate is colored against the ≥50% "MTP engaged" signal
// (ui_plan.md section 5.3). MTP was enabled apparatus-side by D-022.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import VllmPanel from "../src/components/VllmPanel";
import type { TelemetrySample } from "../src/types/schemas";

function sample(mtpAcceptance: number | null): TelemetrySample {
  return {
    timestamp: "2026-05-19T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: {
      running_requests: 1,
      waiting_requests: 0,
      gpu_cache_usage_pct: 12,
      gpu_prefix_cache_hit_rate: null,
      tokens_per_sec_decode: 69,
      mtp_acceptance_rate: mtpAcceptance,
      mtp_draft_tokens: null,
      mtp_accepted_tokens: null,
    },
    processes: [],
    read_errors: null,
  };
}

describe("VllmPanel MTP tile", () => {
  it("shows 'MTP off / metric absent' in gray when the rate is null", () => {
    render(<VllmPanel samples={[sample(null)]} />);
    const value = screen.getByText("MTP off / metric absent");
    expect(value.className).toContain("text-zinc-600");
  });

  it("colors a healthy acceptance rate (>=50%) green", () => {
    render(<VllmPanel samples={[sample(0.82)]} />);
    const value = screen.getByText("82.0 %");
    expect(value.className).toContain("text-emerald-400");
  });

  it("colors a poor acceptance rate (<50%) amber", () => {
    render(<VllmPanel samples={[sample(0.3)]} />);
    const value = screen.getByText("30.0 %");
    expect(value.className).toContain("text-amber-400");
  });
});
