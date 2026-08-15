// journeyStations — the R2 subway-map STATION MODEL for the dossier reader.
//
// It answers, for ONE producer-owned iteration row, the two questions the
// revamped journey asks of every pipeline step:
//   1. what COLOR is this station (its real outcome), and
//   2. what is the ONE LINE the collapsed section shows?
//
// Eight stations, pinned order: hypothesis · retrieval · relevance · novelty ·
// critic · red-team · experiment · verdict. (This replaces the pre-R2
// PipelineRibbon's eight — `redteam` is new, and the old `experiments`/`gate`/
// `outcome` trio collapses to `experiment` + `verdict`.)
//
// COLOR DISCIPLINE — the station status MIRRORS the chip tone family already
// used for the same field (chips.tsx NOVELTY_TONE / VERDICT_TONE / GATE_TONE /
// ExperimentChip): emerald→ok, amber→warn, red→bad, sky→info, zinc→idle. The
// reader decodes ONE color language, not two. That is why `unclear` novelty and
// `undecidable` critique map to `idle` rather than to a new amber alarm — those
// values are DELIBERATELY quiet in chips.tsx ("could not be judged" is not a
// wolf to cry), and R2 does not get to re-tone them. `reached` is carried
// separately so "never got here" and "got here, no clean verdict" stay
// distinguishable even though both render zinc.
//
// ROBUSTNESS: every field is producer-owned JSONL parsed unchecked. asText
// drops by TYPEOF ALONE (no deref), so a hostile row yields an empty summary
// fragment rather than "[object Object]" / "NaN" — the same guard the rest of
// the journey rides.
import type { Status } from "../../design/StatusDot";
import type { IterationRecord } from "../../types/schemas";

// The shared scalar guard (the TutorPanel.asText / SourceBadge.asText idiom). A
// string trims; a finite number / boolean stringifies; anything else (object,
// array, NaN, Infinity, null, undefined, bigint, Symbol, a throwing-toString)
// yields "" by TYPEOF ALONE — no property read, deep-deref safe.
export function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// Re-coerce a typed-but-unvalidated block to a plain record, or null when it is
// a non-object (string / array / number / null).
export function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export type StationKey =
  | "hypothesis"
  | "retrieval"
  | "relevance"
  | "novelty"
  | "critic"
  | "redteam"
  | "experiment"
  | "verdict";

export interface Station {
  key: StationKey;
  /** The station's name on the map. */
  label: string;
  /** Semantic status token driving the node color (StatusDot's set). */
  status: Status;
  /** The ONE line the collapsed section shows. Never fabricated. */
  summary: string;
  /** Did the pipeline actually get here? (the pre-R2 ribbon's data-reached) */
  reached: boolean;
  /** The experiment slot is not wired until β (D-040) — shown, never faked. */
  phase2: boolean;
}

export const STATION_KEYS: readonly StationKey[] = [
  "hypothesis",
  "retrieval",
  "relevance",
  "novelty",
  "critic",
  "redteam",
  "experiment",
  "verdict",
] as const;

const LABELS: Record<StationKey, string> = {
  hypothesis: "hypothesis",
  retrieval: "retrieval",
  relevance: "relevance",
  novelty: "novelty",
  critic: "critic",
  redteam: "red-team",
  experiment: "experiment",
  verdict: "verdict",
};

// Own-key lookup only — a producer value colliding with an Object.prototype
// member ("toString", "constructor", …) must NOT resolve a prototype function.
// The chips.toneFor guard, applied to the status maps.
function statusFor(
  map: Record<string, Status>,
  key: string,
  fallback: Status,
): Status {
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : fallback;
}

// Mirrors NOVELTY_TONE (emerald / amber / zinc / red).
const NOVELTY_STATUS: Record<string, Status> = {
  novel: "ok",
  rediscovery: "warn",
  unclear: "idle",
  nonsense: "bad",
};

// Mirrors VERDICT_TONE (emerald / amber / red / red / deliberate quiet zinc).
const CRITIC_STATUS: Record<string, Status> = {
  survives: "ok",
  restated: "warn",
  falsified: "bad",
  malformed: "bad",
  undecidable: "idle",
};

// Mirrors GATE_TONE (sky / emerald / red / amber).
const GATE_STATUS: Record<string, Status> = {
  pending: "info",
  valid: "ok",
  invalid: "bad",
  needs_revision: "warn",
};

// Loop v1 Step 2.5 red-team verdicts (schema: "proceed" | "fatal_flaw").
const REDTEAM_STATUS: Record<string, Status> = {
  proceed: "ok",
  fatal_flaw: "bad",
};

// Join the non-empty fragments into the one-line summary; "" when nothing
// usable survived coercion (the caller supplies the honest placeholder).
function line(...parts: Array<string | null | undefined>): string {
  return parts.filter((p): p is string => typeof p === "string" && p.length > 0).join(" · ");
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The eight stations for one iteration row. A null row (journey unavailable)
 *  yields eight un-reached idle stations — the map still draws, nothing is
 *  invented. */
export function stationsFor(row: IterationRecord | null): Station[] {
  const r = asRecord(row);

  const hypothesis = asRecord(r?.hypothesis);
  const retrieval = asRecord(r?.retrieval);
  const relevance = asRecord(retrieval?.relevance);
  const novelty = asRecord(r?.novelty);
  const critique = asRecord(r?.critique);
  const redteam = asRecord(r?.redteam);
  const outcome = asRecord(r?.experiment_outcome);
  const gate = asText(r?.gate_status);

  // ── hypothesis: a stated hypothesis is the step's only success condition.
  const hypText = asText(hypothesis?.text);
  const candidates = finite(hypothesis?.candidates_considered);
  const hypothesisStation: Station = {
    key: "hypothesis",
    label: LABELS.hypothesis,
    status: hypText.length > 0 ? "ok" : "idle",
    summary:
      hypText.length > 0
        ? line("stated", candidates !== null ? `${candidates} candidates` : null)
        : "no hypothesis text on this row",
    reached: hypothesis !== null,
    phase2: false,
  };

  // ── retrieval: neighbors are the substance; zero neighbors is a real flag.
  const neighbors = Array.isArray(retrieval?.neighbors) ? retrieval!.neighbors : [];
  const kText = asText(retrieval?.k);
  const retrievalStation: Station = {
    key: "retrieval",
    label: LABELS.retrieval,
    status:
      retrieval === null ? "idle" : neighbors.length > 0 ? "ok" : "warn",
    summary:
      retrieval === null
        ? "no retrieval block on this row"
        : line(
            `${neighbors.length} neighbor${neighbors.length === 1 ? "" : "s"}`,
            kText.length > 0 ? `k=${kText}` : null,
          ),
    reached: retrieval !== null,
    phase2: false,
  };

  // ── relevance: low_confidence is the producer's own flag — the ONLY thing
  // that turns this station amber. The D-052 topicality advisory is non-gating
  // and NEVER colors the station (never cry wolf).
  const lowConfidence = relevance?.low_confidence === true;
  const relevanceStation: Station = {
    key: "relevance",
    label: LABELS.relevance,
    status: relevance === null ? "idle" : lowConfidence ? "warn" : "ok",
    summary:
      relevance === null
        ? "no relevance block on this row"
        : line(
            asText(relevance.relevance),
            asText(relevance.topicality),
            lowConfidence ? "low-confidence" : null,
            asText(relevance.category),
          ) || "scored",
    reached: relevance !== null,
    phase2: false,
  };

  // ── novelty
  const noveltyClass = asText(novelty?.class);
  const noveltyOverride = asText(novelty?.verdict_overridden_from);
  const noveltyStation: Station = {
    key: "novelty",
    label: LABELS.novelty,
    status:
      novelty === null || noveltyClass.length === 0
        ? "idle"
        : statusFor(NOVELTY_STATUS, noveltyClass, "idle"),
    summary:
      novelty === null
        ? "no novelty block on this row"
        : line(
            noveltyClass.length > 0 ? noveltyClass : "unclassified",
            noveltyOverride.length > 0 ? `overridden from ${noveltyOverride}` : null,
          ),
    reached: novelty !== null,
    phase2: false,
  };

  // ── critic
  const criticVerdict = asText(critique?.verdict);
  const contradicting = asText(critique?.contradicting_paper_id);
  const criticStation: Station = {
    key: "critic",
    label: LABELS.critic,
    status:
      critique === null || criticVerdict.length === 0
        ? "idle"
        : statusFor(CRITIC_STATUS, criticVerdict, "idle"),
    summary:
      critique === null
        ? "no critique block on this row"
        : line(
            criticVerdict.length > 0 ? criticVerdict : "unjudged",
            contradicting.length > 0 ? "contradicted" : "uncontradicted",
          ),
    reached: critique !== null,
    phase2: false,
  };

  // ── red-team (Loop v1 Step 2.5). Absent on pre-v1 rows — say so, fake nothing.
  const redteamVerdict = asText(redteam?.verdict);
  const retries = finite(redteam?.retries_used);
  const redteamStation: Station = {
    key: "redteam",
    label: LABELS.redteam,
    status:
      redteam === null || redteamVerdict.length === 0
        ? "idle"
        : statusFor(REDTEAM_STATUS, redteamVerdict, "idle"),
    summary:
      redteam === null
        ? "no red-team pass on this row"
        : line(
            redteamVerdict.length > 0 ? redteamVerdict : "no verdict",
            retries !== null ? `${retries} retries` : null,
          ),
    reached: redteam !== null,
    phase2: false,
  };

  // ── experiment: ALWAYS Phase-2-flagged (the loop is literature-stage until β
  // / D-040), exactly as the pre-R2 ribbon flagged it. The verdict word comes
  // from the producer's own summary line — never fabricated.
  const expVerdict = experimentVerdictOf(outcome);
  const experimentStation: Station = {
    key: "experiment",
    label: LABELS.experiment,
    status:
      outcome === null ? "idle" : expVerdict === "YES" ? "ok" : expVerdict === "NO" ? "bad" : "idle",
    summary:
      outcome === null
        ? "literature-stage — not experimentally tested (Phase 2)"
        : line(
            asText(outcome.experiment_id),
            asText(outcome.metric),
            asText(outcome.value),
            expVerdict !== null ? `verdict=${expVerdict}` : null,
          ) || "an outcome was bridged in",
    reached: outcome !== null,
    phase2: true,
  };

  // ── verdict (the Step-8 human gate)
  const verdictStation: Station = {
    key: "verdict",
    label: LABELS.verdict,
    status: gate.length === 0 ? "idle" : statusFor(GATE_STATUS, gate, "idle"),
    summary: gate.length === 0 ? "no gate status on this row" : gate,
    reached: gate.length > 0,
    phase2: false,
  };

  return [
    hypothesisStation,
    retrievalStation,
    relevanceStation,
    noveltyStation,
    criticStation,
    redteamStation,
    experimentStation,
    verdictStation,
  ];
}

// The chips.experimentVerdict predicate, applied to an already-coerced record:
// the verdict is read ONLY from the producer's own "Verdict=YES|NO" summary
// line. An outcome without one gets no verdict — never a fabricated one.
function experimentVerdictOf(
  outcome: Record<string, unknown> | null,
): "YES" | "NO" | null {
  if (outcome === null) return null;
  const summary = outcome.summary;
  if (typeof summary !== "string") return null;
  const m = summary.match(/verdict\s*=\s*(YES|NO)\b/i);
  return m ? (m[1].toUpperCase() as "YES" | "NO") : null;
}
