// PipelineJourney — the dossier reader's read-only JOURNEY view.
//
// R2 (2026-08-15) rebuilt the PRESENTATION on progressive disclosure; the data
// contract, the degradation contract and the fence are untouched. These tests
// pin, in the new structure: (1) the STICKY SUBWAY-MAP STEPPER renders eight
// stations colored by each step's REAL outcome (the pre-R2 ribbon's
// reached/not-reached semantics survive as data-reached); (2) every section is
// COLLAPSED to one verdict line by default and expanding reveals the prose;
// (3) the heavy raw evidence — retrieved chunk texts, full critic / red-team
// prose, experiment trials — drills into the R0 PeekPanel; (4) BOTH item
// families — gate_verdict (item.id IS the iteration id) and finding_review
// (item.id is a finding id → getFindingDetail → source_iteration_id →
// getIterationJourney), via injection AND via self-fetch; (5) the D-052
// advisory surfaces quiet (never amber, and it never colors a station);
// (6) DEGRADES on every malformed / absent / not-found shape without throwing
// or blanking.
//
// EVERY pre-R2 pin is PORTED, never deleted: assertions that used to read a
// flat always-open section now expand that section first, and the three
// assertions whose content MOVED to the peek (critic rationale, red-team
// prose, experiment trials + results_path) assert against the peek body.
//
// The `journey` / `detail` props are the test-injection overrides (mirror
// TutorPanel's `detail`): when provided the panel renders them WITHOUT a fetch,
// so the injection tests never touch the network. The self-fetch tests spy the
// named http exports (mirrors test_harden_TutorPanel) so jsdom's real `fetch` is
// never hit. Every IterationRecord / FindingDetail field is producer-owned and
// unvalidated — a legacy/partial/buggy row can hand a field a null, number,
// object, array, or NaN; the runtime must survive them (asText drops by typeof,
// no deref).
import {
  act,
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelineJourney from "../src/components/todo/PipelineJourney";
import { STATION_KEYS } from "../src/components/todo/journeyStations";
import type {
  FindingDetail,
  HumanTodoItem,
  IterationJourneyResponse,
  IterationRecord,
} from "../src/types/schemas";
import * as http from "../src/api/http";

// S2: PipelineJourney absorbed the retired IterationDetailModal's LINKS
// section, so it renders real <Link>s — every mount needs a Router. The local
// render override keeps the existing call sites unchanged (RTL re-applies the
// wrapper on rerender too).
const render = (ui: React.ReactElement) =>
  rtlRender(ui, { wrapper: MemoryRouter });

// The absorbed links section joins the coordinator cycles on every LOADED
// journey. Stub it file-wide so no test ever reaches a live :8700 backend
// (the retired modal suite's rule); tests that pin the cycle link re-stub.
beforeEach(() => {
  vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({
    cycles: [],
  } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Cast helper — values illegal per the prop type but legal in the JSONL the
// producer actually writes; the runtime must survive them.
const bad = (v: unknown) => v as unknown as never;

// ── R2 disclosure helpers ──────────────────────────────────────────────────
// Sections are collapsed by default, so every prose assertion opens its
// section first. This is what "port the pin" means under progressive
// disclosure: the invariant is unchanged, the path to it is one click longer.
function expand(key: string) {
  fireEvent.click(screen.getByTestId(`journey-toggle-${key}`));
}

function expandAll() {
  for (const k of STATION_KEYS) {
    const btn = screen.queryByTestId(`journey-toggle-${k}`);
    if (btn !== null) fireEvent.click(btn);
  }
}

// The setup.ts IntersectionObserver stub records its instances so scrollspy can
// be driven deliberately (jsdom never intersects anything on its own).
interface StubIO {
  callback: IntersectionObserverCallback;
  elements: Set<Element>;
}
function ioInstances(): StubIO[] {
  return ((globalThis as unknown as Record<string, unknown>)
    .__IO_INSTANCES__ ?? []) as StubIO[];
}
function intersect(...testids: string[]) {
  const all = ioInstances();
  expect(all.length).toBeGreaterThan(0); // the stub must be installed
  const io = all[all.length - 1];
  const entries = testids.map((t) => ({
    target: screen.getByTestId(t),
    isIntersecting: true,
  }));
  act(() => {
    io.callback(
      entries as unknown as IntersectionObserverEntry[],
      io as unknown as IntersectionObserver,
    );
  });
}

// Watch BOTH error and warn — a React child-type violation logs console.error;
// an unhandled-rejection / act() leak logs console.error/warn. The jsdom
// stand-in for "rendered cleanly" is: neither was called.
function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

// A fully-populated iteration that reached every (non-Phase-2) step AND carries
// an experiment outcome (so the experiment station lights too).
const FULL_ITER: IterationRecord = {
  iteration_id: "iter-2026-06-14-003",
  started_at: "2026-06-14T09:00:00Z",
  ended_at: "2026-06-14T09:40:00Z",
  seed: { topic: "tail-risk mispricing", source: "nemoclaw" },
  hypothesis: { text: "Order books thin asymmetrically before resolution.", candidates_considered: 4 },
  retrieval: {
    k: 8,
    neighbors: ["paper-aaa", "paper-bbb", "paper-ccc"],
    relevance: {
      relevance: 0.82,
      low_confidence: false,
      reason: "strong on-domain match against curated anchors.",
      topicality: "on",
    },
  },
  novelty: { class: "novel", rationale: "no prior asymmetric-thinning result in retrieval." },
  critique: {
    verdict: "survives",
    rationale: "no contradicting paper surfaced.",
    contradicting_paper_id: null,
  },
  gate_status: "pending",
  experiment_outcome: {
    experiment_id: "exp004",
    metric: "effect_size",
    value: 0.31,
    summary: "Verdict=YES. effect held at n=40.",
  },
  journal_entry_path: "journal/iterations/003.md",
};

const journeyOf = (iter: IterationRecord | null): IterationJourneyResponse => ({
  found: iter !== null,
  iteration_id: iter?.iteration_id ?? "missing",
  iteration: iter,
});

const iterItem = (id: string): HumanTodoItem => ({ kind: "gate_verdict", id });
const findingItem = (id: string): HumanTodoItem => ({ kind: "finding_review", id });

const FINDING: FindingDetail = {
  found: true,
  finding_id: "sf-001",
  title: "Markets misprice tail risk",
  claim: "Order books thin asymmetrically before a resolution.",
  source_iteration_id: "iter-2026-06-14-003",
  source_iteration: { iteration_id: "iter-2026-06-14-003", topic: "tail-risk" },
};

// ═══════════════════════════════════════════════════════════════════════════
// R2 — the STICKY SUBWAY-MAP STEPPER (ports the pre-R2 PipelineRibbon pins)
// ═══════════════════════════════════════════════════════════════════════════

describe("PipelineJourney — the STEPPER draws 8 stations colored by real outcome", () => {
  it("renders all 8 stations; the FULL iteration marks every step it reached", () => {
    render(<PipelineJourney item={iterItem("iter-2026-06-14-003")} journey={journeyOf(FULL_ITER)} />);
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    for (const k of [
      "hypothesis",
      "retrieval",
      "relevance",
      "novelty",
      "critic",
      "redteam",
      "experiment",
      "verdict",
    ]) {
      expect(screen.getByTestId(`stepper-station-${k}`)).toBeInTheDocument();
    }
    // The steps THIS row reached are marked reached (the pre-R2 ribbon pin).
    for (const k of ["hypothesis", "retrieval", "relevance", "novelty", "critic", "verdict"]) {
      expect(screen.getByTestId(`stepper-station-${k}`)).toHaveAttribute(
        "data-reached",
        "true",
      );
    }
    // FULL_ITER carries no redteam block — that station is honestly un-reached.
    expect(screen.getByTestId("stepper-station-redteam")).toHaveAttribute(
      "data-reached",
      "false",
    );
    // The experiment station is ALWAYS Phase-2-flagged (the loop is
    // literature-stage until β / D-040) — the pre-R2 ribbon's contract.
    expect(screen.getByTestId("stepper-station-experiment")).toHaveAttribute(
      "data-phase2",
      "true",
    );
    // …and the visible "Phase 2" marker rides the section's summary row.
    expect(screen.getByTestId("journey-experiment")).toHaveTextContent(/phase 2/i);
  });

  it("station COLOR is the step's real outcome, from the semantic status set only", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    // passed → ok (emerald)
    for (const k of ["hypothesis", "retrieval", "relevance", "novelty", "critic", "experiment"]) {
      expect(screen.getByTestId(`stepper-station-${k}`)).toHaveAttribute(
        "data-status",
        "ok",
      );
    }
    // a pending human gate → info (sky, GATE_TONE's own pending color)
    expect(screen.getByTestId("stepper-station-verdict")).toHaveAttribute(
      "data-status",
      "info",
    );
    // a step that never ran → idle (zinc)
    expect(screen.getByTestId("stepper-station-redteam")).toHaveAttribute(
      "data-status",
      "idle",
    );
    // Only the five semantic status tokens ever appear — never a bespoke hue.
    for (const k of STATION_KEYS) {
      expect(
        screen.getByTestId(`stepper-station-${k}`).getAttribute("data-status"),
      ).toMatch(/^(ok|warn|bad|info|idle)$/);
    }
  });

  it("a FLAGGED step reads warn and a FAILED one reads bad — never coerced to ok", () => {
    const flagged: IterationRecord = {
      ...FULL_ITER,
      // zero neighbors is a real retrieval flag
      retrieval: {
        k: 4,
        neighbors: [],
        relevance: { relevance: 0.2, low_confidence: true, reason: "thin" },
      },
      novelty: { class: "nonsense", rationale: "incoherent" },
      critique: { verdict: "falsified", rationale: "a prior result contradicts it." },
      gate_status: "invalid",
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(flagged)} />);
    expect(screen.getByTestId("stepper-station-retrieval")).toHaveAttribute("data-status", "warn");
    expect(screen.getByTestId("stepper-station-relevance")).toHaveAttribute("data-status", "warn");
    expect(screen.getByTestId("stepper-station-novelty")).toHaveAttribute("data-status", "bad");
    expect(screen.getByTestId("stepper-station-critic")).toHaveAttribute("data-status", "bad");
    expect(screen.getByTestId("stepper-station-verdict")).toHaveAttribute("data-status", "bad");
  });

  it("an early-halted iteration marks the stations it never reached", () => {
    const early: IterationRecord = {
      iteration_id: "iter-early",
      started_at: "x",
      ended_at: "y",
      hypothesis: { text: "a hypothesis" },
      retrieval: { k: 3, neighbors: [] },
      // no relevance, no novelty, no critique, no gate, no outcome
      journal_entry_path: "j.md",
    };
    render(<PipelineJourney item={iterItem("iter-early")} journey={journeyOf(early)} />);
    expect(screen.getByTestId("stepper-station-hypothesis")).toHaveAttribute("data-reached", "true");
    expect(screen.getByTestId("stepper-station-retrieval")).toHaveAttribute("data-reached", "true");
    for (const k of ["relevance", "novelty", "critic", "redteam", "experiment", "verdict"]) {
      expect(screen.getByTestId(`stepper-station-${k}`)).toHaveAttribute("data-reached", "false");
      expect(screen.getByTestId(`stepper-station-${k}`)).toHaveAttribute("data-status", "idle");
    }
    // reached-but-empty retrieval is a FLAG, not a pass — 0 neighbors is real.
    expect(screen.getByTestId("stepper-station-retrieval")).toHaveAttribute("data-status", "warn");
  });

  it("clicking a station scrolls to its section and marks it current", () => {
    const scrollSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    fireEvent.click(screen.getByTestId("stepper-station-critic"));
    expect(scrollSpy).toHaveBeenCalled();
    const station = screen.getByTestId("stepper-station-critic");
    expect(station).toHaveAttribute("data-active", "true");
    expect(station).toHaveAttribute("aria-current", "step");
    // Navigation is NOT disclosure — the section stays collapsed.
    expect(screen.queryByTestId("journey-body-critic")).toBeNull();
  });

  it("SCROLLSPY marks the topmost section in view as the current station", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expect(screen.getByTestId("stepper-station-novelty")).toHaveAttribute(
      "data-active",
      "false",
    );
    // novelty + critic both in the band → the EARLIER station wins.
    intersect("journey-novelty", "journey-critic");
    expect(screen.getByTestId("stepper-station-novelty")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("stepper-station-critic")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("the stepper still renders (all stations idle) when the journey is unavailable", () => {
    render(
      <PipelineJourney
        item={iterItem("iter-nf")}
        journey={{ found: false, iteration_id: "iter-nf", iteration: null }}
      />,
    );
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    for (const k of STATION_KEYS) {
      const station = screen.getByTestId(`stepper-station-${k}`);
      expect(station).toHaveAttribute("data-reached", "false");
      expect(station).toHaveAttribute("data-status", "idle");
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// R2 — PROGRESSIVE DISCLOSURE: one verdict line per section by default
// ═══════════════════════════════════════════════════════════════════════════

describe("PipelineJourney — sections are COLLAPSED to one verdict line by default", () => {
  it("no section body is mounted until the human expands it", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    for (const k of STATION_KEYS) {
      expect(screen.queryByTestId(`journey-body-${k}`)).toBeNull();
      expect(screen.getByTestId(`journey-toggle-${k}`)).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    }
    // The prose the sections hold is therefore NOT on the page.
    expect(
      screen.queryByText("no prior asymmetric-thinning result in retrieval."),
    ).toBeNull();
    expect(
      screen.queryByText("Order books thin asymmetrically before resolution."),
    ).toBeNull();
  });

  it("the collapsed line states the step's outcome — the 15-second read", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expect(screen.getByTestId("journey-summary-hypothesis")).toHaveTextContent(
      /stated · 4 candidates/,
    );
    expect(screen.getByTestId("journey-summary-retrieval")).toHaveTextContent(
      /3 neighbors · k=8/,
    );
    expect(screen.getByTestId("journey-summary-relevance")).toHaveTextContent("0.82");
    expect(screen.getByTestId("journey-summary-novelty")).toHaveTextContent("novel");
    expect(screen.getByTestId("journey-summary-critic")).toHaveTextContent(
      /survives · uncontradicted/,
    );
    expect(screen.getByTestId("journey-summary-redteam")).toHaveTextContent(
      /no red-team pass on this row/,
    );
    expect(screen.getByTestId("journey-summary-verdict")).toHaveTextContent("pending");
  });

  it("expanding reveals the prose; each section's state is INDEPENDENT", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expand("hypothesis");
    expect(screen.getByTestId("journey-body-hypothesis")).toHaveTextContent(
      "Order books thin asymmetrically before resolution.",
    );
    expect(screen.getByTestId("journey-toggle-hypothesis")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    // Opening one section opens ONLY that one.
    for (const k of STATION_KEYS.filter((s) => s !== "hypothesis")) {
      expect(screen.queryByTestId(`journey-body-${k}`)).toBeNull();
    }
    // …and it collapses again on a second click.
    expand("hypothesis");
    expect(screen.queryByTestId("journey-body-hypothesis")).toBeNull();
  });

  it("expansion lives in COMPONENT STATE — nothing is written to localStorage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expandAll();
    expect(setItem).not.toHaveBeenCalled();
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// R2 — PEEK drill-in for the heavy raw evidence
// ═══════════════════════════════════════════════════════════════════════════

describe("PipelineJourney — raw evidence drills into the PeekPanel", () => {
  it("retrieved CHUNK TEXTS open in the peek, not inline", () => {
    const withChunks: IterationRecord = {
      ...FULL_ITER,
      retrieval: {
        ...FULL_ITER.retrieval!,
        neighbors: [
          { id: "chunk-a", text: "Thin books precede resolution in 3 of 4 venues.", score: 0.81 },
          { id: "chunk-b", text: "No asymmetry observed in the control window." },
        ],
      },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withChunks)} />);
    // Not inline — the chunk prose is nowhere on the page until the peek opens.
    expect(
      screen.queryByText(/Thin books precede resolution/),
    ).toBeNull();
    expand("retrieval");
    fireEvent.click(screen.getByTestId("journey-peek-chunks"));
    const peek = screen.getByTestId("peek-chunks");
    expect(peek).toHaveTextContent("chunk-a");
    expect(peek).toHaveTextContent("Thin books precede resolution in 3 of 4 venues.");
    expect(peek).toHaveTextContent("No asymmetry observed in the control window.");
    // It is the R0 PeekPanel: a focus-trapped right slide-over dialog.
    expect(screen.getByTestId("peek-panel")).toHaveAttribute("aria-modal", "true");
    // Esc closes it.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("peek-chunks")).toBeNull();
  });

  it("the peek button is absent when there is nothing raw to show", () => {
    const noNeighbors: IterationRecord = {
      ...FULL_ITER,
      retrieval: { k: 4, neighbors: [], relevance: FULL_ITER.retrieval!.relevance },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(noNeighbors)} />);
    expand("retrieval");
    expect(screen.queryByTestId("journey-peek-chunks")).toBeNull();
  });
});

describe("PipelineJourney — JOURNEY blocks render read-only from the iteration record", () => {
  it("renders hypothesis, retrieval (k + neighbors) + relevance, novelty, critic", () => {
    render(<PipelineJourney item={iterItem("iter-2026-06-14-003")} journey={journeyOf(FULL_ITER)} />);
    const panel = screen.getByTestId("pipeline-journey");
    expandAll();

    expect(screen.getByTestId("journey-hypothesis")).toHaveTextContent(
      "Order books thin asymmetrically before resolution.",
    );
    // retrieval: k + a couple top neighbors
    const retrieval = screen.getByTestId("journey-retrieval");
    expect(retrieval).toHaveTextContent("8");
    const neighbors = screen.getByTestId("journey-neighbors");
    expect(neighbors).toHaveTextContent("paper-aaa");
    expect(neighbors).toHaveTextContent("paper-bbb");
    // relevance score + reason
    const relevance = screen.getByTestId("journey-relevance");
    expect(relevance).toHaveTextContent("0.82");
    expect(relevance).toHaveTextContent("strong on-domain match against curated anchors.");
    // novelty class + rationale
    expect(screen.getByTestId("journey-novelty")).toHaveTextContent("novel");
    expect(screen.getByTestId("journey-novelty")).toHaveTextContent(
      "no prior asymmetric-thinning result in retrieval.",
    );
    // critic verdict + rationale (the rationale now reads in the peek)
    expect(screen.getByTestId("journey-critic")).toHaveTextContent("survives");
    fireEvent.click(screen.getByTestId("journey-peek-critic"));
    expect(screen.getByTestId("peek-critic")).toHaveTextContent(
      "no contradicting paper surfaced.",
    );
    expect(panel.textContent ?? "").not.toContain("[object Object]");
  });

  it("contradicting paper: a non-null id renders 'contradicted by <id>'", () => {
    const withContra: IterationRecord = {
      ...FULL_ITER,
      critique: { verdict: "restated", rationale: "a prior paper says this.", contradicting_paper_id: "arxiv-2401.00001" },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withContra)} />);
    expand("critic");
    const contra = screen.getByTestId("journey-contradicting-paper");
    expect(contra).toHaveTextContent(/contradicted by/i);
    expect(contra).toHaveTextContent("arxiv-2401.00001");
  });

  it("contradicting paper: a null id renders 'uncontradicted'", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expand("critic");
    expect(screen.getByTestId("journey-contradicting-paper")).toHaveTextContent(/uncontradicted/i);
  });

  it("experiment-outcome PRESENT renders the bridge fields; an HONEST stage label says experiment-bridged", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expand("experiment");
    const out = screen.getByTestId("journey-outcome-present");
    expect(out).toHaveTextContent("exp004");
    expect(out).toHaveTextContent("effect_size");
    expect(out).toHaveTextContent("0.31");
    expect(screen.queryByTestId("journey-outcome-placeholder")).toBeNull();
    expect(screen.getByTestId("journey-stage-label")).toHaveTextContent(/experiment-bridged/i);
    // the stage BANNER names the applied tier
    const banner = screen.getByTestId("journey-stage-banner");
    expect(banner).toHaveAttribute("data-stage", "applied");
    expect(banner).toHaveTextContent(/applied-tier/i);
  });

  it("experiment-outcome ABSENT renders the Phase-2 placeholder + a literature-stage label", () => {
    const litStage: IterationRecord = { ...FULL_ITER, experiment_outcome: null };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(litStage)} />);
    // The collapsed line ALREADY says it — the placeholder reads on expand.
    expect(screen.getByTestId("journey-summary-experiment")).toHaveTextContent(
      /literature-stage — not experimentally tested \(Phase 2\)/i,
    );
    expand("experiment");
    expect(screen.getByTestId("journey-outcome-placeholder")).toHaveTextContent(
      /literature-stage — not experimentally tested \(Phase 2\)/i,
    );
    expect(screen.queryByTestId("journey-outcome-present")).toBeNull();
    expect(screen.getByTestId("journey-stage-label")).toHaveTextContent(/literature-stage/i);
    // the stage BANNER names the literature stage
    const banner = screen.getByTestId("journey-stage-banner");
    expect(banner).toHaveAttribute("data-stage", "literature");
    expect(banner).toHaveTextContent(/literature-stage/i);
    // the experiment station is NOT lit when no outcome exists
    expect(screen.getByTestId("stepper-station-experiment")).toHaveAttribute("data-reached", "false");
  });
});

describe("PipelineJourney — the D-052 topicality advisory surfaces QUIET, never amber", () => {
  const withAdvisory: IterationRecord = {
    ...FULL_ITER,
    retrieval: {
      ...FULL_ITER.retrieval!,
      relevance: { ...FULL_ITER.retrieval!.relevance!, topicality_advisory: "off" },
    },
  };

  it("renders the raw advisory value when present, with NO amber low-evidence styling", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withAdvisory)} />);
    expand("relevance");
    const adv = screen.getByTestId("journey-topicality-advisory");
    expect(adv).toHaveTextContent(/non-gating/i);
    expect(adv).toHaveTextContent("off");
    // NEVER amber — the advisory is non-gating, dark by default; it must not wear
    // the low-evidence alarm tone.
    expect(adv.className).not.toMatch(/amber/);
  });

  it("the advisory NEVER colors the relevance station (non-gating stays non-gating)", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withAdvisory)} />);
    // low_confidence is false on this row, so the station stays a clean pass
    // even though the advisory dissents.
    expect(screen.getByTestId("stepper-station-relevance")).toHaveAttribute(
      "data-status",
      "ok",
    );
  });

  it("renders NO advisory line when the field is absent (the normal row)", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expand("relevance");
    expect(screen.queryByTestId("journey-topicality-advisory")).toBeNull();
  });
});

describe("PipelineJourney — FINDING family (item.id is a finding_id)", () => {
  it("INJECTED detail + journey: surfaces the finding claim at the top + the journey", () => {
    render(
      <PipelineJourney
        item={findingItem("sf-001")}
        detail={FINDING}
        journey={journeyOf(FULL_ITER)}
      />,
    );
    expect(screen.getByTestId("journey-finding-claim")).toHaveTextContent(
      "Order books thin asymmetrically before a resolution.",
    );
    expect(screen.getByTestId("journey-loaded")).toBeInTheDocument();
    expect(screen.getByTestId("journey-hypothesis")).toBeInTheDocument();
  });

  it("SELF-FETCH: getFindingDetail → source_iteration_id → getIterationJourney → journey", async () => {
    const c = watchConsole();
    const fdSpy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    const jSpy = vi
      .spyOn(http, "getIterationJourney")
      .mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={findingItem("sf-001")} />);
    await waitFor(() => expect(screen.getByTestId("journey-loaded")).toBeInTheDocument());
    expect(fdSpy).toHaveBeenCalledWith("sf-001");
    // the journey was fetched with the finding's SOURCE iteration id, not "sf-001"
    expect(jSpy).toHaveBeenCalledWith("iter-2026-06-14-003");
    expect(screen.getByTestId("journey-finding-claim")).toHaveTextContent(
      "Order books thin asymmetrically before a resolution.",
    );
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a finding whose detail FAILS to load → unavailable, stepper still shown, no throw", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockRejectedValue(new Error("network"));
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={findingItem("sf-x")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    // no source iteration was ever resolved → the journey endpoint is never hit
    expect(jSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a found:false finding detail → unavailable (no source iteration to journey)", () => {
    const c = watchConsole();
    render(
      <PipelineJourney
        item={findingItem("sf-missing")}
        detail={{ found: false, finding_id: "sf-missing" }}
      />,
    );
    expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("journey-loaded")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — ITERATION family (item.id is an iteration_id)", () => {
  it("SELF-FETCH: getIterationJourney(item.id) → renders the journey; no finding fetch", async () => {
    const c = watchConsole();
    const fdSpy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={iterItem("iter-2026-06-14-003")} />);
    await waitFor(() => expect(screen.getByTestId("journey-loaded")).toBeInTheDocument());
    expect(jSpy).toHaveBeenCalledWith("iter-2026-06-14-003");
    // the iteration family NEVER calls getFindingDetail
    expect(fdSpy).not.toHaveBeenCalled();
    // no finding-claim banner for the iteration family
    expect(screen.queryByTestId("journey-finding-claim")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a REJECTED journey fetch → unavailable, stepper still shown, no console error", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getIterationJourney").mockRejectedValue(new Error("down"));
    render(<PipelineJourney item={iterItem("iter-x")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("journey-loaded")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — OTHER item kinds get a quiet note", () => {
  it("a bubble_unacked item → 'no pipeline journey for this item kind', no fetch", async () => {
    const fdSpy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={{ kind: "bubble_unacked", id: "b-1" }} />);
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByTestId("journey-no-kind")).toHaveTextContent(
      /no pipeline journey for this item kind/i,
    );
    // an unknown-kind item fires NO fetch on either endpoint
    expect(fdSpy).not.toHaveBeenCalled();
    expect(jSpy).not.toHaveBeenCalled();
  });

  it("an unknown forward-compat kind also degrades to the quiet note", () => {
    render(<PipelineJourney item={bad({ kind: "some_future_kind", id: "z" })} />);
    expect(screen.getByTestId("journey-no-kind")).toBeInTheDocument();
  });
});

describe("PipelineJourney — DEGRADES on malformed / not-found journey (never throws, never blanks)", () => {
  it("found:false journey → 'journey unavailable', stepper present, no overview", () => {
    const c = watchConsole();
    render(
      <PipelineJourney
        item={iterItem("iter-nf")}
        journey={{ found: false, iteration_id: "iter-nf", iteration: null }}
      />,
    );
    expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
    expect(screen.getByTestId("journey-unavailable")).toHaveTextContent(/journey unavailable/i);
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    expect(screen.queryByTestId("journey-loaded")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a null / array / string injected journey → unavailable, panel present, no throw", () => {
    const c = watchConsole();
    for (const j of [bad(null), bad([1, 2]), bad("nope")]) {
      expect(() =>
        render(<PipelineJourney item={iterItem("x")} journey={j} />),
      ).not.toThrow();
      expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
      expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument();
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("found:true but a NON-OBJECT iteration → unavailable, no `.hypothesis` read on a primitive", () => {
    const c = watchConsole();
    for (const it of ["a string", 42, Number.NaN, null, [1]] as unknown[]) {
      render(
        <PipelineJourney
          item={iterItem("x")}
          journey={bad({ found: true, iteration_id: "x", iteration: it })}
        />,
      );
      expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("journey-loaded")).toBeNull();
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("object-shaped / NaN producer fields never reach React as a child — dropped, no '[object Object]'", () => {
    const c = watchConsole();
    const malformed = bad({
      found: true,
      iteration_id: "iter-bad",
      iteration: {
        iteration_id: "iter-bad",
        hypothesis: { text: { not: "a string" } },
        retrieval: {
          k: { bad: 1 },
          neighbors: [{ id: "ok-neighbor" }, { junk: 1 }, 42, null],
          relevance: { relevance: Number.NaN, reason: ["array"], topicality_advisory: { x: 1 } },
        },
        novelty: { class: ["arr"], rationale: 7 }, // rationale finite → "7" (legal)
        critique: { verdict: { v: 1 }, contradicting_paper_id: { id: 1 } },
        experiment_outcome: { experiment_id: { e: 1 }, value: { multi: 1 } },
      },
    });
    expect(() =>
      render(<PipelineJourney item={iterItem("iter-bad")} journey={malformed} />),
    ).not.toThrow();
    // EVERY section open — a collapsed section would pass this vacuously.
    expandAll();
    const panel = screen.getByTestId("pipeline-journey");
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // the one legal scalar neighbor ({id:"ok-neighbor"}) survives the preview
    expect(screen.getByTestId("journey-neighbors")).toHaveTextContent("ok-neighbor");
    // …and the raw-chunk peek coerces just as hard
    fireEvent.click(screen.getByTestId("journey-peek-chunks"));
    const peekText = screen.getByTestId("peek-chunks").textContent ?? "";
    expect(peekText).toContain("ok-neighbor");
    expect(peekText).not.toContain("[object Object]");
    expect(peekText).not.toMatch(/NaN|Infinity/);
    fireEvent.keyDown(document, { key: "Escape" });
    // a malformed object topicality_advisory renders NO advisory line (dropped)
    expect(screen.queryByTestId("journey-topicality-advisory")).toBeNull();
    // the one legal field (novelty.rationale: 7) survives as raw text
    expect(screen.getByTestId("journey-novelty")).toHaveTextContent("7");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a malformed ITEM (non-object / missing id) degrades to the quiet note, no throw", () => {
    const c = watchConsole();
    for (const it of [bad(null), bad("str"), bad(42), bad({ kind: "gate_verdict" })]) {
      expect(() => render(<PipelineJourney item={it} />)).not.toThrow();
      expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — injection SUPPRESSES the network entirely", () => {
  it("an injected journey fires NO fetch", async () => {
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    await new Promise((r) => setTimeout(r, 10));
    expect(jSpy).not.toHaveBeenCalled();
  });

  it("an injected detail + journey (finding family) fires NO fetch on either endpoint", async () => {
    const fdSpy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(
      <PipelineJourney item={findingItem("sf-001")} detail={FINDING} journey={journeyOf(FULL_ITER)} />,
    );
    await new Promise((r) => setTimeout(r, 10));
    expect(fdSpy).not.toHaveBeenCalled();
    expect(jSpy).not.toHaveBeenCalled();
  });
});

// ── Adversarial-verifier regressions (verifier pass, 2026-06-16). These pin
// breakages an adversarial probe found beyond the build-agent suite. Each is a
// genuine failure mode, not a duplicate of an existing assertion.
describe("PipelineJourney — VERIFIER: cross-family re-render must not strand stale failure state", () => {
  // REGRESSION (real bug, fixed): a finding_review item whose getFindingDetail
  // REJECTED set detailFailed=true; when the SAME mounted component was then
  // re-rendered with a healthy gate_verdict (iteration) item, the surface stayed
  // falsely stuck on "journey unavailable" — because `detailFailed` (a
  // finding-only signal whose effect early-returns for the iteration family,
  // never clearing it) was OR'd into `unavailable` unconditionally. Fix: gate
  // detailFailed by family === "finding". Without the fix this throws in waitFor.
  it("finding detail FAILED → re-render to a healthy ITERATION recovers (no stale detailFailed)", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockRejectedValue(new Error("finding down"));
    vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    const { rerender } = render(<PipelineJourney item={findingItem("sf-fail")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    rerender(<PipelineJourney item={iterItem("iter-2026-06-14-003")} />);
    await waitFor(() => expect(screen.getByTestId("journey-loaded")).toBeInTheDocument());
    expect(screen.queryByTestId("journey-unavailable")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("iteration journey FAILED → re-render to a healthy FINDING recovers (no stale journeyFailed)", async () => {
    const c = watchConsole();
    const jSpy = vi.spyOn(http, "getIterationJourney");
    jSpy.mockRejectedValueOnce(new Error("down")).mockResolvedValue(journeyOf(FULL_ITER));
    vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    const { rerender } = render(<PipelineJourney item={iterItem("iter-bad")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    rerender(<PipelineJourney item={findingItem("sf-001")} />);
    await waitFor(() => expect(screen.getByTestId("journey-loaded")).toBeInTheDocument());
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — VERIFIER: deep-deref-safe coercion of hostile producer scalars", () => {
  it("throwing-toString / Symbol / bigint / Infinity in EVERY field → no throw, no leak", () => {
    const c = watchConsole();
    const thrower = { toString() { throw new Error("boom"); } } as unknown;
    const hostile = bad({
      found: true,
      iteration_id: "iter-hostile",
      iteration: {
        iteration_id: "iter-hostile",
        hypothesis: { text: thrower },
        retrieval: {
          k: Symbol("k"),
          neighbors: [thrower, 10n, Symbol("n")],
          relevance: { relevance: 5n, reason: thrower, topicality: Infinity, topicality_advisory: thrower },
        },
        novelty: { class: Symbol("c"), rationale: thrower },
        critique: { verdict: thrower, contradicting_paper_id: 9n },
        experiment_outcome: { experiment_id: thrower, value: -Infinity },
        gate_status: Symbol("g"),
      },
    });
    expect(() =>
      render(<PipelineJourney item={iterItem("iter-hostile")} journey={hostile} />),
    ).not.toThrow();
    expandAll();
    const text = screen.getByTestId("pipeline-journey").textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity|Symbol|\d+n\b/);
    // a non-string contradicting_paper_id drops → uncontradicted (never a leak)
    expect(screen.getByTestId("journey-contradicting-paper")).toHaveTextContent(/uncontradicted/i);
    // every station still resolves to a legal semantic status
    for (const k of STATION_KEYS) {
      expect(
        screen.getByTestId(`stepper-station-${k}`).getAttribute("data-status"),
      ).toMatch(/^(ok|warn|bad|info|idle)$/);
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("relevance block as an ARRAY and neighbors a NON-ARRAY → no crash, degrades", () => {
    const c = watchConsole();
    render(
      <PipelineJourney
        item={iterItem("x")}
        journey={bad({
          found: true,
          iteration_id: "x",
          iteration: { iteration_id: "x", retrieval: { k: 3, neighbors: "not-an-array", relevance: [1, 2, 3] } },
        })}
      />,
    );
    expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
    expandAll();
    // no neighbor preview, and the relevance step honestly reports "no block"
    // rather than inventing one from an array.
    expect(screen.queryByTestId("journey-neighbors")).toBeNull();
    expect(screen.getByTestId("journey-relevance")).toHaveTextContent(
      /no relevance block on this row/,
    );
    expect(screen.queryByTestId("journey-evidence-grid")).toBeNull();
    expect(screen.getByTestId("stepper-station-relevance")).toHaveAttribute(
      "data-reached",
      "false",
    );
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — VERIFIER: finding usable but its journey fetch fails still surfaces the claim", () => {
  it("getFindingDetail OK, getIterationJourney REJECTS → unavailable BUT the finding claim still shows", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockResolvedValue(FINDING);
    vi.spyOn(http, "getIterationJourney").mockRejectedValue(new Error("journey down"));
    render(<PipelineJourney item={findingItem("sf-001")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    expect(screen.getByTestId("journey-finding-claim")).toHaveTextContent(
      "Order books thin asymmetrically before a resolution.",
    );
    expect(screen.getByTestId("journey-stepper")).toBeInTheDocument();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("source iteration id resolves via NESTED source_iteration.iteration_id when the flat field is absent", async () => {
    const c = watchConsole();
    const nested: FindingDetail = {
      found: true,
      finding_id: "sf-n",
      claim: "nested-source claim",
      source_iteration: { iteration_id: "iter-nested" },
    };
    vi.spyOn(http, "getFindingDetail").mockResolvedValue(nested);
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={findingItem("sf-n")} />);
    await waitFor(() => expect(jSpy).toHaveBeenCalled());
    expect(jSpy).toHaveBeenCalledWith("iter-nested");
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("PipelineJourney — VERIFIER: the D-052 advisory never wears an alarm tone", () => {
  it("advisory present → no amber/red/orange/yellow class token on the line or its children", () => {
    const withAdvisory: IterationRecord = {
      ...FULL_ITER,
      retrieval: {
        ...FULL_ITER.retrieval!,
        relevance: { ...FULL_ITER.retrieval!.relevance!, topicality_advisory: "off" },
      },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withAdvisory)} />);
    expand("relevance");
    const adv = screen.getByTestId("journey-topicality-advisory");
    expect(adv.className).not.toMatch(/amber|red|orange|yellow/);
    expect(adv.innerHTML).not.toMatch(/amber|red|orange|yellow|low-evidence/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// ABSORBED-MODAL pins (UI simplification S2). IterationDetailModal died; its
// unique sections moved into this journey per the plan's absorption table.
// These pins are PORTED from tests/test_iteration_detail_modal.tsx — same
// fixtures, same assertions, re-addressed at the journey testids (and, under
// R2, at the section that now owns each one).
// ═══════════════════════════════════════════════════════════════════════════

// A fully-loaded SYNTHETIC row exercising every absorbed section at once.
// (Constructed for coverage — explicitly not a live row. The
// experiment_outcome block is the verbatim-real exp003 bridge from
// loop_memory.jsonl.)
const FULL_ABSORBED: IterationRecord = {
  iteration_id: "iter-modal-full",
  started_at: "2026-06-10T10:00:00Z",
  ended_at: "2026-06-10T10:05:00Z",
  seed: {
    topic: "Synthetic full-coverage row for the absorbed journey",
    source: "coordinator",
  },
  hypothesis: {
    text: "LLM bidders shade bids under ascending pressure.",
    candidates_considered: 3,
  },
  retrieval: {
    k: 8,
    neighbors: [{ doc_id: "d1" }],
    relevance: {
      relevance: 0.42,
      low_confidence: true,
      reason: "thin: only one sharp neighbor",
      anchor_cosine: 0.31,
      curated_overlap: 0.05,
      neighbor_spread: 0.6,
      topicality: "unsure",
      category: "thin",
      rule_fired: "R2",
    },
  },
  novelty: {
    class: "unclear",
    rationale: "Neighbors cover auctions but not the shading mechanism.",
    novelty_axes: {
      phenomenon: "known",
      substrate: "unstudied_llm",
      predicted_direction: "matches",
    },
    verdict_overridden_from: "novel",
    override_reason: "low-confidence retrieval downgraded the class",
  },
  critique: {
    verdict: "undecidable",
    rationale: "No contradicting neighbor; corpus too thin to judge.",
    contradicting_paper_id: "vickrey1961-chunk-9",
    verdict_overridden_from: "survives",
    override_reason: "skeptic attack_verdict='refuted'",
    skeptic_verdict: "refuted",
  },
  redteam: {
    verdict: "proceed",
    critique: "Mechanism is testable but underspecified.",
    suggested_revision: "Pin the auction format before running.",
    confidence: 0.7,
    retries_used: 0,
  },
  meta_review: {
    conditioning_bullets: ["carried bullet alpha", "carried bullet beta"],
    rows_considered: 5,
  },
  gate_status: "pending",
  // Verbatim-real bridge block (loop_memory.jsonl, exp003).
  experiment_outcome: {
    experiment_id: "exp003_vickrey_rediscovery",
    metric: "truthful_bid_fraction",
    value: 1.0,
    summary:
      "Verdict=YES. Fraction of trials with mean |bid - valuation| <= 5: 100.00%.",
    results_path: "experiments/exp003_vickrey_rediscovery/results/summary.md",
    trials: 50,
  },
  process_status: "exited_clean",
  wrapper_call_ids: ["c502cb94-46bb-42cf-8394-0ffbf2f2063e"],
  journal_entry_path: "journal/iterations/full.md",
};

function renderAbsorbed(row: IterationRecord = FULL_ABSORBED) {
  render(
    <PipelineJourney
      item={iterItem(row.iteration_id)}
      journey={journeyOf(row)}
    />,
  );
  return screen.getByTestId("journey-loaded");
}

describe("PipelineJourney — ABSORBED verdict header (full badge set, always visible)", () => {
  it("renders the full badge set the modal header carried", () => {
    const loaded = renderAbsorbed();
    const header = within(loaded).getByTestId("journey-verdict-header");
    // Full badges: novelty class, axes chip, critique verdict, redteam (the
    // clean chip the row dropped), gate, process, source, low-evidence,
    // experiment.
    expect(within(header).getByText("unclear")).toBeInTheDocument();
    expect(within(header).getByTestId("novelty-axes-chip")).toBeInTheDocument();
    expect(within(header).getByText("undecidable")).toBeInTheDocument();
    expect(within(header).getByTestId("redteam-chip")).toHaveTextContent(
      /proceed/,
    );
    expect(within(header).getByText("pending")).toBeInTheDocument();
    expect(within(header).getByText("pid clean")).toBeInTheDocument();
    expect(within(header).getByTestId("source-badge")).toHaveTextContent(
      "coordinator",
    );
    expect(within(header).getByTestId("low-evidence-badge")).toBeInTheDocument();
    expect(within(header).getByTestId("experiment-chip")).toBeInTheDocument();
  });

  it("override provenance is VISIBLE TEXT for BOTH blocks — now WITH the step it explains", () => {
    renderAbsorbed();
    // R2 moved each override out of the header and into its own section.
    expand("novelty");
    const nov = screen.getByTestId("journey-override-novelty");
    expect(nov).toHaveTextContent("overridden from novel");
    expect(nov).toHaveTextContent(
      "reason: low-confidence retrieval downgraded the class",
    );
    expand("critic");
    const crit = screen.getByTestId("journey-override-critique");
    expect(crit).toHaveTextContent("overridden from survives");
    expect(crit).toHaveTextContent("reason: skeptic attack_verdict='refuted'");
    expect(crit).toHaveTextContent("skeptic said refuted");
  });

  it("hypothesis carries candidates_considered", () => {
    renderAbsorbed();
    expand("hypothesis");
    expect(screen.getByTestId("journey-candidates")).toHaveTextContent(
      "candidates considered: 3",
    );
  });

  it("the quiet-lane verdicts keep their chip tone on the stepper (no new alarm)", () => {
    renderAbsorbed();
    // chips.tsx deliberately renders `unclear` / `undecidable` quiet-grey —
    // "could not be judged" is not a wolf to cry. The stepper mirrors that
    // rather than inventing a second color language.
    expect(screen.getByTestId("stepper-station-novelty")).toHaveAttribute(
      "data-status",
      "idle",
    );
    expect(screen.getByTestId("stepper-station-critic")).toHaveAttribute(
      "data-status",
      "idle",
    );
    // …while the genuinely-flagged low-confidence retrieval DOES read warn.
    expect(screen.getByTestId("stepper-station-relevance")).toHaveAttribute(
      "data-status",
      "warn",
    );
    // …and both are still marked REACHED (grey ≠ "never ran").
    expect(screen.getByTestId("stepper-station-critic")).toHaveAttribute(
      "data-reached",
      "true",
    );
  });
});

describe("PipelineJourney — ABSORBED evidence grid + low-evidence inline", () => {
  it("renders the full relevance diagnostic grid (incl. the ladder diagnostics)", () => {
    renderAbsorbed();
    expand("relevance");
    const grid = screen.getByTestId("journey-evidence-grid");
    for (const pair of [
      ["category", "thin"],
      ["rule_fired", "R2"],
      ["anchor_cosine", "0.31"],
      ["curated_overlap", "0.05"],
      ["neighbor_spread", "0.6"],
    ] as const) {
      expect(grid).toHaveTextContent(pair[0]);
      expect(grid).toHaveTextContent(pair[1]);
    }
    // The frozen trio + topicality still read in the relevance section.
    const rel = screen.getByTestId("journey-relevance");
    expect(rel).toHaveTextContent("0.42");
    expect(rel).toHaveTextContent("thin: only one sharp neighbor");
    expect(rel).toHaveTextContent("unsure");
  });

  it("the low-evidence detail renders INLINE (what the badge's tooltip says)", () => {
    renderAbsorbed();
    expand("relevance");
    const detail = screen.getByTestId("journey-low-evidence-detail");
    expect(detail).toHaveTextContent(/retrieval flagged low-confidence/);
    expect(detail).toHaveTextContent(/category: thin/);
    expect(detail).toHaveTextContent(/rule: R2/);
  });

  it("a confident row renders NO low-evidence box (the amber lane stays honest)", () => {
    render(
      <PipelineJourney
        item={iterItem(FULL_ITER.iteration_id)}
        journey={journeyOf(FULL_ITER)}
      />,
    );
    expand("relevance");
    expect(screen.queryByTestId("journey-low-evidence-detail")).toBeNull();
  });
});

describe("PipelineJourney — ABSORBED adversarial detail (skeptic + redteam)", () => {
  it("renders the skeptic verdict and every redteam field", () => {
    renderAbsorbed();
    expand("critic");
    const critic = screen.getByTestId("journey-critic");
    expect(critic).toHaveTextContent("vickrey1961-chunk-9");
    expect(critic).toHaveTextContent("refuted");
    // The critic PROSE now drills into the peek (R2) rather than inlining.
    fireEvent.click(screen.getByTestId("journey-peek-critic"));
    expect(screen.getByTestId("peek-critic")).toHaveTextContent(
      "No contradicting neighbor; corpus too thin to judge.",
    );
    fireEvent.keyDown(document, { key: "Escape" });

    expand("redteam");
    const redteam = screen.getByTestId("journey-redteam");
    expect(redteam).toHaveTextContent("0.7"); // confidence
    expect(redteam).toHaveTextContent("retries used");
    // The clean proceed/0 chip renders quiet here (it never earns a row's
    // alarm slot) — the moved-scope contract.
    expect(within(redteam).getByTestId("redteam-chip").className).toContain(
      "zinc",
    );
    // …and the red-team PROSE drills into the peek.
    fireEvent.click(screen.getByTestId("journey-peek-redteam"));
    const peek = screen.getByTestId("peek-redteam");
    expect(peek).toHaveTextContent("Mechanism is testable but underspecified.");
    expect(peek).toHaveTextContent("Pin the auction format before running.");
  });

  it("no redteam block → no redteam DETAIL (pre-v1 rows fake nothing)", () => {
    render(
      <PipelineJourney
        item={iterItem(FULL_ITER.iteration_id)}
        journey={journeyOf(FULL_ITER)}
      />,
    );
    // The STATION always exists (the map has eight stops) but it says so
    // honestly and mounts no detail block, no chip, no peek.
    expect(screen.getByTestId("journey-summary-redteam")).toHaveTextContent(
      "no red-team pass on this row",
    );
    expand("redteam");
    expect(screen.queryByTestId("journey-redteam-detail")).toBeNull();
    expect(screen.queryByTestId("journey-peek-redteam")).toBeNull();
  });
});

describe("PipelineJourney — ABSORBED conditioning bullets", () => {
  it("renders the bullets under the SAME conditioning-<id> testid the modal used", () => {
    renderAbsorbed();
    // R2: conditioning primed the hypothesis, so it lives in that section.
    expand("hypothesis");
    const cond = screen.getByTestId("conditioning-iter-modal-full");
    expect(within(cond).getByText("carried bullet alpha")).toBeInTheDocument();
    expect(within(cond).getByText("carried bullet beta")).toBeInTheDocument();
  });

  it("no bullets → the honest placeholder", () => {
    render(
      <PipelineJourney
        item={iterItem(FULL_ITER.iteration_id)}
        journey={journeyOf(FULL_ITER)}
      />,
    );
    expand("hypothesis");
    expect(screen.getByTestId("journey-conditioning")).toHaveTextContent(
      "no conditioning bullets on this row",
    );
  });
});

describe("PipelineJourney — ABSORBED experiment extras", () => {
  it("renders the outcome fields inline and trials + results_path in the peek", () => {
    renderAbsorbed();
    expand("experiment");
    const outcome = screen.getByTestId("journey-outcome-present");
    expect(outcome).toHaveTextContent("exp003_vickrey_rediscovery");
    expect(outcome).toHaveTextContent("truthful_bid_fraction");
    expect(outcome).toHaveTextContent(/Verdict=YES\. Fraction of trials/);
    // R2: the trial count + results path are RAW EVIDENCE → the peek.
    fireEvent.click(screen.getByTestId("journey-peek-trials"));
    const peek = screen.getByTestId("peek-trials");
    expect(peek).toHaveTextContent("50");
    expect(peek).toHaveTextContent(
      "experiments/exp003_vickrey_rediscovery/results/summary.md",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    const chip = screen.getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("exp verdict=YES");
    expect(chip.className).toContain("emerald");
  });

  it("a multi-metric OBJECT value renders only its SCALAR entries (value.<k> rows)", () => {
    const multi: IterationRecord = {
      ...FULL_ABSORBED,
      iteration_id: "iter-multi-metric",
      experiment_outcome: {
        experiment_id: "exp-multi",
        metric: "bundle",
        value: { sub_a: 0.5, junk: { deep: true } } as unknown as number,
        summary: "Verdict=NO. mixed bundle.",
      },
    };
    render(
      <PipelineJourney item={iterItem(multi.iteration_id)} journey={journeyOf(multi)} />,
    );
    expand("experiment");
    const outcome = screen.getByTestId("journey-outcome-present");
    expect(outcome).toHaveTextContent("value.sub_a");
    expect(outcome).toHaveTextContent("0.5");
    expect(outcome).not.toHaveTextContent("value.junk");
    expect(outcome.innerHTML).not.toMatch(/object Object/);
    // A stated Verdict=NO is a FAILED station — never coerced to a pass.
    expect(screen.getByTestId("stepper-station-experiment")).toHaveAttribute(
      "data-status",
      "bad",
    );
  });
});

describe("PipelineJourney — ABSORBED links + lazy journal", () => {
  it("links the call chain from wrapper_call_ids[0] and the experiment page from the outcome", () => {
    const loaded = renderAbsorbed();
    const links = within(loaded).getByTestId("journey-links");
    const chain = within(links).getByTestId("journey-chain-link");
    expect(chain.getAttribute("href")).toBe(
      "/chain/req/c502cb94-46bb-42cf-8394-0ffbf2f2063e",
    );
    const exp = within(links).getByTestId("journey-experiment-link");
    expect(exp.getAttribute("href")).toBe(
      "/experiments/exp003_vickrey_rediscovery",
    );
  });

  it("the coordinator cycle whose dispatched_iteration_id matches gets a link; no match → no link", async () => {
    vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({
      cycles: [
        {
          timestamp: "2026-06-10T09:00:00Z",
          run_id: "coordinator_ab12cd34",
          agent: "coordinator",
          topic: "x",
          topic_source: "coordinator",
          plan: [],
          outcomes: [],
          dispatched_iteration_id: "iter-modal-full",
        },
        {
          timestamp: "2026-06-10T08:00:00Z",
          run_id: "coordinator_ffffffff",
          agent: "coordinator",
          topic: "y",
          topic_source: "coordinator",
          plan: [],
          outcomes: [],
          dispatched_iteration_id: "iter-other",
        },
      ],
    } as never);
    renderAbsorbed();
    const link = await screen.findByTestId("journey-cycle-link");
    expect(link).toHaveTextContent("coordinator_ab12cd34");
    // /cycles — the S3 route rename (the S2 "/coordinator for now" resolved).
    expect(link.getAttribute("href")).toBe("/cycles");
  });

  it("a failed cycle fetch (older backend / skew) silently drops the cycle link — never a red state", async () => {
    vi.spyOn(http, "getCoordinatorCycles").mockRejectedValue(
      new Error("404 not found"),
    );
    const c = watchConsole();
    renderAbsorbed();
    await waitFor(() => expect(http.getCoordinatorCycles).toHaveBeenCalled());
    expect(screen.queryByTestId("journey-cycle-link")).toBeNull();
    expect(screen.getByTestId("pipeline-journey")).not.toHaveTextContent(/404/);
    expect(c.error).not.toHaveBeenCalled();
  });

  it("the journal mounts LAZILY on disclosure open (no fetch before)", async () => {
    const journalSpy = vi.spyOn(http, "getJournalEntry").mockResolvedValue({
      iteration_id: "iter-modal-full",
      path: "journal/iterations/full.md",
      content: "# Journal\n\njourney journal body",
    });
    const loaded = renderAbsorbed();
    expect(journalSpy).not.toHaveBeenCalled();
    expect(within(loaded).queryByTestId("journal-scroll")).toBeNull();

    const details = within(loaded).getByTestId("journey-journal");
    // jsdom does not auto-fire toggle on summary click; set open + toggle.
    (details as HTMLDetailsElement).open = true;
    fireEvent(details, new Event("toggle", { bubbles: false }));
    await waitFor(() =>
      expect(within(loaded).getByTestId("journal-scroll")).toBeInTheDocument(),
    );
    expect(journalSpy).toHaveBeenCalledWith("iter-modal-full");
    await waitFor(() =>
      expect(
        within(loaded).getByText("journey journal body"),
      ).toBeInTheDocument(),
    );
  });

  it("a bare legacy row invents NO chain/experiment/cycle links", () => {
    const bare = {
      iteration_id: "iter-bare-legacy",
      started_at: "2026-05-01T10:00:00Z",
      ended_at: "2026-05-01T10:05:00Z",
      journal_entry_path: "journal/iterations/bare.md",
    } as unknown as IterationRecord;
    render(
      <PipelineJourney item={iterItem("iter-bare-legacy")} journey={journeyOf(bare)} />,
    );
    expect(screen.queryByTestId("journey-chain-link")).toBeNull();
    expect(screen.queryByTestId("journey-experiment-link")).toBeNull();
    expect(screen.queryByTestId("journey-cycle-link")).toBeNull();
  });
});

describe("PipelineJourney — ABSORBED sections degrade on garbled producer rows", () => {
  it("garbled fields in every absorbed section — no [object Object], no NaN, no crash", () => {
    const c = watchConsole();
    const garbled = {
      iteration_id: "iter-garbled-absorbed",
      started_at: "2026-06-10T10:00:00Z",
      ended_at: { seconds: 1 },
      seed: { topic: 42, source: ["x"] },
      hypothesis: { text: { nested: true }, candidates_considered: NaN },
      retrieval: {
        relevance: {
          relevance: NaN,
          low_confidence: true,
          reason: { r: 1 },
          topicality: {},
          category: 3,
          rule_fired: ["R9"],
        },
      },
      novelty: { class: "novel", novelty_axes: "garbage" },
      critique: {
        verdict: "undecidable",
        rationale: ["a"],
        skeptic_verdict: { v: "x" },
      },
      redteam: { verdict: "proceed", retries_used: NaN, confidence: Infinity },
      meta_review: { conditioning_bullets: "one string" },
      experiment_outcome: {
        experiment_id: 7,
        metric: { m: 1 },
        value: { sub_a: 0.5, junk: { deep: true } },
        summary: 12,
      },
      journal_entry_path: "journal/iterations/garbled.md",
    } as unknown as IterationRecord;
    const { container } = rtlRender(
      <MemoryRouter>
        <PipelineJourney
          item={iterItem("iter-garbled-absorbed")}
          journey={journeyOf(garbled)}
        />
      </MemoryRouter>,
    );
    // EVERY section open — otherwise the innerHTML sweep passes vacuously.
    expandAll();
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(container.innerHTML).not.toMatch(/NaN/);
    // The multi-metric object value renders only its SCALAR entries.
    const outcome = screen.getByTestId("journey-outcome-present");
    expect(outcome).toHaveTextContent("value.sub_a");
    expect(outcome).not.toHaveTextContent("value.junk");
    // Candidates line dropped (NaN), conditioning degraded to the placeholder.
    expect(screen.queryByTestId("journey-candidates")).toBeNull();
    expect(screen.getByTestId("journey-conditioning")).toHaveTextContent(
      "no conditioning bullets on this row",
    );
    expect(c.error).not.toHaveBeenCalled();
  });
});
