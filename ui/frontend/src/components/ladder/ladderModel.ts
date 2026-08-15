// ladderModel — the ONE derivation of /api/ladder into everything the R1
// /ladder surfaces render (funnel, board columns, graveyard, kills-per-rung
// bar, table). Pure and payload-guarded: the producer owns every field, so a
// missing/unknown value degrades to an honest bucket, never a faked one.
//
// The two derived quantities worth naming:
//
//   reached[k] — how many clusters got AT LEAST to rung Lk. A cluster sitting
//     at L3 necessarily passed L0-L2, and a cluster KILLED at L2 still reached
//     L2, so reached[k] = (live clusters at rungs >= k, straight off the
//     backend histogram) + (killed clusters whose rung-at-death is >= k). It is
//     monotone non-increasing by construction — that is what makes the funnel
//     a funnel, and it is honest rather than cosmetic narrowing.
//
//   killsByRung[k] — killed clusters whose rung-at-death is exactly Lk: the
//     ribbon that drops out of the funnel between Lk and Lk+1. Note the bar
//     narrows by MORE than the ribbon whenever clusters are simply still
//     resting at Lk (alive, not yet advanced) — the board column carries that
//     remainder, and the funnel caption says so.
//
// A live cluster whose evidence_level is not an L0..L5 string has NO rung: it
// is not on the board and not in the funnel (an unknown rung is not a fake
// L0). It lands in `unrung`, which the page reports out loud.
import { rungIndex } from "../../design/RungGlyph";
import type {
  LadderAgendaItem,
  LadderCluster,
  LadderResponse,
} from "../../types/schemas";

export const LEVELS = ["L0", "L1", "L2", "L3", "L4", "L5"] as const;

export function asText(v: unknown): string | null {
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

export function asCount(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0
    ? Math.floor(v)
    : 0;
}

/** A cluster's display stem, never blank. */
export function stemOf(c: LadderCluster): string {
  return asText(c.stem) ?? asText(c.cluster_id) ?? "(unnamed)";
}

export function isKilled(c: LadderCluster): boolean {
  return asText(c.status) === "killed";
}

/** The kill code a graveyard group is keyed on. */
export function killCodeOf(c: LadderCluster): string {
  const kill =
    c.kill_reason != null &&
    typeof c.kill_reason === "object" &&
    !Array.isArray(c.kill_reason)
      ? c.kill_reason
      : null;
  return asText(kill?.code) ?? "unspecified";
}

export interface GraveyardGroup {
  code: string;
  clusters: LadderCluster[];
}

export interface LadderModel {
  clusters: LadderCluster[];
  histogram: Record<string, number>;
  counts: { open: number; surfaced: number; killed: number };
  agenda: LadderAgendaItem[];
  nextOwed: Record<string, string>;
  /** Live clusters bucketed by rung; index k == Lk. */
  live: LadderCluster[][];
  /** Live clusters the producer gave no usable evidence_level. */
  unrung: LadderCluster[];
  killed: LadderCluster[];
  /** Killed clusters by rung-at-death; index k == Lk. */
  killsByRung: number[];
  /** Killed clusters with no usable rung-at-death (outside killsByRung). */
  killsUnrung: number;
  /** Clusters that reached at least Lk; index k == Lk, monotone down. */
  reached: number[];
  /** Graveyard groups, biggest kill code first. */
  graveyard: GraveyardGroup[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export function buildLadderModel(data: LadderResponse | null): LadderModel {
  const clusters = (Array.isArray(data?.clusters) ? data.clusters : []).filter(
    (c): c is LadderCluster => isRecord(c),
  );
  const histogramRaw = isRecord(data?.histogram) ? data.histogram : {};
  const histogram: Record<string, number> = {};
  for (const l of LEVELS) histogram[l] = asCount(histogramRaw[l]);

  const nextOwedRaw = isRecord(data?.next_owed) ? data.next_owed : {};
  const nextOwed: Record<string, string> = {};
  for (const l of LEVELS) {
    const owed = asText(nextOwedRaw[l]);
    if (owed !== null) nextOwed[l] = owed;
  }

  const live: LadderCluster[][] = LEVELS.map(() => []);
  const unrung: LadderCluster[] = [];
  const killed: LadderCluster[] = [];
  const killsByRung = LEVELS.map(() => 0);
  let killsUnrung = 0;

  for (const c of clusters) {
    const idx = rungIndex(c.evidence_level);
    if (isKilled(c)) {
      killed.push(c);
      if (idx === null) killsUnrung += 1;
      else killsByRung[idx] += 1;
    } else if (idx === null) {
      unrung.push(c);
    } else {
      live[idx].push(c);
    }
  }

  // reached[k]: live-at-or-above (the backend histogram is live-only, so the
  // two sums are disjoint) + killed-at-or-above.
  const reached = LEVELS.map((_, k) => {
    let n = 0;
    for (let j = k; j < LEVELS.length; j += 1) {
      n += histogram[LEVELS[j]] + killsByRung[j];
    }
    return n;
  });

  // Group the graveyard by kill code. A Map, not an object literal: kill codes
  // are producer strings and "toString"/"constructor" would collide with
  // Object.prototype on a plain-object index.
  const groups = new Map<string, LadderCluster[]>();
  for (const c of killed) {
    const code = killCodeOf(c);
    const bucket = groups.get(code);
    if (bucket) bucket.push(c);
    else groups.set(code, [c]);
  }
  const graveyard = [...groups.entries()]
    .map(([code, cs]) => ({ code, clusters: cs }))
    .sort((a, b) => b.clusters.length - a.clusters.length || (a.code < b.code ? -1 : 1));

  return {
    clusters,
    histogram,
    counts: {
      open: asCount(data?.counts?.open),
      surfaced: asCount(data?.counts?.surfaced),
      killed: asCount(data?.counts?.killed),
    },
    agenda: (Array.isArray(data?.agenda) ? data.agenda : []).filter(
      (a): a is LadderAgendaItem => isRecord(a),
    ),
    nextOwed,
    live,
    unrung,
    killed,
    killsByRung,
    killsUnrung,
    reached,
    graveyard,
  };
}

/** The member ids of a cluster, guarded (the payload field is producer-owned). */
export function membersOf(c: LadderCluster): string[] {
  const raw = (c as { members?: unknown }).members;
  if (!Array.isArray(raw)) return [];
  return raw.map((m) => asText(m)).filter((m): m is string => m !== null);
}

/** A member id is dossier-linkable when DossierReader can resolve its kind
 *  from the id prefix (sf-* finding, iter-* iteration). "paper:<arxiv_id>"
 *  members are not dossiers — they render as plain text. */
export function dossierIdOf(member: string): string | null {
  return /^(iter|sf)-/.test(member) ? member : null;
}
