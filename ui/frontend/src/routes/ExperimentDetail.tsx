import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import MiniMarkdown from "../components/MiniMarkdown";
import { getExperimentDetail } from "../api/experiments";
import type { ExperimentDetail as ExperimentDetailT } from "../types/experiments";
import "./experiments.css";

interface Props {
  initial?: ExperimentDetailT | null;
  /** Test-only override for the route parameter. */
  expIdOverride?: string;
}

type RecordValue = Record<string, unknown>;
type Tone = "ok" | "warn" | "bad" | "unknown";

interface HeadlineView {
  verdict: string;
  tone: Tone;
  kind: string | null;
  worstOpponent: string | null;
  exploitThreshold: number | null;
  nExploited: number | null;
  nOpponents: number | null;
  nMechanisms: number | null;
  nYes: number | null;
  meanLlmCoopRate: number | null;
  totalParseFailures: number | null;
}

interface OpponentView {
  opponent: string;
  nRounds: number | null;
  llmCoopRate: number | null;
  opponentCoopRate: number | null;
  llmMeanPayoff: number | null;
  opponentMeanPayoff: number | null;
  firstDefectionLlm: number | null;
  parseFailures: number | null;
  wallClockSeconds: number | null;
}

interface MechanismView {
  mechanism: string;
  truthfulFraction: number | null;
  meanEfficiency: number | null;
  meanRevenue: number | null;
  meanSignedResidual: number | null;
  parseFailureRate: number | null;
  verdict: string | null;
}

interface RoundView {
  round: number | null;
  llmMove: string | null;
  opponentMove: string | null;
  llmPayoff: number | null;
  opponentPayoff: number | null;
  cumulativeLlm: number | null;
  cumulativeOpponent: number | null;
}

interface TrialsView {
  sample: RecordValue[];
  totalRows: number | null;
  truncated: boolean | null;
}

function isRecord(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function asStrictText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function displayNumber(value: number | null, digits?: number): string {
  if (value === null) return "Not reported";
  return digits === undefined ? String(value) : value.toFixed(digits);
}

function displayRatio(value: number | null): string {
  return value === null ? "Not reported" : `${(value * 100).toFixed(1)}%`;
}

function normalizeHeadline(value: unknown): HeadlineView | null {
  if (!isRecord(value)) return null;
  const verdict = asStrictText(value.verdict);
  if (verdict === null) return null;
  const suppliedTone = asStrictText(value.tone);
  const tone: Tone =
    suppliedTone === "ok" || suppliedTone === "warn" || suppliedTone === "bad"
      ? suppliedTone
      : "unknown";
  const worst = isRecord(value.worst) ? value.worst : null;
  return {
    verdict,
    tone,
    kind: asStrictText(value.kind),
    worstOpponent: asStrictText(worst?.opponent),
    exploitThreshold: asNumber(value.exploit_gap_threshold),
    nExploited: asNumber(value.n_exploited),
    nOpponents: asNumber(value.n_opponents),
    nMechanisms: asNumber(value.n_mechanisms),
    nYes: asNumber(value.n_yes),
    meanLlmCoopRate: asNumber(value.mean_llm_coop_rate),
    totalParseFailures: asNumber(value.total_parse_failures),
  };
}

function normalizeOpponents(summary: RecordValue | null): OpponentView[] {
  if (!summary || !Array.isArray(summary.per_opponent)) return [];
  const rows: OpponentView[] = [];
  for (const value of summary.per_opponent) {
    if (!isRecord(value)) continue;
    const opponent = asStrictText(value.opponent);
    if (!opponent) continue;
    rows.push({
      opponent,
      nRounds: asNumber(value.n_rounds),
      llmCoopRate: asNumber(value.llm_coop_rate),
      opponentCoopRate: asNumber(value.opp_coop_rate),
      llmMeanPayoff: asNumber(value.llm_mean_payoff),
      opponentMeanPayoff: asNumber(value.opp_mean_payoff),
      firstDefectionLlm: asNumber(value.first_d_round_llm),
      parseFailures: asNumber(value.llm_parse_failures),
      wallClockSeconds: asNumber(value.wall_clock_s),
    });
  }
  return rows;
}

function normalizeMechanisms(summary: RecordValue | null): MechanismView[] {
  if (!summary || !Array.isArray(summary.per_mechanism)) return [];
  const rows: MechanismView[] = [];
  for (const value of summary.per_mechanism) {
    if (!isRecord(value)) continue;
    const mechanism = asStrictText(value.mechanism);
    if (!mechanism) continue;
    rows.push({
      mechanism,
      truthfulFraction: asNumber(value.truthful_fraction),
      meanEfficiency: asNumber(value.mean_efficiency),
      meanRevenue: asNumber(value.mean_revenue),
      meanSignedResidual: asNumber(value.mean_signed_residual),
      parseFailureRate: asNumber(value.parse_failure_rate),
      verdict: asStrictText(value.verdict),
    });
  }
  return rows;
}

function normalizeRound(value: unknown): RoundView | null {
  if (!isRecord(value)) return null;
  return {
    round: asNumber(value.round),
    llmMove: asStrictText(value.llm),
    opponentMove: asStrictText(value.opp),
    llmPayoff: asNumber(value.llm_payoff),
    opponentPayoff: asNumber(value.opp_payoff),
    cumulativeLlm: asNumber(value.cum_llm),
    cumulativeOpponent: asNumber(value.cum_opp),
  };
}

function normalizeRoundSeries(perRound: RecordValue | null): Record<string, RoundView[]> {
  if (!perRound || !isRecord(perRound.by_opponent)) return {};
  const result: Record<string, RoundView[]> = {};
  for (const [opponent, value] of Object.entries(perRound.by_opponent)) {
    if (!Array.isArray(value)) continue;
    result[opponent] = value
      .map(normalizeRound)
      .filter((row): row is RoundView => row !== null);
  }
  return result;
}

function normalizeTrials(value: unknown): TrialsView | null {
  if (!isRecord(value)) return null;
  const sample = Array.isArray(value.sample)
    ? value.sample.filter(isRecord)
    : [];
  return {
    sample,
    totalRows: asNumber(value.total_rows),
    truncated: typeof value.truncated === "boolean" ? value.truncated : null,
  };
}

function safeStringify(value: unknown): string {
  try {
    const rendered = JSON.stringify(value, null, 2);
    return rendered ?? "Value could not be represented as JSON.";
  } catch {
    return "Value could not be represented as JSON.";
  }
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number")
    return Number.isFinite(value) ? String(value) : "Invalid number";
  if (typeof value === "string" || typeof value === "boolean")
    return String(value);
  const rendered = safeStringify(value);
  return rendered.length > 120 ? `${rendered.slice(0, 117)}…` : rendered;
}

function detailShapeProblems(data: RecordValue): string[] {
  const problems: string[] = [];
  if (data.summary_json != null && !isRecord(data.summary_json))
    problems.push("summary.json has an unsupported shape");
  if (data.summary_md != null && typeof data.summary_md !== "string")
    problems.push("summary.md has an unsupported shape");
  if (
    isRecord(data.summary_json) &&
    "per_opponent" in data.summary_json &&
    !Array.isArray(data.summary_json.per_opponent)
  )
    problems.push("per-opponent results are malformed");
  if (
    isRecord(data.summary_json) &&
    "per_mechanism" in data.summary_json &&
    !Array.isArray(data.summary_json.per_mechanism)
  )
    problems.push("per-mechanism results are malformed");
  if (data.per_round != null && !isRecord(data.per_round))
    problems.push("per-round evidence has an unsupported shape");
  if (
    isRecord(data.per_round) &&
    "by_opponent" in data.per_round &&
    !isRecord(data.per_round.by_opponent)
  )
    problems.push("per-round opponent groups are malformed");
  if (data.trials != null && !isRecord(data.trials))
    problems.push("trial evidence has an unsupported shape");
  if (isRecord(data.trials) && !Array.isArray(data.trials.sample))
    problems.push("trial sample is malformed");
  if (data.headline != null && normalizeHeadline(data.headline) === null)
    problems.push("reported result label is malformed");
  return problems;
}

function statusScope(
  headline: HeadlineView,
  hasOpponentComparison: boolean,
  hasMarkdown: boolean,
  hasJson: boolean,
): { label: string; explanation: string } {
  if (hasOpponentComparison || headline.worstOpponent) {
    return {
      label: "Opponent diagnostic",
      explanation:
        "This compares recorded play against opponents. It is separate from the authored hypothesis conclusion.",
    };
  }
  if (headline.kind === "per_mechanism") {
    return {
      label: "Structured mechanism result",
      explanation:
        "This label summarizes producer-supplied mechanism rows; independent validity is not reported.",
    };
  }
  if (headline.kind === "flat" || hasJson) {
    return {
      label: "Structured result label",
      explanation:
        "This label comes from the structured source. Its claim binding and independent validity are not reported.",
    };
  }
  if (hasMarkdown) {
    return {
      label: "Summary-derived result label",
      explanation:
        "This label was derived upstream from authored text. The original summary remains visible below.",
    };
  }
  return {
    label: "Reported result label",
    explanation: "The source does not report a stronger result scope.",
  };
}

function ResultScopeCard({
  headline,
  hasOpponentComparison,
  hasMarkdown,
  hasJson,
}: {
  headline: HeadlineView;
  hasOpponentComparison: boolean;
  hasMarkdown: boolean;
  hasJson: boolean;
}) {
  const scope = statusScope(
    headline,
    hasOpponentComparison,
    hasMarkdown,
    hasJson,
  );
  return (
    <section
      className="experiment-detail-card experiment-reported-result"
      data-tone={headline.tone}
      data-testid="outcome-headline"
    >
      <p className="experiment-field-label">{scope.label}</p>
      <h2 data-testid={hasOpponentComparison ? "opponent-diagnostic" : undefined}>
        {headline.verdict}
      </h2>
      <p>{scope.explanation}</p>
      {(headline.nOpponents !== null ||
        headline.nMechanisms !== null ||
        headline.totalParseFailures !== null) && (
        <dl className="experiment-result-facts">
          {headline.nOpponents !== null && (
            <div>
              <dt>Diagnostic coverage</dt>
              <dd>
                {displayNumber(headline.nExploited)} of {displayNumber(headline.nOpponents)} opponents crossed the supplied threshold
              </dd>
            </div>
          )}
          {headline.nMechanisms !== null && (
            <div>
              <dt>Mechanism labels</dt>
              <dd>
                {displayNumber(headline.nYes)} of {displayNumber(headline.nMechanisms)} reported YES
              </dd>
            </div>
          )}
          {headline.meanLlmCoopRate !== null && (
            <div>
              <dt>Mean LLM cooperation</dt>
              <dd>{displayRatio(headline.meanLlmCoopRate)}</dd>
            </div>
          )}
          {headline.totalParseFailures !== null && (
            <div>
              <dt>Parse failures</dt>
              <dd>{displayNumber(headline.totalParseFailures)}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}

function UnknownAxes() {
  return (
    <section className="experiment-unknown-axes" aria-label="Result qualification">
      <div>
        <span>Claim binding</span>
        <strong>Unknown</strong>
        <small>Not supplied in this response</small>
      </div>
      <div>
        <span>Evidence validity</span>
        <strong>Unknown</strong>
        <small>No independent validation state</small>
      </div>
      <div>
        <span>Evaluation mode</span>
        <strong>Unknown</strong>
        <small>Do not infer from orchestration fields</small>
      </div>
      <div>
        <span>Application fit</span>
        <strong>Unknown</strong>
        <small>No market is assumed</small>
      </div>
    </section>
  );
}

function authoredSummaryExcerpt(source: string): string {
  const blocks = source
    .split(/\r?\n[\t ]*\r?\n/)
    .filter((block) => block.trim().length > 0);
  return blocks.slice(0, 2).join("\n\n");
}

function AuthoredSummary({ source }: { source: string }) {
  const excerpt = authoredSummaryExcerpt(source);
  return (
    <section
      className="experiment-detail-card experiment-authored-summary"
      data-testid="markdown-summary"
    >
      <div className="experiment-section-heading">
        <div>
          <p className="experiment-field-label">Original source text</p>
          <h2>Authored summary</h2>
        </div>
        <span>summary.md</span>
      </div>
      <p className="experiment-scope-note">
        Exact source excerpt. This authored conclusion is separate from the
        opponent diagnostic and is not independently validated here.
      </p>
      {source.length === 0 ? (
        <p className="experiment-scope-note" data-testid="markdown-summary-empty">
          summary.md is reported present and empty. No conclusion is inferred.
        </p>
      ) : (
        <>
          <div
            className="experiment-markdown experiment-markdown--excerpt"
            data-testid="authored-summary-excerpt"
          >
            <MiniMarkdown source={excerpt} />
          </div>
          <details
            className="experiment-authored-summary__full"
            data-testid="authored-summary-full"
          >
            <summary>Read full summary.md source</summary>
            <div className="experiment-markdown">
              <MiniMarkdown source={source} />
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function opponentGap(row: OpponentView): number | null {
  return row.llmMeanPayoff !== null && row.opponentMeanPayoff !== null
    ? row.opponentMeanPayoff - row.llmMeanPayoff
    : null;
}

function ComparisonSelector({
  rows,
  selected,
  onSelect,
}: {
  rows: OpponentView[];
  selected: string;
  onSelect: (opponent: string) => void;
}) {
  const selectFromKey = (index: number, key: string) => {
    if (key === "Enter" || key === " ") {
      onSelect(rows[index].opponent);
      return true;
    }
    if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(key)) {
      const delta = key === "ArrowRight" || key === "ArrowDown" ? 1 : -1;
      const next = (index + delta + rows.length) % rows.length;
      onSelect(rows[next].opponent);
      return true;
    }
    return false;
  };

  return (
    <div
      className="experiment-opponent-selector"
      role="radiogroup"
      aria-label="Choose an opponent comparison"
      data-testid="opponent-table"
    >
      {rows.map((row, index) => {
        const selectedRow = selected === row.opponent;
        const gap = opponentGap(row);
        return (
          <button
            key={`${row.opponent}-${index}`}
            type="button"
            role="radio"
            aria-checked={selectedRow}
            data-testid={`opp-row-${row.opponent}`}
            onClick={() => onSelect(row.opponent)}
            onKeyDown={(event) => {
              if (selectFromKey(index, event.key)) event.preventDefault();
            }}
          >
            <strong>{row.opponent}</strong>
            <span>
              Payoff gap {displayNumber(gap, 2)} · LLM cooperation {displayRatio(row.llmCoopRate)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function RoundComparisonChart({
  series,
  opponent,
}: {
  series: RoundView[];
  opponent: string;
}) {
  const data = series.map((row, index) => ({
    sourceOrder: index + 1,
    round: row.round ?? index + 1,
    cumulativeLlm: row.cumulativeLlm,
    cumulativeOpponent: row.cumulativeOpponent,
  }));
  const hasCumulative = data.some(
    (row) => row.cumulativeLlm !== null || row.cumulativeOpponent !== null,
  );
  const finalPoint = [...data]
    .reverse()
    .find(
      (row) =>
        row.cumulativeLlm !== null || row.cumulativeOpponent !== null,
    );
  const missingRoundLabels = series.some((row) => row.round === null);

  return (
    <section
      className="experiment-detail-card experiment-round-comparison"
      data-testid="cumulative-chart"
    >
      <div className="experiment-section-heading">
        <div>
          <p className="experiment-field-label">Selected comparison</p>
          <h3>Cumulative payoff against {opponent}</h3>
        </div>
        <span>{series.length} source rows</span>
      </div>
      {!hasCumulative ? (
        <p>No cumulative payoff values were reported for this opponent.</p>
      ) : (
        <figure>
          <figcaption id="experiment-payoff-chart-caption">
            {finalPoint
              ? `Final reported cumulative payoff in the selected series: LLM ${displayNumber(finalPoint.cumulativeLlm, 2)}; opponent ${displayNumber(finalPoint.cumulativeOpponent, 2)}.`
              : "Cumulative payoff values are plotted from the selected series."}
            {missingRoundLabels
              ? " Missing round labels use source-row order on the plot."
              : ""}
          </figcaption>
          <div className="experiment-chart" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 12, right: 12, bottom: 8, left: 0 }}
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
                  dataKey="cumulativeLlm"
                  stroke="#38bdf8"
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                  name="LLM cumulative payoff"
                />
                <Line
                  type="monotone"
                  dataKey="cumulativeOpponent"
                  stroke="#71717a"
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                  name="Opponent cumulative payoff"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </figure>
      )}
      <details className="experiment-data-equivalent" data-testid="round-data">
        <summary>View exact plotted and move values ({series.length})</summary>
        <div className="experiment-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Round</th>
                <th>LLM move</th>
                <th>Opponent move</th>
                <th>LLM payoff</th>
                <th>Opponent payoff</th>
                <th>LLM cumulative</th>
                <th>Opponent cumulative</th>
              </tr>
            </thead>
            <tbody>
              {series.map((row, index) => (
                <tr key={index}>
                  <td>{displayNumber(row.round)}</td>
                  <td>{row.llmMove ?? "Not reported"}</td>
                  <td>{row.opponentMove ?? "Not reported"}</td>
                  <td>{displayNumber(row.llmPayoff)}</td>
                  <td>{displayNumber(row.opponentPayoff)}</td>
                  <td>{displayNumber(row.cumulativeLlm)}</td>
                  <td>{displayNumber(row.cumulativeOpponent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function OpponentComparison({
  rows,
  seriesByOpponent,
  selected,
  onSelect,
  threshold,
}: {
  rows: OpponentView[];
  seriesByOpponent: Record<string, RoundView[]>;
  selected: string;
  onSelect: (opponent: string) => void;
  threshold: number | null;
}) {
  const selectedRow = rows.find((row) => row.opponent === selected) ?? null;
  const series = seriesByOpponent[selected] ?? [];
  const gap = selectedRow ? opponentGap(selectedRow) : null;
  const thresholdReading =
    gap === null || threshold === null
      ? "Diagnostic threshold comparison unavailable"
      : gap > threshold
        ? `Payoff gap ${gap.toFixed(2)} is above the supplied ${threshold} diagnostic threshold`
        : `Payoff gap ${gap.toFixed(2)} does not exceed the supplied ${threshold} diagnostic threshold`;

  return (
    <section className="experiment-comparison-workspace" aria-labelledby="opponent-comparison-title">
      <div className="experiment-section-heading">
        <div>
          <p className="experiment-field-label">Evidence comparison</p>
          <h2 id="opponent-comparison-title">Choose one opponent</h2>
        </div>
        <span aria-live="polite">Selected: {selected}</span>
      </div>
      <ComparisonSelector rows={rows} selected={selected} onSelect={onSelect} />
      <div className="experiment-selected-opponent" data-testid="selected-comparison">
        <p>{thresholdReading}. This is an opponent diagnostic, not the authored hypothesis conclusion.</p>
        {selectedRow ? (
          <dl>
            <div><dt>LLM mean payoff</dt><dd>{displayNumber(selectedRow.llmMeanPayoff, 2)}</dd></div>
            <div><dt>Opponent mean payoff</dt><dd>{displayNumber(selectedRow.opponentMeanPayoff, 2)}</dd></div>
            <div><dt>LLM cooperation</dt><dd>{displayRatio(selectedRow.llmCoopRate)}</dd></div>
            <div><dt>Opponent cooperation</dt><dd>{displayRatio(selectedRow.opponentCoopRate)}</dd></div>
            <div><dt>Rounds</dt><dd>{displayNumber(selectedRow.nRounds)}</dd></div>
            <div><dt>LLM parse failures</dt><dd>{displayNumber(selectedRow.parseFailures)}</dd></div>
            <div><dt>First LLM defection</dt><dd>{displayNumber(selectedRow.firstDefectionLlm)}</dd></div>
            <div><dt>Recorded wall seconds</dt><dd>{displayNumber(selectedRow.wallClockSeconds)}</dd></div>
          </dl>
        ) : (
          <p>No summary row was reported for this round-data opponent.</p>
        )}
      </div>
      {series.length > 0 ? (
        <RoundComparisonChart series={series} opponent={selected} />
      ) : (
        <div className="experiment-detail-card" data-testid="comparison-no-rounds">
          No per-round series was reported for {selected}. The summary values above remain available.
        </div>
      )}
    </section>
  );
}

function ResultChip({ verdict }: { verdict: string | null }) {
  const normalized = verdict?.trim().toUpperCase();
  const tone = normalized === "YES" ? "ok" : normalized === "NO" ? "bad" : "unknown";
  return (
    <span className="experiment-mechanism-result" data-tone={tone}>
      {verdict ?? "Not reported"}
    </span>
  );
}

function MechanismComparison({ rows }: { rows: MechanismView[] }) {
  return (
    <section
      className="experiment-detail-card"
      data-testid="mechanism-table"
      aria-labelledby="mechanism-results-title"
    >
      <div className="experiment-section-heading">
        <div>
          <p className="experiment-field-label">Structured source rows</p>
          <h2 id="mechanism-results-title">Mechanism comparison</h2>
        </div>
        <span>{rows.length} reported</span>
      </div>
      <div className="experiment-mechanism-list">
        {rows.map((row, index) => (
          <article key={`${row.mechanism}-${index}`} data-testid={`mech-row-${row.mechanism}`}>
            <div>
              <strong>{row.mechanism}</strong>
              <ResultChip verdict={row.verdict} />
            </div>
            <dl>
              <div><dt>truthful fraction</dt><dd>{displayNumber(row.truthfulFraction)}</dd></div>
              <div><dt>mean efficiency</dt><dd>{displayNumber(row.meanEfficiency)}</dd></div>
              <div><dt>mean revenue</dt><dd>{displayNumber(row.meanRevenue)}</dd></div>
              <div><dt>mean signed residual</dt><dd>{displayNumber(row.meanSignedResidual)}</dd></div>
              <div><dt>parse failure rate</dt><dd>{displayNumber(row.parseFailureRate)}</dd></div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function ScalarFields({ summary }: { summary: RecordValue }) {
  const entries = Object.entries(summary).filter(
    ([key, value]) =>
      key !== "verdict" &&
      (typeof value === "string" ||
        typeof value === "boolean" ||
        (typeof value === "number" && Number.isFinite(value))),
  );
  if (entries.length === 0) return null;
  return (
    <details className="experiment-evidence-disclosure" data-testid="json-header">
      <summary>Producer scalar fields ({entries.length})</summary>
      <p>
        Values are displayed without inferring units or converting thresholds from their field names.
      </p>
      <dl className="experiment-raw-fields">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replace(/_/g, " ")}</dt>
            <dd>{formatCell(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function TrialsSample({ trials }: { trials: TrialsView }) {
  const columns = trials.sample.length
    ? Array.from(
        trials.sample.reduce((set, row) => {
          Object.keys(row).forEach((key) => set.add(key));
          return set;
        }, new Set<string>()),
      ).slice(0, 8)
    : [];
  return (
    <details className="experiment-evidence-disclosure" data-testid="trials-sample">
      <summary>
        Trial sample · {trials.sample.length} of {displayNumber(trials.totalRows)}
        {trials.truncated === true ? " · truncated" : ""}
      </summary>
      {columns.length === 0 ? (
        <p>No readable trial rows were present.</p>
      ) : (
        <div className="experiment-table-scroll">
          <table>
            <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {trials.sample.map((row, index) => (
                <tr key={index}>{columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function SourceInventory({ data }: { data: RecordValue }) {
  const state = (value: unknown) =>
    value === true ? "Reported present" : value === false ? "Reported absent" : "Unknown";
  return (
    <section className="experiment-detail-card experiment-source-inventory">
      <p className="experiment-field-label">Evidence context</p>
      <h2>Source inventory</h2>
      <dl>
        <div><dt>Results directory</dt><dd>{state(data.has_results_dir)}</dd></div>
        <div><dt>Result files</dt><dd>{displayNumber(asNumber(data.n_results_files))}</dd></div>
        <div><dt>JSON summary</dt><dd>{state(data.has_summary_json)}</dd></div>
        <div><dt>Authored summary</dt><dd>{state(data.has_summary_md)}</dd></div>
        <div><dt>Round data</dt><dd>{state(data.has_per_round)}</dd></div>
        <div><dt>Trial sample</dt><dd>{state(data.has_trials)}</dd></div>
        <div><dt>Result as-of</dt><dd>Unknown</dd></div>
      </dl>
    </section>
  );
}

export default function ExperimentDetail({ initial, expIdOverride }: Props) {
  const params = useParams<{ expId: string }>();
  const location = useLocation();
  const expId = expIdOverride ?? params.expId ?? "";
  const [data, setData] = useState<ExperimentDetailT | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined || !expId) return;
    let active = true;
    setData(null);
    setError(null);
    setSelected(null);
    getExperimentDetail(expId)
      .then((response) => {
        if (active) setData(response);
      })
      .catch((reason) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
    };
  }, [expId, initial, requestVersion]);

  const record = data && isRecord(data) ? (data as unknown as RecordValue) : null;
  const summary = record && isRecord(record.summary_json) ? record.summary_json : null;
  const authoredSummary = record ? asStrictText(record.summary_md) : null;
  const perRound = record && isRecord(record.per_round) ? record.per_round : null;
  const headline = record ? normalizeHeadline(record.headline) : null;
  const opponents = useMemo(() => normalizeOpponents(summary), [summary]);
  const mechanisms = useMemo(() => normalizeMechanisms(summary), [summary]);
  const seriesByOpponent = useMemo(() => normalizeRoundSeries(perRound), [perRound]);
  const trials = useMemo(() => normalizeTrials(record?.trials), [record?.trials]);
  const problems = record ? detailShapeProblems(record) : [];

  const comparisonNames = useMemo(() => {
    const names = new Set(opponents.map((row) => row.opponent));
    Object.keys(seriesByOpponent).forEach((name) => names.add(name));
    return [...names];
  }, [opponents, seriesByOpponent]);
  const comparisonRows = useMemo(
    () =>
      comparisonNames.map(
        (name) =>
          opponents.find((row) => row.opponent === name) ?? {
            opponent: name,
            nRounds: null,
            llmCoopRate: null,
            opponentCoopRate: null,
            llmMeanPayoff: null,
            opponentMeanPayoff: null,
            firstDefectionLlm: null,
            parseFailures: null,
            wallClockSeconds: null,
          },
      ),
    [comparisonNames, opponents],
  );
  const focusedOpponent =
    selected && comparisonNames.includes(selected)
      ? selected
      : headline?.worstOpponent && comparisonNames.includes(headline.worstOpponent)
        ? headline.worstOpponent
        : comparisonNames[0] ?? null;

  const state = isRecord(location.state) ? location.state : null;
  const requestedReturn = asStrictText(state?.experimentsReturnTo);
  const returnTo =
    requestedReturn?.startsWith("/experiments") ? requestedReturn : "/experiments";
  const sourceId = record ? asText(record.id) ?? expId : expId;
  const title = record ? asText(record.title) : null;
  const files = record ? asNumber(record.n_results_files) : null;
  const noResultsDirectory = record?.has_results_dir === false;
  const emptyResultsDirectory =
    record?.has_results_dir === true &&
    files === 0 &&
    record.has_summary_json !== true &&
    record.has_summary_md !== true &&
    record.has_per_round !== true &&
    record.has_trials !== true;
  const unreadableResults =
    record?.has_results_dir === true &&
    files !== null &&
    files > 0 &&
    !summary &&
    authoredSummary === null &&
    !perRound &&
    !trials;
  const summaryJsonError = record ? asStrictText(record.summary_json_error) : null;
  const summaryMarkdownError = record ? asStrictText(record.summary_md_error) : null;

  return (
    <div className="page-full experiment-detail-page" data-testid="experiment-detail-page">
      <header className="experiment-detail-header">
        <Link
          to={returnTo}
          state={{ focusExperimentId: sourceId }}
          className="experiment-back-link"
        >
          ← Experiments
        </Link>
        <p className="experiments-eyebrow">Recorded evaluation source</p>
        <h1>{title || sourceId || "Experiment detail"}</h1>
        <p className="experiment-detail-id">{sourceId || "Source id unavailable"}</p>
      </header>

      {error && (
        <div className="experiments-state experiments-state--error" role="alert">
          <strong>Experiment detail read failed.</strong>
          <span>{error}. No empty or adverse result is inferred.</span>
          <button type="button" onClick={() => setRequestVersion((value) => value + 1)}>
            Retry read
          </button>
        </div>
      )}
      {!data && !error && (
        <div className="experiments-state" role="status">Reading experiment evidence…</div>
      )}

      {record && (
        <>
          <UnknownAxes />

          {noResultsDirectory && (
            <div className="experiments-state experiments-state--warning" data-testid="detail-no-results">
              <strong>Results directory reported absent.</strong>
              <span>This source has no reported result inventory. That does not establish a zero or a scientific conclusion.</span>
            </div>
          )}
          {emptyResultsDirectory && (
            <div className="experiments-state experiments-state--warning" data-testid="detail-empty-results">
              <strong>Results directory reported present and empty.</strong>
              <span>No run status or conclusion is inferred from the empty directory.</span>
            </div>
          )}
          {unreadableResults && (
            <div className="experiments-state experiments-state--warning" data-testid="detail-unreadable-results">
              <strong>Result files are reported, but no supported evidence shape was readable.</strong>
              <span>The state remains unknown rather than zero, empty or NO.</span>
            </div>
          )}

          <div className="experiment-detail-layout">
            <main className="experiment-detail-main">
              {headline && (
                <ResultScopeCard
                  headline={headline}
                  hasOpponentComparison={comparisonRows.length > 0}
                  hasMarkdown={authoredSummary !== null}
                  hasJson={summary !== null}
                />
              )}
              {focusedOpponent && comparisonRows.length > 0 && (
                <OpponentComparison
                  rows={comparisonRows}
                  seriesByOpponent={seriesByOpponent}
                  selected={focusedOpponent}
                  onSelect={setSelected}
                  threshold={headline?.exploitThreshold ?? null}
                />
              )}
              {mechanisms.length > 0 && <MechanismComparison rows={mechanisms} />}
              {!headline &&
                authoredSummary === null &&
                comparisonRows.length === 0 &&
                mechanisms.length === 0 &&
                !noResultsDirectory &&
                !emptyResultsDirectory &&
                !unreadableResults && (
                  <div className="experiments-state" data-testid="detail-no-readable-summary">
                    No readable result label or comparison was reported. Source inventory remains available.
                  </div>
                )}
            </main>

            <aside className="experiment-evidence-panel" aria-label="Experiment evidence context">
              {authoredSummary !== null && <AuthoredSummary source={authoredSummary} />}
              <SourceInventory data={record} />

              {(summaryJsonError || summaryMarkdownError) && (
                <div className="experiments-inline-warning" role="status">
                  <strong>Source read errors</strong>
                  {summaryJsonError && <span>summary.json: {summaryJsonError}</span>}
                  {summaryMarkdownError && <span>summary.md: {summaryMarkdownError}</span>}
                </div>
              )}

              {problems.length > 0 && (
                <div className="experiments-inline-warning" role="status" data-testid="detail-malformed">
                  <strong>Malformed evidence retained</strong>
                  <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
                  <span>Readable evidence remains visible; malformed fields are not converted to a result.</span>
                </div>
              )}

              {summary && <ScalarFields summary={summary} />}
              {trials && <TrialsSample trials={trials} />}

              {perRound && (
                <div className="experiment-detail-card experiment-linkage-note" data-testid={perRound.round_inspector_linkage === false ? "linkage-absent" : "linkage-state"}>
                  <p className="experiment-field-label">Round provenance</p>
                  {perRound.round_inspector_linkage === false ? (
                    <p>
                      Round → inspector linkage is not available. These rows carry no reported <code>task_id</code>, so no call-chain link is invented.
                    </p>
                  ) : perRound.round_inspector_linkage === true ? (
                    <p>Round-to-inspector linkage is reported available by the source.</p>
                  ) : (
                    <p>Round-to-inspector linkage is unknown.</p>
                  )}
                  <p>
                    {displayNumber(asNumber(perRound.total_rows))} total rows reported
                    {perRound.truncated === true ? " · series truncated at the source scan cap" : ""}.
                  </p>
                </div>
              )}

              {summary && (
                <details className="experiment-evidence-disclosure">
                  <summary>Original summary.json payload</summary>
                  <pre>{safeStringify(summary)}</pre>
                </details>
              )}

              <details className="experiment-evidence-disclosure">
                <summary>Original detail response</summary>
                <pre>{safeStringify(record)}</pre>
              </details>
            </aside>
          </div>
        </>
      )}

      <p className="experiments-page__boundary">
        This route reads recorded evidence only. It does not validate a claim,
        run a model or experiment, select a market, or submit a ruling.
      </p>
    </div>
  );
}
