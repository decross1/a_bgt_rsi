// ladderBar.ts — the evidence-ladder bar logic, extracted VERBATIM from
// components/HumanTodoPanel.tsx (UI simplification S1) so the /todo inbox and
// the Pulse OweStrip share ONE definition of "clears the bar". Pure module:
// no React, no fetch — just the D-059 bar (only L4/L5 deserves the human's
// attention) plus the shared compact-age formatter.
//
// finding_review items carry `evidence_level` ("L0".."L5", D-059) when their
// surfaced row has one. Legacy rows (all 31 pre-ladder findings) have NO
// level — below-bar by definition. Non-finding kinds (gates, bubbles, stale
// run, state gates) are OPERATIONAL items, not ladder claims — the bar never
// applies to them (hiding a blocking state_gate would fake an unblocked loop).
import type { HumanTodoItem } from "./types/schemas";

export const BAR_LEVELS = new Set(["L4", "L5"]);

// Coerce a producer-owned display scalar to renderable text. An object/array
// rendered as a React child throws and blanks the WHOLE page, so those drop to
// null; a finite number/bool stringifies. (Mirrors SurfacedFindingsPanel.asText.)
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  // object / array / anything else: not safely renderable as text — skip it.
  return null;
}

// Normalized level ("L0".."L9" shape) or null for absent/malformed — the
// field is producer-owned, so anything that is not an L<digit> string reads
// as "no level" (below-bar), never as a crash or a fake pass.
export function evidenceLevelOf(item: HumanTodoItem): string | null {
  const raw = asText(item.evidence_level);
  if (!raw) return null;
  const norm = raw.trim().toUpperCase();
  return /^L\d$/.test(norm) ? norm : null;
}

export function clearsLadderBar(item: HumanTodoItem): boolean {
  const level = evidenceLevelOf(item);
  return level !== null && BAR_LEVELS.has(level);
}

// Compact age ("4d" / "3h" / "12m") from an ISO `since`. Producer-owned: a
// non-string / unparseable timestamp renders "—" — an item of unknown age is
// shown, never faked fresh.
export function ageLabel(iso: unknown, nowMs: number): string {
  const s = asText(iso);
  if (!s) return "—";
  const t = Date.parse(s);
  if (Number.isNaN(t)) return "—";
  const mins = Math.max(0, Math.floor((nowMs - t) / 60_000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
