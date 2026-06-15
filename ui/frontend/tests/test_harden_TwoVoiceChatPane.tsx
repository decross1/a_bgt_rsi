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

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TwoVoiceChatPane from "../src/components/todo/TwoVoiceChatPane";
import type { ChatTurn } from "../src/types/todo";

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
    expectPanePresent();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
