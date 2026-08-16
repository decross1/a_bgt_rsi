// /channel — the S4 lab channel surface. Pins: the merged feed (voice
// bubbles + event system-lines with kind chips), the one-model honesty note
// beside the role selector, the turn post (role threads through), the
// capability-off preview state (send disabled, nothing posted), the delegate
// CONFIRM-CARD flow — the confirm click is the ONLY path that posts — and
// THE FENCE: no disposition surface exists anywhere on the page. Skew (404
// on /api/channel/timeline) renders the quiet EndpointMissingNote.
//
// loop3h-ui-hotfix pins: first live load asks for only the NEWEST 40 rows;
// the feed is chronological (newest at the bottom) in its own overflow-y
// scroll container with the composer docked below; "load older" widens the
// limit window and prepends; nara/pi bubble bodies render through
// MiniMarkdown (human turns stay verbatim); runs of >=3 consecutive
// same-kind events collapse into one expandable wall line.
//
// R4 pins (the designed conversation surface): document-style voice blocks
// (avatar · name · time · body) with a per-voice accent and the human's own
// tint; events as compact subordinate rows; the all/conversation/events
// filter chips; UTC day dividers; reference chips (cl-*/iter-*/sf-*) that
// PEEK rather than inline the object; the pending block on a turn in flight
// (no stop affordance — the seam has no abort verb); jump-to-present.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChannelRow } from "../src/api/channel";

const mocks = vi.hoisted(() => ({
  getChannelAvailability: vi.fn(),
  getChannelTimeline: vi.fn(),
  postChannelTurn: vi.fn(),
  postChannelDelegate: vi.fn(),
  getLadder: vi.fn(),
  getFindingDetail: vi.fn(),
  getIterationJourney: vi.fn(),
}));
vi.mock("../src/api/channel", () => ({
  getChannelAvailability: mocks.getChannelAvailability,
  getChannelTimeline: mocks.getChannelTimeline,
  postChannelTurn: mocks.postChannelTurn,
  postChannelDelegate: mocks.postChannelDelegate,
}));
// EndpointMissingNote self-fetches /api/health when no version prop is
// passed; mock the http module so the skew test stays fetch-free. The three
// reference-peek reads (R4) live in the same module and are mocked here too —
// the peek is the ONLY thing on this page that touches them, and only on a
// chip click.
vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: null,
    version: "testsha",
  }),
  getLadder: mocks.getLadder,
  getFindingDetail: mocks.getFindingDetail,
  getIterationJourney: mocks.getIterationJourney,
}));

import Channel from "../src/routes/Channel";

const ROWS: ChannelRow[] = [
  {
    ts: "2026-08-15T10:00:00Z",
    kind: "event",
    message: "cycle: kv-cache probing · executed · 3 plan action(s) · promoted 0",
  },
  {
    ts: "2026-08-15T10:01:00Z",
    kind: "event",
    message: "cluster killed: cl-x — rediscovery: already in the literature",
  },
  {
    ts: "2026-08-15T10:02:00Z",
    kind: "event",
    message: "promoted: sf-009 — eviction bias holds at 4-bit",
  },
  {
    ts: "2026-08-15T10:03:00Z",
    kind: "event",
    message: "loop alert: amber — promote drought 6d",
  },
  { ts: "2026-08-15T10:05:00Z", kind: "human", message: "what is running?" },
  {
    ts: "2026-08-15T10:05:40Z",
    kind: "nara",
    message: "one cycle executing: kv-cache probing.",
  },
  {
    ts: "2026-08-15T10:07:00Z",
    kind: "pi",
    message: "the eviction cluster owes an experiment_outcome next.",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("/channel feed", () => {
  it("renders voice bubbles and event lines with kind chips", () => {
    render(<Channel initial={ROWS} initialAvailable={true} />);

    // Voice bubbles carry ChatPane's visual language: uppercase voice labels.
    expect(screen.getByTestId("channel-turn-human")).toHaveTextContent(
      "what is running?",
    );
    expect(screen.getByTestId("channel-turn-nara")).toHaveTextContent(
      "nara · operations voice",
    );
    expect(screen.getByTestId("channel-turn-pi")).toHaveTextContent(
      "research voice",
    );

    // Event system-lines, chipped by kind: cycle / kill / promotion / alert.
    const chips = screen
      .getAllByTestId("channel-event-chip")
      .map((el) => el.textContent);
    expect(chips).toEqual(["cycle", "kill", "promotion", "alert"]);
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(4);
  });

  it("renders the honest empty state when there are no rows", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    expect(screen.getByTestId("channel-empty")).toHaveTextContent(
      "no channel activity yet",
    );
  });

  it("renders the one-model honesty note beside the role selector", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    const note = screen.getByTestId("channel-honesty-note");
    expect(note).toHaveTextContent("SAME local model");
    expect(note).toHaveTextContent("never treat one as independent confirmation");
    // The independent skeptic is named as living elsewhere (dossier chat).
    expect(note).toHaveTextContent("dossier reader");
  });

  it("version-skew 404 renders the quiet EndpointMissingNote", async () => {
    mocks.getChannelTimeline.mockRejectedValue(
      Object.assign(new Error("404 Not Found"), { status: 404 }),
    );
    mocks.getChannelAvailability.mockResolvedValue({
      available: false,
      actions: { timeline: false, turn: false, delegate: false },
      skew: true,
    });
    render(<Channel />);
    await waitFor(() =>
      expect(screen.getByTestId("endpoint-missing-note")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
      "/api/channel/timeline",
    );
    expect(screen.queryByTestId("channel-error")).toBeNull(); // never red
  });

  it("a non-404 failure renders the honest red error", async () => {
    mocks.getChannelTimeline.mockRejectedValue(
      Object.assign(new Error("500 exec failed"), { status: 500 }),
    );
    mocks.getChannelAvailability.mockResolvedValue({
      available: true,
      actions: { timeline: true, turn: true, delegate: true },
    });
    render(<Channel />);
    await waitFor(() =>
      expect(screen.getByTestId("channel-error")).toHaveTextContent(
        "exec failed",
      ),
    );
  });
});

// n sequential human rows one minute apart, oldest first ("m<minute>").
function makeRows(n: number, startMin = 0): ChannelRow[] {
  return Array.from({ length: n }, (_, i) => {
    const min = startMin + i;
    const hh = String(Math.floor(min / 60)).padStart(2, "0");
    const mm = String(min % 60).padStart(2, "0");
    return {
      ts: `2026-08-15T${hh}:${mm}:00Z`,
      kind: "human",
      message: `m${min}`,
    };
  });
}

describe("/channel chat layout + paging (loop3h-ui-hotfix)", () => {
  const LIVE_CAP = {
    available: true,
    actions: { timeline: true, turn: true, delegate: true },
  };

  it("first live load requests only the NEWEST 40 rows (no 400-row wall)", async () => {
    mocks.getChannelAvailability.mockResolvedValue(LIVE_CAP);
    mocks.getChannelTimeline.mockResolvedValue({ rows: [] });
    render(<Channel />);
    await waitFor(() =>
      expect(mocks.getChannelTimeline).toHaveBeenCalledWith(undefined, 40),
    );
  });

  it("renders chronological with the newest at the bottom (fixture order sorted)", () => {
    // Deliberately shuffled: pi (10:07), cycle event (10:00), human (10:05).
    render(
      <Channel
        initial={[ROWS[6], ROWS[0], ROWS[4]]}
        initialAvailable={true}
      />,
    );
    const feed = screen.getByTestId("channel-feed");
    const nodes = Array.from(
      feed.querySelectorAll(
        '[data-testid^="channel-turn-"], [data-testid="channel-event-row"]',
      ),
    );
    expect(nodes).toHaveLength(3);
    expect(nodes[0]).toHaveTextContent("kv-cache probing"); // 10:00 oldest, top
    expect(nodes[1]).toHaveTextContent("what is running?"); // 10:05
    expect(nodes[2]).toHaveTextContent("experiment_outcome"); // 10:07 newest, bottom
  });

  it("the feed scrolls in its own container with the composer docked below", () => {
    render(<Channel initial={ROWS} initialAvailable={true} />);
    const feed = screen.getByTestId("channel-feed");
    expect(feed.className).toContain("overflow-y-auto");
    expect(screen.getByTestId("channel-page").className).toContain("flex-col");
    // The composer FOLLOWS the feed in document order — docked below it.
    const composer = screen.getByTestId("channel-composer");
    expect(
      feed.compareDocumentPosition(composer) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("'load older' widens the limit window and prepends the older rows", async () => {
    const older = makeRows(5, 0); // m0..m4 — the older tail
    const newest40 = makeRows(40, 5); // m5..m44 — the first-load window
    mocks.getChannelAvailability.mockResolvedValue(LIVE_CAP);
    mocks.getChannelTimeline
      .mockResolvedValue({ rows: [] }) // any later poll: quiet
      .mockResolvedValueOnce({ rows: newest40 })
      .mockResolvedValueOnce({ rows: [...older, ...newest40] });
    render(<Channel />);

    // A full first-load window ⇒ older rows may exist ⇒ the button shows.
    await waitFor(() =>
      expect(screen.getByTestId("channel-load-older")).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("channel-turn-human")).toHaveLength(40);

    fireEvent.click(screen.getByTestId("channel-load-older"));
    await waitFor(() =>
      expect(mocks.getChannelTimeline).toHaveBeenLastCalledWith(undefined, 80),
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("channel-turn-human")).toHaveLength(45),
    );
    // Prepended: oldest first at the top, newest still at the bottom.
    const turns = screen.getAllByTestId("channel-turn-human");
    expect(turns[0]).toHaveTextContent("m0");
    expect(turns[44]).toHaveTextContent("m44");
    // 45 < the 80 window ⇒ nothing older remains ⇒ the button disappears.
    await waitFor(() =>
      expect(screen.queryByTestId("channel-load-older")).toBeNull(),
    );
  });

  it("fixture mode never shows 'load older' (it belongs to the live window)", () => {
    render(<Channel initial={makeRows(60)} initialAvailable={true} />);
    expect(screen.queryByTestId("channel-load-older")).toBeNull();
  });

  it("nara/pi bubble bodies render through MiniMarkdown; human turns stay raw", () => {
    const rows: ChannelRow[] = [
      { ts: "2026-08-15T10:00:00Z", kind: "human", message: "**not markdown**" },
      {
        ts: "2026-08-15T10:01:00Z",
        kind: "nara",
        message: "reply with **bold** and `code`",
      },
      { ts: "2026-08-15T10:02:00Z", kind: "pi", message: "- item one\n- item two" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    const nara = screen.getByTestId("channel-turn-nara");
    expect(within(nara).getByTestId("mini-markdown")).toBeInTheDocument();
    expect(within(nara).getByText("bold").tagName).toBe("STRONG");
    const pi = screen.getByTestId("channel-turn-pi");
    expect(within(pi).getByTestId("mini-markdown")).toBeInTheDocument();
    expect(within(pi).getByText("item one").tagName).toBe("LI");
    // The human's own turn is NOT interpreted — asterisks and all.
    const human = screen.getByTestId("channel-turn-human");
    expect(within(human).queryByTestId("mini-markdown")).toBeNull();
    expect(human).toHaveTextContent("**not markdown**");
  });

  it("collapses runs of >=3 consecutive same-kind events; expand reveals them", () => {
    const kills: ChannelRow[] = [1, 2, 3, 4].map((n) => ({
      ts: `2026-08-15T11:0${n}:00Z`,
      kind: "event",
      message: `cluster killed: cl-${n} — reason ${n}`,
    }));
    // cycle event (10:00) + human (10:05) sit outside the 4-kill run.
    render(
      <Channel initial={[ROWS[0], ROWS[4], ...kills]} initialAvailable={true} />,
    );

    const wall = screen.getByTestId("channel-event-wall");
    expect(wall).toHaveTextContent("4 cluster kills — expand");
    // Only the lone cycle event renders as an individual event row.
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(1);
    expect(screen.getAllByTestId("channel-event-chip")).toHaveLength(1);

    fireEvent.click(screen.getByTestId("channel-event-wall-expand"));
    expect(screen.queryByTestId("channel-event-wall")).toBeNull();
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(5);
  });

  it("short same-kind runs (under 3) stay individual rows", () => {
    const twoKills: ChannelRow[] = [1, 2].map((n) => ({
      ts: `2026-08-15T11:0${n}:00Z`,
      kind: "event",
      message: `cluster killed: cl-${n}`,
    }));
    render(<Channel initial={twoKills} initialAvailable={true} />);
    expect(screen.queryByTestId("channel-event-wall")).toBeNull();
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(2);
  });
});

describe("/channel turn composer", () => {
  it("posts a turn with the selected role and refreshes the feed", async () => {
    mocks.postChannelTurn.mockResolvedValue({
      status: "passed",
      role: "pi",
      reply: "a reply",
    });
    mocks.getChannelTimeline.mockResolvedValue({ rows: [] });
    render(<Channel initial={[]} initialAvailable={true} />);

    fireEvent.click(screen.getByTestId("channel-role-pi"));
    fireEvent.change(screen.getByLabelText("channel turn input"), {
      target: { value: "what is alive?" },
    });
    fireEvent.click(screen.getByTestId("channel-send"));

    await waitFor(() =>
      expect(mocks.postChannelTurn).toHaveBeenCalledWith({
        role: "pi",
        message: "what is alive?",
      }),
    );
    // The send triggers an immediate feed refresh (the CLI appended rows).
    await waitFor(() => expect(mocks.getChannelTimeline).toHaveBeenCalled());
  });

  it("defaults to the nara voice", async () => {
    mocks.postChannelTurn.mockResolvedValue({ status: "passed" });
    mocks.getChannelTimeline.mockResolvedValue({ rows: [] });
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByLabelText("channel turn input"), {
      target: { value: "status?" },
    });
    fireEvent.click(screen.getByTestId("channel-send"));
    await waitFor(() =>
      expect(mocks.postChannelTurn).toHaveBeenCalledWith({
        role: "nara",
        message: "status?",
      }),
    );
  });

  it("capability off: send disabled, banner shown, nothing ever posted", () => {
    render(<Channel initial={[]} initialAvailable={false} />);
    expect(screen.getByTestId("channel-capability-off")).toHaveTextContent(
      "your message is not sent",
    );
    const send = screen.getByTestId("channel-send") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("channel turn input"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByTestId("channel-send"));
    expect(mocks.postChannelTurn).not.toHaveBeenCalled();
  });

  it("a failed turn surfaces the CLI stderr verbatim", async () => {
    mocks.postChannelTurn.mockRejectedValue(
      Object.assign(new Error("502 boom"), {
        stderr: "rejected: message must be non-empty\n",
      }),
    );
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByLabelText("channel turn input"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByTestId("channel-send"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-send-error")).toHaveTextContent(
        "rejected: message must be non-empty",
      ),
    );
  });
});

describe("/channel delegate confirm-card flow", () => {
  it("review renders the confirm card naming the exact write targets — WITHOUT posting", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "probe the eviction schedule" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));

    const card = screen.getByTestId("delegate-confirm-card");
    expect(card).toHaveTextContent("probe the eviction schedule");
    // research → the agenda event + its ledger file, and the standing cluster.
    expect(card).toHaveTextContent("agenda_item_added");
    expect(card).toHaveTextContent("memory/idea_ledger.jsonl");
    expect(card).toHaveTextContent("cl-human-delegations");
    expect(card).toHaveTextContent("memory/lab_channel.jsonl");
    // Reviewing NEVER posts — only the confirm click does.
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();
  });

  it("the improvement card names the authorize_fix packet queue", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-delegate-kind-improvement"));
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "fix the tailer attach" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));
    const card = screen.getByTestId("delegate-confirm-card");
    expect(card).toHaveTextContent("authorize_fix packet row");
    expect(card).toHaveTextContent("memory/authorize_fix_queue.jsonl");
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();
  });

  it("ONLY the confirm click posts; the payload threads kind/text/cluster", async () => {
    mocks.postChannelDelegate.mockResolvedValue({
      status: "passed",
      kind: "research",
      rows: [],
    });
    mocks.getChannelTimeline.mockResolvedValue({ rows: [] });
    render(<Channel initial={[]} initialAvailable={true} />);

    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "probe eviction" },
    });
    fireEvent.change(screen.getByTestId("channel-delegate-cluster"), {
      target: { value: "cl-abc" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled(); // still not posted

    fireEvent.click(screen.getByTestId("delegate-confirm"));
    await waitFor(() =>
      expect(mocks.postChannelDelegate).toHaveBeenCalledTimes(1),
    );
    expect(mocks.postChannelDelegate).toHaveBeenCalledWith({
      kind: "research",
      text: "probe eviction",
      cluster_id: "cl-abc",
    });
    await waitFor(() =>
      expect(screen.getByTestId("channel-delegate-result")).toHaveTextContent(
        "delegation recorded",
      ),
    );
  });

  it("cancel dismisses the card and posts nothing", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "an idea" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));
    fireEvent.click(screen.getByTestId("delegate-cancel"));
    expect(screen.queryByTestId("delegate-confirm-card")).toBeNull();
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();
  });

  it("editing the text invalidates a pending confirm card", () => {
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "v1" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));
    expect(screen.getByTestId("delegate-confirm-card")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "v2 changed" },
    });
    // The card must not survive an edit — the human confirms EXACT content.
    expect(screen.queryByTestId("delegate-confirm-card")).toBeNull();
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();
  });

  it("a rejected delegation surfaces the CLI stderr verbatim", async () => {
    mocks.postChannelDelegate.mockRejectedValue(
      Object.assign(new Error("502"), {
        stderr: "rejected: cluster 'cl-nope' not found in the idea ledger\n",
      }),
    );
    render(<Channel initial={[]} initialAvailable={true} />);
    fireEvent.change(screen.getByTestId("channel-delegate-text"), {
      target: { value: "t" },
    });
    fireEvent.click(screen.getByTestId("channel-delegate-review"));
    fireEvent.click(screen.getByTestId("delegate-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-delegate-error")).toHaveTextContent(
        "cl-nope",
      ),
    );
  });
});

describe("/channel voice blocks (R4)", () => {
  it("a turn is a document-style block: avatar mark · name · time · body", () => {
    render(<Channel initial={[ROWS[4], ROWS[5]]} initialAvailable={true} />);
    const human = screen.getByTestId("channel-turn-human");
    expect(within(human).getByTestId("channel-voice-avatar")).toBeInTheDocument();
    expect(within(human).getByTestId("channel-voice-name")).toHaveTextContent(
      "you",
    );
    // The day lives on the divider, so a turn carries only its time — and it
    // carries the full ts machine-readably.
    const time = within(human).getByTestId("channel-voice-time");
    expect(time).toHaveTextContent("10:05");
    expect(time).toHaveAttribute("dateTime", "2026-08-15T10:05:00Z");
    expect(within(human).getByTestId("channel-voice-body")).toHaveTextContent(
      "what is running?",
    );
  });

  it("each voice carries its own accent; only the human's turn is tinted", () => {
    render(
      <Channel initial={[ROWS[4], ROWS[5], ROWS[6]]} initialAvailable={true} />,
    );
    const human = screen.getByTestId("channel-turn-human");
    const nara = screen.getByTestId("channel-turn-nara");
    const pi = screen.getByTestId("channel-turn-pi");
    const accent = (el: HTMLElement) => el.style.getPropertyValue("--voice-accent");
    // Three distinct accents — the rail + name color is what tells voices apart.
    expect(new Set([accent(human), accent(nara), accent(pi)]).size).toBe(3);
    expect(accent(nara)).toBe("var(--voice-nara)");
    expect(accent(pi)).toBe("var(--voice-pi)");
    // Document-style blocks, not bubbles: the ONE surface fill is the human's
    // own-turn tint.
    expect(human).toHaveClass("chn-turn--own");
    expect(nara).not.toHaveClass("chn-turn--own");
    expect(pi).not.toHaveClass("chn-turn--own");
    for (const el of [human, nara, pi]) expect(el).toHaveClass("chn-turn");
  });

  it("the oracle steward is a named voice, distinct from the reader's own", () => {
    // 2026-08-16: another session addresses the lab through `turn --as oracle`.
    // Its turns must never read as the owner's — so: own hue, no own-tint, and
    // a label that says what it is.
    const rows: ChannelRow[] = [
      { ts: "2026-08-16T01:27:06Z", kind: "oracle", message: "steward asks" },
      { ts: "2026-08-16T01:30:00Z", kind: "nara", message: "nara answers" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    const oracle = screen.getByTestId("channel-turn-oracle");
    expect(within(oracle).getByTestId("channel-voice-name")).toHaveTextContent(
      "oracle · mission steward",
    );
    expect(oracle.style.getPropertyValue("--voice-accent")).toBe(
      "var(--voice-oracle)",
    );
    expect(oracle).not.toHaveClass("chn-turn--own");
    expect(oracle).not.toHaveClass("chn-turn--event");
    // It is conversation, not an apparatus event — the filter must keep it.
    expect(within(oracle).getByTestId("channel-voice-body")).toHaveTextContent(
      "steward asks",
    );
  });

  it("an unknown producer kind renders the neutral fallback voice, never a prototype member", () => {
    const rows: ChannelRow[] = [
      { ts: "2026-08-15T10:00:00Z", kind: "toString", message: "hostile kind" },
      { ts: "2026-08-15T10:01:00Z", kind: "future_voice", message: "new voice" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    const hostile = screen.getByTestId("channel-turn-toString");
    expect(within(hostile).getByTestId("channel-voice-name")).toHaveTextContent(
      "voice",
    );
    expect(hostile.style.getPropertyValue("--voice-accent")).toBe(
      "var(--voice-other)",
    );
    expect(hostile).not.toHaveClass("chn-turn--own");
    expect(screen.getByTestId("channel-turn-future_voice")).toHaveTextContent(
      "new voice",
    );
  });

  it("the delegation mirror row's prefix becomes an activity chip, not prose", () => {
    const rows: ChannelRow[] = [
      {
        ts: "2026-08-15T10:00:00Z",
        kind: "human",
        message: "DELEGATED[research]: probe the eviction schedule",
      },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    expect(screen.getByTestId("channel-activity-chip")).toHaveTextContent(
      "delegated · research",
    );
    const body = screen.getByTestId("channel-voice-body");
    expect(body).toHaveTextContent("probe the eviction schedule");
    expect(body).not.toHaveTextContent("DELEGATED[research]");
  });

  it("an ordinary turn gets NO activity chip (no tool-use field exists to invent one from)", () => {
    render(<Channel initial={[ROWS[5]]} initialAvailable={true} />);
    expect(screen.queryByTestId("channel-activity-chip")).toBeNull();
  });
});

describe("/channel system events (R4)", () => {
  it("an event is a compact single-line row (glyph · label · text · time), not a voice block", () => {
    render(<Channel initial={[ROWS[1]]} initialAvailable={true} />);
    const row = screen.getByTestId("channel-event-row");
    expect(row).toHaveClass("chn-event");
    expect(row).not.toHaveClass("chn-turn");
    expect(row.querySelector(".chn-event-glyph")).not.toBeNull();
    expect(screen.getByTestId("channel-event-chip")).toHaveTextContent("kill");
    expect(row.querySelector("time")).toHaveTextContent("10:01");
    // Speech carries the avatar/name header; an event never does.
    expect(within(row).queryByTestId("channel-voice-avatar")).toBeNull();
  });

  it("the collapsed run reads as one timeline row with the count as the affordance", () => {
    const kills: ChannelRow[] = [1, 2, 3].map((n) => ({
      ts: `2026-08-15T11:0${n}:00Z`,
      kind: "event",
      message: `cluster killed: cl-${n} — reason ${n}`,
    }));
    render(<Channel initial={kills} initialAvailable={true} />);
    const wall = screen.getByTestId("channel-event-wall");
    expect(wall).toHaveClass("chn-event");
    expect(wall.querySelector(".chn-event-glyph")).not.toBeNull();
    const expand = screen.getByTestId("channel-event-wall-expand");
    expect(expand).toHaveClass("chn-collapse");
    expect(expand).toHaveTextContent("3 cluster kills — expand");
    // The run's span is still legible from the collapsed row.
    expect(wall.querySelector("time")).toHaveTextContent("11:01");
    expect(wall.querySelector("time")).toHaveTextContent("11:03");
  });
});

describe("/channel filter chips (R4)", () => {
  it("conversation hides events; events hides speech; all restores both", () => {
    render(<Channel initial={ROWS} initialAvailable={true} />);
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(4);
    expect(screen.getAllByTestId(/^channel-turn-/)).toHaveLength(3);

    fireEvent.click(screen.getByTestId("channel-filter-conversation"));
    expect(screen.queryAllByTestId("channel-event-row")).toHaveLength(0);
    expect(screen.getAllByTestId(/^channel-turn-/)).toHaveLength(3);

    fireEvent.click(screen.getByTestId("channel-filter-events"));
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(4);
    expect(screen.queryAllByTestId(/^channel-turn-/)).toHaveLength(0);

    fireEvent.click(screen.getByTestId("channel-filter-all"));
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(4);
    expect(screen.getAllByTestId(/^channel-turn-/)).toHaveLength(3);
  });

  it("the steward filter keeps the oracle exchange — its turn AND the reply", () => {
    const rows: ChannelRow[] = [
      { ts: "2026-08-16T01:00:00Z", kind: "human", message: "owner turn" },
      { ts: "2026-08-16T01:00:01Z", kind: "nara", message: "reply to owner" },
      { ts: "2026-08-16T01:27:06Z", kind: "oracle", message: "steward asks" },
      { ts: "2026-08-16T01:27:07Z", kind: "nara", message: "reply to steward" },
      { ts: "2026-08-16T01:30:00Z", kind: "event", message: "cycle: c1 — ok" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-filter-steward"));
    const turns = screen.getAllByTestId(/^channel-turn-/);
    expect(turns).toHaveLength(2);
    expect(turns[0]).toHaveTextContent("steward asks");
    expect(turns[1]).toHaveTextContent("reply to steward");
    // The owner's own exchange and apparatus events are not the steward's.
    expect(screen.queryByText("reply to owner")).toBeNull();
    expect(screen.queryAllByTestId("channel-event-row")).toHaveLength(0);
  });

  it("the active filter is aria-pressed (all by default)", () => {
    render(<Channel initial={ROWS} initialAvailable={true} />);
    expect(screen.getByTestId("channel-filter-all")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByTestId("channel-filter-events"));
    expect(screen.getByTestId("channel-filter-events")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("channel-filter-all")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("a filter that empties the feed says the rows are HIDDEN, not absent", () => {
    render(<Channel initial={[ROWS[4]]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-filter-events"));
    expect(screen.getByTestId("channel-filter-empty")).toHaveTextContent(
      "the filter is hiding them",
    );
    // The honest "nothing ever happened" state is a DIFFERENT state.
    expect(screen.queryByTestId("channel-empty")).toBeNull();
  });
});

describe("/channel day dividers (R4)", () => {
  it("splits the feed by UTC day, in order, naming the zone", () => {
    const rows: ChannelRow[] = [
      { ts: "2026-08-14T23:50:00Z", kind: "human", message: "late" },
      { ts: "2026-08-15T00:10:00Z", kind: "nara", message: "early" },
      { ts: "2026-08-15T09:00:00Z", kind: "human", message: "later" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    const dividers = screen.getAllByTestId("channel-day-divider");
    expect(dividers).toHaveLength(2);
    expect(dividers[0]).toHaveTextContent("Aug 14, 2026 · UTC");
    expect(dividers[1]).toHaveTextContent("Aug 15, 2026 · UTC");
  });

  it("a row whose ts does not parse lands under an honest 'undated' divider", () => {
    const rows: ChannelRow[] = [
      { ts: "", kind: "human", message: "no timestamp survived the seam" },
    ];
    render(<Channel initial={rows} initialAvailable={true} />);
    expect(screen.getByTestId("channel-day-divider")).toHaveTextContent(
      "undated",
    );
  });

  it("a collapsed event run never spans a day divider", () => {
    // Four kills, two on each side of midnight: two runs of two, not one of 4.
    const kills: ChannelRow[] = [
      "2026-08-14T23:40:00Z",
      "2026-08-14T23:50:00Z",
      "2026-08-15T00:10:00Z",
      "2026-08-15T00:20:00Z",
    ].map((ts, i) => ({
      ts,
      kind: "event",
      message: `cluster killed: cl-${i} — reason`,
    }));
    render(<Channel initial={kills} initialAvailable={true} />);
    expect(screen.queryByTestId("channel-event-wall")).toBeNull();
    expect(screen.getAllByTestId("channel-event-row")).toHaveLength(4);
    expect(screen.getAllByTestId("channel-day-divider")).toHaveLength(2);
  });
});

// Fixtures for the reference peek. Each is the SHAPE the real endpoint
// returns (found-flagged for finding/journey, a cluster list for the ladder).
const LADDER_PAYLOAD = {
  clusters: [
    {
      cluster_id: "cl-x",
      stem: "eviction bias survives 4-bit quantization",
      status: "killed",
      evidence_level: "L2",
      member_count: 3,
      last_event_ts: "2026-08-15T10:01:00Z",
      kill_reason: { code: "rediscovery", detail: "already in the literature" },
    },
  ],
  histogram: {},
  counts: {},
  agenda: [],
};

const inRouter = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("/channel reference chips → peek (R4)", () => {
  it("ids the apparatus wrote render as chips inline, without swallowing punctuation", () => {
    const rows: ChannelRow[] = [
      {
        ts: "2026-08-15T10:00:00Z",
        kind: "human",
        message: "did cl-x die before iter-2026-08-15-001, or after sf-009?",
      },
    ];
    inRouter(<Channel initial={rows} initialAvailable={true} />);
    const chips = screen.getAllByTestId("channel-ref-chip");
    expect(chips.map((c) => c.textContent)).toEqual([
      "cl-x",
      "iter-2026-08-15-001",
      "sf-009",
    ]);
    expect(chips.map((c) => c.getAttribute("data-ref-kind"))).toEqual([
      "cluster",
      "iteration",
      "finding",
    ]);
    // The surrounding prose survives verbatim, punctuation and all.
    expect(screen.getByTestId("channel-voice-body")).toHaveTextContent(
      "did cl-x die before iter-2026-08-15-001, or after sf-009?",
    );
    // A chip is inert until clicked — no page load ever fetches these.
    expect(mocks.getLadder).not.toHaveBeenCalled();
    expect(mocks.getFindingDetail).not.toHaveBeenCalled();
    expect(mocks.getIterationJourney).not.toHaveBeenCalled();
  });

  it("a cluster chip peeks the ladder row — and never inlines it into the thread", async () => {
    mocks.getLadder.mockResolvedValue(LADDER_PAYLOAD);
    inRouter(<Channel initial={[ROWS[1]]} initialAvailable={true} />);

    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-body")).toBeInTheDocument(),
    );
    expect(mocks.getLadder).toHaveBeenCalledTimes(1);
    const peek = screen.getByTestId("peek-panel");
    expect(within(peek).getByTestId("channel-peek-headline")).toHaveTextContent(
      "eviction bias survives 4-bit quantization",
    );
    expect(peek).toHaveTextContent("killed");
    expect(peek).toHaveTextContent("rediscovery");
    expect(within(peek).getByTestId("channel-peek-link")).toHaveAttribute(
      "href",
      "/ladder",
    );
    // THE THREAD IS NOT AN OBJECT VIEWER: the feed still shows only the chip.
    expect(screen.getByTestId("channel-feed")).not.toHaveTextContent(
      "eviction bias survives 4-bit quantization",
    );
  });

  it("a finding chip peeks /api/finding/{id} and links to its dossier", async () => {
    mocks.getFindingDetail.mockResolvedValue({
      found: true,
      finding_id: "sf-009",
      title: "eviction bias holds at 4-bit",
      claim: "the bias is unchanged under NVFP4",
      status: "promoted",
      novelty_class: "novel",
      source_iteration_id: "iter-2026-08-15-001",
    });
    inRouter(<Channel initial={[ROWS[2]]} initialAvailable={true} />);

    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-body")).toBeInTheDocument(),
    );
    expect(mocks.getFindingDetail).toHaveBeenCalledWith("sf-009");
    const peek = screen.getByTestId("peek-panel");
    expect(within(peek).getByTestId("channel-peek-headline")).toHaveTextContent(
      "eviction bias holds at 4-bit",
    );
    expect(peek).toHaveTextContent("the bias is unchanged under NVFP4");
    expect(within(peek).getByTestId("channel-peek-link")).toHaveAttribute(
      "href",
      "/dossier/sf-009",
    );
  });

  it("an iteration chip peeks the journey endpoint", async () => {
    mocks.getIterationJourney.mockResolvedValue({
      found: true,
      iteration_id: "iter-2026-08-15-001",
      iteration: {
        iteration_id: "iter-2026-08-15-001",
        started_at: "2026-08-15T09:00:00Z",
        ended_at: "2026-08-15T09:40:00Z",
        seed: { topic: "kv-cache eviction under quantization" },
        gate_status: "valid",
        novelty: { class: "novel" },
      },
    });
    const rows: ChannelRow[] = [
      {
        ts: "2026-08-15T10:00:00Z",
        kind: "human",
        message: "what came out of iter-2026-08-15-001?",
      },
    ];
    inRouter(<Channel initial={rows} initialAvailable={true} />);

    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-body")).toBeInTheDocument(),
    );
    expect(mocks.getIterationJourney).toHaveBeenCalledWith(
      "iter-2026-08-15-001",
    );
    const peek = screen.getByTestId("peek-panel");
    expect(within(peek).getByTestId("channel-peek-headline")).toHaveTextContent(
      "kv-cache eviction under quantization",
    );
    expect(peek).toHaveTextContent("valid");
    expect(within(peek).getByTestId("channel-peek-link")).toHaveAttribute(
      "href",
      "/dossier/iter-2026-08-15-001",
    );
  });

  it("an id the backend does not know renders an honest not-found, never an invented summary", async () => {
    mocks.getFindingDetail.mockResolvedValue({
      found: false,
      finding_id: "sf-009",
    });
    inRouter(<Channel initial={[ROWS[2]]} initialAvailable={true} />);

    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-missing")).toHaveTextContent(
        "sf-009 is not in surfaced_findings",
      ),
    );
    expect(screen.queryByTestId("channel-peek-body")).toBeNull();
    expect(screen.queryByTestId("channel-peek-headline")).toBeNull();
  });

  it("a cluster id absent from the ledger reads as absent, not as an empty cluster", async () => {
    mocks.getLadder.mockResolvedValue({ ...LADDER_PAYLOAD, clusters: [] });
    inRouter(<Channel initial={[ROWS[1]]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-missing")).toHaveTextContent(
        "cl-x is not in the idea ledger",
      ),
    );
  });

  it("a version-skew 404 on the peek read degrades quietly, writing nothing", async () => {
    mocks.getLadder.mockRejectedValue(
      Object.assign(new Error("404 Not Found"), { status: 404 }),
    );
    inRouter(<Channel initial={[ROWS[1]]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-missing")).toHaveTextContent(
        "version skew",
      ),
    );
    expect(screen.queryByTestId("channel-peek-error")).toBeNull();
  });

  it("a model turn keeps its MiniMarkdown body; its ids ride a chip row beneath", () => {
    const rows: ChannelRow[] = [
      {
        ts: "2026-08-15T10:00:00Z",
        kind: "nara",
        message: "**cl-x** died; see sf-009 and cl-x again",
      },
    ];
    inRouter(<Channel initial={rows} initialAvailable={true} />);
    const nara = screen.getByTestId("channel-turn-nara");
    expect(within(nara).getByTestId("mini-markdown")).toBeInTheDocument();
    const refRow = within(nara).getByTestId("channel-voice-refs");
    // Deduped, in first-mention order.
    expect(
      within(refRow)
        .getAllByTestId("channel-ref-chip")
        .map((c) => c.textContent),
    ).toEqual(["cl-x", "sf-009"]);
  });

  it("Esc closes the peek (the R0 panel behavior is really wired)", async () => {
    mocks.getLadder.mockResolvedValue(LADDER_PAYLOAD);
    inRouter(<Channel initial={[ROWS[1]]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("peek-panel")).toBeInTheDocument(),
    );
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("peek-panel")).toBeNull());
  });
});

describe("/channel pending turn + jump to present (R4)", () => {
  it("a turn in flight shows a pending block; no stop affordance is faked", async () => {
    let settle: (v: unknown) => void = () => {};
    mocks.postChannelTurn.mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    mocks.getChannelTimeline.mockResolvedValue({ rows: [] });
    render(<Channel initial={[]} initialAvailable={true} />);

    fireEvent.change(screen.getByLabelText("channel turn input"), {
      target: { value: "what is alive?" },
    });
    fireEvent.click(screen.getByTestId("channel-send"));

    const pending = await screen.findByTestId("channel-pending-turn");
    expect(pending).toHaveTextContent("nara is composing");
    // The seam exposes no abort verb, so the page offers no stop button
    // rather than a button that would not actually stop the CLI.
    const feedButtons = within(screen.getByTestId("channel-feed"))
      .queryAllByRole("button")
      .map((b) => (b.textContent ?? "").toLowerCase())
      .join(" · ");
    for (const verb of ["stop", "abort", "cancel", "interrupt"]) {
      expect(feedButtons).not.toContain(verb);
    }

    settle({ status: "passed" });
    await waitFor(() =>
      expect(screen.queryByTestId("channel-pending-turn")).toBeNull(),
    );
  });

  it("scrolling up reveals 'jump to present'; clicking it returns to the newest row", () => {
    render(<Channel initial={ROWS} initialAvailable={true} />);
    const feed = screen.getByTestId("channel-feed");
    // jsdom reports every height as 0 — give the scroller a real geometry.
    Object.defineProperty(feed, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(feed, "clientHeight", { value: 300, configurable: true });

    expect(screen.queryByTestId("channel-jump-present")).toBeNull();
    feed.scrollTop = 0;
    fireEvent.scroll(feed);
    expect(screen.getByTestId("channel-jump-present")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("channel-jump-present"));
    expect(feed.scrollTop).toBe(1000);
    expect(screen.queryByTestId("channel-jump-present")).toBeNull();
  });
});

describe("/channel fence — no disposition surface anywhere", () => {
  it("renders no verdict/disposition control on the whole page", () => {
    const { container } = render(
      <Channel initial={ROWS} initialAvailable={true} />,
    );
    // No testid on the page carries a disposition name.
    for (const fragment of ["verdict", "disposition", "sign-off", "signoff",
      "finding-review", "gate-verdict"]) {
      expect(
        container.querySelector(`[data-testid*="${fragment}"]`),
      ).toBeNull();
    }
    // No button offers a disposition verb. (The only buttons are the role
    // chips, send, the delegate kind chips, review, confirm, cancel.)
    const buttonText = Array.from(container.querySelectorAll("button"))
      .map((b) => b.textContent ?? "")
      .join(" · ")
      .toLowerCase();
    for (const verb of ["verdict", "validated", "rejected", "sign off",
      "approve", "promote", "kill"]) {
      expect(buttonText).not.toContain(verb);
    }
  });

  it("the reference peek is read-only too — a summary and one link, no disposition", async () => {
    mocks.getFindingDetail.mockResolvedValue({
      found: true,
      finding_id: "sf-009",
      title: "eviction bias holds at 4-bit",
      status: "promoted",
      novelty_class: "novel",
    });
    inRouter(<Channel initial={[ROWS[2]]} initialAvailable={true} />);
    fireEvent.click(screen.getByTestId("channel-ref-chip"));
    await waitFor(() =>
      expect(screen.getByTestId("channel-peek-body")).toBeInTheDocument(),
    );

    // The panel is portal-rendered, so the fence is checked on the panel.
    const peek = screen.getByTestId("peek-panel");
    for (const fragment of ["verdict", "disposition", "sign-off", "signoff",
      "finding-review", "gate-verdict"]) {
      expect(peek.querySelector(`[data-testid*="${fragment}"]`)).toBeNull();
    }
    expect(peek.querySelectorAll("form")).toHaveLength(0);
    expect(peek.querySelectorAll("textarea")).toHaveLength(0);
    // Its only button is the panel's own close control.
    const peekButtons = Array.from(peek.querySelectorAll("button"));
    expect(peekButtons).toHaveLength(1);
    expect(peekButtons[0]).toHaveAttribute("aria-label", "close panel");
  });
});
