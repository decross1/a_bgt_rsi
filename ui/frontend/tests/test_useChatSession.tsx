// useChatSession — hook-level regression pins for the LIVE chat seam shared by
// the tutor (U2) and two-voice (U3) panes. The pane tests prove the rendered
// behavior; this file pins the hook's CONTRACT directly:
//   - the VERDICT FENCE at the hook surface: `send` carries only message
//     (+ optional two_voice addressee); the hook never exposes a verdict/
//     disposition/confidence value;
//   - SESSION lifecycle: a single session is opened then reused; a turn/start/
//     error resolving AFTER findingId changes is DROPPED (no stale leak across
//     findings — the docstring's promise made real);
//   - HOSTILE producer envelopes coerce field-by-field and never throw.
//
// The api client is mocked with vi.spyOn(todoApi, ...); the network is NEVER hit
// and no CLI / model is ever exec'd.
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useChatSession } from "../src/components/todo/useChatSession";
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
  finding_id: "f1",
  session_id: "sess-1",
  stances: null,
};

function turnOk(reply: string, sid = "sess-1"): ChatTurnResult {
  return {
    ok: true,
    mode: "tutor",
    action: "turn",
    finding_id: "f1",
    session_id: sid,
    turn_index: 0,
    capped: false,
    warning: null,
    replies: [{ stance: null, reply, request_id: "r" }],
  };
}

describe("useChatSession — session lifecycle", () => {
  it("opens a session on the first send and reuses it on the second", async () => {
    const startSpy = vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValueOnce(turnOk("a"))
      .mockResolvedValueOnce(turnOk("b"));

    const { result } = renderHook(() => useChatSession("tutor", "f1"));
    await act(async () => {
      await result.current.send("q1");
    });
    await act(async () => {
      await result.current.send("q2");
    });

    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(turnSpy).toHaveBeenCalledTimes(2);
    // Both turns threaded the same opened session id.
    expect(turnSpy.mock.calls[0][0].session_id).toBe("sess-1");
    expect(turnSpy.mock.calls[1][0].session_id).toBe("sess-1");
    expect(result.current.turns).toHaveLength(2);
    expect(result.current.started).toBe(true);
  });

  it("resets transcript + session when findingId changes", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(turnOk("a"));
    const { result, rerender } = renderHook(
      ({ fid }: { fid: string }) => useChatSession("tutor", fid),
      { initialProps: { fid: "f1" } },
    );
    await act(async () => {
      await result.current.send("q1");
    });
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.sessionId).toBe("sess-1");

    rerender({ fid: "f2" });
    // A clean slate for the new finding.
    expect(result.current.turns).toHaveLength(0);
    expect(result.current.sessionId).toBeNull();
    expect(result.current.started).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useChatSession — NO stale leak across findings", () => {
  it("a TURN resolving after findingId changes is dropped (not appended to the new finding)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    let resolveStale!: (v: ChatTurnResult) => void;
    const stale = new Promise<ChatTurnResult>((r) => {
      resolveStale = r;
    });
    const turnSpy = vi.spyOn(todoApi, "postChatTurn").mockReturnValueOnce(stale);

    const { result, rerender } = renderHook(
      ({ fid }: { fid: string }) => useChatSession("tutor", fid),
      { initialProps: { fid: "f1" } },
    );
    // start the send but do NOT await — the turn promise is held open.
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.send("q for f1");
    });
    await waitFor(() => expect(turnSpy).toHaveBeenCalledTimes(1));

    // Finding changes while the turn is in flight.
    act(() => {
      rerender({ fid: "f2" });
    });
    // Now the stale f1 turn resolves.
    await act(async () => {
      resolveStale(turnOk("STALE f1 reply"));
      await pending;
    });

    // The new f2 transcript stays empty; the stale reply was dropped.
    expect(result.current.turns).toHaveLength(0);
    expect(result.current.turns.some((t) => t.reply === "STALE f1 reply")).toBe(
      false,
    );
  });

  it("a stale START is dropped — the new finding opens a FRESH session, not the old one", async () => {
    let resolveStart!: (v: ChatStartResult) => void;
    const startP = new Promise<ChatStartResult>((r) => {
      resolveStart = r;
    });
    const startSpy = vi
      .spyOn(todoApi, "postChatStart")
      .mockReturnValueOnce(startP);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(turnOk("new", "sess-f2"));

    const { result, rerender } = renderHook(
      ({ fid }: { fid: string }) => useChatSession("tutor", fid),
      { initialProps: { fid: "f1" } },
    );
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.send("q1");
    });
    await waitFor(() => expect(startSpy).toHaveBeenCalledTimes(1));

    // Switch findings; queue a FRESH start for f2.
    startSpy.mockResolvedValue({
      ...START_OK,
      finding_id: "f2",
      session_id: "sess-f2",
    } as ChatStartResult);
    act(() => {
      rerender({ fid: "f2" });
    });
    // The stale f1 start resolves with the OLD session id.
    await act(async () => {
      resolveStart({ ...START_OK, session_id: "sess-OLD" } as ChatStartResult);
      await pending;
    });
    // The old session id must NOT have leaked into the hook's state.
    expect(result.current.sessionId).not.toBe("sess-OLD");

    // A send on f2 opens a fresh session, never reuses sess-OLD.
    await act(async () => {
      await result.current.send("q2");
    });
    expect(turnSpy.mock.calls[0][0].session_id).not.toBe("sess-OLD");
    expect(turnSpy.mock.calls[0][0].finding_id).toBe("f2");
  });

  it("a stale ERROR is dropped — it never surfaces on the new finding", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    let rejectStale!: (e: unknown) => void;
    const p = new Promise<ChatTurnResult>((_resolve, rej) => {
      rejectStale = rej;
    });
    const turnSpy = vi.spyOn(todoApi, "postChatTurn").mockReturnValueOnce(p);

    const { result, rerender } = renderHook(
      ({ fid }: { fid: string }) => useChatSession("tutor", fid),
      { initialProps: { fid: "f1" } },
    );
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.send("q");
    });
    await waitFor(() => expect(turnSpy).toHaveBeenCalledTimes(1));

    act(() => {
      rerender({ fid: "f2" });
    });
    await act(async () => {
      rejectStale(new Error("STALE ERROR for f1"));
      await pending;
    });
    // The new finding has no error; the stale rejection was swallowed + dropped.
    expect(result.current.error).toBeNull();
  });
});

describe("useChatSession — degrade, never throw, never coerce a fake verdict", () => {
  it("a start with no session_id sets a legible error and posts NO turn", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue({
      ok: true,
      action: "start",
    } as ChatStartResult);
    const turnSpy = vi.spyOn(todoApi, "postChatTurn");
    const { result } = renderHook(() => useChatSession("tutor", "f1"));
    await act(async () => {
      await result.current.send("q");
    });
    expect(result.current.error).toMatch(/no session_id|did not open/i);
    expect(turnSpy).not.toHaveBeenCalled();
  });

  it("a TodoError surfaces its CLI stderr VERBATIM (D-046)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockRejectedValue(
      new todoApi.TodoError(502, "boom", 1, "ValueError: finding-id is required"),
    );
    const { result } = renderHook(() => useChatSession("tutor", "f1"));
    await act(async () => {
      await result.current.send("q");
    });
    expect(result.current.error).toBe("ValueError: finding-id is required");
  });

  it.each([
    ["null body", null],
    ["a bare string", "a string"],
    ["undefined body", undefined],
    ["replies a non-array object", { ok: true, replies: { not: "array" } }],
    ["replies with a bare-null member", { ok: true, replies: [null] }],
    ["replies with a string member", { ok: true, replies: ["bad"] }],
  ])(
    "a hostile turn envelope (%s) appends nothing and never throws",
    async (_label, body) => {
      vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
      vi.spyOn(todoApi, "postChatTurn").mockResolvedValue(
        body as unknown as ChatTurnResult,
      );
      const { result } = renderHook(() => useChatSession("tutor", "f1"));
      await act(async () => {
        await expect(result.current.send("q")).resolves.toBeUndefined();
      });
      expect(result.current.turns).toHaveLength(0);
      expect(result.current.error).toBeNull();
    },
  );

  it("coerces a deeply-nested / non-string reply + stance to legible scalars (no object/NaN)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    vi.spyOn(todoApi, "postChatTurn").mockResolvedValue({
      ok: true,
      action: "turn",
      session_id: "sess-1",
      replies: [
        {
          stance: { deep: { nested: true } } as unknown as string,
          reply: { body: { more: "nope" } } as unknown as string,
          request_id: 7 as unknown as string,
        },
        {
          stance: ["attacker"] as unknown as string,
          reply: NaN as unknown as string,
          request_id: null,
        },
      ],
    } as unknown as ChatTurnResult);
    const { result } = renderHook(() => useChatSession("two_voice", "f1"));
    await act(async () => {
      await result.current.send("q", "both");
    });
    // Both rows append; object/array stance → null, object/NaN reply → "".
    expect(result.current.turns).toHaveLength(2);
    for (const t of result.current.turns) {
      expect(t.stance).toBeNull();
      expect(t.reply).toBe("");
      // A non-string request_id is coerced to null (used only as a React key).
      expect(t.request_id === null || typeof t.request_id === "string").toBe(true);
    }
  });
});

describe("useChatSession — the verdict fence at the hook surface", () => {
  it("exposes no verdict/disposition/confidence value and send carries only message(+addressee)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue({
      ...START_OK,
      mode: "two_voice",
      session_id: "sess-2v",
    } as ChatStartResult);
    const turnSpy = vi.spyOn(todoApi, "postChatTurn").mockResolvedValue({
      ok: true,
      action: "turn",
      session_id: "sess-2v",
      replies: [{ stance: "defender", reply: "x", request_id: "d" }],
    } as ChatTurnResult);

    const { result } = renderHook(() => useChatSession("two_voice", "f1"));
    // The hook's public surface carries NO disposition verb.
    const keys = Object.keys(result.current);
    for (const forbidden of [
      "verdict",
      "disposition",
      "confidence",
      "onResolved",
      "resolve",
      "calibration",
    ]) {
      expect(keys).not.toContain(forbidden);
    }
    await act(async () => {
      await result.current.send("interrogate", "attacker");
    });
    // The turn body carries ONLY chat fields — no verdict/disposition key.
    const body = turnSpy.mock.calls[0][0] as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(
      ["addressee", "finding_id", "message", "mode", "session_id"].sort(),
    );
    expect(body).not.toHaveProperty("verdict");
    expect(body).not.toHaveProperty("disposition");
  });

  it("tutor mode never threads an addressee even if one is passed (single-voice)", async () => {
    vi.spyOn(todoApi, "postChatStart").mockResolvedValue(START_OK);
    const turnSpy = vi
      .spyOn(todoApi, "postChatTurn")
      .mockResolvedValue(turnOk("x"));
    const { result } = renderHook(() => useChatSession("tutor", "f1"));
    await act(async () => {
      // A caller passing an addressee in tutor mode must be ignored.
      await result.current.send("q", "attacker");
    });
    expect(turnSpy.mock.calls[0][0]).not.toHaveProperty("addressee");
  });
});
