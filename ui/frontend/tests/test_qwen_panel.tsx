// QwenPanel reads samples[i].vllm_qwen and mirrors VllmPanel's metric
// tiles. The "no data" state — every sample missing vllm_qwen — is the
// expected display today (Qwen is staged but not wired into a worker),
// so it gets a first-class explicit test.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QwenPanel from "../src/components/QwenPanel";
import type { TelemetrySample } from "../src/types/schemas";

function sampleWithQwen(mtpAcceptance: number | null): TelemetrySample {
  return {
    timestamp: "2026-05-27T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: null,
    vllm_qwen: {
      running_requests: 1,
      waiting_requests: 0,
      gpu_cache_usage_pct: 18,
      gpu_prefix_cache_hit_rate: null,
      tokens_per_sec_decode: 37,
      mtp_acceptance_rate: mtpAcceptance,
      mtp_draft_tokens: null,
      mtp_accepted_tokens: null,
    },
    processes: [],
    read_errors: null,
  };
}

function sampleWithoutQwen(): TelemetrySample {
  return {
    timestamp: "2026-05-27T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: null,
    vllm_qwen: null,
    processes: [],
    read_errors: null,
  };
}

describe("QwenPanel", () => {
  it("renders 'unreachable' when every sample's vllm_qwen is null", () => {
    // Expected state today: Qwen is staged but no worker fires against
    // :8001, so the sampler may never see a successful read. Panel must
    // self-describe rather than render an empty card that reads as broken.
    render(<QwenPanel samples={[sampleWithoutQwen(), sampleWithoutQwen()]} />);
    expect(
      screen.getByText(/Qwen endpoint unreachable/),
    ).toBeInTheDocument();
  });

  it("renders 'unreachable' on an empty samples array", () => {
    render(<QwenPanel samples={[]} />);
    expect(
      screen.getByText(/Qwen endpoint unreachable/),
    ).toBeInTheDocument();
  });

  it("renders metric tiles when vllm_qwen is present", () => {
    render(<QwenPanel samples={[sampleWithQwen(0.82)]} />);
    expect(screen.getByText(/Qwen3.6-27B/)).toBeInTheDocument();
    expect(screen.getByText("Running requests")).toBeInTheDocument();
    expect(screen.getByText("Decode tok/s")).toBeInTheDocument();
    // MTP acceptance shows the formatted percentage and the healthy color.
    const mtpValue = screen.getByText("82.0 %");
    expect(mtpValue.className).toContain("text-emerald-400");
  });

  it("shows a soft banner when the latest sample lost vllm_qwen", () => {
    // Intermittent drop: at least one sample had data, but the latest
    // does not. The panel keeps its space and tells the user.
    render(
      <QwenPanel samples={[sampleWithQwen(0.7), sampleWithoutQwen()]} />,
    );
    expect(screen.getByText(/dropped on the latest sample/)).toBeInTheDocument();
  });
});
