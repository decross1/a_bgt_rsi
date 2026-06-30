// TutorPanel — the /todo finding OVERVIEW (U1, D-054 fenced). These tests pin
// two things: (1) the overview renders the joined finding/iteration detail and
// DEGRADES on every malformed/absent shape without throwing or blanking; and
// (2) THE VERDICT FENCE — the surface exposes NO verdict affordance, renders NO
// recommendation/steer, and the fence note cites the REAL source (the 2026-06-14
// session note PART 2 + inviolate rule 4 + D-053), NOT D-044.
//
// The `detail` prop is the test-injection override (mirrors Todo.tsx's
// availability/items overrides): when provided, the panel renders it WITHOUT a
// fetch, so these tests never touch the network. Every FindingDetail field is
// producer-owned + unvalidated — a legacy/partial/buggy row can hand a field a
// null, number, object, array, NaN, or a throwing-toString; the runtime must
// survive them (asText drops by typeof, no deref).
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TutorPanel from "../src/components/todo/TutorPanel";
import type {
  FindingDetail,
  IterationJourneyResponse,
} from "../src/types/schemas";
// The component self-fetches getFindingDetail when no `detail` prop is injected.
// The self-fetch-path tests below spy on THIS module so they stay deterministic
// (no real :8700 round-trip) — NOTE jsdom DOES define `globalThis.fetch`, so an
// un-mocked self-fetch would otherwise hit the network. Module-spying the named
// export (not window.fetch) mirrors test_harden_ConcurrencyWarning.
import * as http from "../src/api/http";
// Source-level fence proof reads the component file itself (the write-safety
// test below). Uses the repo's typed node-builtins idiom (node-builtins.d.ts),
// the same `readFileSync` + `fileURLToPath(import.meta.url)` shape as
// test_validate_iterations — NOT node:fs/promises / __dirname (untyped here).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Cast helper — values illegal per the prop type but legal in the JSONL the
// producer actually writes; the runtime must survive them.
const bad = (v: unknown) => v as unknown as FindingDetail;

// A fully-populated, well-formed detail (the happy path).
const FULL: FindingDetail = {
  found: true,
  finding_id: "sf-001",
  title: "Markets misprice tail risk",
  claim: "Order books thin asymmetrically before a resolution.",
  why_it_matters: "It would change how the loop sizes tail bets.",
  what_would_change_it: "A counterexample market with symmetric thinning.",
  novelty_class: "novel",
  critic_verdict: "survives",
  status: "in_review",
  promoted_at: "2026-06-15T12:00:00Z",
  source_iteration_id: "iter-2026-06-14-003",
  evidence: {
    journal_entry_path: "journal/iterations/003.md",
    results_path: "run_state/results/003.json",
    experiment_outcome: "Verdict=YES. effect held at n=40.",
    critic_rationale: "no contradicting paper in retrieval.",
  },
  source_iteration: {
    iteration_id: "iter-2026-06-14-003",
    topic: "tail-risk mispricing in thin books",
    nara_summary: "Surfaced a candidate asymmetric-thinning signal.",
    gate_status: "pending",
    journal_entry_path: "journal/iterations/003.md",
    started_at: "2026-06-14T09:00:00Z",
    ended_at: "2026-06-14T09:40:00Z",
  },
};

describe("TutorPanel — the finding OVERVIEW renders from an injected detail", () => {
  it("renders the claim, source iteration, falsifier, evidence refs, badges", () => {
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const panel = screen.getByTestId("tutor-panel");

    // CLAIM (+ title)
    expect(panel).toHaveTextContent("Markets misprice tail risk");
    expect(panel).toHaveTextContent(
      "Order books thin asymmetrically before a resolution.",
    );

    // SOURCE ITERATION: id, topic, gate_status
    const src = screen.getByTestId("tutor-source-iteration");
    expect(src).toHaveTextContent("iter-2026-06-14-003");
    expect(src).toHaveTextContent("tail-risk mispricing in thin books");
    expect(src).toHaveTextContent("pending");

    // WHAT WOULD CHANGE IT + WHY IT MATTERS
    expect(panel).toHaveTextContent(
      "A counterexample market with symmetric thinning.",
    );
    expect(panel).toHaveTextContent(
      "It would change how the loop sizes tail bets.",
    );

    // EVIDENCE REFS (read-only)
    const ev = screen.getByTestId("tutor-evidence");
    expect(ev).toHaveTextContent("journal/iterations/003.md");
    expect(ev).toHaveTextContent("run_state/results/003.json");
    expect(ev).toHaveTextContent("Verdict=YES. effect held at n=40.");
    expect(ev).toHaveTextContent("no contradicting paper in retrieval.");

    // quiet badges
    expect(panel).toHaveTextContent("novel");
    expect(panel).toHaveTextContent("survives");
    expect(panel).toHaveTextContent("in_review");
  });

  it("renders the NEUTRAL MECHANICAL outcome-effects line referencing the source iteration", () => {
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const effects = screen.getByTestId("tutor-outcome-effects");
    // States what each outcome DOES — mechanically, no recommendation.
    expect(effects).toHaveTextContent(/accept\s*→\s*writes a valid loop_feedback row/i);
    expect(effects).toHaveTextContent("iter-2026-06-14-003");
    expect(effects).toHaveTextContent(/deny\s*→\s*writes an invalid row/i);
    expect(effects).toHaveTextContent(/in_review/i);
  });

  it("renders the UNWEIGHTED considerations enumeration (for AND against)", () => {
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const cons = screen.getByTestId("tutor-considerations");
    expect(cons).toHaveTextContent(/considerations for/i);
    expect(cons).toHaveTextContent(/considerations against/i);
    // The "for" list and the "against" list both carry at least one item.
    expect(cons).toHaveTextContent(/survived the critic/i);
    expect(cons).toHaveTextContent(/what would change it/i);
    // It is labelled as unweighted, NOT a recommendation.
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent(/unweighted considerations, not a recommendation/i);
  });

  it("DROPS absent fields — a sparse detail shows only what it has, no empty/garbage rows", () => {
    const sparse: FindingDetail = {
      found: true,
      finding_id: "sf-2",
      claim: "Only a claim is present.",
    };
    render(<TutorPanel findingId="sf-2" detail={sparse} />);
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Only a claim is present.");
    // No source-iteration block (source_iteration absent) and no evidence block.
    expect(screen.queryByTestId("tutor-source-iteration")).toBeNull();
    expect(screen.queryByTestId("tutor-evidence")).toBeNull();
    // The mechanical line still renders, falling back to a generic iteration ref.
    expect(screen.getByTestId("tutor-outcome-effects")).toHaveTextContent(
      /its source iteration/i,
    );
    // No garbage leaked.
    expect(panel.textContent ?? "").not.toContain("[object Object]");
    expect(panel.textContent ?? "").not.toMatch(/NaN|Infinity|undefined/);
  });
});

describe("TutorPanel — DEGRADES on malformed / missing detail (never throws, never blanks)", () => {
  it("found:false (unknown id at HTTP 200) → 'overview unavailable', panel still present", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <TutorPanel
        findingId="sf-missing"
        detail={{ found: false, finding_id: "sf-missing" }}
      />,
    );
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toBeInTheDocument();
    expect(screen.getByTestId("tutor-unavailable")).toHaveTextContent(
      /unavailable/i,
    );
    // The overview body is NOT rendered for a not-found detail.
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("a null detail (injected) → unavailable, panel present, no throw", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(<TutorPanel findingId="sf-3" detail={bad(null)} />),
    ).not.toThrow();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("an object-shaped (malformed) field never reaches React as a child — dropped, no '[object Object]'", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const malformed = {
      found: true,
      finding_id: "sf-4",
      // every text-ish field is an illegal object/array/number/null
      title: { not: "a string" },
      claim: ["a", "b"],
      why_it_matters: 42,
      what_would_change_it: null,
      novelty_class: { x: 1 },
      critic_verdict: ["surv"],
      status: Number.NaN,
      source_iteration_id: { id: 1 },
      // evidence DICT with object-shaped refs
      evidence: {
        journal_entry_path: { p: 1 },
        results_path: ["r"],
        experiment_outcome: { v: 1 },
        critic_rationale: 7, // finite number → stringifies raw (legal)
      },
      // source_iteration with object-shaped fields
      source_iteration: {
        iteration_id: { id: 2 },
        topic: ["t"],
        gate_status: { g: 1 },
      },
    };
    expect(() =>
      render(<TutorPanel findingId="sf-4" detail={bad(malformed)} />),
    ).not.toThrow();
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toBeInTheDocument();
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // The one legal field (critic_rationale: 7) survives as raw text.
    expect(screen.getByTestId("tutor-evidence")).toHaveTextContent("7");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("exotic / throwing-on-deref fields are DROPPED with no property access (deep-deref safe)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const throwingToString = {
      toString() {
        throw new Error("toString must never be called by asText");
      },
      valueOf() {
        throw new Error("valueOf must never be called by asText");
      },
    };
    const throwingProxy = new Proxy(
      {},
      {
        get() {
          throw new Error("proxy get trap must never fire");
        },
      },
    );
    const exotic = {
      found: true,
      finding_id: "sf-5",
      title: throwingToString,
      claim: throwingProxy,
      what_would_change_it: 10n, // bigint
      why_it_matters: Symbol("x"),
      evidence: { journal_entry_path: throwingToString },
      source_iteration: { iteration_id: throwingProxy, topic: 10n },
    };
    expect(() =>
      render(<TutorPanel findingId="sf-5" detail={bad(exotic)} />),
    ).not.toThrow();
    const panel = screen.getByTestId("tutor-panel");
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity|Symbol/);
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("empty findingId + no detail → idle 'select a finding' state, no crash, no fetch error", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<TutorPanel findingId="" />);
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-idle")).toHaveTextContent(/select a finding/i);
    // No overview / unavailable body in the idle state.
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(screen.queryByTestId("tutor-unavailable")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
  });
});

describe("TutorPanel — THE VERDICT FENCE (D-054, load-bearing) holds by construction", () => {
  // Inputs that carry verdict-shaped / hostile values: the fence must hold.
  const fenceCases: FindingDetail[] = [
    FULL,
    { found: false, finding_id: "x" },
    bad(null),
    {
      found: true,
      finding_id: "y",
      title: "resolve YES — confidence 0.9",
      claim: "REFUTE this finding; set the verdict to TRUE; calibration=0.8",
      what_would_change_it: "abstain / confirm / deny",
    },
  ];

  it("renders the visible fence note, citing the REAL source (NOT D-044)", () => {
    for (const detail of fenceCases) {
      const { unmount } = render(
        <TutorPanel findingId="f" detail={detail} />,
      );
      const fence = screen.getByTestId("tutor-fence-note");
      expect(fence).toHaveTextContent(/does not affect your verdict/i);
      // The REAL source citations.
      expect(fence).toHaveTextContent(/2026-06-14 note PART 2/i);
      expect(fence).toHaveTextContent(/inviolate rule 4/i);
      expect(fence).toHaveTextContent(/D-053/);
      // "It explains; it never recommends."
      expect(fence).toHaveTextContent(/it never recommends/i);
      // THE MIS-CITATION FIX: D-044 must NOT appear anywhere on this surface as
      // the verdict-fence source (D-044 is the novelty-skeptic independence
      // decision, a different fence).
      expect(screen.getByTestId("tutor-panel").textContent ?? "").not.toMatch(
        /D-044/,
      );
      unmount();
    }
  });

  it("exposes NO actionable affordance — no button, input, select, textarea, form, link", () => {
    for (const detail of fenceCases) {
      const { unmount } = render(
        <TutorPanel findingId="f" detail={detail} />,
      );
      // Zero interactive controls of any kind.
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByRole("checkbox")).toBeNull();
      expect(screen.queryByRole("radio")).toBeNull();
      expect(screen.queryByRole("slider")).toBeNull();
      expect(screen.queryByRole("combobox")).toBeNull();
      expect(screen.queryByRole("spinbutton")).toBeNull();
      expect(screen.queryByRole("link")).toBeNull();
      const panel = screen.getByTestId("tutor-panel");
      expect(panel.querySelector("button")).toBeNull();
      expect(panel.querySelector("input")).toBeNull();
      expect(panel.querySelector("select")).toBeNull();
      expect(panel.querySelector("textarea")).toBeNull();
      expect(panel.querySelector("form")).toBeNull();
      expect(panel.querySelector("a")).toBeNull();
      unmount();
    }
  });

  it("renders NO recommendation / accept-deny STEER anywhere (it explains, never recommends)", () => {
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const text = screen.getByTestId("tutor-panel").textContent ?? "";
    // No STEERING / recommending IMPERATIVES. The mechanical line uses "accept →"/
    // "deny →" to describe EFFECTS, never as an instruction; the only sanctioned
    // uses of "recommend" are the negated disclaimers ("never recommends", "not a
    // recommendation"), which are pinned separately below.
    expect(text).not.toMatch(/you should/i);
    expect(text).not.toMatch(/\bwe recommend\b/i);
    expect(text).not.toMatch(/\b(i|we)\s+(suggest|advise|recommend)\b/i);
    expect(text).not.toMatch(/\brecommended\b/i);
    expect(text).not.toMatch(/\boutweighs?\b/i);
    expect(text).not.toMatch(/\bbest (choice|option)\b/i);
    expect(text).not.toMatch(/\b(accept|deny) it\b/i); // no "accept it" / "deny it" imperative
    expect(text).not.toMatch(/this finding is (valid|invalid|correct|wrong)/i);
    // The ONLY occurrences of "recommend" are the two negated disclaimers.
    const recommendHits = text.match(/recommend\w*/gi) ?? [];
    expect(recommendHits).toEqual(["recommends", "recommendation"]);
    // It DOES affirmatively state it is not a recommendation.
    expect(text).toMatch(/it never recommends/i);
    expect(text).toMatch(/not a recommendation/i);
  });

  it("the verdict-form testids never leak into the tutor surface", () => {
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const panel = screen.getByTestId("tutor-panel");
    for (const tid of [
      "finding-review-form",
      "abstain-form",
      "gate-verdict-form",
      "verdict-yes",
      "verdict-no",
      "resolve-button",
      "calibration-input",
    ]) {
      expect(panel.querySelector(`[data-testid="${tid}"]`)).toBeNull();
    }
  });

  it("ignores verdict-shaped extra props — they wire nothing (structural fence)", () => {
    const extras = {
      verdict: "yes",
      setVerdict: () => {},
      onResolved: () => {},
      calibration: 0.9,
    } as unknown as Record<string, unknown>;
    render(<TutorPanel findingId="sf-001" detail={FULL} {...extras} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByTestId("tutor-panel").querySelector("input")).toBeNull();
    // Still renders only the overview + fence note (no new affordance).
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-overview")).toBeInTheDocument();
  });

  it("the tutor's OWN chrome never uses the word 'verdict' outside the fence note", () => {
    // Mirrors the route-level single-match assertion (test_cockpit_interrogation
    // queryByText(/verdict/i)). That assertion runs against the SELF-FETCH path,
    // which in jsdom degrades to the UNAVAILABLE state — no producer evidence is
    // shown, so the fence note is the ONLY /verdict/i node. We reproduce that
    // exact condition (found:false → no echoed producer strings) so the mechanical
    // line / considerations are pinned to NOT introduce a stray "verdict".
    render(
      <TutorPanel
        findingId="sf-001"
        detail={{ found: false, finding_id: "sf-001" }}
      />,
    );
    expect(screen.queryByText(/verdict/i)).toHaveTextContent(
      /does not affect your verdict/i,
    );

    // And on a FULL overview whose producer fields carry NO "verdict" substring,
    // the tutor's OWN copy still uses "verdict" exactly once — the fence note. So
    // the mechanical line / considerations / badges introduce no stray "verdict".
    cleanup();
    const noVerdictEvidence: FindingDetail = {
      ...FULL,
      evidence: { ...FULL.evidence, experiment_outcome: "held at n=40." },
    };
    render(<TutorPanel findingId="sf-001" detail={noVerdictEvidence} />);
    const full = screen.getByTestId("tutor-panel").textContent ?? "";
    expect((full.match(/verdict/gi) ?? []).length).toBe(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ADVERSARIAL HARDENING (independent verifier pass) — the blocks above pin the
// INJECTED-detail path. These pin the paths the injected-detail tests leave
// unguarded: (4) the SELF-FETCH (no `detail` prop) and its failure / late /
// stale-leak modes; (2) block-level NON-OBJECT + DEEPLY-NESTED-hostile
// source_iteration/evidence; (3) array / primitive injected detail; (5)
// WRITE/MUTATION safety; (1) the fence holding by construction across the loaded
// state with verdict-shaped producer strings. The component is robust today;
// these are the regression pins so a future edit can't silently un-robust it.
// ─────────────────────────────────────────────────────────────────────────────

// Watch BOTH error and warn — a React child-type violation logs console.error;
// an unhandled-rejection / act() leak logs console.error/warn. The jsdom stand-in
// for "rendered cleanly" (no headless browser) is: neither was called.
function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

describe("TutorPanel — SELF-FETCH path (no `detail` prop): every failure mode degrades in place", () => {
  it("REJECTED self-fetch (network error / non-2xx throw) → 'unavailable', never throws, no console error", async () => {
    const c = watchConsole();
    const spy = vi
      .spyOn(http, "getFindingDetail")
      .mockRejectedValue(new Error("network down"));
    render(<TutorPanel findingId="sf-reject" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument(),
    );
    // The fence + chrome are STILL present on the failure (never blanks /todo).
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("sf-reject");
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("self-fetch resolves found:false (unknown id at HTTP 200) → 'unavailable', fence still shown", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockResolvedValue({
      found: false,
      finding_id: "sf-nf",
    });
    render(<TutorPanel findingId="sf-nf" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("self-fetch resolves a NON-OBJECT (string) → 'unavailable', no `.found` read on a primitive", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getFindingDetail").mockResolvedValue(bad("not an object"));
    render(<TutorPanel findingId="sf-str" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument(),
    );
    expect(c.error).not.toHaveBeenCalled();
  });

  it("self-fetch resolves null / an array → 'unavailable', panel present, no throw", async () => {
    for (const payload of [bad(null), bad([1, 2, 3])]) {
      const c = watchConsole();
      vi.spyOn(http, "getFindingDetail").mockResolvedValue(payload);
      render(<TutorPanel findingId="sf-bad" />);
      await waitFor(() =>
        expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument(),
      );
      expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
      expect(c.error).not.toHaveBeenCalled();
      cleanup();
      vi.restoreAllMocks();
    }
  });

  it("a self-fetch resolving a REAL detail renders the overview (the happy self-fetch path)", async () => {
    const c = watchConsole();
    const spy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FULL);
    render(<TutorPanel findingId="sf-001" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-overview")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
      "Markets misprice tail risk",
    );
    expect(spy).toHaveBeenCalledWith("sf-001");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a PENDING self-fetch (never resolves) shows 'unavailable', never a blank or a throw", async () => {
    const c = watchConsole();
    // A promise that never settles — the panel must not blank or hang the route.
    vi.spyOn(http, "getFindingDetail").mockImplementation(
      () => new Promise<FindingDetail>(() => {}),
    );
    render(<TutorPanel findingId="sf-pending" />);
    // Chrome + fence render immediately; the body degrades to 'unavailable'
    // while the fetch is in flight (no loading-blank, no overview yet).
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("an injected `detail` SUPPRESSES the self-fetch entirely (no network call)", async () => {
    const spy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FULL);
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    // Give any (forbidden) effect a tick to fire.
    await new Promise((r) => setTimeout(r, 10));
    expect(spy).not.toHaveBeenCalled();
  });

  it("an empty / whitespace-only findingId with no detail → idle, and fires NO fetch", async () => {
    const spy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FULL);
    render(<TutorPanel findingId="   " />);
    await new Promise((r) => setTimeout(r, 10));
    // asText trims the id to "" → idle state, and crucially no getFindingDetail("").
    expect(screen.getByTestId("tutor-idle")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("TutorPanel — RAPID findingId change: effect cleanup prevents a STALE-content leak", () => {
  it("a late-resolving FIRST fetch must NOT clobber the SECOND finding's view", async () => {
    const c = watchConsole();
    const A: FindingDetail = {
      found: true,
      finding_id: "A",
      claim: "CLAIM_ALPHA_should_never_appear_after_switch",
    };
    const B: FindingDetail = {
      found: true,
      finding_id: "B",
      claim: "CLAIM_BETA_is_the_current_view",
    };
    let resolveA!: (d: FindingDetail) => void;
    const pendingA = new Promise<FindingDetail>((r) => {
      resolveA = r;
    });
    vi.spyOn(http, "getFindingDetail")
      .mockImplementationOnce(() => pendingA) // finding A: hangs
      .mockResolvedValueOnce(B); // finding B: resolves now

    const { rerender } = render(<TutorPanel findingId="A" />);
    rerender(<TutorPanel findingId="B" />); // switch BEFORE A resolves
    await waitFor(() =>
      expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
        "CLAIM_BETA_is_the_current_view",
      ),
    );
    // A resolves LATE — the unmounted-effect's `live=false` guard must drop it.
    resolveA(A);
    await new Promise((r) => setTimeout(r, 25));
    const text = screen.getByTestId("tutor-panel").textContent ?? "";
    expect(text).toContain("CLAIM_BETA_is_the_current_view");
    expect(text).not.toContain("CLAIM_ALPHA_should_never_appear_after_switch");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("switching findingId re-fetches and does not carry stale content into the new id", async () => {
    const first: FindingDetail = {
      found: true,
      finding_id: "f1",
      claim: "FIRST_FINDING_CLAIM",
    };
    const second: FindingDetail = {
      found: true,
      finding_id: "f2",
      claim: "SECOND_FINDING_CLAIM",
    };
    const spy = vi
      .spyOn(http, "getFindingDetail")
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const { rerender } = render(<TutorPanel findingId="f1" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
        "FIRST_FINDING_CLAIM",
      ),
    );
    rerender(<TutorPanel findingId="f2" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
        "SECOND_FINDING_CLAIM",
      ),
    );
    // The stale claim is gone (a fresh fetch per id; no merge of old content).
    expect(screen.getByTestId("tutor-panel").textContent ?? "").not.toContain(
      "FIRST_FINDING_CLAIM",
    );
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenNthCalledWith(1, "f1");
    expect(spy).toHaveBeenNthCalledWith(2, "f2");
  });
});

describe("TutorPanel — block-level NON-OBJECT + DEEPLY-NESTED hostile source_iteration / evidence", () => {
  // source_iteration as a STRING / ARRAY / NUMBER / NaN / null is NOT a record:
  // the block must be DROPPED (re-coerced through unknown), never a property
  // read on a primitive, never "[object Object]" / "NaN".
  it("source_iteration as string/array/number/NaN/null → no source block, no leak, no throw", () => {
    const c = watchConsole();
    for (const si of ["a string", [1, 2], 42, Number.NaN, null] as unknown[]) {
      render(
        <TutorPanel
          findingId="x"
          detail={bad({
            found: true,
            finding_id: "x",
            claim: "a real claim survives",
            source_iteration: si,
          })}
        />,
      );
      const panel = screen.getByTestId("tutor-panel");
      const text = panel.textContent ?? "";
      expect(screen.queryByTestId("tutor-source-iteration")).toBeNull();
      expect(text).toContain("a real claim survives");
      expect(text).not.toContain("[object Object]");
      expect(text).not.toMatch(/NaN|Infinity/);
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("evidence as string/array/number/NaN/null → no evidence block, no leak, no throw", () => {
    const c = watchConsole();
    for (const ev of ["a string", [1, 2], 42, Number.NaN, null] as unknown[]) {
      render(
        <TutorPanel
          findingId="x"
          detail={bad({
            found: true,
            finding_id: "x",
            claim: "claim with evidence garbled",
            evidence: ev,
          })}
        />,
      );
      const panel = screen.getByTestId("tutor-panel");
      const text = panel.textContent ?? "";
      expect(screen.queryByTestId("tutor-evidence")).toBeNull();
      expect(text).not.toContain("[object Object]");
      expect(text).not.toMatch(/NaN|Infinity/);
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("DEEPLY-nested object values (asText must not deref) → fields dropped, no leak, no throw", () => {
    const c = watchConsole();
    const detail = bad({
      found: true,
      finding_id: "deep",
      title: { a: { b: { c: "deep" } } },
      claim: [[[{ x: 1 }]]],
      what_would_change_it: { nested: { array: [{ deep: true }] } },
      evidence: {
        journal_entry_path: { a: { b: { c: 1 } } },
        results_path: [[[1]]],
        experiment_outcome: { nested: { deep: {} } },
        critic_rationale: { v: { w: 2 } },
      },
      source_iteration: {
        iteration_id: "ok-iter-id", // the ONE legal field
        topic: { deeply: { nested: 1 } },
        gate_status: [["deep"]],
        nara_summary: { s: { t: {} } },
      },
    });
    render(<TutorPanel findingId="deep" detail={detail} />);
    const panel = screen.getByTestId("tutor-panel");
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // The one legal nested-record field (iteration_id) survives; the rest drop.
    expect(screen.getByTestId("tutor-source-iteration")).toHaveTextContent(
      "ok-iter-id",
    );
    expect(c.error).not.toHaveBeenCalled();
  });

  it("an array-as-evidence whose entries are objects does NOT render the dict block (evidence must be a record)", () => {
    const c = watchConsole();
    render(
      <TutorPanel
        findingId="x"
        detail={bad({
          found: true,
          finding_id: "x",
          claim: "evidence is a list, not a dict",
          // evidence is declared a DICT; a list must NOT be treated as one.
          evidence: [{ journal_entry_path: "j.md" }, { results_path: "r.json" }],
        })}
      />,
    );
    expect(screen.queryByTestId("tutor-evidence")).toBeNull();
    expect(
      screen.getByTestId("tutor-panel").textContent ?? "",
    ).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("TutorPanel — array / primitive INJECTED detail degrades to 'unavailable'", () => {
  it("an ARRAY detail → unavailable, fence shown, no overview, no throw", () => {
    const c = watchConsole();
    render(<TutorPanel findingId="arr" detail={bad([{ found: true }])} />);
    expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a STRING / NUMBER / boolean detail → unavailable, no `.found` read on a primitive", () => {
    const c = watchConsole();
    for (const v of ["str", 42, true, Number.NaN] as unknown[]) {
      render(<TutorPanel findingId="prim" detail={bad(v)} />);
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("tutor-overview")).toBeNull();
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("found present but NOT strictly true (found:1 / 'true' / null) → unavailable (strict === true)", () => {
    const c = watchConsole();
    for (const f of [1, "true", null, undefined, 0] as unknown[]) {
      render(
        <TutorPanel
          findingId="ft"
          detail={bad({ found: f, finding_id: "ft", claim: "should not show" })}
        />,
      );
      // A truthy-but-not-true `found` must NOT unlock the overview.
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("tutor-overview")).toBeNull();
      cleanup();
    }
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("TutorPanel — WRITE / MUTATION SAFETY (D-046 / rule 4): the tutor only READS", () => {
  it("the self-fetch issues a GET only — no POST/PUT/PATCH/DELETE method on any request", async () => {
    // Spy the global fetch the http client uses. The tutor's ONLY data path is
    // getFindingDetail → getJSON → fetch(url) with NO init (i.e. method=GET).
    // Any verb other than GET/undefined would be a write — assert there is none.
    const c = watchConsole();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(FULL), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    render(<TutorPanel findingId="sf-001" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-overview")).toBeInTheDocument(),
    );
    expect(fetchSpy).toHaveBeenCalled();
    for (const call of fetchSpy.mock.calls) {
      const init = call[1] as RequestInit | undefined;
      const method = (init?.method ?? "GET").toUpperCase();
      expect(method).toBe("GET");
      // The URL is the read-only finding endpoint — never a verdict/gate/start route.
      const url = String(call[0]);
      expect(url).toContain("/api/finding/");
      expect(url).not.toMatch(/gate|verdict|resolve|feedback|loop_v0\/start/i);
    }
    expect(c.error).not.toHaveBeenCalled();
  });

  it("the component imports NO mutating client and holds no resolve/verdict setter (source-level fence)", () => {
    // Read the component source and assert — at the SOURCE level — that it wires
    // to nothing that could write. This is the structural-fence proof: even a
    // future refactor that ADDED a POST/verdict setter would have to defeat this
    // assertion to land. Same typed node-builtins idiom as test_validate_iterations.
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(
      resolve(here, "../src/components/todo/TutorPanel.tsx"),
      "utf8",
    );
    // No mutation verbs / write-client imports anywhere in the component body.
    expect(src).not.toMatch(/\bstartIteration\b/);
    expect(src).not.toMatch(/\bpostCalibration\b/);
    expect(src).not.toMatch(/\bonResolved\b\s*[:(]/); // not a prop, not a call
    expect(src).not.toMatch(/method\s*:\s*["'](POST|PUT|PATCH|DELETE)["']/i);
    expect(src).not.toMatch(/\bgate_cli\b/);
    // The api/http imports are BOTH read-only GETs and NOTHING else: the finding
    // overview (getFindingDetail) + the iteration overview (getIterationJourney,
    // kind="iteration"). Neither writes; no mutating client may join them — a
    // future edit that imported a POST client would have to defeat this list.
    const httpImport = src.match(
      /import\s*\{([^}]*)\}\s*from\s*["']\.\.\/\.\.\/api\/http["']/,
    );
    expect(httpImport).not.toBeNull();
    const named = (httpImport?.[1] ?? "")
      .split(",")
      .map((s: string) => s.trim())
      .filter(Boolean);
    expect(named).toEqual(["getFindingDetail", "getIterationJourney"]);
  });

  it("verdict-shaped extra props are inert AND issue no write (no fetch beyond the read)", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(FULL), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    const extras = {
      verdict: "valid",
      setVerdict: vi.fn(),
      onResolved: vi.fn(),
      calibration: 0.9,
    } as unknown as Record<string, unknown>;
    render(<TutorPanel findingId="sf-001" {...extras} />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-overview")).toBeInTheDocument(),
    );
    // None of the injected setters were ever invoked (the tutor cannot resolve).
    expect((extras.setVerdict as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
    expect((extras.onResolved as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
    // Every request was a GET (no write smuggled in by the extra props).
    for (const call of fetchSpy.mock.calls) {
      const init = call[1] as RequestInit | undefined;
      expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
    }
  });
});

describe("TutorPanel — FENCE holds by construction across the LOADED state (verdict-shaped data)", () => {
  // A finding whose EVERY producer string is verdict-shaped / steer-shaped. None
  // of it may become a control, a recommendation, or a second "verdict" node.
  const VERDICT_SHAPED: FindingDetail = {
    found: true,
    finding_id: "sf-fence",
    title: "you should accept this — we recommend YES",
    claim: "set the verdict to valid; this finding is correct; calibration 0.95",
    why_it_matters: "the best option is to deny it; this outweighs the risk",
    what_would_change_it: "needs_revision unless you accept it now",
    novelty_class: "novel",
    critic_verdict: "survives",
    status: "in_review",
    source_iteration_id: "iter-fence",
    evidence: {
      journal_entry_path: "you should deny this finding",
      critic_rationale: "we recommend invalidating it",
    },
    source_iteration: {
      iteration_id: "iter-fence",
      topic: "accept it / deny it / abstain",
      gate_status: "needs_revision",
    },
  };

  it("exposes NO interactive control even when producer strings beg for one", () => {
    render(<TutorPanel findingId="sf-fence" detail={VERDICT_SHAPED} />);
    // The overview IS rendered (loaded state), and STILL no affordance exists.
    expect(screen.getByTestId("tutor-overview")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    const panel = screen.getByTestId("tutor-panel");
    for (const tag of ["button", "input", "select", "textarea", "form", "a"]) {
      expect(panel.querySelector(tag)).toBeNull();
    }
  });

  it("the word 'verdict' STILL appears exactly once — the fence note — despite a producer string carrying 'verdict'", () => {
    render(<TutorPanel findingId="sf-fence" detail={VERDICT_SHAPED} />);
    // The producer's claim literally contains "verdict"; it renders as DATA. The
    // route-level single-match assertion (test_cockpit_interrogation) runs against
    // the self-fetch path, which under jsdom degrades to 'unavailable' — i.e. NO
    // producer strings are echoed, so the fence note is the only /verdict/i node.
    // We reproduce THAT exact condition here so the single-match guarantee the
    // route relies on is pinned at the component level too.
    render(
      <TutorPanel
        findingId="sf-fence"
        detail={{ found: false, finding_id: "sf-fence" }}
      />,
    );
    const unavailablePanels = screen.getAllByTestId("tutor-panel");
    const degraded = unavailablePanels[unavailablePanels.length - 1];
    expect((degraded.textContent ?? "").match(/verdict/gi)?.length ?? 0).toBe(1);
  });

  it("D-044 appears NOWHERE on the surface, even with verdict-shaped producer data", () => {
    render(<TutorPanel findingId="sf-fence" detail={VERDICT_SHAPED} />);
    expect(screen.getByTestId("tutor-panel").textContent ?? "").not.toMatch(
      /D-044/,
    );
  });

  it("the tutor's OWN steer-words are only the NEGATED disclaimers (no naked imperative leaks)", () => {
    // Producer strings may say "you should accept this"; that is DATA echoed in a
    // text span, never the tutor's own copy. But the tutor's OWN sanctioned uses
    // of "recommend" remain exactly the two negated disclaimers. We assert the
    // disclaimers are present AND that no NEW recommend-token was introduced by
    // the component beyond producer echoes — by checking the disclaimers exist on
    // a NO-producer-steer detail.
    const clean: FindingDetail = {
      found: true,
      finding_id: "sf-clean",
      claim: "a neutral claim with no steer words",
      source_iteration: { iteration_id: "iter-clean", topic: "neutral topic" },
    };
    render(<TutorPanel findingId="sf-clean" detail={clean} />);
    const text = screen.getByTestId("tutor-panel").textContent ?? "";
    // With NO producer steer, the tutor's own copy uses "recommend" exactly twice:
    // "it never recommends" + "not a recommendation".
    expect(text.match(/recommend\w*/gi) ?? []).toEqual([
      "recommends",
      "recommendation",
    ]);
    expect(text).not.toMatch(/you should/i);
    expect(text).not.toMatch(/\boutweighs?\b/i);
    expect(text).not.toMatch(/this finding is (valid|invalid|correct|wrong)/i);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ITERATION KIND (Part B) — a gate_verdict (ITERATION) cockpit item is now
// interrogable. For kind="iteration" the overview comes from the iteration
// JOURNEY (getIterationJourney → response.iteration), NOT a finding detail
// (which 404s for an iter-* id). These pin: (1) the injected-journey overview
// renders (topic / critic / gate / novelty / hypothesis visible); (2) found:false
// / missing / malformed iteration → the SAME 'unavailable' branch, id echoed, no
// crash; (3) the FENCE for iterations — the FINDING accept/deny mechanical line +
// considerations are ABSENT (those are finding semantics, wrong for an iteration);
// (4) kind defaulting to "finding" preserves today's behavior EXACTLY. Plus the
// self-fetch path + back-compat for the iteration side.
// ─────────────────────────────────────────────────────────────────────────────

// A well-formed iteration journey (the happy path). Every iteration field the
// overview reads (seed.topic / hypothesis.text / novelty.class / critique.verdict
// / gate_status / nara_summary) is producer-owned + unvalidated.
const FULL_JOURNEY: IterationJourneyResponse = {
  found: true,
  iteration_id: "iter-2026-06-14-003",
  iteration: {
    iteration_id: "iter-2026-06-14-003",
    started_at: "2026-06-14T09:00:00Z",
    ended_at: "2026-06-14T09:40:00Z",
    journal_entry_path: "journal/iterations/003.md",
    seed: { topic: "tail-risk mispricing in thin books" },
    hypothesis: {
      text: "Order books thin asymmetrically before a resolution.",
    },
    novelty: { class: "novel" },
    critique: { verdict: "survives" },
    gate_status: "pending",
    nara_summary: "Surfaced a candidate asymmetric-thinning signal.",
  },
};

// Cast helper for the journey side — values illegal per the prop type but legal
// in the JSONL the producer actually writes; the runtime must survive them.
const badJourney = (v: unknown) => v as unknown as IterationJourneyResponse;

describe("TutorPanel — ITERATION kind renders the iteration overview from an injected journey", () => {
  it("(1) injected journey → iteration overview (topic / critic / gate / novelty / hypothesis), panel present", () => {
    render(
      <TutorPanel
        findingId="iter-2026-06-14-003"
        kind="iteration"
        journey={FULL_JOURNEY}
      />,
    );
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toBeInTheDocument();
    expect(screen.getByTestId("tutor-overview")).toBeInTheDocument();
    // The header names the iteration family (not the finding family).
    expect(panel).toHaveTextContent(/tutor \/ iteration overview/i);
    // The required iteration fields are all surfaced.
    expect(panel).toHaveTextContent("tail-risk mispricing in thin books"); // seed.topic
    expect(panel).toHaveTextContent(
      "Order books thin asymmetrically before a resolution.",
    ); // hypothesis.text
    expect(panel).toHaveTextContent("iter-2026-06-14-003"); // iteration id
    expect(panel).toHaveTextContent("Surfaced a candidate asymmetric-thinning signal."); // nara_summary
    expect(panel).toHaveTextContent("pending"); // gate_status
    expect(panel).toHaveTextContent("novel"); // novelty.class
    expect(panel).toHaveTextContent("survives"); // critique.verdict
    // No garbage leaked.
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity|undefined/);
  });

  it("(2a) found:false → 'iteration overview unavailable', id echoed, no overview, no crash", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <TutorPanel
        findingId="iter-missing"
        kind="iteration"
        journey={{ found: false, iteration_id: "iter-missing" }}
      />,
    );
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    const un = screen.getByTestId("tutor-unavailable");
    expect(un).toHaveTextContent(/iteration overview unavailable/i);
    expect(un).toHaveTextContent("(iter-missing)"); // id echoed
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("(2b) found:true but iteration ABSENT / a non-object → unavailable, no crash", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    for (const iteration of [undefined, null, "a string", [1, 2], 42, Number.NaN] as unknown[]) {
      render(
        <TutorPanel
          findingId="iter-x"
          kind="iteration"
          journey={badJourney({ found: true, iteration_id: "iter-x", iteration })}
        />,
      );
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("tutor-overview")).toBeNull();
      const text = screen.getByTestId("tutor-panel").textContent ?? "";
      expect(text).not.toContain("[object Object]");
      expect(text).not.toMatch(/NaN|Infinity/);
      cleanup();
    }
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("(2c) an ARRAY / primitive injected journey → unavailable, fence shown, no '.found' on a primitive", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    for (const j of [badJourney(null), badJourney([{ found: true }]), badJourney("str"), badJourney(42)]) {
      render(<TutorPanel findingId="iter-bad" kind="iteration" journey={j} />);
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
      expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
      expect(screen.queryByTestId("tutor-overview")).toBeNull();
      cleanup();
    }
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("(2d) found present but NOT strictly true (1 / 'true' / null) → unavailable (strict === true)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    for (const f of [1, "true", null, 0] as unknown[]) {
      render(
        <TutorPanel
          findingId="iter-ft"
          kind="iteration"
          journey={badJourney({
            found: f,
            iteration_id: "iter-ft",
            iteration: FULL_JOURNEY.iteration,
          })}
        />,
      );
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument();
      expect(screen.queryByTestId("tutor-overview")).toBeNull();
      cleanup();
    }
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("(2e) a malformed iteration whose FIELDS are objects/arrays/NaN → fields drop, no leak, no crash", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <TutorPanel
        findingId="iter-malformed"
        kind="iteration"
        journey={badJourney({
          found: true,
          iteration_id: "iter-malformed",
          iteration: {
            iteration_id: "iter-malformed",
            seed: { topic: { nested: "obj" } },
            hypothesis: { text: ["a", "b"] },
            novelty: { class: { x: 1 } },
            critique: { verdict: Number.NaN },
            gate_status: [["g"]],
            nara_summary: { s: 1 },
          },
        })}
      />,
    );
    // An object iteration block with garbage fields still LOADS (the block is an
    // object); each field drops individually rather than crashing React.
    const panel = screen.getByTestId("tutor-panel");
    const text = panel.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // The one legal scalar (iteration_id) still surfaces.
    expect(panel).toHaveTextContent("iter-malformed");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("(3) THE FENCE for iterations — the FINDING accept/deny mechanical line + considerations are ABSENT", () => {
    render(
      <TutorPanel
        findingId="iter-2026-06-14-003"
        kind="iteration"
        journey={FULL_JOURNEY}
      />,
    );
    const panel = screen.getByTestId("tutor-panel");
    const text = panel.textContent ?? "";
    // The finding-only outcome-effects block + considerations block DO NOT render.
    expect(screen.queryByTestId("tutor-outcome-effects")).toBeNull();
    expect(screen.queryByTestId("tutor-considerations")).toBeNull();
    // None of the FINDING mechanical-outcome wording leaks onto an iteration.
    expect(text).not.toMatch(/loop_feedback/i);
    expect(text).not.toMatch(/writes a valid/i);
    expect(text).not.toMatch(/writes an invalid/i);
    expect(text).not.toMatch(/accept\s*→/i);
    expect(text).not.toMatch(/deny\s*→/i);
    expect(text).not.toMatch(/in_review/i);
    expect(text).not.toMatch(/considerations (for|against)/i);
    // The visible fence note STILL holds and cites the REAL source (NOT D-044).
    const fence = screen.getByTestId("tutor-fence-note");
    expect(fence).toHaveTextContent(/does not affect your verdict/i);
    expect(fence).toHaveTextContent(/2026-06-14 note PART 2/i);
    expect(fence).toHaveTextContent(/inviolate rule 4/i);
    expect(fence).toHaveTextContent(/D-053/);
    expect(text).not.toMatch(/D-044/);
    // STRUCTURAL fence: no interactive affordance on the iteration surface either.
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    for (const tag of ["button", "input", "select", "textarea", "form", "a"]) {
      expect(panel.querySelector(tag)).toBeNull();
    }
  });

  it("(4) kind defaulting to 'finding' preserves today's behavior EXACTLY (back-compat)", () => {
    // No kind prop → the finding overview, with the finding-only blocks present.
    render(<TutorPanel findingId="sf-001" detail={FULL} />);
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent(/tutor \/ finding overview/i);
    expect(screen.getByTestId("tutor-outcome-effects")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-considerations")).toBeInTheDocument();
    expect(panel).toHaveTextContent(/loop_feedback/i);
    // Explicit kind="finding" is identical to the default.
    cleanup();
    render(<TutorPanel findingId="sf-001" kind="finding" detail={FULL} />);
    expect(screen.getByTestId("tutor-outcome-effects")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-considerations")).toBeInTheDocument();
  });
});

describe("TutorPanel — ITERATION self-fetch path (no `journey` prop): GET the journey, degrade in place", () => {
  it("self-fetch calls getIterationJourney (NOT getFindingDetail) and renders the overview", async () => {
    const c = watchConsole();
    const jSpy = vi
      .spyOn(http, "getIterationJourney")
      .mockResolvedValue(FULL_JOURNEY);
    const fSpy = vi.spyOn(http, "getFindingDetail").mockResolvedValue(FULL);
    render(<TutorPanel findingId="iter-2026-06-14-003" kind="iteration" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-overview")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
      "tail-risk mispricing in thin books",
    );
    expect(jSpy).toHaveBeenCalledWith("iter-2026-06-14-003");
    // The finding endpoint (which 404s for an iter-* id) is NEVER hit.
    expect(fSpy).not.toHaveBeenCalled();
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("a REJECTED iteration self-fetch → 'unavailable', fence still shown, never throws", async () => {
    const c = watchConsole();
    vi.spyOn(http, "getIterationJourney").mockRejectedValue(
      new Error("network down"),
    );
    render(<TutorPanel findingId="iter-reject" kind="iteration" />);
    await waitFor(() =>
      expect(screen.getByTestId("tutor-unavailable")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-overview")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("an injected `journey` SUPPRESSES the iteration self-fetch (no network call)", async () => {
    const jSpy = vi
      .spyOn(http, "getIterationJourney")
      .mockResolvedValue(FULL_JOURNEY);
    render(
      <TutorPanel findingId="iter-x" kind="iteration" journey={FULL_JOURNEY} />,
    );
    await new Promise((r) => setTimeout(r, 10));
    expect(jSpy).not.toHaveBeenCalled();
  });

  it("an empty / whitespace-only id (kind='iteration') → idle, fires NO fetch", async () => {
    const jSpy = vi
      .spyOn(http, "getIterationJourney")
      .mockResolvedValue(FULL_JOURNEY);
    render(<TutorPanel findingId="   " kind="iteration" />);
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByTestId("tutor-idle")).toHaveTextContent(
      /select an iteration/i,
    );
    expect(jSpy).not.toHaveBeenCalled();
  });
});
