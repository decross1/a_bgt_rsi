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
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChannelRow } from "../src/api/channel";

const mocks = vi.hoisted(() => ({
  getChannelAvailability: vi.fn(),
  getChannelTimeline: vi.fn(),
  postChannelTurn: vi.fn(),
  postChannelDelegate: vi.fn(),
}));
vi.mock("../src/api/channel", () => ({
  getChannelAvailability: mocks.getChannelAvailability,
  getChannelTimeline: mocks.getChannelTimeline,
  postChannelTurn: mocks.postChannelTurn,
  postChannelDelegate: mocks.postChannelDelegate,
}));
// EndpointMissingNote self-fetches /api/health when no version prop is
// passed; mock the http module so the skew test stays fetch-free.
vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: null,
    version: "testsha",
  }),
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
});
