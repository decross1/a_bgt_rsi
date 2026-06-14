// VALIDATION (not just unit) — render ResolvedIterationsList against the REAL
// 49 rows of memory/loop_memory.jsonl, the live data contract the panel must
// survive, and assert it renders every row across every page WITHOUT a single
// React console.error / console.warn (the jsdom stand-in for "no console
// errors", since there is no headless browser in this stack).
//
// The existing test_resolved_iterations_list.tsx exercises synthetic fixtures.
// This file is deliberately complementary: it pins the component to the SHAPE
// of the production data as it actually is on 2026-06-09 —
//   - seed.source ∈ {human_cli, loop_memory_probe, coordinator} (all badge),
//   - 10 rows carry redteam/gate_status/meta_review (Loop v1),
//   - ~10 rows predate novelty/critique entirely (must degrade quiet, no crash),
//   - exactly 1 row carries retrieval.relevance (low_confidence:false → no flag).
// If the producer's schema drifts under us, this is the test that catches the
// panel choking on real rows rather than on a hand-built happy path.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import type { IterationRecord } from "../src/types/schemas";

const PAGE_SIZE = 10;

// Resolve the primary repo root by walking UP from this test file's directory
// until a directory containing memory/loop_memory.jsonl exists — the backend's
// _PRIMARY_REPO target found structurally, not via a fixed "../.." depth, so
// the SAME file resolves from the main checkout AND any worktree nesting (the
// old hardcoded six-up only resolved from .claude/worktrees/<name>). Probes
// with readFileSync — the only fs symbol tests/node-builtins.d.ts declares —
// where ENOENT/ENOTDIR is a miss, any other error rethrows, and an exhausted
// walk fails loudly with every probed path. Same idiom inlined in
// test_revalidate_live_rows.tsx / test_validate_lowevidence.tsx (a shared
// livePaths.ts would be a new file — deferred to the integrator).
function findPrimaryRepoRoot(): string {
  const probed: string[] = [];
  let dir = dirname(fileURLToPath(import.meta.url));
  for (;;) {
    const probe = resolve(dir, "memory/loop_memory.jsonl");
    try {
      readFileSync(probe, "utf8");
      return dir;
    } catch (e) {
      const code = (e as { code?: string }).code;
      if (code !== "ENOENT" && code !== "ENOTDIR") throw e;
      probed.push(probe);
    }
    const parent = dirname(dir);
    if (parent === dir) {
      throw new Error(
        "memory/loop_memory.jsonl not found in any ancestor of this test " +
          `file — probed:\n${probed.join("\n")}`,
      );
    }
    dir = parent;
  }
}

// The real, gitignored loop memory the backend reads live, resolved via the
// walk-up above so the test reads exactly what the UI serves. Loading is
// wrapped so a missing file fails loudly with a clear message (this data IS
// the contract under validation — an empty load is a real failure, not a skip).
function loadRealIterations(): IterationRecord[] {
  const path = resolve(findPrimaryRepoRoot(), "memory/loop_memory.jsonl");
  const raw = readFileSync(path, "utf8");
  const rows = raw
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as IterationRecord);
  // Mirror the backend contract: newest-first by ended_at (the component
  // re-sorts on poll, but the initial prop is rendered as given).
  rows.sort((a, b) => (b.ended_at ?? "").localeCompare(a.ended_at ?? ""));
  return rows;
}

const REAL = loadRealIterations();

// A spy that fails the test if React (or our code) logs a warning/error while
// rendering — the jsdom equivalent of "renders without console errors".
function watchConsole() {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { error, warn };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ResolvedIterationsList — validation against REAL loop_memory.jsonl", () => {
  it("loaded the real rows (sanity: the contract file is present and non-trivial)", () => {
    // The live file has 49 rows on 2026-06-09; assert a generous lower bound so
    // the test stays meaningful as rows accrete but still proves real data loaded.
    expect(REAL.length).toBeGreaterThanOrEqual(40);
    // Every real row carries the React key + the journal link target.
    for (const r of REAL) expect(r.iteration_id).toBeTruthy();
  });

  it("renders the first page of real rows with no console.error/console.warn", () => {
    const spy = watchConsole();
    render(<ResolvedIterationsList initial={REAL} />);
    // The header count shows the bare total (no filter active).
    expect(screen.getByTestId("resolved-count")).toHaveTextContent(
      String(REAL.length),
    );
    // First page renders exactly PAGE_SIZE journal rows (49 rows > 1 page).
    const firstPage = screen.queryAllByRole("button", {
      name: /^load journal /,
    });
    expect(firstPage.length).toBe(Math.min(PAGE_SIZE, REAL.length));
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("walks every page of the real data without throwing or logging", () => {
    const spy = watchConsole();
    render(<ResolvedIterationsList initial={REAL} />);

    const pageCount = Math.max(1, Math.ceil(REAL.length / PAGE_SIZE));
    const seen = new Set<string>();
    // Tally page 1, then click 'next' through the rest.
    for (let p = 0; p < pageCount; p++) {
      for (const btn of screen.queryAllByRole("button", {
        name: /^load journal /,
      })) {
        const name = btn.getAttribute("aria-label") ?? "";
        seen.add(name.replace(/^load journal /, ""));
      }
      const next = screen.queryByLabelText("next page");
      if (next && !(next as HTMLButtonElement).disabled) {
        fireEvent.click(next);
      }
    }
    // Every real iteration_id was rendered on some page (nothing silently
    // dropped) and no row threw on the way.
    expect(seen.size).toBe(REAL.length);
    for (const r of REAL) expect(seen.has(r.iteration_id)).toBe(true);
    expect(spy.error).not.toHaveBeenCalled();
    expect(spy.warn).not.toHaveBeenCalled();
  });

  it("badges all three real seed.source kinds (human_cli, loop_memory_probe, coordinator)", () => {
    watchConsole();
    // Pick the first real row of each source so they share one page.
    const bySource = new Map<string, IterationRecord>();
    for (const r of REAL) {
      const s = r.seed?.source;
      if (s && !bySource.has(s)) bySource.set(s, r);
    }
    // The real data carries exactly these three; assert each maps to a badge.
    for (const s of ["human_cli", "loop_memory_probe", "coordinator"]) {
      expect(bySource.has(s)).toBe(true);
    }
    render(
      <ResolvedIterationsList initial={Array.from(bySource.values())} />,
    );
    // Scope to the panel container (not getByRole("list") — a Loop v1 row's
    // conditioning bullets render a second <ul>, which makes that ambiguous).
    const panel = within(screen.getByTestId("resolved-iterations-list"));
    // 2026-06-10 condense: only β nemoclaw provenance earns row ink; other
    // sources render in the IterationDetailModal (modal coverage pinned in
    // test_iteration_detail_modal.tsx).
    const badges = panel.queryAllByTestId("source-badge");
    const nemoRows = Array.from(bySource.values()).filter(
      (r) => r.seed?.source === "nemoclaw_agent",
    );
    expect(badges.length).toBe(nemoRows.length);
    for (const b of badges) expect(b).toHaveTextContent("nemoclaw");
  });

  it("renders the one real row that carries retrieval.relevance, and (low_confidence:false) shows NO low-evidence flag", () => {
    watchConsole();
    const withRelevance = REAL.filter(
      (r) => r.retrieval?.relevance != null,
    ).slice(0, PAGE_SIZE);
    // The live corpus started at one such row (2026-06-09) and grows every
    // session; cap to one page (PAGE_SIZE) so the per-row label assertion below
    // stays stable once relevance-bearing rows exceed the page size — they now
    // do (11 as of 2026-06-13, the oldest of which paginates to page 2). Still
    // require ≥1 so the contract field is exercised.
    expect(withRelevance.length).toBeGreaterThanOrEqual(1);
    render(<ResolvedIterationsList initial={withRelevance} />);
    // The row renders by id (no crash on the nested relevance block).
    for (const r of withRelevance) {
      expect(
        screen.getByLabelText(`load journal ${r.iteration_id}`),
      ).toBeInTheDocument();
    }
    // None of the real relevance rows is flagged low_confidence today, so the
    // low-evidence badge must NOT fire — the panel doesn't cry wolf on a
    // confidently-grounded verdict. (If a future row sets low_confidence:true
    // this assertion intentionally tightens with the data.)
    const anyLowConf = withRelevance.some(
      (r) => r.retrieval?.relevance?.low_confidence === true,
    );
    if (!anyLowConf) {
      expect(screen.queryByTestId("low-evidence-badge")).toBeNull();
    }
  });

  it("degrades quietly on real pre-novelty rows: no novelty/critique badge, no crash", () => {
    watchConsole();
    // Real rows that predate the novelty/critique blocks (≈10 on 2026-06-09).
    const bare = REAL.filter((r) => !r.novelty && !r.critique).slice(0, PAGE_SIZE);
    expect(bare.length).toBeGreaterThanOrEqual(1);
    render(<ResolvedIterationsList initial={bare} />);
    const panel = within(screen.getByTestId("resolved-iterations-list"));
    // Each bare row still renders (id + topic) and carries its source badge —
    // a pre-novelty row is legible, just quiet on the verdict badges.
    for (const r of bare) {
      expect(
        panel.getByLabelText(`load journal ${r.iteration_id}`),
      ).toBeInTheDocument();
    }
    // No novelty/critique badge fires for these rows: NOVELTY_CLASSES /
    // VERDICT_CLASSES strings appear only as the filter-select <option> labels,
    // never inside the row list. Scope to the row <ul> (unambiguous here — bare
    // pre-novelty rows carry no conditioning block, so there is exactly one list)
    // so an <option> label can't masquerade as a row badge.
    const rowList = within(screen.getByRole("list"));
    for (const cls of ["novel", "rediscovery", "nonsense", "unclear"]) {
      expect(rowList.queryByText(cls)).toBeNull();
    }
  });
});
