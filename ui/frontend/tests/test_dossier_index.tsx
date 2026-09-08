// DossierIndex (/dossier) — the fetch-owning picker (UI simplification S2, the
// ResolveRail evolution). Pins:
//   1. OWE-FIRST ordering: section (1) carries ONLY the blocking kinds
//      (gate_verdict + state_gate families); section (2) ONLY the findings
//      that clear the L4/L5 ladder bar; section (3) everything else —
//      below-bar/legacy findings, bubbles, stale runs, resolved iterations.
//   2. HONEST empty states: "Nothing cleared L4 this week." when no finding
//      clears the bar; a 404 todo feed reads "queue UNKNOWN", never calm.
//   3. STEM CLUSTERING (ported verbatim from ResolveRail): near-dup titles
//      sharing a 6-word prefix collapse to one ×N cluster; expanding lists
//      the members; a search that hits one member surfaces it directly.
//   4. Rows are LINKS into /dossier/:id — the picker exposes NO disposition
//      affordance (the verdict fence).
//   5. The deferred sky chip ports from the retired HumanTodoPanel.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DossierIndex from "../src/routes/DossierIndex";
import type { HumanTodoItem, IterationRecord } from "../src/types/schemas";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// No test here fetches — the `items`/`iterations` injections bypass the polls.
// A defensive stub still guards against any stray fetch reaching a backend.
beforeEach(() => {
  vi.stubGlobal("fetch", async () => {
    throw new Error("unstubbed fetch in test_dossier_index");
  });
});

const GATE: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-14-002",
  title: "Verdict needed: novel_on_02 over-gated by primary R0",
  since: "2026-06-14T15:00:00Z",
};
const STATE_GATE: HumanTodoItem = {
  kind: "state_gate",
  id: "gate-d049-ratification",
  title: "State-file gate: D-049 awaits ratification",
};
const L4_FINDING: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-l4-001",
  title: "Finding: shading is dominated under VCG",
  evidence_level: "L4",
};
const LEGACY_FINDING_A: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-legacy-001",
  title: "In repeated public goods games with noisy contribution observation alpha",
};
const LEGACY_FINDING_B: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-legacy-002",
  title: "In repeated public goods games with noisy contribution observation beta",
};
const BUBBLE: HumanTodoItem = {
  kind: "bubble_ack",
  id: "bubble-001",
  title: "Bubble: degraded-signal note",
};
const DEFERRED_ITEM: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-deferred-001",
  title: "A deferred finding",
  deferred: true,
  deferral: { by: "human:ui", note: "revisit after R0 fix" },
};

const ITER_ROW: IterationRecord = {
  iteration_id: "iter-2026-06-10-001",
  started_at: "2026-06-10T10:00:00Z",
  ended_at: "2026-06-10T10:05:00Z",
  seed: { topic: "resolved history row", source: "coordinator" },
  critique: { verdict: "survives" },
  novelty: { class: "novel" },
  gate_status: "valid",
  journal_entry_path: "journal/iterations/x.md",
} as IterationRecord;

function renderIndex(items: HumanTodoItem[], iterations: IterationRecord[] = []) {
  return render(
    <MemoryRouter>
      <DossierIndex items={items} iterations={iterations} />
    </MemoryRouter>,
  );
}

describe("DossierIndex — owe-first sectioning", () => {
  it("routes each item to its section: blocking → owe, L4 finding → cleared, rest → else", () => {
    renderIndex(
      [GATE, STATE_GATE, L4_FINDING, LEGACY_FINDING_A, BUBBLE],
      [ITER_ROW],
    );
    const owe = screen.getByTestId("dossier-owe");
    expect(within(owe).getByTestId("dossier-row-iter-2026-06-14-002")).toBeInTheDocument();
    expect(within(owe).getByTestId("dossier-row-gate-d049-ratification")).toBeInTheDocument();
    expect(within(owe).getByTestId("dossier-owe-count")).toHaveTextContent("2");

    const cleared = screen.getByTestId("dossier-cleared");
    expect(within(cleared).getByTestId("dossier-row-sf-l4-001")).toBeInTheDocument();
    expect(within(cleared).getByTestId("dossier-cleared-count")).toHaveTextContent("1");

    const rest = screen.getByTestId("dossier-else");
    expect(within(rest).getByTestId("dossier-row-sf-legacy-001")).toBeInTheDocument();
    expect(within(rest).getByTestId("dossier-row-bubble-001")).toBeInTheDocument();
    // The L4 finding is NOT double-listed in section 3.
    expect(within(rest).queryByTestId("dossier-row-sf-l4-001")).toBeNull();
    // The resolved iteration renders in the else section's history block.
    expect(
      within(rest).getByTestId("dossier-iter-iter-2026-06-10-001"),
    ).toBeInTheDocument();
  });

  it("rows are LINKS to /dossier/:id — no disposition affordance anywhere", () => {
    renderIndex([GATE, L4_FINDING], [ITER_ROW]);
    const gateRow = screen.getByTestId("dossier-row-iter-2026-06-14-002");
    const link = within(gateRow).getByRole("link");
    expect(link.getAttribute("href")).toBe("/dossier/iter-2026-06-14-002");
    const iterRow = screen.getByTestId("dossier-iter-iter-2026-06-10-001");
    expect(within(iterRow).getByRole("link").getAttribute("href")).toBe(
      "/dossier/iter-2026-06-10-001",
    );
    // The verdict fence: no verdict-shaped buttons exist on the picker.
    for (const re of [/valid/i, /invalid/i, /sign[\s_-]?off/i, /abstain/i]) {
      expect(screen.queryByRole("button", { name: re })).toBeNull();
    }
  });

  it("the ladder level chip renders on a cleared finding row", () => {
    renderIndex([L4_FINDING]);
    const row = screen.getByTestId("dossier-row-sf-l4-001");
    expect(within(row).getByText("L4")).toBeInTheDocument();
  });

  it("the deferred sky chip ports from the retired inbox (with its title bits)", () => {
    renderIndex([DEFERRED_ITEM]);
    const tag = screen.getByTestId("todo-deferred-tag");
    expect(tag).toHaveTextContent(/deferred to dev session/i);
    expect(tag).toHaveTextContent(/revisit after R0 fix/);
  });
});

describe("DossierIndex — honest empty states", () => {
  it("no cleared-bar findings → 'Nothing cleared L4 this week.'", () => {
    renderIndex([GATE, LEGACY_FINDING_A]);
    expect(screen.getByTestId("dossier-cleared-empty")).toHaveTextContent(
      "Nothing cleared L4 this week.",
    );
  });

  it("nothing owed → the unblocked line; empty else → its own quiet line", () => {
    renderIndex([]);
    expect(screen.getByTestId("dossier-owe-empty")).toHaveTextContent(
      /You owe nothing/,
    );
    expect(screen.getByTestId("dossier-else-empty")).toHaveTextContent(
      /nothing else pending/,
    );
  });

  it("a 404 todo feed reads queue UNKNOWN — never a calm empty state", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/human_todo")) {
        return {
          ok: false,
          status: 404,
          statusText: "Not Found",
          json: async () => ({}),
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        statusText: "200",
        json: async () => ({ iterations: [] }),
      } as unknown as Response;
    });
    render(
      <MemoryRouter>
        <DossierIndex />
      </MemoryRouter>,
    );
    const err = await screen.findByTestId("dossier-error");
    expect(err).toHaveTextContent(/queue is UNKNOWN, not empty/);
    // The calm owe-empty line must NOT render off a dead endpoint.
    expect(screen.queryByTestId("dossier-owe-empty")).toBeNull();
    expect(screen.queryByTestId("dossier-cleared-empty")).toBeNull();
  });
});

describe("DossierIndex — stem clustering (ported verbatim from ResolveRail)", () => {
  it("near-dup titles sharing the 6-word stem collapse to one ×N cluster; expanding lists members", () => {
    renderIndex([LEGACY_FINDING_A, LEGACY_FINDING_B]);
    // One cluster, keyed by the first-seen member.
    const cluster = screen.getByTestId("dossier-cluster-sf-legacy-001");
    expect(
      within(cluster).getByTestId("dossier-cluster-count-sf-legacy-001"),
    ).toHaveTextContent("×2");
    // Collapsed: no member rows yet.
    expect(screen.queryByTestId("dossier-row-sf-legacy-001")).toBeNull();
    // Expand → both members appear as linkable rows.
    fireEvent.click(
      screen.getByTestId("dossier-cluster-header-sf-legacy-001"),
    );
    expect(screen.getByTestId("dossier-row-sf-legacy-001")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-row-sf-legacy-002")).toBeInTheDocument();
  });

  it("unrelated titles stay singletons (no false merge)", () => {
    renderIndex([LEGACY_FINDING_A, BUBBLE]);
    expect(screen.queryByTestId("dossier-cluster-sf-legacy-001")).toBeNull();
    expect(screen.getByTestId("dossier-row-sf-legacy-001")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-row-bubble-001")).toBeInTheDocument();
  });

  it("an untitled item buckets by its own id — always its own singleton", () => {
    renderIndex([
      { kind: "bubble_ack", id: "bubble-untitled-1" },
      { kind: "bubble_ack", id: "bubble-untitled-2" },
    ]);
    expect(screen.getByTestId("dossier-row-bubble-untitled-1")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-row-bubble-untitled-2")).toBeInTheDocument();
    expect(screen.queryByTestId("dossier-cluster-bubble-untitled-1")).toBeNull();
  });
});

describe("DossierIndex — search (section 3)", () => {
  it("search hits one cluster member → it surfaces as a singleton (re-cluster on the narrowed set)", () => {
    renderIndex([LEGACY_FINDING_A, LEGACY_FINDING_B]);
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "sf-legacy-002" },
    });
    expect(screen.getByTestId("dossier-row-sf-legacy-002")).toBeInTheDocument();
    expect(screen.queryByTestId("dossier-cluster-sf-legacy-001")).toBeNull();
    expect(screen.queryByTestId("dossier-row-sf-legacy-001")).toBeNull();
  });

  it("search filters the resolved iterations by topic/id too", () => {
    renderIndex([BUBBLE], [ITER_ROW]);
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "resolved history" },
    });
    expect(
      screen.getByTestId("dossier-iter-iter-2026-06-10-001"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("dossier-row-bubble-001")).toBeNull();
    // A no-hit search shows the honest no-match line.
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "zzz-no-match" },
    });
    expect(screen.getByTestId("dossier-else-empty")).toHaveTextContent(
      /no dossiers match/,
    );
  });

  it("search does NOT hide the owe or cleared sections (only section 3 is searchable)", () => {
    renderIndex([GATE, L4_FINDING, BUBBLE]);
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "zzz-no-match" },
    });
    expect(screen.getByTestId("dossier-row-iter-2026-06-14-002")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-row-sf-l4-001")).toBeInTheDocument();
  });
});

describe("DossierIndex — hostile rows degrade", () => {
  it("id-less / non-object todo rows are dropped; a garbled iteration row never crashes", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const hostileItems = [
      GATE,
      null,
      "bare string",
      { kind: "finding_review", title: "no id" },
      { kind: "finding_review", id: "" },
    ] as unknown as HumanTodoItem[];
    const hostileIters = [
      ITER_ROW,
      null,
      { iteration_id: 42, seed: { topic: { o: 1 } } },
    ] as unknown as IterationRecord[];
    const { container } = renderIndex(hostileItems, hostileIters);
    expect(screen.getByTestId("dossier-row-iter-2026-06-14-002")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
