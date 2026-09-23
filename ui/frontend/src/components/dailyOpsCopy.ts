/**
 * Human-digestible copy for the "Today's research path" panel.
 *
 * The lab mailbox + git are the real ledger; what the owner sees on the front
 * end should read as plain sentences, not log lines. This module holds the
 * pure derivations so DailyOpsPanel/DailyDecisionCards stay renderers.
 */

/** A plain title from a raw (often "loggy") plan-item title, when no explicit
 * `summary` was written. Cuts at the first of ':', ' - ' or '(', strips
 * backticks/paths/CLI-looking tokens, and caps at ~90 chars on a word
 * boundary. */
export function deriveSummary(title: string): string {
  const marks: [string, number][] = [":", " - ", "("].map(mark => [mark, title.indexOf(mark)]);
  const first = marks.filter(([, index]) => index >= 0).sort((a, b) => a[1] - b[1])[0];
  let cut = first ? title.slice(0, first[1]) : title;
  cut = cut.replace(/`/g, "");
  cut = cut
    .split(/\s+/)
    .filter(token => token.length > 0 && !token.includes("/") && !/^[-\w.]+\.(py|md|ts|tsx|json|jsonl|sh)$/.test(token))
    .join(" ")
    .trim();
  if (!cut) cut = title.trim();
  if (cut.length > 90) {
    const truncated = cut.slice(0, 90).replace(/\s+\S*$/, "").trim();
    cut = truncated || cut.slice(0, 90).trim();
  }
  return cut;
}

/** The plain-language title a card leads with: the written summary if one
 * exists, else one derived from the raw title. */
export function cardHeadline(summary: string | null, title: string): string {
  return summary && summary.trim().length > 0 ? summary : deriveSummary(title);
}

const WORK_STATUS_SENTENCE: Record<string, string> = {
  merged: "Done, merged into the lab",
  validated: "Built and checked; waiting to be merged",
  building: "Nara is building it",
  awaiting_review: "Waiting for review",
  held: "On hold: the reviewer asked for changes",
  amend_requested: "On hold: the reviewer asked for changes",
  rejected: "Rejected by the reviewer",
  failed: "Failed",
  not_started: "Not started yet",
  waiting_on_you: "Needs your decision",
  withdrawn: "Withdrawn",
  expired: "Expired without a decision",
  accepted: "Accepted",
  answered: "Answered",
};

/** One plain sentence for a work-item status; `mergedAt`, if given, appends
 * "on <date>" the way the spec calls for merged items. */
export function statusSentence(status: string, mergedAt?: string | null): string {
  const base = WORK_STATUS_SENTENCE[status] ?? status.replaceAll("_", " ");
  if (status === "merged" && mergedAt) {
    const date = new Date(mergedAt).toLocaleDateString("en-US", {
      timeZone: "UTC", month: "short", day: "numeric",
    });
    return `${base} on ${date}`;
  }
  return base;
}

/** A plain owner word: Oracle / Nara / You / the raw value title-cased. */
export function ownerWord(value: string): string {
  const lower = value.toLowerCase();
  if (lower === "oracle") return "Oracle";
  if (lower === "nara") return "Nara";
  if (lower.startsWith("human:") || lower === "owner" || lower === "you") return "You";
  return value.length > 0 ? value[0].toUpperCase() + value.slice(1) : value;
}
