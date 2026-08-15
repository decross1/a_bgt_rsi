// ChatPane — the ONE mode-parameterized chat pane (UI simplification S2;
// merges the retired TutorChatPane + TwoVoiceChatPane). This file carries the
// substantive pins of BOTH retired suites (test_TutorChatPane.tsx +
// test_harden_TwoVoiceChatPane.tsx's live-mode blocks), with the fence-note
// assertions carried VERBATIM:
//
//   TUTOR mode:
//   - the FENCE is visible and cites the REAL source (D-053/D-054, NOT D-044);
//   - available=false keeps the pane an honest disabled state (no model call);
//   - available=true: typing + send opens a session (postChatStart) then posts
//     a tutor TURN (postChatTurn with mode:"tutor" and NO addressee) and
//     renders the tutor reply (single voice, no stance);
//   - a start/turn error DEGRADES legibly; a hostile envelope never crashes;
//   - THE VERDICT FENCE: no verdict control exists, the word "verdict" appears
//     ONLY in the fence note, and D-044 never appears on this single-voice
//     teaching surface.
//
//   TWO_VOICE mode:
//   - the two-stance layout (Gemma DEFENDS / Qwen ATTACKS, D-044) + the
//     addressee selector + the cap intent + its own D-044 fence note;
//   - a live send threads the SELECTED addressee into postChatTurn and renders
//     stance-tagged replies; unknown/prototype-colliding stances degrade;
//   - THE FENCE AT THE WIRE: only postChatStart/postChatTurn ever fire — no
//     verdict/disposition POST is reachable from either mode.
//
// STRUCTURALLY fence-preserving: the component accepts NO verdict /
// confidence / onResolved / setter prop (asserted below against its rendered
// surface; the prop surface is enforced by the TS interface). useChatSession
// is untouched by the merge — its own suite still owns the session mechanics.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ChatPane from "../src/components/todo/ChatPane";
import * as todoApi from "../src/api/todo";
import type { ChatStartResult, ChatTurnResult } from "../src/types/todo";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const START_TUTOR: ChatStartResult = {
  ok: true,
  mode: "tutor",
  action: "start",
  finding_id: "sf-iter-x",
  session_id: "sess-tutor-1",
  stances: null,
};

const START_TWO_VOICE: ChatStartResult = {
  ok: true,
  mode: "two_voice",
  action: "start",
  finding_id: "sf-iter-x",
  session_id: "sess-2v-1",
  stances: { defender: "gemma", attacker: "qwen" },
};

function tutorTurn(reply: string): ChatTurnResult {
  return {
    ok: true,
    mode: "tutor",
    action: "turn",
    finding_id: "sf-iter-x",
    session_id: "sess-tutor-1",
    turn_index: 0,
    capped: false,
    warning: null,
    replies: [{ stance: null, reply, request_id: "req-1" }],
  };
}

function twoVoiceTurn(): ChatTurnResult {
  return {
    ok: true,
    mode: "two_voice",
    action: "turn",
    finding_id: "sf-iter-x",
    session_id: "sess-2v-1",
    turn_index: 0,
    capped: false,
    addressee: "both",
    warning: null,
    replies: [
      { stance: "defender", reply: "I stand by the finding.", request_id: "r-d" },
      { stance: "attacker", reply: "Your sample is biased.", request_id: "r-a" },
    ],
  };
}

function renderQuietly(ui: React.ReactElement) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  let container!: HTMLElement;
  expect(() => {
    container = render(ui).container;
  }).not.toThrow();
  return { container, errorSpy, warnSpy };
}

// ═══════════════════════ TUTOR mode ═══════════════════════

describe("ChatPane mode=tutor — fence", () => {
  it("renders the pane and a visible fence note citing the REAL source (NOT D-044)", () => {
    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" />);
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
    const fence = screen.getByTestId("tutor-chat-fence-note");
    expect(fence).toHaveTextContent(/does not affect your verdict/i);
    expect(fence).toHaveTextContent(/never recommends/i);
    expect(fence).toHaveTextContent(/D-053/);
    // D-044 (the two-voice independence fence) must NOT appear on the
    // single-voice tutor surface.
    expect(screen.getByTestId("tutor-chat-pane").textContent ?? "").not.toMatch(
      /D-044/,
    );
  });

  it("exposes NO verdict control; the word 'verdict' appears ONLY in the fence note", () => {
    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" available />);
    // No verdict-shaped buttons leak through this teaching surface.
    expect(screen.queryByRole("button", { name: /valid/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /invalid/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /needs_revision/i })).toBeNull();
    // "verdict" is single-match: only the fence note carries it.
    expect(screen.queryByText(/verdict/i)).toHaveTextContent(
      /does not affect your verdict/i,
    );
  });

  it("renders no verdict/disposition/confidence/calibration control in ANY pane state (live or stub)", () => {
    // Adversarial fence pin: prove the disposition-verbs never surface as a
    // control regardless of `available` — the pane is STRUCTURALLY verdict-free.
    for (const available of [true, false] as const) {
      const { unmount } = render(
        <ChatPane findingId="sf-iter-x" mode="tutor" available={available} />,
      );
      for (const re of [
        /verdict/i,
        /disposition/i,
        /confidence/i,
        /calibration/i,
        /sign[\s_-]?off/i,
        /authorize/i,
        /abstain/i,
        /resolve/i,
        /approve/i,
        /reject/i,
      ]) {
        expect(
          screen.queryByRole("button", { name: re }),
          `verdict-shaped control leaked (available=${available}): ${re}`,
        ).toBeNull();
        // No verdict slider/number input either (confidence capture).
        expect(screen.queryByRole("slider")).toBeNull();
        expect(screen.queryByRole("spinbutton")).toBeNull();
      }
      unmount();
    }
  });

  it("the pane issues ONLY postChatStart/postChatTurn — never a verdict/feedback/gate/calibration POST", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_TUTOR);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(tutorTurn("a reply"));
    // Every non-chat POST the cockpit client exposes — none may be called.
    const verdictWriters = [
      "postDirectiveSignoff",
      "postAuthorizeFix",
      "postSpawnTopic",
      "postAbstain",
      "postCalibration",
    ] as const;
    const writerSpies = verdictWriters.map((name) =>
      vi.spyOn(todoApi, name).mockResolvedValue({}),
    );

    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" available />);
    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "ask" },
    });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() =>
      expect(screen.getByTestId("tutor-chat-reply")).toBeInTheDocument(),
    );

    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy).toHaveBeenCalledTimes(1);
    for (const s of writerSpies) expect(s).not.toHaveBeenCalled();
  });
});

describe("ChatPane mode=tutor — availability", () => {
  it("available=false: send is disabled and no model call is made", () => {
    const startSpy = vi.spyOn(todoApi, "postChatStart");
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");
    renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="tutor" available={false} />,
    );
    expect(screen.getByTestId("tutor-chat-stub-banner")).toBeInTheDocument();
    // Even with text typed, the disabled send stays disabled.
    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "why was this surfaced?" },
    });
    expect(screen.getByTestId("tutor-chat-send")).toBeDisabled();
    expect(startSpy).not.toHaveBeenCalled();
    expect(turnSpy).not.toHaveBeenCalled();
  });

  it("available=true with no text keeps send disabled (never posts an empty turn)", () => {
    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" available />);
    expect(screen.queryByTestId("tutor-chat-stub-banner")).toBeNull();
    expect(screen.getByTestId("tutor-chat-send")).toBeDisabled();
  });
});

describe("ChatPane mode=tutor — live send", () => {
  it("typing + send opens a session then posts a tutor turn (mode:tutor, NO addressee) and renders the reply", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_TUTOR);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(tutorTurn("It was surfaced because the critic let it pass."));

    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" available />);

    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "why was this surfaced?" },
    });
    const send = screen.getByTestId("tutor-chat-send");
    expect(send).toBeEnabled();
    fireEvent.click(send);

    await waitFor(() =>
      expect(screen.getByTestId("tutor-chat-reply")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-chat-reply")).toHaveTextContent(
      "It was surfaced because the critic let it pass.",
    );

    // start was called once with mode tutor + the finding.
    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(startSpy).toHaveBeenCalledWith({
      mode: "tutor",
      finding_id: "sf-iter-x",
    });
    // turn was called once threading the session id, with NO addressee key.
    expect(turnSpy).toHaveBeenCalledTimes(1);
    const turnArg = turnSpy.mock.calls[0][0];
    expect(turnArg).toMatchObject({
      mode: "tutor",
      finding_id: "sf-iter-x",
      session_id: "sess-tutor-1",
      message: "why was this surfaced?",
    });
    expect(turnArg).not.toHaveProperty("addressee");
  });

  it("a SECOND send reuses the session (start once, turn twice)", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_TUTOR);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValueOnce(tutorTurn("first reply"))
      .mockResolvedValueOnce(tutorTurn("second reply"));

    renderQuietly(<ChatPane findingId="sf-iter-x" mode="tutor" available />);
    const input = screen.getByLabelText(/tutor chat input/i);

    fireEvent.change(input, { target: { value: "q1" } });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("tutor-chat-reply").length).toBe(1),
    );

    fireEvent.change(input, { target: { value: "q2" } });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("tutor-chat-reply").length).toBe(2),
    );

    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy).toHaveBeenCalledTimes(2);
  });
});

describe("ChatPane mode=tutor — degrade", () => {
  it("a start error degrades to a legible error, never throws or blanks", async () => {
    vi.spyOn(todoApi, "postChatStart").mockRejectedValue(
      new todoApi.TodoError(502, "boom", 1, "ValueError: finding-id is required"),
    );
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");

    const { errorSpy } = renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="tutor" available />,
    );
    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "anything" },
    });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));

    await waitFor(() =>
      expect(screen.getByTestId("tutor-chat-error")).toBeInTheDocument(),
    );
    // The CLI's stderr is shown verbatim (D-046), the pane survives, no reply
    // is fabricated, and turn is never reached.
    expect(screen.getByTestId("tutor-chat-error")).toHaveTextContent(
      /finding-id is required/i,
    );
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-chat-reply")).toBeNull();
    expect(turnSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("a hostile envelope (replies non-array / non-string reply) never crashes the pane", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_TUTOR);
    vi.spyOn(todoApi, "postChatTurn")
      .mockResolvedValueOnce({
        ok: true,
        action: "turn",
        session_id: "sess-tutor-1",
        replies: { not: "an array" } as unknown as ChatTurnResult["replies"],
      })
      .mockResolvedValueOnce({
        ok: true,
        action: "turn",
        session_id: "sess-tutor-1",
        replies: [
          { stance: null, reply: { body: "obj" } as unknown as string, request_id: null },
        ],
      });

    const { container, errorSpy } = renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="tutor" available />,
    );
    const input = screen.getByLabelText(/tutor chat input/i);

    // Non-array replies → no rows appended, no crash, the pane stays.
    fireEvent.change(input, { target: { value: "q1" } });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
    expect(screen.queryByTestId("tutor-chat-reply")).toBeNull();

    // Non-string reply → the row renders but degrades to "", no [object Object].
    fireEvent.change(input, { target: { value: "q2" } });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() =>
      expect(screen.getByTestId("tutor-chat-reply")).toBeInTheDocument(),
    );
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

// ═══════════════════════ TWO_VOICE mode ═══════════════════════

describe("ChatPane mode=two_voice — layout + fence", () => {
  it("renders the two-stance layout, the cap intent, and its D-044 fence note", () => {
    renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" turnCap={24} tokenCap={1024} />,
    );
    // D-044: Gemma defends, Qwen attacks (the interrogator is not the author).
    expect(screen.getByTestId("stance-defender")).toHaveTextContent(/Gemma DEFENDS/i);
    expect(screen.getByTestId("stance-attacker")).toHaveTextContent(/Qwen ATTACKS/i);
    // Cap intent shown read-only.
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/24 turns/);
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/1024 tok/);
    // The two-voice fence note cites D-044 independence.
    const fence = screen.getByTestId("two-voice-fence-note");
    expect(fence).toHaveTextContent(/does not affect your verdict/i);
    expect(fence).toHaveTextContent(/D-044/);
    // Capability-off banner present; no model calls.
    expect(screen.getByTestId("two-voice-stub-banner")).toBeInTheDocument();
  });

  it("NaN/Infinity/non-number caps degrade to '—' (never 'NaN turns')", () => {
    renderQuietly(
      <ChatPane
        findingId="sf-iter-x"
        mode="two_voice"
        turnCap={NaN}
        tokenCap={Infinity}
      />,
    );
    const intent = screen.getByTestId("two-voice-cap-intent");
    expect(intent).toHaveTextContent(/— turns/);
    expect(intent).toHaveTextContent(/— tok/);
    expect(intent.textContent ?? "").not.toMatch(/NaN|Infinity/);
  });

  it("lets the human direct a turn at defender / attacker / both (not a spectator debate)", () => {
    renderQuietly(<ChatPane findingId="sf-iter-x" mode="two_voice" />);
    const defenderBtn = screen.getByRole("button", { name: "defender" });
    const attackerBtn = screen.getByRole("button", { name: "attacker" });
    const bothBtn = screen.getByRole("button", { name: "both" });
    // Default addressee is "both".
    expect(bothBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(attackerBtn);
    expect(attackerBtn).toHaveAttribute("aria-pressed", "true");
    expect(bothBtn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(defenderBtn);
    expect(defenderBtn).toHaveAttribute("aria-pressed", "true");
    // The send turn is disabled in the capability-off state (no model calls).
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("renders no verdict-shaped control in either availability state (the fence)", () => {
    for (const available of [true, false] as const) {
      const { unmount } = render(
        <ChatPane findingId="sf-iter-x" mode="two_voice" available={available} />,
      );
      for (const re of [
        /verdict/i,
        /disposition/i,
        /sign[\s_-]?off/i,
        /authorize/i,
        /abstain/i,
        /approve/i,
        /reject/i,
      ]) {
        expect(
          screen.queryByRole("button", { name: re }),
          `verdict-shaped control leaked (available=${available}): ${re}`,
        ).toBeNull();
      }
      expect(screen.queryByRole("slider")).toBeNull();
      unmount();
    }
  });
});

describe("ChatPane mode=two_voice — live send threads the addressee", () => {
  it("opens a session then posts a turn with the SELECTED addressee, rendering both stances", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_TWO_VOICE);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(twoVoiceTurn());

    renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" available />,
    );
    fireEvent.click(screen.getByRole("button", { name: "attacker" }));
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "defend the sample size" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));

    await waitFor(() =>
      expect(screen.getByTestId("chat-turn-defender")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("chat-turn-attacker")).toBeInTheDocument();
    expect(screen.getByTestId("chat-turn-defender")).toHaveTextContent(
      "I stand by the finding.",
    );
    expect(screen.getByTestId("chat-turn-attacker")).toHaveTextContent(
      "Your sample is biased.",
    );

    expect(startSpy).toHaveBeenCalledWith({
      mode: "two_voice",
      finding_id: "sf-iter-x",
    });
    expect(turnSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy.mock.calls[0][0]).toMatchObject({
      mode: "two_voice",
      finding_id: "sf-iter-x",
      session_id: "sess-2v-1",
      message: "defend the sample size",
      addressee: "attacker",
    });
  });

  it("the live footer echoes the real finding id (never the '' fallback)", async () => {
    renderQuietly(
      <ChatPane findingId="sf-2026-06-14-001" mode="two_voice" available />,
    );
    expect(
      screen.getByText(/directed at both · sf-2026-06-14-001/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/directed at both · $/)).toBeNull();
  });

  it("an unknown / prototype-colliding stance degrades generically (no function leaks into className)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_TWO_VOICE);
    vi.spyOn(todoApi, "postChatTurn").mockResolvedValue({
      ok: true,
      action: "turn",
      session_id: "sess-2v-1",
      replies: [
        { stance: "arbiter", reply: "a third voice appears", request_id: "r1" },
        { stance: "toString", reply: "prototype collision", request_id: "r2" },
        { stance: { o: 1 } as unknown as string, reply: "object stance", request_id: "r3" },
      ],
    });
    const { container, errorSpy } = renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" available />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "who else is here?" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-turn-unknown").length).toBe(3),
    );
    // The raw string stance shows generically; no inherited function ever
    // reaches the className; the object stance degrades to the generic label.
    expect(screen.getByText("arbiter")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/native code/);
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("a live send issues ONLY the chat verbs — no verdict/disposition POST (the wire fence)", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_TWO_VOICE);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(twoVoiceTurn());
    const writerSpies = (
      [
        "postDirectiveSignoff",
        "postAuthorizeFix",
        "postSpawnTopic",
        "postAbstain",
        "postCalibration",
      ] as const
    ).map((name) => vi.spyOn(todoApi, name).mockResolvedValue({}));

    renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" available />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "attack it" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getByTestId("chat-turn-defender")).toBeInTheDocument(),
    );
    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy).toHaveBeenCalledTimes(1);
    for (const s of writerSpies) expect(s).not.toHaveBeenCalled();
  });

  it("a start error degrades to a legible error (no throw, no blank, no turn posted)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockRejectedValue(
      new todoApi.TodoError(502, "boom", 1, "RuntimeError: qwen skeptic offline"),
    );
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");
    const { errorSpy } = renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" available />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "anything" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getByTestId("two-voice-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("two-voice-error")).toHaveTextContent(
      /qwen skeptic offline/i,
    );
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(turnSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("available=false: send stays disabled and no model call is made", () => {
    const startSpy = vi.spyOn(todoApi, "postChatStart");
    renderQuietly(
      <ChatPane findingId="sf-iter-x" mode="two_voice" available={false} />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "not sent" },
    });
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
    expect(startSpy).not.toHaveBeenCalled();
  });
});

describe("ChatPane — a malformed findingId never leaks [object Object]", () => {
  it("both modes render with an object findingId without leaking", () => {
    for (const mode of ["tutor", "two_voice"] as const) {
      const { container, unmount } = render(
        <ChatPane
          findingId={{ v: 1 } as unknown as string}
          mode={mode}
          available
        />,
      );
      expect(container.innerHTML).not.toMatch(/object Object/);
      unmount();
    }
  });
});
