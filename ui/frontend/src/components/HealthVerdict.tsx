// Composed top-of-page health verdict. Synthesizes the four signals the
// dashboard header used to scatter across thin inline spans — connection
// state, telemetry staleness (>5s), telemetry read_errors, and the Gemma
// model-server reachability — into one "healthy / degraded / down" hero.
//
// Verdict precedence (worst wins):
//   down      — no live connection, OR no telemetry yet, OR the Gemma
//               model server is unreachable. The apparatus can't be
//               observed / driven; this is the loudest state. NOTE: the
//               caller debounces the `gemmaUp` signal (Dashboard.tsx) so a
//               single transient /metrics scrape miss does NOT flip the
//               hero to DOWN — DOWN here means "no vllm block across the
//               most recent N samples," not "one scrape had no vllm block."
//   degraded  — connected and serving, but a soft fault: telemetry is
//               stale (>5s old) or the sampler reported read_errors on a
//               named subsystem. Data is flowing but not fully trustworthy.
//   healthy   — connected, fresh telemetry, no read_errors, Gemma up.
//
// Qwen is deliberately NOT part of the verdict: it is staged/unwired today
// (renders a no-data state by design), so an unreachable Qwen must not drag
// the whole system to degraded. Its at-a-glance health lives in QwenPanel.
//
// computeVerdict is pure so it can be unit-tested directly; the component is
// a thin presentational shell over it.

export type VerdictLevel = "healthy" | "degraded" | "down";

export interface VerdictInput {
  connected: boolean;
  // Whether any telemetry sample has arrived yet ("waiting for telemetry").
  hasTelemetry: boolean;
  // Telemetry age in ms (latest sample / health.telemetry_last_seen vs now).
  // Null when unknown (no sample seen).
  ageMs: number | null;
  staleThresholdMs?: number;
  // Sampler-reported read failures, keyed by subsystem. The canonical key
  // set is defined in ui/sampler/sampler.py: "nvidia-smi", "psutil",
  // "thermal", "vllm-metrics", "vllm-qwen-metrics". The caller is
  // responsible for dropping Qwen-only keys (see QWEN_READ_ERROR_KEYS and
  // Dashboard.tsx) before passing them here, since Qwen is excluded from
  // the verdict by design. Empty when clean.
  readErrors: string[];
  // Whether the Gemma model server's /metrics are currently reachable
  // (latest sample carries a `vllm` block).
  gemmaUp: boolean;
}

export interface Verdict {
  level: VerdictLevel;
  // One-line headline reason for the current level.
  headline: string;
  // Named contributing faults, worst-first, for the detail line.
  reasons: string[];
}

const DEFAULT_STALE_MS = 5000;

// Sampler read_errors keys that belong to Qwen, which is deliberately
// excluded from the verdict (staged/unwired today). A failing-but-enabled
// Qwen reader emits "vllm-qwen-metrics"; that key must NOT drag the verdict
// to degraded. Callers filter readErrors through this set before passing
// them in. Keep in sync with ui/sampler/sampler.py.
export const QWEN_READ_ERROR_KEYS: ReadonlySet<string> = new Set([
  "vllm-qwen-metrics",
]);

// Drop Qwen-owned keys from a read_errors key list. Pure; exported for the
// dashboard and for tests.
export function excludeQwenReadErrors(keys: string[]): string[] {
  return keys.filter((k) => !QWEN_READ_ERROR_KEYS.has(k));
}

export function computeVerdict(input: VerdictInput): Verdict {
  const staleMs = input.staleThresholdMs ?? DEFAULT_STALE_MS;
  const stale = input.ageMs != null && input.ageMs > staleMs;

  const downReasons: string[] = [];
  if (!input.connected) downReasons.push("telemetry stream disconnected");
  if (!input.hasTelemetry) downReasons.push("no telemetry received");
  if (!input.gemmaUp) downReasons.push("Gemma model server unreachable");

  if (downReasons.length > 0) {
    return {
      level: "down",
      headline: downReasons[0],
      reasons: downReasons,
    };
  }

  const degradedReasons: string[] = [];
  if (stale) {
    const secs = input.ageMs != null ? Math.round(input.ageMs / 1000) : null;
    degradedReasons.push(
      secs != null ? `telemetry stale (${secs}s old)` : "telemetry stale",
    );
  }
  if (input.readErrors.length > 0) {
    degradedReasons.push(`read errors: ${input.readErrors.join(", ")}`);
  }

  if (degradedReasons.length > 0) {
    return {
      level: "degraded",
      headline: degradedReasons[0],
      reasons: degradedReasons,
    };
  }

  return {
    level: "healthy",
    headline: "all systems nominal",
    reasons: [],
  };
}

const LEVEL_LABEL: Record<VerdictLevel, string> = {
  healthy: "HEALTHY",
  degraded: "DEGRADED",
  down: "DOWN",
};

// Tailwind tone per level — matches the zinc/emerald/amber/red idiom.
const LEVEL_TONE: Record<VerdictLevel, { dot: string; text: string; border: string }> = {
  healthy: {
    dot: "bg-emerald-400",
    text: "text-emerald-300",
    border: "border-emerald-800/60",
  },
  degraded: {
    dot: "bg-amber-400",
    text: "text-amber-300",
    border: "border-amber-800/60",
  },
  down: {
    dot: "bg-red-500",
    text: "text-red-300",
    border: "border-red-800/60",
  },
};

export default function HealthVerdict(props: VerdictInput) {
  const verdict = computeVerdict(props);
  const tone = LEVEL_TONE[verdict.level];

  return (
    <div
      data-testid="health-verdict"
      data-level={verdict.level}
      className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded border ${tone.border} bg-zinc-900/40 px-4 py-3`}
    >
      <span className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-hidden />
        <span className={`text-lg font-semibold tracking-wide ${tone.text}`}>
          {LEVEL_LABEL[verdict.level]}
        </span>
      </span>
      <span className="text-sm text-zinc-400">{verdict.headline}</span>
      {verdict.reasons.length > 1 && (
        <span className="text-xs text-zinc-500" data-testid="health-verdict-reasons">
          {verdict.reasons.slice(1).join(" · ")}
        </span>
      )}
    </div>
  );
}
