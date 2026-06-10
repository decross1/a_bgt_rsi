// roles.ts — the ADDITIVE tone maps for the 2026-06-10 provenance renders
// (backend chips, caller-tag accents, panel "driving" derivation). All inputs
// here are CONSTRUCTED (explicitly synthetic counts/run ids); the tag /
// model / backend strings are the live names (skeptic_attack,
// subagent.finding_skeptic_*, qwen3.6-27b-nvfp4-mtp, vllm-qwen, ...).
import { describe, expect, it } from "vitest";
import {
  backendTone,
  CALLER_TAG_TONE_UNKNOWN,
  callerTagTone,
  drivingTags,
  TONE_QUIET,
} from "../src/roles";
import type { LiveCallGroup, LiveCalls } from "../src/types/activity";

describe("backendTone", () => {
  it("maps the four backend registry names to their tones", () => {
    expect(backendTone("vllm-gemma")).toContain("emerald");
    expect(backendTone("vllm-qwen")).toContain("sky");
    expect(backendTone("ollama-coder")).toContain("amber");
    expect(backendTone("anthropic")).toContain("fuchsia");
  });

  it("unknown / absent / malformed backends fall back to quiet zinc", () => {
    expect(backendTone("vllm-mystery")).toBe(TONE_QUIET);
    expect(backendTone(null)).toBe(TONE_QUIET);
    expect(backendTone(undefined)).toBe(TONE_QUIET);
    expect(backendTone("")).toBe(TONE_QUIET);
    expect(backendTone({ nested: "object" })).toBe(TONE_QUIET);
    expect(backendTone(["vllm-gemma"])).toBe(TONE_QUIET);
    expect(backendTone(Number.NaN)).toBe(TONE_QUIET);
  });

  it("OWN-KEY guard: an Object.prototype member name never leaks a function", () => {
    // Producer-owned strings can collide with inherited prototype members;
    // a bare obj[key] would resolve "toString" to Function.prototype.toString
    // and interpolate a function into className (the SourceBadge hazard).
    for (const hostile of [
      "toString",
      "constructor",
      "hasOwnProperty",
      "valueOf",
      "__proto__",
    ]) {
      const tone = backendTone(hostile);
      expect(typeof tone).toBe("string");
      expect(tone).toBe(TONE_QUIET);
    }
  });
});

describe("callerTagTone", () => {
  it("accents the live tag families per the IA/colors contract", () => {
    // skeptic_* + subagent.finding_skeptic_* -> rose
    expect(callerTagTone("skeptic_attack")).toContain("rose");
    expect(callerTagTone("subagent.finding_skeptic_1")).toContain("rose");
    expect(callerTagTone("subagent.finding_skeptic_3")).toContain("rose");
    // topicality_check + novelty_classify -> indigo
    expect(callerTagTone("topicality_check")).toContain("indigo");
    expect(callerTagTone("novelty_classify")).toContain("indigo");
    // nara.* + hypothesize + meta_review -> emerald
    expect(callerTagTone("nara.run_iteration")).toContain("emerald");
    expect(callerTagTone("hypothesize")).toContain("emerald");
    expect(callerTagTone("meta_review")).toContain("emerald");
    // coordinator.* -> sky
    expect(callerTagTone("coordinator.plan")).toContain("sky");
    // battery -> cyan
    expect(callerTagTone("battery")).toContain("cyan");
    expect(callerTagTone("battery-case-007")).toContain("cyan");
    expect(callerTagTone("lit_battery_20260610T080000Z")).toContain("cyan");
  });

  it("unknown tags read quiet zinc text (rendered raw, never filtered)", () => {
    expect(callerTagTone("finding_session")).toBe(CALLER_TAG_TONE_UNKNOWN);
    expect(callerTagTone("subagent.summarizer")).toBe(CALLER_TAG_TONE_UNKNOWN);
    expect(callerTagTone(null)).toBe(CALLER_TAG_TONE_UNKNOWN);
    expect(callerTagTone(undefined)).toBe(CALLER_TAG_TONE_UNKNOWN);
    expect(callerTagTone({ tag: "object" })).toBe(CALLER_TAG_TONE_UNKNOWN);
  });

  it("OWN-KEY guard on the exact-match map", () => {
    for (const hostile of ["toString", "constructor", "__proto__", "valueOf"]) {
      expect(callerTagTone(hostile)).toBe(CALLER_TAG_TONE_UNKNOWN);
    }
  });
});

describe("drivingTags (panel sub-line derivation)", () => {
  const QWEN = "qwen3.6-27b-nvfp4-mtp";
  const GEMMA = "gemma-4-26b-a4b";

  function lc(groups: LiveCallGroup[] | undefined): LiveCalls {
    return {
      active: true,
      count: 0,
      window_s: 60,
      calls_per_s: null,
      last_call_at: "2026-06-10T08:00:06.4Z",
      caller_tags: [],
      model: null,
      ...(groups === undefined ? {} : { groups }),
    };
  }

  const GROUPS: LiveCallGroup[] = [
    {
      tag: "skeptic_attack",
      model: QWEN,
      backend: "vllm-qwen",
      run_id: null,
      count: 12,
      last_call_at: "2026-06-10T08:00:06.4Z",
    },
    {
      // Same tag, different run context — counts must FOLD per tag.
      tag: "skeptic_attack",
      model: QWEN,
      backend: "vllm-qwen",
      run_id: "exp008_qat_eval_0610",
      count: 3,
      last_call_at: "2026-06-10T08:00:02.0Z",
    },
    {
      tag: "hypothesize",
      model: GEMMA,
      backend: "vllm-gemma",
      run_id: "loop_v0_2026-06-10_001",
      count: 4,
      last_call_at: "2026-06-10T08:00:05.0Z",
    },
    {
      // NEAR-MISS model string (constructed): a superstring of the served
      // name. EXACT match only — must never attribute.
      tag: "meta_review",
      model: "qwen3.6-27b-nvfp4-mtp-quant",
      backend: null,
      run_id: null,
      count: 9,
      last_call_at: "2026-06-10T08:00:04.0Z",
    },
    {
      // Null model — attributes to NO panel (never guessed).
      tag: "topicality_check",
      model: null,
      backend: null,
      run_id: null,
      count: 2,
      last_call_at: "2026-06-10T08:00:03.0Z",
    },
  ];

  it("EXACT model match only — near-miss superstrings and null models never match", () => {
    const qwen = drivingTags(lc(GROUPS), QWEN);
    expect(qwen.map((t) => t.tag)).toEqual(["skeptic_attack"]);
    expect(qwen.map((t) => t.tag)).not.toContain("meta_review");
    expect(qwen.map((t) => t.tag)).not.toContain("topicality_check");
  });

  it("folds counts per tag across matching groups, count-desc", () => {
    const qwen = drivingTags(lc(GROUPS), QWEN);
    expect(qwen).toEqual([{ tag: "skeptic_attack", count: 15 }]);
    const gemma = drivingTags(lc(GROUPS), GEMMA);
    expect(gemma).toEqual([{ tag: "hypothesize", count: 4 }]);
  });

  it("returns [] when groups are absent (older backend) or nothing matches", () => {
    expect(drivingTags(lc(undefined), QWEN)).toEqual([]);
    expect(drivingTags(lc([]), QWEN)).toEqual([]);
    expect(drivingTags(null, QWEN)).toEqual([]);
    expect(drivingTags(undefined, QWEN)).toEqual([]);
    expect(drivingTags(lc(GROUPS), "ollama-something-served")).toEqual([]);
  });

  it("tolerates malformed group rows (non-object, bad count) without throwing", () => {
    const messy = [
      null,
      "not-an-object",
      { tag: "skeptic_attack", model: QWEN, backend: null, run_id: null, count: "12", last_call_at: null },
      { tag: "skeptic_attack", model: QWEN, backend: null, run_id: null, count: Number.NaN, last_call_at: null },
      { tag: "skeptic_attack", model: QWEN, backend: null, run_id: null, count: 2, last_call_at: null },
    ] as unknown as LiveCallGroup[];
    expect(drivingTags(lc(messy), QWEN)).toEqual([
      { tag: "skeptic_attack", count: 2 },
    ]);
  });
});
