// nowVerdict.computeActivity — the pure three-state verdict shared by the
// merged NowBoard headline strip and the (S3-dying) SystemActivityHero. The
// behavior pins are PORTED from tests/test_system_activity_hero.tsx (which
// stays until the hero dies in S3): the machine must never read idle while
// it works, and a stale live-call snapshot must never light it. Pure-function
// assertions — no render, no mocks.
import { describe, expect, it } from "vitest";
import { computeActivity } from "../src/components/nowVerdict";
import type { LiveCalls } from "../src/types/activity";
import type { ActiveIteration, TelemetrySample } from "../src/types/schemas";

// Fixed clock: all fixtures are aged relative to this instant.
const NOW = Date.parse("2026-06-09T20:00:00.000+00:00");
const FRESH_TS = "2026-06-09T19:59:55.000+00:00"; // 5s ago
const STALE_TS = "2026-06-09T16:00:00.000+00:00"; // 4h ago

function liveCalls(overrides: Partial<LiveCalls> = {}): LiveCalls {
  return {
    active: true,
    count: 4,
    window_s: 15,
    calls_per_s: 0.27,
    last_call_at: FRESH_TS,
    caller_tags: [{ tag: "nara.run_iteration", count: 4 }],
    model: "gemma-4-26b-a4b",
    ...overrides,
  };
}

function telemetry(
  utilPct: number | null,
  vllm?: { running_requests?: number; tokens_per_sec_decode?: number | null },
): TelemetrySample {
  return {
    timestamp: FRESH_TS,
    gpu: {
      util_pct: utilPct,
      mem_used_mb: null,
      mem_total_mb: null,
      temp_c: 60,
      power_w: 40,
    },
    host: null,
    vllm: vllm
      ? {
          running_requests: vllm.running_requests ?? 0,
          waiting_requests: 0,
          gpu_cache_usage_pct: 10,
          gpu_prefix_cache_hit_rate: null,
          tokens_per_sec_decode: vllm.tokens_per_sec_decode ?? null,
          mtp_acceptance_rate: null,
          mtp_draft_tokens: null,
          mtp_accepted_tokens: null,
        }
      : null,
    processes: [],
    read_errors: null,
  };
}

const iteration: ActiveIteration = {
  iteration_id: "iter-2026-06-09-003",
  topic: "lit-pipe gate refinement",
  started_at: FRESH_TS,
  current_step: "summarize_paper",
};

describe("computeActivity (nowVerdict)", () => {
  it("registered run WITH calls flowing prefers registered and names it", () => {
    const v = computeActivity(
      {
        activeIteration: iteration,
        liveCalls: liveCalls(),
        telemetry: telemetry(96, {
          running_requests: 1,
          tokens_per_sec_decode: 51.6,
        }),
      },
      NOW,
    );
    expect(v.state).toBe("registered");
    expect(v.headline).toBe(
      "RUNNING — lit-pipe gate refinement · summarize_paper",
    );
    // strongest evidence still built alongside the registered headline
    const evidence = v.evidence.join(" · ");
    expect(evidence).toContain("nara.run_iteration × gemma-4-26b-a4b");
    expect(evidence).toContain("GPU 96%");
    expect(evidence).toContain("51.6 tok/s decode");
  });

  it("registered via coordinator active run", () => {
    const v = computeActivity(
      {
        coordinatorActive: {
          kind: "coordinator",
          run_id: "coord-001",
          label: "coordinator cycle",
          current_step: "plan",
        },
      },
      NOW,
    );
    expect(v.state).toBe("registered");
    expect(v.headline).toBe("RUNNING — coordinator cycle · plan");
  });

  it("no registered run + fresh calls -> busy-unregistered (aggregate phrasing)", () => {
    const v = computeActivity(
      {
        liveCalls: liveCalls(),
        telemetry: telemetry(96, { running_requests: 1 }),
      },
      NOW,
    );
    expect(v.state).toBe("busy-unregistered");
    expect(v.headline).toContain(
      "BUSY (unregistered) — nara.run_iteration driving gemma-4-26b-a4b · 4 calls/15s · GPU 96%",
    );
    expect(v.headline).toContain(
      "activity without provenance (see reconciliation plan A1)",
    );
  });

  it("busy-unregistered with groups[] names the top groups (named rollup)", () => {
    const v = computeActivity(
      {
        liveCalls: liveCalls({
          count: 16,
          model: "qwen3.6-27b-nvfp4-mtp",
          caller_tags: [{ tag: "skeptic_attack", count: 12 }],
          groups: [
            {
              tag: "skeptic_attack",
              model: "qwen3.6-27b-nvfp4-mtp",
              backend: "vllm-qwen",
              run_id: null,
              count: 12,
              last_call_at: FRESH_TS,
            },
            {
              tag: "subagent.finding_skeptic_1",
              model: "qwen3.6-27b-nvfp4-mtp",
              backend: "vllm-qwen",
              run_id: null,
              count: 4,
              last_call_at: FRESH_TS,
            },
            {
              // Third group — beyond the top-2 headline cap; never named.
              tag: "topicality_check",
              model: "gemma-4-26b-a4b",
              backend: "vllm-gemma",
              run_id: null,
              count: 1,
              last_call_at: FRESH_TS,
            },
          ],
        }),
        telemetry: telemetry(96, { running_requests: 1 }),
      },
      NOW,
    );
    // State machine untouched — only the headline string changed.
    expect(v.state).toBe("busy-unregistered");
    expect(v.headline).toContain("skeptic_attack ×12 on qwen3.6-27b-nvfp4-mtp");
    expect(v.headline).toContain("subagent.finding_skeptic_1 ×4");
    expect(v.headline).toContain("no registered run");
    expect(v.headline).toContain("last 5.0s");
    // The anonymous phrasing is replaced by the named rollup.
    expect(v.headline).not.toContain("BUSY (unregistered)");
    expect(v.headline).not.toContain("topicality_check ×1");
  });

  it("stale snapshot's groups are NOT named (timestamp trusted over count)", () => {
    const v = computeActivity(
      {
        liveCalls: liveCalls({
          active: false,
          last_call_at: STALE_TS,
          groups: [
            {
              tag: "skeptic_attack",
              model: "qwen3.6-27b-nvfp4-mtp",
              backend: "vllm-qwen",
              run_id: null,
              count: 12,
              last_call_at: STALE_TS,
            },
          ],
        }),
        telemetry: telemetry(96),
      },
      NOW,
    );
    expect(v.state).toBe("busy-unregistered");
    expect(v.headline).not.toContain("skeptic_attack ×12");
    expect(v.headline).toContain("BUSY (unregistered)");
  });

  it("gpu-only load (no calls, no registered run) -> busy-unregistered", () => {
    const v = computeActivity({ telemetry: telemetry(96) }, NOW);
    expect(v.state).toBe("busy-unregistered");
    expect(v.headline).toContain("GPU 96%");
  });

  it("vllm running_requests alone -> busy-unregistered", () => {
    const v = computeActivity(
      { telemetry: telemetry(5, { running_requests: 1 }) },
      NOW,
    );
    expect(v.state).toBe("busy-unregistered");
  });

  it("nothing at all -> idle", () => {
    const v = computeActivity({}, NOW);
    expect(v.state).toBe("idle");
    expect(v.headline).toContain("IDLE");
  });

  it("calls present but stale last_call_at -> idle (timestamp trusted over count)", () => {
    const v = computeActivity(
      {
        liveCalls: liveCalls({ active: false, last_call_at: STALE_TS }),
        telemetry: telemetry(5),
      },
      NOW,
    );
    expect(v.state).toBe("idle");
    // the stale evidence is still built honestly
    expect(v.evidence.join(" · ")).toContain("last call");
  });

  it("NaN gpu util and malformed caller_tags never leak NaN", () => {
    const v = computeActivity(
      {
        liveCalls: {
          active: true,
          count: Number.NaN,
          window_s: null,
          calls_per_s: null,
          last_call_at: FRESH_TS,
          caller_tags: [
            { tag: { nested: "object" } },
            null,
            { tag: "novelty_classify" },
          ],
          model: null,
        } as unknown as LiveCalls,
        telemetry: telemetry(Number.NaN, { running_requests: Number.NaN }),
      },
      NOW,
    );
    // fresh last_call_at still lights the drift state
    expect(v.state).toBe("busy-unregistered");
    const all = `${v.headline} ${v.evidence.join(" · ")}`;
    expect(all).not.toContain("NaN");
    // the first legible tag survives the malformed leading entries
    expect(all).toContain("novelty_classify");
  });

  it("null gpu block and null vllm are safe", () => {
    const sample: TelemetrySample = {
      timestamp: FRESH_TS,
      gpu: null,
      host: null,
      vllm: null,
      processes: [],
      read_errors: null,
    };
    expect(computeActivity({ telemetry: sample }, NOW).state).toBe("idle");
  });
});
