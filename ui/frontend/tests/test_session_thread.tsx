// SessionThreadCard + the /model-io feed it plugs into (owner feedback
// 2026-08-19: "I posed 3 questions for iter-2026-06-05-006 but it shows up
// as 6 cards instead of maybe 1 or 2 (since it goes to 2 models)").
//
// The finding-session engine is a stateless replay — every turn re-sends the
// whole message stack — so the same 3-question interrogation produced 6
// wrapper calls, each rendered as its own card repeating the entire growing
// context. The pins here:
//
//  1. THE 3x2 SHAPE: one card, three question blocks, two answers under each
//     question — the question printed ONCE, not once per voice;
//  2. NO REPLAY IN THE CARD: a turn shows its own answer and the NEW ask;
//     the replayed prefix appears only as a "context: N prior messages"
//     chip, which opens the full stack through the page's existing
//     expanded-call reader (one fetch, one expansion at a time);
//  3. FEED INTEGRATION: a thread is ONE row of the page's 20 and every
//     non-session call still renders as its own CallRow, unchanged;
//  4. HONEST BOUNDS: a thread whose opening turns fell outside the scan
//     window says so instead of implying it is the whole session.
//
// PAGING (rewritten 2026-08-19). The previous version of this file — and its
// backend twin — built CONTIGUOUS sessions: no plain rows anywhere inside
// the thread's span. That is the ONLY shape in which "page from the thread's
// `started`" looks correct, so both tests were green over a broken rule. A
// real log interleaves: the coordinator and the batteries write to
// calls.jsonl while a chat session is open, and a page's guaranteed coverage
// ends at its FILL POINT, which for a thread that opened the page is its
// LATEST turn — every older turn the backend backfilled rides along BELOW
// that boundary. Paging from `started` therefore jumped straight past the
// plain rows in between, and they appeared on neither page.
//
// The fixtures below are interleaved on purpose, and the assertions are set
// equalities over the whole walk: page1 ∪ page2 ∪ … = every row of the log,
// each exactly once, taking the boundary from the SERVER's next_before_ts.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SessionThreadCard, {
  formatWall,
  questionGroups,
  stanceAccent,
  threadComplete,
  voices,
  type SessionThread,
  type SessionTurn,
} from "../src/components/SessionThreadCard";
import ModelIO, {
  foldThread,
  mergeFeed,
  pageBoundary,
  toFeed,
} from "../src/routes/ModelIO";
import { resetPollHub } from "../src/api/pollhub";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // The poll hub is MODULE-GLOBAL and caches snapshots, so a sibling suite's
  // cached ModelIO payload bleeds into this one and the retention test reads
  // stale turns. Every other suite that renders <ModelIO/> already resets it
  // (test_model_io_perf, test_pulse_no_blank, test_pollhub); this one did not,
  // which is exactly why it passed alone and failed in the full run.
  resetPollHub();
});

const QUESTIONS = [
  "what is the reason we should kill this idea",
  "what would you do if you thought the idea was good, but we are just lacking validation on the expiermentation front?",
  "So if you both could give just 1 word, kill or reframe what would it be?",
];

// The real shape on disk (logs/calls.jsonl, session fs-6eddb609a03a): each
// question asked of BOTH voices, the replayed prefix growing by 2 messages a
// round — gemma defends, qwen attacks.
function turn(
  qi: number,
  stance: "defender" | "attacker",
  extra: Partial<SessionTurn> = {},
): SessionTurn {
  const gemma = stance === "defender";
  return {
    ts: `2026-08-19T03:${30 + qi * 2 + (gemma ? 0 : 1)}:00.000000Z`,
    request_id: `${stance}-${qi}`,
    caller_tag: `finding_session_${stance}`,
    stance,
    model: gemma ? "gemma-4-26b-a4b" : "qwen3.8-27b-nvfp4-mtp",
    backend: gemma ? "vllm-gemma" : "vllm-qwen",
    user_delta: QUESTIONS[qi],
    user_delta_truncated: false,
    prefix_message_count: 1 + qi * 2,
    completion: `${stance} answer to q${qi}`,
    completion_truncated: false,
    empty: false,
    tokens_in: 2695 + qi * 700,
    tokens_out: gemma ? 709 : 2196,
    latency_ms: gemma ? 27457.8 : 160233.3,
    ...extra,
  };
}

function thread(turns: SessionTurn[], extra: Partial<SessionThread> = {}) {
  const stamps = turns.map((t) => t.ts).filter((t): t is string => t != null);
  return {
    kind: "session_thread",
    session_id: "fs-6eddb609a03a",
    run_id: "finding_session_fs-6eddb609a03a",
    started: stamps.length ? stamps[0] : null,
    ended: stamps.length ? stamps[stamps.length - 1] : null,
    wall_ms: 821505,
    models: ["gemma-4-26b-a4b", "qwen3.8-27b-nvfp4-mtp"],
    stances: ["attacker", "defender"],
    caller_tags: ["finding_session_attacker", "finding_session_defender"],
    turn_count: turns.length,
    turns_truncated: false,
    turns_complete: threadComplete(turns),
    turns,
    ...extra,
  } as SessionThread;
}

const THREAD: SessionThread = thread(
  [0, 1, 2].flatMap((qi) => [turn(qi, "defender"), turn(qi, "attacker")]),
  { started: "2026-08-19T03:30:00.000000Z", ended: "2026-08-19T03:35:00.000000Z" },
);

// ─── pure helpers ───────────────────────────────────────────────────────

it("questionGroups collapses only CONSECUTIVE identical asks", () => {
  const groups = questionGroups(THREAD.turns);
  expect(groups.map((g) => g.length)).toEqual([2, 2, 2]);
  expect(groups.map((g) => g[0].user_delta)).toEqual(QUESTIONS);
  // The same question asked again LATER is a second question, never merged
  // back into the first.
  const repeat = [turn(0, "defender"), turn(1, "defender"), turn(0, "attacker")];
  expect(questionGroups(repeat).map((g) => g.length)).toEqual([1, 1, 1]);
  expect(questionGroups([])).toEqual([]);
});

it("formatWall is compact and honest about the unknown", () => {
  expect(formatWall(47_000)).toBe("47s");
  expect(formatWall(821_505)).toBe("13m 42s");
  expect(formatWall(3_780_000)).toBe("1h 03m");
  expect(formatWall(null)).toBe("—");
  expect(formatWall(Number.NaN)).toBe("—");
});

it("stanceAccent tones the adversarial and defending voices apart", () => {
  expect(stanceAccent("attacker")).not.toBe(stanceAccent("defender"));
  expect(stanceAccent("who-knows")).toBe(stanceAccent(null));
});

it("threadComplete refuses to read a MISSING prompt stack as proof", () => {
  // prefix 0 is real evidence — the stack IS the opening question. A row
  // with no legible prompt_messages reports null, which proves nothing;
  // reading it as 0 would let a malformed row forge completeness.
  expect(threadComplete([turn(0, "defender", { prefix_message_count: 0 })]))
    .toBe(true);
  expect(threadComplete([turn(0, "defender", { prefix_message_count: null })]))
    .toBe(false);
  // A voice whose only turn is malformed blocks the claim even when the
  // OTHER voice's opener is in hand.
  expect(
    threadComplete([
      turn(0, "defender", { prefix_message_count: null }),
      turn(0, "attacker", { prefix_message_count: 1 }),
    ]),
  ).toBe(false);
  expect(threadComplete([])).toBe(false);
  // Deep turns alone never prove an opener.
  expect(threadComplete([turn(2, "defender"), turn(2, "attacker")])).toBe(
    false,
  );
});

it("voices() takes model AND backend from the same evidence", () => {
  // Regression: the backend came from a voice's FIRST turn only while the
  // models accumulated, so a voice re-served mid-session claimed one
  // backend for two models — a chip contradicting itself.
  const moved = [
    turn(0, "defender"),
    turn(1, "defender", {
      model: "gemma-4-26b-a4b-nvfp4",
      backend: "vllm-gemma-b",
    }),
  ];
  const [v] = voices(moved);
  expect(v.models).toEqual(["gemma-4-26b-a4b", "gemma-4-26b-a4b-nvfp4"]);
  expect(v.backends).toEqual(["vllm-gemma", "vllm-gemma-b"]);
  // The ordinary case is still one of each, in first-appearance order.
  expect(voices(THREAD.turns).map((x) => x.stance)).toEqual([
    "defender",
    "attacker",
  ]);
});

// ─── the card ───────────────────────────────────────────────────────────

it("renders the 3-questions x 2-answers session as ONE card", () => {
  render(<SessionThreadCard thread={THREAD} onToggleContext={() => {}} />);
  expect(screen.getAllByTestId("session-thread")).toHaveLength(1);
  // Three question blocks, six answers — not six cards.
  const questions = screen.getAllByTestId("thread-question");
  expect(questions).toHaveLength(3);
  expect(screen.getAllByTestId("thread-turn")).toHaveLength(6);
  // Each question is printed ONCE, with BOTH voices' answers under it.
  QUESTIONS.forEach((q, i) => {
    expect(screen.getAllByText(q)).toHaveLength(1);
    const stances = within(questions[i])
      .getAllByTestId("thread-stance-chip")
      .map((el) => el.textContent);
    expect(stances).toEqual(["defender", "attacker"]);
    expect(
      within(questions[i]).getByText(`defender answer to q${i}`),
    ).toBeInTheDocument();
    expect(
      within(questions[i]).getByText(`attacker answer to q${i}`),
    ).toBeInTheDocument();
  });
  // Header: the session, its two voices, and the shape at a glance. The
  // question count is derived from the turns the card HOLDS (there is no
  // question_count on the wire — a folded card would contradict it).
  expect(screen.getByTestId("thread-session-id").textContent).toBe(
    "fs-6eddb609a03a",
  );
  expect(screen.getAllByTestId("thread-voice")).toHaveLength(2);
  expect(screen.getByText("vllm-gemma")).toBeInTheDocument();
  expect(screen.getByText("vllm-qwen")).toBeInTheDocument();
  expect(screen.getByTestId("thread-questions").textContent).toBe("3 questions");
  expect(screen.getByTestId("thread-turns").textContent).toBe("6 turns");
  expect(screen.getByTestId("thread-wall").textContent).toBe("13m 42s");
  // A complete thread makes no bounded-window excuse.
  expect(screen.queryByTestId("thread-incomplete")).toBeNull();
  expect(screen.queryByTestId("thread-turns-truncated")).toBeNull();
});

it("shows the replayed context as a COUNT, never as repeated prose", () => {
  render(<SessionThreadCard thread={THREAD} onToggleContext={() => {}} />);
  const chips = screen
    .getAllByTestId("thread-context-chip")
    .map((el) => el.textContent);
  expect(chips).toEqual([
    "context: 1 prior message",
    "context: 1 prior message",
    "context: 3 prior messages",
    "context: 3 prior messages",
    "context: 5 prior messages",
    "context: 5 prior messages",
  ]);
  // Q1's text appears once in the whole card even though five later calls
  // replayed it — that repetition is exactly what the card removes.
  expect(screen.getAllByText(QUESTIONS[0])).toHaveLength(1);
});

it("a turn with no legible prompt stack discloses no count", () => {
  render(
    <SessionThreadCard
      thread={thread([turn(0, "defender", { prefix_message_count: null })])}
      onToggleContext={() => {}}
    />,
  );
  expect(screen.getByTestId("thread-context-chip").textContent).toBe(
    "full record",
  );
  // …and the card does not claim to be the whole session off that row.
  expect(screen.getByTestId("thread-incomplete")).toBeInTheDocument();
});

it("the context chip opens the expansion under ITS OWN turn only", () => {
  const onToggle = vi.fn();
  const { rerender } = render(
    <SessionThreadCard thread={THREAD} onToggleContext={onToggle} />,
  );
  fireEvent.click(screen.getAllByTestId("thread-context-chip")[3]);
  expect(onToggle).toHaveBeenCalledWith("attacker-1");
  // The page hands the reader back for the turn it opened.
  rerender(
    <SessionThreadCard
      thread={THREAD}
      expandedRequestId="attacker-1"
      expansion={<div data-testid="stub-expansion">the full stack</div>}
      onToggleContext={onToggle}
    />,
  );
  const turns = screen.getAllByTestId("thread-turn");
  expect(within(turns[3]).getByTestId("stub-expansion")).toBeInTheDocument();
  expect(screen.getAllByTestId("stub-expansion")).toHaveLength(1);
  expect(screen.getAllByTestId("thread-context-chip")[3]).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});

it("says so when the session's opening turns are outside the window", () => {
  render(
    <SessionThreadCard
      thread={{ ...THREAD, turns_complete: false }}
      onToggleContext={() => {}}
    />,
  );
  expect(screen.getByTestId("thread-incomplete").textContent).toContain(
    "outside the scanned window",
  );
});

it("says so when the PAGE bounded how many turns it carried", () => {
  render(
    <SessionThreadCard
      thread={{ ...THREAD, turns_truncated: true }}
      onToggleContext={() => {}}
    />,
  );
  expect(screen.getByTestId("thread-turns-truncated").textContent).toContain(
    "load older",
  );
});

it("flags an empty turn and a clipped answer without hiding either", () => {
  render(
    <SessionThreadCard
      thread={thread([
        turn(0, "defender", { completion: "", empty: true }),
        turn(0, "attacker", { completion_truncated: true }),
      ])}
      onToggleContext={() => {}}
    />,
  );
  expect(screen.getByTestId("empty-loud")).toBeInTheDocument();
  expect(screen.getByTestId("thread-answer-clipped")).toBeInTheDocument();
  expect(screen.getByText("attacker answer to q0")).toBeInTheDocument();
});

// ─── merge internals (B2) ───────────────────────────────────────────────

it("foldThread prepends the older slice and dedupes turns by request_id", () => {
  const live = thread([turn(1, "defender"), turn(1, "attacker")], {
    turns_complete: false,
  });
  // The older slice OVERLAPS: it re-delivers q1 (a page may legally carry
  // rows below its own stated boundary) and adds q0.
  const older = thread([
    turn(0, "defender"),
    turn(0, "attacker"),
    turn(1, "defender"),
    turn(1, "attacker"),
  ]);
  const folded = foldThread(live, older);
  expect(folded.turns.map((t) => t.request_id)).toEqual([
    "defender-0",
    "attacker-0",
    "defender-1",
    "attacker-1",
  ]);
  expect(folded.turn_count).toBe(4);
  expect(folded.started).toBe(older.started);
  expect(folded.ended).toBe(live.ended);
  // Completeness is recomputed over the MERGED turns, not copied from a
  // slice: only the union proves both voices' openers are in hand.
  expect(folded.turns_complete).toBe(true);
  expect(foldThread(live, thread([turn(0, "defender")])).turns_complete).toBe(
    false,
  );
});

it("mergeFeed folds slices that BOTH live in the older list", () => {
  // The hole this closes: byKey was built from the NEWEST page only, so two
  // older slices of one session never met and rendered as two cards.
  const newest = toFeed({ calls: [], threads: [] } as never);
  const older = [
    ...toFeed({ calls: [], threads: [thread([turn(1, "defender")])] } as never),
    ...toFeed({ calls: [], threads: [thread([turn(0, "defender")])] } as never),
  ];
  const merged = mergeFeed(newest, older);
  expect(merged).toHaveLength(1);
  const item = merged[0];
  if (item.kind !== "thread") throw new Error("expected a thread item");
  expect(item.thread.turns.map((t) => t.request_id)).toEqual([
    "defender-0",
    "defender-1",
  ]);
});

it("pageBoundary uses the STATED fill point and refuses to guess", () => {
  // Stated: used verbatim, even when older rows ride below it.
  expect(
    pageBoundary({ calls: [], threads: [], next_before_ts: "T" } as never),
  ).toEqual({ ts: "T", supported: true });
  expect(
    pageBoundary({ calls: [], threads: [], next_before_ts: null } as never),
  ).toEqual({ ts: null, supported: true });
  // Version skew with NO threads: no backfill happened, so the oldest call
  // provably IS the fill point — the one safe inference.
  expect(
    pageBoundary({
      calls: [{ ts: "2026-08-19T03:31:00Z" }, { ts: "2026-08-19T03:30:00Z" }],
    } as never),
  ).toEqual({ ts: "2026-08-19T03:30:00Z", supported: true });
  // Version skew WITH threads: that inference is exactly the bug. Refuse.
  expect(
    pageBoundary({ calls: [], threads: [THREAD] } as never).supported,
  ).toBe(false);
});

// ─── the page feed ──────────────────────────────────────────────────────

const CALL = {
  ts: "2026-08-19T04:00:00Z",
  request_id: "iter-1",
  parent_request_id: null,
  model: "gemma-4-26b-a4b",
  backend: "vllm-gemma",
  caller_tag: "nara.run_iteration",
  run_id: null,
  latency_ms: 4991,
  input_tokens: 822,
  output_tokens: 55,
  prompt_preview: "Evaluate this research topic",
  completion_preview: "I will query chroma",
  empty: false,
};

const BASE = {
  source: "logs/calls.jsonl",
  window_truncated: false,
  scanned_bytes: 4096,
  max_scan_bytes: 16777216,
  generated_at: "2026-08-19T04:00:03Z",
};

const TABLE = {
  ...BASE,
  calls: [CALL],
  threads: [THREAD],
  next_before_ts: null,
  end_of_log: true,
};

const DETAIL = {
  found: true,
  call: {
    timestamp: "2026-08-19T03:31:00Z",
    request_id: "attacker-1",
    model: "qwen3.8-27b-nvfp4-mtp",
    caller_tag: "finding_session_attacker",
    prompt_messages: [
      { role: "system", content: "You are the INDEPENDENT SKEPTIC" },
      { role: "user", content: QUESTIONS[0] },
      { role: "assistant", content: "attacker answer to q0" },
      { role: "user", content: QUESTIONS[1] },
    ],
    completion: "attacker answer to q1",
    usage: { input_tokens: 3554, output_tokens: 2820 },
  },
};

const EMPTY_STRIP = {
  orchestrator_available: true,
  calls_available: true,
  chain: [],
  subagent_groups: [],
  window_truncated: false,
  generated_at: "2026-08-19T04:00:03Z",
};

/** Route the page's four sources. `pages` maps a before_ts value (or "" for
 * the live page) to the /api/model_io body to answer with. */
function stubPage(pages: Record<string, unknown> | unknown = TABLE) {
  const table =
    pages != null && typeof pages === "object" && "live" in (pages as object)
      ? (pages as Record<string, unknown>)
      : { live: pages };
  const mock = vi.fn(async (url: unknown) => {
    const u = String(url);
    let body: unknown;
    if (u.includes("/api/model_io/")) body = DETAIL;
    else if (u.includes("/api/model_io")) {
      const m = /before_ts=([^&]*)/.exec(u);
      const key = m ? decodeURIComponent(m[1]) : "live";
      body = table[key];
      if (body === undefined) {
        throw new Error(`no fixture page for before_ts=${key}`);
      }
    } else if (u.includes("/api/runtime_activity")) body = EMPTY_STRIP;
    else if (u.includes("/api/dispatch_trace")) {
      body = {
        orchestrator_available: true,
        spawn_available: true,
        tasks: [],
        spawns: [],
        generated_at: "2026-08-19T04:00:03Z",
      };
    } else body = { available: true, calls: [], rows_in_window: 0 };
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

it("renders a session as ONE feed row and leaves plain calls alone", async () => {
  stubPage();
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  // The 6 session calls are ONE row; the unrelated chain call keeps its own
  // per-call rendering exactly as before.
  expect(screen.getAllByTestId("session-thread")).toHaveLength(1);
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(1);
  expect(screen.getByText("nara.run_iteration")).toBeInTheDocument();
  expect(screen.getAllByTestId("thread-question")).toHaveLength(3);
  // Feed row count reported honestly: 1 call + 1 thread = 2 rows.
  expect(screen.getByText(/showing 2 rows/)).toBeInTheDocument();
  // The live page already said it reached the file start — no button to
  // click, and the page says so without one.
  expect(screen.getByTestId("pager-end")).toBeInTheDocument();
});

it("a context chip fetches that turn's FULL replayed stack", async () => {
  const mock = stubPage();
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  fireEvent.click(screen.getAllByTestId("thread-context-chip")[3]);
  await waitFor(() =>
    expect(screen.getByTestId("call-expansion")).toBeInTheDocument(),
  );
  expect(
    mock.mock.calls.some((c) =>
      String(c[0]).includes("/api/model_io/attacker-1"),
    ),
  ).toBe(true);
  // The stack the card refused to repeat is all here, role-labeled.
  const expansion = screen.getByTestId("call-expansion");
  expect(within(expansion).getByText(/INDEPENDENT SKEPTIC/)).toBeInTheDocument();
  expect(within(expansion).getAllByTestId("role-chip").length).toBeGreaterThan(3);
});

// ─── the interleaved paging walk (B1 + B2) ──────────────────────────────
//
// THE LOG (chronological). Plain calls sit BETWEEN the session's turns —
// this is the shape the previous tests avoided and the shape that broke.
//
//   03:30 plain-0 | 03:31 def-0 | 03:32 plain-2 | 03:33 att-0
//   03:34 plain-4 | 03:35 def-1 | 03:36 plain-6 | 03:37 att-1
//   03:38 plain-8
//
// The pages below are what the backend answers at limit=3 (its own suite
// proves the arithmetic). PAGE 1's fill point is plain-6 at 03:36: the
// session's older turns ride BELOW that boundary as a bonus so the card can
// be whole on first paint, and PAGE 2 re-delivers them, which is why the
// client must fold turns by request_id.

const AT = (mm: number) => `2026-08-19T03:${mm}:00.000000Z`;

const plain = (mm: number) => ({
  ...CALL,
  ts: AT(mm),
  request_id: `plain-${mm}`,
  completion_preview: `plain ${mm}`,
});

const sturn = (
  mm: number,
  stance: "defender" | "attacker",
  qi: number,
  prefix: number,
): SessionTurn => ({
  ...turn(qi, stance),
  ts: AT(mm),
  request_id: `sess-${mm}`,
  prefix_message_count: prefix,
});

const DEF0 = sturn(31, "defender", 0, 1);
const ATT0 = sturn(33, "attacker", 0, 1);
const DEF1 = sturn(35, "defender", 1, 3);
const ATT1 = sturn(37, "attacker", 1, 3);

const EVERY_ROW = [
  "plain-30",
  "sess-31",
  "plain-32",
  "sess-33",
  "plain-34",
  "sess-35",
  "plain-36",
  "sess-37",
  "plain-38",
];

const WALK = {
  // PAGE 1 — budget spent at plain-36; the thread's older turns ride below.
  live: {
    ...BASE,
    calls: [plain(38), plain(36)],
    threads: [thread([DEF0, ATT0, DEF1, ATT1])],
    next_before_ts: AT(36),
    end_of_log: false,
  },
  // PAGE 2 — strictly older than 03:36. Re-delivers the three session turns
  // that page 1 carried below its boundary, plus the two plain rows the old
  // rule jumped straight over.
  [AT(36)]: {
    ...BASE,
    calls: [plain(34), plain(32)],
    threads: [thread([DEF0, ATT0, DEF1])],
    next_before_ts: AT(31),
    end_of_log: false,
  },
  // PAGE 3 — the file's first row.
  [AT(31)]: {
    ...BASE,
    calls: [plain(30)],
    threads: [],
    next_before_ts: null,
    end_of_log: true,
  },
};

it("the paging walk covers every INTERLEAVED row exactly once", async () => {
  const mock = stubPage(WALK);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(4),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getByTestId("pager-end")).toBeInTheDocument(),
  );

  // EVERY plain row of the log is on screen, exactly once.
  const previews = screen
    .getAllByTestId("row-preview")
    .map((el) => el.textContent);
  expect(previews).toEqual([
    "plain 38",
    "plain 36",
    "plain 34",
    "plain 32",
    "plain 30",
  ]);
  // …and the four session turns fold into ONE card, no turn doubled even
  // though page 2 re-delivered three of them.
  expect(screen.getAllByTestId("session-thread")).toHaveLength(1);
  expect(screen.getAllByTestId("thread-turn")).toHaveLength(4);
  expect(screen.getByTestId("thread-turns").textContent).toBe("4 turns");
  // 5 plain rows + 4 turns = the 9 log rows, each rendered once.
  expect(previews.length + screen.getAllByTestId("thread-turn").length).toBe(
    EVERY_ROW.length,
  );

  // The FIRST older request used the server's stated fill point (03:36) —
  // NOT the thread's `started` (03:31), which is where the old rule paged
  // from. plain-34 and plain-32 sit between the two, so a page keyed on
  // `started` would never have returned them and page 1 never carried them.
  const asked = mock.mock.calls
    .map((c) => String(c[0]))
    .filter((u) => u.includes("before_ts="))
    .map((u) => decodeURIComponent(/before_ts=([^&]*)/.exec(u)![1]));
  expect(asked[0]).toBe(AT(36));
  expect(asked[0]).not.toBe(DEF0.ts); // DEF0.ts IS the thread's `started`
  expect(WALK.live.threads[0].started).toBe(DEF0.ts);
  expect(DEF0.ts! < AT(34) && AT(34) < AT(36)).toBe(true);
});

it("an older page may OPEN a session, and later pages complete it", async () => {
  // The thread is NOT on the live page: it opens at PAGE 2's own fill point
  // with turns_complete false, and PAGE 3 carries its opening turns. Both
  // slices live in the appended-older list — which is exactly where the old
  // mergeFeed never looked, so they rendered as two cards, and where the old
  // loadOlder dropped the second slice whole.
  const pages = {
    live: {
      ...BASE,
      calls: [plain(38), plain(36)],
      threads: [],
      next_before_ts: AT(36),
      end_of_log: false,
    },
    [AT(36)]: {
      ...BASE,
      calls: [plain(34)],
      threads: [thread([DEF1, ATT1], { turns_truncated: true })],
      next_before_ts: AT(34),
      end_of_log: false,
    },
    [AT(34)]: {
      ...BASE,
      calls: [plain(30)],
      threads: [thread([DEF0, ATT0])],
      next_before_ts: null,
      end_of_log: true,
    },
  };
  stubPage(pages);
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(2),
  );
  expect(screen.queryByTestId("session-thread")).toBeNull();

  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  // Honest while it is a fragment: the openers are not in hand, and the
  // page said it stopped at its per-thread turn cap.
  expect(screen.getByTestId("thread-incomplete")).toBeInTheDocument();
  expect(screen.getByTestId("thread-turns-truncated")).toBeInTheDocument();
  expect(screen.getAllByTestId("thread-turn")).toHaveLength(2);

  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("thread-turn")).toHaveLength(4),
  );
  // ONE card, chronological, and the completeness claim now comes from the
  // MERGED turns rather than from either slice's own flag.
  expect(screen.getAllByTestId("session-thread")).toHaveLength(1);
  expect(screen.queryByTestId("thread-incomplete")).toBeNull();
  expect(screen.getAllByTestId("thread-question")).toHaveLength(2);
  expect(screen.getByTestId("pager-end")).toBeInTheDocument();
  // Every plain row is still there, once each.
  expect(screen.getAllByTestId("modelio-row")).toHaveLength(4);
});

it("a poll that pushes the session off the live page keeps its turns", async () => {
  // The retention path is the third place the same defect lived: rows the
  // live page no longer holds move onto the older list, and the thread item
  // was dropped there too when a paged slice of the SAME session had already
  // been appended — losing the session's newest turns on a poll tick.
  let live: unknown = {
    ...BASE,
    calls: [plain(38)],
    threads: [thread([DEF1, ATT1], { turns_complete: false })],
    next_before_ts: AT(35),
    end_of_log: false,
  };
  const older = {
    ...BASE,
    calls: [plain(34)],
    threads: [thread([DEF0, ATT0])],
    next_before_ts: null,
    end_of_log: true,
  };
  const mock = vi.fn(async (url: unknown) => {
    const u = String(url);
    const body = u.includes("/api/model_io/")
      ? DETAIL
      : u.includes("before_ts=")
        ? older
        : u.includes("/api/model_io")
          ? live
          : u.includes("/api/runtime_activity")
            ? EMPTY_STRIP
            : {
                orchestrator_available: true,
                spawn_available: true,
                tasks: [],
                spawns: [],
                generated_at: "2026-08-19T04:00:03Z",
              };
    return {
      ok: true,
      status: 200,
      statusText: "200",
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  render(<ModelIO pollMs={60} />);
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByTestId("load-older"));
  await waitFor(() =>
    expect(screen.getAllByTestId("thread-turn")).toHaveLength(4),
  );
  // A burst of new plain calls now pushes the session clean off the live
  // page. Its turns must be RETAINED, not dropped.
  live = {
    ...BASE,
    calls: [plain(39), plain(38)],
    threads: [],
    next_before_ts: AT(38),
    end_of_log: false,
  };
  // plain-39 (new) + plain-38 (live) + plain-34 (paged) = 3 call rows …
  await waitFor(
    () => expect(screen.getAllByTestId("modelio-row").length).toBe(3),
    { timeout: 3000 },
  );
  // … and the session is still ONE card holding ALL FOUR of its turns: the
  // two the live page had just handed back are retained, not dropped.
  expect(screen.getAllByTestId("session-thread")).toHaveLength(1);
  expect(screen.getAllByTestId("thread-turn")).toHaveLength(4);
  expect(screen.getByTestId("thread-turns").textContent).toBe("4 turns");
});

it("refuses to page when the response states no boundary", async () => {
  // Version skew: a backend that predates the coverage contract answers
  // with threads but no next_before_ts. Inferring one from the rendered
  // rows is the bug itself — the pager stops and says so instead.
  stubPage({
    live: {
      ...BASE,
      calls: [CALL],
      threads: [THREAD],
    },
  });
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getByTestId("session-thread")).toBeInTheDocument(),
  );
  expect(screen.getByTestId("pager-blocked").textContent).toContain(
    "states no page boundary",
  );
  expect(screen.queryByTestId("load-older")).toBeNull();
});

it("degrades to plain call rows when the backend sends no threads key", async () => {
  // Version skew: an older backend has no grouping. The page renders its
  // calls rather than blanking, and paging still works (no threads means no
  // backfill, so the oldest call provably IS the fill point).
  stubPage({ live: { ...BASE, calls: [CALL] } });
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(1),
  );
  expect(screen.queryByTestId("session-thread")).toBeNull();
  expect(screen.getByTestId("load-older")).toBeInTheDocument();
});
