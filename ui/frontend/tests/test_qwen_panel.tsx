// QwenPanel reads samples[i].vllm_qwen and mirrors VllmPanel's metric
// tiles. The "no data" state — every sample missing vllm_qwen — is the
// expected display today (Qwen is staged but not wired into a worker),
// so it gets a first-class explicit test.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QwenPanel from "../src/components/QwenPanel";
import type { LiveCalls } from "../src/types/activity";
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

  it("shows '● up' (emerald) in the status badge when the latest sample has vllm_qwen", () => {
    render(<QwenPanel samples={[sampleWithQwen(0.82)]} />);
    const badge = screen.getByTestId("qwen-status");
    expect(badge.textContent).toBe("● up");
    expect(badge.className).toContain("text-emerald-400");
  });

  it("shows '● down' (red) in the status badge when no vllm_qwen on the latest sample", () => {
    render(<QwenPanel samples={[sampleWithoutQwen()]} />);
    const badge = screen.getByTestId("qwen-status");
    expect(badge.textContent).toBe("● down");
    expect(badge.className).toContain("text-red-400");
  });

  it("keeps both CORE rows visible and tucks all INTERNALS inside the disclosure", () => {
    render(<QwenPanel samples={[sampleWithQwen(0.82)]} />);
    const details = screen.getByTestId("qwen-details");
    // CORE rows (Decode tok/s + KV-cache usage) must NOT be nested under
    // the <details> disclosure — they stay visible at a glance.
    expect(screen.getByText("Decode tok/s").closest("details")).toBeNull();
    expect(screen.getByText("KV-cache usage").closest("details")).toBeNull();
    // INTERNALS rows must ALL resolve inside the qwen-details element, so a
    // row leaking out to core (or a core row sinking into internals) fails.
    for (const label of [
      "Running requests",
      "Waiting requests",
      "Prefix-cache hit rate",
      "MTP acceptance",
    ]) {
      const row = screen.getByText(label);
      expect(details.contains(row)).toBe(true);
      expect(row.closest("details")).toBe(details);
    }
    // Disclosure summary uses the shared show/hide internals idiom. Note:
    // <details> renders its children regardless of open state, so these
    // assert DOM membership (the partition), not collapse visibility.
    expect(screen.getByText("show internals ▸")).toBeInTheDocument();
    expect(screen.getByText("hide internals ▾")).toBeInTheDocument();
  });

  it("shows a soft banner when the latest sample lost vllm_qwen", () => {
    // Intermittent drop: at least one sample had data, but the latest
    // does not. The panel keeps its space and tells the user.
    render(
      <QwenPanel samples={[sampleWithQwen(0.7), sampleWithoutQwen()]} />,
    );
    expect(screen.getByText(/dropped on the latest sample/)).toBeInTheDocument();
  });

  it("pairs the soft amber banner with a hard-red '● down' badge in the transient-drop state", () => {
    // Pins the intended header/body relationship in the surprising case:
    // anyQwen && !qwen. The body shows the SOFTER amber intermittent banner
    // while the badge is deliberately binary (parity with VllmPanel) and so
    // reads hard-red "● down". Both must coexist — if the badge ever goes
    // tri-state or the banner hardens, this guard fires.
    render(
      <QwenPanel samples={[sampleWithQwen(0.7), sampleWithoutQwen()]} />,
    );
    expect(screen.getByText(/dropped on the latest sample/)).toBeInTheDocument();
    const badge = screen.getByTestId("qwen-status");
    expect(badge.textContent).toBe("● down");
    expect(badge.className).toContain("text-red-400");
  });

  it("omits the workload-hint pill (intentional design choice — see QwenPanel header)", () => {
    // VllmPanel renders a decode-regime "workload:" hint derived from the
    // Gemma orchestrator's calls.jsonl; there is no Qwen equivalent yet, so
    // QwenPanel intentionally drops it. Guard the absence so a future
    // copy-paste from VllmPanel is flagged as a regression.
    render(<QwenPanel samples={[sampleWithQwen(0.82)]} />);
    expect(screen.queryByText(/workload:/i)).not.toBeInTheDocument();
  });
});

// "driving: <tag> ×N" sub-line (handoff Task 1 / 2026-06-10): derived ONLY
// from live-call groups whose `model` EXACTLY equals this panel's served
// model (qwen3.6-27b-nvfp4-mtp) — no substring matching, absent when none.
// Groups are CONSTRUCTED (synthetic counts); tags/models/backends are the
// live names (skeptic_attack + subagent.finding_skeptic_* are today's live
// qwen drivers).
describe("QwenPanel driving sub-line", () => {
  const DRIVING: LiveCalls = {
    active: true,
    count: 19,
    window_s: 60,
    calls_per_s: 0.32,
    last_call_at: "2026-06-10T08:00:06.4Z",
    caller_tags: [{ tag: "skeptic_attack", count: 12 }],
    model: "qwen3.6-27b-nvfp4-mtp",
    groups: [
      {
        tag: "skeptic_attack",
        model: "qwen3.6-27b-nvfp4-mtp",
        backend: "vllm-qwen",
        run_id: null,
        count: 12,
        last_call_at: "2026-06-10T08:00:06.4Z",
      },
      {
        tag: "subagent.finding_skeptic_1",
        model: "qwen3.6-27b-nvfp4-mtp",
        backend: "vllm-qwen",
        run_id: null,
        count: 5,
        last_call_at: "2026-06-10T08:00:05.5Z",
      },
      {
        // Gemma-served group — belongs to VllmPanel, not here.
        tag: "hypothesize",
        model: "gemma-4-26b-a4b",
        backend: "vllm-gemma",
        run_id: "loop_v0_2026-06-10_001",
        count: 4,
        last_call_at: "2026-06-10T08:00:05.0Z",
      },
      {
        // NEAR-MISS (constructed): a superstring of the served model name —
        // exact-match only, must never attribute to this panel.
        tag: "meta_review",
        model: "qwen3.6-27b-nvfp4-mtp-quant",
        backend: null,
        run_id: null,
        count: 9,
        last_call_at: "2026-06-10T08:00:04.0Z",
      },
    ],
  };

  it("renders 'driving: <tag> ×N' from exact-model groups only", () => {
    render(<QwenPanel samples={[sampleWithQwen(0.8)]} liveCalls={DRIVING} />);
    const line = screen.getByTestId("qwen-driving");
    expect(line).toHaveTextContent("driving:");
    expect(line).toHaveTextContent("skeptic_attack");
    expect(line).toHaveTextContent("×12");
    expect(line).toHaveTextContent("subagent.finding_skeptic_1");
    expect(line).toHaveTextContent("×5");
    // The gemma-served group and the near-miss model never show here.
    expect(line.textContent).not.toContain("hypothesize");
    expect(line.textContent).not.toContain("meta_review");
  });

  it("renders the sub-line even in the 'no data' body state (load is load)", () => {
    // The driving derivation comes from the call log, not the sampler —
    // a panel whose /metrics reader is down can still be the busy backend.
    render(<QwenPanel samples={[sampleWithoutQwen()]} liveCalls={DRIVING} />);
    expect(screen.getByTestId("qwen-driving")).toHaveTextContent(
      "skeptic_attack",
    );
  });

  it("is ABSENT when no group's model exactly matches", () => {
    render(
      <QwenPanel
        samples={[sampleWithQwen(0.8)]}
        liveCalls={{
          ...DRIVING,
          groups: DRIVING.groups!.filter(
            (g) => g.model !== "qwen3.6-27b-nvfp4-mtp",
          ),
        }}
      />,
    );
    expect(screen.queryByTestId("qwen-driving")).toBeNull();
  });

  it("is ABSENT when liveCalls is not provided (additive prop)", () => {
    render(<QwenPanel samples={[sampleWithQwen(0.8)]} />);
    expect(screen.queryByTestId("qwen-driving")).toBeNull();
  });
});
