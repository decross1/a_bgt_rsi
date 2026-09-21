import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ResearchFocusCard, admitResearchFocus } from "../src/components/ResearchFocusCard";
import Ladder from "../src/routes/Ladder";

const sha = (character: string) => character.repeat(64);

function selectedFocus() {
  return {
    schema_version: "research-focus/v1",
    status: "selected",
    focus_id: "disclosed-payoff-competence",
    receipt_sha256: sha("a"),
    title: "Disclosed payoff information and public-goods action competence",
    source_iteration_id: "iter-2026-09-15-007",
    source_record_ordinal: 127,
    source_row_sha256: sha("b"),
    source_campaign_id: "v2-known-opponent-utility-20260915",
    source_campaign_manifest_sha256: sha("c"),
    source_evidence_level: null,
    stage: "needs_clean_refinement",
    next_action: "Rewrite the structured source into one falsifiable hypothesis, then draft the preregistration.",
    blockers: ["The source hypothesis is a raw structured candidate envelope."],
    source_quality: "raw_structured_hypothesis",
    selected_at: "2026-09-20T04:00:00+00:00",
    selected_by: "codex",
    selection_reason: "Advance one agentic game-theory seed through a real study gate.",
    next_gate: {
      from: "research_seed",
      to: "study_ready",
      artifact: "clean hypothesis + preregistration",
      status: "pending",
      owner: "Oracle + Codex",
    },
    intake_policy: "focus_before_new_topics",
    execution_authorized: false,
    evidence_refs: [{ path: "memory/loop_memory.jsonl", iteration_id: "iter-2026-09-15-007", record_ordinal: 127, row_sha256: sha("b") }],
    scientific_credit: "none_selection_only",
  };
}

describe("ResearchFocusCard", () => {
  it("shows one selected seed, its missing artifact, and the authorization boundary", () => {
    render(<MemoryRouter><ResearchFocusCard focus={selectedFocus()} /></MemoryRouter>);
    const card = screen.getByTestId("research-focus-card");
    expect(card).toHaveAttribute("data-focus-status", "selected");
    expect(within(card).getByRole("heading")).toHaveTextContent("Disclosed payoff information");
    expect(card).toHaveTextContent("needs clean refinement · no source rung");
    expect(card).toHaveTextContent("research seed → study ready");
    expect(card).toHaveTextContent("Produce: clean hypothesis + preregistration");
    expect(card).toHaveTextContent("historical seed unverified; no credit inherited");
    expect(card).not.toHaveTextContent("raw hypothesis needs cleanup");
    expect(card).toHaveTextContent("source record #127");
    expect(card).toHaveTextContent("Claim refinement");
    expect(card).toHaveTextContent("Selecting a focus does not advance evidence or inherit source credit.");
    expect(card).not.toHaveTextContent("Execution not authorized");
    expect(within(card).getByRole("link", { name: "Open source dossier →" })).toHaveAttribute(
      "href", "/dossier/iter-2026-09-15-007?research_scope=all",
    );
  });

  it("fails closed when selected focus fields are malformed", () => {
    const malformed = { ...selectedFocus(), receipt_sha256: "bad", title: "Do not trust this title" };
    expect(admitResearchFocus(malformed)).toEqual({ status: "malformed" });
    render(<MemoryRouter><ResearchFocusCard focus={malformed} /></MemoryRouter>);
    expect(screen.getByTestId("research-focus-card")).toHaveAttribute("data-focus-status", "malformed");
    expect(screen.getByText(/did not match its contract/i)).toBeInTheDocument();
    expect(screen.queryByText("Do not trust this title")).not.toBeInTheDocument();
  });

  it("labels a plain source rung as historical derivation rather than new focus credit", () => {
    const plain = {
      ...selectedFocus(),
      source_quality: "plain_hypothesis",
      source_evidence_level: "L1",
    };
    render(<MemoryRouter><ResearchFocusCard focus={plain} /></MemoryRouter>);
    expect(screen.getByTestId("research-focus-card")).toHaveTextContent(
      "L1 historical derived source only",
    );
    expect(screen.getByTestId("research-focus-card")).toHaveTextContent(
      "Selecting a focus does not advance evidence or inherit source credit.",
    );
  });

  it("keeps no-selection and invalid-source states distinct", () => {
    const { rerender } = render(
      <MemoryRouter><ResearchFocusCard focus={{ status: "none", execution_authorized: false }} /></MemoryRouter>,
    );
    expect(screen.getByRole("heading")).toHaveTextContent("No durable research focus selected");
    rerender(
      <MemoryRouter><ResearchFocusCard focus={{ status: "source_invalid", reason: "source binding changed", execution_authorized: false }} /></MemoryRouter>,
    );
    expect(screen.getByRole("heading")).toHaveTextContent("Focus source needs review");
    expect(screen.getByText(/source binding changed/)).toBeInTheDocument();
  });

  it("does not substitute an unrelated campaign thesis when the focus source is absent", () => {
    const ladder = {
      clusters: [{
        cluster_id: "cl-other",
        stem: "Other recorded claim",
        status: "open",
        evidence_level: "L0",
        members: ["iter-other"],
      }],
      counts: { open: 1, surfaced: 0, killed: 0 },
      histogram: { L0: 1, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
      agenda: [],
      next_owed: {},
    };
    const ops = {
      schema: "research-ops-status/v1",
      observed_at: "2026-09-20T04:00:00+00:00",
      research_focus: selectedFocus(),
    };
    render(
      <MemoryRouter>
        <Ladder
          initial={ladder}
          initialIterations={[{ iteration_id: "iter-other", seed: { topic: "Other topic" }, hypothesis: { text: "Other question" } }]}
          initialResearchOps={ops}
        />
      </MemoryRouter>,
    );
    const focus = screen.getByTestId("research-focus-card");
    const boundary = screen.getByTestId("research-selection-boundary");
    expect(focus.compareDocumentPosition(boundary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(boundary).toHaveTextContent("Selected focus is outside this campaign view");
    expect(boundary).toHaveTextContent("An unrelated campaign thesis was not substituted");
    expect(within(boundary).getByRole("link", { name: "Open the source dossier →" })).toHaveAttribute(
      "href", "/dossier/iter-2026-09-15-007?research_scope=all",
    );
    expect(screen.queryByTestId("research-canvas")).toBeNull();
    expect(focus).toHaveTextContent("Disclosed payoff information");
  });

  it("defaults the research canvas to an available selected focus", () => {
    const ladder = {
      clusters: [{ cluster_id: "cl-other", stem: "Other claim", status: "open", evidence_level: "L0", members: ["iter-other"] },
        { cluster_id: "cl-focus", stem: "Focus claim", status: "open", evidence_level: "L0", members: ["iter-2026-09-15-007"] }],
      counts: { open: 2, surfaced: 0, killed: 0 },
      histogram: { L0: 2, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
      agenda: [], next_owed: {},
    };
    const ops = { schema: "research-ops-status/v1", research_focus: selectedFocus() };
    render(<MemoryRouter><Ladder initial={ladder} initialResearchOps={ops} initialIterations={[
      { iteration_id: "iter-other", seed: { topic: "Other topic" }, hypothesis: { text: "Other question" } },
      { iteration_id: "iter-2026-09-15-007", seed: { topic: "Focused topic" }, hypothesis: { text: "Focused question" } },
    ]} /></MemoryRouter>);

    expect(screen.getByTestId("research-canvas-context")).toHaveTextContent("Focused question");
    expect(screen.getByTestId("research-canvas-family-select")).toHaveDisplayValue(/Focused topic/);
  });

  it("lets an exact URL iteration selection win over the selected focus", () => {
    const ladder = {
      clusters: [{ cluster_id: "cl-other", stem: "Other claim", status: "open", evidence_level: "L0", members: ["iter-other"] },
        { cluster_id: "cl-focus", stem: "Focus claim", status: "open", evidence_level: "L0", members: ["iter-2026-09-15-007"] }],
      counts: { open: 2, surfaced: 0, killed: 0 },
      histogram: { L0: 2, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
      agenda: [], next_owed: {},
    };
    const ops = { schema: "research-ops-status/v1", research_focus: selectedFocus() };
    render(<MemoryRouter initialEntries={["/ladder?iteration=iter-other"]}><Ladder
      initial={ladder}
      initialResearchOps={ops}
      initialIterations={[
        { iteration_id: "iter-other", seed: { topic: "Other topic" }, hypothesis: { text: "Other question" } },
        { iteration_id: "iter-2026-09-15-007", seed: { topic: "Focused topic" }, hypothesis: { text: "Focused question" } },
      ]}
    /></MemoryRouter>);

    expect(screen.getByTestId("research-canvas-context")).toHaveTextContent("Other question");
    expect(screen.getByTestId("research-canvas-family-select")).toHaveDisplayValue(/Other topic/);
  });
});
