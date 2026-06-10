// NowBoard — PAGE A's multi-run board, fed by GET /api/activity/active_runs
// (the D-047 registry: run_state/active_runs/<run_id>.json, one file per LIVE
// run). It takes over the hero's run slot from the single-run ActiveRunCard:
// one card per registered run — kind chip, label, current_step, progress —
// with a STALE-HEARTBEAT amber state when `now - heartbeat_at > 120s` (a
// `legacy_mirror` run has no heartbeat semantics, so its freshest timestamp
// stands in — the ActiveRunCard staleness fallback idiom). The empty state is
// honest ("no registered runs") and never invents a run; a version-skew 404
// (older backend binary without the endpoint) renders the quiet
// EndpointMissingNote, never red. Per-field coercion follows ActiveRunCard:
// every field is producer-owned, so a malformed scalar drops its cell rather
// than crashing the board.
import { useEffect, useState } from "react";
import { getActiveRuns } from "../api/http";
import { elapsed, useNow } from "../time";
import type { ActiveRun, ActiveRunsResponse } from "../types/activity";
import EndpointMissingNote, { isVersionSkew404 } from "./EndpointMissingNote";

const ACTIVE_RUNS_ENDPOINT = "/api/activity/active_runs";
const POLL_MS = 5000;
// A registry run whose heartbeat is older than this is rendered stale-amber:
// the writer refreshes heartbeat_at on every update, so two minutes of
// silence means a hung/killed driver, not a slow step.
const STALE_HEARTBEAT_MS = 120_000;

// Coerce a producer-owned display scalar to renderable text (the
// ActiveRunCard idiom): an object/array rendered as a React child throws and
// blanks the page, so those drop to ""; a finite number/bool stringifies.
function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// Epoch ms of a producer-owned timestamp, or null when absent/unparseable.
function parseMs(value: unknown): number | null {
  if (typeof value !== "string" || !value) return null;
  const t = Date.parse(value);
  return Number.isNaN(t) ? null : t;
}

// The instant a run's staleness is judged against. A registry run is judged
// on heartbeat_at ONLY (refreshed every update; absent/unparseable -> no
// staleness claim — unknown is not stale). A legacy_mirror run predates
// heartbeat semantics, so its FRESHEST timestamp stands in.
export function staleRefMs(run: ActiveRun): number | null {
  const heartbeat = parseMs(run.heartbeat_at);
  if (run.legacy_mirror === true) {
    const candidates = [
      heartbeat,
      parseMs(run.step_started_at),
      parseMs(run.started_at),
    ].filter((t): t is number => t != null);
    return candidates.length ? Math.max(...candidates) : null;
  }
  return heartbeat;
}

function RunCard({ run, now }: { run: ActiveRun; now: number }) {
  const kind = asText(run.kind);
  const label = asText(run.label);
  const currentStep = asText(run.current_step);
  const runId = asText(run.run_id);
  const legacy = run.legacy_mirror === true;

  const ref = staleRefMs(run);
  const stale = ref != null && now - ref > STALE_HEARTBEAT_MS;

  // progress {done,total,unit} — only a plain object renders; done/total
  // degrade to "?" independently (ActiveRunCard idiom).
  const progress =
    run.progress != null &&
    typeof run.progress === "object" &&
    !Array.isArray(run.progress)
      ? run.progress
      : null;
  const progressDone = asText(progress?.done);
  const progressTotal = asText(progress?.total);
  const progressUnit = asText(progress?.unit);
  const hasProgress = Boolean(progressDone || progressTotal);

  // Live elapsed since the current step began, falling back to the run start.
  const since = asText(run.step_started_at) || asText(run.started_at) || null;

  const tone = stale
    ? {
        card: "border-amber-800/60 bg-amber-950/20",
        chip: "border-amber-700/60 text-amber-300",
        elapsed: "text-amber-300",
      }
    : {
        card: "border-emerald-800/50 bg-emerald-950/20",
        chip: "border-emerald-700/60 text-emerald-300",
        elapsed: "text-emerald-300",
      };

  return (
    <div
      // The id anchors the LiveCallsBanner's run chips (#run-<run_id>).
      id={runId ? `run-${runId}` : undefined}
      data-testid={`now-run-${runId || "unidentified"}`}
      data-stale={stale ? "true" : "false"}
      className={`rounded border p-3 ${tone.card}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          {kind && (
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tone.chip}`}
            >
              {kind}
            </span>
          )}
          {label && (
            <span className="text-sm font-medium text-zinc-100">{label}</span>
          )}
          {legacy && (
            <span
              data-testid="legacy-mirror-chip"
              title="wrapped from the single-slot active_run.json mirror (pre-D-047 apparatus)"
              className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400"
            >
              legacy mirror
            </span>
          )}
        </div>
        <span className={`font-mono text-xs ${tone.elapsed}`}>
          {elapsed(since, now)}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        {runId && <span className="font-mono text-zinc-500">{runId}</span>}
        {currentStep && (
          <span className="text-zinc-300">
            <span className="text-zinc-500">step:</span>{" "}
            <span className="font-mono">{currentStep}</span>
          </span>
        )}
        {hasProgress && (
          <span className="font-mono text-zinc-300">
            {progressDone || "?"}/{progressTotal || "?"}
            {progressUnit ? ` ${progressUnit}` : ""}
          </span>
        )}
      </div>

      {stale && (
        <div
          className="mt-2 text-xs text-amber-400"
          data-testid={`now-run-stale-${runId || "unidentified"}`}
        >
          stale heartbeat — last sign of life{" "}
          <span className="font-mono">{elapsed(new Date(ref!).toISOString(), now)}</span>{" "}
          ago{legacy ? " (freshest timestamp of the legacy mirror)" : ""}
        </div>
      )}
    </div>
  );
}

export interface NowBoardProps {
  // Tests inject the payload (even as null) — the board then never fetches.
  initial?: ActiveRunsResponse | null;
  // The parent page's static-render gate (Activity's `live`): when false the
  // board does not self-poll, so fixture-injected route tests stay
  // network-free without knowing this component exists.
  live?: boolean;
  // Injectable clock for staleness tests; defaults to the shared 1 Hz clock.
  nowMs?: number;
}

export default function NowBoard({ initial, live = false, nowMs }: NowBoardProps) {
  const tick = useNow();
  const now = nowMs ?? tick;
  const [data, setData] = useState<ActiveRunsResponse | null>(initial ?? null);
  const [skew, setSkew] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selfPoll = initial === undefined && live;

  useEffect(() => {
    if (!selfPoll) return;
    // Several suites module-mock ../api/http with a fixed export list that
    // predates getActiveRuns. Vitest's mock proxy THROWS on the mere access
    // of a missing export (even under typeof), so the binding is read inside
    // a try — under those mocks the board simply never polls and stays
    // empty, rather than crashing the page.
    let fetchRuns: typeof getActiveRuns;
    try {
      fetchRuns = getActiveRuns;
    } catch {
      return;
    }
    if (typeof fetchRuns !== "function") return;
    let cancelled = false;
    const poll = () =>
      fetchRuns()
        .then((r) => {
          if (cancelled) return;
          setData(r);
          setSkew(false);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          if (isVersionSkew404(e, ACTIVE_RUNS_ENDPOINT)) {
            // Older backend binary without the endpoint — quiet note, not red.
            setSkew(true);
            setError(null);
          } else {
            setError(String(e));
          }
        });
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selfPoll]);

  if (skew) {
    return <EndpointMissingNote endpoint={ACTIVE_RUNS_ENDPOINT} />;
  }
  if (error) {
    return (
      <div className="text-xs text-red-400" data-testid="now-board-error">
        {error}
      </div>
    );
  }
  // No payload yet (first poll pending, or a static render with nothing
  // injected): render nothing — the board must never claim idle OR busy
  // without data.
  if (data == null) return null;

  // runs is producer-owned: drop non-object entries instead of crashing.
  const runs = Array.isArray(data.runs)
    ? data.runs.filter(
        (r): r is ActiveRun =>
          r != null && typeof r === "object" && !Array.isArray(r),
      )
    : [];
  const skipped =
    typeof data.skipped === "number" && Number.isFinite(data.skipped)
      ? data.skipped
      : 0;

  return (
    <section data-testid="now-board" className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Now board
        </h3>
        <span className="text-xs text-zinc-600">
          {runs.length} registered run{runs.length === 1 ? "" : "s"}
        </span>
        {skipped > 0 && (
          <span
            className="ml-auto text-[11px] text-amber-500/80"
            data-testid="now-board-skipped"
          >
            {skipped} unreadable run file{skipped === 1 ? "" : "s"} skipped
          </span>
        )}
      </div>
      {runs.length === 0 ? (
        <div
          className="rounded border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-sm text-zinc-500"
          data-testid="now-board-empty"
        >
          no registered runs
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {runs.map((run, i) => (
            <RunCard key={asText(run.run_id) || `idx-${i}`} run={run} now={now} />
          ))}
        </div>
      )}
    </section>
  );
}
