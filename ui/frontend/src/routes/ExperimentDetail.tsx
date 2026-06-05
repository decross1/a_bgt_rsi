// Page B detail — a DEEP DIVE into one experiment's outcome. Renders
// whatever the experiment actually carries:
//  - an OUTCOME headline (the verdict / key metric) up top,
//  - a per-opponent breakdown table + a coop-rate bar chart,
//  - a round-by-round cumulative-payoff line chart and a C/D timeline,
//    selectable by opponent (exp001 JSON shape),
//  - the rendered markdown summary + a trials sample (exp003 MD shape),
//  - an honest "no results yet" notice for empty experiments (exp002).
// Where the round->inspector linkage is absent (exp001 per_round rows carry
// no task_id), we say so rather than fabricate a link.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import MiniMarkdown from "../components/MiniMarkdown";
import { getExperimentDetail } from "../api/experiments";
import { fmt, fmtRatioPct } from "../format";
import type {
  ExperimentDetail as ExperimentDetailT,
  Headline,
  PerOpponentSummary,
  PerRoundEntry,
} from "../types/experiments";

interface Props {
  initial?: ExperimentDetailT | null;
  /** test-only override for the route param */
  expIdOverride?: string;
}

const CARD = "rounded border border-zinc-800 bg-zinc-900/40 p-4";

// Fallback only — the live threshold comes from the backend headline
// (headline.exploit_gap_threshold) so the table tint and the verdict share a
// single source of truth. Used only when no headline is present.
const DEFAULT_EXPLOIT_GAP_THRESHOLD = 0.5;

const TONE = {
  ok: {
    box: "border-emerald-700/50 bg-emerald-900/15 text-emerald-200",
    dot: "bg-emerald-400",
  },
  warn: {
    box: "border-amber-700/50 bg-amber-900/15 text-amber-200",
    dot: "bg-amber-400",
  },
  bad: {
    box: "border-red-800/50 bg-red-900/15 text-red-200",
    dot: "bg-red-400",
  },
} as const;

function HeadlineCard({ headline }: { headline: Headline }) {
  const tone = TONE[headline.tone] ?? TONE.warn;
  return (
    <div
      className={`rounded border p-4 ${tone.box}`}
      data-testid="outcome-headline"
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
        <span className="text-[10px] font-medium uppercase tracking-wide opacity-70">
          Outcome
        </span>
      </div>
      <div className="mt-1 text-sm font-medium">{headline.verdict}</div>
      {(headline.n_opponents != null ||
        headline.mean_llm_coop_rate != null ||
        headline.total_parse_failures != null) && (
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs tabular-nums opacity-80">
          {headline.n_opponents != null && (
            <span>
              exploited {fmt(headline.n_exploited)}/{fmt(headline.n_opponents)}{" "}
              opponents
            </span>
          )}
          {headline.mean_llm_coop_rate != null && (
            <span>
              mean llm coop {fmtRatioPct(headline.mean_llm_coop_rate)}%
            </span>
          )}
          {headline.total_parse_failures != null && (
            <span>parse failures {fmt(headline.total_parse_failures)}</span>
          )}
        </div>
      )}
    </div>
  );
}

function OpponentTable({
  rows,
  selected,
  onSelect,
  exploitThreshold,
}: {
  rows: PerOpponentSummary[];
  selected: string | null;
  onSelect: (opp: string) => void;
  exploitThreshold: number;
}) {
  return (
    <div className={CARD} data-testid="opponent-table">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Per-opponent breakdown
      </h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase text-zinc-500">
              <th className="py-1 pr-3">opponent</th>
              <th className="py-1 pr-3">rounds</th>
              <th className="py-1 pr-3">llm coop</th>
              <th className="py-1 pr-3">opp coop</th>
              <th className="py-1 pr-3">llm payoff</th>
              <th className="py-1 pr-3">opp payoff</th>
              <th className="py-1 pr-3">first D (llm)</th>
              <th className="py-1 pr-3">parse fails</th>
              <th className="py-1 pr-3">wall s</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-zinc-300">
            {rows.map((r) => {
              const lp = r.llm_mean_payoff;
              const op = r.opp_mean_payoff;
              const exploited =
                typeof lp === "number" &&
                typeof op === "number" &&
                op - lp > exploitThreshold;
              const isSel = selected === r.opponent;
              return (
                <tr
                  key={r.opponent}
                  className={`cursor-pointer border-t border-zinc-800/60 ${
                    isSel ? "bg-zinc-800/40" : "hover:bg-zinc-800/20"
                  }`}
                  data-testid={`opp-row-${r.opponent}`}
                  onClick={() => onSelect(r.opponent)}
                >
                  <td className="py-1 pr-3 text-zinc-200">
                    {isSel ? "▸ " : ""}
                    {r.opponent}
                  </td>
                  <td className="py-1 pr-3">{fmt(r.n_rounds)}</td>
                  <td className="py-1 pr-3">{fmtRatioPct(r.llm_coop_rate)}%</td>
                  <td className="py-1 pr-3">{fmtRatioPct(r.opp_coop_rate)}%</td>
                  <td
                    className={`py-1 pr-3 ${
                      exploited ? "text-red-400" : ""
                    }`}
                  >
                    {fmt(r.llm_mean_payoff, 2)}
                  </td>
                  <td className="py-1 pr-3">{fmt(r.opp_mean_payoff, 2)}</td>
                  <td className="py-1 pr-3">
                    {r.first_d_round_llm == null
                      ? "—"
                      : fmt(r.first_d_round_llm)}
                  </td>
                  <td
                    className={`py-1 pr-3 ${
                      (r.llm_parse_failures ?? 0) > 0 ? "text-amber-400" : ""
                    }`}
                  >
                    {fmt(r.llm_parse_failures)}
                  </td>
                  <td className="py-1 pr-3">{fmt(r.wall_clock_s, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 text-[10px] text-zinc-600">
        Click a row to focus the round-by-round charts on that opponent.
      </div>
    </div>
  );
}

function CoopRateChart({
  rows,
  selected,
}: {
  rows: PerOpponentSummary[];
  selected: string | null;
}) {
  const data = rows.map((r) => ({
    opponent: r.opponent,
    llm_coop_pct:
      typeof r.llm_coop_rate === "number" ? r.llm_coop_rate * 100 : 0,
  }));
  return (
    <div className={CARD} data-testid="coop-chart">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        LLM cooperation rate by opponent
      </h2>
      <div className="mt-2 h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="#27272a" vertical={false} />
            <XAxis
              dataKey="opponent"
              tick={{ fill: "#a1a1aa", fontSize: 11 }}
              stroke="#3f3f46"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: "#a1a1aa", fontSize: 11 }}
              stroke="#3f3f46"
              unit="%"
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #3f3f46",
                fontSize: 12,
              }}
              labelStyle={{ color: "#e4e4e7" }}
            />
            <Bar dataKey="llm_coop_pct" radius={[2, 2, 0, 0]}>
              {data.map((d) => (
                <Cell
                  key={d.opponent}
                  fill={
                    selected && d.opponent !== selected
                      ? d.llm_coop_pct >= 50
                        ? "#34d39955"
                        : "#f8717155"
                      : d.llm_coop_pct >= 50
                        ? "#34d399"
                        : "#f87171"
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function CumulativePayoffChart({
  series,
  opponent,
}: {
  series: PerRoundEntry[];
  opponent: string;
}) {
  const data = series.map((e, i) => ({
    round: e.round ?? i + 1,
    cum_llm: typeof e.cum_llm === "number" ? e.cum_llm : null,
    cum_opp: typeof e.cum_opp === "number" ? e.cum_opp : null,
  }));
  const hasCum = data.some((d) => d.cum_llm != null || d.cum_opp != null);
  return (
    <div className={CARD} data-testid="cumulative-chart">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Cumulative payoff over rounds
        </h2>
        <span className="font-mono text-[10px] text-zinc-600">vs {opponent}</span>
      </div>
      {!hasCum ? (
        <div className="mt-2 text-xs text-zinc-500">
          No per-round payoff data for this opponent.
        </div>
      ) : (
        <>
          <div className="mt-1 flex gap-4 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-3 bg-sky-400" /> llm
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-3 bg-zinc-500" /> opponent
            </span>
          </div>
          <div className="mt-2 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
              >
                <CartesianGrid stroke="#27272a" vertical={false} />
                <XAxis
                  dataKey="round"
                  tick={{ fill: "#a1a1aa", fontSize: 11 }}
                  stroke="#3f3f46"
                />
                <YAxis
                  tick={{ fill: "#a1a1aa", fontSize: 11 }}
                  stroke="#3f3f46"
                />
                <Tooltip
                  contentStyle={{
                    background: "#18181b",
                    border: "1px solid #3f3f46",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#e4e4e7" }}
                />
                <Line
                  type="monotone"
                  dataKey="cum_llm"
                  stroke="#38bdf8"
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                  name="llm"
                />
                <Line
                  type="monotone"
                  dataKey="cum_opp"
                  stroke="#71717a"
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                  name="opponent"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

// Compact C/D timeline — one cell per round, colored by the LLM's move,
// with the opponent's move on a second strip. Reads at a glance whether the
// LLM defected and when relative to the opponent.
function MoveTimeline({
  series,
  opponent,
}: {
  series: PerRoundEntry[];
  opponent: string;
}) {
  const cap = 200; // bound the DOM; long sweeps render a leading window
  const shown = series.slice(0, cap);
  const cell = (m: string | null) =>
    m === "C"
      ? "bg-emerald-500/70"
      : m === "D"
        ? "bg-red-500/70"
        : "bg-zinc-700";
  return (
    <div className={CARD} data-testid="move-timeline">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          C / D timeline
        </h2>
        <span className="font-mono text-[10px] text-zinc-600">vs {opponent}</span>
        {series.length > cap && (
          <span className="text-[10px] text-zinc-600">
            (first {cap} of {series.length})
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1">
        <div className="flex items-center gap-1">
          <span className="w-8 shrink-0 text-[10px] text-zinc-500">llm</span>
          <div className="flex flex-wrap gap-px">
            {shown.map((e, i) => (
              <span
                key={i}
                title={`round ${e.round ?? i + 1}: ${e.llm ?? "?"}`}
                className={`h-3 w-1.5 ${cell(e.llm)}`}
              />
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-8 shrink-0 text-[10px] text-zinc-500">opp</span>
          <div className="flex flex-wrap gap-px">
            {shown.map((e, i) => (
              <span
                key={i}
                title={`round ${e.round ?? i + 1}: ${e.opp ?? "?"}`}
                className={`h-3 w-1.5 ${cell(e.opp)}`}
              />
            ))}
          </div>
        </div>
      </div>
      <div className="mt-2 flex gap-4 text-[10px] text-zinc-500">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-1.5 bg-emerald-500/70" /> C
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-1.5 bg-red-500/70" /> D
        </span>
      </div>
    </div>
  );
}

function TrialsSampleCard({
  trials,
}: {
  trials: NonNullable<ExperimentDetailT["trials"]>;
}) {
  const cols = trials.sample.length
    ? Array.from(
        trials.sample.reduce((set, row) => {
          Object.keys(row).forEach((k) => set.add(k));
          return set;
        }, new Set<string>()),
      ).slice(0, 8)
    : [];
  return (
    <div className={CARD} data-testid="trials-sample">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Trials sample
        </h2>
        <span className="text-[10px] text-zinc-600">
          showing {trials.sample.length} of {trials.total_rows}
          {trials.truncated ? " (truncated)" : ""}
        </span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase text-zinc-500">
              {cols.map((c) => (
                <th key={c} className="py-1 pr-3">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono text-zinc-300">
            {trials.sample.map((row, i) => (
              <tr key={i} className="border-t border-zinc-800/60">
                {cols.map((c) => (
                  <td key={c} className="py-1 pr-3 align-top">
                    {formatCell(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") {
    const s = JSON.stringify(v);
    return s.length > 80 ? s.slice(0, 77) + "…" : s;
  }
  const s = String(v);
  return s.length > 80 ? s.slice(0, 77) + "…" : s;
}

export default function ExperimentDetail({ initial, expIdOverride }: Props) {
  const params = useParams<{ expId: string }>();
  const expId = expIdOverride ?? params.expId ?? "";
  const [data, setData] = useState<ExperimentDetailT | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    if (!expId) return;
    let active = true;
    getExperimentDetail(expId)
      .then((d) => active && setData(d))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
    };
  }, [expId, initial]);

  const opponents = data?.summary_json?.per_opponent ?? [];
  const byOpponent = data?.per_round?.by_opponent ?? {};
  const roundOpponents = useMemo(
    () => Object.keys(byOpponent),
    [byOpponent],
  );
  const noResults = data != null && !data.has_results_dir;

  // Default the round-chart focus to the first opponent that has per-round
  // rows (prefer one the summary flags as exploited so the deep-dive lands
  // on the interesting case).
  const focus = useMemo(() => {
    if (selected && roundOpponents.includes(selected)) return selected;
    const worst = data?.headline?.worst?.opponent;
    if (worst && roundOpponents.includes(worst)) return worst;
    return roundOpponents[0] ?? null;
  }, [selected, roundOpponents, data?.headline?.worst?.opponent]);

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="experiment-detail-page">
      <div className="flex items-baseline gap-3">
        <Link
          to="/experiments"
          className="text-xs text-sky-400 hover:text-sky-300"
        >
          ← experiments
        </Link>
        <h1 className="font-mono text-base font-semibold text-zinc-100">
          {data?.id ?? expId}
        </h1>
        {data?.title && (
          <span className="text-xs text-zinc-500">{data.title}</span>
        )}
      </div>

      {error && <div className="mt-3 text-sm text-red-400">{error}</div>}
      {!data && !error && (
        <div className="mt-4 text-sm text-zinc-500">Loading…</div>
      )}

      {/* OUTCOME headline — the verdict / key metric, up top. */}
      {data?.headline && (
        <div className="mt-4">
          <HeadlineCard headline={data.headline} />
        </div>
      )}

      {noResults && (
        <div
          className="mt-4 rounded border border-amber-800/50 bg-amber-900/10 p-4 text-sm text-amber-300"
          data-testid="detail-no-results"
        >
          No <span className="font-mono">results/</span> directory — this
          experiment has no results yet.
        </div>
      )}

      {data?.summary_json_error && (
        <div className="mt-3 text-sm text-red-400">
          summary.json error: {data.summary_json_error}
        </div>
      )}

      {/* JSON-shaped: header metrics + per-opponent table + coop chart. */}
      {data?.summary_json && (
        <div className="mt-4 space-y-4">
          <div className={CARD} data-testid="json-header">
            <div className="flex flex-wrap gap-x-8 gap-y-1 text-sm text-zinc-300">
              <span>
                opponents:{" "}
                <span className="font-mono text-zinc-100">
                  {fmt(data.summary_json.n_opponents)}
                </span>
              </span>
              <span>
                rounds/opp:{" "}
                <span className="font-mono text-zinc-100">
                  {fmt(data.summary_json.rounds_per_opponent)}
                </span>
              </span>
              <span>
                total rounds:{" "}
                <span className="font-mono text-zinc-100">
                  {fmt(data.summary_json.total_rounds)}
                </span>
              </span>
              <span>
                wall clock:{" "}
                <span className="font-mono text-zinc-100">
                  {fmt(data.summary_json.total_wall_clock_s, 1)}s
                </span>
              </span>
              <span>
                via orchestrator:{" "}
                <span className="font-mono text-zinc-100">
                  {String(data.summary_json.via_orchestrator ?? "?")}
                </span>
              </span>
            </div>
          </div>
          {opponents.length > 0 && (
            <OpponentTable
              rows={opponents}
              selected={focus}
              onSelect={setSelected}
              exploitThreshold={
                data.headline?.exploit_gap_threshold ??
                DEFAULT_EXPLOIT_GAP_THRESHOLD
              }
            />
          )}
          {opponents.length > 0 && (
            /* Pass the raw user `selected` (not the auto-default `focus`) so
               bars only dim after an actual click, not on first render. */
            <CoopRateChart rows={opponents} selected={selected} />
          )}
        </div>
      )}

      {/* Round-by-round deep dive for the focused opponent. */}
      {focus && byOpponent[focus] && byOpponent[focus].length > 0 && (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <CumulativePayoffChart series={byOpponent[focus]} opponent={focus} />
          <MoveTimeline series={byOpponent[focus]} opponent={focus} />
        </div>
      )}

      {/* per_round linkage honesty note. */}
      {data?.per_round && (
        <div className="mt-4">
          {data.per_round.round_inspector_linkage ? null : (
            <div
              className="rounded border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-500"
              data-testid="linkage-absent"
            >
              Round → inspector linkage is not available for this experiment:
              its <span className="font-mono">per_round.jsonl</span> rows carry
              no <span className="font-mono">task_id</span>, so individual
              rounds cannot be traced into the call-chain inspector.
              {data.per_round.truncated &&
                " (Per-round series truncated at the scan cap.)"}{" "}
              {fmt(data.per_round.total_rows)} rounds across{" "}
              {fmt(Object.keys(data.per_round.by_opponent).length)} opponents.
            </div>
          )}
        </div>
      )}

      {/* Markdown-shaped: render the summary.md + a trials sample. */}
      {data?.summary_md && (
        <div className="mt-4 space-y-4">
          <div className={CARD} data-testid="markdown-summary">
            <div className="flex items-baseline gap-2">
              <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                Markdown summary
              </h2>
              <span className="text-[10px] text-zinc-600">summary.md</span>
            </div>
            <div className="mt-2">
              <MiniMarkdown source={data.summary_md} />
            </div>
          </div>
        </div>
      )}

      {data?.trials && (
        <div className="mt-4">
          <TrialsSampleCard trials={data.trials} />
        </div>
      )}
    </div>
  );
}
