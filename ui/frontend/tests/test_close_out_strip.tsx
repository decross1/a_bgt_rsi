// CloseOutStrip — the session CLOSE-OUT surface (GAP 2, 2026-08-19).
//
// The owner test-driving the cockpit asked "how do we get the outcome of this
// to yield a follow up for nara?" and could not find the answer on screen —
// even though `finding_session.end_session` has always routed it
// (spawn_topic -> memory/finding_followups.jsonl -> the daemon -> the
// coordinator's topic list). These pins hold the answer VISIBLE:
//
//  1. the four real outcomes are NAMED with what each writes and what
//     consumes it — sourced from GET /api/todo/close_out (the backend's own
//     truth), never frontend prose that can drift from the writers;
//  2. spawn_topic is the one interactive path and it posts the EXISTING
//     /api/todo/spawn_topic seam (a SESSION-EXIT that writes nothing) —
//     no seam is re-implemented — and its REQUEST BODY is pinned at the wire
//     (stubbed `fetch`, un-mocked client), not merely as the argument handed
//     to a mocked `postSpawnTopic`. Mocking the client is what let the
//     `ref_id` / `finding_id` mismatch 422 on every real call while the suite
//     stayed green;
//  3. the topic is PREFILLED from the attacker's last turn when one exists,
//     the source is shown read-only, and the human's edits win;
//  4. THE FENCE HOLDS: the strip records no verdict and says so; a version-
//     skewed backend degrades honestly instead of inventing outcome copy;
//  5. mounted in the two_voice pane (the pane the owner used), never in the
//     single-voice tutor pane (which has no attacker to suggest anything).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CloseOutStrip from "../src/components/todo/CloseOutStrip";
import ChatPane from "../src/components/todo/ChatPane";
import * as todoApi from "../src/api/todo";
import type { ChatStartResult, ChatTurnResult } from "../src/types/todo";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const DESCRIPTOR = {
  available: true,
  writer: "orchestrator.finding_session (end_session)",
  followups_queue: "memory/finding_followups.jsonl",
  outcomes: [
    {
      outcome: "validated",
      label: "validate",
      endpoint: "/api/attest/finding_review",
      writes: "memory/loop_feedback.jsonl (verdict `valid`) + a status-audit row",
      downstream: "the Step-8 human-gate edge",
      session_exit: false,
    },
    {
      outcome: "rejected",
      label: "reject",
      endpoint: "/api/attest/finding_review",
      writes: "memory/loop_feedback.jsonl (verdict `invalid`) + a status-audit row",
      downstream: "the human-gate edge",
      session_exit: false,
    },
    {
      outcome: "spawn_topic",
      label: "spawn follow-up topic",
      endpoint: "/api/todo/spawn_topic",
      writes: "memory/finding_followups.jsonl (one queue row; NO verdict)",
      downstream:
        "the nara daemon watches the queue and the coordinator consumes the row as a TOPIC",
      session_exit: true,
    },
    {
      outcome: "refine",
      label: "refine",
      endpoint: "/api/attest/finding_review",
      writes: "a status-audit row only (status `in_review`) — NO verdict ledger row",
      downstream: "the finding parks in_review for another pass",
      session_exit: false,
    },
  ],
};

const ATTACKER = "The claim conflates the memory window with the prompt size — rerun with matched padding.";

const descriptorFn = (d: unknown = DESCRIPTOR) => vi.fn(async () => d as never);

describe("CloseOutStrip — the outcomes are NAMED with their downstream", () => {
  it("renders the four real outcomes and the nara follow-up chain", async () => {
    render(
      <CloseOutStrip findingId="sf-001" fetchDescriptor={descriptorFn()} />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("close-out-outcome")).toHaveLength(4),
    );
    const text = screen.getByTestId("close-out-outcomes").textContent ?? "";
    for (const label of ["validate", "reject", "spawn follow-up topic", "refine"]) {
      expect(text).toContain(label);
    }
    // The answer to the owner's question, on screen.
    expect(text).toContain("nara daemon");
    expect(text).toContain("coordinator");
    expect(text).toContain("finding_followups.jsonl");
    // refine is honest about writing NO verdict.
    expect(text).toContain("NO verdict ledger row");
  });

  it("names its own fence: the dispositions live in the footer, not here", async () => {
    render(
      <CloseOutStrip findingId="sf-001" fetchDescriptor={descriptorFn()} />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-fence")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("close-out-fence").textContent).toMatch(
      /disposition footer/i,
    );
    // No verdict-shaped control is reachable from the strip.
    for (const re of [/^validate$/i, /^reject$/i, /sign[\s_-]?off/i, /refine/i]) {
      expect(screen.queryByRole("button", { name: re })).toBeNull();
    }
  });

  it("a version-skewed backend degrades honestly and never invents outcomes", async () => {
    render(
      <CloseOutStrip
        findingId="sf-001"
        fetchDescriptor={vi.fn(async () => ({
          available: false, writer: "", followups_queue: "",
          outcomes: [], skew: true,
        }) as never)}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-skew")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("close-out-skew").textContent).toContain(
      "UNAVAILABLE",
    );
    expect(screen.queryByTestId("close-out-outcome")).toBeNull();
    // The follow-up path still works — it is a different (existing) seam.
    expect(screen.getByTestId("close-out-spawn")).toBeInTheDocument();
  });

  it("a failed descriptor fetch degrades instead of throwing", async () => {
    render(
      <CloseOutStrip
        findingId="sf-001"
        fetchDescriptor={vi.fn(async () => {
          throw new Error("boom");
        })}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-skew")).toBeInTheDocument(),
    );
  });
});

describe("CloseOutStrip — the attacker prefill", () => {
  it("prefills the topic from the attacker's last turn and shows the source read-only", async () => {
    render(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={ATTACKER}
        fetchDescriptor={descriptorFn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-prefill-text")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("close-out-prefill-text").textContent).toBe(
      ATTACKER,
    );
    // The seed lands in a FOLLOW-UP commit (an effect keyed on the
    // suggestion), so wait for the settled value rather than the render that
    // merely revealed the source — asserting synchronously after waitFor
    // races the second commit under load.
    await waitFor(() =>
      expect(
        (screen.getByLabelText(/follow-up topic/i) as HTMLTextAreaElement).value,
      ).toBe(ATTACKER),
    );
  });

  it("the human's edit wins — a later prefill never overwrites the draft", async () => {
    const { rerender } = render(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={ATTACKER}
        fetchDescriptor={descriptorFn()}
      />,
    );
    const field = () =>
      screen.getByLabelText(/follow-up topic/i) as HTMLTextAreaElement;
    await waitFor(() => expect(field().value).toBe(ATTACKER));
    fireEvent.change(field(), { target: { value: "my own narrower topic" } });
    rerender(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={`${ATTACKER} (and another point)`}
        fetchDescriptor={descriptorFn()}
      />,
    );
    expect(field().value).toBe("my own narrower topic");
    // …and the human can deliberately go back to the suggestion.
    fireEvent.click(screen.getByTestId("close-out-reset-prefill"));
    expect(field().value).toBe(`${ATTACKER} (and another point)`);
  });

  it("no attacker turn: says so rather than inventing a topic", async () => {
    render(
      <CloseOutStrip findingId="sf-001" fetchDescriptor={descriptorFn()} />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-no-prefill")).toBeInTheDocument(),
    );
    expect(
      (screen.getByLabelText(/follow-up topic/i) as HTMLTextAreaElement).value,
    ).toBe("");
    expect(screen.getByTestId("close-out-spawn")).toBeDisabled();
  });
});

describe("CloseOutStrip — spawn posts the EXISTING seam", () => {
  it("posts /api/todo/spawn_topic with the finding, kind and edited topic", async () => {
    const spy = vi
      .spyOn(todoApi, "postSpawnTopic")
      .mockResolvedValue({ status: "session_exit", outcome: "spawn_topic" });
    render(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={ATTACKER}
        fetchDescriptor={descriptorFn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-spawn")).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText(/follow-up kind/i), {
      target: { value: "step" },
    });
    fireEvent.change(screen.getByLabelText(/follow-up topic/i), {
      target: { value: "rerun with matched padding" },
    });
    fireEvent.click(screen.getByTestId("close-out-spawn"));

    await waitFor(() =>
      expect(screen.getByTestId("close-out-result")).toBeInTheDocument(),
    );
    expect(spy).toHaveBeenCalledWith({
      finding_id: "sf-001",
      kind: "step",
      topic: "rerun with matched padding",
    });
    // The honest session-exit copy — end_session is the writer of record.
    expect(screen.getByTestId("close-out-result").textContent).toContain(
      "session exit",
    );
    expect(screen.getByTestId("close-out-result").textContent).toContain(
      "nothing was written here",
    );
  });

  // THE WIRE PIN. The test above mocks `postSpawnTopic`, so it can only pin
  // the ARGUMENT — never the request that leaves the browser. That blind spot
  // is exactly where the bug lived: the client posted `{ref_id, kind, topic}`
  // while the backend read `finding_id`, so every real spawn 422'd
  // ("finding_id is required") while the suite stayed green. This one stubs
  // `fetch` and asserts the BODY, with the client un-mocked.
  it("the REQUEST BODY carries finding_id — the key the backend reads", async () => {
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({
          url: String(url),
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        });
        return new Response(
          JSON.stringify({ status: "session_exit", outcome: "spawn_topic" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    render(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={ATTACKER}
        fetchDescriptor={descriptorFn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-spawn")).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText(/follow-up topic/i), {
      target: { value: "rerun with matched padding" },
    });
    fireEvent.click(screen.getByTestId("close-out-spawn"));
    await waitFor(() => expect(calls.length).toBe(1));

    const [call] = calls;
    expect(call.url).toContain("/api/todo/spawn_topic");
    // The exact wire contract: the id key the router requires, and NO alias.
    expect(call.body).toEqual({
      finding_id: "sf-001",
      kind: "finding",
      topic: "rerun with matched padding",
    });
    expect(Object.keys(call.body)).not.toContain("ref_id");
  });

  it("a failed spawn surfaces the stderr VERBATIM", async () => {
    vi.spyOn(todoApi, "postSpawnTopic").mockRejectedValue(
      new todoApi.TodoError(502, "d", 1, "rejected: finding_id is required"),
    );
    render(
      <CloseOutStrip
        findingId="sf-001"
        attackerSuggestion={ATTACKER}
        fetchDescriptor={descriptorFn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("close-out-spawn")).toBeEnabled(),
    );
    fireEvent.click(screen.getByTestId("close-out-spawn"));
    await waitFor(() =>
      expect(screen.getByTestId("close-out-stderr")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("close-out-stderr").textContent).toBe(
      "rejected: finding_id is required",
    );
    expect(screen.queryByTestId("close-out-result")).toBeNull();
  });
});

// ─── mounted in the session pane the owner used ─────────────────────────

const START_TWO_VOICE: ChatStartResult = {
  ok: true, mode: "two_voice", action: "start",
  finding_id: "sf-iter-x", session_id: "sess-2v-1",
  stances: { defender: "gemma", attacker: "qwen" },
};

function twoVoiceTurn(): ChatTurnResult {
  return {
    ok: true, mode: "two_voice", action: "turn",
    finding_id: "sf-iter-x", session_id: "sess-2v-1", turn_index: 1,
    addressee: "both",
    replies: [
      { stance: "defender", reply: "the mechanism holds", request_id: "r1" },
      { stance: "attacker", reply: ATTACKER, request_id: "r2" },
    ],
  };
}

describe("ChatPane — the strip is PERSISTENT in the two-voice pane", () => {
  it("renders before any turn (the point: the human sees it BEFORE deciding)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, statusText: "200",
      json: async () => DESCRIPTOR,
    }) as Response));
    render(<ChatPane findingId="sf-iter-x" mode="two_voice" available />);
    await waitFor(() =>
      expect(screen.getAllByTestId("close-out-outcome")).toHaveLength(4),
    );
    expect(screen.getByTestId("close-out-no-prefill")).toBeInTheDocument();
  });

  it("the attacker's last reply becomes the prefill after a turn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, statusText: "200",
      json: async () => DESCRIPTOR,
    }) as Response));
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_TWO_VOICE);
    vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(twoVoiceTurn());

    render(<ChatPane findingId="sf-iter-x" mode="two_voice" available />);
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "attack it" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));

    await waitFor(() =>
      expect(screen.getByTestId("close-out-prefill-text")).toBeInTheDocument(),
    );
    // The ATTACKER's reply, not the defender's.
    expect(screen.getByTestId("close-out-prefill-text").textContent).toBe(
      ATTACKER,
    );
    await waitFor(() =>
      expect(
        (screen.getByLabelText(/follow-up topic/i) as HTMLTextAreaElement).value,
      ).toBe(ATTACKER),
    );
  });

  it("the single-voice tutor pane carries NO close-out strip", () => {
    render(<ChatPane findingId="sf-iter-x" mode="tutor" available />);
    expect(screen.queryByTestId("close-out-strip")).toBeNull();
  });
});
