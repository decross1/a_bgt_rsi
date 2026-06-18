// Edge-case + malformed-input hardening for TwoVoiceChatPane (the human-DRIVEN
// two-voice interrogation stub; D-044: Gemma DEFENDS, Qwen ATTACKS).
//
// HOUSE ROBUSTNESS DOCTRINE: the live transcript is producer-owned (the
// finding_session two-stance seam — orchestrator/finding_session.py — which has
// NOT shipped). Today the component renders whatever ChatTurn[] fixture is
// passed in, and the type is a compile-time fiction the moment a real seam (or a
// legacy / partial / mid-rotation producer) hands back a malformed body. A
// single bad value — a non-array `turns`, a bare-null turn, a non-object turn, a
// wrong-typed / unknown / prototype-collision `stance`, an object `text` /
// `addressee`, a NaN/Infinity cap, a non-string findingId — must DEGRADE to a
// legible fallback ("—" / generic tone / dropped field / empty state), NEVER
// blank the pane or throw.
//
// The component's PRE-EXISTING tests live in test_cockpit_interrogation.tsx
// (the two-stance layout, cap intent, stub banner, addressee selector, disabled
// send). This file adds ONLY the malformed/edge coverage and proves valid-input
// behavior is unchanged. It does NOT exercise any model call — the stub stays a
// stub (the send button stays disabled; nothing is sent).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TwoVoiceChatPane from "../src/components/todo/TwoVoiceChatPane";
import * as todoApi from "../src/api/todo";
import type {
  ChatTurn,
  ChatStartResult,
  ChatTurnResult,
} from "../src/types/todo";

// A well-formed control transcript so each malformed case proves the GOOD turns
// still render alongside the bad one (skip/degrade the bad turn, never blank-all).
const GOOD_TURNS: ChatTurn[] = [
  { stance: "defender", addressee: "human", text: "I stand by the finding." },
  { stance: "attacker", addressee: "defender", text: "Your sample is biased." },
];

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Render with spies on console.error/warn (a thrown React render surfaces as a
// console.error, so a crash is caught even if render() doesn't rethrow). Returns
// the container + spies.
function renderQuietly(ui: React.ReactElement) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  let container!: HTMLElement;
  expect(() => {
    container = render(ui).container;
  }).not.toThrow();
  return { container, errorSpy, warnSpy };
}

// The pane root is always present (we never blank the page).
function expectPanePresent() {
  expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
  // The stub is still a stub: send stays disabled, nothing is sent.
  expect(screen.getByTestId("two-voice-send")).toBeDisabled();
}

describe("TwoVoiceChatPane hardening — valid input unchanged (no regression)", () => {
  it("renders both fixture turns, the cap intent, and the stub banner exactly as before", () => {
    const { errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane
        findingId="sf-iter-x"
        turns={GOOD_TURNS}
        turnCap={24}
        tokenCap={1024}
      />,
    );
    expect(screen.getByTestId("stance-defender")).toHaveTextContent(/Gemma DEFENDS/i);
    expect(screen.getByTestId("stance-attacker")).toHaveTextContent(/Qwen ATTACKS/i);
    expect(screen.getByTestId("chat-turn-defender")).toBeInTheDocument();
    expect(screen.getByTestId("chat-turn-attacker")).toBeInTheDocument();
    expect(screen.getByTestId("chat-turn-defender")).toHaveTextContent(
      "I stand by the finding.",
    );
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/24 turns/);
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/1024 tok/);
    expect(screen.getByTestId("two-voice-stub-banner")).toBeInTheDocument();
    expectPanePresent();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("keeps the default-prop empty state and disabled send (no turns, no caps passed)", () => {
    const { errorSpy } = renderQuietly(<TwoVoiceChatPane findingId="sf-iter-y" />);
    expect(screen.getByTestId("two-voice-empty")).toBeInTheDocument();
    // default caps still render (24 / 1024), not "—".
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/24 turns/);
    expect(screen.getByTestId("two-voice-cap-intent")).toHaveTextContent(/1024 tok/);
    expectPanePresent();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("still lets the human direct a turn (addressee selector unchanged; nothing sent)", () => {
    renderQuietly(<TwoVoiceChatPane findingId="sf-iter-x" turns={GOOD_TURNS} />);
    const attackerBtn = screen.getByRole("button", { name: "attacker" });
    const bothBtn = screen.getByRole("button", { name: "both" });
    expect(bothBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(attackerBtn);
    expect(attackerBtn).toHaveAttribute("aria-pressed", "true");
    expect(bothBtn).toHaveAttribute("aria-pressed", "false");
    // The stub stays a stub.
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });
});

describe("TwoVoiceChatPane hardening — non-array / absent `turns` degrade to empty state", () => {
  // `turns` is producer-owned; a non-array body must not crash `.length`/`.map`.
  it.each([
    ["bare null", null],
    ["bare undefined", undefined],
    ["a number", 42],
    ["a string", "not an array"],
    ["a plain object", { 0: "fake", length: 1 }],
    ["a 404-default object", { detail: "Not Found" }],
  ])("renders the empty state for turns = %s (no crash)", (_label, bad) => {
    const { errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane
        findingId="sf-iter-x"
        turns={bad as unknown as ChatTurn[]}
      />,
    );
    expectPanePresent();
    // Degrades to the legible empty state, never a blank gap or a leaked value.
    expect(screen.getByTestId("two-voice-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-turn-defender")).toBeNull();
    expect(screen.getByTestId("two-voice-chat-pane").textContent ?? "").not.toMatch(
      /object Object|NaN|undefined/,
    );
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe("TwoVoiceChatPane hardening — malformed turn ENTRIES never crash the pane", () => {
  it("survives a bare-null / non-object turn entry alongside a good turn", () => {
    const turns = [
      null,
      "a bare string turn",
      42,
      GOOD_TURNS[0],
    ] as unknown as ChatTurn[];
    const { container, errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    // The one good turn still renders.
    expect(screen.getByTestId("chat-turn-defender")).toHaveTextContent(
      "I stand by the finding.",
    );
    // No object/NaN leaks anywhere in the transcript.
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives a turn missing every optional key (only a stance present)", () => {
    const turns = [{ stance: "defender" }] as unknown as ChatTurn[];
    const { errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    const row = screen.getByTestId("chat-turn-defender");
    // Missing addressee degrades to the em-dash placeholder, not "undefined".
    expect(row).toHaveTextContent("—");
    expect(row.textContent ?? "").not.toMatch(/undefined/);
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

describe("TwoVoiceChatPane hardening — malformed `stance` renders generically (no function/object leak)", () => {
  it("survives an unknown stance string (generic tone, no crash, raw value shown)", () => {
    const turns = [
      { stance: "moderator", addressee: "both", text: "novel stance" },
    ] as unknown as ChatTurn[];
    const { container, errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    // Unknown stance buckets to the stable "unknown" testid, never object/undefined.
    expect(screen.getByTestId("chat-turn-unknown")).toBeInTheDocument();
    // The raw stance value still shows (render generically; don't vanish).
    expect(screen.getByTestId("chat-turn-unknown")).toHaveTextContent("moderator");
    expect(container.innerHTML).not.toMatch(/native code/);
    expect(container.querySelector('[class*="function"]')).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives a stance colliding with an Object.prototype member name (no function leaks into className)", () => {
    // `STANCE_TONE["toString"]` is Function.prototype.toString (a function, not
    // undefined), so a bare `?? fallback` would NOT fire and the function would
    // interpolate into the className. Own-key lookup must take the quiet fallback.
    const turns = [
      { stance: "toString", addressee: "human", text: "proto collision" },
      { stance: "valueOf", addressee: "both", text: "another collision" },
      { stance: "constructor", addressee: "attacker", text: "third" },
    ] as unknown as ChatTurn[];
    const { container, errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    const offending = container.innerHTML.match(/class="[^"]*function[^"]*"/g);
    expect(
      offending,
      `leaked function into className: ${JSON.stringify(offending)}`,
    ).toBeNull();
    expect(container.innerHTML).not.toMatch(/native code/);
    // The raw collision values still render generically.
    expect(container.textContent).toMatch(/toString/);
    expect(container.textContent).toMatch(/valueOf/);
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives a stance emitted as an object / array (reaches no React child renderer)", () => {
    const turns = [
      { stance: { weird: true }, addressee: "human", text: "obj stance" },
      { stance: ["defender"], addressee: "both", text: "array stance" },
    ] as unknown as ChatTurn[];
    const { container, errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    // Object/array stance falls to the generic "voice" label + fallback tone.
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(screen.getAllByTestId("chat-turn-unknown").length).toBe(2);
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

describe("TwoVoiceChatPane hardening — non-string `text` / `addressee` never throw a React child error", () => {
  it("survives an object/array text and an object addressee (degrade, no 'Objects are not valid as a React child')", () => {
    const turns = [
      { stance: "defender", addressee: { who: "x" }, text: { body: "nope" } },
      { stance: "attacker", addressee: ["both"], text: ["array", "text"] },
    ] as unknown as ChatTurn[];
    const { container, errorSpy, warnSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    expectPanePresent();
    expect(container.innerHTML).not.toMatch(/object Object/);
    // The good stance still buckets correctly; the bad scalars degrade to "—"/"".
    expect(screen.getByTestId("chat-turn-defender")).toHaveTextContent("—");
    expect(errorSpy, `console.error: ${JSON.stringify(errorSpy.mock.calls)}`).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders a numeric text/addressee as its scalar (finite numbers are legible)", () => {
    const turns = [
      { stance: "defender", addressee: 7, text: 42 },
    ] as unknown as ChatTurn[];
    const { errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turns={turns} />,
    );
    const row = screen.getByTestId("chat-turn-defender");
    expect(row).toHaveTextContent("42");
    expect(row).toHaveTextContent("7");
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

describe("TwoVoiceChatPane hardening — NaN/Infinity/non-number caps degrade to '—'", () => {
  it.each([
    ["NaN", NaN],
    ["Infinity", Infinity],
    ["-Infinity", -Infinity],
    ["a string", "lots"],
    ["an object", { n: 1 }],
    ["null", null],
  ])("renders '—' rather than '%s' for the cap intent", (_label, bad) => {
    const { errorSpy } = renderQuietly(
      <TwoVoiceChatPane
        findingId="sf-iter-x"
        turns={GOOD_TURNS}
        turnCap={bad as unknown as number}
        tokenCap={bad as unknown as number}
      />,
    );
    const cap = screen.getByTestId("two-voice-cap-intent");
    expect(cap.textContent ?? "").not.toMatch(/NaN|Infinity|object Object|null|lots/);
    expect(cap).toHaveTextContent("—");
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("still shows a real finite cap value (guard is not over-broad)", () => {
    renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" turnCap={8} tokenCap={512} />,
    );
    const cap = screen.getByTestId("two-voice-cap-intent");
    expect(cap).toHaveTextContent(/8 turns/);
    expect(cap).toHaveTextContent(/512 tok/);
  });
});

describe("TwoVoiceChatPane hardening — non-string findingId in the available branch", () => {
  it("does not leak '[object Object]' when findingId is malformed and the seam is available", () => {
    const { container, errorSpy } = renderQuietly(
      <TwoVoiceChatPane
        findingId={{ id: "x" } as unknown as string}
        turns={GOOD_TURNS}
        available
      />,
    );
    expectPanePresent();
    // available branch renders "directed at both · <id>" — the id must not be
    // an [object Object].
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(container.textContent).toMatch(/directed at both/);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("renders an oversize / unicode / leading-dash findingId without crashing", () => {
    const weird = "-‮\u{1f4a5}" + "x".repeat(5000);
    const { errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId={weird} turns={GOOD_TURNS} available />,
    );
    // available=true takes the LIVE branch; on mount send is disabled (no draft).
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

// =====================================================================
// LIVE PATH (available===true) — the U3 chat seam. The api client is mocked
// with vi.spyOn(todoApi, ...); the network is NEVER hit and no CLI / model is
// ever exec'd. The stub path above (available!==true) stays byte-identical, so
// its tests are unchanged.
// =====================================================================

const START_OK: ChatStartResult = {
  ok: true,
  mode: "two_voice",
  action: "start",
  finding_id: "sf-iter-x",
  session_id: "sess-2v-1",
  stances: { defender: "vllm-gemma", attacker: "vllm-qwen" },
};

function twoVoiceTurn(
  addressee: string,
  replies: ChatTurnResult["replies"],
): ChatTurnResult {
  return {
    ok: true,
    mode: "two_voice",
    action: "turn",
    finding_id: "sf-iter-x",
    session_id: "sess-2v-1",
    turn_index: 0,
    capped: false,
    addressee,
    warning: null,
    replies,
  };
}

describe("TwoVoiceChatPane LIVE — send threads the addressee + renders stance-tagged replies", () => {
  it("opens a session then posts a turn with the SELECTED addressee, rendering both stances", async () => {
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockResolvedValue(START_OK);
    const turnSpy = vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(
      twoVoiceTurn("attacker", [
        { stance: "attacker", reply: "Your sample is biased.", request_id: "rq-a" },
      ]),
    );

    renderQuietly(<TwoVoiceChatPane findingId="sf-iter-x" available />);

    // Select the attacker as the addressee, then send.
    fireEvent.click(screen.getByRole("button", { name: "attacker" }));
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "defend the sample" },
    });
    const send = screen.getByTestId("two-voice-send");
    expect(send).toBeEnabled();
    fireEvent.click(send);

    await waitFor(() =>
      expect(screen.getByTestId("chat-turn-attacker")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("chat-turn-attacker")).toHaveTextContent(
      "Your sample is biased.",
    );
    // D-044: the attacker voice is labelled Qwen ATTACKS.
    expect(screen.getByTestId("chat-turn-attacker")).toHaveTextContent(/Qwen/);

    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(startSpy).toHaveBeenCalledWith({
      mode: "two_voice",
      finding_id: "sf-iter-x",
    });
    // The selected addressee threaded into the turn.
    expect(turnSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy.mock.calls[0][0]).toMatchObject({
      mode: "two_voice",
      finding_id: "sf-iter-x",
      session_id: "sess-2v-1",
      message: "defend the sample",
      addressee: "attacker",
    });
  });

  it("an addressee=both turn renders BOTH a defender and an attacker reply", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(
      twoVoiceTurn("both", [
        { stance: "defender", reply: "I stand by the finding.", request_id: "d1" },
        { stance: "attacker", reply: "The anchor is off-domain.", request_id: "a1" },
      ]),
    );
    renderQuietly(<TwoVoiceChatPane findingId="sf-iter-x" available />);
    // Default addressee is "both".
    expect(screen.getByRole("button", { name: "both" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getByTestId("chat-turn-defender")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("chat-turn-defender")).toHaveTextContent(
      "I stand by the finding.",
    );
    expect(screen.getByTestId("chat-turn-attacker")).toHaveTextContent(
      "The anchor is off-domain.",
    );
  });
});

describe("TwoVoiceChatPane LIVE — each addressee threads into postChatTurn", () => {
  it.each(["defender", "attacker", "both"] as const)(
    "directing at %s threads that addressee into the turn",
    async (who) => {
      vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
      const turnSpy = vi
        .spyOn(todoApi, "postChatTurn")
        .mockResolvedValue(
          twoVoiceTurn(who, [
            { stance: "defender", reply: "ok", request_id: "x" },
          ]),
        );
      renderQuietly(<TwoVoiceChatPane findingId="sf-iter-x" available />);
      fireEvent.click(screen.getByRole("button", { name: who }));
      fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
        target: { value: `aimed at ${who}` },
      });
      fireEvent.click(screen.getByTestId("two-voice-send"));
      await waitFor(() => expect(turnSpy).toHaveBeenCalledTimes(1));
      expect(turnSpy.mock.calls[0][0]).toMatchObject({
        mode: "two_voice",
        addressee: who,
        message: `aimed at ${who}`,
      });
    },
  );
});

describe("TwoVoiceChatPane LIVE — the verdict fence at the wire (only chat verbs fire)", () => {
  it("a live send issues ONLY postChatStart/postChatTurn — no verdict/disposition POST", async () => {
    const startSpy = vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    const turnSpy = vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(
      twoVoiceTurn("both", [
        { stance: "defender", reply: "stand", request_id: "d" },
      ]),
    );
    const writerSpies = (
      [
        "postDirectiveSignoff",
        "postAuthorizeFix",
        "postSpawnTopic",
        "postAbstain",
        "postCalibration",
      ] as const
    ).map((name) => vi.spyOn(todoApi, name).mockResolvedValue({}));

    renderQuietly(<TwoVoiceChatPane findingId="sf-iter-x" available />);
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() => expect(turnSpy).toHaveBeenCalledTimes(1));
    expect(startSpy).toHaveBeenCalledTimes(1);
    for (const s of writerSpies) expect(s).not.toHaveBeenCalled();
  });

  it("renders no verdict-shaped control in either branch (available true/false)", () => {
    for (const available of [true, false] as const) {
      const { unmount } = render(
        <TwoVoiceChatPane findingId="sf-iter-x" available={available} />,
      );
      for (const re of [
        /verdict/i,
        /disposition/i,
        /confidence/i,
        /sign[\s_-]?off/i,
        /abstain/i,
        /resolve/i,
        /approve/i,
      ]) {
        expect(
          screen.queryByRole("button", { name: re }),
          `verdict control leaked (available=${available}): ${re}`,
        ).toBeNull();
      }
      expect(screen.queryByRole("slider")).toBeNull();
      // The pane text never carries D-044's sibling disposition vocabulary as a
      // control; the only allowed POSTs are the chat verbs.
      unmount();
    }
  });
});

describe("TwoVoiceChatPane LIVE — stale session never leaks across findings", () => {
  it("a turn resolving AFTER findingId changes does not append to the new finding", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    let resolveStale!: (v: ChatTurnResult) => void;
    const stale = new Promise<ChatTurnResult>((r) => {
      resolveStale = r;
    });
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockReturnValueOnce(stale);

    const { rerender } = render(
      <TwoVoiceChatPane findingId="sf-iter-A" available />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "for A" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() => expect(turnSpy).toHaveBeenCalledTimes(1));

    // Switch findings while the turn is still in flight.
    rerender(<TwoVoiceChatPane findingId="sf-iter-B" available />);
    // Now the stale A turn resolves — its reply must NOT enter B's transcript.
    resolveStale(
      twoVoiceTurn("both", [
        { stance: "defender", reply: "STALE-A reply", request_id: "s" },
      ]),
    );
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByText(/STALE-A reply/)).toBeNull();
    expect(screen.getByTestId("two-voice-empty")).toBeInTheDocument();
  });
});

describe("TwoVoiceChatPane LIVE — degrade + hostile envelopes never crash", () => {
  it("a start error degrades to a legible error (no throw, no blank, no turn posted)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockRejectedValue(
      new todoApi.TodoError(502, "boom", 1, "ValueError: session-id is required"),
    );
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");
    const { errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" available />,
    );
    fireEvent.change(screen.getByLabelText(/two-voice turn input/i), {
      target: { value: "anything" },
    });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getByTestId("two-voice-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("two-voice-error")).toHaveTextContent(
      /session-id is required/i,
    );
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(turnSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("a hostile turn envelope (non-array replies / non-string reply / unknown stance) never crashes", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    vi.spyOn(todoApi, "postChatTurn")
      // 1) replies as a bare object (non-array) → nothing appended, no crash.
      .mockResolvedValueOnce({
        ok: true,
        action: "turn",
        session_id: "sess-2v-1",
        replies: { nope: true } as unknown as ChatTurnResult["replies"],
      })
      // 2) a non-string reply + an unknown stance → degrade, no [object Object].
      .mockResolvedValueOnce(
        twoVoiceTurn("both", [
          {
            stance: "moderator",
            reply: { body: "obj" } as unknown as string,
            request_id: null,
          },
          {
            stance: { weird: true } as unknown as string,
            reply: ["array", "reply"] as unknown as string,
            request_id: null,
          },
        ]),
      );

    const { container, errorSpy } = renderQuietly(
      <TwoVoiceChatPane findingId="sf-iter-x" available />,
    );
    const input = screen.getByLabelText(/two-voice turn input/i);

    // Non-array replies → no rows, no crash, the empty state holds.
    fireEvent.change(input, { target: { value: "q1" } });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.getByTestId("two-voice-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-turn-defender")).toBeNull();

    // Hostile members → bucket to the "unknown" testid, degrade text, no leak.
    fireEvent.change(input, { target: { value: "q2" } });
    fireEvent.click(screen.getByTestId("two-voice-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-turn-unknown").length).toBe(2),
    );
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(container.innerHTML).not.toMatch(/native code/);
    const offending = container.innerHTML.match(/class="[^"]*function[^"]*"/g);
    expect(offending).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
