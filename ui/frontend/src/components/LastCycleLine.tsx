// LastCycleLine — Pulse's one-line "what did the loop just do" (UI
// simplification S1). One /api/coordinator/cycles poll; renders cycles[0]
// (the backend sorts newest-first): topic · status · errored count ·
// promoted findings · age. Tones: status "no_valid_plan" amber (the loop
// planned nothing actionable), errored outcomes red, promoted findings
// emerald. Links into the cycle narrative at /cycles (the S3 rename of the
// old /coordinator route — the S1 deviation is now resolved).
import { memo } from "react";
import { Link } from "react-router-dom";
import { getCoordinatorCycles } from "../api/http";
import { usePolled } from "../api/pollhub";
import { ageLabel } from "../ladderBar";
import type { CoordinatorCycle } from "../types/schemas";

function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

interface Props {
  // Fixture injection (tests render synchronously, never fetch). null =
  // loaded-but-empty history.
  initial?: CoordinatorCycle[] | null;
  pollMs?: number;
}

function LastCycleLine({ initial, pollMs = 60000 }: Props) {
  // Controlled mode (Pulse passes its own cycles poll): render straight from
  // the PROP — the old useState(initial) copy froze this line at its
  // first-mount payload and it never updated again (perf-audit find,
  // 2026-08-18). Standalone mounts poll via the hub instead; the "cycles"
  // key is shared with Pulse's poll, so the two can never double-fetch.
  const poll = usePolled<{ cycles?: CoordinatorCycle[] }>(
    "cycles",
    getCoordinatorCycles,
    { intervalMs: pollMs, enabled: initial === undefined },
  );
  const cycles: CoordinatorCycle[] =
    initial !== undefined
      ? Array.isArray(initial)
        ? initial
        : []
      : Array.isArray(poll.data?.cycles)
        ? poll.data.cycles
        : [];
  const loaded = initial !== undefined || poll.data !== undefined;
  // SWR: a failing refetch keeps the last line; red only before any data.
  const error =
    initial === undefined && poll.failing && poll.data === undefined
      ? String(poll.error)
      : null;

  if (error) {
    return (
      <div
        data-testid="last-cycle-error"
        style={{ fontSize: "var(--text-meta)", color: "var(--status-bad)" }}
      >
        {error}
      </div>
    );
  }
  if (!loaded) return null;

  // Producer-owned row guard (one malformed line never blanks Pulse).
  const last =
    cycles.length > 0 && cycles[0] != null && typeof cycles[0] === "object"
      ? cycles[0]
      : null;

  if (last == null) {
    return (
      <div
        data-testid="last-cycle-empty"
        style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}
      >
        no coordinator cycles yet
      </div>
    );
  }

  const topic = asText(last.topic) ?? "(no topic)";
  const status = asText(last.status);
  const errored = Array.isArray(last.outcomes)
    ? last.outcomes.filter(
        (o) => o != null && typeof o === "object" && o.status === "errored",
      ).length
    : 0;
  const findings = Array.isArray(last.promoted_finding_ids)
    ? last.promoted_finding_ids.length
    : 0;

  return (
    <div
      data-testid="last-cycle-line"
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "baseline",
        gap: "var(--space-3)",
        fontSize: "var(--text-meta)",
        color: "var(--fg-muted)",
      }}
    >
      <span>last cycle</span>
      <span style={{ color: "var(--fg)" }}>{topic}</span>
      {status && (
        <span
          data-testid="last-cycle-status"
          data-tone={status === "no_valid_plan" ? "warn" : "neutral"}
          style={{
            color:
              status === "no_valid_plan"
                ? "var(--status-warn)"
                : "var(--fg-muted)",
          }}
        >
          {status}
        </span>
      )}
      {errored > 0 && (
        <span
          data-testid="last-cycle-errored"
          data-tone="bad"
          style={{ color: "var(--status-bad)" }}
        >
          {errored} errored
        </span>
      )}
      {findings > 0 && (
        <span
          data-testid="last-cycle-findings"
          data-tone="ok"
          style={{ color: "var(--status-ok)" }}
        >
          +{findings} finding{findings === 1 ? "" : "s"}
        </span>
      )}
      <span className="tnum" style={{ fontFamily: "var(--font-mono)" }}>
        {ageLabel(last.timestamp, Date.now())}
      </span>
      <Link to="/cycles" style={{ marginLeft: "auto", color: "var(--accent)" }}>
        cycles →
      </Link>
    </div>
  );
}

// Memoized: Pulse passes `initial` (a stable identity between cycle polls),
// so this line skips the page's clock/telemetry re-renders.
export default memo(LastCycleLine);
