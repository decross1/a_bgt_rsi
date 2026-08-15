// /channel — the S4 lab channel surface. Pins: the merged feed (voice
// bubbles + event system-lines with kind chips), the one-model honesty note
// beside the role selector, the turn post (role threads through), the
// capability-off preview state (send disabled, nothing posted), the delegate
// CONFIRM-CARD flow — the confirm click is the ONLY path that posts — and
// THE FENCE: no disposition surface exists anywhere on the page. Skew (404
// on /api/channel/timeline) renders the quiet EndpointMissingNote.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
