// HealthVerdict composes connection / telemetry-staleness / read_errors /
// Gemma reachability into one healthy/degraded/down verdict. These tests
// pin the precedence (down > degraded > healthy) and the named-subsystem
// reasons, plus the rendered hero.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HealthVerdict, {
  computeVerdict,
  excludeQwenReadErrors,
  type VerdictInput,
} from "../src/components/HealthVerdict";

// Canonical sampler read_errors keys, mirrored from ui/sampler/sampler.py.
// The verdict logic joins whatever keys arrive, so the tests must exercise
// the REAL vocabulary, not invented names, to mean anything.
const SAMPLER_KEYS = {
  nvidiaSmi: "nvidia-smi",
  psutil: "psutil",
  thermal: "thermal",
  vllm: "vllm-metrics",
  vllmQwen: "vllm-qwen-metrics",
} as const;

// A fully-healthy baseline; each test perturbs one field.
function base(): VerdictInput {
  return {
    connected: true,
    hasTelemetry: true,
    ageMs: 1000,
    readErrors: [],
    gemmaUp: true,
  };
}

describe("computeVerdict", () => {
  it("is healthy when connected, fresh, error-free, and Gemma is up", () => {
    const v = computeVerdict(base());
    expect(v.level).toBe("healthy");
    expect(v.reasons).toHaveLength(0);
  });

  it("is degraded from telemetry staleness (>5s)", () => {
    const v = computeVerdict({ ...base(), ageMs: 9000 });
    expect(v.level).toBe("degraded");
    expect(v.headline).toContain("stale");
    expect(v.headline).toContain("9s");
  });

  it("is degraded from read_errors and names the real failing subsystems", () => {
    // Real sampler keys (see SAMPLER_KEYS / ui/sampler/sampler.py), not the
    // fictional "vllm"/"gpu" the fixtures used to carry.
    const v = computeVerdict({
      ...base(),
      readErrors: [SAMPLER_KEYS.vllm, SAMPLER_KEYS.nvidiaSmi],
    });
    expect(v.level).toBe("degraded");
    expect(v.headline).toContain("vllm-metrics");
    expect(v.headline).toContain("nvidia-smi");
  });

  it("is down when the model server is unreachable", () => {
    const v = computeVerdict({ ...base(), gemmaUp: false });
    expect(v.level).toBe("down");
    expect(v.headline).toContain("Gemma");
  });

  it("is down when disconnected, even if other signals look fine", () => {
    const v = computeVerdict({ ...base(), connected: false });
    expect(v.level).toBe("down");
    expect(v.headline).toContain("disconnected");
  });

  it("is down when no telemetry has arrived yet", () => {
    const v = computeVerdict({ ...base(), hasTelemetry: false, ageMs: null });
    expect(v.level).toBe("down");
    expect(v.headline).toContain("no telemetry");
  });

  it("lets down win over a concurrent staleness fault (worst wins)", () => {
    const v = computeVerdict({
      ...base(),
      gemmaUp: false,
      ageMs: 9000,
    });
    expect(v.level).toBe("down");
  });

  it("collects multiple degraded reasons (stale + read_errors)", () => {
    const v = computeVerdict({
      ...base(),
      ageMs: 9000,
      readErrors: [SAMPLER_KEYS.psutil],
    });
    expect(v.level).toBe("degraded");
    expect(v.reasons.length).toBeGreaterThan(1);
    expect(v.reasons.some((r) => r.includes("psutil"))).toBe(true);
  });

  // Qwen is excluded from the verdict by design. The Dashboard filters the
  // "vllm-qwen-metrics" key out of readErrors BEFORE computeVerdict sees it,
  // so a Qwen-only read error must not push the verdict to degraded.
  it("stays healthy when the ONLY read error is the (filtered) Qwen key", () => {
    const filtered = excludeQwenReadErrors([SAMPLER_KEYS.vllmQwen]);
    const v = computeVerdict({ ...base(), readErrors: filtered });
    expect(filtered).toHaveLength(0);
    expect(v.level).toBe("healthy");
    expect(v.reasons).toHaveLength(0);
  });

  it("still degrades on a real key when a Qwen key is also present (Qwen dropped)", () => {
    const filtered = excludeQwenReadErrors([
      SAMPLER_KEYS.vllmQwen,
      SAMPLER_KEYS.thermal,
    ]);
    const v = computeVerdict({ ...base(), readErrors: filtered });
    expect(filtered).toEqual([SAMPLER_KEYS.thermal]);
    expect(v.level).toBe("degraded");
    expect(v.headline).toContain("thermal");
    expect(v.headline).not.toContain("qwen");
  });

  // Freshness-unknown guard. The Dashboard coerces a non-finite age (e.g. a
  // malformed timestamp -> Date.parse NaN) to null before passing it in. A
  // null age with telemetry present must not be treated as fresh-and-healthy
  // by accident, but it is also not itself a fault: staleness simply cannot
  // be evaluated, so it raises no degraded reason here (documented edge).
  it("does not flag staleness when ageMs is null (freshness unknown)", () => {
    const v = computeVerdict({ ...base(), ageMs: null });
    expect(v.level).toBe("healthy");
    expect(v.reasons.some((r) => r.includes("stale"))).toBe(false);
  });
});

describe("excludeQwenReadErrors", () => {
  it("drops the Qwen metrics key and keeps all other sampler keys", () => {
    const out = excludeQwenReadErrors([
      SAMPLER_KEYS.nvidiaSmi,
      SAMPLER_KEYS.vllmQwen,
      SAMPLER_KEYS.vllm,
    ]);
    expect(out).toEqual([SAMPLER_KEYS.nvidiaSmi, SAMPLER_KEYS.vllm]);
  });

  it("returns an empty list unchanged", () => {
    expect(excludeQwenReadErrors([])).toEqual([]);
  });
});

describe("HealthVerdict component", () => {
  it("renders the DOWN level and reason for an unreachable model server", () => {
    render(<HealthVerdict {...base()} gemmaUp={false} />);
    const el = screen.getByTestId("health-verdict");
    expect(el.getAttribute("data-level")).toBe("down");
    expect(screen.getByText("DOWN")).toBeInTheDocument();
    expect(screen.getByText(/Gemma model server unreachable/)).toBeInTheDocument();
  });

  it("renders HEALTHY with the nominal headline", () => {
    render(<HealthVerdict {...base()} />);
    expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    expect(screen.getByText("all systems nominal")).toBeInTheDocument();
  });
});
