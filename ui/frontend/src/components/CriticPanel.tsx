// Critic invocations (Day-9 W2-01). Surfaces the latest ≤50 critic runs
// from /api/critic_summary plus the rolling flag-rate + per-fixture
// confusion-matrix matchup table. Strictly read-only: no execute
// affordances (operating-contract rule 8). Mirrors UnlockPanel.tsx's
// data-fetching + 10s polling pattern.
import { useEffect, useState } from "react";
import { getCriticSummary } from "../api/http";
import type {
  CriticDecision,
  CriticMatchupRow,
  CriticOutcome,
  CriticRecentRun,
  CriticSummary,
} from "../types/schemas";

function StatusBadge({
  tone,
  text,
}: {
  tone: "ok" | "warn" | "fail" | "info";
  text: string;
}) {
  const cls = {
    ok: "bg-emerald-950 text-emerald-400",
    warn: "bg-amber-950 text-amber-400",
    fail: "bg-red-950 text-red-400",
    info: "bg-zinc-800 text-zinc-400",
  }[tone];
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${cls}`}
    >
      {text}
    </span>
  );
}

function decisionBadge(decision: CriticDecision | null) {
  if (decision === "flawed") return <StatusBadge tone="warn" text="flawed" />;
  if (decision === "sound") return <StatusBadge tone="ok" text="sound" />;
  return <StatusBadge tone="info" text="—" />;
}

function outcomeBadge(outcome: CriticOutcome) {
  // TP / TN = correct (ok); FP / FN = wrong (fail); unrun / unknown = info.
  if (outcome === "TP" || outcome === "TN")
    return <StatusBadge tone="ok" text={outcome} />;
  if (outcome === "FP" || outcome === "FN")
    return <StatusBadge tone="fail" text={outcome} />;
  return <StatusBadge tone="info" text={outcome} />;
}

function FlagRateHeader({
  data,
}: {
  data: CriticSummary["flag_rate"];
}) {
  if (!data.available) {
    return (
      <div className="text-xs text-zinc-500">
        logs/critic_eval.jsonl not present yet.
      </div>
    );
  }
  const rateText =
    data.flag_rate === null ? "—" : `${(data.flag_rate * 100).toFixed(0)} %`;
  return (
    <div className="text-xs text-zinc-400">
      <span className="text-zinc-200 font-mono">{rateText}</span>{" "}
      flagged · {data.flawed_count}/{data.total} in last {data.window_days} d
    </div>
  );
}

function MatchupSummary({
  data,
}: {
  data: CriticSummary["fixture_matchup"];
}) {
  if (!data.available) {
    return (
      <div className="text-xs text-zinc-500">
        Fixtures or critic log absent — matchup unavailable.
      </div>
    );
  }
  const accuracyText =
    data.accuracy === null
      ? "—"
      : `${(data.accuracy * 100).toFixed(0)} % (${data.scored}/${data.total_fixtures})`;
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-zinc-400">
      <span className="text-zinc-300">accuracy {accuracyText}</span>
      <span>TP {data.counts.TP}</span>
      <span>TN {data.counts.TN}</span>
      <span className={data.counts.FP > 0 ? "text-red-400" : ""}>
        FP {data.counts.FP}
      </span>
      <span className={data.counts.FN > 0 ? "text-red-400" : ""}>
        FN {data.counts.FN}
      </span>
      <span>unrun {data.counts.unrun}</span>
      {data.counts.unknown_fixture > 0 && (
        <span className="text-amber-400">
          unknown-fixture {data.counts.unknown_fixture}
        </span>
      )}
    </div>
  );
}

function RecentRunRow({ row }: { row: CriticRecentRun }) {
  const targetText =
    row.target_count === 0
      ? "no expected targets"
      : `${row.target_hits.length}/${row.target_count} targets hit`;
  return (
    <div className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="flex flex-wrap items-baseline gap-2 text-xs">
        <span className="font-mono text-zinc-200">
          {row.hypothesis_id ?? "(unnamed)"}
        </span>
        {decisionBadge(row.flag_decision)}
        {row.ground_truth_label && (
          <span className="text-[10px] uppercase tracking-wide text-zinc-500">
            truth: {row.ground_truth_label}
          </span>
        )}
        {row.injected_flaw_type && row.injected_flaw_type !== "none" && (
          <span className="text-[10px] text-zinc-500">
            {row.injected_flaw_type}
          </span>
        )}
        {row.timestamp && (
          <span className="ml-auto text-zinc-600">{row.timestamp}</span>
        )}
      </div>
      {row.critique_excerpt && (
        <div className="mt-1 text-xs text-zinc-300">{row.critique_excerpt}</div>
      )}
      <div className="mt-1 text-[11px] text-zinc-500">{targetText}</div>
    </div>
  );
}

function RecentRunsSection({
  data,
}: {
  data: CriticSummary["recent_runs"];
}) {
  if (!data.available) {
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            Recent runs
          </h3>
          <StatusBadge tone="info" text="absent" />
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          logs/critic_eval.jsonl not present yet — Track A's
          workers/critic.py has not produced output. The panel lights
          up once the Day-9 cron wrapper appends its first record.
        </div>
      </div>
    );
  }
  if (data.rows.length === 0) {
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            Recent runs
          </h3>
          <StatusBadge tone="info" text="0 runs" />
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          logs/critic_eval.jsonl is empty — awaiting the first critic
          invocation.
        </div>
      </div>
    );
  }
  // Newest first in the panel even though the backend returns the
  // newest-last (append order) tail — a freshly produced row should
  // surface at the top so the user notices it.
  const newestFirst = [...data.rows].reverse();
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
          Recent runs
        </h3>
        <StatusBadge
          tone="info"
          text={`${data.rows.length} of ${data.total_runs}`}
        />
        {data.malformed_lines.length > 0 && (
          <span className="text-[11px] text-red-400">
            {data.malformed_lines.length} malformed
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1.5">
        {newestFirst.map((row, i) => (
          <RecentRunRow
            key={`${row.hypothesis_id ?? "row"}-${row.timestamp ?? i}`}
            row={row}
          />
        ))}
      </div>
    </div>
  );
}

function MatchupRow({ row }: { row: CriticMatchupRow }) {
  return (
    <tr className="border-t border-zinc-800/60">
      <td className="py-1 pr-3 font-mono text-zinc-200">{row.fixture_id}</td>
      <td className="py-1 pr-3 text-zinc-500">{row.ground_truth_label ?? "—"}</td>
      <td className="py-1 pr-3 text-zinc-300">{row.decision ?? "—"}</td>
      <td className="py-1 pr-3">{outcomeBadge(row.outcome)}</td>
      <td className="py-1 pr-3 text-zinc-500">
        {row.target_count === 0
          ? "—"
          : `${row.target_hits.length}/${row.target_count}`}
      </td>
      <td className="py-1 text-zinc-600">{row.latest_run_ts ?? "—"}</td>
    </tr>
  );
}

function MatchupTableSection({
  data,
}: {
  data: CriticSummary["fixture_matchup"];
}) {
  if (!data.available || data.rows.length === 0) return null;
  // Order: scored rows (TP/FP/TN/FN) first sorted by outcome severity;
  // unrun and unknown_fixture rows after.
  const severity: Record<CriticOutcome, number> = {
    FN: 0,
    FP: 1,
    TP: 2,
    TN: 3,
    unknown_truth: 4,
    unknown_fixture: 5,
    unrun: 6,
  };
  const sorted = [...data.rows].sort(
    (a, b) =>
      severity[a.outcome] - severity[b.outcome] ||
      a.fixture_id.localeCompare(b.fixture_id),
  );
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
          Fixture matchup
        </h3>
        <span className="text-[10px] text-zinc-600">
          §11.3 — flawed-vs-sound · positive class = flawed
        </span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="pb-1 pr-3 font-normal">fixture</th>
              <th className="pb-1 pr-3 font-normal">truth</th>
              <th className="pb-1 pr-3 font-normal">decision</th>
              <th className="pb-1 pr-3 font-normal">outcome</th>
              <th className="pb-1 pr-3 font-normal">targets</th>
              <th className="pb-1 font-normal">latest run</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <MatchupRow key={row.fixture_id} row={row} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CriticPanel() {
  const [data, setData] = useState<CriticSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getCriticSummary()
        .then((d) => {
          if (!active) return;
          setData(d);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Critic invocations
        </h2>
        <span className="text-[10px] text-zinc-600">
          §11.3 phase-2 prereq — /api/critic_summary · read-only render
        </span>
        {data && (
          <span className="ml-auto">
            <FlagRateHeader data={data.flag_rate} />
          </span>
        )}
      </div>
      {data && (
        <div className="mt-1">
          <MatchupSummary data={data.fixture_matchup} />
        </div>
      )}
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {!data && !error && (
        <div className="mt-2 text-sm text-zinc-500">Loading…</div>
      )}
      {data && (
        <div className="mt-3 space-y-4">
          <RecentRunsSection data={data.recent_runs} />
          <MatchupTableSection data={data.fixture_matchup} />
        </div>
      )}
    </div>
  );
}
