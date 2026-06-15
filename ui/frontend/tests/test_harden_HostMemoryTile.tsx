// HARDENING for HostMemoryTile (host RAM-used tile) + its pure `hostMemSeries`
// helper, against the HOUSE ROBUSTNESS DOCTRINE.
//
// The tile's data is producer-owned telemetry the backend forwards RAW: the
// `initial` prop is a fixture/test pin and the polled /api/telemetry/recent body
// is an UNVALIDATED `{ samples }` envelope (ui/sampler emits whatever psutil
// read; a stale/version-skewed agent can emit null, a non-object, wrong field
// types, NaN/Infinity, a missing host, or an absent `samples` key). Every such
// value MUST degrade to the honest unavailable state ("—", note "host telemetry
// unavailable") — never blank the page, throw, or fabricate a number (inviolate
// rule 4: the tile NEVER invents a total/free/percent).
//
// VALID-input behavior is asserted unchanged: a well-formed series renders the
// latest reading in GiB with the "used" note (the guards only catch the junk).
//
// jsdom "renders without console errors" stand-in (no headless browser): render
// and spy on console.error/console.warn; assert not called.
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HostMemoryTile, {
  hostMemSeries,
} from "../src/components/HostMemoryTile";
import type { TelemetrySample } from "../src/types/schemas";

function watchConsole() {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { error, warn };
}

// A well-formed host sample carrying mem_used_mb (the only host field this tile
// reads). 8192 MiB == 8.0 GiB.
function goodSample(mem_used_mb: number): TelemetrySample {
  return {
    ts: "2026-06-14T00:00:00Z",
    host: {
      cpu_pct: 12,
      mem_used_mb,
      cpu_temp_c: 40,
      load_avg: [1, 1, 1],
    },
    vllm: null,
    processes: [],
    read_errors: null,
  } as unknown as TelemetrySample;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// === Pure helper: hostMemSeries =========================================
// The render path runs entirely through this function, so pin its degrades
// directly (fast, exhaustive) and then prove the component mirrors them.

describe("hostMemSeries — malformed / edge inputs degrade, never throw", () => {
  it("a well-formed series yields the latest GiB and per-sample values (valid path unchanged)", () => {
    const out = hostMemSeries([goodSample(4096), goodSample(8192)]);
    expect(out.values).toEqual([4, 8]);
    expect(out.latestGiB).toBe(8);
  });

  it.each<[string, unknown]>([
    ["null", null],
    ["undefined", undefined],
    ["a bare object", {}],
    ["a number", 42],
    ["a string", "oops"],
    ["an array-like with length", { length: 3 }],
  ])("a non-array `samples` (%s) degrades to empty series + null latest", (_label, bad) => {
    const out = hostMemSeries(bad as unknown as TelemetrySample[]);
    expect(out.values).toEqual([]);
    expect(out.latestGiB).toBeNull();
  });

  it.each<[string, unknown]>([
    ["null row", null],
    ["undefined row", undefined],
    ["scalar row", 7],
    ["string row", "x"],
    ["row with no host", {}],
    ["row with host=null", { host: null }],
    ["row with host as scalar", { host: 5 }],
    ["row with host missing mem_used_mb", { host: { cpu_pct: 1 } }],
    ["row with mem_used_mb as string", { host: { mem_used_mb: "1024" } }],
    ["row with mem_used_mb NaN", { host: { mem_used_mb: Number.NaN } }],
    ["row with mem_used_mb +Infinity", { host: { mem_used_mb: Number.POSITIVE_INFINITY } }],
    ["row with mem_used_mb -Infinity", { host: { mem_used_mb: Number.NEGATIVE_INFINITY } }],
    ["row with mem_used_mb null", { host: { mem_used_mb: null } }],
  ])("a malformed row (%s) maps to a null value, never a fabricated number", (_label, bad) => {
    const out = hostMemSeries([bad as unknown as TelemetrySample]);
    expect(out.values).toEqual([null]);
    expect(out.latestGiB).toBeNull();
  });

  it("walks past a trailing bad sample to the most recent usable reading", () => {
    // A trailing null host sample must NOT blank a tile with fresh data behind it.
    const out = hostMemSeries([
      goodSample(2048),
      { host: null } as unknown as TelemetrySample,
    ]);
    expect(out.values).toEqual([2, null]);
    expect(out.latestGiB).toBe(2); // the 2 GiB reading, not the trailing null
  });

  it("an empty array (absent collection) is the same clean unavailable state", () => {
    const out = hostMemSeries([]);
    expect(out.values).toEqual([]);
    expect(out.latestGiB).toBeNull();
  });
});

// === Component render: initial prop (no fetch) ==========================

describe("HostMemoryTile — render with a malformed `initial` prop", () => {
  it("a valid initial renders the latest GiB with the 'used' note (valid path unchanged)", () => {
    const spy = watchConsole();
    render(<HostMemoryTile initial={[goodSample(8192)]} />);
    expect(screen.getByText("Host RAM")).toBeInTheDocument();
    expect(screen.getByText("8.0")).toBeInTheDocument();
    expect(screen.getByText("GiB")).toBeInTheDocument();
    expect(screen.getByText("used")).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it.each<[string, unknown]>([
    ["empty array", []],
    ["all-null rows", [null, null]],
    ["all-undefined rows", [undefined, undefined]],
    ["rows with absent host", [{}, {}]],
    ["a non-array (number)", 42],
    ["a non-array (string)", "oops"],
    ["a non-array (object)", { length: 2 }],
    ["NaN/Infinity readings", [
      { host: { mem_used_mb: Number.NaN } },
      { host: { mem_used_mb: Number.POSITIVE_INFINITY } },
    ]],
  ])("a malformed initial (%s) degrades to the honest unavailable state", (_label, bad) => {
    const spy = watchConsole();
    expect(() =>
      render(<HostMemoryTile initial={bad as unknown as TelemetrySample[]} />),
    ).not.toThrow();
    // Tile still mounts (no white-screen), shows the em-dash, the unavailable
    // note, and NO unit (no fabricated GiB number).
    expect(screen.getByText("Host RAM")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(screen.queryByText("GiB")).toBeNull();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});

// === Component render: polled body via mocked getRecentTelemetry ========
// `initial` is undefined → the component polls. Mock the http layer so we can
// feed it a malformed / version-skewed body and a rejected (404) fetch, and
// assert the degrade reaches the DOM.

const getRecentTelemetry = vi.hoisted(() => vi.fn());
vi.mock("../src/api/http", () => ({ getRecentTelemetry }));

describe("HostMemoryTile — polled /api/telemetry/recent body hardening", () => {
  beforeEach(() => {
    getRecentTelemetry.mockReset();
    vi.useRealTimers();
  });

  async function flush() {
    // Let the load() promise chain settle so the setState it triggers lands
    // before we assert. Wrapped in act() so React flushes the update inside the
    // testing boundary (no "not wrapped in act(...)" console.error).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("a well-formed polled body renders the latest GiB (valid path unchanged)", async () => {
    const spy = watchConsole();
    getRecentTelemetry.mockResolvedValue({ samples: [goodSample(16384)] });
    render(<HostMemoryTile pollMs={100000} />);
    await flush();
    expect(screen.getByText("16.0")).toBeInTheDocument();
    expect(screen.getByText("used")).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it.each<[string, unknown]>([
    ["null body (version-skew 200)", null],
    ["non-object body (number)", 42],
    ["non-object body (string)", "oops"],
    ["body missing samples key", { other: 1 }],
    ["samples is null", { samples: null }],
    ["samples is a non-array", { samples: 42 }],
    ["samples has junk rows", { samples: [null, { host: { mem_used_mb: "x" } }] }],
  ])("a malformed polled body (%s) degrades to '—' without crash or console noise", async (_label, body) => {
    const spy = watchConsole();
    getRecentTelemetry.mockResolvedValue(body);
    expect(() => render(<HostMemoryTile pollMs={100000} />)).not.toThrow();
    await flush();
    expect(screen.getByText("Host RAM")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("a rejected fetch (version-skew 404 / unreachable) leaves the honest '—', no crash", async () => {
    const spy = watchConsole();
    getRecentTelemetry.mockRejectedValue(new Error("404 Not Found"));
    expect(() => render(<HostMemoryTile pollMs={100000} />)).not.toThrow();
    await flush();
    // No last-good series existed → the unavailable state stands (never a throw
    // escaping the .catch, never a fabricated number).
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  // ADVERSARIAL — ordering-contract / transition: a SECOND poll that returns a
  // malformed (version-skewed) body must DEGRADE the live good reading to "—",
  // not silently freeze the stale number behind a guard that only ever sees the
  // first body. The `r?.samples` guard sets [] (the honest absent series), which
  // is a deliberate degrade distinct from the .catch path (which keeps last-good
  // on a network error). Pins that contract so a future "keep last good on
  // malformed too" regression is caught.
  it("a malformed body on a later poll degrades the live good reading to '—'", async () => {
    const spy = watchConsole();
    // Use fake timers so we drive the interval ticks deterministically (no race
    // between assert and a fast real interval). Tick 1 → good body; tick 2 →
    // version-skew null envelope.
    vi.useFakeTimers();
    getRecentTelemetry
      .mockResolvedValueOnce({ samples: [goodSample(8192)] }) // first tick: good
      .mockResolvedValue(null); // every later tick: version-skew null envelope
    render(<HostMemoryTile pollMs={5000} />);
    // initial load() (good body) settles.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("8.0")).toBeInTheDocument();
    // Advance to the next interval tick whose body is the malformed null
    // envelope, then let its promise chain settle.
    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });
    vi.useRealTimers();
    // Degrades to the honest unavailable state — NOT a frozen stale "8.0", and
    // crucially NOT a TypeError dereferencing `samples` off the null body.
    expect(screen.queryByText("8.0")).toBeNull();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("NaN");
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  // ADVERSARIAL — prop↔poll race: a slow poll that RESOLVES AFTER unmount must
  // not setState on the dead component (the `active` flag gates the setSamples).
  // A regression that dropped the flag would surface as React's "state update on
  // an unmounted component" console.error — which the doctrine's no-console-noise
  // stance forbids.
  it("a poll that resolves after unmount does not setState or emit console noise", async () => {
    const spy = watchConsole();
    let resolve!: (v: unknown) => void;
    getRecentTelemetry.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const { unmount } = render(<HostMemoryTile pollMs={100000} />);
    unmount();
    // The in-flight fetch only now resolves, with a perfectly good body.
    resolve({ samples: [goodSample(4096)] });
    await flush();
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });
});
