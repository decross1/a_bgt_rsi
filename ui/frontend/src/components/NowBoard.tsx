// NowBoard — the ONE merged now-card (UI simplification S1). Fed by GET
// /api/activity/active_runs (the D-047 registry: run_state/active_runs/
// <run_id>.json, one file per LIVE run), plus OPTIONAL liveCalls/telemetry
// feeds that light a RUNNING/BUSY/IDLE headline strip (shared verdict logic
// in nowVerdict.ts — "registered" derives from the registry itself, so the
// strip absorbs SystemActivityHero without the two retired mirror endpoints).
// It took over the hero's run slot from the single-run ActiveRunCard:
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
import StatusDot, { type Status as StatusName } from "../design/StatusDot";
import { getActiveRuns } from "../api/http";
import { ageLabel } from "../ladderBar";
import { elapsed, useNow } from "../time";
import type { ActiveRun, ActiveRunsResponse, LiveCalls } from "../types/activity";
import type { TelemetrySample } from "../types/schemas";
import EndpointMissingNote, { isVersionSkew404 } from "./EndpointMissingNote";
import {
  buildEvidence,
  computeActivity,
  STATE_LABEL,
  type ActivityState,
  type ActivityVerdict,
} from "./nowVerdict";

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

  const muted = { fontSize: "var(--text-meta)", color: "var(--fg-muted)" };

  return (
    <div
      // The id anchors the LiveCallsBanner's run chips (#run-<run_id>).
      id={runId ? `run-${runId}` : undefined}
      data-testid={`now-run-${runId || "unidentified"}`}
      data-stale={stale ? "true" : "false"}
      style={{
        background: "var(--surface-2)",
        border: `1px solid ${stale ? "var(--status-warn)" : "var(--border-1)"}`,
        borderRadius: "var(--radius-card)",
        padding: "var(--space-3)",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "var(--space-2)",
        }}
      >
        {/* The ONLY animated element on the card, and it pulses only while a
            run is genuinely alive — a stale heartbeat goes static amber. */}
        <StatusDot
          status={stale ? "warn" : "ok"}
          pulse={!stale}
          label={stale ? "stale heartbeat" : "running"}
        />
        {label && (
          <span
            style={{
              fontSize: "var(--text-prose)",
              fontWeight: "var(--weight-medium)",
              color: "var(--fg)",
            }}
          >
            {label}
          </span>
        )}
        {kind && <span style={muted}>{kind}</span>}
        {legacy && (
          <span
            data-testid="legacy-mirror-chip"
            title="wrapped from the single-slot active_run.json mirror (pre-D-047 apparatus)"
            style={muted}
          >
            legacy mirror
          </span>
        )}
        <span
          className="tnum"
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-meta)",
            color: stale ? "var(--status-warn)" : "var(--fg)",
          }}
        >
          {elapsed(since, now)}
        </span>
      </div>

      <div
        style={{
          marginTop: "var(--space-2)",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "baseline",
          gap: "var(--space-3)",
          fontFamily: "var(--font-mono)",
          ...muted,
        }}
      >
        {runId && <span>{runId}</span>}
        {currentStep && <span style={{ color: "var(--fg)" }}>{currentStep}</span>}
        {hasProgress && (
          <span className="tnum">
            {progressDone || "?"}/{progressTotal || "?"}
            {progressUnit ? ` ${progressUnit}` : ""}
          </span>
        )}
      </div>

      {stale && (
        <div
          data-testid={`now-run-stale-${runId || "unidentified"}`}
          style={{
            marginTop: "var(--space-2)",
            fontSize: "var(--text-meta)",
            color: "var(--status-warn)",
          }}
        >
          stale heartbeat — last sign of life{" "}
          <span className="tnum" style={{ fontFamily: "var(--font-mono)" }}>
            {elapsed(new Date(ref!).toISOString(), now)}
          </span>{" "}
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
  // HEADLINE-STRIP feeds (UI simplification S1 — the merged now-card). BOTH
  // optional and ADDITIVE: when neither is provided (old mounts: /activity)
  // the strip does not render and the board is byte-identical to before.
  // "Registered" derives from the D-047 registry itself (runs.length > 0) —
  // NOT from the retired activeIteration/coordinatorActive mirrors — so the
  // strip can never claim RUNNING off a stale mirror; busy/idle come from
  // the shared computeActivity (nowVerdict.ts) over these two feeds.
  liveCalls?: LiveCalls | null;
  telemetry?: TelemetrySample | null;
  // R3: the ISO instant the loop last FINISHED something (newest coordinator
  // cycle / iteration end). Used ONLY to qualify the idle state — "nothing is
  // running, and here is when something last did" — never to imply a run is
  // live. Absent/unparseable simply drops the clause.
  lastFinishedIso?: string | null;
}

// The one-line verdict for the strip. Registered wins (a registry run IS
// provenance); the first run is named the way the hero named its mirrors.
function stripVerdict(
  runs: ActiveRun[],
  liveCalls: LiveCalls | null | undefined,
  telemetry: TelemetrySample | null | undefined,
  now: number,
): ActivityVerdict {
  if (runs.length > 0) {
    const first = runs[0];
    const label = [asText(first.label) || asText(first.kind) || asText(first.run_id),
      asText(first.current_step)]
      .filter(Boolean)
      .join(" · ");
    const more = runs.length > 1 ? ` (+${runs.length - 1} more)` : "";
    return {
      state: "registered",
      headline: `RUNNING — ${label || "registered run"}${more}`,
      evidence: buildEvidence({ liveCalls, telemetry }, now),
    };
  }
  return computeActivity({ liveCalls, telemetry }, now);
}

export default function NowBoard({
  initial,
  live = false,
  nowMs,
  liveCalls,
  telemetry,
  lastFinishedIso,
}: NowBoardProps) {
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

  // The strip only renders when a feed prop was provided at all — an old
  // mount (no feeds) must not claim IDLE without data.
  const stripLive = liveCalls !== undefined || telemetry !== undefined;
  const verdict = stripLive
    ? stripVerdict(runs, liveCalls, telemetry, now)
    : null;
  // R3: the verdict was a full-width banner competing with the owed hero. It
  // is now a compact status line on this card's header — same verdict, same
  // testids, demoted emphasis.
  const verdictDot: Record<ActivityState, StatusName> = {
    registered: "ok",
    "busy-unregistered": "warn",
    idle: "idle",
  };
  const lastFinished = lastFinishedIso ? ageLabel(lastFinishedIso, now) : "—";

  return (
    <section
      data-testid="now-board"
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "var(--space-2)",
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: "var(--text-title)",
            fontWeight: "var(--weight-medium)",
            color: "var(--fg)",
          }}
        >
          Running now
        </h3>
        <span style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}>
          {runs.length} registered run{runs.length === 1 ? "" : "s"}
        </span>
        {verdict && (
          <span
            data-testid="now-verdict"
            data-state={verdict.state}
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: "var(--space-2)",
              fontSize: "var(--text-meta)",
              color: "var(--fg-muted)",
            }}
          >
            <StatusDot
              status={verdictDot[verdict.state]}
              pulse={verdict.state !== "idle"}
              label={STATE_LABEL[verdict.state]}
            />
            {STATE_LABEL[verdict.state]}
          </span>
        )}
      </div>

      {skipped > 0 && (
        <div
          data-testid="now-board-skipped"
          style={{ fontSize: "var(--text-meta)", color: "var(--status-warn)" }}
        >
          {skipped} unreadable run file{skipped === 1 ? "" : "s"} skipped
        </div>
      )}

      {runs.length === 0 ? (
        <div
          data-testid="now-board-empty"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            background: "var(--surface-2)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--radius-card)",
            padding: "var(--space-3)",
            fontSize: "var(--text-ui)",
            color: "var(--fg-muted)",
          }}
        >
          {/* Never a pulse, never a fake run: this is the honest idle state. */}
          <StatusDot status="idle" label="idle" />
          no registered runs
          {lastFinishedIso && <span>· last finished {lastFinished} ago</span>}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gap: "var(--space-3)",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          }}
        >
          {runs.map((run, i) => (
            <RunCard key={asText(run.run_id) || `idx-${i}`} run={run} now={now} />
          ))}
        </div>
      )}

      {verdict && verdict.evidence.length > 0 && (
        <div
          data-testid="now-verdict-evidence"
          className="tnum"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          {verdict.evidence.join(" · ")}
        </div>
      )}
    </section>
  );
}
