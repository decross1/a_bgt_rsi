// test_chips — the shared chip primitives (src/components/chips.tsx, UI
// simplification S2; moved VERBATIM out of the retired IterationDetailModal).
// Carries the PORTED pins the modal suite + the forward-compat suite held on
// these helpers:
//   - toneFor: own-key lookup only — a prototype-colliding producer value
//     ("toString"/"constructor"/…) must take the quiet fallback, never resolve
//     an inherited FUNCTION into a className;
//   - the DELIBERATE "undecidable" quiet tone (the /40 translucency marks it
//     as intentional, distinct from the unknown-enum fallback);
//   - badgeText: scalar coercion (string / finite number pass; object, array,
//     NaN, null, undefined yield "" — never "[object Object]");
//   - experimentVerdict: reads ONLY a literal Verdict=YES|NO from the
//     producer's own summary line — never fabricates a verdict;
//   - conditioningBullets: a non-array (or junk entries) degrade to [] /
//     string-only bullets;
//   - Badge / ExperimentChip / RedteamChip / OverrideProvenance render + tone
//     behavior.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  Badge,
  ExperimentChip,
  GATE_TONE,
  NOVELTY_TONE,
  OverrideProvenance,
  RedteamChip,
  VERDICT_TONE,
  badgeText,
  conditioningBullets,
  experimentVerdict,
  overrideTooltip,
  processLabel,
  processTone,
  redteamAlarm,
  seedTopic,
  shortTimestamp,
  toneFor,
} from "../src/components/chips";
import type { IterationRecord } from "../src/types/schemas";

afterEach(() => {
  cleanup();
});

const FALLBACK = "bg-zinc-800 text-zinc-400";

describe("toneFor — own-key lookup with the prototype-collision guard", () => {
  it("resolves known enum values from each map", () => {
    expect(toneFor(NOVELTY_TONE, "novel", FALLBACK)).toBe(
      "bg-emerald-950 text-emerald-400",
    );
    expect(toneFor(VERDICT_TONE, "falsified", FALLBACK)).toBe(
      "bg-red-950 text-red-400",
    );
    expect(toneFor(GATE_TONE, "pending", FALLBACK)).toBe(
      "bg-sky-950 text-sky-300",
    );
  });

  it("a prototype-member collision takes the FALLBACK, never an inherited function", () => {
    for (const hostile of [
      "toString",
      "constructor",
      "valueOf",
      "hasOwnProperty",
      "__proto__",
    ]) {
      const tone = toneFor(NOVELTY_TONE, hostile, FALLBACK);
      expect(tone).toBe(FALLBACK);
      // The classic failure: the resolved value is a FUNCTION that stringifies
      // into the className. It must never escape.
      expect(typeof tone).toBe("string");
      expect(tone).not.toMatch(/native code/);
    }
  });

  it("unknown / non-string keys take the fallback", () => {
    expect(toneFor(VERDICT_TONE, "never_seen_verdict", FALLBACK)).toBe(FALLBACK);
    expect(toneFor(VERDICT_TONE, null, FALLBACK)).toBe(FALLBACK);
    expect(toneFor(VERDICT_TONE, undefined, FALLBACK)).toBe(FALLBACK);
  });

  it("'undecidable' keeps its DELIBERATE quiet /40 tone — the zinc family, distinct from the bare fallback", () => {
    const tone = toneFor(VERDICT_TONE, "undecidable", FALLBACK);
    // The quiet lane (no emerald/red/amber alarm)…
    expect(tone).toContain("zinc-800");
    expect(tone).toContain("text-zinc-400");
    // …with the /40 translucency that marks the entry as intentional.
    expect(tone).toContain("/40");
    expect(tone).not.toBe(FALLBACK);
  });
});

describe("badgeText — scalar coercion (the [object Object] guard)", () => {
  it("passes strings through and stringifies finite numbers", () => {
    expect(badgeText("survives")).toBe("survives");
    expect(badgeText(42 as unknown as string)).toBe("42");
  });

  it("objects, arrays, NaN, null, undefined all yield '' (no badge, no crash)", () => {
    expect(badgeText({ v: 1 } as unknown as string)).toBe("");
    expect(badgeText(["a"] as unknown as string)).toBe("");
    expect(badgeText(NaN as unknown as string)).toBe("");
    expect(badgeText(null)).toBe("");
    expect(badgeText(undefined)).toBe("");
  });

  it("Badge renders nothing for a garbled text value", () => {
    const { container } = render(
      <Badge text={{ nested: true } as unknown as string} tone={FALLBACK} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(container.innerHTML).not.toMatch(/object Object/);
  });
});

describe("experimentVerdict — only a literal Verdict=YES|NO in the summary counts", () => {
  it("reads YES / NO from the producer's own summary line", () => {
    expect(
      experimentVerdict({
        experiment_id: "exp003_vickrey_rediscovery",
        metric: "truthful_bid_fraction",
        value: 1.0,
        summary:
          "Verdict=YES. Fraction of trials with mean |bid - valuation| <= 5: 100.00%.",
      }),
    ).toBe("YES");
    expect(
      experimentVerdict({
        experiment_id: "e",
        metric: "m",
        value: 1,
        summary: "VCG verdict=NO. Fraction under threshold.",
      }),
    ).toBe("NO");
  });

  it("no verdict line / no summary / non-object outcomes yield null (never fabricated)", () => {
    expect(
      experimentVerdict({ experiment_id: "e", metric: "m", value: 1 }),
    ).toBe(null);
    expect(experimentVerdict(null)).toBe(null);
    expect(
      experimentVerdict(
        "nope" as unknown as IterationRecord["experiment_outcome"],
      ),
    ).toBe(null);
    expect(
      experimentVerdict([] as unknown as IterationRecord["experiment_outcome"]),
    ).toBe(null);
  });

  it("ExperimentChip: NO → red, no verdict line → quiet 'experiment'", () => {
    const { rerender } = render(
      <ExperimentChip
        outcome={{
          experiment_id: "exp009",
          metric: "x",
          value: 0.1,
          summary: "Verdict=NO. Deviation persists.",
        }}
      />,
    );
    let chip = screen.getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("exp verdict=NO");
    expect(chip.className).toContain("red");

    rerender(
      <ExperimentChip
        outcome={{ experiment_id: "exp001", metric: "m", value: 1 }}
      />,
    );
    chip = screen.getByTestId("experiment-chip");
    expect(chip).toHaveTextContent("experiment");
    expect(chip.className).toContain("zinc");
  });

  it("ExperimentChip: an OBJECT value never reaches the title as [object Object]", () => {
    render(
      <ExperimentChip
        outcome={{
          experiment_id: "exp-multi",
          metric: "m",
          value: { sub_a: 0.5 } as unknown as number,
          summary: "Verdict=YES. multi.",
        }}
      />,
    );
    const chip = screen.getByTestId("experiment-chip");
    expect(chip.getAttribute("title") ?? "").not.toMatch(/object Object/);
  });
});

describe("conditioningBullets — non-array / junk degrade, never crash", () => {
  const rowWith = (bullets: unknown): IterationRecord =>
    ({
      iteration_id: "iter-x",
      started_at: "t",
      ended_at: "t",
      journal_entry_path: "j",
      meta_review: { conditioning_bullets: bullets },
    }) as unknown as IterationRecord;

  it("returns the string bullets of a well-formed list", () => {
    expect(conditioningBullets(rowWith(["alpha", "beta"]))).toEqual([
      "alpha",
      "beta",
    ]);
  });

  it("a bare string (non-array) yields []", () => {
    expect(conditioningBullets(rowWith("one string"))).toEqual([]);
  });

  it("junk entries (null, numbers, objects) are filtered; only strings survive", () => {
    expect(
      conditioningBullets(rowWith(["keep", null, 7, { o: 1 }, "also"])),
    ).toEqual(["keep", "also"]);
  });

  it("an absent meta_review yields []", () => {
    expect(
      conditioningBullets({
        iteration_id: "iter-y",
        started_at: "t",
        ended_at: "t",
        journal_entry_path: "j",
      } as IterationRecord),
    ).toEqual([]);
  });
});

describe("redteamAlarm / RedteamChip", () => {
  it("fatal or retries>0 alarms; clean/NaN/negative does not", () => {
    expect(redteamAlarm({ verdict: "fatal_flaw" })).toBe(true);
    expect(redteamAlarm({ verdict: "proceed", retries_used: 2 })).toBe(true);
    expect(redteamAlarm({ verdict: "proceed", retries_used: 0 })).toBe(false);
    expect(redteamAlarm({ verdict: "proceed", retries_used: NaN })).toBe(false);
    expect(redteamAlarm({ verdict: "proceed", retries_used: -3 })).toBe(false);
    expect(redteamAlarm(null)).toBe(false);
    expect(redteamAlarm(undefined)).toBe(false);
  });

  it("the clean proceed/0 chip renders quiet zinc; a fatal one renders red", () => {
    const { rerender } = render(
      <RedteamChip redteam={{ verdict: "proceed", retries_used: 0 }} />,
    );
    let chip = screen.getByTestId("redteam-chip");
    expect(chip).toHaveTextContent(/proceed/);
    expect(chip.className).toContain("zinc");

    rerender(<RedteamChip redteam={{ verdict: "fatal_flaw" }} />);
    chip = screen.getByTestId("redteam-chip");
    expect(chip.className).toContain("red");
  });
});

describe("overrideTooltip / OverrideProvenance", () => {
  it("composes 'overridden from' + 'skeptic said'; garbled fields drop", () => {
    expect(
      overrideTooltip({
        verdict_overridden_from: "survives",
        skeptic_verdict: "refuted",
      }),
    ).toBe("overridden from survives; skeptic said refuted");
    expect(
      overrideTooltip({
        verdict_overridden_from: { v: 1 },
        skeptic_verdict: ["x"],
      }),
    ).toBeUndefined();
    expect(overrideTooltip(null)).toBeUndefined();
    // PORTED from test_undecidable_verdict (S3): an override with ONLY
    // verdict_overridden_from (the novelty-side low-confidence downgrade)
    // carries just that part — no dangling "; skeptic said".
    expect(overrideTooltip({ verdict_overridden_from: "novel" })).toBe(
      "overridden from novel",
    );
  });

  it("OverrideProvenance renders the three fields as VISIBLE text; nothing on an empty block", () => {
    const { rerender } = render(
      <OverrideProvenance
        label="critique"
        testid="op-test"
        block={{
          verdict_overridden_from: "survives",
          override_reason: "skeptic attack_verdict='refuted'",
          skeptic_verdict: "refuted",
        }}
      />,
    );
    const box = screen.getByTestId("op-test");
    expect(box).toHaveTextContent("overridden from survives");
    expect(box).toHaveTextContent("reason: skeptic attack_verdict='refuted'");
    expect(box).toHaveTextContent("skeptic said refuted");

    rerender(<OverrideProvenance label="novelty" testid="op-test" block={{}} />);
    expect(screen.queryByTestId("op-test")).toBeNull();
  });
});

describe("scalar guards — processTone/processLabel, seedTopic, shortTimestamp", () => {
  it("processTone/processLabel survive non-string statuses and map the known ones", () => {
    expect(processTone("running")).toContain("sky");
    expect(processTone("exited_clean")).toContain("emerald");
    expect(processTone("exited_error_2")).toContain("red");
    expect(processTone(7 as unknown as string)).toBe(FALLBACK);
    expect(processLabel("exited_clean")).toBe("pid clean");
    expect(processLabel("killed_signal_9")).toBe("pid killed 9");
    expect(processLabel({} as unknown as string)).toBe(null);
  });

  it("seedTopic coerces a non-string topic to ''", () => {
    expect(
      seedTopic({ seed: { topic: 42 } } as unknown as IterationRecord),
    ).toBe("");
    expect(
      seedTopic({ seed: { topic: "real topic" } } as unknown as IterationRecord),
    ).toBe("real topic");
  });

  it("shortTimestamp survives non-string ended_at", () => {
    expect(shortTimestamp("2026-06-10T10:05:00Z")).toBe("2026-06-10 10:05:00");
    expect(shortTimestamp({ seconds: 1 })).toBe("—");
    expect(shortTimestamp(null)).toBe("—");
  });
});
