// VALIDATION (real-data, panels-empty surface) — SurfacedFindingsPanel +
// BubblesPanel + HealthSignalsPanel against the LIVE autonomy data, which is
// genuinely ABSENT: memory/surfaced_findings.jsonl, memory/coordinator_bubbles
// .jsonl, and run_state/health_signals.jsonl do not exist in the primary repo
// yet. The backend (verified out-of-band via TestClient(create_app()), reading
// the hardcoded _PRIMARY_REPO) returns {findings:[]} / {bubbles:[]} /
// {health_signals:[]} for those absent files — so each panel must render its
// CLEAN EMPTY STATE, never a blank gap or a crash. This is design principle #2
// ("make absence legible"): loaded-but-empty must read as "the loop has nothing
// here", distinct from "nothing loaded".
//
// The existing per-panel tests assert the empty testid with initial=[] but do
// NOT assert a clean render (no console.error/warn) and do NOT exercise the
// live POLL path that the real absent-data backend actually drives. This file
// adds both, since there is no headless browser: jsdom + a console spy is the
// stand-in for "renders without console errors" (the test_source_badge idiom),
// and a mocked http layer resolving the EXACT real empty-response shape
// (the test_dashboard idiom) stands in for the live absent-data backend.
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import BubblesPanel from "../src/components/BubblesPanel";
import HealthSignalsPanel from "../src/components/HealthSignalsPanel";

// The live absent-data backend returns the key present with an empty array.
// Mock the http layer the panels self-poll to resolve exactly that shape, so
// the POLL path (not just the initial=[] shortcut) is validated against what
// the real files-absent endpoints return.
vi.mock("../src/api/http", () => ({
  getSurfacedFindings: vi.fn().mockResolvedValue({ findings: [] }),
  getBubbles: vi.fn().mockResolvedValue({ bubbles: [] }),
  getHealthSignals: vi.fn().mockResolvedValue({ health_signals: [] }),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

// Spy on console.error/warn for the duration of one render and assert neither
// fired — a React act() warning or a render-time throw lands on console.error
// in jsdom, so "not called" is the no-headless-browser stand-in for a clean
// render. Returns the spies so the caller can assert post-await.
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

describe("autonomy panels — clean empty state vs the REAL absent live data", () => {
  // ── initial=[] path (the spec's primary ask) ───────────────────────────
  // initial=[] bypasses polling and renders synchronously, mirroring a backend
  // that already returned the empty list. Each panel must show its *-empty
  // testid and log nothing to the console.

  it("SurfacedFindingsPanel: initial=[] shows findings-empty with no console errors", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<SurfacedFindingsPanel initial={[]} />);

    const panel = within(screen.getByTestId("surfaced-findings-panel"));
    expect(screen.getByTestId("findings-empty")).toBeInTheDocument();
    expect(screen.getByText("No surfaced findings yet.")).toBeInTheDocument();
    // Not a blank gap and not a stray data row.
    expect(panel.queryByTestId(/^finding-/)).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("BubblesPanel: initial=[] shows bubbles-empty with no console errors", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<BubblesPanel initial={[]} />);

    const panel = within(screen.getByTestId("bubbles-panel"));
    expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument();
    expect(panel.queryByTestId("bubble-0")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("HealthSignalsPanel: initial=[] shows health-signals-empty with no console errors", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<HealthSignalsPanel initial={[]} />);

    const panel = within(screen.getByTestId("health-signals-panel"));
    expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument();
    expect(panel.queryByTestId("health-signal-0")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  // ── live POLL path (what the real absent-data backend actually drives) ──
  // No `initial` prop → each panel polls its getX(); the mock resolves the
  // exact {key: []} the files-absent endpoints return. The loaded transition
  // must flip to the empty state (not flash a data row), and the async state
  // update must be wrapped — an unwrapped one is a console.error act() warning.

  it("SurfacedFindingsPanel: polling the absent-data endpoint settles to the empty state cleanly", async () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<SurfacedFindingsPanel pollMs={100000} />);

    await waitFor(() =>
      expect(screen.getByTestId("findings-empty")).toBeInTheDocument(),
    );
    // No error banner — the empty response is success, not failure.
    expect(
      within(screen.getByTestId("surfaced-findings-panel")).queryByText(
        /Error|TypeError|undefined/,
      ),
    ).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("BubblesPanel: polling the absent-data endpoint settles to the empty state cleanly", async () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<BubblesPanel pollMs={100000} />);

    await waitFor(() =>
      expect(screen.getByTestId("bubbles-empty")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("bubble-0")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("HealthSignalsPanel: polling the absent-data endpoint settles to the empty state cleanly", async () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<HealthSignalsPanel pollMs={100000} />);

    await waitFor(() =>
      expect(screen.getByTestId("health-signals-empty")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("health-signal-0")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
