// IterationDetailModal (2026-06-10 Task 4) — the drill-in that received
// everything the condensed ResolvedIterationsList rows gave up. Pins:
//
//   1. DIALOG MECHANICS on the native <dialog>: opens via showModal() on
//      mount (tests/setup.ts polyfills jsdom), Esc closes, a backdrop click
//      closes, a content click does NOT, and closing restores focus to the
//      opening card. Card click keeps the existing onSelect journal behavior.
//   2. SECTIONS in the pinned order: verdict header (full badges + override
//      provenance AS VISIBLE TEXT), hypothesis, evidence (relevance detail
//      incl. topicality + axes chip + rationale + low-evidence inline),
//      adversarial record, conditioning bullets (the block that left the
//      row), experiment_outcome (scalar-guard + Verdict=YES|NO chips), gate
//      panel (gate_status + the integrator's data-attest-slot + the CLI
//      fallback), links (lazy journal, /chain/req/<id>, the experiment page,
//      the matching coordinator cycle).
//   3. HONESTY: producer-owned garbage degrades (no "[object Object]", no
//      NaN); absent blocks omit their lines; the cycle-join fetch failing
//      (older backend) silently drops the link, never a red state.
//
// Fixtures are EXPLICITLY SYNTHETIC constructions except where noted: the
// experiment_outcome block is the verbatim-real exp003 bridge row from
// memory/loop_memory.jsonl (2026-06-05). No live-count pins.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import IterationDetailModal, {
  ExperimentChip,
  experimentVerdict,
  redteamAlarm,
} from "../src/components/IterationDetailModal";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import * as http from "../src/api/http";
import type { IterationRecord } from "../src/types/schemas";

afterEach(() => {
  vi.restoreAllMocks();
});

function stubCycles(cycles: unknown[] = []) {
  return vi
    .spyOn(http, "getCoordinatorCycles")
    .mockResolvedValue({ cycles } as never);
}

// A fully-loaded SYNTHETIC row exercising every modal section at once.
// (Constructed for coverage — explicitly not a live row. The
// experiment_outcome block is the verbatim-real exp003 bridge from
// loop_memory.jsonl.)
const FULL_ROW: IterationRecord = {
  iteration_id: "iter-modal-full",
  started_at: "2026-06-10T10:00:00Z",
  ended_at: "2026-06-10T10:05:00Z",
  seed: {
    topic: "Synthetic full-coverage row for the detail modal",
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

function renderModal(row: IterationRecord, onClose = vi.fn()) {
  stubCycles();
  render(
    <MemoryRouter>
      <IterationDetailModal row={row} onClose={onClose} />
    </MemoryRouter>,
  );
  return { onClose, dialog: screen.getByTestId("iteration-detail-modal") };
}

describe("IterationDetailModal — dialog mechanics", () => {
  it("opens via showModal() on mount (native dialog carries the open attribute)", () => {
    const { dialog } = renderModal(FULL_ROW);
    expect(dialog).toHaveAttribute("open");
  });

  it("Esc closes (close event → onClose)", () => {
    const { onClose, dialog } = renderModal(FULL_ROW);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a backdrop click closes; a content click does NOT", () => {
    const { onClose, dialog } = renderModal(FULL_ROW);
    // Content click: target is a descendant — stays open.
    fireEvent.click(within(dialog).getByTestId("modal-verdict-header"));
    expect(onClose).not.toHaveBeenCalled();
    // Backdrop click: the event target is the <dialog> element itself
    // (::backdrop clicks target the dialog; p-0 leaves no inner dialog area).
    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the explicit close button closes", () => {
    const { onClose, dialog } = renderModal(FULL_ROW);
    fireEvent.click(within(dialog).getByLabelText("close iteration detail"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("card click in the list opens the modal AND keeps onSelect; closing restores focus to the opening card", () => {
    stubCycles();
    const onSelect = vi.fn();
    render(
      <MemoryRouter>
        <ResolvedIterationsList initial={[FULL_ROW]} onSelect={onSelect} />
      </MemoryRouter>,
    );
    const card = screen.getByLabelText("load journal iter-modal-full");
    fireEvent.click(card);
    expect(onSelect).toHaveBeenCalledWith("iter-modal-full");
    const dialog = screen.getByTestId("iteration-detail-modal");
    expect(dialog).toHaveAttribute("open");

    fireEvent.keyDown(dialog, { key: "Escape" });
    // Modal unmounts and the OPENING CARD regains focus (Task 4 contract).
    expect(screen.queryByTestId("iteration-detail-modal")).toBeNull();
    expect(document.activeElement).toBe(card);
  });
});

describe("IterationDetailModal — sections in pinned order", () => {
  it("renders the eight section anchors in DOM order", () => {
    const { dialog } = renderModal(FULL_ROW);
    const ids = [
      "modal-verdict-header",
      "modal-hypothesis",
      "modal-evidence",
      "modal-adversarial",
      "modal-conditioning",
      "modal-experiment-outcome",
      "modal-gate-panel",
      "modal-links",
    ];
    const nodes = ids.map((id) => within(dialog).getByTestId(id));
    for (let i = 1; i < nodes.length; i++) {
      // DOCUMENT_POSITION_FOLLOWING (4): nodes[i] comes after nodes[i-1].
      expect(
        nodes[i - 1].compareDocumentPosition(nodes[i]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("1 — verdict header: full badge set + override provenance AS VISIBLE TEXT for both blocks", () => {
    const { dialog } = renderModal(FULL_ROW);
    const header = within(dialog).getByTestId("modal-verdict-header");
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

    // Override provenance is VISIBLE TEXT here (the row keeps tooltip-only).
    const nov = within(header).getByTestId("modal-override-novelty");
    expect(nov).toHaveTextContent("overridden from novel");
    expect(nov).toHaveTextContent(
      "reason: low-confidence retrieval downgraded the class",
    );
    const crit = within(header).getByTestId("modal-override-critique");
    expect(crit).toHaveTextContent("overridden from survives");
    expect(crit).toHaveTextContent("reason: skeptic attack_verdict='refuted'");
    expect(crit).toHaveTextContent("skeptic said refuted");
  });

  it("2 — hypothesis: text, source badge, candidates_considered", () => {
    const { dialog } = renderModal(FULL_ROW);
    const hyp = within(dialog).getByTestId("modal-hypothesis");
    expect(hyp).toHaveTextContent(
      "LLM bidders shade bids under ascending pressure.",
    );
    expect(within(hyp).getByTestId("source-badge")).toHaveTextContent(
      "coordinator",
    );
    expect(within(hyp).getByTestId("modal-candidates")).toHaveTextContent(
      "candidates considered: 3",
    );
  });

  it("3 — evidence: the full relevance diagnostic detail (incl. topicality), axes chip, rationale, low-evidence inline", () => {
    const { dialog } = renderModal(FULL_ROW);
    const ev = within(dialog).getByTestId("modal-evidence");
    for (const pair of [
      ["relevance", "0.42"],
      ["category", "thin"],
      ["rule_fired", "R2"],
      ["topicality", "unsure"],
      ["anchor_cosine", "0.31"],
      ["curated_overlap", "0.05"],
      ["neighbor_spread", "0.6"],
      ["reason", "thin: only one sharp neighbor"],
    ] as const) {
      expect(ev).toHaveTextContent(pair[0]);
      expect(ev).toHaveTextContent(pair[1]);
    }
    expect(within(ev).getByTestId("novelty-axes-chip")).toBeInTheDocument();
    expect(ev).toHaveTextContent(
      "Neighbors cover auctions but not the shading mechanism.",
    );
    // The low-evidence detail INLINE (what the badge's tooltip says).
    const detail = within(ev).getByTestId("modal-low-evidence-detail");
    expect(detail).toHaveTextContent(/retrieval flagged low-confidence/);
    expect(detail).toHaveTextContent(/category: thin/);
    expect(detail).toHaveTextContent(/rule: R2/);
  });

  it("4 — adversarial record: critique rationale/contradicting/skeptic + every redteam field", () => {
    const { dialog } = renderModal(FULL_ROW);
    const adv = within(dialog).getByTestId("modal-adversarial");
    expect(adv).toHaveTextContent(
      "No contradicting neighbor; corpus too thin to judge.",
    );
    expect(adv).toHaveTextContent("vickrey1961-chunk-9");
    expect(adv).toHaveTextContent("refuted");
    expect(adv).toHaveTextContent("Mechanism is testable but underspecified.");
    expect(adv).toHaveTextContent("Pin the auction format before running.");
    expect(adv).toHaveTextContent("0.7"); // confidence
    expect(adv).toHaveTextContent("retries used");
  });

  it("5 — conditioning bullets render under the SAME testid the row used to carry (moved scope)", () => {
    const { dialog } = renderModal(FULL_ROW);
    const cond = within(dialog).getByTestId("conditioning-iter-modal-full");
    expect(within(cond).getByText("carried bullet alpha")).toBeInTheDocument();
    expect(within(cond).getByText("carried bullet beta")).toBeInTheDocument();
  });

  it("6 — experiment_outcome: Verdict=YES chip + scalar-guarded detail", () => {
    const { dialog } = renderModal(FULL_ROW);
    const exp = within(dialog).getByTestId("modal-experiment-outcome");
    const chip = within(exp).getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("exp verdict=YES");
    expect(chip.className).toContain("emerald");
    expect(exp).toHaveTextContent("exp003_vickrey_rediscovery");
    expect(exp).toHaveTextContent("truthful_bid_fraction");
    expect(exp).toHaveTextContent("1");
    expect(exp).toHaveTextContent("50");
    expect(exp).toHaveTextContent(/Verdict=YES\. Fraction of trials/);
  });

  it("7 — gate panel: gate_status + the integrator's data-attest-slot + the CLI fallback disclosure", () => {
    const { dialog } = renderModal(FULL_ROW);
    const gate = within(dialog).getByTestId("modal-gate-panel");
    expect(within(gate).getByText("pending")).toBeInTheDocument();
    // The seam the integrator stitches GateVerdictForm into:
    const slot = gate.querySelector('[data-attest-slot="gate"]');
    expect(slot).not.toBeNull();
    expect(slot!.getAttribute("data-iteration-id")).toBe("iter-modal-full");
    // The copy-paste CLI fallback inside a <details> disclosure.
    const cli = within(gate).getByTestId("modal-gate-cli");
    expect(cli).toHaveTextContent(
      ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id iter-modal-full",
    );
    expect(cli).toHaveTextContent("<valid|invalid|needs_revision>");
  });

  it("8 — links: call chain from wrapper_call_ids[0] and the experiment page from the outcome", () => {
    const { dialog } = renderModal(FULL_ROW);
    const links = within(dialog).getByTestId("modal-links");
    const chain = within(links).getByTestId("modal-chain-link");
    expect(chain.getAttribute("href")).toBe(
      "/chain/req/c502cb94-46bb-42cf-8394-0ffbf2f2063e",
    );
    const exp = within(links).getByTestId("modal-experiment-link");
    expect(exp.getAttribute("href")).toBe(
      "/experiments/exp003_vickrey_rediscovery",
    );
  });

  it("8 — links: the coordinator cycle whose dispatched_iteration_id matches gets a link; no match → no link", async () => {
    // Synthetic cycle rows: only the matching one links.
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
    render(
      <MemoryRouter>
        <IterationDetailModal row={FULL_ROW} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    const link = await screen.findByTestId("modal-cycle-link");
    expect(link).toHaveTextContent("coordinator_ab12cd34");
    expect(link.getAttribute("href")).toBe("/coordinator");
  });

  it("8 — links: journal mounts LAZILY on disclosure open (no fetch before)", async () => {
    const journalSpy = vi.spyOn(http, "getJournalEntry").mockResolvedValue({
      iteration_id: "iter-modal-full",
      path: "journal/iterations/full.md",
      content: "# Journal\n\nmodal journal body",
    });
    const { dialog } = renderModal(FULL_ROW);
    expect(journalSpy).not.toHaveBeenCalled();
    expect(within(dialog).queryByTestId("journal-scroll")).toBeNull();

    const details = within(dialog).getByTestId("modal-journal");
    // jsdom does not auto-fire toggle on summary click; set open + toggle.
    (details as HTMLDetailsElement).open = true;
    fireEvent(details, new Event("toggle", { bubbles: false }));
    await waitFor(() =>
      expect(within(dialog).getByTestId("journal-scroll")).toBeInTheDocument(),
    );
    expect(journalSpy).toHaveBeenCalledWith("iter-modal-full");
    await waitFor(() =>
      expect(
        within(dialog).getByText("modal journal body"),
      ).toBeInTheDocument(),
    );
  });
});

describe("IterationDetailModal — honesty on sparse / garbled rows", () => {
  it("a bare legacy row renders every section without crashing, faking nothing", () => {
    stubCycles();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const bare = {
      iteration_id: "iter-modal-bare",
      started_at: "2026-05-01T10:00:00Z",
      ended_at: "2026-05-01T10:05:00Z",
      journal_entry_path: "journal/iterations/bare.md",
    } as unknown as IterationRecord;
    render(
      <MemoryRouter>
        <IterationDetailModal row={bare} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    const dialog = screen.getByTestId("iteration-detail-modal");
    expect(dialog).toHaveTextContent("no hypothesis text on this row");
    expect(dialog).toHaveTextContent("no retrieval.relevance block");
    expect(dialog).toHaveTextContent("no conditioning bullets on this row");
    // No experiment section at all when the bridge block is absent.
    expect(
      within(dialog).queryByTestId("modal-experiment-outcome"),
    ).toBeNull();
    // Gate panel still shows its honest empty state + the attest slot.
    expect(within(dialog).getByTestId("modal-gate-panel")).toHaveTextContent(
      "pre-v1 row, no gate",
    );
    expect(dialog.querySelector('[data-attest-slot="gate"]')).not.toBeNull();
    // No chain/experiment/cycle links invented.
    expect(within(dialog).queryByTestId("modal-chain-link")).toBeNull();
    expect(within(dialog).queryByTestId("modal-experiment-link")).toBeNull();
    expect(within(dialog).queryByTestId("modal-cycle-link")).toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("garbled producer fields degrade — no [object Object], no NaN", () => {
    stubCycles();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const garbled = {
      iteration_id: "iter-modal-garbled",
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
    const { container } = render(
      <MemoryRouter>
        <IterationDetailModal row={garbled} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(container.innerHTML).not.toMatch(/NaN/);
    // The multi-metric object value renders only its SCALAR entries.
    const exp = screen.getByTestId("modal-experiment-outcome");
    expect(exp).toHaveTextContent("value.sub_a");
    expect(exp).toHaveTextContent("0.5");
    expect(exp).not.toHaveTextContent("value.junk");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("a failed cycle fetch (older backend / skew) silently drops the cycle link — never a red state", async () => {
    vi.spyOn(http, "getCoordinatorCycles").mockRejectedValue(
      new Error("404 not found"),
    );
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <MemoryRouter>
        <IterationDetailModal row={FULL_ROW} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    // Let the rejected promise settle.
    await waitFor(() =>
      expect(http.getCoordinatorCycles).toHaveBeenCalled(),
    );
    expect(screen.queryByTestId("modal-cycle-link")).toBeNull();
    expect(screen.getByTestId("iteration-detail-modal")).not.toHaveTextContent(
      /404/,
    );
    expect(errSpy).not.toHaveBeenCalled();
  });
});

describe("exported helpers — experimentVerdict / redteamAlarm / ExperimentChip", () => {
  it("experimentVerdict reads only a literal Verdict=YES|NO from the summary", () => {
    expect(experimentVerdict(FULL_ROW.experiment_outcome)).toBe("YES");
    expect(
      experimentVerdict({
        experiment_id: "e",
        metric: "m",
        value: 1,
        summary: "VCG verdict=NO. Fraction under threshold.",
      }),
    ).toBe("NO");
    expect(
      experimentVerdict({ experiment_id: "e", metric: "m", value: 1 }),
    ).toBe(null);
    expect(experimentVerdict(null)).toBe(null);
    expect(
      experimentVerdict("nope" as unknown as IterationRecord["experiment_outcome"]),
    ).toBe(null);
  });

  it("ExperimentChip: NO → red, no verdict line → quiet 'experiment'", () => {
    const { rerender } = render(
      <ExperimentChip
        outcome={{
          experiment_id: "exp009",
          metric: "x",
          value: 0.1,
          summary: "Verdict=NO. Deviation persists.",
        }}
      />,
    );
    let chip = screen.getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("exp verdict=NO");
    expect(chip.className).toContain("red");

    rerender(
      <ExperimentChip outcome={{ experiment_id: "exp001", metric: "m", value: 1 }} />,
    );
    chip = screen.getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("experiment");
    expect(chip.className).toContain("zinc");
  });

  it("redteamAlarm: fatal or retries>0 alarms; clean/NaN/negative does not", () => {
    expect(redteamAlarm({ verdict: "fatal_flaw" })).toBe(true);
    expect(redteamAlarm({ verdict: "proceed", retries_used: 2 })).toBe(true);
    expect(redteamAlarm({ verdict: "proceed", retries_used: 0 })).toBe(false);
    expect(redteamAlarm({ verdict: "proceed", retries_used: NaN })).toBe(false);
    expect(redteamAlarm({ verdict: "proceed", retries_used: -3 })).toBe(false);
    expect(redteamAlarm(null)).toBe(false);
    expect(redteamAlarm(undefined)).toBe(false);
  });
});
