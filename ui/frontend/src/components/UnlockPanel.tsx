// Week-2 unlock prerequisites (§11.3 of ui_plan.md). Renders the five
// sections from /api/unlock_status that the human needs to attest the
// Week-2 tier-shift unlock — and only renders them. The panel is
// strictly read-only: `attest_command` and `rollback_command` are
// shown as copy-pasteable text, never executed (operating-contract
// rule 8; ui_plan.md §2).
import { useEffect, useState } from "react";
import { getUnlockStatus } from "../api/http";
import type {
  HardGatePending,
  SoftGatePending,
  UnlockStatus,
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

function SectionHeader({
  label,
  badge,
}: {
  label: string;
  badge: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-400">
        {label}
      </h3>
      {badge}
    </div>
  );
}

function CommandLine({ cmd }: { cmd: string }) {
  // Copy-pasteable CLI text. The UI does not run this — surfacing the
  // string is the affordance §11.3 requires (operating-contract rule 8).
  return (
    <code className="block break-all rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-300">
      $ {cmd}
    </code>
  );
}

function RunLogIntegritySection({ data }: { data: UnlockStatus["run_log_integrity"] }) {
  if (!data.available) {
    return (
      <div>
        <SectionHeader
          label="Run-log integrity"
          badge={<StatusBadge tone="info" text="absent" />}
        />
        <div className="mt-1 text-xs text-zinc-500">
          run_state/week1.run.jsonl not present.
        </div>
      </div>
    );
  }
  const badge = data.ok ? (
    <StatusBadge tone="ok" text="ok" />
  ) : (
    <StatusBadge tone="fail" text="fail" />
  );
  return (
    <div>
      <SectionHeader label="Run-log integrity" badge={badge} />
      <div className="mt-1 text-xs text-zinc-400">
        {data.total_lines} entries · {data.malformed_lines.length} malformed ·{" "}
        {data.rolling_count} in last {data.rolling_window_days} d
      </div>
      {data.malformed_lines.length > 0 && (
        <div className="mt-1 text-xs text-red-400">
          malformed lines: {data.malformed_lines.join(", ")}
        </div>
      )}
    </div>
  );
}

function SoftGateRow({ entry }: { entry: SoftGatePending }) {
  return (
    <div className="mt-1.5 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5">
      <div className="flex items-baseline gap-2 text-xs">
        <span className="font-mono text-zinc-200">{entry.task_id}</span>
        {entry.agent_id && (
          <span className="text-zinc-500">{entry.agent_id}</span>
        )}
        {entry.ts && (
          <span className="ml-auto text-zinc-600">{entry.ts}</span>
        )}
      </div>
      {entry.summary && (
        <div className="mt-1 text-xs text-zinc-300">{entry.summary}</div>
      )}
      {(entry.expected_observable || entry.observed_actual) && (
        <div className="mt-1 grid grid-cols-2 gap-2 text-[11px] text-zinc-500">
          {entry.expected_observable && (
            <div>
              <span className="uppercase tracking-wide">expected:</span>{" "}
              <span className="text-zinc-400">{entry.expected_observable}</span>
            </div>
          )}
          {entry.observed_actual && (
            <div>
              <span className="uppercase tracking-wide">observed:</span>{" "}
              <span className="text-zinc-400">{entry.observed_actual}</span>
            </div>
          )}
        </div>
      )}
      <div className="mt-1.5">
        <div className="text-[10px] uppercase tracking-wide text-zinc-500">
          rollback (copy-paste)
        </div>
        <CommandLine cmd={entry.rollback_command} />
      </div>
    </div>
  );
}

function SoftGateSection({ data }: { data: UnlockStatus["soft_gate_queue"] }) {
  if (!data.available) {
    return (
      <div>
        <SectionHeader
          label="Soft-gate queue"
          badge={<StatusBadge tone="info" text="absent" />}
        />
        <div className="mt-1 text-xs text-zinc-500">
          run_state/attestations.jsonl not present.
        </div>
      </div>
    );
  }
  const tone = data.pending.length === 0 ? "ok" : "warn";
  const text = data.pending.length === 0 ? "clear" : `${data.pending.length} pending`;
  return (
    <div>
      <SectionHeader
        label="Soft-gate queue"
        badge={<StatusBadge tone={tone} text={text} />}
      />
      {data.pending.length === 0 && (
        <div className="mt-1 text-xs text-zinc-500">
          No pending soft-gate attestations.
        </div>
      )}
      {data.pending.map((p) => (
        <SoftGateRow key={p.task_id} entry={p} />
      ))}
    </div>
  );
}

function HardGateRow({ entry }: { entry: HardGatePending }) {
  return (
    <div className="mt-1.5 rounded border border-red-900/60 bg-red-950/20 px-2 py-1.5">
      <div className="flex items-baseline gap-2 text-xs">
        <span className="font-mono text-zinc-100">
          {entry.task_id ?? "(unnamed)"}
        </span>
      </div>
      {entry.attest_command && (
        <div className="mt-1.5">
          <div className="text-[10px] uppercase tracking-wide text-zinc-500">
            attest (copy-paste — human-only, hard-gate)
          </div>
          <CommandLine cmd={entry.attest_command} />
        </div>
      )}
    </div>
  );
}

function HardGateSection({
  data,
}: {
  data: UnlockStatus["hard_gates_pending"];
}) {
  if (!data.available) {
    return (
      <div>
        <SectionHeader
          label="Hard gates pending"
          badge={<StatusBadge tone="info" text="absent" />}
        />
      </div>
    );
  }
  const tone = data.pending.length === 0 ? "ok" : "fail";
  const text =
    data.pending.length === 0 ? "clear" : `${data.pending.length} pending`;
  return (
    <div>
      <SectionHeader
        label="Hard gates pending"
        badge={<StatusBadge tone={tone} text={text} />}
      />
      {data.pending.length === 0 && (
        <div className="mt-1 text-xs text-zinc-500">
          No pending hard-gate attestations.
        </div>
      )}
      {data.pending.map((p, i) => (
        <HardGateRow key={p.task_id ?? `hg-${i}`} entry={p} />
      ))}
    </div>
  );
}

// Group metric_log keys by the day_N prefix so the per-day comparison
// the alignment-evidence §11.3 calls out is visible at a glance.
// Anything not matching `day(_)?N…` goes under "other".
function groupMetricLog(
  log: Record<string, number | string | null>,
): Array<{ day: string; entries: Array<{ key: string; value: string }> }> {
  const groups: Record<string, Array<{ key: string; value: string }>> = {};
  for (const [key, value] of Object.entries(log)) {
    const match = key.match(/^day[_-]?(\d+(?:[._]\d+)?)/);
    const dayKey = match ? `day ${match[1].replace("_", ".")}` : "other";
    if (!groups[dayKey]) groups[dayKey] = [];
    groups[dayKey].push({
      key,
      value: value == null ? "—" : String(value),
    });
  }
  // Sort so day groups come in numeric order, "other" last.
  const ordered = Object.keys(groups).sort((a, b) => {
    if (a === "other") return 1;
    if (b === "other") return -1;
    const an = parseFloat(a.replace(/^day /, ""));
    const bn = parseFloat(b.replace(/^day /, ""));
    return an - bn;
  });
  return ordered.map((day) => ({ day, entries: groups[day] }));
}

function MetricLogSection({
  data,
}: {
  data: UnlockStatus["metric_log"];
}) {
  const groups = groupMetricLog(data);
  const empty = groups.length === 0;
  return (
    <div>
      <SectionHeader
        label="metric_log (drift check)"
        badge={
          empty ? (
            <StatusBadge tone="info" text="empty" />
          ) : (
            <StatusBadge tone="info" text={`${Object.keys(data).length} keys`} />
          )
        }
      />
      {empty ? (
        <div className="mt-1 text-xs text-zinc-500">
          state.metric_log is empty — no per-day metrics recorded yet.
        </div>
      ) : (
        <div className="mt-1.5 space-y-2">
          {groups.map((g) => (
            <div key={g.day}>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                {g.day}
              </div>
              <dl className="mt-0.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                {g.entries.map((e) => (
                  <div key={e.key} className="contents">
                    <dt className="font-mono text-zinc-500">{e.key}</dt>
                    <dd className="font-mono text-zinc-200">{e.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FallbacksSection({
  data,
}: {
  data: UnlockStatus["fallbacks_taken"];
}) {
  const entries = Object.entries(data);
  const tone = entries.length === 0 ? "ok" : "warn";
  const text = entries.length === 0 ? "none" : `${entries.length} taken`;
  return (
    <div>
      <SectionHeader
        label="fallbacks_taken"
        badge={<StatusBadge tone={tone} text={text} />}
      />
      {entries.length === 0 ? (
        <div className="mt-1 text-xs text-zinc-500">No fallbacks taken.</div>
      ) : (
        <ul className="mt-1.5 space-y-1 text-xs">
          {entries.map(([key, reason]) => (
            <li key={key}>
              <span className="font-mono text-zinc-400">{key}:</span>{" "}
              <span className="text-zinc-300">{reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function UnlockPanel() {
  const [data, setData] = useState<UnlockStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getUnlockStatus()
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
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Week-2 unlock prerequisites
        </h2>
        <span className="text-[10px] text-zinc-600">
          §11.3 — /api/unlock_status · read-only render
        </span>
        {data?.current_day && (
          <span className="ml-auto text-[11px] text-zinc-500">
            apparatus {data.current_day}
          </span>
        )}
      </div>
      {error && (
        <div className="mt-2 text-sm text-red-400">{error}</div>
      )}
      {!data && !error && (
        <div className="mt-2 text-sm text-zinc-500">Loading…</div>
      )}
      {data && (
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
          <RunLogIntegritySection data={data.run_log_integrity} />
          <SoftGateSection data={data.soft_gate_queue} />
          <HardGateSection data={data.hard_gates_pending} />
          <FallbacksSection data={data.fallbacks_taken} />
          <div className="md:col-span-2">
            <MetricLogSection data={data.metric_log} />
          </div>
        </div>
      )}
    </div>
  );
}
