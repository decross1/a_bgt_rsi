// OweCard — the redesigned "What you owe" hero (owner ask 2026-08-18). Pins:
// collapsed default is a SHORT claim-head title (first sentence, ~120 chars,
// never the full hypothesis/stats wall) over one muted action line; expand
// reveals the labeled sections in reading order (WHAT YOU'RE DOING → VET
// FIRST → WHAT APPROVAL MEANS → WHY THE TAG collapsed by default → RESOLVE
// with a one-line command + copy affordance); age chips go amber >14d and
// rose >45d; the server-derived triage tags render as DECLARATIVE statements
// ("LIKELY SUPERSEDED", never a question mark) and never remove a row;
// OweStrip's inherited pins (below-bar demotion line, owed count, dossier
// links) carry over.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import OweCard from "../src/components/OweCard";
import type { HumanTodoItem } from "../src/types/schemas";

// Fixed clock: 2026-08-18T12:00:00Z — ages below are computed against this.
const NOW = Date.parse("2026-08-18T12:00:00Z");

function renderCard(items?: HumanTodoItem[]) {
  return render(
    <MemoryRouter>
      <OweCard initial={items} nowMs={NOW} />
    </MemoryRouter>,
  );
}

// A 74-day-old gate item the audit tagged likely-superseded (the
// iter-2026-06-05-004 shape), fully enriched by backend/owe_triage.py.
const OLD_SUPERSEDED: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-05-004",
  title: "Experiment exp004_combinatorial_auction reports vcg_truthful_fraction = 0.965.",
  since: "2026-06-05T20:31:13Z",
  detail: "iteration iter-2026-06-05-004 finished and awaits a human gate verdict",
  resolve_command:
    ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id iter-2026-06-05-004 --verdict <valid|invalid|needs_revision>",
  action: "Record a gate verdict on iter-2026-06-05-004",
  doing:
    "Decide whether iteration iter-2026-06-05-004's result is valid, invalid, or needs revision.",
  approval_means:
    "gate_cli appends your verdict to memory/loop_feedback.jsonl (readers are last-row-wins).",
  vet: [
    "redteam verdict: fatal_flaw — read its rationale before trusting the headline metric",
    "exp004_combinatorial_auction reports vcg_truthful_fraction = 0.965 over 40 trials",
    "its idea-ledger cluster cl-iter-2026-06-05-004 was killed 2026-08-15 (redteam_fatal_flaw)",
  ],
  triage: "likely_superseded",
  triage_reason:
    "H-KILL: cluster cl-iter-2026-06-05-004 was killed 2026-08-15 (redteam_fatal_flaw). A tag, not a dismissal.",
};

// A fresh (1-day-old) valid gate item — no tag, no amber.
const FRESH_VALID: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-08-17-011",
  title: "Bounded rationality slows convergence in LQG games.",
  since: "2026-08-17T03:48:00Z",
  resolve_command: "gate_cli --iteration-id iter-2026-08-17-011",
  action: "Record a gate verdict on iter-2026-08-17-011",
  triage: "valid",
  triage_reason: "no supersession signal in the stores — treated as a live ask",
};

// 20 days old: amber band (>14d, <=45d).
const AMBER_AGE: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-07-29-001",
  title: "amber-band item",
  since: "2026-07-29T12:00:00Z",
  triage: "valid",
};

describe("OweCard (collapsed default)", () => {
  it("renders ONE action-verb line per owed item, details hidden", () => {
    renderCard([OLD_SUPERSEDED, FRESH_VALID]);
    expect(screen.getByTestId("owe-count")).toHaveTextContent("2");
    expect(
      screen.getByText("Record a gate verdict on iter-2026-06-05-004"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Record a gate verdict on iter-2026-08-17-011"),
    ).toBeInTheDocument();
    // The three labeled answers stay hidden until a row is expanded.
    expect(screen.queryByText("WHAT YOU'RE DOING")).toBeNull();
    expect(screen.queryByText("WHAT APPROVAL MEANS")).toBeNull();
    expect(screen.queryByText("VET FIRST")).toBeNull();
    expect(screen.queryByTestId("owe-detail-0")).toBeNull();
  });

  it("rows still link into the dossier reader", () => {
    renderCard([OLD_SUPERSEDED]);
    const link = screen.getByRole("link", {
      name: /Record a gate verdict on iter-2026-06-05-004/,
    });
    expect(link).toHaveAttribute("href", "/dossier/iter-2026-06-05-004");
  });

  it("falls back to kind-generic phrasing against an older backend", () => {
    renderCard([
      { kind: "gate_verdict", id: "iter-x", title: "t", since: "2026-08-17T00:00:00Z" },
      { kind: "state_gate", id: "gate-1", title: "g", since: "2026-08-17T00:00:00Z" },
    ]);
    expect(screen.getByText("Record a gate verdict on iter-x")).toBeInTheDocument();
    expect(screen.getByText("Clear blocking human gate 'gate-1'")).toBeInTheDocument();
  });
});

describe("OweCard (triage tags)", () => {
  it("likely_superseded renders a DECLARATIVE tag (no question mark); valid renders none", () => {
    renderCard([OLD_SUPERSEDED, FRESH_VALID]);
    const tag = screen.getByTestId("owe-tag-0");
    expect(tag).toHaveTextContent("LIKELY SUPERSEDED");
    expect(tag.textContent).not.toContain("?");
    expect(tag).toHaveAttribute("data-triage", "likely_superseded");
    expect(screen.queryByTestId("owe-tag-1")).toBeNull();
  });

  it("a tag never removes the row — it stays listed, counted, linked", () => {
    renderCard([OLD_SUPERSEDED]);
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");
    expect(screen.getByTestId("owe-row-0")).toBeInTheDocument();
  });
});

describe("OweCard (age chips)", () => {
  it("fresh <=14d neutral, >14d amber, >45d rose", () => {
    renderCard([FRESH_VALID, AMBER_AGE, OLD_SUPERSEDED]);
    // Rows sort as given (backend owns ordering): fresh, amber, old.
    expect(screen.getByTestId("owe-age-0")).toHaveAttribute("data-tone", "fresh");
    expect(screen.getByTestId("owe-age-1")).toHaveAttribute("data-tone", "amber");
    expect(screen.getByTestId("owe-age-2")).toHaveAttribute("data-tone", "rose");
    // 74 days renders as a day count, honest and compact.
    expect(screen.getByTestId("owe-age-2")).toHaveTextContent("73d");
  });

  it("an unknown age renders the em-dash, never a false alarm tone", () => {
    renderCard([{ kind: "gate_verdict", id: "iter-noage", title: "t" }]);
    const chip = screen.getByTestId("owe-age-0");
    expect(chip).toHaveTextContent("—");
    expect(chip).toHaveAttribute("data-tone", "fresh");
  });
});

describe("OweCard (expanded)", () => {
  it("expand reveals the labeled sections + collapsed WHY toggle + resolve route", () => {
    renderCard([OLD_SUPERSEDED]);
    const btn = screen.getByTestId("owe-expand-0");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");

    const detail = screen.getByTestId("owe-detail-0");
    expect(within(detail).getByText("WHAT YOU'RE DOING")).toBeInTheDocument();
    expect(detail).toHaveTextContent(
      "valid, invalid, or needs revision",
    );
    expect(within(detail).getByText("WHAT APPROVAL MEANS")).toBeInTheDocument();
    expect(detail).toHaveTextContent("loop_feedback.jsonl");
    expect(within(detail).getByText("VET FIRST")).toBeInTheDocument();
    // The vet bullets come from the item's own record, rendered as a list.
    const bullets = within(detail).getAllByRole("listitem");
    expect(bullets).toHaveLength(3);
    expect(bullets[0]).toHaveTextContent("redteam verdict: fatal_flaw");
    // WHY THE TAG is collapsed by default (the triage_reason runs long):
    // the toggle is there, the reason text is NOT — until clicked.
    const why = within(detail).getByTestId("owe-why-0");
    expect(why).toHaveTextContent("WHY THE TAG");
    expect(why).toHaveAttribute("aria-expanded", "false");
    expect(detail).not.toHaveTextContent("A tag, not a dismissal.");
    fireEvent.click(why);
    expect(why).toHaveAttribute("aria-expanded", "true");
    expect(detail).toHaveTextContent("A tag, not a dismissal.");
    // Resolve route: the exact CLI command + the dossier link.
    expect(detail).toHaveTextContent("orchestrator.gate_cli");
    expect(
      within(detail).getByRole("link", { name: "open dossier →" }),
    ).toHaveAttribute("href", "/dossier/iter-2026-06-05-004");
  });

  it("sections read in the polished order: DOING → VET → MEANS → WHY → RESOLVE", () => {
    renderCard([OLD_SUPERSEDED]);
    fireEvent.click(screen.getByTestId("owe-expand-0"));
    const text = screen.getByTestId("owe-detail-0").textContent ?? "";
    const order = [
      "WHAT YOU'RE DOING",
      "VET FIRST",
      "WHAT APPROVAL MEANS",
      "WHY THE TAG",
      "RESOLVE",
    ].map((label) => text.indexOf(label));
    expect(order.every((idx) => idx >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("collapses again on a second click", () => {
    renderCard([OLD_SUPERSEDED]);
    const btn = screen.getByTestId("owe-expand-0");
    fireEvent.click(btn);
    expect(screen.getByTestId("owe-detail-0")).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.queryByTestId("owe-detail-0")).toBeNull();
    expect(btn).toHaveAttribute("aria-expanded", "false");
  });

  it("expanding one row leaves the others collapsed", () => {
    renderCard([OLD_SUPERSEDED, FRESH_VALID]);
    fireEvent.click(screen.getByTestId("owe-expand-1"));
    expect(screen.queryByTestId("owe-detail-0")).toBeNull();
    expect(screen.getByTestId("owe-detail-1")).toBeInTheDocument();
  });
});

// ── Pointed enrichment (owner ask 2026-08-18 #2) ───────────────────────────
// The backend's human_todo._point_gate_verdicts now sends record-joined,
// item-specific copy for the three answers. The card renders the server
// strings verbatim — these pins prove the pointed shapes survive the trip
// (hypothesis-bearing doing, killed-cluster consequence, the old-redteam
// caveat + pre-debate-era probes with values inline).
const POINTED: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-05-004",
  title: "Experiment exp004_combinatorial_auction reports vcg_truthful_fraction = 0.965.",
  since: "2026-06-05T20:31:13Z",
  resolve_command:
    ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id iter-2026-06-05-004 --verdict <valid|invalid|needs_revision>",
  action: "Record a gate verdict on iter-2026-06-05-004",
  doing:
    'You are judging whether this finished iteration\'s record is sound — hypothesis: "The observed VCG truthfulness fraction of 0.965 is significantly higher than the baseline…". Its experiment exp004_combinatorial_auction measured vcg_truthful_fraction=0.965 over 150 trials. The idea ledger folded it into cluster cl-iter-2026-06-05-004, KILLED 2026-08-15 (redteam_fatal_flaw).',
  approval_means:
    "Cluster cl-iter-2026-06-05-004 is already KILLED (redteam_fatal_flaw, 2026-08-15) — this verdict settles the historical record, nothing downstream re-runs (it can feed your calibration review, but that join is manual today — the cockpit calibration page has no automated loop_feedback scorer). It does NOT reopen the cluster: reopening needs new evidence (redteam_proceed_on_revision) per the ledger's reopening_condition. (Mechanically: gate_cli appends one row to memory/loop_feedback.jsonl; readers are last-row-wins.)",
  vet: [
    "killed by the OLD redteam prompt — the R1a calibration battery (bench/redteam_cal/runs/, 2026-08-18) measured that configuration condemning 6/7 parsed known-good fixtures; treat the fatal_flaw as weak evidence, judge the hypothesis on its merits",
    "pre-debate-era row: no independent skeptic ever saw this — your read is the ONLY adversarial pass",
    "does vcg_truthful_fraction=0.965 actually discriminate the hypothesis from the null? check the locked decision rule in experiments/exp004_combinatorial_auction/results/summary.json",
    "novelty: unclear — The hypothesis refers to a specific experimental result…",
    "cluster cl-iter-2026-06-05-004 also holds iter-2026-06-19-011 — the ledger folded these as ONE idea; check the sibling record before judging this one in isolation",
  ],
  triage: "likely_superseded",
  triage_reason:
    "H-KILL: cluster cl-iter-2026-06-05-004 was killed 2026-08-15 (redteam_fatal_flaw). A tag, not a dismissal.",
};

describe("OweCard (pointed enrichment, 2026-08-18 #2)", () => {
  it("renders the record-joined WHAT YOU'RE DOING (hypothesis + experiment + cluster)", () => {
    renderCard([POINTED]);
    fireEvent.click(screen.getByTestId("owe-expand-0"));
    const detail = screen.getByTestId("owe-detail-0");
    expect(detail).toHaveTextContent(
      'hypothesis: "The observed VCG truthfulness fraction of 0.965',
    );
    expect(detail).toHaveTextContent(
      "measured vcg_truthful_fraction=0.965 over 150 trials",
    );
    expect(detail).toHaveTextContent(
      "cluster cl-iter-2026-06-05-004, KILLED 2026-08-15 (redteam_fatal_flaw)",
    );
  });

  it("renders the killed-cluster consequence with the footnote demoted", () => {
    renderCard([POINTED]);
    fireEvent.click(screen.getByTestId("owe-expand-0"));
    const detail = screen.getByTestId("owe-detail-0");
    expect(detail).toHaveTextContent("does NOT reopen the cluster");
    expect(detail).toHaveTextContent("settles the historical record");
    // Softened calibration claim (no automated scorer joins loop_feedback
    // to calibration entries — the join is manual today).
    expect(detail).toHaveTextContent("that join is manual today");
    expect(detail).toHaveTextContent(
      "reopening needs new evidence (redteam_proceed_on_revision)",
    );
  });

  it("renders all five pointed probes as VET FIRST bullets, values inline", () => {
    renderCard([POINTED]);
    fireEvent.click(screen.getByTestId("owe-expand-0"));
    const detail = screen.getByTestId("owe-detail-0");
    const bullets = within(detail).getAllByRole("listitem");
    expect(bullets).toHaveLength(5);
    expect(bullets[0]).toHaveTextContent("killed by the OLD redteam prompt");
    expect(bullets[0]).toHaveTextContent("6/7 parsed known-good fixtures");
    expect(bullets[1]).toHaveTextContent(
      "pre-debate-era row: no independent skeptic ever saw this",
    );
    expect(bullets[2]).toHaveTextContent(
      "does vcg_truthful_fraction=0.965 actually discriminate",
    );
    expect(bullets[4]).toHaveTextContent("also holds iter-2026-06-19-011");
  });
});

// ── Frozen ages (flagged residual, fixed 2026-08-18) ───────────────────────
// Under pollhub change detection + memo the card re-renders only when the
// queue payload CHANGES, so a Date.now()-at-render age chip froze at the
// last data change. The chip now self-ticks: a 30 s useNow scoped to the
// LiveAgeChip leaf (the OweStrip pattern, kept local) — the row list itself
// never re-renders for a clock advance. `nowMs` still pins the tests above.
describe("OweCard ages advance without a data change", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("a row's age chip ticks forward while the payload stays identical", async () => {
    vi.useFakeTimers();
    const TEN_MIN = 10 * 60_000;
    render(
      <MemoryRouter>
        {/* no nowMs: the leaf's own 30 s clock must drive the label */}
        <OweCard
          initial={[
            {
              ...FRESH_VALID,
              since: new Date(Date.now() - TEN_MIN).toISOString(),
            },
          ]}
        />
      </MemoryRouter>,
    );
    const chip = screen.getByTestId("owe-age-0");
    expect(chip).toHaveTextContent("10m");
    // Two minutes pass with NO refetch (fixture mode): the age must advance
    // anyway — this read "10m" forever before the fix.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60_000);
    });
    expect(chip).toHaveTextContent("12m");
  });
});

// ── Typography polish (owner live feedback 2026-08-18: "the text and font is
// all over the place" — their pasted card showed the full hypothesis + stats
// blob as the TITLE) ─────────────────────────────────────────────────────────
describe("OweCard (typography polish 2026-08-18)", () => {
  const WALL_TITLE =
    "Cognitive load forces truthful VCG bidding under bounded rationality. " +
    "Experiment exp004 measured vcg_truthful_fraction=0.965 over 150 trials " +
    "and the idea ledger folded it into cluster cl-x with evidence L2 while " +
    "the redteam verdict was fatal_flaw on the pre-battery prompt.";

  it("the row title is the SHORT claim head — first sentence, never the wall", () => {
    renderCard([{ ...FRESH_VALID, title: WALL_TITLE }]);
    expect(
      screen.getByText(
        "Cognitive load forces truthful VCG bidding under bounded rationality.",
      ),
    ).toBeInTheDocument();
    // The stats tail never renders in the header — it belongs to the
    // expanded WHAT YOU'RE DOING copy.
    expect(
      screen.queryByText(new RegExp("measured vcg_truthful_fraction=0.965")),
    ).toBeNull();
  });

  it("an un-sentenced >120-char title truncates with an ellipsis", () => {
    const noSentence = "x".repeat(200); // no sentence boundary at all
    renderCard([{ ...FRESH_VALID, title: noSentence }]);
    const head = screen.getByText(/^x+…$/);
    expect(head.textContent!.length).toBeLessThanOrEqual(120);
  });

  it("the resolve command is one line until clicked, with a copy affordance", () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    });
    renderCard([OLD_SUPERSEDED]);
    fireEvent.click(screen.getByTestId("owe-expand-0"));
    const cmd = screen.getByTestId("owe-resolve-0");
    expect(cmd).toHaveAttribute("data-expanded", "false");
    fireEvent.click(cmd);
    expect(cmd).toHaveAttribute("data-expanded", "true");
    fireEvent.click(cmd);
    expect(cmd).toHaveAttribute("data-expanded", "false");
    fireEvent.click(screen.getByTestId("owe-copy-0"));
    expect(write).toHaveBeenCalledWith(OLD_SUPERSEDED.resolve_command);
  });

  it("the header line names everything that renders (state gates included)", () => {
    renderCard([]);
    expect(screen.getByTestId("owe-strip").textContent).toContain(
      "gate verdicts, blocking state gates + findings that cleared L4",
    );
  });
});

describe("OweCard (inherited OweStrip pins)", () => {
  it("below-bar findings stay a muted info line, never rows", () => {
    renderCard([
      OLD_SUPERSEDED,
      { kind: "finding_review", id: "sf-legacy-001", title: "pre-ladder finding" },
    ]);
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");
    expect(screen.getByTestId("owe-below-bar")).toHaveTextContent(
      "1 below-bar finding demoted to the ladder",
    );
    expect(screen.getByTestId("owe-strip").textContent).not.toContain(
      "pre-ladder finding",
    );
  });

  it("empty owed queue is the designed, honest empty state", () => {
    renderCard([]);
    expect(screen.getByTestId("owe-empty")).toHaveTextContent(
      "Nothing owed — the loop is unblocked.",
    );
  });

  it("malformed rows degrade (non-object entries dropped, never a crash)", () => {
    renderCard([null, 42, ["array-row"], FRESH_VALID] as unknown as HumanTodoItem[]);
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");
  });
});
