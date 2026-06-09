// Live dashboard. The page is health-first: a composed HealthVerdict hero
// at the top synthesizes connection / telemetry-staleness / read_errors /
// Gemma reachability, then the health row (HealthStrip + both model-server
// panels). The LOOP_V0 workflow sits below as a high-level glance — a
// compact active-iteration line, a launcher, and a collapsible resolved
// list whose journal opens on selection. Deep data lives on /experiments
// and the /chain inspector, not here. BaselineCard + ProcessGrid are
// low-priority sanity checks behind a "reference" disclosure.
import { useEffect, useState } from "react";
import ActiveIterationPanel from "../components/ActiveIterationPanel";
import BaselineCard from "../components/BaselineCard";
import BubblesPanel from "../components/BubblesPanel";
import HealthStrip from "../components/HealthStrip";
import HealthVerdict, {
  excludeQwenReadErrors,
} from "../components/HealthVerdict";
import JournalScroll from "../components/JournalScroll";
import NaraPromptForm from "../components/NaraPromptForm";
import ProcessGrid from "../components/ProcessGrid";
import QwenPanel from "../components/QwenPanel";
import RedFlagsTrendStrip from "../components/RedFlagsTrendStrip";
import ResolvedIterationsList from "../components/ResolvedIterationsList";
import SurfacedFindingsPanel from "../components/SurfacedFindingsPanel";
import VllmPanel from "../components/VllmPanel";
import { getHealth, getIterations } from "../api/http";
import { useTelemetryStream } from "../hooks/useTelemetryStream";
import { useNow } from "../time";
import type { Health, IterationRecord } from "../types/schemas";

export default function Dashboard() {
  const { samples, latest, connected } = useTelemetryStream();
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedIteration, setSelectedIteration] = useState<string | null>(
    null,
  );
  // Iterations are lifted here only to feed the standing red-flags strip (the
  // novel-rate / suspected-false-novel / off-domain self-checks). The resolved
  // list below still owns its own poll/pagination.
  const [iterations, setIterations] = useState<IterationRecord[]>([]);
  const now = useNow();

  useEffect(() => {
    const loadHealth = () => getHealth().then(setHealth).catch(() => {});
    loadHealth();
    const id = setInterval(loadHealth, 10000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const loadIterations = () =>
      getIterations()
        .then((r) => setIterations(r.iterations))
        .catch(() => {});
    loadIterations();
    const id = setInterval(loadIterations, 10000);
    return () => clearInterval(id);
  }, []);

  const lastSeen = latest?.timestamp ?? health?.telemetry_last_seen ?? null;
  // Guard against a malformed/absent timestamp: Date.parse -> NaN, which
  // would otherwise slip past the `ageMs > threshold` staleness check
  // (NaN comparisons are always false) and paint a false-healthy hero.
  // Coerce non-finite ages to null so the verdict treats freshness as
  // unknown rather than fresh.
  const parsedAge = lastSeen ? now - Date.parse(lastSeen) : null;
  const ageMs =
    parsedAge != null && Number.isFinite(parsedAge) ? parsedAge : null;
  // Qwen is excluded from the verdict (staged/unwired today): a failing-but-
  // enabled Qwen reader emits a "vllm-qwen-metrics" read error, which must
  // not drag the whole system to degraded. Drop Qwen-owned keys here.
  const readErrors = excludeQwenReadErrors(
    latest?.read_errors ? Object.keys(latest.read_errors) : [],
  );
  // Gemma is up when the latest sample carries a `vllm` block. Debounced:
  // a single transient scrape miss (server fine, one failed /metrics poll)
  // should not flip the hero to DOWN. We require the vllm block to be
  // absent across the most recent GEMMA_DOWN_WINDOW samples before calling
  // it down. With fewer samples than the window, fall back to the latest.
  const GEMMA_DOWN_WINDOW = 2;
  const recent = samples.slice(-GEMMA_DOWN_WINDOW);
  const gemmaUp =
    recent.length === 0
      ? false
      : recent.length < GEMMA_DOWN_WINDOW
        ? recent[recent.length - 1]?.vllm != null
        : recent.some((s) => s.vllm != null);

  return (
    <div className="mx-auto max-w-7xl p-5">
      {/* Thin identity header. The health signals it used to carry inline
          are now composed into the HealthVerdict hero below. */}
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span className="font-mono text-zinc-200">
          {health?.hostname ?? "spark"}
        </span>
        <span className="text-zinc-500">backend {health?.version ?? "?"}</span>
      </div>

      {/* HERO: composed health verdict. */}
      <div className="mt-3">
        <HealthVerdict
          connected={connected}
          hasTelemetry={samples.length > 0}
          ageMs={ageMs}
          readErrors={readErrors}
          gemmaUp={gemmaUp}
        />
      </div>

      {/* Health row: host/GPU strip + both model-server panels side-by-side.
          Gemma (primary orchestrator) first, Qwen (staged sub-agent) second.
          Stacked on narrow screens. */}
      <div className="mt-4">
        <HealthStrip samples={samples} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <VllmPanel samples={samples} />
        <QwenPanel samples={samples} />
      </div>

      {/* LOOP_V0 high-level glance: compact active line + launcher. */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
        <ActiveIterationPanel compact />
        <NaraPromptForm />
      </div>

      {/* AUTONOMY block — the coordinator loop's standing self-checks +
          its two "raise to the human" channels. Kept below the health-first
          hero/panels: the red-flags strip answers "is the loop surfacing
          things genuinely new?" at a glance; Surfaced Findings + Bubbles are
          the loop's promoted output and its escalations. */}
      <section className="mt-6 space-y-4" data-testid="autonomy-block">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Autonomy
        </h2>
        <RedFlagsTrendStrip iterations={iterations} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SurfacedFindingsPanel />
          <BubblesPanel />
        </div>
      </section>

      {/* Recent iterations — secondary, collapsible. Kept fully functional
          (pagination + filters + Loop-v1 chips); the journal for a selected
          row opens inline only on selection. */}
      <details className="mt-4 group" data-testid="recent-iterations-disclosure" open>
        <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">▸ recent iterations</span>
          <span className="hidden group-open:inline">▾ recent iterations</span>
        </summary>
        <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ResolvedIterationsList
            onSelect={setSelectedIteration}
            selectedId={selectedIteration}
          />
          {selectedIteration && (
            <JournalScroll iterationId={selectedIteration} />
          )}
        </div>
      </details>

      {/* Reference: Spark perf baseline + tracked processes (low-priority
          sanity checks). Collapsed by default to keep the page health-first. */}
      <details className="mt-6 group" data-testid="reference-disclosure">
        <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-300">
          <span className="group-open:hidden">▸ reference — baseline & processes</span>
          <span className="hidden group-open:inline">▾ reference — baseline & processes</span>
        </summary>
        <div className="mt-2">
          <BaselineCard />
        </div>
        <div className="mt-4">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            Tracked processes
          </h2>
          <ProcessGrid samples={samples} />
        </div>
      </details>
    </div>
  );
}
