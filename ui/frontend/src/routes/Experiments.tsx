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

// Verdict chip. YES/ok -> emerald, NO/bad -> red, warn -> amber, none -> zinc.
// We never guess a green/red outcome; a null verdict reads a muted "no verdict".
function VerdictChip({
  verdict,
  testid,
}: {
  verdict: ResearchVerdict | null;
  testid: string;
}) {
  if (!verdict || verdict.tone === null) {
    return (
      <span
        data-testid={testid}
        className="rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[10px] text-zinc-400"
      >
        no verdict
      </span>
    );
  }
  const cls = {
    ok: "border-emerald-700/50 bg-emerald-900/20 text-emerald-300",
    warn: "border-amber-700/50 bg-amber-900/20 text-amber-300",
    bad: "border-red-700/50 bg-red-900/20 text-red-300",
  }[verdict.tone];
  return (
    <span
      data-testid={testid}
      className={`rounded border px-1.5 py-0.5 text-[10px] ${cls}`}
      title={verdict.text ?? undefined}
    >
      {verdict.text ?? verdict.tone}
    </span>
  );
}

// A bridge badge: "-> iter-... . metric=value". Pure pass-through of the
// producer's experiment_outcome — we render the value only when it is a scalar.
function bridgeLabel(b: ResearchBridge): string {
  const it = b.iteration_id ?? "iter (unnamed)";
  const scalar =
    typeof b.value === "number" || typeof b.value === "string"
      ? `${b.metric ?? "metric"}=${b.value}`
      : (b.metric ?? "outcome");
  return `→ ${it} · ${scalar}`;
}

function BridgeRow({ exp }: { exp: ResearchExperiment }) {
  if (exp.bridge.length === 0) {
    return (
      <div
        data-testid={`bridge-${exp.id}`}
        className="mt-2 text-[11px] text-zinc-500"
      >
        not yet bridged into the loop
      </div>
    );
  }
  return (
    <div data-testid={`bridge-${exp.id}`} className="mt-2 flex flex-wrap gap-1.5">
      {exp.bridge.map((b, i) => (
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
    exp.verdict === null &&
    exp.bridge.length === 0 &&
    !exp.has_summary_json &&
    !exp.has_summary_md;
  const notRunCopy =
    tier === "applied" ? "design-only — not run" : "no results yet — not run";
  return (
    <Link
      to={`/experiments/${encodeURIComponent(exp.id)}`}
      data-testid={`research-card-${exp.id}`}
      className={CARD}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm text-zinc-200">{exp.id}</span>
        <span className="text-xs text-zinc-500">{exp.title}</span>
        <span className="ml-auto">
          <VerdictChip verdict={exp.verdict} testid={`verdict-${exp.id}`} />
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
  return (
    <section
      data-testid={`tier-section-${tier.tier}`}
      className="mt-6 first:mt-4"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-100">{tier.label}</h2>
        <span className="font-mono text-[10px] text-zinc-600">{tier.tier}</span>
      </div>
      <p className="mt-1 text-xs text-zinc-500">{tier.description}</p>

      {tier.experiments.length === 0 ? (
        <div className="mt-3 text-xs text-zinc-600">
          No experiments in this tier.
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {tier.experiments.map((exp) => (
            <ResearchCard key={exp.id} exp={exp} tier={tier.tier} />
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

  const nExperiments =
    (data?.tiers.reduce((acc, t) => acc + t.experiments.length, 0) ?? 0) +
    (data?.untiered.length ?? 0);

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
          {data.tiers.map((tier) => (
            <TierSection key={tier.tier} tier={tier} />
          ))}

          {data.untiered.length > 0 && (
            <section data-testid="tier-section-untiered" className="mt-6">
              <div className="flex items-baseline gap-2">
                <h2 className="text-sm font-semibold text-zinc-100">Untiered</h2>
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                On-disk experiment dirs not mapped to a sandbox tier.
              </p>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                {data.untiered.map((exp) => (
                  <ResearchCard key={exp.id} exp={exp} />
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
            {cycles.length}
          </span>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Autonomous cycles as auditable units: the plan, each action's outcome,
          the linked iteration, and the findings/bubbles it produced.
        </p>
        {cycles.length === 0 ? (
          <div
            className="mt-3 text-xs text-zinc-600"
            data-testid="coordinator-cycles-empty"
          >
            No coordinator cycles yet.
          </div>
        ) : (
          <div className="mt-3 space-y-4">
            {cycles.map((cycle) => (
              <CoordinatorCycleCard key={cycle.run_id} cycle={cycle} />
            ))}
          </div>
        )}
      </section>

      <div className="mt-6 text-[11px] text-zinc-600">
        {fmt(nExperiments)} experiment(s) across {fmt(data?.tiers.length ?? 0)}{" "}
        tier(s).
      </div>
    </div>
  );
}
