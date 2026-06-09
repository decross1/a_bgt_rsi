// SurfacedFindingsPanel — the UI surface for memory/surfaced_findings.jsonl
// (the coordinator's promote_findings output, previously invisible). Polls
// /api/coordinator/findings newest-first and renders each promoted finding's
// title + claim, its novelty/critic verdict badges, the iteration it came out
// of, and when it was promoted. See ui_plan.md §AUTONOMY OBSERVABILITY:
// promoted findings had no view, so the loop's "here's what's worth keeping"
// output ran dark.
//
// Row shape is the EMIT contract (orchestrator/finding_promotion.py): the
// human-readable field is `title` (with `claim`/`why_it_matters` as context),
// `novelty_class`/`critic_verdict` are the badges, `source_iteration_id` links
// the iteration, and `promoted_at` is the time field. There is NO `agent` field
// — promotion is the coordinator's, so the panel carries no provenance chip.
//
// Poll discipline mirrors ResolvedIterationsList: an `initial` prop bypasses
// polling (tests render synchronously from fixtures); otherwise it polls the
// api/http.ts helper, cleans up on unmount, and surfaces an error string rather
// than throwing. Absent (gitignored) data file → backend returns {findings:[]}
// → a clean empty state, never a blank gap.
import { useEffect, useState } from "react";
import { getSurfacedFindings } from "../api/http";
import type { SurfacedFinding } from "../types/schemas";

// Reuse the novelty/verdict palette the resolved-iterations list uses so a
// finding's badges read the same across the dashboard.
const NOVELTY_TONE: Record<string, string> = {
  novel: "bg-emerald-950 text-emerald-400",
  rediscovery: "bg-amber-950 text-amber-400",
  unclear: "bg-zinc-800 text-zinc-400",
  nonsense: "bg-red-950 text-red-400",
};
const VERDICT_TONE: Record<string, string> = {
  survives: "bg-emerald-950 text-emerald-400",
  restated: "bg-amber-950 text-amber-400",
  falsified: "bg-red-950 text-red-400",
  malformed: "bg-red-950 text-red-400",
};
const QUIET_TONE = "bg-zinc-800 text-zinc-400";

// novelty_class / critic_verdict are producer-owned JSONL, so a novel /
// forward-compat enum value can collide with an inherited Object.prototype
// member name ("toString", "constructor", "valueOf", "hasOwnProperty",
// "__proto__", ...). A bare `TONE[value]` then resolves to a FUNCTION via the
// prototype chain instead of undefined, so `?? QUIET_TONE` does NOT fall
// through and that function interpolates into className as
// "function toString() { [native code] }" — the badge loses its quiet fallback
// and lands garbage CSS. Look up own keys only; any unrecognized class/verdict
// (incl. a prototype collision) degrades to the quiet zinc fallback.
// (Mirrors SourceBadge.sourceTone / CoordinatorCycleCard.statusTone.)
function toneFor(palette: Record<string, string>, value: unknown): string {
  return typeof value === "string" &&
    Object.prototype.hasOwnProperty.call(palette, value)
    ? palette[value]
    : QUIET_TONE;
}

// A producer-owned row is unvalidated: a field the panel renders as a React
// child (title/claim/badge text/iteration id) may arrive as a number, boolean,
// or — fatally — an object/array. Rendering an object as a child throws
// "Objects are not valid as a React child", which crashes the WHOLE Dashboard,
// not just this row. Coerce a scalar to a string and DROP an object/array
// (return null) so one malformed field can never blank the page.
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  // object / array / anything else: not safely renderable as text — skip it.
  return null;
}

// First NON-EMPTY rendered text from candidates. `asText` keeps "" (a string
// is a string), but a producer that writes `title:""` (empty string, distinct
// from absent/null) must not blank the row: `?? ` only coalesces on null, so
// `asText("") ?? asText(claim)` keeps the "" and the real claim is suppressed
// — the row's only legible field vanishes. Coalesce on truthiness (the Badge
// `if (!label)` idiom) so an empty/whitespace string falls through to the next
// legible field instead of rendering blank.
function firstText(...candidates: unknown[]): string | null {
  for (const c of candidates) {
    const s = asText(c);
    if (s && s.trim() !== "") return s;
  }
  return null;
}

function Badge({
  text,
  tone,
}: {
  text: string | null | undefined;
  tone: string;
}) {
  // A producer may type novelty_class/critic_verdict as a number or object;
  // asText keeps a scalar (rendered) and drops an object (would throw).
  const label = asText(text);
  if (!label) return null;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

function shortTimestamp(iso: string | null | undefined): string {
  // promoted_at may arrive as an epoch number or other non-string (legacy/
  // malformed producer). `.replace` only exists on strings, so coerce first;
  // a non-string that isn't a usable timestamp falls back to the em-dash.
  const s = asText(iso);
  if (!s) return "—";
  return s.replace("T", " ").replace("Z", "");
}

interface Props {
  initial?: SurfacedFinding[];
  pollMs?: number;
}

export default function SurfacedFindingsPanel({
  initial,
  pollMs = 5000,
}: Props) {
  const [findings, setFindings] = useState<SurfacedFinding[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getSurfacedFindings()
        .then((r) => {
          if (!active) return;
          // Backend returns newest-first per the contract; sort defensively by
          // promoted_at descending so a producer appending out-of-order can't
          // scramble the panel.
          const sorted = [...r.findings].sort((a, b) =>
            // String() guards a non-string promoted_at (e.g. an epoch number):
            // Number.prototype has no localeCompare, so the raw call would
            // throw inside this .then and blank the whole list.
            String(b.promoted_at ?? "").localeCompare(String(a.promoted_at ?? "")),
          );
          setFindings(sorted);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="surfaced-findings-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Surfaced findings
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/coordinator/findings · newest first
        </span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {findings.length}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && findings.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="findings-empty">
          No surfaced findings yet.
        </div>
      )}

      {findings.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {findings.map((finding, i) => (
            // A producer-owned legacy/partial row may omit finding_id; index-
            // suffix the key (the BubblesPanel idiom) so a missing/duplicate id
            // can't trigger React's "two children with the same key" console
            // error, and fall the testid back to the index in that case.
            <li
              key={`${finding.finding_id ?? "finding"}-${i}`}
              data-testid={`finding-${finding.finding_id ?? i}`}
              className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-baseline gap-2 text-[11px]">
                <Badge
                  text={finding.novelty_class}
                  tone={toneFor(NOVELTY_TONE, finding.novelty_class)}
                />
                <Badge
                  text={finding.critic_verdict}
                  tone={toneFor(VERDICT_TONE, finding.critic_verdict)}
                />
                {asText(finding.source_iteration_id) && (
                  <span className="font-mono text-zinc-400">
                    {asText(finding.source_iteration_id)}
                  </span>
                )}
                <span className="ml-auto font-mono text-[10px] text-zinc-500">
                  {shortTimestamp(finding.promoted_at)}
                </span>
              </div>
              {(() => {
                // Primary line: first non-empty of title → claim → id, so an
                // empty-string title (producer wrote "" not absent) falls
                // through to the real claim instead of rendering blank. The
                // secondary claim line shows only when claim is non-empty AND
                // it isn't already the primary (an empty title promotes claim
                // to primary — don't print it twice).
                const claim = firstText(finding.claim);
                const primary = firstText(finding.title, claim, finding.finding_id);
                return (
                  <>
                    {primary && (
                      <div className="mt-1 text-xs text-zinc-200">{primary}</div>
                    )}
                    {claim && claim !== primary && (
                      <div className="mt-0.5 text-[11px] text-zinc-400">
                        {claim}
                      </div>
                    )}
                  </>
                );
              })()}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
