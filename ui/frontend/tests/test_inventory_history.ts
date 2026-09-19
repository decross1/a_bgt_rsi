import { describe, expect, it } from "vitest";
import type { ServedModel } from "../src/api/http";
import type { VllmSample } from "../src/types/schemas";
import { appendInventoryHistory } from "../src/routes/Pulse";

function metrics(decode: number): VllmSample {
  return {
    running_requests: 1,
    waiting_requests: 0,
    gpu_cache_usage_pct: 20,
    gpu_prefix_cache_hit_rate: null,
    tokens_per_sec_decode: decode,
    mtp_acceptance_rate: null,
    mtp_draft_tokens: 0,
    mtp_accepted_tokens: 0,
  };
}

function flash(probedAt: string, decode: number | null): ServedModel {
  return {
    url: "http://127.0.0.1:8012",
    model: "qwen3.8-flash-next-mia",
    error: null,
    probed_at: probedAt,
    configured_model: "qwen3.8-flash-next-mia",
    configured_max_context_tokens: 32768,
    observed_max_context_tokens: 32768,
    deployment_role: "research_candidate",
    benchmark_cohort: "flash",
    promotion_authorized: false,
    models_endpoint_status: "available",
    service_status: "online",
    identity_status: "match",
    metrics_endpoint_status: decode == null ? "unreachable" : "available",
    activity_status: decode == null ? "unknown" : "busy",
    metrics: decode == null ? null : metrics(decode),
    metrics_error: decode == null ? "timeout" : null,
  };
}

describe("inventory metric history", () => {
  it("adds each real Flash probe once and retains successive values", () => {
    const first = appendInventoryHistory(
      {},
      [["flash", flash("2026-09-18T12:00:00Z", 14)]],
      { flash: "flash-generation-a" },
    );
    const cachedReplay = appendInventoryHistory(
      first,
      [["flash", flash("2026-09-18T12:00:00Z", 99)]],
      { flash: "flash-generation-a" },
    );
    expect(cachedReplay).toBe(first);
    expect(cachedReplay.flash.points).toHaveLength(1);
    expect(cachedReplay.flash.points[0].metrics?.tokens_per_sec_decode).toBe(14);

    const second = appendInventoryHistory(
      cachedReplay,
      [["flash", flash("2026-09-18T12:00:30Z", 18)]],
      { flash: "flash-generation-a" },
    );
    expect(second.flash.points.map((point) => point.metrics?.tokens_per_sec_decode)).toEqual([14, 18]);
  });

  it("records a failed-metrics gap and resets when runtime identity changes", () => {
    const first = appendInventoryHistory(
      {},
      [["flash", flash("2026-09-18T12:00:00Z", 14)]],
      { flash: "flash-generation-a" },
    );
    const gap = appendInventoryHistory(
      first,
      [["flash", flash("2026-09-18T12:00:30Z", null)]],
      { flash: "flash-generation-a" },
    );
    expect(gap.flash.points.map((point) => point.metrics)).toEqual([
      metrics(14),
      null,
    ]);

    const reset = appendInventoryHistory(
      gap,
      [["flash", flash("2026-09-18T12:01:00Z", 21)]],
      { flash: "flash-generation-b" },
    );
    expect(reset.flash.points).toHaveLength(1);
    expect(reset.flash.points[0].metrics?.tokens_per_sec_decode).toBe(21);
  });
});
