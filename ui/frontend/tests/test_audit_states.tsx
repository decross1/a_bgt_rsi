// CROSS-CUTTING STATE-COVERAGE AUDIT — every autonomy polling component must
// handle its THREE async states DISTINCTLY: loading (request in flight, not yet
// resolved), error (the fetch rejected → a legible error string, NOT a crash and
// NOT a false "empty"), and empty (resolved with no rows → the clean empty
// surface). This is design principle #2 ("make absence legible"): idle ≠ failed ≠
// loading ≠ empty — a blank gap must never stand in for any of them.
//
// Why this file exists alongside the per-component tests: test_validate_panels_empty
// covers the EMPTY surface (initial=[] + the absent-data poll) with a console spy,
// and the test_harden_* / test_robust_* families cover malformed-row TYPES. But no
// test drives the four self-polling autonomy components through a fetch REJECT and
// asserts the error surface renders (not a crash, not a silent empty), nor pins the
// LOADING state as distinct from empty. A fetch can reject for real — the live
// backend on :8700 was stale and 404'd /api/coordinator/* the morning this landed,
// which is exactly an error-path the human-as-auditor must see surfaced, not
// swallowed. This audit closes that triad gap across all four.
//
// The four self-polling components (each owns a useEffect that calls its getX,
// flips `loaded` on resolve, and sets an error string on reject):
//   SurfacedFindingsPanel  → getSurfacedFindings  (findings-empty testid)
//   BubblesPanel           → getBubbles           (bubbles-empty testid)
//   HealthSignalsPanel     → getHealthSignals     (health-signals-empty testid)
//   ResolvedIterationsList → getIterations        (text empty — no testid)
// (CoordinatorPhases is pure/prop-driven — its parent Activity/Coordinator route
//  polls and hands it activeRun — so it is not a self-poller; its idle surface is
//  covered by test_coordinator_phases. This audit targets the self-pollers, which
//  are the components that own the loading/error/empty triad.)
//
// No headless browser exists (Playwright/chromium absent), so "renders without
// console errors" is jsdom + a console.error/warn spy (the test_validate_panels
// _empty / test_source_badge idiom): a render-time throw and an unwrapped act()
// state update both land on console.error, so "not called" is the stand-in for a
// clean render. Each component's getX is mocked per-state via a module-mutable
// response the hoisted vi.mock factory reads (the test_harden_Coordinator_r2 idiom).
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import BubblesPanel from "../src/components/BubblesPanel";
import HealthSignalsPanel from "../src/components/HealthSignalsPanel";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";

// Each getX returns IMPL() — a module-mutable function the test swaps per state.
// Default is a never-settling promise (the LOADING state) so a test that forgets
// to stage an outcome stays in loading rather than leaking a prior resolution.
const PENDING = () => new Promise<never>(() => {});
let findingsImpl: () => Promise<unknown> = PENDING;
let bubblesImpl: () => Promise<unknown> = PENDING;
let signalsImpl: () => Promise<unknown> = PENDING;
let iterationsImpl: () => Promise<unknown> = PENDING;

vi.mock("../src/api/http", () => ({
  getSurfacedFindings: vi.fn(() => findingsImpl()),
  getBubbles: vi.fn(() => bubblesImpl()),
  getHealthSignals: vi.fn(() => signalsImpl()),
  getIterations: vi.fn(() => iterationsImpl()),
}));

// Spy console.error/warn for one render and return only the REAL calls (React's
// "not wrapped in act" advisory is a test-harness artifact, filtered out). A
// thrown render lands on console.error here too, so a crash is caught even when
// render() does not rethrow.
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const real = (spy: ReturnType<typeof vi.spyOn>) =>
    spy.mock.calls
      .map((c: unknown[]) => String(c[0]))
      .filter((m: string) => !m.includes("not wrapped in act"));
  return {
    error: () => real(errSpy),
    warn: () => real(warnSpy),
    restore: () => {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    },
  };
}

afterEach(() => {
  cleanup();
  findingsImpl = PENDING;
  bubblesImpl = PENDING;
  signalsImpl = PENDING;
  iterationsImpl = PENDING;
  vi.clearAllMocks();
});

// A long poll interval so the test observes exactly the first load's settled
// state (no second poll racing the assertion).
const POLL = 1_000_000;

// ── SurfacedFindingsPanel ────────────────────────────────────────────────────
describe("state-coverage audit — SurfacedFindingsPanel (getSurfacedFindings)", () => {
  it("LOADING: request in flight shows neither the empty state nor an error", async () => {
    findingsImpl = PENDING; // never resolves
    const spy = spyConsole();
    render(<SurfacedFindingsPanel pollMs={POLL} />);
    // Let any synchronous effect run; the panel mounts but the load is pending.
    await Promise.resolve();

    const panel = within(screen.getByTestId("surfaced-findings-panel"));
    // Loading ≠ empty: the empty surface must NOT show before the first resolve.
    expect(panel.queryByTestId("findings-empty")).toBeNull();
    // Loading ≠ error: no red error string while still in flight.
    expect(panel.queryByText(/Error|TypeError/)).toBeNull();
    // And no data rows leaked.
    expect(panel.queryByTestId(/^finding-/)).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    expect(spy.warn(), spy.warn().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("ERROR: a rejected fetch surfaces the error string, not a crash or a false empty", async () => {
    findingsImpl = () => Promise.reject(new Error("503 backend unavailable"));
    const spy = spyConsole();
    render(<SurfacedFindingsPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(
        within(screen.getByTestId("surfaced-findings-panel")).getByText(
          /503 backend unavailable/,
        ),
      ).toBeInTheDocument(),
    );
    const panel = within(screen.getByTestId("surfaced-findings-panel"));
    // Error ≠ empty: a fetch failure must NOT masquerade as "nothing here".
    expect(panel.queryByTestId("findings-empty")).toBeNull();
    // The panel itself still rendered (no crash blanked it).
    expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    expect(spy.warn(), spy.warn().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("EMPTY: resolved with no rows shows the clean empty state", async () => {
    findingsImpl = () => Promise.resolve({ findings: [] });
    const spy = spyConsole();
    render(<SurfacedFindingsPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(screen.getByTestId("findings-empty")).toBeInTheDocument(),
    );
    const panel = within(screen.getByTestId("surfaced-findings-panel"));
    // Empty ≠ error: the empty response is success, no red banner.
    expect(panel.queryByText(/Error|TypeError/)).toBeNull();
    expect(panel.queryByTestId(/^finding-/)).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    expect(spy.warn(), spy.warn().join(" | ")).toHaveLength(0);
    spy.restore();
  });
});

// ── BubblesPanel ─────────────────────────────────────────────────────────────
describe("state-coverage audit — BubblesPanel (getBubbles)", () => {
  it("LOADING: request in flight shows neither the empty state nor an error", async () => {
    bubblesImpl = PENDING;
    const spy = spyConsole();
    render(<BubblesPanel pollMs={POLL} />);
    await Promise.resolve();

    const panel = within(screen.getByTestId("bubbles-panel"));
    expect(panel.queryByTestId("bubbles-empty")).toBeNull();
    expect(panel.queryByText(/Error|TypeError/)).toBeNull();
    expect(panel.queryByTestId(/^bubble-/)).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("ERROR: a rejected fetch surfaces the error string, not a crash or a false empty", async () => {
    bubblesImpl = () => Promise.reject(new Error("404 Not Found"));
    const spy = spyConsole();
    render(<BubblesPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(
        within(screen.getByTestId("bubbles-panel")).getByText(/404 Not Found/),
      ).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("bubbles-panel")).queryByTestId("bubbles-empty"),
    ).toBeNull();
    expect(screen.getByTestId("bubbles-panel")).toBeInTheDocument();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("EMPTY: resolved with no rows shows the clean empty state", async () => {
    bubblesImpl = () => Promise.resolve({ bubbles: [] });
    const spy = spyConsole();
    render(<BubblesPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("bubbles-panel")).queryByText(/Error|TypeError/),
    ).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });
});

// ── HealthSignalsPanel ───────────────────────────────────────────────────────
describe("state-coverage audit — HealthSignalsPanel (getHealthSignals)", () => {
  it("LOADING: request in flight shows neither the empty state nor an error", async () => {
    signalsImpl = PENDING;
    const spy = spyConsole();
    render(<HealthSignalsPanel pollMs={POLL} />);
    await Promise.resolve();

    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(panel.queryByTestId("health-signals-empty")).toBeNull();
    expect(panel.queryByText(/Error|TypeError/)).toBeNull();
    expect(panel.queryByTestId(/^health-signal-/)).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("ERROR: a rejected fetch surfaces the error string, not a crash or a false empty", async () => {
    signalsImpl = () => Promise.reject(new Error("500 Internal Server Error"));
    const spy = spyConsole();
    render(<HealthSignalsPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(
        within(screen.getByTestId("health-signals-panel")).getByText(
          /500 Internal Server Error/,
        ),
      ).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("health-signals-panel")).queryByTestId(
        "health-signals-empty",
      ),
    ).toBeNull();
    expect(screen.getByTestId("health-signals-panel")).toBeInTheDocument();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("EMPTY: resolved with no rows shows the clean empty state", async () => {
    signalsImpl = () => Promise.resolve({ health_signals: [] });
    const spy = spyConsole();
    render(<HealthSignalsPanel pollMs={POLL} />);

    await waitFor(() =>
      expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("health-signals-panel")).queryByText(
        /Error|TypeError/,
      ),
    ).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });
});

// ── ResolvedIterationsList ───────────────────────────────────────────────────
// Its empty surface is a plain text node (no *-empty testid), so assert on the
// copy. Its error surface is the shared red div; loading shows neither.
describe("state-coverage audit — ResolvedIterationsList (getIterations)", () => {
  const EMPTY_COPY = /No iterations yet/;

  it("LOADING: request in flight shows neither the empty copy nor an error", async () => {
    iterationsImpl = PENDING;
    const spy = spyConsole();
    render(<ResolvedIterationsList pollMs={POLL} />);
    await Promise.resolve();

    const panel = within(screen.getByTestId("resolved-iterations-list"));
    expect(panel.queryByText(EMPTY_COPY)).toBeNull();
    expect(panel.queryByText(/Error|TypeError/)).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("ERROR: a rejected fetch surfaces the error string, not a crash or a false empty", async () => {
    iterationsImpl = () =>
      Promise.reject(new Error("ECONNREFUSED 127.0.0.1:8700"));
    const spy = spyConsole();
    render(<ResolvedIterationsList pollMs={POLL} />);

    await waitFor(() =>
      expect(
        within(screen.getByTestId("resolved-iterations-list")).getByText(
          /ECONNREFUSED/,
        ),
      ).toBeInTheDocument(),
    );
    const panel = within(screen.getByTestId("resolved-iterations-list"));
    // Error ≠ empty: a connection refusal must not read as "no iterations yet".
    expect(panel.queryByText(EMPTY_COPY)).toBeNull();
    expect(screen.getByTestId("resolved-iterations-list")).toBeInTheDocument();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });

  it("EMPTY: resolved with no rows shows the empty copy, not an error", async () => {
    iterationsImpl = () => Promise.resolve({ iterations: [] });
    const spy = spyConsole();
    render(<ResolvedIterationsList pollMs={POLL} />);

    await waitFor(() =>
      expect(
        within(screen.getByTestId("resolved-iterations-list")).getByText(
          EMPTY_COPY,
        ),
      ).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("resolved-iterations-list")).queryByText(
        /Error|TypeError/,
      ),
    ).toBeNull();
    expect(spy.error(), spy.error().join(" | ")).toHaveLength(0);
    spy.restore();
  });
});
