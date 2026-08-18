// FrontierReviews — the frontier tier's SUBSTANCE on /model-io (owner
// rejection 2026-08-18 of the invocation-only panel: "i can't even see what
// their debating issue was"). Load-bearing pins:
//
//  1. the HEALTH STRIP decodes outages per vendor — the real
//     2026-08-18T06:00:43Z rows (claude exit 1 / codex exit 127) read as
//     legible lines ("binary not found (PATH)…"), never mystery rows;
//  2. the feed renders typed cards: screen cards carry cluster + claim head
//     + verdict chip (veto rose / pass emerald / inconclusive amber) + BOTH
//     roles' FULL reasoning behind the payload family's 2-line clamp, which
//     EXPANDS on click; agenda cards carry topic + rationale; refine cards
//     carry round + digest; the cross-run summary line ships when present;
//  3. the old raw invocation table is behind the "plumbing" disclosure,
//     DEFAULT CLOSED (its poll doesn't even run until opened), and opens to
//     the unchanged rows;
//  4. empty / degraded states stay honest (UNKNOWN ≠ idle; empty ≠ outage).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FrontierReviews, {
  frontierAge,
} from "../src/components/FrontierReviews";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

// ─── /api/frontier_reviews fixture (the substance feed) ─────────────────

const METHODS_REASONING =
  "The record contains no experiment at all, yet the claim asserts a " +
  "specific causal mechanism — discriminating between those mechanisms " +
  "requires an ablation that varies history length while holding context " +
  "size fixed; none of these are present in the record.";

const REVIEWS = {
  available: { screen: true, agenda: true, calls: true },
  events: [
    {
      type: "screen",
      ts: minsAgo(2),
      cluster_id: "cl-iter-2026-07-15-001",
      evidence_level: "L1",
      verdict: "veto",
      seconds: 49.7,
      claim_head: "does longer payoff memory drive cooperation gains…",
      roles: {
        methods: {
          verdict: "veto",
          reasoning: METHODS_REASONING,
          vendor: "claude",
          closest_prior_work: "Axelrod 1984",
        },
        novelty: {
          verdict: "pass",
          reasoning: "Fontana et al. varied the gameplay-history window.",
          vendor: "codex",
        },
      },
      cross_run_summary: "the vetoing methods reviewer re-ran on codex: veto",
    },
    {
      type: "refine",
      ts: minsAgo(5),
      cluster_id: "cl-iter-2026-08-15-004",
      round: 2,
      refined_claim_head: "heuristic delegation induces a non-linear…",
      feedback_digest: "methods[veto]: confounded || novelty[pass]: prior",
    },
    {
      type: "agenda",
      ts: minsAgo(9),
      proposal_id: "fa-4b8a1c85",
      proposed_by: "frontier:claude",
      topic: "Run the two L1 synthetic experiments as a paired batch",
      rationale:
        "These are the only two ideas that survived the gates yet both sat " +
        "at 'next: synthetic experiment' for days while the loop mints L0s.",
      status: "proposed",
    },
    {
      type: "screen",
      ts: minsAgo(12),
      cluster_id: "cl-iter-2026-05-27-004",
      evidence_level: "L0",
      verdict: "inconclusive",
      roles: {
        methods: { verdict: "inconclusive", reasoning: "r", vendor: "claude" },
        novelty: { verdict: "pass", reasoning: "n", vendor: "codex" },
      },
    },
  ],
  events_in_window: 4,
  // The REAL 2026-08-18T06:00:43Z outage shape: claude exit 1, codex 127.
  health: {
    claude: {
      calls_24h: 2,
      last_ok_ts: minsAgo(110),
      last_ok_age_s: 6600,
      consecutive_failures: 1,
      last_error: {
        ts: minsAgo(10),
        exit_code: 1,
        decoded: "CLI error (exit 1)",
      },
    },
    codex: {
      calls_24h: 2,
      last_ok_ts: minsAgo(110),
      last_ok_age_s: 6600,
      consecutive_failures: 1,
      last_error: {
        ts: minsAgo(10),
        exit_code: 127,
        decoded: "binary not found (PATH)",
      },
    },
  },
  ledger_join: { ok: true, error: null },
  windows: {
    screen: { bytes: 524288, truncated: false },
    agenda: { bytes: 131072, truncated: false },
    calls: { bytes: 262144, truncated: false },
  },
  generated_at: new Date().toISOString(),
};

// ─── /api/frontier_calls fixture (the plumbing table, unchanged shape) ──

const CALLS = {
  available: true,
  calls: [
    {
      timestamp: minsAgo(10),
      vendor: "claude",
      cli_version: "2.1.143 (Claude Code)",
      role: "methods_reviewer",
      verdict: null,
      duration_ms: 2086,
      exit_code: 1,
      prompt_sha256: "ab".repeat(32),
    },
    {
      timestamp: minsAgo(10),
      vendor: "codex",
      cli_version: "unknown",
      role: "novelty_reviewer",
      verdict: null,
      duration_ms: 0,
      exit_code: 127,
      prompt_sha256: "cd".repeat(32),
    },
  ],
  rows_in_window: 2,
  summary: {
    last_call_ts: minsAgo(10),
    calls_24h: 2,
    consecutive_nonzero_exit_by_vendor: { claude: 1, codex: 1 },
    vendors_down: [],
    down_streak_threshold: 3,
  },
  window_bytes: 262144,
  window_truncated: false,
  generated_at: new Date().toISOString(),
};

function stubBoth(reviews: unknown = REVIEWS, calls: unknown = CALLS) {
  const mock = vi.fn(async (url: unknown) => {
    const u = String(url);
    const body = u.includes("/api/frontier_reviews")
      ? reviews
      : u.includes("/api/frontier_calls")
        ? calls
        : null;
    if (body == null) throw new Error(`unexpected fetch ${u}`);
    return {
      ok: true,
      status: 200,
      statusText: "200",
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubFailing(status = 404) {
  const mock = vi.fn(async () => ({
    ok: false,
    status,
    statusText: String(status),
    json: async () => ({ detail: "nope" }),
  }) as Response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

// ─── the health strip decodes the outage ────────────────────────────────

it("health strip renders one decoded line per vendor for the real outage", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("vendor-health")).toHaveLength(2),
  );
  const decoded = screen.getAllByTestId("health-decoded");
  expect(decoded.map((d) => d.textContent)).toEqual([
    "1 consecutive failure — CLI error (exit 1)",
    "1 consecutive failure — binary not found (PATH)",
  ]);
  // 1-2 failures = amber, never green — and never silent.
  expect(decoded[0].className).toContain("amber");
  expect(decoded[1].className).toContain("amber");
});

it("health strip is green and quiet for a healthy vendor, red at the down streak", async () => {
  stubBoth({
    ...REVIEWS,
    health: {
      claude: { ...REVIEWS.health.claude, consecutive_failures: 0, last_error: null },
      codex: { ...REVIEWS.health.codex, consecutive_failures: 4 },
    },
  });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("vendor-health")).toHaveLength(2),
  );
  const [claude, codex] = screen.getAllByTestId("vendor-health");
  expect(within(claude).queryByTestId("health-decoded")).toBeNull();
  expect(claude.innerHTML).toContain("emerald");
  const codexDecoded = within(codex).getByTestId("health-decoded");
  expect(codexDecoded.className).toContain("rose");
  expect(codexDecoded.textContent).toContain("binary not found (PATH)");
});

// ─── screen cards: verdict chips + expandable full reasoning ────────────

it("screen cards show cluster, claim head, verdict chip tones, and both roles", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("screen-card")).toHaveLength(2),
  );
  const [veto, inconclusive] = screen.getAllByTestId("screen-card");
  expect(veto.textContent).toContain("cl-iter-2026-07-15-001");
  expect(within(veto).getByTestId("screen-claim-head").textContent).toContain(
    "does longer payoff memory",
  );
  const vetoChip = within(veto).getByTestId("screen-verdict-chip");
  expect(vetoChip.textContent).toBe("veto");
  expect(vetoChip.className).toContain("rose");
  // inconclusive is AMBER in the substance feed (owner: the state matters).
  const incChip = within(inconclusive).getByTestId("screen-verdict-chip");
  expect(incChip.textContent).toBe("inconclusive");
  expect(incChip.className).toContain("amber");
  // Both roles present, methods first (D-061 order).
  const roles = within(veto).getAllByTestId("screen-role");
  expect(roles).toHaveLength(2);
  expect(roles[0].textContent).toContain("methods");
  expect(roles[1].textContent).toContain("novelty");
  // The cross-run summary line (D-061: the vetoing role re-ran).
  expect(within(veto).getByTestId("cross-run-summary").textContent).toContain(
    "the vetoing methods reviewer re-ran on codex: veto",
  );
  // No cross-run on the second card → no line.
  expect(within(inconclusive).queryByTestId("cross-run-summary")).toBeNull();
});

it("screen card reasoning is clamped to 2 lines and expands on click", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("screen-card")).toHaveLength(2),
  );
  const card = screen.getAllByTestId("screen-card")[0];
  const methodsRole = within(card).getAllByTestId("screen-role")[0];
  // FULL text is in the DOM (the clamp is visual only — nothing hidden from
  // copy/search), collapsed via the 2-line -webkit clamp.
  const clamped = within(methodsRole).getByTestId("clamped-text");
  expect(clamped.textContent).toBe(METHODS_REASONING);
  expect(clamped.style.webkitLineClamp).toBe("2");
  // Click the payload family's show-more affordance → clamp removed.
  fireEvent.click(within(methodsRole).getByText("show more"));
  expect(clamped.style.webkitLineClamp).toBe("");
  expect(within(methodsRole).getByText("show less")).toBeInTheDocument();
});

// ─── agenda + refine cards ───────────────────────────────────────────────

it("agenda cards carry topic, proposer, and collapsed rationale", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("agenda-card")).toBeInTheDocument(),
  );
  const card = screen.getByTestId("agenda-card");
  expect(card.textContent).toContain(
    "Run the two L1 synthetic experiments as a paired batch",
  );
  expect(card.textContent).toContain("frontier:claude");
  expect(within(card).getByTestId("clamped-text").textContent).toContain(
    "only two ideas that survived",
  );
});

it("refine cards carry round, cluster, claim head, and digest", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("refine-card")).toBeInTheDocument(),
  );
  const card = screen.getByTestId("refine-card");
  expect(card.textContent).toContain("round 2");
  expect(card.textContent).toContain("cl-iter-2026-08-15-004");
  expect(card.textContent).toContain("heuristic delegation induces");
  expect(within(card).getByTestId("clamped-text").textContent).toContain(
    "methods[veto]: confounded",
  );
});

it("feed order follows the backend's newest-first merge", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId(/^(screen|agenda|refine)-card$/)).toHaveLength(4),
  );
  const cards = screen.getAllByTestId(/^(screen|agenda|refine)-card$/);
  expect(cards.map((c) => c.getAttribute("data-testid"))).toEqual([
    "screen-card",
    "refine-card",
    "agenda-card",
    "screen-card",
  ]);
});

// ─── the plumbing disclosure (default closed, opens to the old table) ───

it("plumbing is closed by default and its rows are not rendered or fetched", async () => {
  const mock = stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("screen-card")).toHaveLength(2),
  );
  const details = screen.getByTestId("frontier-plumbing");
  expect(details).not.toHaveAttribute("open");
  expect(screen.queryAllByTestId("frontier-row")).toHaveLength(0);
  // The calls poll never ran while closed.
  const urls = mock.mock.calls.map((c) => String(c[0]));
  expect(urls.some((u) => u.includes("/api/frontier_calls"))).toBe(false);
});

it("opening plumbing fetches and renders the unchanged raw rows", async () => {
  stubBoth();
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getAllByTestId("screen-card")).toHaveLength(2),
  );
  fireEvent.click(screen.getByText(/plumbing — raw CLI invocations/));
  await waitFor(() =>
    expect(screen.getAllByTestId("frontier-row")).toHaveLength(2),
  );
  // The original row content: vendor badge, role, exit chip, null verdict.
  const badges = screen.getAllByTestId("vendor-badge");
  expect(badges.map((b) => b.textContent)).toEqual(["claude", "codex"]);
  const exits = screen.getAllByTestId("exit-chip");
  expect(exits.map((e) => e.textContent)).toEqual(["exit 1", "exit 127"]);
  expect(screen.getAllByTestId("verdict-null")).toHaveLength(2);
  expect(screen.getByTestId("frontier-summary").textContent).toContain(
    "2 calls/24h",
  );
});

// ─── honest empty / degraded states ──────────────────────────────────────

it("says UNKNOWN (not idle) when the reviews endpoint never loads", async () => {
  stubFailing(404);
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(
      screen.getByText(/frontier tier state UNKNOWN,\s*not idle/),
    ).toBeInTheDocument(),
  );
});

it("an empty feed is normal, not an outage; vendor health absent is UNKNOWN", async () => {
  stubBoth({
    ...REVIEWS,
    events: [],
    events_in_window: 0,
    health: {},
  });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("reviews-empty")).toBeInTheDocument(),
  );
  expect(screen.getByTestId("reviews-empty").textContent).toContain(
    "normal, not an outage",
  );
  expect(screen.getByTestId("health-empty").textContent).toContain(
    "vendor health UNKNOWN",
  );
});

it("a failed idea-ledger join is named, and the feed still renders", async () => {
  stubBoth({
    ...REVIEWS,
    ledger_join: { ok: false, error: "idea_ledger unreadable: boom" },
  });
  render(<FrontierReviews pollMs={600_000} />);
  await waitFor(() =>
    expect(screen.getByTestId("ledger-join-error")).toBeInTheDocument(),
  );
  expect(screen.getByTestId("ledger-join-error").textContent).toContain(
    "idea_ledger unreadable: boom",
  );
  expect(screen.getAllByTestId("screen-card")).toHaveLength(2);
});

// ─── frontierAge (compact ages, deterministic via nowMs) ────────────────

it("frontierAge renders compact ages and honest dashes", () => {
  const now = Date.parse("2026-08-18T12:00:00Z");
  expect(frontierAge("2026-08-18T11:59:30Z", now)).toBe("30s");
  expect(frontierAge("2026-08-18T11:55:00Z", now)).toBe("5m");
  expect(frontierAge(null, now)).toBe("—");
  expect(frontierAge("junk", now)).toBe("—");
});
