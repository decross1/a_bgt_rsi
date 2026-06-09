// Research index — experiments GROUPED BY SANDBOX TIER. One section per tier
// (synthetic -> semi_synthetic -> applied), each header carrying a human label
// + one-line description. Each experiment is a vettable card: id + title, a
// verdict chip (YES/ok=emerald, NO/bad=red, warn=amber, none=zinc), and BRIDGE
// badges naming the loop iteration(s) it bridged into. Nothing is fabricated:
// an absent verdict reads "no verdict"; an applied design-only entry reads
// "design-only — not run"; an empty bridge reads "not yet bridged into the
// loop". An untiered section appears only when an on-disk dir is unmapped.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CoordinatorCycleCard from "../components/CoordinatorCycleCard";
import { getResearch } from "../api/experiments";
import { getCoordinatorCycles } from "../api/http";
import { fmt } from "../format";
import type {
  ResearchBridge,
  ResearchExperiment,
  ResearchResponse,
  ResearchTier,
  ResearchVerdict,
} from "../types/experiments";
import type { CoordinatorCycle } from "../types/schemas";

interface Props {
  initial?: ResearchResponse | null;
  // Coordinator cycles rendered as auditable units (plan → outcome → evidence).
  // Injected for tests; otherwise fetched alongside the research index. Gated on
  // the research `initial` so a static render stays network-free.
  initialCoordinatorCycles?: CoordinatorCycle[];
}

const CARD =
  "block rounded border border-zinc-800 bg-zinc-900/40 p-4 hover:border-zinc-700";

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

function ResearchCard({
  exp,
  tier,
}: {
  exp: ResearchExperiment;
  tier?: string;
}) {
  // Not-run: nothing was produced — no readable summary, no derived verdict,
  // and no bridge. This covers both an ABSENT results dir and a PRESENT-but-
  // empty one (e.g. applied/exp007's .gitkeep-only dir), without ever guessing
  // a result that isn't there. The applied tier is CFTC-gated design-only, so
  // its copy says so; other no-result dirs just haven't run yet.
  const notRun =
    !exp.verdict &&
    asArray(exp.bridge).length === 0 &&
    !exp.has_summary_json &&
    !exp.has_summary_md;
  const notRunCopy =
    tier === "applied" ? "design-only — not run" : "no results yet — not run";
  // `id`/`title` are producer scalars but a malformed row could carry an object
  // there; rendered as a React child that throws "Objects are not valid as a
  // React child" and unwinds the whole grid. Coerce to a string (empty string
  // when absent — the id still anchors the link/testid without crashing).
  const id = asText(exp.id) ?? "";
  const title = asText(exp.title);
  return (
    <Link
      to={`/experiments/${safeEncodePath(id)}`}
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

      {notRun && (
        <div className="mt-2 text-xs text-amber-400/90">{notRunCopy}</div>
      )}

      <BridgeRow exp={exp} />
    </Link>
  );
}

function TierSection({ tier }: { tier: ResearchTier }) {
  // A legacy/truncated tier row may carry no `experiments` array OR a non-array
  // there; `asArray` coerces both so the section renders its "no experiments"
  // state rather than crashing on `.length`/`.map`. A non-object experiment
  // element is dropped (it carries no card to render). `tier`/`label`/
  // `description` are coerced for rendering as React children: an object there
  // throws "Objects are not valid as a React child". The tier id also anchors
  // the testid/key, so an absent/object id falls back to "untiered".
  const experiments = asArray<unknown>(tier.experiments).filter(
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
              tier={tierId}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default function Experiments({ initial, initialCoordinatorCycles }: Props) {
  const [data, setData] = useState<ResearchResponse | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);
  const [cycles, setCycles] = useState<CoordinatorCycle[]>(
    initialCoordinatorCycles ?? [],
  );

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    getResearch()
      .then((d) => active && setData(d))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [initial]);

  useEffect(() => {
    // Static-render gate: when the research index is injected (test mode), do
    // not self-fetch the coordinator cycles either — use whatever was injected.
    if (initial !== undefined) return;
    let active = true;
    getCoordinatorCycles()
      .then((r) => {
        if (!active) return;
        const sorted = [...r.cycles].sort((a, b) =>
          (b.timestamp ?? "").localeCompare(a.timestamp ?? ""),
        );
        setCycles(sorted);
      })
      .catch(() => {
        /* coordinator cycles are optional context here; never block the index */
      });
    return () => {
      active = false;
    };
  }, [initial]);

  // `tiers` / `untiered` / per-tier `experiments` are producer-owned (the
  // backend computes /api/research, but a legacy/partial/truncated payload —
  // or a future EMIT shape change — may drop an array OR put the WRONG TYPE
  // there: a string/object where an array is expected). `asArray` coerces every
  // reduce/length/map target so a non-array field reads "empty" instead of
  // crashing the page on `.reduce`/`.map`. Non-object tier/exp elements are
  // dropped (a null/number in the array carries no section/card).
  const tiers = asArray<ResearchTier>(data?.tiers).filter(
    (t): t is ResearchTier => typeof t === "object" && t !== null,
  );
  const untiered = asArray<ResearchExperiment>(data?.untiered).filter(
    (e): e is ResearchExperiment => typeof e === "object" && e !== null,
  );
  const nExperiments =
    tiers.reduce((acc, t) => acc + asArray(t?.experiments).length, 0) +
    untiered.length;
  // `cycles` is React state (CoordinatorCycle[]); the live fetch path is
  // .catch-guarded, but an injected `initialCoordinatorCycles` could be a
  // non-array or carry a null/non-object element. Coerce to an array and drop
  // non-object rows so the key access (`cycle.run_id`) and CoordinatorCycleCard
  // never receive a null/scalar that would crash this list.
  const cycleList = asArray<CoordinatorCycle>(cycles).filter(
    (c): c is CoordinatorCycle => typeof c === "object" && c !== null,
  );

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="experiments-page">
      <div className="flex items-baseline gap-3">
        <h1 className="text-base font-semibold text-zinc-100">Research</h1>
        <span className="text-[10px] text-zinc-600">/api/research</span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        Experiments grouped by sandbox tier, each with its outcome verdict and
        the loop iteration(s) it bridged into.
      </p>

      {error && <div className="mt-3 text-sm text-red-400">{error}</div>}

      {data && !data.available && (
        <div
          className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-300"
          data-testid="experiments-unavailable"
        >
          Experiments directory is not available
          {data.reason ? ` (${data.reason})` : ""}.
        </div>
      )}

      {data && data.available && (
        <>
          {tiers.map((tier, i) => (
            <TierSection key={asText(tier.tier) ?? `tier-${i}`} tier={tier} />
          ))}

          {untiered.length > 0 && (
            <section data-testid="tier-section-untiered" className="mt-6">
              <div className="flex items-baseline gap-2">
                <h2 className="text-sm font-semibold text-zinc-100">Untiered</h2>
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                On-disk experiment dirs not mapped to a sandbox tier.
              </p>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                {untiered.map((exp, i) => (
                  <ResearchCard key={asText(exp.id) ?? `exp-${i}`} exp={exp} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {!data && !error && (
        <div className="mt-4 text-sm text-zinc-500">Loading…</div>
      )}

      {/* Coordinator cycles as auditable units. Each card carries the verdict's
          plan → outcome → evidence chain (incl. an errored dispatch as an
          explicit row), so a coordinator-driven result can be trusted or
          doubted alongside the hand-run experiments above. */}
      <section className="mt-8" data-testid="coordinator-cycles-section">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-zinc-100">
            Coordinator cycles
          </h2>
          <span className="font-mono text-[10px] text-zinc-600">
            /api/coordinator/cycles
          </span>
          <span className="ml-auto text-[11px] text-zinc-500">
            {cycleList.length}
          </span>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Autonomous cycles as auditable units: the plan, each action's outcome,
          the linked iteration, and the findings/bubbles it produced.
        </p>
        {cycleList.length === 0 ? (
          <div
            className="mt-3 text-xs text-zinc-600"
            data-testid="coordinator-cycles-empty"
          >
            No coordinator cycles yet.
          </div>
        ) : (
          <div className="mt-3 space-y-4">
            {cycleList.map((cycle, i) => (
              // `run_id` is the producer's join key; fall back to the index so a
              // legacy row missing it doesn't collide into a duplicate-key warn.
              <CoordinatorCycleCard
                key={cycle.run_id ?? `cycle-${i}`}
                cycle={cycle}
              />
            ))}
          </div>
        )}
      </section>

      <div className="mt-6 text-[11px] text-zinc-600">
        {fmt(nExperiments)} experiment(s) across {fmt(tiers.length)} tier(s).
      </div>
    </div>
  );
}
