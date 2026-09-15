// ModelServerCard — the parameterized VllmPanel+QwenPanel merge (UI
// simplification S1). The meaningful cases from both retired suites, run
// against BOTH parameterizations: MTP tile coloring, the Gemma-only workload
// pill, the body states, the core/internals partition, and the
// exact-served-model "driving" attribution.
//
// LAST-GOOD RETENTION (residual fix 5, 2026-08-18): the badge + body used to
// key off the LATEST sample alone — one missed scrape swapped the body to
// "/metrics unavailable" under a hard-red badge. Now: up to 2 trailing
// misses keep the last-good data with an explicit "last sample Xs ago" note
// and an amber "● stale" badge; only 3 consecutive misses (or no data ever)
// degrade the body, with "● down" reserved for those cases.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LiveCalls } from "../src/types/activity";
import type { ServedModel } from "../src/api/http";
import type { TelemetrySample } from "../src/types/schemas";

const mocks = vi.hoisted(() => ({
  getWorkloadHint: vi.fn().mockResolvedValue({
    available: true,
    sample_size: 100,
    calls_per_s: 0.4,
    median_output_tokens: 2,
    regime: "short_completion",
    expected_decode_tok_s_lower: 8,
    expected_decode_tok_s_upper: 14,
    window_s: 120,
    note: "prefill-bound",
  }),
}));
vi.mock("../src/api/http", () => ({
  getWorkloadHint: mocks.getWorkloadHint,
}));

import ModelServerCard, {
  QWEN_SERVED_MODEL,
  VLLM_SERVED_MODEL,
} from "../src/components/ModelServerCard";

function vllmBlock(mtpAcceptance: number | null) {
  return {
    running_requests: 1,
    waiting_requests: 0,
    gpu_cache_usage_pct: 12,
    gpu_prefix_cache_hit_rate: null,
    tokens_per_sec_decode: 69,
    mtp_acceptance_rate: mtpAcceptance,
    mtp_draft_tokens: null,
    mtp_accepted_tokens: null,
  };
}

function gemmaSample(mtpAcceptance: number | null): TelemetrySample {
  return {
    timestamp: "2026-08-14T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: vllmBlock(mtpAcceptance),
    processes: [],
    read_errors: null,
  };
}

function qwenSample(mtpAcceptance: number | null): TelemetrySample {
  return {
    timestamp: "2026-08-14T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: null,
    vllm_qwen: vllmBlock(mtpAcceptance),
    processes: [],
    read_errors: null,
  };
}

function emptySample(): TelemetrySample {
  return {
    timestamp: "2026-08-14T10:00:00.000+00:00",
    gpu: null,
    host: null,
    vllm: null,
    vllm_qwen: null,
    processes: [],
    read_errors: null,
  };
}

function renderGemma(samples: TelemetrySample[], liveCalls?: LiveCalls | null) {
  return render(
    <ModelServerCard
      title="gemma-4-26b-a4b"
      servedModel={VLLM_SERVED_MODEL}
      pick={(s) => s.vllm}
      samples={samples}
      liveCalls={liveCalls}
      accent="zinc"
      workloadHint
    />,
  );
}

function renderQwen(samples: TelemetrySample[], liveCalls?: LiveCalls | null) {
  return render(
    <ModelServerCard
      title="Qwen3.6-27B · NVFP4-MTP"
      servedModel={QWEN_SERVED_MODEL}
      pick={(s) => s.vllm_qwen}
      samples={samples}
      liveCalls={liveCalls}
      accent="sky"
      transientDropBanner
    />,
  );
}

function inventory(overrides: Partial<ServedModel> = {}): ServedModel {
  return {
    url: "http://127.0.0.1:8012",
    model: "qwen3.8-flash-next",
    error: null,
    probed_at: new Date().toISOString(),
    configured_model: "qwen3.8-flash-next",
    configured_max_context_tokens: 16384,
    observed_max_context_tokens: 32768,
    deployment_role: "research_candidate",
    benchmark_cohort: "flash",
    promotion_authorized: false,
    models_endpoint_status: "available",
    service_status: "online",
    identity_status: "match",
    metrics_endpoint_status: "available",
    activity_status: "idle",
    metrics: vllmBlock(null),
    metrics_error: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ModelServerCard MTP tile (both parameterizations)", () => {
  it("shows 'MTP off / metric absent' in gray when the rate is null", () => {
    renderGemma([gemmaSample(null)]);
    const value = screen.getByText("MTP off / metric absent");
    expect(value.className).toContain("text-zinc-600");
  });

  it("colors a healthy acceptance rate (>=50%) green", () => {
    renderQwen([qwenSample(0.82)]);
    const value = screen.getByText("82.0 %");
    expect(value.className).toContain("text-emerald-400");
  });

  it("colors a poor acceptance rate (<50%) amber", () => {
    renderGemma([gemmaSample(0.3)]);
    const value = screen.getByText("30.0 %");
    expect(value.className).toContain("text-amber-400");
  });
});

describe("ModelServerCard body states", () => {
  it("gemma (binary mode): NEVER any block -> unavailable, badge down", () => {
    renderGemma([{ ...gemmaSample(0.8), vllm: null }]);
    expect(screen.getByText(/\/metrics unavailable/)).toBeInTheDocument();
    const badge = screen.getByTestId(`${VLLM_SERVED_MODEL}-status`);
    expect(badge.textContent).toBe("● down");
    expect(badge.className).toContain("text-red-400");
  });

  it("qwen (tri-state): every sample missing the block -> unreachable", () => {
    renderQwen([emptySample(), emptySample()]);
    expect(screen.getByText(/endpoint unreachable/)).toBeInTheDocument();
    expect(
      screen.getByTestId(`${QWEN_SERVED_MODEL}-status`).textContent,
    ).toBe("● down");
  });

  it("qwen: empty samples array -> unreachable", () => {
    renderQwen([]);
    expect(screen.getByText(/endpoint unreachable/)).toBeInTheDocument();
  });

  it("ONE missed scrape KEEPS the last-good body with an explicit staleness note (fix 5)", () => {
    // The reviewer's finding: the body keyed off the latest sample alone,
    // so one missed scrape swapped a healthy card to its no-data message.
    renderQwen([qwenSample(0.7), emptySample()]);
    // The core rows still render — from the retained last-good sample.
    expect(screen.getByText("Decode tok/s")).toBeInTheDocument();
    expect(screen.getByText("KV-cache usage")).toBeInTheDocument();
    // …and the retention is HONEST: an explicit staleness note names the
    // last sample's age and the miss count.
    const note = screen.getByTestId(`${QWEN_SERVED_MODEL}-stale-note`);
    expect(note).toHaveTextContent(/last sample .* ago/);
    expect(note).toHaveTextContent("1 missed scrape");
    // No degrade message anywhere.
    expect(screen.queryByText(/\/metrics dropped/)).toBeNull();
    expect(screen.queryByText(/endpoint unreachable/)).toBeNull();
  });

  it("the badge distinguishes STALE TELEMETRY from DOWN (fix 5)", () => {
    renderQwen([qwenSample(0.7), emptySample()]);
    const badge = screen.getByTestId(`${QWEN_SERVED_MODEL}-status`);
    expect(badge.textContent).toBe("● stale");
    expect(badge.className).toContain("text-amber-400");
  });

  it("binary mode retains through a short miss run too (gemma)", () => {
    renderGemma([gemmaSample(0.8), { ...gemmaSample(0.8), vllm: null }]);
    expect(screen.getByText("Decode tok/s")).toBeInTheDocument();
    expect(screen.queryByText(/\/metrics unavailable/)).toBeNull();
    expect(
      screen.getByTestId(`${VLLM_SERVED_MODEL}-stale-note`),
    ).toHaveTextContent(/last sample .* ago/);
    expect(
      screen.getByTestId(`${VLLM_SERVED_MODEL}-status`).textContent,
    ).toBe("● stale");
  });

  it("3 CONSECUTIVE misses degrade the body honestly: qwen -> dropped, badge down", () => {
    renderQwen([
      qwenSample(0.7),
      emptySample(),
      emptySample(),
      emptySample(),
    ]);
    expect(
      screen.getByText(/\/metrics dropped — 3 consecutive scrapes/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Decode tok/s")).toBeNull();
    const badge = screen.getByTestId(`${QWEN_SERVED_MODEL}-status`);
    expect(badge.textContent).toBe("● down");
    expect(badge.className).toContain("text-red-400");
  });

  it("3 consecutive misses in binary mode -> unavailable (gemma)", () => {
    renderGemma([
      gemmaSample(0.8),
      { ...gemmaSample(0.8), vllm: null },
      { ...gemmaSample(0.8), vllm: null },
      { ...gemmaSample(0.8), vllm: null },
    ]);
    expect(screen.getByText(/\/metrics unavailable/)).toBeInTheDocument();
    expect(
      screen.getByTestId(`${VLLM_SERVED_MODEL}-status`).textContent,
    ).toBe("● down");
  });

  it("a fresh latest sample shows NO staleness note", () => {
    renderQwen([emptySample(), qwenSample(0.82)]);
    expect(
      screen.queryByTestId(`${QWEN_SERVED_MODEL}-stale-note`),
    ).toBeNull();
  });

  it("status badge reads '● up' emerald when the latest sample carries the block", () => {
    renderQwen([qwenSample(0.82)]);
    const badge = screen.getByTestId(`${QWEN_SERVED_MODEL}-status`);
    expect(badge.textContent).toBe("● up");
    expect(badge.className).toContain("text-emerald-400");
  });

  it("keeps both CORE rows visible and tucks all INTERNALS inside the disclosure", () => {
    renderQwen([qwenSample(0.82)]);
    const details = screen.getByTestId(`${QWEN_SERVED_MODEL}-details`);
    expect(screen.getByText("Decode tok/s").closest("details")).toBeNull();
    expect(screen.getByText("KV-cache usage").closest("details")).toBeNull();
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
    expect(screen.getByText("show internals ▸")).toBeInTheDocument();
    expect(screen.getByText("hide internals ▾")).toBeInTheDocument();
  });
});

describe("ModelServerCard dynamic endpoint inventory", () => {
  it("separates an online candidate identity from its evaluation-only role", () => {
    render(
      <ModelServerCard
        title="qwen3.8-flash-next"
        servedModel="qwen3.8-flash-next"
        endpointName="flash"
        inventory={inventory()}
        pick={() => null}
        samples={[]}
        accent="violet"
      />,
    );
    expect(screen.getByTestId("qwen3.8-flash-next-status")).toHaveTextContent("online");
    expect(screen.getByTestId("flash-inventory")).toHaveTextContent("Research candidate");
    expect(screen.getByTestId("flash-inventory")).toHaveTextContent("Evaluation only");
    expect(screen.getByText("Decode tok/s")).toBeInTheDocument();
    expect(screen.getByText("16K")).toBeInTheDocument();
    expect(screen.getByText("32K")).toBeInTheDocument();
    expect(screen.getByText("Server-advertised context")).toBeInTheDocument();
  });

  it("does not turn an unreachable configured candidate into a zero measurement", () => {
    render(
      <ModelServerCard
        title="qwen3.8-flash-next"
        servedModel="unobserved-flash"
        endpointName="flash"
        inventory={inventory({
          model: null,
          service_status: "offline",
          models_endpoint_status: "unreachable",
          identity_status: "unknown",
          metrics_endpoint_status: "unreachable",
          activity_status: "unknown",
          metrics: null,
        })}
        pick={() => null}
        samples={[]}
        accent="violet"
      />,
    );
    expect(screen.getByTestId("unobserved-flash-status")).toHaveTextContent("offline");
    expect(screen.getByTestId("unobserved-flash-status")).toHaveClass("text-red-400");
    expect(screen.getByText(/Live metrics were not observed/)).toBeInTheDocument();
    expect(screen.queryByText("Decode tok/s")).toBeNull();
    expect(screen.queryByText("0.0")).toBeNull();
  });

  it("shows an optional offline candidate as configured standby rather than an outage", () => {
    render(
      <ModelServerCard
        title="qwen3.8-flash-next"
        servedModel="unobserved-flash"
        endpointName="flash"
        inventory={inventory({
          model: null,
          service_status: "offline",
          models_endpoint_status: "unreachable",
          identity_status: "unknown",
          metrics_endpoint_status: "unreachable",
          activity_status: "unknown",
          metrics: null,
        })}
        serviceExpectation="standby"
        pick={() => null}
        samples={[]}
        accent="violet"
      />,
    );
    const status = screen.getByTestId("unobserved-flash-status");
    expect(status).toHaveTextContent("not serving");
    expect(status.className).toContain("text-zinc-500");
    expect(status.className).not.toContain("text-red-400");
    expect(screen.getByText(/optional research candidate is configured/)).toBeInTheDocument();
  });

  it.each([
    {
      expectation: "expected_offline" as const,
      role: "production_resident" as const,
      status: "offline · expected during research",
      note: /intentionally stopped for the controller-bound research window/,
    },
    {
      expectation: "starting" as const,
      role: "research_candidate" as const,
      status: "starting",
      note: /model endpoint was not ready at the last probe/,
    },
  ])("explains controller-bound offline state as $status", ({ expectation, role, status, note }) => {
    render(
      <ModelServerCard
        title="configured-model"
        servedModel="unobserved-endpoint"
        endpointName="endpoint"
        inventory={inventory({
          model: null,
          deployment_role: role,
          service_status: "offline",
          models_endpoint_status: "unreachable",
          identity_status: "unknown",
          metrics_endpoint_status: "unreachable",
          activity_status: "unknown",
          metrics: null,
        })}
        serviceExpectation={expectation}
        pick={() => null}
        samples={[]}
      />,
    );
    const badge = screen.getByTestId("unobserved-endpoint-status");
    expect(badge).toHaveTextContent(status);
    expect(badge.className).not.toContain("text-red-400");
    expect(screen.getByText(note)).toBeInTheDocument();
  });

  it("makes a served/configured identity mismatch a red primary state", () => {
    render(
      <ModelServerCard
        title="unexpected-model"
        servedModel="unexpected-model"
        endpointName="flash"
        inventory={inventory({ model: "unexpected-model", identity_status: "mismatch" })}
        pick={() => null}
        samples={[]}
        accent="violet"
      />,
    );
    const status = screen.getByTestId("unexpected-model-status");
    expect(status).toHaveTextContent("identity mismatch");
    expect(status.className).toContain("text-red-400");
    expect(screen.getByText(/Configured:/)).toHaveTextContent("qwen3.8-flash-next");
  });
});

describe("ModelServerCard workload-hint pill (Gemma-only)", () => {
  it("renders the pill when workloadHint is set and the hint resolves", async () => {
    renderGemma([gemmaSample(0.8)]);
    await waitFor(() =>
      expect(screen.getByText(/workload:/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/short-completion/)).toBeInTheDocument();
  });

  it("qwen parameterization omits the pill AND never fetches the hint", () => {
    renderQwen([qwenSample(0.82)]);
    expect(screen.queryByText(/workload:/i)).not.toBeInTheDocument();
    expect(mocks.getWorkloadHint).not.toHaveBeenCalled();
  });
});

// "driving: <tag> ×N" — derived ONLY from live-call groups whose `model`
// EXACTLY equals the card's served model. Groups are CONSTRUCTED (synthetic
// counts); tags/models/backends are the live names.
const DRIVING: LiveCalls = {
  active: true,
  count: 19,
  window_s: 60,
  calls_per_s: 0.32,
  last_call_at: "2026-08-14T10:00:06.4Z",
  caller_tags: [{ tag: "skeptic_attack", count: 12 }],
  model: "qwen3.6-27b-nvfp4-mtp",
  groups: [
    {
      tag: "skeptic_attack",
      model: "qwen3.6-27b-nvfp4-mtp",
      backend: "vllm-qwen",
      run_id: null,
      count: 12,
      last_call_at: "2026-08-14T10:00:06.4Z",
    },
    {
      tag: "hypothesize",
      model: "gemma-4-26b-a4b",
      backend: "vllm-gemma",
      run_id: "loop_v0_2026-08-14_001",
      count: 4,
      last_call_at: "2026-08-14T10:00:05.0Z",
    },
    {
      // NEAR-MISS (constructed): a superstring of a served model name —
      // exact-match only, must never attribute to either card.
      tag: "meta_review",
      model: "gemma-4-26b-a4b-quant",
      backend: null,
      run_id: null,
      count: 9,
      last_call_at: "2026-08-14T10:00:04.0Z",
    },
  ],
};

describe("ModelServerCard driving sub-line", () => {
  it("gemma card attributes exact-model groups only", () => {
    renderGemma([gemmaSample(0.8)], DRIVING);
    const line = screen.getByTestId(`${VLLM_SERVED_MODEL}-driving`);
    expect(line).toHaveTextContent("driving:");
    expect(line).toHaveTextContent("hypothesize");
    expect(line).toHaveTextContent("×4");
    expect(line.textContent).not.toContain("skeptic_attack");
    expect(line.textContent).not.toContain("meta_review");
  });

  it("qwen card attributes exact-model groups only", () => {
    renderQwen([qwenSample(0.8)], DRIVING);
    const line = screen.getByTestId(`${QWEN_SERVED_MODEL}-driving`);
    expect(line).toHaveTextContent("skeptic_attack");
    expect(line).toHaveTextContent("×12");
    expect(line.textContent).not.toContain("hypothesize");
    expect(line.textContent).not.toContain("meta_review");
  });

  it("renders the sub-line even in the no-data body state (load is load)", () => {
    // The driving derivation comes from the call log, not the sampler — a
    // card whose /metrics reader is down can still be the busy backend.
    renderQwen([emptySample()], DRIVING);
    expect(
      screen.getByTestId(`${QWEN_SERVED_MODEL}-driving`),
    ).toHaveTextContent("skeptic_attack");
  });

  it("is ABSENT when no group's model exactly matches", () => {
    renderQwen([qwenSample(0.8)], {
      ...DRIVING,
      groups: DRIVING.groups!.filter(
        (g) => g.model !== "qwen3.6-27b-nvfp4-mtp",
      ),
    });
    expect(screen.queryByTestId(`${QWEN_SERVED_MODEL}-driving`)).toBeNull();
  });

  it("is ABSENT when liveCalls is not provided (additive prop)", () => {
    renderGemma([gemmaSample(0.8)]);
    expect(screen.queryByTestId(`${VLLM_SERVED_MODEL}-driving`)).toBeNull();
  });
});
