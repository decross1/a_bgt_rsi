// pollhub (src/api/pollhub.ts) — the ONE page-level polling scheduler
// (perf work 2026-08-18). Pins the behaviors the Pulse + /model-io fixes
// ride on: per-source cadences off one heartbeat, the in-flight guard (a
// slow endpoint can never stack concurrent requests — the /api/lab_todo
// failure mode) NOW BOUNDED BY A DEADLINE (adversarial review 2026-08-18:
// a hung request fails its source honestly and retries instead of wedging
// it forever), change detection (an unchanged payload notifies nobody, so
// a no-change poll tick re-renders nothing), stale-while-revalidate (a
// failure keeps the last good payload and flips `failing` exactly once),
// zero-sub eviction for parameterized keys, and the age-only tick that
// keeps rendered data ages honest across silent unchanged polls.
import { useRef } from "react";
import { cleanup, render, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getPollSnapshot,
  pollHubEntryCount,
  resetPollHub,
  subscribePoll,
  subscribePollAge,
  usePolled,
} from "../src/api/pollhub";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  resetPollHub();
  vi.useRealTimers();
});

const tickAsync = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("pollhub scheduler", () => {
  it("paces each source at its own interval off the one heartbeat", async () => {
    const fast = vi.fn().mockResolvedValue({ v: 1 });
    const slow = vi.fn().mockResolvedValue({ v: 2 });
    const un1 = subscribePoll("fast", fast, { intervalMs: 5000 }, () => {});
    const un2 = subscribePoll("slow", slow, { intervalMs: 60000 }, () => {});

    await tickAsync(0); // initial fires + settle
    expect(fast).toHaveBeenCalledTimes(1);
    expect(slow).toHaveBeenCalledTimes(1);

    await tickAsync(61_000);
    // fast: initial + ~every 5s (heartbeat-paced); slow: initial + one repoll.
    expect(fast.mock.calls.length).toBeGreaterThanOrEqual(11);
    expect(fast.mock.calls.length).toBeLessThanOrEqual(14);
    expect(slow).toHaveBeenCalledTimes(2);
    un1();
    un2();
  });

  it("FETCH DEADLINE: a hung fetch fails the source at the deadline, keeps the snapshot honestly, and RETRIES", async () => {
    // The /api/lab_todo failure mode, round two (adversarial review
    // 2026-08-18): the in-flight guard stops request stacking, but a fetch
    // that never settles used to wedge the source FOREVER while the page
    // read its frozen snapshot as fresh. Now the hub races every fire
    // against a deadline (default 20s): before it, exactly one request is
    // in flight (the guard, unchanged); at it, the source fails HONESTLY —
    // data + asOf kept from the last real success, failing=true so the
    // stale note renders — and the next due tick fires a fresh attempt.
    let hang = false;
    const fetcher = vi.fn().mockImplementation(() =>
      hang ? new Promise(() => {}) : Promise.resolve({ n: 1 }),
    );
    const unsub = subscribePoll("hang", fetcher, { intervalMs: 5000 }, () => {});
    await tickAsync(0); // first fetch succeeds — there is a snapshot to keep
    expect(getPollSnapshot("hang").data).toEqual({ n: 1 });
    const asOfBefore = getPollSnapshot("hang").asOf;

    hang = true;
    await tickAsync(6_000); // the ~5s repoll fires and hangs
    expect(fetcher).toHaveBeenCalledTimes(2);
    // BEFORE the deadline: still exactly one in flight, not yet failing.
    await tickAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(getPollSnapshot("hang").failing).toBe(false);
    // PAST the deadline (20s after the hang started at ~5s): failing,
    // snapshot + asOf frozen at the last success — stale legible as stale.
    await tickAsync(10_000);
    const snap = getPollSnapshot<{ n: number }>("hang");
    expect(snap.failing).toBe(true);
    expect(snap.data).toEqual({ n: 1 });
    expect(snap.asOf).toBe(asOfBefore);
    expect(String(snap.error)).toContain("deadline");
    // …and the source is NOT wedged: later ticks retry.
    await tickAsync(30_000);
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(3);
    // Recovery: once the endpoint answers again, failing clears.
    hang = false;
    await tickAsync(30_000);
    expect(getPollSnapshot("hang").failing).toBe(false);
    expect(getPollSnapshot("hang").asOf).toBeGreaterThan(asOfBefore!);
    unsub();
  });

  it("FETCH DEADLINE: a settlement arriving after its deadline is ignored", async () => {
    // A past-deadline response is out of order by definition — a retry may
    // already own the source; adopting the late payload would lie about
    // asOf. First settle normally, then hang past the deadline and settle
    // late with DIFFERENT data: the late data must not land.
    let resolveLate: ((v: unknown) => void) | null = null;
    let mode: "ok" | "late" = "ok";
    const fetcher = vi.fn().mockImplementation(() =>
      mode === "ok"
        ? Promise.resolve({ v: 1 })
        : new Promise((res) => {
            resolveLate = res;
            mode = "ok"; // subsequent retries succeed normally
          }),
    );
    const cb = vi.fn();
    const unsub = subscribePoll("late", fetcher, { intervalMs: 60_000 }, cb);
    await tickAsync(0);
    expect(getPollSnapshot("late").data).toEqual({ v: 1 });

    mode = "late";
    await tickAsync(61_000); // repoll fires and hangs
    await tickAsync(21_000); // deadline passed — source failed honestly
    expect(getPollSnapshot("late").failing).toBe(true);
    const notifiesAtFail = cb.mock.calls.length;

    // The hung request finally answers — with data that must be DROPPED.
    resolveLate!({ v: 999 });
    await tickAsync(0);
    expect(getPollSnapshot<{ v: number }>("late").data).toEqual({ v: 1 });
    expect(cb.mock.calls.length).toBe(notifiesAtFail);
    unsub();
  });

  it("CHANGE DETECTION: an unchanged payload notifies nobody", async () => {
    // Fresh object identity each time, same JSON — the no-change poll tick.
    const fetcher = vi.fn().mockImplementation(() =>
      Promise.resolve({ items: [{ id: "a" }] }),
    );
    const cb = vi.fn();
    const unsub = subscribePoll("cd", fetcher, { intervalMs: 5000 }, cb);
    await tickAsync(0);
    expect(cb).toHaveBeenCalledTimes(1); // the first payload
    await tickAsync(20_000);
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(4);
    expect(cb).toHaveBeenCalledTimes(1); // …and not once more

    // A REAL change notifies again.
    fetcher.mockImplementation(() =>
      Promise.resolve({ items: [{ id: "b" }] }),
    );
    await tickAsync(6_000);
    expect(cb).toHaveBeenCalledTimes(2);
    expect(getPollSnapshot<{ items: { id: string }[] }>("cd").data)
      .toEqual({ items: [{ id: "b" }] });
    unsub();
  });

  it("SWR: failure keeps the last good payload, flips failing ONCE, and recovery clears it", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const cb = vi.fn();
    const unsub = subscribePoll("swr", fetcher, { intervalMs: 5000 }, cb);
    await tickAsync(0);
    expect(getPollSnapshot("swr").data).toEqual({ n: 1 });

    fetcher.mockRejectedValue(new Error("backend drowned"));
    await tickAsync(6_000);
    let snap = getPollSnapshot<{ n: number }>("swr");
    expect(snap.data).toEqual({ n: 1 }); // data SURVIVES the failure
    expect(snap.failing).toBe(true);
    expect(String(snap.error)).toContain("backend drowned");
    const failNotifies = cb.mock.calls.length;

    // Repeat failures do NOT re-notify (no render churn while down).
    await tickAsync(15_000);
    expect(cb.mock.calls.length).toBe(failNotifies);

    // Recovery with the SAME payload still notifies (failing -> false).
    fetcher.mockResolvedValue({ n: 1 });
    await tickAsync(6_000);
    snap = getPollSnapshot<{ n: number }>("swr");
    expect(snap.failing).toBe(false);
    expect(snap.data).toEqual({ n: 1 });
    expect(cb.mock.calls.length).toBe(failNotifies + 1);
    unsub();
  });

  it("staggers a delayed first fetch precisely, not heartbeat-granularly", async () => {
    const fetcher = vi.fn().mockResolvedValue({});
    const unsub = subscribePoll(
      "stag",
      fetcher,
      { intervalMs: 60000, initialDelayMs: 300 },
      () => {},
    );
    await tickAsync(0);
    expect(fetcher).not.toHaveBeenCalled();
    await tickAsync(350);
    expect(fetcher).toHaveBeenCalledTimes(1);
    unsub();
  });

  it("EVICTION: evictOnZero keys are deleted at zero subs — N filter keys never leak N entries", async () => {
    // The /model-io table source keys on the applied filter string. An
    // always-on dashboard cycling filters would mint an Entry per query
    // forever; evictOnZero deletes on last-unsubscribe instead.
    for (let i = 0; i < 25; i++) {
      const unsub = subscribePoll(
        `table:filter-${i}`,
        vi.fn().mockResolvedValue({ i }),
        { intervalMs: 5000, evictOnZero: true },
        () => {},
      );
      await tickAsync(0);
      unsub();
    }
    expect(pollHubEntryCount()).toBe(0);

    // Default (unparameterized) sources KEEP their warm-remount entry.
    const unsub = subscribePoll(
      "warm",
      vi.fn().mockResolvedValue({}),
      { intervalMs: 5000 },
      () => {},
    );
    await tickAsync(0);
    unsub();
    expect(pollHubEntryCount()).toBe(1);
  });

  it("AGE TICK: an unchanged poll advances asOf and notifies age-only subscribers, not data subscribers", async () => {
    // Minor (a) of the 2026-08-18 review: the unchanged-payload path used
    // to mutate snapshot.asOf with NO notify of any kind — an "as of Ns"
    // display could never learn the data had been re-verified fresh.
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve({ v: 1 }));
    const cb = vi.fn();
    const ageCb = vi.fn();
    const unsub = subscribePoll("aged", fetcher, { intervalMs: 5000 }, cb);
    const unsubAge = subscribePollAge("aged", ageCb);
    await tickAsync(0);
    expect(cb).toHaveBeenCalledTimes(1); // the first payload
    const ageAfterFirst = ageCb.mock.calls.length;
    const asOf1 = getPollSnapshot("aged").asOf;

    await tickAsync(6_000); // one UNCHANGED repoll
    expect(cb).toHaveBeenCalledTimes(1); // data subscribers: silent
    expect(ageCb.mock.calls.length).toBeGreaterThan(ageAfterFirst);
    expect(getPollSnapshot("aged").asOf).toBeGreaterThan(asOf1!);
    unsubAge();
    unsub();
  });

  it("two subscribers on one key share a single fetch loop", async () => {
    const fetcher = vi.fn().mockResolvedValue({ shared: true });
    const un1 = subscribePoll("dup", fetcher, { intervalMs: 5000 }, () => {});
    const un2 = subscribePoll("dup", fetcher, { intervalMs: 5000 }, () => {});
    await tickAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1); // not one per subscriber
    await tickAsync(6_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    un1();
    un2();
  });
});

describe("usePolled (React binding)", () => {
  function Probe({
    fetcher,
    enabled = true,
    renders,
  }: {
    fetcher: () => Promise<{ label: string }>;
    enabled?: boolean;
    renders: { count: number };
  }) {
    renders.count += 1;
    const fetcherRef = useRef(fetcher);
    fetcherRef.current = fetcher;
    const snap = usePolled<{ label: string }>(
      "probe",
      () => fetcherRef.current(),
      { intervalMs: 5000, enabled },
    );
    return (
      <div data-testid="probe">
        {snap.data?.label ?? "no-data"}
        {snap.failing ? " (failing)" : ""}
      </div>
    );
  }

  it("does NOT re-render the consumer on a no-change poll tick", async () => {
    const renders = { count: 0 };
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve({ label: "steady" }));
    const { getByTestId } = render(<Probe fetcher={fetcher} renders={renders} />);
    await tickAsync(0);
    expect(getByTestId("probe").textContent).toBe("steady");
    const after = renders.count;

    await tickAsync(20_000); // ~4 unchanged polls
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(4);
    expect(renders.count).toBe(after); // ZERO re-renders

    fetcher.mockImplementation(() => Promise.resolve({ label: "moved" }));
    await tickAsync(6_000);
    expect(getByTestId("probe").textContent).toBe("moved");
    expect(renders.count).toBe(after + 1); // exactly the change
  });

  it("enabled:false (fixture mode) never fetches", async () => {
    const fetcher = vi.fn().mockResolvedValue({ label: "x" });
    render(<Probe fetcher={fetcher} enabled={false} renders={{ count: 0 }} />);
    await tickAsync(10_000);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
