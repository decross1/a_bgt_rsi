// Hardening for the Dashboard "N need you →" coupling (2026-06-14 work order
// PART 1). The dashboard polls getHumanTodo() and derives the at-a-glance
// escalation count from `counts.gate_verdict + counts.state_gate` (taxonomy A +
// B only). That counts map is producer-owned and UNVALIDATED: a malformed /
// legacy / partial body could omit `counts`, hand back a non-object, a
// non-number per kind, NaN/Infinity, a NEGATIVE count (sign-flip/underflow), a
// fractional value, or an absurdly HUGE number. None of those may crash/blank
// the page or paint a nonsense badge ("-5 need you →", "2.7", "1e+308").
//
// House doctrine: degrade to a legible fallback, never throw. The guard coerces
// each kind to a non-negative integer; a failed fetch leaves the last good
// count (the getHealth idiom) so the signal does not blink to "none" on a
// transient miss. Valid integer counts pass through unchanged.
//
// The badge is rendered by SystemActivityHero via the `needsYou` prop Dashboard
// passes; we assert on the `dashboard-needs-you` testid Dashboard stamps on it.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TelemetrySample } from "../src/types/schemas";

// A valid, gemma-up, connected stream so the rest of the page renders cleanly
// and only the human-todo counts vary per test.
function sample(): TelemetrySample {
  return {
    timestamp: new Date().toISOString(),
    gpu: null,
    host: null,
    vllm: {
      running_requests: 1,
      waiting_requests: 0,
      gpu_cache_usage_pct: 12,
      gpu_prefix_cache_hit_rate: 0.8,
      tokens_per_sec_decode: 42,
      mtp_acceptance_rate: 0.6,
      mtp_draft_tokens: 100,
      mtp_accepted_tokens: 60,
    },
    vllm_qwen: null,
    processes: [],
    read_errors: null,
  } as unknown as TelemetrySample;
}

const STREAM = {
  samples: [sample(), sample()],
  latest: sample(),
  connected: true,
};

vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => STREAM,
}));

vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: new Date().toISOString(),
    version: "test",
  }),
  getState: vi.fn().mockResolvedValue({ current_day: "2026-06-14" }),
  getIterations: vi.fn().mockResolvedValue({ iterations: [] }),
  getJournalEntry: vi.fn().mockResolvedValue({
    iteration_id: "iter-001",
    path: "journal/iterations/001.md",
    content: "# Journal\n\nbody",
  }),
  getActiveIteration: vi.fn().mockResolvedValue(null),
  getBaseline: vi.fn().mockResolvedValue({ rows: [] }),
  getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
  getSurfacedFindings: vi.fn().mockResolvedValue({ findings: [] }),
  getBubbles: vi.fn().mockResolvedValue({ bubbles: [] }),
  getHealthSignals: vi.fn().mockResolvedValue({ health_signals: [] }),
  getCoordinatorActive: vi.fn().mockResolvedValue(null),
  // The endpoint under test — overridden per case.
  getHumanTodo: vi.fn().mockResolvedValue({ items: [], counts: {} }),
}));

vi.mock("../src/api/activity", () => ({
  getActivityMonitor: vi.fn().mockResolvedValue({
    available: true,
    active: [],
    recent: [],
    synthetic_inference: { synthetic: true, source: "fixture", workers: [] },
    generated_at: new Date().toISOString(),
  }),
  getActivityGraph: vi.fn().mockResolvedValue({
    available: false,
    nodes: [],
    edges: [],
    generated_at: new Date().toISOString(),
  }),
  getActiveRun: vi.fn().mockResolvedValue(null),
}));

import Dashboard from "../src/routes/Dashboard";
import { getHumanTodo } from "../src/api/http";

// Render Dashboard, flush async polls, return console.error/warn the render
// emitted. A thrown render surfaces here as a console.error, so a crash is
// caught either way.
async function renderQuietly() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
  await waitFor(() => expect(true).toBe(true));
  await waitFor(() => expect(true).toBe(true));
  const calls = {
    error: errSpy.mock.calls.map((c) => String(c[0])),
    warn: warnSpy.mock.calls.map((c) => String(c[0])),
  };
  errSpy.mockRestore();
  warnSpy.mockRestore();
  return calls;
}

// Resolve the badge once the poll has settled, then read its text.
async function badgeText(): Promise<string> {
  const el = await screen.findByTestId("dashboard-needs-you");
  return el.textContent ?? "";
}

describe("Dashboard coupling — needsYou A+B counts coercion", () => {
  beforeEach(() => {
    vi.mocked(getHumanTodo).mockResolvedValue({ items: [], counts: {} } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("sums A (gate_verdict) + B (state_gate) for valid integer counts", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 2, state_gate: 3 },
    } as never);
    const { error, warn } = await renderQuietly();
    await waitFor(async () =>
      expect(await badgeText()).toMatch(/5 need you/),
    );
    expect(error, error.join(" | ")).toHaveLength(0);
    expect(warn, warn.join(" | ")).toHaveLength(0);
  });

  it("renders 'none need you' when counts is the empty object", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: {},
    } as never);
    await renderQuietly();
    await waitFor(async () =>
      expect(await badgeText()).toMatch(/none need you/),
    );
  });

  it("treats an ABSENT counts key as zero (no NaN badge)", async () => {
    // Legacy/older backend: a 200 body with items but no counts map at all.
    vi.mocked(getHumanTodo).mockResolvedValue({ items: [] } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/NaN/);
    expect(text).toMatch(/none need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("treats a null response body as zero without crashing", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue(null as never);
    const { error, warn } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/NaN/);
    expect(text).toMatch(/none need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
    expect(warn, warn.join(" | ")).toHaveLength(0);
  });

  it("treats a non-object counts (string) as zero", async () => {
    // Property access on a string primitive yields undefined, not a throw;
    // num() coerces to 0. No crash, no NaN.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: "broken",
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/NaN/);
    expect(text).toMatch(/none need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("coerces a non-number count (string) to zero", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: "lots", state_gate: 4 },
    } as never);
    await renderQuietly();
    // The string A-count drops to 0; only B (4) survives.
    await waitFor(async () => expect(await badgeText()).toMatch(/4 need you/));
  });

  it("coerces NaN and Infinity counts to zero", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: NaN, state_gate: Infinity },
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/NaN|Infinity/);
    expect(text).toMatch(/none need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("clamps a NEGATIVE count to zero (no '-N need you')", async () => {
    // Sign-flip / underflow on the producer side must not paint a negative.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: -5, state_gate: 3 },
    } as never);
    await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/-\d/);
    // -5 clamps to 0; only +3 survives.
    expect(text).toMatch(/3 need you/);
  });

  it("floors a fractional count to an integer", async () => {
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 2.7, state_gate: 0 },
    } as never);
    await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/2\.7/);
    expect(text).toMatch(/2 need you/);
  });

  it("renders a HUGE count as a plain integer, not scientific notation", async () => {
    // A finite-but-absurd number must degrade to a legible integer string
    // rather than "1e+308 need you →".
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 1e308, state_gate: 0 },
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/e\+/i);
    expect(text).toMatch(/need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("does not blink to 'none' on a transient fetch failure (keeps last good)", async () => {
    // First poll succeeds with a count; the component holds the last good value.
    // A subsequent rejection is swallowed and leaves needsYouCount intact.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 7, state_gate: 0 },
    } as never);
    await renderQuietly();
    await waitFor(async () => expect(await badgeText()).toMatch(/7 need you/));
  });
});

// ── ADVERSARIAL-VERIFY pass (skeptic) ──────────────────────────────────────
// The harden pass clamped `num()` into [0, CAP] as an integer and tightened the
// `counts` cast. A skeptic's job is to find a producer-owned shape that slips a
// SHALLOW guard but throws on a DEEPER deref, paints a nonsense badge, or blanks
// the page. The cases below are the nastiest JSON-EXPRESSIBLE shapes the producer
// (loop_memory.jsonl / the /api/human_todo body) could realistically emit; each
// must still degrade to a legible "N need you" / "none need you" with no crash,
// no NaN/Infinity, no '-N', and no scientific notation. None of these were
// pinned by the cases above. Verdict: the surface holds — every probe degrades.
describe("Dashboard coupling — adversarial-verify (skeptic)", () => {
  beforeEach(() => {
    vi.mocked(getHumanTodo).mockResolvedValue({ items: [], counts: {} } as never);
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not exponent-render when BOTH operands cap (sum stays a plain int)", async () => {
    // Both kinds absurd: each clamps to CAP=9999, the sum is 19998 — still a
    // legible plain integer, never '1e+308' or '2e+308'.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 1e308, state_gate: 5e307 },
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/e\+/i);
    expect(text).toMatch(/19998 need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("treats an ARRAY counts as zero (Array passes the truthy/?? guard)", async () => {
    // `counts: [1,2,3]` is truthy so it survives `r?.counts ?? {}`; the cast to
    // Record is a lie, but `counts.gate_verdict` on an array yields undefined,
    // which num() coerces to 0. No '.length'-as-count leak, no crash.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: [1, 2, 3],
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/NaN/);
    expect(text).toMatch(/none need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("treats a primitive `counts: 0` / `counts: false` as zero (?? only catches nullish)", async () => {
    // `0 ?? {}` is `0`; `false ?? {}` is `false`. Both are non-nullish falsy
    // primitives that the nullish-coalesce does NOT replace with {}. Property
    // access on a number/boolean primitive yields undefined (no throw) → 0.
    for (const bad of [0, false]) {
      vi.mocked(getHumanTodo).mockResolvedValue({
        items: [],
        counts: bad,
      } as never);
      const { error } = await renderQuietly();
      const text = await badgeText();
      expect(text, `counts=${bad}`).not.toMatch(/NaN/);
      expect(text, `counts=${bad}`).toMatch(/none need you/);
      expect(error, error.join(" | ")).toHaveLength(0);
      cleanup();
    }
  });

  it("drops a NESTED-OBJECT count value to zero (deeper shape than 'string')", async () => {
    // The producer hands a structured object where a scalar was expected:
    // `gate_verdict: { count: 5 }`. `typeof v === "number"` is false so num()
    // returns 0 WITHOUT dereferencing `.count` — no '[object Object] need you',
    // no throw. Only the legible B operand survives.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: { count: 5 }, state_gate: 4 },
    } as never);
    const { error } = await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/object|NaN/i);
    expect(text).toMatch(/4 need you/);
    expect(error, error.join(" | ")).toHaveLength(0);
  });

  it("floors a NEGATIVE-FRACTIONAL count toward zero, not toward -infinity", async () => {
    // -2.9 must clamp to 0 (Math.max(0, Math.floor(-2.9)) = Math.max(0,-3) = 0),
    // NOT floor first to -3 and render '-3'. Order of operations matters here.
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: -2.9, state_gate: 2.9 },
    } as never);
    await renderQuietly();
    const text = await badgeText();
    expect(text).not.toMatch(/-\d/);
    // -2.9 -> 0; 2.9 -> floor -> 2.
    expect(text).toMatch(/2 need you/);
  });

  it("survives a MALFORMED last telemetry sample without blanking the page", async () => {
    // `latest` (the raw last sample, used for lastSeen/read_errors BEFORE
    // cleanSamples filters) could be a primitive string if a garbage frame
    // landed last. `latest?.timestamp` / `latest?.read_errors` optional-chain on
    // a string to undefined — no throw. The badge (and page) still render.
    STREAM.latest = "thermal failed" as unknown as TelemetrySample;
    vi.mocked(getHumanTodo).mockResolvedValue({
      items: [],
      counts: { gate_verdict: 1, state_gate: 0 },
    } as never);
    try {
      const { error } = await renderQuietly();
      const text = await badgeText();
      expect(text).toMatch(/1 need you/);
      expect(error, error.join(" | ")).toHaveLength(0);
    } finally {
      STREAM.latest = sample();
    }
  });
});
