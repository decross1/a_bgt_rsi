// VllmPanel's MTP acceptance tile: null reads "MTP off / metric absent" in
// gray; a present rate is colored against the ≥50% "MTP engaged" signal
// (ui_plan.md section 5.3). MTP was enabled apparatus-side by D-022.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import VllmPanel from "../src/components/VllmPanel";
import type { LiveCalls } from "../src/types/activity";
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

// "driving: <tag> ×N" sub-line (handoff Task 1 / 2026-06-10): derived ONLY
// from live-call groups whose `model` EXACTLY equals the panel's served model
// (gemma-4-26b-a4b) — no substring matching, absent when none. Groups are
// CONSTRUCTED (synthetic counts); tags/models/backends are the live names.
describe("VllmPanel driving sub-line", () => {
  const DRIVING: LiveCalls = {
    active: true,
    count: 19,
    window_s: 60,
    calls_per_s: 0.32,
    last_call_at: "2026-06-10T08:00:06.4Z",
    caller_tags: [{ tag: "hypothesize", count: 4 }],
    model: "gemma-4-26b-a4b",
    groups: [
      {
        tag: "hypothesize",
        model: "gemma-4-26b-a4b",
        backend: "vllm-gemma",
        run_id: "loop_v0_2026-06-10_001",
        count: 4,
        last_call_at: "2026-06-10T08:00:05.0Z",
      },
      {
        tag: "skeptic_attack",
        model: "qwen3.6-27b-nvfp4-mtp",
        backend: "vllm-qwen",
        run_id: null,
        count: 12,
        last_call_at: "2026-06-10T08:00:06.4Z",
      },
      {
        // NEAR-MISS (constructed): a superstring of the served model name —
        // exact-match only, must never attribute to this panel.
        tag: "meta_review",
        model: "gemma-4-26b-a4b-quant",
        backend: null,
        run_id: null,
        count: 9,
        last_call_at: "2026-06-10T08:00:04.0Z",
      },
    ],
  };

  it("renders 'driving: <tag> ×N' from exact-model groups only", () => {
    render(<VllmPanel samples={[sample(0.82)]} liveCalls={DRIVING} />);
    const line = screen.getByTestId("vllm-driving");
    expect(line).toHaveTextContent("driving:");
    expect(line).toHaveTextContent("hypothesize");
    expect(line).toHaveTextContent("×4");
    // The qwen-served group and the near-miss model never show here.
    expect(line.textContent).not.toContain("skeptic_attack");
    expect(line.textContent).not.toContain("meta_review");
  });

  it("is ABSENT when no group's model exactly matches", () => {
    render(
      <VllmPanel
        samples={[sample(0.82)]}
        liveCalls={{
          ...DRIVING,
          groups: DRIVING.groups!.filter(
            (g) => g.model !== "gemma-4-26b-a4b",
          ),
        }}
      />,
    );
    expect(screen.queryByTestId("vllm-driving")).toBeNull();
  });

  it("is ABSENT when liveCalls is not provided (additive prop)", () => {
    render(<VllmPanel samples={[sample(0.82)]} />);
    expect(screen.queryByTestId("vllm-driving")).toBeNull();
  });
});
