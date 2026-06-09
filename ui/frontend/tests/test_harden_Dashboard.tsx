// Consolidated edge-case + property-fuzz hardening for Dashboard (merged from per-round files).
//
// ── round r1 — edge-case category: missing/null/undefined optional fields +
// entirely-absent nested objects on producer-owned data. The iterations list is
// written by an external JSONL producer (loop_memory.jsonl, surfaced live by the
// backend) and may be partial/legacy/malformed; the Dashboard must NEVER crash
// the whole page on one bad payload.
//
// Dashboard lifts the iterations array up (to feed RedFlagsTrendStrip) via
// getIterations().then((r) => setIterations(r.iterations)). The adversarial
// payload here is a MALFORMED top-level response where the `iterations` field is
// absent / null — exactly the "missing optional field" the producer could emit
// (e.g. an older backend, an empty file mid-rotation, a 200 with `null` body).
// Without a guard, `setIterations(undefined)` flows into RedFlagsTrendStrip's
// `iterations.length`, throwing "Cannot read properties of undefined" and blanking
// the page. We render Dashboard with that payload and assert: it does not throw,
// the autonomy block still mounts, and no React console.error/warn fires (the
// jsdom stand-in for "renders without browser console errors").
//
// We also feed a partial iteration row (no novelty/critique/retrieval/meta_review/
// redteam — a pre-2026-06-09 legacy row) to confirm the row-level reads stay
// guarded end-to-end through the Dashboard render path.
//
// ── round r2 — edge-case category: malformed value TYPES on producer-owned
// data (a string where an object/number is expected and vice-versa, an array
// where an object is expected, null inside an array, NaN/Infinity, a garbage
// ISO timestamp). Dashboard renders two raw producer streams it does NOT
// validate at the type level:
//   - the telemetry buffer (useTelemetryStream forwards `msg.line as
//     TelemetrySample` straight off the WS — no shape check), and
//   - `health` / `latest.timestamp` used for the staleness age math.
// A single malformed row must never throw, blank the whole page, print "NaN",
// or paint a false health verdict. jsdom stand-in for "renders without browser
// console errors": spy on console.error/console.warn and assert silence.
//
// Two real bugs r2 guards (both reproduced before the fix):
//   A. `read_errors` is a non-object truthy value (a string "thermal failed",
//      or an array). The old `latest.read_errors ? Object.keys(...)` mined it
//      for index keys ("0","1",…) → a FALSE degraded with numeric "read
//      errors: 0, 1, …" reasons. Fix: only a plain object is a real error map.
//   B. a `null` element inside the `samples` array. The old
//      `recent.some((s) => s.vllm != null)` dereferenced null and threw
//      "Cannot read properties of null (reading 'vllm')" → white screen. Fix:
//      optional-chain the access.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  IterationRecord,
  TelemetrySample,
} from "../src/types/schemas";

// ─────────────────────────────────────────────────────────────────────────────
// Shared fixtures
// ─────────────────────────────────────────────────────────────────────────────

// (r1) A pre-2026-06-09 legacy iteration row: seed only, every other nested block
// (novelty / critique / retrieval / meta_review / redteam / hypothesis) absent.
// This is the entirely-absent-nested-objects sub-case, fed end-to-end.
const PARTIAL_ROW = {
  iteration_id: "iter-legacy-001",
  started_at: "2026-05-20T10:00:00.000000Z",
  ended_at: "2026-05-20T10:01:00.000000Z",
  seed: { topic: "legacy hello-world", source: "human_cli" },
  journal_entry_path: "journal/iterations/001.md",
} as IterationRecord;

// (r2) A well-formed telemetry sample with a Gemma vllm block, parameterized on
// the (deliberately mistyped) read_errors / timestamp so each case mutates one
// field while the rest stays valid. Cast through unknown: the whole point is
// that the live producer can hand back values the TS type forbids.
function sample(
  overrides: Partial<{ read_errors: unknown; timestamp: unknown }> = {},
): TelemetrySample {
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
    ...overrides,
  } as unknown as TelemetrySample;
}

// (r2) Per-test the hook hands back this stream. Reassigned in each `it` before
// the (synchronous) Dashboard render reads it. The default is a fresh, valid,
// gemma-up, connected stream — which is also exactly what the r1 tests need
// (they never mutate STREAM; they only drive the iterations payload).
let STREAM: {
  samples: TelemetrySample[];
  latest: TelemetrySample | null;
  connected: boolean;
} = { samples: [sample(), sample()], latest: sample(), connected: true };

// Single hook mock for both rounds: hand back the shared STREAM. r1 leaves it at
// the valid default (so gemmaUp is true); r2 reassigns it per-test.
vi.mock("../src/hooks/useTelemetryStream", () => ({
  useTelemetryStream: () => STREAM,
}));

// Single HTTP mock for both rounds. getIterations is a bare vi.fn() with the
// quiet `{ iterations: [] }` default (r2's happy path); r1 reassigns it per-test
// via vi.mocked(getIterations).mockResolvedValue(...). The remaining endpoints
// hand back the superset of the two rounds' quiet/empty happy-path payloads so
// only the field under test in each case varies.
vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: new Date().toISOString(),
    version: "test",
  }),
  getState: vi.fn().mockResolvedValue({ current_day: "2026-06-09" }),
  getIterations: vi.fn().mockResolvedValue({ iterations: [] }),
  getJournalEntry: vi.fn().mockResolvedValue({
    iteration_id: "iter-legacy-001",
    path: "journal/iterations/001.md",
    content: "# Journal\n\nbody",
  }),
  getActiveIteration: vi.fn().mockResolvedValue(null),
  getBaseline: vi.fn().mockResolvedValue({ rows: [] }),
  getWorkloadHint: vi.fn().mockResolvedValue({ regime: "idle" }),
  getSurfacedFindings: vi.fn().mockResolvedValue({ findings: [] }),
  getBubbles: vi.fn().mockResolvedValue({ bubbles: [] }),
  getHealthSignals: vi.fn().mockResolvedValue({ health_signals: [] }),
}));

import Dashboard from "../src/routes/Dashboard";
import { getIterations } from "../src/api/http";

// Render Dashboard, flush the async polls inside act(), and return any
// console.error / console.warn the render path emitted. A thrown render inside
// React surfaces as a console.error here too, so a crash is caught either way.
// (identical body in both source rounds; kept once.)
async function renderQuietly() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  render(<Dashboard />);
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

describe("Dashboard hardening — r1: malformed/partial iterations payload", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not crash when the iterations response omits the `iterations` field", async () => {
    // Producer emits a 200 with no `iterations` key (older backend / mid-rotation).
    vi.mocked(getIterations).mockResolvedValue({} as never);
    const { error, warn } = await renderQuietly();
    // The autonomy block + its red-flags strip must still mount, not blank out.
    await waitFor(() =>
      expect(screen.getByTestId("autonomy-block")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not crash when the response carries iterations: null", async () => {
    vi.mocked(getIterations).mockResolvedValue({ iterations: null } as never);
    const { error, warn } = await renderQuietly();
    await waitFor(() =>
      expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument(),
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not crash when the whole response body is null", async () => {
    vi.mocked(getIterations).mockResolvedValue(null as never);
    const { error, warn } = await renderQuietly();
    await waitFor(() =>
      expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument(),
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders a legacy row missing all nested blocks without console noise", async () => {
    vi.mocked(getIterations).mockResolvedValue({
      iterations: [PARTIAL_ROW],
    } as never);
    const { error, warn } = await renderQuietly();
    await waitFor(() =>
      expect(screen.getByTestId("red-flags-trend-strip")).toBeInTheDocument(),
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});

describe("Dashboard hardening — r2: malformed value TYPES on telemetry", () => {
  // The shared getIterations mock is module-scoped and r1 reassigns its
  // implementation per-test; vi.clearAllMocks() does not restore implementations.
  // Re-establish the quiet `{ iterations: [] }` default (and the valid STREAM)
  // before each r2 case so this block is order-independent of r1.
  beforeEach(() => {
    vi.mocked(getIterations).mockResolvedValue({ iterations: [] });
    STREAM = { samples: [sample(), sample()], latest: sample(), connected: true };
  });

  afterEach(() => {
    STREAM = { samples: [sample(), sample()], latest: sample(), connected: true };
    vi.clearAllMocks();
  });

  it("does not crash on a null element inside the samples array", async () => {
    // Bug B: a malformed WS frame lands a `null` in the rolling buffer; it
    // falls inside the last-N gemmaUp window. Pre-fix: throws on `s.vllm`.
    STREAM = {
      samples: [sample(), null as unknown as TelemetrySample],
      latest: sample(),
      connected: true,
    };
    const { error, warn } = await renderQuietly();
    expect(screen.getByTestId("health-verdict")).toBeInTheDocument();
    expect(screen.getByTestId("autonomy-block")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not mine a STRING read_errors for index keys (no false degraded)", async () => {
    // Bug A: read_errors is a string. Object.keys would yield "0","1",… and
    // paint a false degraded with numeric reasons. A malformed shape carries
    // no legible read errors -> the otherwise-fresh, gemma-up stream is HEALTHY.
    STREAM = {
      samples: [
        sample({ read_errors: "thermal sensor read failed" }),
        sample({ read_errors: "thermal sensor read failed" }),
      ],
      latest: sample({ read_errors: "thermal sensor read failed" }),
      connected: true,
    };
    const { error, warn } = await renderQuietly();
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict.getAttribute("data-level")).toBe("healthy");
    // No "read errors: 0, 1, 2 …" garbage anywhere in the hero.
    expect(verdict.textContent ?? "").not.toMatch(/read errors: \d/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not mine an ARRAY read_errors for numeric keys", async () => {
    // read_errors as an array (another non-object shape). Same defense: not a
    // real error map -> HEALTHY, no numeric reasons, no crash.
    const arr = ["thermal", "psutil"] as unknown;
    STREAM = {
      samples: [sample({ read_errors: arr }), sample({ read_errors: arr })],
      latest: sample({ read_errors: arr }),
      connected: true,
    };
    const { error, warn } = await renderQuietly();
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict.getAttribute("data-level")).toBe("healthy");
    expect(verdict.textContent ?? "").not.toMatch(/read errors: \d/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("still flags a genuine object read_errors map (guard did not over-suppress)", async () => {
    // Counter-case so the type guard can't pass by suppressing ALL read errors:
    // a real {key: msg} object must still drive a degraded verdict.
    const realErr = { thermal: "sensor timeout" } as unknown;
    STREAM = {
      samples: [sample({ read_errors: realErr }), sample({ read_errors: realErr })],
      latest: sample({ read_errors: realErr }),
      connected: true,
    };
    await renderQuietly();
    const verdict = screen.getByTestId("health-verdict");
    expect(verdict.getAttribute("data-level")).toBe("degraded");
    expect(verdict.textContent ?? "").toMatch(/thermal/);
  });

  it("does not print NaN or crash on a garbage / wrong-typed timestamp", async () => {
    // latest.timestamp is the staleness-age input. Garbage string, a number,
    // null — Date.parse -> NaN, already guarded to null (unknown freshness).
    // Assert no "NaN" leaks into the hero and nothing throws across the cases.
    for (const ts of ["not-a-real-iso", 1234567890 as unknown, NaN as unknown]) {
      STREAM = {
        samples: [sample({ timestamp: ts }), sample({ timestamp: ts })],
        latest: sample({ timestamp: ts }),
        connected: true,
      };
      const { error, warn } = await renderQuietly();
      const verdict = screen.getByTestId("health-verdict");
      expect(verdict.textContent ?? "").not.toMatch(/NaN/);
      // Fresh-or-unknown + gemma up + connected -> not down, not falsely stale.
      expect(verdict.getAttribute("data-level")).not.toBe("down");
      expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
      expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
      // Unmount this iteration's tree before the next render so getByTestId
      // sees one hero, not an accumulating stack of them.
      cleanup();
      vi.clearAllMocks();
    }
  });
});
