// DossierIndex (/dossier) — the fetch-owning picker (UI simplification S2, the
// ResolveRail evolution). Pins:
//   1. OWE-FIRST ordering: section (1) carries ONLY the blocking kinds
//      (gate_verdict + state_gate families); section (2) ONLY the findings
//      that clear the L4/L5 ladder bar; section (3) everything else —
//      below-bar/legacy findings, bubbles, stale runs, resolved iterations.
//   2. HONEST empty states: "No L4/L5 findings are listed in the loaded queue source." when no finding
//      clears the bar; a 404 todo feed reads "queue UNKNOWN", never calm.
//   3. STEM CLUSTERING (ported verbatim from ResolveRail): near-dup titles
//      sharing a 6-word prefix collapse to one ×N cluster; expanding lists
//      the members; a search that hits one member surfaces it directly.
//   4. Rows are LINKS into /dossier/:id — the picker exposes NO disposition
//      affordance (the verdict fence).
//   5. The deferred sky chip ports from the retired HumanTodoPanel.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
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

type Oklch = [number, number, number];

function readOklch(source: string, property: string): Oklch {
  const match = source.match(
    new RegExp(`--${property}:\\s*oklch\\(([0-9.]+)\\s+([0-9.]+)\\s+([0-9.]+)`),
  );
  if (!match) throw new Error(`Missing OKLCH property: ${property}`);
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function relativeLuminance([lightness, chroma, hue]: Oklch): number {
  const radians = (hue * Math.PI) / 180;
  const a = chroma * Math.cos(radians);
  const b = chroma * Math.sin(radians);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((channel) => Math.max(0, Math.min(1, channel)));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(first: Oklch, second: Oklch): number {
  const a = relativeLuminance(first);
  const b = relativeLuminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
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
  it("no cleared-bar findings → 'No L4/L5 findings are listed in the loaded queue source.'", () => {
    renderIndex([GATE, LEGACY_FINDING_A]);
    expect(screen.getByTestId("dossier-cleared-empty")).toHaveTextContent(
      "No L4/L5 findings are listed in the loaded queue source.",
    );
  });

  it("nothing listed stays source-scoped; empty history has its own quiet line", () => {
    renderIndex([]);
    expect(screen.getByTestId("dossier-owe-empty")).toHaveTextContent(
      /current queue source/,
    );
    expect(screen.getByTestId("dossier-owe-empty")).not.toHaveTextContent(
      /loop is unblocked/i,
    );
    expect(screen.getByTestId("dossier-else-empty")).toHaveTextContent(
      /no other recorded dossiers/i,
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
    expect(screen.getByLabelText("Find a dossier")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "sf-legacy-002" },
    });
    expect(screen.getByTestId("dossier-history-browser")).toHaveAttribute(
      "open",
    );
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

  it("search keeps source sections and restores every request when cleared", () => {
    renderIndex([GATE, L4_FINDING, BUBBLE]);
    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "zzz-no-match" },
    });
    expect(screen.getByTestId("dossier-owe")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-cleared")).toBeInTheDocument();
    expect(screen.queryByTestId("dossier-row-iter-2026-06-14-002")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dossier-row-sf-l4-001")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("dossier-search"), { target: { value: "" } });
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
    expect(screen.getByTestId("dossier-partial")).toHaveTextContent(
      /displayed counts are partial/i,
    );
    expect(screen.getByTestId("dossier-history-partial")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});

describe("DossierIndex — compact record library", () => {
  it("leads with recorded requests and one latest context while history is collapsed", () => {
    renderIndex([GATE, BUBBLE], [ITER_ROW]);
    expect(screen.getByRole("heading", { name: "Dossiers" })).toBeInTheDocument();
    expect(screen.getByTestId("dossier-source-state")).toHaveTextContent(
      /queue source loaded/i,
    );
    expect(screen.getByTestId("dossier-owe")).toHaveTextContent(/recorded requests/i);
    expect(
      screen.getByTestId("dossier-latest-iter-iter-2026-06-10-001"),
    ).toHaveTextContent("resolved history row");
    expect(screen.getByTestId("dossier-history-browser")).not.toHaveAttribute(
      "open",
    );
  });

  it("keeps exact ids visible in compact decision rows", () => {
    renderIndex([GATE]);
    const row = screen.getByTestId(`dossier-row-${GATE.id}`);
    expect(within(row).getByText(GATE.id)).toBeInTheDocument();
    expect(within(row).getByText("Open dossier")).toBeInTheDocument();
  });

  it("bounds large iteration history and appends pages without losing button focus", () => {
    const rows = Array.from({ length: 121 }, (_, index) => ({
      ...ITER_ROW,
      iteration_id: `iter-2026-06-${String(index + 1).padStart(3, "0")}`,
      ended_at: new Date(Date.UTC(2026, 5, 1, 0, index)).toISOString(),
    })) as IterationRecord[];
    renderIndex([], rows);

    expect(screen.getByTestId("dossier-history-progress")).toHaveTextContent(
      "Showing 50 of 121 matching records",
    );
    const more = screen.getByTestId("dossier-history-more");
    more.focus();
    fireEvent.click(more);
    expect(more).toHaveFocus();
    expect(screen.getByTestId("dossier-history-progress")).toHaveTextContent(
      "Showing 100 of 121 matching records",
    );
    fireEvent.click(more);
    expect(more).toBeDisabled();
    expect(more).toHaveFocus();
    expect(screen.getByTestId("dossier-history-progress")).toHaveTextContent(
      "Showing 121 of 121 matching records",
    );
  });

  it("bounds a 577-row non-iteration archive and keeps an exact source-order match reachable", () => {
    const rows = Array.from({ length: 577 }, (_, index) => ({
      kind: "bubble_ack",
      id: `bubble-archive-${String(index).padStart(3, "0")}`,
      title: `Archived record number ${String(index).padStart(3, "0")}`,
    })) as HumanTodoItem[];
    renderIndex(rows);

    const archive = screen.getByTestId("dossier-else");
    expect(within(archive).getAllByRole("link")).toHaveLength(50);
    expect(screen.getByTestId("dossier-history-progress")).toHaveTextContent(
      "Showing 50 of 577 matching records",
    );
    const more = screen.getByTestId("dossier-history-more");
    more.focus();
    fireEvent.click(more);
    expect(more).toHaveFocus();
    expect(within(archive).getAllByRole("link")).toHaveLength(100);

    fireEvent.change(screen.getByTestId("dossier-search"), {
      target: { value: "bubble-archive-576" },
    });
    expect(within(archive).getAllByRole("link")).toHaveLength(1);
    expect(screen.getByTestId("dossier-row-bubble-archive-576")).toBeVisible();
  });

  it("uses a light-theme normal-text warning token for source-integrity prose", () => {
    renderIndex(
      [GATE, null as unknown as HumanTodoItem],
      [ITER_ROW, null as unknown as IterationRecord],
    );
    for (const testId of ["dossier-partial", "dossier-history-partial"]) {
      const message = screen.getByTestId(testId);
      expect(message).toHaveClass("dossier-integrity-message");
      expect(message).not.toHaveClass("text-amber-600");
    }

    const here = dirname(fileURLToPath(import.meta.url));
    const styles = readFileSync(resolve(here, "../src/routes/dossiers.css"), "utf8");
    const tokens = readFileSync(resolve(here, "../src/design/tokens.css"), "utf8");
    const integrityRule = styles.match(
      /\.dossier-integrity-message\s*\{([^}]+)\}/,
    )?.[1];
    expect(integrityRule).toContain("color: var(--status-warn)");
    for (const background of ["bg", "surface-1"]) {
      expect(
        contrast(
          readOklch(tokens, "status-warn"),
          readOklch(tokens, background),
        ),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("does not call an undated iteration the latest recorded context", () => {
    renderIndex([], [{ ...ITER_ROW, ended_at: "not-a-date" }]);
    expect(screen.getByTestId("dossier-latest-empty")).toHaveTextContent(
      "No iteration has a usable recorded end time.",
    );
  });
});


it("withholds inventory totals while sources are loading or malformed", () => {
  vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
  const pending = render(<MemoryRouter><DossierIndex /></MemoryRouter>);
  expect(screen.getByTestId("dossier-owe-count")).not.toHaveTextContent(/^0$/);
  expect(screen.getByTestId("dossier-latest-count")).not.toHaveTextContent(/^0$/);
  expect(screen.getByTestId("dossier-history-browser")).not.toHaveTextContent("Browse history · 0 recorded items");
  pending.unmount();
  renderIndex(null as unknown as HumanTodoItem[], null as unknown as IterationRecord[]);
  expect(screen.getByTestId("dossier-owe-count")).toHaveTextContent("unknown");
  expect(screen.queryByTestId("dossier-else-empty")).not.toBeInTheDocument();
});

it("searches recorded requests as well as history without claiming current eligibility", () => {
  renderIndex([GATE, STATE_GATE], [ITER_ROW]);
  expect(screen.queryByText(/Live decisions stay visible/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByTestId("dossier-search"), { target: { value: ITER_ROW.iteration_id } });
  expect(within(screen.getByTestId("dossier-owe")).queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByTestId(`dossier-iter-${ITER_ROW.iteration_id}`)).toBeVisible();
  fireEvent.change(screen.getByTestId("dossier-search"), { target: { value: GATE.id } });
  expect(within(screen.getByTestId("dossier-owe")).getAllByRole("link")).toHaveLength(1);
  fireEvent.change(screen.getByTestId("dossier-search"), { target: { value: "" } });
  expect(within(screen.getByTestId("dossier-owe")).getAllByRole("link")).toHaveLength(2);
});
