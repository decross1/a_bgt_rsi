// Hardening for HealthStrip — the 6-tile GPU/host strip + its new host-mem tile.
//
// HOUSE ROBUSTNESS DOCTRINE: HealthStrip's `samples` come from
// /api/telemetry/recent (TelemetrySample[]), producer-owned JSON forwarded raw —
// the declared type cannot enforce shape at runtime. A null/non-array body, a
// null/non-object trailing sample, a string/NaN/Infinity where a number is
// expected, or an empty samples array must each DEGRADE to a legible "n/a"/idle
// tile (and the host tile's honest "—"), NEVER blank the strip or throw.
//
// Pre-mitigation, two crashes/leaks existed:
//   1. a non-array (or null/undefined) `samples` prop threw on `samples.map`
//      (series) / `samples[samples.length - 1]` — a TypeError white-screens the
//      whole dashboard route.
//   2. a non-finite or non-number `mem_used_mb`/`mem_total_mb` (a malformed/
//      legacy sample) passed the bare `!= null` gate and `(x/1024).toFixed(1)`
//      rendered a literal "NaN/NaN" GiB value in the GPU-memory tile.
//
// Each fix is pinned below. Valid-input behavior is unchanged (last test).
//
// jsdom stand-in for "renders without console errors": spy on console.error/
// console.warn and assert not called.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HealthStrip from "../src/components/HealthStrip";
import type { TelemetrySample } from "../src/types/schemas";

function watchConsole() {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { error, warn };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const TILE_LABELS = [
  "GPU util",
  "GPU memory",
  "GPU temp",
  "GPU power",
  "CPU temp",
  "Host RAM",
];

// A well-formed sample, used to prove the guards never touch the happy path.
function goodSample(): TelemetrySample {
  return {
    timestamp: "2026-06-14T10:00:00.000+00:00",
    gpu: {
      util_pct: 12,
      mem_used_mb: 8192,
      mem_total_mb: 16384,
      temp_c: 65,
      power_w: 80,
    },
    host: { cpu_pct: 10, mem_used_mb: 5120, cpu_temp_c: 44, load_avg: [1, 1, 1] },
    vllm: null,
    processes: [],
    read_errors: null,
  };
}

function expectAllTilesPresent() {
  for (const label of TILE_LABELS) {
    expect(screen.getByText(label)).toBeInTheDocument();
  }
}

describe("HealthStrip hardening — non-array / null / undefined samples prop", () => {
  // Every shape a malformed telemetry body could substitute for the array.
  const NON_ARRAYS: [string, unknown][] = [
    ["null", null],
    ["undefined", undefined],
    ["bare object", {}],
    ["number", 42],
    ["string", "oops"],
    ["array-like with length", { length: 3 }],
  ];

  it.each(NON_ARRAYS)(
    "does not throw and shows every tile when samples is %s",
    (_label, bad) => {
      const spy = watchConsole();
      // The runtime value violates the declared type — exactly the hazard.
      expect(() =>
        render(<HealthStrip samples={bad as unknown as TelemetrySample[]} />),
      ).not.toThrow();
      // No white-screen: all six tiles mount; the absent data reads as honest
      // "n/a" / "—", never a NaN and never a crash.
      expectAllTilesPresent();
      expect(document.body.innerHTML).not.toContain("NaN");
      expect(screen.getByText("GB10 unified memory — n/a")).toBeInTheDocument();
      expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
      expect(spy.error).not.toHaveBeenCalled();
      expect(spy.warn).not.toHaveBeenCalled();
    },
  );
});

describe("HealthStrip hardening — empty vs malformed samples", () => {
  it("an empty samples array renders the clean empty strip (no crash, honest n/a)", () => {
    const spy = watchConsole();
    render(<HealthStrip samples={[]} />);
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("a null/non-object trailing sample degrades, not crashes", () => {
    const spy = watchConsole();
    // A literal null JSONL line as the most-recent sample (the one the strip
    // reads for current values). Optional chaining alone is not enough — the
    // index read + the per-sample series map must both tolerate it.
    const rows = [
      goodSample(),
      null as unknown as TelemetrySample,
      "junk" as unknown as TelemetrySample,
    ];
    expect(() => render(<HealthStrip samples={rows} />)).not.toThrow();
    expectAllTilesPresent();
    // The trailing junk has no gpu/host → current values read n/a/idle, but the
    // strip still mounts and never leaks a NaN.
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

describe("HealthStrip hardening — non-finite / wrong-type mem fields", () => {
  // mem_used_mb / mem_total_mb arriving as the values a malformed or legacy
  // producer write could emit. None must reach (x/1024).toFixed() as a divide.
  const BAD_MEM: [string, unknown, unknown][] = [
    ["NaN used", Number.NaN, 16384],
    ["Infinity used", Number.POSITIVE_INFINITY, 16384],
    ["NaN total", 8192, Number.NaN],
    ["string used", "8192", 16384],
    ["string total", 8192, "16384"],
    ["object used", {}, 16384],
    ["array total", 8192, [1, 2, 3]],
  ];

  it.each(BAD_MEM)(
    "GPU-memory tile shows n/a (never NaN) when mem is %s",
    (_label, used, total) => {
      const spy = watchConsole();
      const s = goodSample();
      // Force the malformed runtime values past the declared number|null type.
      (s.gpu as unknown as Record<string, unknown>).mem_used_mb = used;
      (s.gpu as unknown as Record<string, unknown>).mem_total_mb = total;
      render(<HealthStrip samples={[s]} />);
      expectAllTilesPresent();
      // The GPU-memory tile falls back to the honest unavailable state, and no
      // "NaN" string leaks anywhere in the strip.
      expect(screen.getByText("GB10 unified memory — n/a")).toBeInTheDocument();
      expect(document.body.innerHTML).not.toContain("NaN");
      expect(spy.error).not.toHaveBeenCalled();
      expect(spy.warn).not.toHaveBeenCalled();
    },
  );

  it("non-finite gpu/host temps & power do not crash or leak NaN", () => {
    const spy = watchConsole();
    const s = goodSample();
    (s.gpu as unknown as Record<string, unknown>).temp_c = Number.NaN;
    (s.gpu as unknown as Record<string, unknown>).power_w = Number.POSITIVE_INFINITY;
    (s.gpu as unknown as Record<string, unknown>).util_pct = Number.NEGATIVE_INFINITY;
    (s.host as unknown as Record<string, unknown>).cpu_temp_c = Number.NaN;
    (s.host as unknown as Record<string, unknown>).mem_used_mb = Number.NaN;
    render(<HealthStrip samples={[s]} />);
    expectAllTilesPresent();
    // fmt() guards non-finite → "n/a"; Sparkline filters non-finite → no NaN.
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

describe("HealthStrip hardening — missing optional keys / absent nested objects", () => {
  it("a sample with absent gpu/host objects renders every tile as n/a", () => {
    const spy = watchConsole();
    // A pre-schema / partial sample carrying only timestamp — gpu & host absent.
    const partial = {
      timestamp: "2026-06-14T10:00:00.000+00:00",
    } as unknown as TelemetrySample;
    expect(() => render(<HealthStrip samples={[partial]} />)).not.toThrow();
    expectAllTilesPresent();
    expect(screen.getByText("GB10 unified memory — n/a")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("gpu/host present as wrong-type scalars are absorbed (no throw)", () => {
    const spy = watchConsole();
    const malformed = {
      timestamp: "2026-06-14T10:00:00.000+00:00",
      gpu: "broken",
      host: 7,
    } as unknown as TelemetrySample;
    expect(() => render(<HealthStrip samples={[malformed]} />)).not.toThrow();
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

describe("HealthStrip adversarial-verify — deeper malformed shapes hold the line", () => {
  // ADVERSARIAL-VERIFY (skeptic pass): the harden guards above use SHALLOW
  // checks (Array.isArray, typeof === "object", Number.isFinite). These cases
  // probe whether a value that SLIPS PAST a shallow guard then throws on a
  // DEEPER deref — or leaks a NaN — anywhere in the strip or its delegated
  // tiles (MetricTile/Sparkline/HostMemoryTile). They all DEGRADE legibly; the
  // single-level optional chains off gpu/host plus fmt()/Sparkline's finite
  // filter form a complete net for JSON-shaped input. No fix was warranted
  // (broke_it=false) — these pin that the net stays complete.

  it("gpu/host present as arrays (typeof object, pass the latest guard) degrade", () => {
    const spy = watchConsole();
    const s = goodSample();
    // Arrays are objects: latest passes `typeof === object`, and gpu/host pass
    // too. `[1,2,3].mem_used_mb` is undefined → every read falls back, no throw.
    (s as unknown as Record<string, unknown>).gpu = [1, 2, 3];
    (s as unknown as Record<string, unknown>).host = [4, 5];
    expect(() => render(<HealthStrip samples={[s]} />)).not.toThrow();
    expectAllTilesPresent();
    expect(screen.getByText("GB10 unified memory — n/a")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("a sample that is itself an array (Array, typeof object) does not throw", () => {
    const spy = watchConsole();
    // An array slips past `typeof rawLatest === "object"` for the latest read and
    // past the per-sample series guard; its .gpu/.host are undefined → safe.
    const rows = [[1, 2, 3] as unknown as TelemetrySample];
    expect(() => render(<HealthStrip samples={rows} />)).not.toThrow();
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("an oversize series (5000 samples) renders without crash or console noise", () => {
    const spy = watchConsole();
    const big = Array.from({ length: 5000 }, () => goodSample());
    expect(() => render(<HealthStrip samples={big} />)).not.toThrow();
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("a unicode RTL-override / emoji string in a numeric field never leaks NaN", () => {
    const spy = watchConsole();
    const s = goodSample();
    // A garbled producer write: a bidi-override + emoji string where a number is
    // expected. fmt()'s typeof-number gate rejects it → "n/a", never NaN, no throw.
    (s.gpu as unknown as Record<string, unknown>).util_pct = "‮99🚀";
    (s.gpu as unknown as Record<string, unknown>).temp_c = true; // bool, not number
    (s.host as unknown as Record<string, unknown>).cpu_temp_c = " ";
    expect(() => render(<HealthStrip samples={[s]} />)).not.toThrow();
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("mem_total_mb=0 (a finite legit value) renders raw, never NaN, never throws", () => {
    const spy = watchConsole();
    const s = goodSample();
    // 0 is finite → the finite-guard intentionally lets it through and the tile
    // renders the raw ratio (e.g. "8.0/0.0"). That is the forward-raw doctrine:
    // honest render of a real value, not a crash and not a NaN. We pin that it
    // stays legible (no NaN, no throw) and do NOT special-case a legit 0.
    (s.gpu as unknown as Record<string, unknown>).mem_total_mb = 0;
    expect(() => render(<HealthStrip samples={[s]} />)).not.toThrow();
    expectAllTilesPresent();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("prop->poll race: a malformed prop on re-render never falls into HostMemoryTile's fetch path", () => {
    const spy = watchConsole();
    // HealthStrip always passes the normalized `list` (an array) to
    // HostMemoryTile's `initial`, so `initial !== undefined` always holds and the
    // tile NEVER polls /api/telemetry/recent from inside the strip — even across a
    // good -> null-prop -> junk-prop re-render sequence. No fetch is mocked here;
    // if the poll path were reachable, getRecentTelemetry would fire and (in
    // jsdom) surface as a console error. It must not.
    const { rerender } = render(<HealthStrip samples={[goodSample()]} />);
    expect(() =>
      rerender(<HealthStrip samples={null as unknown as TelemetrySample[]} />),
    ).not.toThrow();
    expect(() =>
      rerender(
        <HealthStrip
          samples={
            [
              goodSample(),
              null as unknown as TelemetrySample,
              "junk" as unknown as TelemetrySample,
            ] as TelemetrySample[]
          }
        />,
      ),
    ).not.toThrow();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

describe("HealthStrip — valid input is unchanged (no regression from the guards)", () => {
  it("renders real current values from the latest well-formed sample", () => {
    const spy = watchConsole();
    const a = goodSample();
    a.gpu!.temp_c = 41;
    const b = goodSample();
    b.gpu!.temp_c = 83;
    render(<HealthStrip samples={[a, b]} />);
    expectAllTilesPresent();
    // Latest sample's temp surfaces, and the real mem ratio (8/16 GiB) renders
    // — proving the finite-guard never blocks a valid divide.
    expect(screen.getByText("83.0")).toBeInTheDocument();
    expect(screen.getByText("8.0/16.0")).toBeInTheDocument();
    // The well-formed host sample feeds the Host RAM tile a real "used" value.
    expect(screen.getByText("used")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});
