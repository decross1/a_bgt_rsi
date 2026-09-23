import { describe, expect, it } from "vitest";
import { cardHeadline, deriveSummary, ownerWord, statusSentence } from "../src/components/dailyOpsCopy";

describe("deriveSummary", () => {
  it("derives a plain title from the real (loggy) plan-item titles", () => {
    expect(deriveSummary(
      "nara_lane precheck: run admission(), then the acceptance test in the real sandbox twice - with no tool (must be red) ...",
    )).toBe("nara_lane precheck");

    expect(deriveSummary(
      "Re-post the held lab state packet (C3): tools/lab_state_packet.py --root DIR --json covering ...",
    )).toBe("Re-post the held lab state packet");

    expect(deriveSummary(
      "Focus-selection CLI: `python -m orchestrator.research_focus select ...` wrapping select_focus() ...",
    )).toBe("Focus-selection CLI");

    expect(deriveSummary(
      "Write the payoff-line closeout document: notes/research/2026-09-23-payoff-closeout/THESIS_DISPOSITION.md, ...",
    )).toBe("Write the payoff-line closeout document");

    expect(deriveSummary(
      "Timer discussion the owner deferred on 2026-09-22, narrowed: install the daily-loop timers ...",
    )).toBe("Timer discussion the owner deferred on 2026-09-22, narrowed");
  });

  it("leaves a plain title with no punctuation marker alone", () => {
    expect(deriveSummary("Lane precheck")).toBe("Lane precheck");
  });

  it("strips backticks and path/CLI-shaped tokens", () => {
    expect(deriveSummary("Run `pytest` over orchestrator/nara_lane.py fully")).not.toContain("`");
    expect(deriveSummary("Run `pytest` over orchestrator/nara_lane.py fully")).not.toContain("/");
  });

  it("caps at about 90 characters on a word boundary", () => {
    const long = "A".repeat(40) + " " + "b".repeat(40) + " " + "c".repeat(40);
    const derived = deriveSummary(long);
    expect(derived.length).toBeLessThanOrEqual(90);
    expect(derived.endsWith(" ")).toBe(false);
  });
});

describe("cardHeadline", () => {
  it("prefers a written summary over a derived one", () => {
    expect(cardHeadline("Lane precheck gate", "nara_lane precheck: run admission() ...")).toBe("Lane precheck gate");
  });

  it("falls back to a derived title when no summary was written", () => {
    expect(cardHeadline(null, "Focus-selection CLI: `python -m orchestrator.research_focus select ...`"))
      .toBe("Focus-selection CLI");
  });
});

describe("statusSentence", () => {
  it("maps every work status to a plain sentence", () => {
    expect(statusSentence("validated")).toBe("Built and checked; waiting to be merged");
    expect(statusSentence("building")).toBe("Nara is building it");
    expect(statusSentence("awaiting_review")).toBe("Waiting for review");
    expect(statusSentence("held")).toBe("On hold: the reviewer asked for changes");
    expect(statusSentence("rejected")).toBe("Rejected by the reviewer");
    expect(statusSentence("failed")).toBe("Failed");
    expect(statusSentence("not_started")).toBe("Not started yet");
    expect(statusSentence("waiting_on_you")).toBe("Needs your decision");
    expect(statusSentence("withdrawn")).toBe("Withdrawn");
  });

  it("appends the merge date for a merged item", () => {
    expect(statusSentence("merged", "2026-09-20T09:00:00Z")).toBe("Done, merged into the lab on Sep 20");
  });
});

describe("ownerWord", () => {
  it("renders plain owner words", () => {
    expect(ownerWord("oracle")).toBe("Oracle");
    expect(ownerWord("nara")).toBe("Nara");
    expect(ownerWord("human:derrick")).toBe("You");
    expect(ownerWord("owner")).toBe("You");
  });
});
