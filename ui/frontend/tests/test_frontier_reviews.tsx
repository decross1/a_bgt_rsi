// FrontierReviews — the frontier tier (D-061) on /model-io. Load-bearing
// pins:
//
//  1. one line per ledger row: vendor badge, role, verdict chip (veto rose /
//     pass emerald / inconclusive zinc / null "—"), candidate_id, duration,
//     age — all backend passthrough;
//  2. the reasoning_digest expands on click, and rows without one are not
//     pretend-expandable;
//  3. a vendor the BACKEND derived as down gets the amber "VENDOR DOWN?"
//     chip on its rows and only its rows — a dead vendor must never look
//     like a quiet reviewer (the 2026-08-16 codex lesson); nonzero exits
//     show their code;
//  4. the empty ledger is honest: no fake rows, and the note says the
//     promotion screen fires on promotion candidates only.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FrontierReviews, {
  frontierAge,
} from "../src/components/FrontierReviews";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const ROWS = {
  available: true,
  calls: [
    {
      timestamp: minsAgo(2),
      vendor: "codex",
      cli_version: "codex-cli 0.147.0",
      role: "novelty_reviewer",
      verdict: null,
      duration_ms: 35,
      exit_code: 1,
      prompt_sha256: "ab".repeat(32),
    },
    {
      timestamp: minsAgo(10),
      vendor: "claude",
      cli_version: "2.1.233 (Claude Code)",
      role: "methods_reviewer",
      candidate_id: "cand-7",
      verdict: "veto",
      reasoning_digest:
        "The ablation lacks a seed sweep; the effect is within run-to-run variance.",
      duration_ms: 25001,
      exit_code: 0,
      prompt_sha256: "cd".repeat(32),
    },
    {
      timestamp: minsAgo(20),
      vendor: "claude",
      cli_version: "2.1.233 (Claude Code)",
      role: "equivalence_judge",
      verdict: "pass",
      duration_ms: 1874,
      exit_code: 0,
      prompt_sha256: "ef".repeat(32),
    },
  ],
  rows_in_window: 3,
  summary: {
    last_call_ts: minsAgo(2),
    calls_24h: 3,
    consecutive_nonzero_exit_by_vendor: { claude: 0, codex: 4 },
    vendors_down: ["codex"],
    down_streak_threshold: 3,
  },
  window_bytes: 262144,
  window_truncated: false,
  generated_at: new Date().toISOString(),
};

const EMPTY = {
  ...ROWS,
  calls: [],
  rows_in_window: 0,
  summary: {
    last_call_ts: null,
    calls_24h: 0,
    consecutive_nonzero_exit_by_vendor: {},
    vendors_down: [],
    down_streak_threshold: 3,
  },
};

function stubFrontier(body: unknown, status = 200) {
  const mock = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  }) as Response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

// ─── rows ────────────────────────────────────────────────────────────────

it("renders one row per call: vendor badge, role, verdict chips, candidate, duration", async () => {
  stubFrontier(ROWS);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("frontier-row")).toHaveLength(3),
  );
  // Vendor badges verbatim, with distinct local tones (claude fuchsia /
  // codex teal — never the gemma/qwen families).
  const badges = screen.getAllByTestId("vendor-badge");
  expect(badges.map((b) => b.textContent)).toEqual([
    "codex",
    "claude",
    "claude",
  ]);
  expect(badges[0].className).toContain("teal");
  expect(badges[1].className).toContain("fuchsia");
  // Roles + verdicts: veto rose, pass emerald, null an honest dash.
  expect(screen.getByText("novelty_reviewer")).toBeInTheDocument();
  expect(screen.getByText("methods_reviewer")).toBeInTheDocument();
  const chips = screen.getAllByTestId("verdict-chip");
  expect(chips.map((c) => c.textContent)).toEqual(["veto", "pass"]);
  expect(chips[0].className).toContain("rose");
  expect(chips[1].className).toContain("emerald");
  expect(screen.getAllByTestId("verdict-null")).toHaveLength(1);
  // candidate_id (small mono) + duration passthrough.
  expect(screen.getByTestId("candidate-id").textContent).toBe("cand-7");
  expect(screen.getByText("25001ms")).toBeInTheDocument();
  // Summary line derived server-side, passed through.
  expect(screen.getByTestId("frontier-summary").textContent).toContain(
    "3 calls/24h",
  );
});

it("expands the reasoning digest on click, only where one exists", async () => {
  stubFrontier(ROWS);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("frontier-row")).toHaveLength(3),
  );
  expect(screen.queryByTestId("digest-body")).toBeNull();
  const rows = screen.getAllByTestId("frontier-row");
  // Row 0 (codex, no digest) is not expandable.
  fireEvent.click(rows[0]);
  expect(screen.queryByTestId("digest-body")).toBeNull();
  // Row 1 (claude veto) carries the digest.
  fireEvent.click(rows[1]);
  expect(screen.getByTestId("digest-body").textContent).toContain(
    "seed sweep",
  );
  // Click again collapses.
  fireEvent.click(rows[1]);
  expect(screen.queryByTestId("digest-body")).toBeNull();
});

// ─── the vendor-down chip (2026-08-16: a dead vendor must never look like
//     a quiet reviewer) ───────────────────────────────────────────────────

it("marks rows of a backend-derived down vendor with the amber VENDOR DOWN? chip", async () => {
  stubFrontier(ROWS);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("frontier-row")).toHaveLength(3),
  );
  // Exactly the codex row — never the claude rows.
  const downChips = screen.getAllByTestId("vendor-down-chip");
  expect(downChips).toHaveLength(1);
  expect(downChips[0].textContent).toBe("VENDOR DOWN?");
  expect(downChips[0].className).toContain("amber");
  expect(downChips[0].title).toContain("last 4");
  // The nonzero exit is outage evidence, shown as its code.
  const exits = screen.getAllByTestId("exit-chip");
  expect(exits).toHaveLength(1);
  expect(exits[0].textContent).toBe("exit 1");
});

it("shows no down chip when the backend derived none", async () => {
  stubFrontier({
    ...ROWS,
    summary: { ...ROWS.summary, vendors_down: [] },
  });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("frontier-row")).toHaveLength(3),
  );
  expect(screen.queryAllByTestId("vendor-down-chip")).toHaveLength(0);
});

// ─── honest empty / degraded states ──────────────────────────────────────

it("says an empty ledger tail is normal — the screen fires on promotion candidates only", async () => {
  stubFrontier(EMPTY);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("frontier-empty")).toBeInTheDocument(),
  );
  const note = screen.getByTestId("frontier-empty");
  expect(note.textContent).toContain("no frontier calls in the recent tail");
  expect(note.textContent).toContain("promotion candidates only");
  expect(screen.queryAllByTestId("frontier-row")).toHaveLength(0);
});

it("says UNKNOWN (not idle) when the endpoint never loads", async () => {
  stubFrontier({ detail: "Not Found" }, 404);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(
      screen.getByText(/frontier tier state UNKNOWN, not idle/),
    ).toBeInTheDocument(),
  );
});

it("names an absent ledger file honestly", async () => {
  stubFrontier({ ...EMPTY, available: false });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("frontier-absent")).toBeInTheDocument(),
  );
  expect(screen.getByTestId("frontier-absent").textContent).toContain(
    "frontier ledger absent",
  );
});

it("states the tail bound, and flags counts as floors when truncated", async () => {
  stubFrontier({ ...ROWS, window_truncated: true });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("frontier-footnote")).toBeInTheDocument(),
  );
  const note = screen.getByTestId("frontier-footnote");
  expect(note.textContent).toContain("262144 bytes");
  expect(note.textContent).toContain("counts are floors");
});

// ─── frontierAge (compact ages, deterministic via nowMs) ────────────────

it("frontierAge renders compact ages and honest dashes", () => {
  const now = Date.parse("2026-08-18T12:00:00Z");
  expect(frontierAge("2026-08-18T11:59:30Z", now)).toBe("30s");
  expect(frontierAge("2026-08-18T11:55:00Z", now)).toBe("5m");
  expect(frontierAge(null, now)).toBe("—");
  expect(frontierAge("junk", now)).toBe("—");
});
