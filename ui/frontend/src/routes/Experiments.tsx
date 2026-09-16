// Research index — experiments GROUPED BY SANDBOX TIER. One section per tier
// (synthetic -> semi_synthetic -> applied), each header carrying a human label
// + one-line description. Each experiment is a vettable card: id + title, a
// verdict chip (YES/ok=emerald, NO/bad=red, warn=amber, none=zinc), and BRIDGE
// badges naming the loop iteration(s) it bridged into. Nothing is fabricated:
// an absent verdict reads "no verdict"; an absent indexed result stays
// explicitly unknown; an empty bridge reads "not yet bridged into the
// loop". An untiered section appears only when an on-disk dir is unmapped.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ResearchScopeBar from "../components/ResearchScopeBar";
import { getResearch } from "../api/experiments";
import { fmt } from "../format";
import {
  researchScopedHref,
  useResearchScope,
  type ResearchScope,
} from "../researchScope";
import type {
  ResearchBridge,
  ResearchExperiment,
  ResearchResponse,
  ResearchTier,
  ResearchVerdict,
} from "../types/experiments";

interface Props {
  initial?: ResearchResponse | null;
  /** Retained as a no-op compatibility seam for older fixture callers. */
  initialCoordinatorCycles?: unknown[];
}

const CARD =
  "block rounded border border-zinc-800 bg-zinc-900/40 p-4 hover:border-zinc-700";
const ARCHIVE_PAGE_SIZE = 40;

// The /api/research payload is producer-owned (backend walks experiments/*/
// results/ heterogeneously; a legacy/partial/malformed row — or a future EMIT
// shape — can hand us the WRONG TYPE in a field: a tiers/experiments that is a
// string or object instead of an array, an id/label/value that is an object
// where a scalar is expected, a NaN/Infinity number. These two coercions mirror
// CoordinatorCycleCard's asArray/asText so one bad row degrades to "empty"
// instead of throwing "x.map is not a function" / "Objects are not valid as a
// React child" and blanking the whole page.
function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

// A producer-owned scalar rendered as a React child (or used in a key/testid/
// URL) must be a string; an object/array there throws and unwinds the page.
// Returns the string (incl. empty) or null when it is not a renderable scalar,
// so the caller can omit/fallback. Finite numbers are stringified (a numeric id
// stays legible); NaN/Infinity collapse to null rather than print "NaN".
function asText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

// `encodeURIComponent` THROWS `URIError: URI malformed` on a lone UTF-16
// surrogate (e.g. a producer string truncated mid-codepoint, or a model that
// emitted a malformed surrogate in an experiment id). The id is interpolated
// into the card's `<Link to>` URL, and a throw there unwinds the whole grid —
// one corrupt id blanks the entire Research page. Encode defensively: on a
// malformed id, strip the unpaired surrogate(s) so the link still routes to a
// legible (if lossily-encoded) path rather than crashing the page.
function safeEncodePath(id: string): string {
  try {
    return encodeURIComponent(id);
  } catch {
    // Drop lone surrogates (a high surrogate not followed by a low one, or a
    // stray low surrogate) and retry; the remaining valid codepoints encode.
    const stripped = id.replace(
      /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g,
      "",
    );
    try {
      return encodeURIComponent(stripped);
    } catch {
      return "";
    }
  }
}

// Verdict chip. YES/ok -> emerald, NO/bad -> red, warn -> amber, none -> zinc.
// We never guess a green/red outcome; a null verdict reads a muted "no verdict".
function VerdictChip({
  verdict,
  testid,
}: {
  verdict: ResearchVerdict | null;
  testid: string;
}) {
  // `tone` is producer-owned; a malformed/legacy row OR a future EMIT shape
  // could carry a tone outside the {ok,warn,bad} palette (a garbage string, a
  // number, a never-seen enum). Treat any unrecognized tone as "no verdict"
  // (muted zinc) rather than splicing `undefined`/garbage into the className.
  // Look up OWN keys only: a bare `toneCls[tone]` reads off the prototype chain,
  // so a producer tone that collides with an inherited Object.prototype member
  // name ("toString", "constructor", "valueOf", "hasOwnProperty", "__proto__",
  // …) resolves to a FUNCTION/object instead of undefined and gets interpolated
  // into the class as "function toString() { [native code] }" / "[object
  // Object]" (the sibling SourceBadge/AgentBadge are guarded the same way).
  // `text` is coerced so an object there reads a fallback instead of throwing
  // "Objects are not valid as a React child".
  const toneCls: Record<string, string> = {
    ok: "border-emerald-700/50 bg-emerald-900/20 text-emerald-300",
    warn: "border-amber-700/50 bg-amber-900/20 text-amber-300",
    bad: "border-red-700/50 bg-red-900/20 text-red-300",
  };
  const cls =
    verdict &&
    typeof verdict.tone === "string" &&
    Object.prototype.hasOwnProperty.call(toneCls, verdict.tone)
      ? toneCls[verdict.tone]
      : undefined;
  const text = asText(verdict?.text);
  if (!verdict || !cls) {
    return (
      <span
        data-testid={testid}
        className="rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[10px] text-zinc-400"
      >
        {text ?? "no verdict"}
      </span>
    );
  }
  return (
    <span
      data-testid={testid}
      className={`rounded border px-1.5 py-0.5 text-[10px] ${cls}`}
      title={text ?? undefined}
    >
      {text ?? asText(verdict.tone) ?? "verdict"}
    </span>
  );
}

// A bridge badge: "-> iter-... . metric=value". Pure pass-through of the
// producer's experiment_outcome — we render the value only when it is a scalar.
function bridgeLabel(b: ResearchBridge): string {
  // `iteration_id` / `metric` are producer scalars; coerce so an object/array
  // there reads a fallback label instead of "[object Object]" (or a crash if
  // ever rendered as a child). A non-finite number (NaN/Infinity) is NOT a
  // legible metric value — render the metric name alone rather than print "NaN".
  const it = asText(b.iteration_id) ?? "iter (unnamed)";
  const metric = asText(b.metric) ?? "metric";
  const renderableValue =
    typeof b.value === "string" ||
    (typeof b.value === "number" && Number.isFinite(b.value));
  const scalar = renderableValue ? `${metric}=${b.value}` : (asText(b.metric) ?? "outcome");
  return `→ ${it} · ${scalar}`;
}

function BridgeRow({ exp }: { exp: ResearchExperiment }) {
  // `bridge` is producer-owned (built from a loop_memory.jsonl row's
  // experiment_outcome block); a legacy/partial experiment row may omit it OR
  // (malformed) carry a non-array there — `asArray` coerces both to [] so a bad
  // value reads "not yet bridged" instead of throwing ".map is not a function".
  // A non-object bridge element is dropped so it can't crash bridgeLabel.
  const bridge = asArray<unknown>(exp.bridge).filter(
    (b): b is ResearchBridge => typeof b === "object" && b !== null,
  );
  const id = asText(exp.id) ?? "";
  if (bridge.length === 0) {
    return (
      <div
        data-testid={`bridge-${id}`}
        className="mt-2 text-[11px] text-zinc-500"
      >
        not yet bridged into the loop
      </div>
    );
  }
  return (
    <div data-testid={`bridge-${id}`} className="mt-2 flex flex-wrap gap-1.5">
      {bridge.map((b, i) => (
        <span
          key={`${b.iteration_id ?? "it"}-${i}`}
          className="rounded border border-sky-700/50 bg-sky-900/20 px-1.5 py-0.5 font-mono text-[10px] text-sky-300"
        >
          {bridgeLabel(b)}
        </span>
      ))}
    </div>
  );
}

function ResearchCard({ exp }: { exp: ResearchExperiment }) {
  // The index only knows whether indexed result artifacts are present. It must
  // not turn their absence into a claim that the evaluation never ran; the
  // source detail can contain evidence that an older index omitted.
  const resultUnknown =
    !exp.verdict &&
    asArray(exp.bridge).length === 0 &&
    !exp.has_summary_json &&
    !exp.has_summary_md;
  // `id`/`title` are producer scalars but a malformed row could carry an object
  // there; rendered as a React child that throws "Objects are not valid as a
  // React child" and unwinds the whole grid. Coerce to a string (empty string
  // when absent — the id still anchors the link/testid without crashing).
  const id = asText(exp.id) ?? "";
  const title = asText(exp.title);
  return (
    <Link
      to={researchScopedHref(`/experiments/${safeEncodePath(id)}`, "all")}
      aria-label={`${title ?? id} · source history`}
      data-testid={`research-card-${id}`}
      className={CARD}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm text-zinc-200">{id}</span>
        <span className="text-xs text-zinc-500">{title}</span>
        <span className="ml-auto">
          <VerdictChip verdict={exp.verdict} testid={`verdict-${id}`} />
        </span>
      </div>

      {resultUnknown && (
        <div className="mt-2 text-xs text-amber-400/90">No result summary in this index · open the source record to verify status</div>
      )}

      <div className="mt-2 text-[9px] uppercase tracking-wide text-zinc-600">
        Source record · all history
      </div>

      <BridgeRow exp={exp} />
    </Link>
  );
}

function TierSection({
  tier,
  experiments: suppliedExperiments,
}: {
  tier: ResearchTier;
  experiments?: ResearchExperiment[];
}) {
  // A legacy/truncated tier row may carry no `experiments` array OR a non-array
  // there; `asArray` coerces both so the section renders its "no experiments"
  // state rather than crashing on `.length`/`.map`. A non-object experiment
  // element is dropped (it carries no card to render). `tier`/`label`/
  // `description` are coerced for rendering as React children: an object there
  // throws "Objects are not valid as a React child". The tier id also anchors
  // the testid/key, so an absent/object id falls back to "untiered".
  const experiments = suppliedExperiments ?? asArray<unknown>(tier.experiments).filter(
    (e): e is ResearchExperiment => typeof e === "object" && e !== null,
  );
  const tierId = asText(tier.tier) ?? "untiered";
  const label = asText(tier.label);
  const description = asText(tier.description);
  return (
    <section data-testid={`tier-section-${tierId}`} className="mt-6 first:mt-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-100">{label}</h2>
        <span className="font-mono text-[10px] text-zinc-600">{tierId}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">{description}</p>

      {experiments.length === 0 ? (
        <div className="mt-3 text-xs text-zinc-600">
          No experiments in this tier.
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {experiments.map((exp, i) => (
            <ResearchCard
              key={asText(exp.id) ?? `exp-${i}`}
              exp={exp}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default function Experiments({ initial }: Props) {
  const researchScope = useResearchScope();
  const [data, setData] = useState<ResearchResponse | null>(initial ?? null);
  const [dataScope, setDataScope] = useState<ResearchScope | null>(
    initial !== undefined ? researchScope : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(ARCHIVE_PAGE_SIZE);

  useEffect(() => {
    if (initial !== undefined) {
      setDataScope(researchScope);
      return;
    }
    let active = true;
    getResearch(researchScope)
      .then((d) => {
        if (!active) return;
        setData(d);
        setDataScope(researchScope);
        setError(null);
      })
      .catch((e) => {
        if (!active) return;
        setDataScope(researchScope);
        setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [initial, researchScope]);

  // Never render the prior scope while a client-side history transition is
  // resolving. The visible scope switch performs a full reload as the main
  // cache boundary; this guards other navigation mechanisms too.
  const scopedData = dataScope === researchScope ? data : null;
  const scopedError = dataScope === researchScope ? error : null;

  // `tiers` / `untiered` / per-tier `experiments` are producer-owned (the
  // backend computes /api/research, but a legacy/partial/truncated payload —
  // or a future EMIT shape change — may drop an array OR put the WRONG TYPE
  // there: a string/object where an array is expected). `asArray` coerces every
  // reduce/length/map target so a non-array field reads "empty" instead of
  // crashing the page on `.reduce`/`.map`. Non-object tier/exp elements are
  // dropped (a null/number in the array carries no section/card).
  const tiers = asArray<ResearchTier>(scopedData?.tiers).filter(
    (t): t is ResearchTier => typeof t === "object" && t !== null,
  );
  const untiered = asArray<ResearchExperiment>(scopedData?.untiered).filter(
    (e): e is ResearchExperiment => typeof e === "object" && e !== null,
  );
  const nExperiments =
    tiers.reduce((acc, t) => acc + asArray(t?.experiments).length, 0) +
    untiered.length;
  const visibleTiers = tiers.filter(
    (tier) =>
      researchScope === "all" || asArray(tier.experiments).length > 0,
  );
  useEffect(() => {
    setVisibleCount(ARCHIVE_PAGE_SIZE);
  }, [researchScope, scopedData]);

  const boundedArchive = useMemo(() => {
    let remaining = visibleCount;
    const boundedTiers = visibleTiers.flatMap((tier) => {
      const experiments = asArray<unknown>(tier.experiments).filter(
        (entry): entry is ResearchExperiment => typeof entry === "object" && entry !== null,
      );
      const shown = experiments.slice(0, Math.max(0, remaining));
      remaining -= shown.length;
      // Preserve genuinely empty tier headings in the all-history archive, but
      // do not render a false empty state for a tier whose rows are merely on a
      // later page.
      return shown.length > 0 || experiments.length === 0
        ? [{ tier, experiments: shown }]
        : [];
    });
    const boundedUntiered = untiered.slice(0, Math.max(0, remaining));
    return { tiers: boundedTiers, untiered: boundedUntiered };
  }, [untiered, visibleCount, visibleTiers]);
  const shownExperiments = Math.min(nExperiments, visibleCount);
  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="experiments-page">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-zinc-100">Evaluation archive</h1>
        <span className="text-[10px] text-zinc-600">/api/research</span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        {researchScope === "active"
          ? "Only experiment summaries explicitly bound to the current campaign are shown."
          : "Preserved experiments grouped by sandbox tier, with their recorded outcomes and bridges."}
      </p>

      <ResearchScopeBar fetchMetadata={initial === undefined} className="mt-4" />

      {scopedError && <div className="mt-3 text-sm text-red-400">{scopedError}</div>}

      {scopedData && !scopedData.available && (
        <div
          className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-300"
          data-testid="experiments-unavailable"
        >
          Experiments directory is not available
          {scopedData.reason ? ` (${scopedData.reason})` : ""}.
        </div>
      )}

      {scopedData && scopedData.available && (
        <>
          {researchScope === "active" && nExperiments === 0 && (
            <div className="mt-4 rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400" data-testid="experiments-campaign-empty">
              No experiment summary is explicitly linked to the current campaign. This is an empty campaign view, not a missing history archive.
            </div>
          )}
          {boundedArchive.tiers.map(({ tier, experiments }, i) => (
              <TierSection key={asText(tier.tier) ?? `tier-${i}`} tier={tier} experiments={experiments} />
          ))}

          {boundedArchive.untiered.length > 0 && (
            <section data-testid="tier-section-untiered" className="mt-6">
              <div className="flex items-baseline gap-2">
                <h2 className="text-sm font-semibold text-zinc-100">Untiered</h2>
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                On-disk experiment dirs not mapped to a sandbox tier.
              </p>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                {boundedArchive.untiered.map((exp, i) => (
                  <ResearchCard key={asText(exp.id) ?? `exp-${i}`} exp={exp} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {!scopedData && !scopedError && (
        <div className="mt-4 text-sm text-zinc-500">Loading…</div>
      )}

      <div className="mt-6 text-[11px] text-zinc-600">
        <span data-testid="experiments-page-count">Showing {fmt(shownExperiments)} of {fmt(nExperiments)} evaluation record(s) across {fmt(visibleTiers.length)} tier(s).</span>
        {shownExperiments < nExperiments && (
          <button
            type="button"
            data-testid="experiments-show-more"
            className="ml-3 rounded border border-zinc-800 px-2 py-1 text-sky-300 hover:border-zinc-600"
            onClick={() => setVisibleCount((count) => count + ARCHIVE_PAGE_SIZE)}
          >
            Show {fmt(Math.min(ARCHIVE_PAGE_SIZE, nExperiments - shownExperiments))} more
          </button>
        )}
      </div>
    </div>
  );
}
