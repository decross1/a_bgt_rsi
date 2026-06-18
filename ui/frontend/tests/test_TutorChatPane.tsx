// TutorChatPane (U2) — the LIVE single-voice tutor chat. This file proves:
//   - the FENCE is visible and cites the REAL source (D-053/D-054, NOT D-044);
//   - available=false keeps the pane an honest disabled stub (no model call);
//   - available=true: typing + send opens a session (postChatStart) then posts a
//     tutor TURN (postChatTurn with mode:"tutor" and NO addressee) and renders
//     the tutor reply (single voice, no stance, no addressee);
//   - a start/turn error DEGRADES legibly (no throw, no blank pane);
//   - a hostile envelope (non-array replies / non-string reply) never crashes;
//   - the VERDICT FENCE: no verdict control exists, the word "verdict" appears
//     ONLY in the fence note, and D-044 never appears on this single-voice
//     teaching surface.
//
// The api client is mocked with vi.spyOn(todoApi, ...) — the network is NEVER
// hit and no CLI / model is ever exec'd.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TutorChatPane from "../src/components/todo/TutorChatPane";
import * as todoApi from "../src/api/todo";
import type { ChatStartResult, ChatTurnResult } from "../src/types/todo";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const START_OK: ChatStartResult = {
  ok: true,
  mode: "tutor",
  action: "start",
  finding_id: "sf-iter-x",
  session_id: "sess-tutor-1",
  stances: null,
};

function turnOk(reply: string): ChatTurnResult {
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

function renderQuietly(ui: React.ReactElement) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  let container!: HTMLElement;
  expect(() => {
    container = render(ui).container;
  }).not.toThrow();
  return { container, errorSpy, warnSpy };
}

describe("TutorChatPane — fence", () => {
  it("renders the pane and a visible fence note citing the REAL source (NOT D-044)", () => {
    renderQuietly(<TutorChatPane findingId="sf-iter-x" />);
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
    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);
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
        <TutorChatPane findingId="sf-iter-x" available={available} />,
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
    // The fence at the wire level: a live send touches exactly the two chat
    // verbs and nothing on the attest/cockpit surface. Spy every disposition
    // writer the cockpit exposes and assert none fire.
    const startSpy = vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(turnOk("a reply"));
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

    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);
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

describe("TutorChatPane — availability", () => {
  it("available=false: send is disabled and no model call is made", () => {
    const startSpy = vi.spyOn(todoApi, "postChatStart");
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");
    renderQuietly(<TutorChatPane findingId="sf-iter-x" available={false} />);
    expect(screen.getByTestId("tutor-chat-stub-banner")).toBeInTheDocument();
    // Even with text typed, the stub send stays disabled.
    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "why was this surfaced?" },
    });
    expect(screen.getByTestId("tutor-chat-send")).toBeDisabled();
    expect(startSpy).not.toHaveBeenCalled();
    expect(turnSpy).not.toHaveBeenCalled();
  });

  it("available=true with no text keeps send disabled (never posts an empty turn)", () => {
    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);
    expect(screen.queryByTestId("tutor-chat-stub-banner")).toBeNull();
    expect(screen.getByTestId("tutor-chat-send")).toBeDisabled();
  });
});

describe("TutorChatPane — live send", () => {
  it("typing + send opens a session then posts a tutor turn (mode:tutor, NO addressee) and renders the reply", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_OK);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(turnOk("It was surfaced because the critic let it pass."));

    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);

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
      .mockResolvedValue(START_OK);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValueOnce(turnOk("first reply"))
      .mockResolvedValueOnce(turnOk("second reply"));

    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);
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

describe("TutorChatPane — degrade", () => {
  it("a start error degrades to a legible error, never throws or blanks", async () => {
    vi.spyOn(todoApi, "postChatStart").mockRejectedValue(
      new todoApi.TodoError(502, "boom", 1, "ValueError: finding-id is required"),
    );
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");

    const { errorSpy } = renderQuietly(
      <TutorChatPane findingId="sf-iter-x" available />,
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
    // The thrown rejection never surfaced as an unhandled console.error.
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("a turn error after a clean start degrades legibly", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    vi.spyOn(todoApi, "postChatTurn").mockRejectedValue(
      new Error("turn cap exceeded"),
    );
    renderQuietly(<TutorChatPane findingId="sf-iter-x" available />);
    fireEvent.change(screen.getByLabelText(/tutor chat input/i), {
      target: { value: "one more" },
    });
    fireEvent.click(screen.getByTestId("tutor-chat-send"));
    await waitFor(() =>
      expect(screen.getByTestId("tutor-chat-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("tutor-chat-error")).toHaveTextContent(
      /turn cap exceeded/i,
    );
    expect(screen.queryByTestId("tutor-chat-reply")).toBeNull();
  });

  it("a hostile envelope (replies non-array / non-string reply) never crashes the pane", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    // replies as a bare object (non-array), then a member with a non-string reply.
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
      <TutorChatPane findingId="sf-iter-x" available />,
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
