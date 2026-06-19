// PipelineJourney — the /todo cockpit's read-only JOURNEY view (slice FE2).
// These tests pin: (1) the PIPELINE RIBBON marks which of the 8 steps the row
// reached, with the experiment step ALWAYS greyed + Phase-2-labelled; (2) the
// JOURNEY blocks render read-only from an IterationRecord (hypothesis /
// retrieval+relevance / novelty / critic + contradicting-paper both branches /
// experiment-outcome present + Phase-2 placeholder); (3) BOTH item families —
// gate_verdict (item.id IS the iteration id) and finding_review (item.id is a
// finding id → getFindingDetail → source_iteration_id → getIterationJourney),
// via injection AND via self-fetch; (4) the D-052 advisory surfaces quiet
// (never amber); (5) DEGRADES on every malformed / absent / not-found shape
// without throwing or blanking.
//
// The `journey` / `detail` props are the test-injection overrides (mirror
// TutorPanel's `detail`): when provided the panel renders them WITHOUT a fetch,
// so the injection tests never touch the network. The self-fetch tests spy the
// named http exports (mirrors test_harden_TutorPanel) so jsdom's real `fetch` is
// never hit. Every IterationRecord / FindingDetail field is producer-owned and
// unvalidated — a legacy/partial/buggy row can hand a field a null, number,
// object, array, or NaN; the runtime must survive them (asText drops by typeof,
// no deref).
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PipelineJourney from "../src/components/todo/PipelineJourney";
import type {
  FindingDetail,
  HumanTodoItem,
  IterationJourneyResponse,
  IterationRecord,
} from "../src/types/schemas";
import * as http from "../src/api/http";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Cast helper — values illegal per the prop type but legal in the JSONL the
// producer actually writes; the runtime must survive them.
const bad = (v: unknown) => v as unknown as never;

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
// an experiment outcome (so the experiment/outcome steps light too).
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

describe("PipelineJourney — the RIBBON marks reached steps; experiments greyed Phase-2", () => {
  it("renders all 8 steps; the FULL iteration lights every non-Phase-2 step", () => {
    render(<PipelineJourney item={iterItem("iter-2026-06-14-003")} journey={journeyOf(FULL_ITER)} />);
    const ribbon = screen.getByTestId("pipeline-ribbon");
    for (const k of ["hypothesis", "retrieval", "relevance", "novelty", "critic", "experiments", "gate", "outcome"]) {
      expect(screen.getByTestId(`ribbon-step-${k}`)).toBeInTheDocument();
    }
    // Non-Phase-2 steps the FULL iteration reached are marked reached.
    for (const k of ["hypothesis", "retrieval", "relevance", "novelty", "critic", "gate"]) {
      expect(screen.getByTestId(`ribbon-step-${k}`)).toHaveAttribute("data-reached", "true");
    }
    // The experiment step is ALWAYS Phase-2-flagged and carries the label.
    const exp = screen.getByTestId("ribbon-step-experiments");
    expect(exp).toHaveAttribute("data-phase2", "true");
    expect(exp).toHaveTextContent(/phase 2/i);
    expect(ribbon).toHaveTextContent(/hypothesis/i);
  });

  it("an early-halted iteration greys the steps it never reached", () => {
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
    expect(screen.getByTestId("ribbon-step-hypothesis")).toHaveAttribute("data-reached", "true");
    expect(screen.getByTestId("ribbon-step-retrieval")).toHaveAttribute("data-reached", "true");
    expect(screen.getByTestId("ribbon-step-relevance")).toHaveAttribute("data-reached", "false");
    expect(screen.getByTestId("ribbon-step-novelty")).toHaveAttribute("data-reached", "false");
    expect(screen.getByTestId("ribbon-step-critic")).toHaveAttribute("data-reached", "false");
    expect(screen.getByTestId("ribbon-step-gate")).toHaveAttribute("data-reached", "false");
  });
});

describe("PipelineJourney — JOURNEY blocks render read-only from the iteration record", () => {
  it("renders hypothesis, retrieval (k + neighbors) + relevance, novelty, critic", () => {
    render(<PipelineJourney item={iterItem("iter-2026-06-14-003")} journey={journeyOf(FULL_ITER)} />);
    const panel = screen.getByTestId("pipeline-journey");

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
    // critic verdict + rationale
    expect(screen.getByTestId("journey-critic")).toHaveTextContent("survives");
    expect(panel.textContent ?? "").not.toContain("[object Object]");
  });

  it("contradicting paper: a non-null id renders 'contradicted by <id>'", () => {
    const withContra: IterationRecord = {
      ...FULL_ITER,
      critique: { verdict: "restated", rationale: "a prior paper says this.", contradicting_paper_id: "arxiv-2401.00001" },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withContra)} />);
    const contra = screen.getByTestId("journey-contradicting-paper");
    expect(contra).toHaveTextContent(/contradicted by/i);
    expect(contra).toHaveTextContent("arxiv-2401.00001");
  });

  it("contradicting paper: a null id renders 'uncontradicted'", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    expect(screen.getByTestId("journey-contradicting-paper")).toHaveTextContent(/uncontradicted/i);
  });

  it("experiment-outcome PRESENT renders the bridge fields; an HONEST stage label says experiment-bridged", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
    const out = screen.getByTestId("journey-outcome-present");
    expect(out).toHaveTextContent("exp004");
    expect(out).toHaveTextContent("effect_size");
    expect(out).toHaveTextContent("0.31");
    expect(screen.queryByTestId("journey-outcome-placeholder")).toBeNull();
    expect(screen.getByTestId("journey-stage-label")).toHaveTextContent(/experiment-bridged/i);
  });

  it("experiment-outcome ABSENT renders the Phase-2 placeholder + a literature-stage label", () => {
    const litStage: IterationRecord = { ...FULL_ITER, experiment_outcome: null };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(litStage)} />);
    expect(screen.getByTestId("journey-outcome-placeholder")).toHaveTextContent(
      /literature-stage — not experimentally tested \(Phase 2\)/i,
    );
    expect(screen.queryByTestId("journey-outcome-present")).toBeNull();
    expect(screen.getByTestId("journey-stage-label")).toHaveTextContent(/literature-stage/i);
    // the experiment / outcome ribbon steps are NOT lit when no outcome exists
    expect(screen.getByTestId("ribbon-step-outcome")).toHaveAttribute("data-reached", "false");
  });
});

describe("PipelineJourney — the D-052 topicality advisory surfaces QUIET, never amber", () => {
  it("renders the raw advisory value when present, with NO amber low-evidence styling", () => {
    const withAdvisory: IterationRecord = {
      ...FULL_ITER,
      retrieval: {
        ...FULL_ITER.retrieval!,
        relevance: { ...FULL_ITER.retrieval!.relevance!, topicality_advisory: "off" },
      },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(withAdvisory)} />);
    const adv = screen.getByTestId("journey-topicality-advisory");
    expect(adv).toHaveTextContent(/non-gating/i);
    expect(adv).toHaveTextContent("off");
    // NEVER amber — the advisory is non-gating, dark by default; it must not wear
    // the low-evidence alarm tone.
    expect(adv.className).not.toMatch(/amber/);
  });

  it("renders NO advisory line when the field is absent (the normal row)", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(FULL_ITER)} />);
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

  it("a finding whose detail FAILS to load → unavailable, ribbon still shown, no throw", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockRejectedValue(new Error("network"));
    const jSpy = vi.spyOn(http, "getIterationJourney").mockResolvedValue(journeyOf(FULL_ITER));
    render(<PipelineJourney item={findingItem("sf-x")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    // no source iteration was ever resolved → the journey endpoint is never hit
    expect(jSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("pipeline-ribbon")).toBeInTheDocument();
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

  it("a REJECTED journey fetch → unavailable, ribbon still shown, no console error", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getIterationJourney").mockRejectedValue(new Error("down"));
    render(<PipelineJourney item={iterItem("iter-x")} />);
    await waitFor(() => expect(screen.getByTestId("journey-unavailable")).toBeInTheDocument());
    expect(screen.getByTestId("pipeline-ribbon")).toBeInTheDocument();
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
  it("found:false journey → 'journey unavailable', ribbon present, no overview", () => {
    const c = watchConsole();
    render(
      <PipelineJourney
        item={iterItem("iter-nf")}
        journey={{ found: false, iteration_id: "iter-nf", iteration: null }}
      />,
    );
    expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
    expect(screen.getByTestId("journey-unavailable")).toHaveTextContent(/journey unavailable/i);
    expect(screen.getByTestId("pipeline-ribbon")).toBeInTheDocument();
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
    const panel = screen.getByTestId("pipeline-journey");
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // the one legal scalar neighbor ({id:"ok-neighbor"}) survives the preview
    expect(screen.getByTestId("journey-neighbors")).toHaveTextContent("ok-neighbor");
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
    const text = screen.getByTestId("pipeline-journey").textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity|Symbol|\d+n\b/);
    // a non-string contradicting_paper_id drops → uncontradicted (never a leak)
    expect(screen.getByTestId("journey-contradicting-paper")).toHaveTextContent(/uncontradicted/i);
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
    expect(screen.queryByTestId("journey-neighbors")).toBeNull();
    expect(screen.queryByTestId("journey-relevance")).toBeNull();
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
    expect(screen.getByTestId("pipeline-ribbon")).toBeInTheDocument();
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
    const adv = screen.getByTestId("journey-topicality-advisory");
    expect(adv.className).not.toMatch(/amber|red|orange|yellow/);
    expect(adv.innerHTML).not.toMatch(/amber|red|orange|yellow|low-evidence/);
  });
});
