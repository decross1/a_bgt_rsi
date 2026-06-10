// SystemActivityHero: the dashboard must never read "idle" while the machine
// works. Three states from pure fixture props (no fetch mocks): registered
// (emerald, wins even with calls flowing), busy-unregistered (amber — calls
// OR gpu OR running requests with no registered run), idle (zinc — including
// the calls-present-but-stale-timestamp snapshot, which must NOT light it).
import { render, screen } from "@testing-library/react";
import SystemActivityHero from "../src/components/SystemActivityHero";
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

describe("SystemActivityHero", () => {
  it("registered run WITH calls flowing prefers registered (emerald), names it", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        activeIteration={iteration}
        liveCalls={liveCalls()}
        telemetry={telemetry(96, { running_requests: 1, tokens_per_sec_decode: 51.6 })}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "registered");
    expect(hero.textContent).toContain("RUNNING — lit-pipe gate refinement · summarize_paper");
    // strongest evidence still shown alongside the registered headline
    const evidence = screen.getByTestId("system-activity-evidence");
    expect(evidence.textContent).toContain("nara.run_iteration × gemma-4-26b-a4b");
    expect(evidence.textContent).toContain("GPU 96%");
    expect(evidence.textContent).toContain("51.6 tok/s decode");
  });

  it("registered via coordinator active run", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        coordinatorActive={{
          kind: "coordinator",
          run_id: "coord-001",
          label: "coordinator cycle",
          current_step: "plan",
        }}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "registered");
    expect(hero.textContent).toContain("RUNNING — coordinator cycle · plan");
  });

  it("no registered run + fresh calls -> BUSY (unregistered), amber drift state", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        liveCalls={liveCalls()}
        telemetry={telemetry(96, { running_requests: 1 })}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "busy-unregistered");
    expect(hero.textContent).toContain(
      "BUSY (unregistered) — nara.run_iteration driving gemma-4-26b-a4b · 4 calls/15s · GPU 96%",
    );
    expect(hero.textContent).toContain(
      "activity without provenance (see reconciliation plan A1)",
    );
  });

  it("busy-unregistered with groups[] names the top groups (named rollup)", () => {
    // The 2026-06-10 legibility fix: the drift headline names WHO is driving
    // WHAT instead of the anonymous aggregate. Group rows are CONSTRUCTED
    // (synthetic counts); tags/models/backends are the live names.
    render(
      <SystemActivityHero
        nowMs={NOW}
        liveCalls={liveCalls({
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
              // Third group — beyond the top-2 headline cap; must not be named.
              tag: "topicality_check",
              model: "gemma-4-26b-a4b",
              backend: "vllm-gemma",
              run_id: null,
              count: 1,
              last_call_at: FRESH_TS,
            },
          ],
        })}
        telemetry={telemetry(96, { running_requests: 1 })}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    // State machine untouched — only the headline string changed.
    expect(hero).toHaveAttribute("data-state", "busy-unregistered");
    expect(hero.textContent).toContain(
      "skeptic_attack ×12 on qwen3.6-27b-nvfp4-mtp",
    );
    expect(hero.textContent).toContain("subagent.finding_skeptic_1 ×4");
    expect(hero.textContent).toContain("no registered run");
    expect(hero.textContent).toContain("last 5.0s");
    // The anonymous phrasing is replaced by the named rollup (the BUSY state
    // label itself stays).
    expect(hero.textContent).not.toContain("BUSY (unregistered)");
    expect(hero.textContent).not.toContain("topicality_check ×1");
  });

  it("stale snapshot's groups are NOT named (timestamp trusted over count)", () => {
    // GPU keeps the drift state lit, but the call groups are from a stale
    // aggregate — naming them as live work would lie. Falls back to the
    // aggregate phrasing without the named rollup.
    render(
      <SystemActivityHero
        nowMs={NOW}
        liveCalls={liveCalls({
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
        })}
        telemetry={telemetry(96)}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "busy-unregistered");
    expect(hero.textContent).not.toContain("skeptic_attack ×12");
    expect(hero.textContent).toContain("BUSY (unregistered)");
  });

  it("gpu-only load (no calls, no registered run) -> BUSY (unregistered)", () => {
    render(<SystemActivityHero nowMs={NOW} telemetry={telemetry(96)} />);
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "busy-unregistered");
    expect(hero.textContent).toContain("GPU 96%");
  });

  it("vllm running_requests alone -> BUSY (unregistered)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        telemetry={telemetry(5, { running_requests: 1 })}
      />,
    );
    expect(screen.getByTestId("system-activity-hero")).toHaveAttribute(
      "data-state",
      "busy-unregistered",
    );
  });

  it("nothing at all -> idle (quiet zinc)", () => {
    render(<SystemActivityHero nowMs={NOW} />);
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "idle");
    expect(hero.textContent).toContain("IDLE");
  });

  it("calls present but stale last_call_at -> idle (timestamp trusted over count)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        liveCalls={liveCalls({ active: false, last_call_at: STALE_TS })}
        telemetry={telemetry(5)}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    expect(hero).toHaveAttribute("data-state", "idle");
    // the stale evidence is still rendered honestly
    expect(screen.getByTestId("system-activity-evidence").textContent).toContain(
      "last call",
    );
  });

  it("NaN gpu util and malformed caller_tags never render NaN or crash", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        liveCalls={
          {
            active: true,
            count: Number.NaN,
            window_s: null,
            calls_per_s: null,
            last_call_at: FRESH_TS,
            caller_tags: [{ tag: { nested: "object" } }, null, { tag: "novelty_classify" }],
            model: null,
          } as unknown as LiveCalls
        }
        telemetry={telemetry(Number.NaN, { running_requests: Number.NaN })}
      />,
    );
    const hero = screen.getByTestId("system-activity-hero");
    // fresh last_call_at still lights the drift state
    expect(hero).toHaveAttribute("data-state", "busy-unregistered");
    expect(hero.textContent).not.toContain("NaN");
    // the first legible tag survives the malformed leading entries
    expect(hero.textContent).toContain("novelty_classify");
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
    render(<SystemActivityHero nowMs={NOW} telemetry={sample} />);
    expect(screen.getByTestId("system-activity-hero")).toHaveAttribute(
      "data-state",
      "idle",
    );
  });
});
