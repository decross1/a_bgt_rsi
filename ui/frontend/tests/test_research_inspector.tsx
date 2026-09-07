import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import ResearchInspector from "../src/components/ladder/ResearchInspector";
import { researchContextsForRecord } from "../src/components/ladder/researchContext";
import { buildThesisFamilies } from "../src/components/ladder/thesisModel";
import type { LadderCluster } from "../src/types/schemas";

const claims = [
  {
    id: "iter-2026-08-16-003",
    claim: "In a liquid democracy model, a smaller spectral gap in the delegation transition matrix results in higher transient variance of the Gini coefficient during the convergence phase towards the stationary distribution.",
    topic: "Representation in Peer Selection: A Liquid Democracy Perspective",
    endedAt: "2026-08-16T02:03:15.949832Z",
    review: "2026-09-06T15:41:30.626927Z",
  },
  {
    id: "iter-2026-08-17-014",
    claim: "In liquid democracy networks, high local clustering coefficients decrease the effective representation of minority nodes by concentrating delegated weight through reinforced transitive paths, rather than diluting it through redundancy.",
    topic: "Representation in Peer Selection: A Liquid Democracy Perspective",
    endedAt: "2026-08-17T04:39:17.771385Z",
    review: "2026-09-06T16:16:05.785832Z",
  },
  {
    id: "iter-2026-08-24-006",
    claim: "In liquid democracy networks, an increase in the eigenvector centrality of a subset of delegates leads to higher systemic volatility because the rapid convergence of delegated weights reduces the time-to-equilibrium following stochastic preference shifts.",
    topic: "Power in Liquid Democracy: A Network Centrality Approach",
    endedAt: "2026-08-24T09:12:32.047580Z",
    review: "2026-09-06T16:16:05.785832Z",
  },
] as const;

const clusters: LadderCluster[] = claims.map((claim, index) => ({
  cluster_id: `cl-${claim.id}`,
  stem: claim.claim,
  status: "open",
  evidence_level: "L1",
  origin: "consolidation",
  members: [claim.id],
  last_event_ts: [
    "2026-08-16T02:03:28.689931Z",
    "2026-08-17T05:00:14.365960Z",
    "2026-08-24T09:12:46.387744Z",
  ][index],
}));

const rows = claims.map((claim, index) => ({
  iteration_id: claim.id,
  started_at: claim.endedAt,
  ended_at: claim.endedAt,
  seed: { topic: claim.topic, source: "coordinator" },
  gate_status: "pending",
  hypothesis: { text: claim.claim },
  retrieval: {
    relevance: {
      relevance: index === 2 ? 0.5884 : 1,
      low_confidence: false,
      reason: `Exact recorded retrieval reason ${index + 1}`,
    },
  },
  novelty: { class: "novel", rationale: `Exact recorded novelty rationale ${index + 1}` },
  critique: { verdict: index === 2 ? "survives_debate" : "survives", rationale: `Exact recorded critique rationale ${index + 1}` },
  redteam: {
    verdict: "proceed",
    critique: index === 2
      ? "The hypothesis risks conflating 'speed of convergence' with 'volatility'."
      : "(sub-agent emitted schema-mismatched output; defaulting to proceed)",
    subagent_status: index === 2 ? "passed" : "schema_mismatch",
  },
  experiment_outcome: null,
}));

function liquidFamily() {
  return buildThesisFamilies(clusters, rows).families.find(
    (family) => family.id === "collection:liquid-democracy",
  )!;
}

describe("ResearchInspector", () => {
  it("shows the three exact Liquid Democracy claims together with independent unknown axes", () => {
    render(
      <MemoryRouter>
        <ResearchInspector
          family={liquidFamily()}
          agenda={[]}
          nextOwed={{ L1: "experiment_outcome with trials >= 30" }}
          nowMs={Date.parse("2026-09-07T20:00:00Z")}
        />
      </MemoryRouter>,
    );

    const overview = screen.getByTestId("research-claim-overview");
    expect(overview).toHaveAttribute("data-claim-count", "3");
    expect(overview).toHaveAttribute("data-featured-claim-count", "3");
    expect(overview).toHaveTextContent("Three distinct recorded claims");
    expect(overview).toHaveAttribute("data-family-record-count", "3");
    expect(overview).toHaveTextContent("3 family records · 3 received claim entries · 3 pinned claim summaries · 0 other histories");

    for (const [index, claim] of claims.entries()) {
      const label = [
        "Spectral gap → transient Gini variance",
        "Clustering → minority representation",
        "Centrality → convergence → volatility",
      ][index];
      const summary = screen.getByRole("button", {
        name: `Inspect exact claim record cl-${claim.id}, iteration ${claim.id}: ${label}`,
      });
      expect(summary).toHaveAttribute("aria-expanded", "false");
      expect(summary).toHaveTextContent(claim.endedAt);
      expect(summary).toHaveTextContent("application fit unmapped · evidence validity unknown · execution mode unknown");
      fireEvent.click(summary);
      expect(summary).toHaveAttribute("aria-expanded", "true");
      const card = screen.getByTestId(`research-claim-${claim.id}`);
      expect(card).toHaveTextContent(claim.claim);
      expect(card).toHaveTextContent(claim.endedAt);
      expect(card).toHaveTextContent(claim.review);
      expect(within(card).getByTestId("axis-claim-standing")).toHaveTextContent("open · L1");
      expect(within(card).getByTestId("axis-application-fit")).toHaveTextContent("Unmapped");
      expect(within(card).getByTestId("axis-evidence-validity")).toHaveTextContent("Unknown");
      expect(within(card).getByTestId("axis-execution-mode")).toHaveTextContent("Unknown");
      expect(within(card).getByTestId("evidence-delta")).toHaveTextContent("Not established");
      expect(within(card).getByTestId("evidence-delta")).toHaveTextContent("not supplied in the received projection");
      expect(within(card).getByText("Dated engineering proposal · 2026-09-07 · not adopted protocol")).toBeVisible();
      expect(within(card).getByText("Stage requirement (generic), not a claim-specific accepted test")).toBeVisible();
      expect(within(card).getByRole("link", { name: `Open full dossier for ${claim.id}` })).toHaveAttribute("href", `/dossier/${claim.id}`);
      expect(card).toHaveTextContent(`Exact recorded retrieval reason ${index + 1}`);
      expect(card).toHaveTextContent("Recorded producer review · direction not inferred");
      expect(card).toHaveTextContent([
        "analytical preflight supplied a conditional counterexample",
        "red-team proceed was defaulted after a schema mismatch",
        "faster convergence and volatility are distinct",
      ][index]);
    }

    const lastCard = screen.getByTestId(`research-claim-${claims[2].id}`);
    expect(lastCard).toHaveTextContent("Exact recorded critique rationale 3");
    expect(screen.getAllByText("Dated blocker assessment · 2026-09-07")).toHaveLength(1);
    expect(screen.getAllByText("Dated decision proposal · 2026-09-07 · not a ruling")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Pending suggestions and ruling history" })).toHaveAttribute(
      "href",
      "/model-io#research-suggestions",
    );
  });

  it("keeps exact-claim summaries consistent with explicitly supplied application and execution fields", () => {
    const mappedRows = rows.map((row, index) => index === 0
      ? {
          ...row,
          application_fit: { status: "mapped", reason: "governance simulation" },
          execution_mode: "simulation",
        }
      : row);
    const family = buildThesisFamilies(clusters, mappedRows).families.find(
      (candidate) => candidate.id === "collection:liquid-democracy",
    )!;

    render(
      <MemoryRouter>
        <ResearchInspector family={family} agenda={[]} nextOwed={{ L1: "run comparison" }} nowMs={0} />
      </MemoryRouter>,
    );

    const summary = screen.getByRole("button", {
      name: "Inspect exact claim record cl-iter-2026-08-16-003, iteration iter-2026-08-16-003: Spectral gap → transient Gini variance",
    });
    expect(summary).toHaveTextContent("application fit supplied · evidence validity unknown · execution mode supplied");
    expect(summary).not.toHaveTextContent("application fit unmapped");
    fireEvent.click(summary);
    const detail = screen.getByTestId("research-selected-detail");
    expect(within(detail).getByTestId("axis-application-fit")).toHaveTextContent("Recorded source: mapped · governance simulation");
    expect(within(detail).getByTestId("axis-execution-mode")).toHaveTextContent("Recorded source: simulation");
    expect(within(detail).getByTestId("axis-evidence-validity")).toHaveTextContent("Unknown");
  });

  it("foregrounds three exact claims in a current-shape 80-record family and bounds the other 77 histories", () => {
    const otherClusters: LadderCluster[] = Array.from({ length: 77 }, (_, index) => {
      const id = `iter-other-${String(index + 1).padStart(3, "0")}`;
      const killed = index === 76;
      return {
        cluster_id: `cl-${id}`,
        stem: `Other Liquid Democracy history ${index + 1}`,
        status: killed ? "killed" : "open",
        evidence_level: "L0",
        origin: "consolidation",
        members: [id],
        last_event_ts: "2026-08-01T00:00:00Z",
        kill_reason: killed ? { code: "recorded_negative", detail: "Pinned synthetic negative history" } : null,
        reopening_condition: killed ? { requires: "new_evidence" } : null,
      };
    });
    const otherRows = otherClusters.map((cluster, index) => ({
      iteration_id: cluster.members?.[0],
      ended_at: "2026-08-01T00:00:00Z",
      seed: { topic: claims[index % claims.length].topic },
      hypothesis: { text: `Other recorded hypothesis ${index + 1}` },
      experiment_outcome: null,
    }));
    const family = buildThesisFamilies([...clusters, ...otherClusters], [...rows, ...otherRows]).families.find(
      (candidate) => candidate.id === "collection:liquid-democracy",
    )!;
    expect(family.records).toHaveLength(80);

    render(
      <MemoryRouter>
        <ResearchInspector family={family} agenda={[]} nextOwed={{ L0: "record retrieval evidence", L1: "run comparison" }} nowMs={0} />
      </MemoryRouter>,
    );

    const overview = screen.getByTestId("research-claim-overview");
    expect(overview).toHaveAttribute("data-claim-count", "80");
    expect(overview).toHaveAttribute("data-featured-claim-count", "3");
    expect(overview).toHaveAttribute("data-family-record-count", "80");
    expect(overview).toHaveTextContent("80 family records · 80 received claim entries · 3 pinned claim summaries · 77 other histories");
    expect(screen.getAllByTestId(/^research-claim-summary-/)).toHaveLength(3);
    expect(screen.queryByTestId("research-selected-detail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("research-other-histories")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open full dossier for iter-other/ })).not.toBeInTheDocument();

    const pinnedSummary = screen.getByRole("button", {
      name: "Inspect exact claim record cl-iter-2026-08-16-003, iteration iter-2026-08-16-003: Spectral gap → transient Gini variance",
    });
    fireEvent.click(pinnedSummary);
    expect(pinnedSummary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("research-selected-detail")).toHaveTextContent(claims[0].claim);

    const historyDisclosure = screen.getByRole("button", { name: "Show 77 other recorded histories" });
    expect(historyDisclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(historyDisclosure);
    expect(historyDisclosure).toHaveAttribute("aria-expanded", "true");
    const historyBrowser = screen.getByTestId("research-other-histories");
    expect(within(historyBrowser).getAllByRole("button", { name: /Inspect other history/ })).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "Next histories" }));
    expect(pinnedSummary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("research-selected-detail")).toHaveTextContent(claims[0].claim);
    fireEvent.click(screen.getByRole("button", { name: "Previous histories" }));
    expect(pinnedSummary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("research-selected-detail")).toHaveTextContent(claims[0].claim);
    fireEvent.click(screen.getByRole("button", { name: "Last histories" }));
    expect(pinnedSummary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("research-selected-detail")).toHaveTextContent(claims[0].claim);
    expect(within(historyBrowser).queryByTestId("research-selected-history-detail")).not.toBeInTheDocument();

    fireEvent.click(within(historyBrowser).getByRole("button", {
      name: "Inspect other history record cl-iter-other-077, iteration iter-other-077: Other Liquid Democracy history 77",
    }));
    const selectedHistory = screen.getByTestId("research-selected-history-detail");
    expect(selectedHistory).toHaveTextContent("Pinned synthetic negative history");
    expect(within(selectedHistory).getByRole("link", { name: "Open full dossier for iter-other-077" })).toBeVisible();
    expect(pinnedSummary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("research-selected-detail")).toHaveTextContent(claims[0].claim);

    fireEvent.click(historyDisclosure);
    expect(screen.queryByTestId("research-other-histories")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open full dossier for iter-other-077" })).not.toBeInTheDocument();
  });

  it("keeps shared-iteration summaries distinct by source record identity", () => {
    const family = buildThesisFamilies(
      [
        { cluster_id: "cl-shared-a", stem: "Shared record A", status: "open", evidence_level: "L0", members: ["iter-shared"] },
        { cluster_id: "cl-shared-b", stem: "Shared record B", status: "killed", evidence_level: "L0", members: ["iter-shared"] },
      ],
      [{
        iteration_id: "iter-shared",
        ended_at: "2026-08-30T00:00:00Z",
        seed: { topic: "Shared source topic" },
        hypothesis: { text: "One iteration referenced by two distinct records." },
      }],
    ).families.find((candidate) => candidate.id === "topic:Shared source topic")!;
    expect(family.records).toHaveLength(2);

    render(
      <MemoryRouter>
        <ResearchInspector family={family} agenda={[]} nextOwed={{}} nowMs={0} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show 2 recorded entries" }));
    expect(screen.getByRole("button", {
      name: "Inspect recorded entry record cl-shared-a, iteration iter-shared: Shared record A",
    })).toBeVisible();
    expect(screen.getByRole("button", {
      name: "Inspect recorded entry record cl-shared-b, iteration iter-shared: Shared record B",
    })).toBeVisible();
  });

  it("does not attach a claim-specific proposal when an exact ID has changed hypothesis bytes", () => {
    const family = liquidFamily();
    const changed = {
      ...family.records[0],
      iterations: [{
        ...family.records[0].iterations[0],
        hypothesis: `${family.records[0].iterations[0].hypothesis} changed`,
      }],
    };

    render(
      <MemoryRouter>
        <ResearchInspector record={changed} agenda={[]} nextOwed={{ L1: "generic L1 debt" }} nowMs={0} />
      </MemoryRouter>,
    );

    expect(screen.queryByText("Dated engineering proposal · 2026-09-07 · not adopted protocol")).not.toBeInTheDocument();
    expect(screen.getByText(/No claim-specific accepted test is supplied in this projection/)).toBeVisible();
    expect(screen.getByText("Stage requirement (generic), not a claim-specific accepted test")).toBeVisible();
  });

  it("withholds pinned context for missing, duplicate, or mismatched source identities", () => {
    const base = liquidFamily().records[0];
    const missing = {
      ...base,
      cluster: { ...base.cluster, cluster_id: undefined as unknown as string },
      hasUniqueSourceId: false,
    };
    expect(researchContextsForRecord(missing, {}).every((context) => !context.isPinnedExactClaim)).toBe(true);

    const wrongIteration = {
      ...base,
      iterations: [{ ...base.iterations[0], id: "iter-stale-copy" }],
    };
    expect(researchContextsForRecord(wrongIteration, {}).every((context) => !context.isPinnedExactClaim)).toBe(true);

    const duplicateModel = buildThesisFamilies(
      [base.cluster, { ...base.cluster }],
      [rows[0]],
    );
    expect(duplicateModel.records).toHaveLength(2);
    expect(duplicateModel.records.every((record) => !record.hasUniqueSourceId)).toBe(true);
    expect(duplicateModel.records.flatMap((record) => researchContextsForRecord(record, {}))
      .every((context) => !context.isPinnedExactClaim)).toBe(true);
  });

  it("shows a raw outcome separately while withholding evidence validity and inferred execution mode", () => {
    const family = buildThesisFamilies(
      [{
        cluster_id: "cl-unrelated",
        stem: "Unrelated recorded question",
        status: "surfaced",
        evidence_level: "L4",
        members: ["iter-unrelated"],
        last_event_ts: "2026-09-01T01:02:03Z",
      }],
      [{
        iteration_id: "iter-unrelated",
        ended_at: "2026-09-01T01:00:00Z",
        seed: { topic: "A separate topic" },
        hypothesis: { text: "A separate recorded hypothesis." },
        experiment_outcome: {
          experiment_id: "exp-recorded",
          metric: "score",
          value: 0.7,
          trials: 12,
          summary: "Raw producer summary",
        },
      }],
    ).families[0];

    render(
      <MemoryRouter>
        <ResearchInspector record={family.records[0]} agenda={[]} nextOwed={{ L4: "human validity verdict" }} nowMs={0} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("raw-recorded-outcome")).toHaveTextContent("exp-recorded");
    expect(screen.getByTestId("raw-recorded-outcome")).toHaveTextContent("Raw producer summary");
    expect(screen.getByTestId("axis-evidence-validity")).toHaveTextContent("Unknown");
    expect(screen.getByTestId("axis-execution-mode")).toHaveTextContent("Unknown");
    expect(screen.getByTestId("evidence-delta")).toHaveTextContent("Not established");
    expect(screen.getByTestId("evidence-delta")).toHaveTextContent("not supplied in the received projection");
    expect(screen.getByTestId("axis-application-fit")).toHaveTextContent("Unmapped");
  });
});


describe("independent source presence and bounded history work", () => {
  const fields = ["experiment_outcome", "claim_experiment_binding", "evidence_comparison"] as const;
  const labels = ["Outcome", "Claim/spec/result binding", "Comparison"];
  it.each(Array.from({ length: 8 }, (_, mask) => mask))("reports each field independently for presence mask %i", (mask) => {
    const base = liquidFamily().records[0];
    const source = Object.fromEntries(fields.flatMap((field, i) => (mask & (1 << i)) ? [[field, { marker: field }]] : []));
    const record = { ...base, iterations: [{ ...base.iterations[0], source }] };
    render(<MemoryRouter><ResearchInspector record={record} agenda={[]} nextOwed={{}} nowMs={0} /></MemoryRouter>);
    const delta = screen.getByTestId("evidence-delta");
    labels.forEach((label, i) => expect(delta).toHaveTextContent(`${label}: ${(mask & (1 << i)) ? "object supplied" : "not supplied in the received projection"}`));
    expect(delta).toHaveTextContent("validity is not established");
  });
  it.each([null, [], "malformed", 42, false])("retains present unsupported metadata %j without calling it absent", (value) => {
    const base = liquidFamily().records[0];
    const source = Object.fromEntries(fields.map((field) => [field, value]));
    const record = { ...base, iterations: [{ ...base.iterations[0], source }] };
    render(<MemoryRouter><ResearchInspector record={record} agenda={[]} nextOwed={{}} nowMs={0} /></MemoryRouter>);
    const delta = screen.getByTestId("evidence-delta");
    labels.forEach((label) => expect(delta).toHaveTextContent(`${label}: ${value === null ? "explicit null" : "present with unsupported shape"}`));
    expect(delta).not.toHaveTextContent("not supplied");
    expect(screen.getByTestId("raw-provenance-fields")).toHaveTextContent(JSON.stringify(value));
    expect(screen.getByTestId("axis-evidence-validity")).toHaveTextContent("Unknown");
  });
  it("derives only a finite visible window from 10,000 histories and retains the last entry", () => {
    const base = liquidFamily().records[0];
    let sourceReads = 0;
    const records = Array.from({ length: 10000 }, (_, i) => ({
      ...base, key: `record-${i}`, id: `record-${i}`, title: `History ${i}`,
      cluster: { ...base.cluster, cluster_id: `record-${i}` },
      iterations: [{ ...base.iterations[0], id: `iteration-${i}`, hypothesis: `History ${i}`, source: {
        get experiment_outcome() { sourceReads++; return null; },
      } }],
    }));
    const family = { ...liquidFamily(), id: "topic:large", records };
    render(<MemoryRouter><ResearchInspector family={family} agenda={[]} nextOwed={{}} nowMs={0} /></MemoryRouter>);
    expect(sourceReads).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Show 10000 recorded entries" }));
    expect(screen.getAllByRole("button", { name: /Inspect recorded entry/ })).toHaveLength(10);
    expect(sourceReads).toBeGreaterThan(0);
    expect(sourceReads).toBeLessThanOrEqual(60);
    fireEvent.click(screen.getByRole("button", { name: "Last histories" }));
    expect(screen.getByRole("button", { name: /iteration-9999: History 9999/ })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /Inspect recorded entry/ })).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: /iteration-9999: History 9999/ }));
    expect(screen.getByTestId("research-selected-history-detail")).toHaveTextContent("History 9999");
  });
});
