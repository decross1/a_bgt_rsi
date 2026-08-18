// FrontierReviews — the frontier tier (D-061) made visible on /model-io.
//
// Claude = methods reviewer, Codex = novelty reviewer (plus refine-cycle /
// improve-loop reviewer roles); every CLI invocation lands in
// run_state/frontier_calls.jsonl, and until now NONE of it reached the
// dashboard. The owner armed the promotion screen (NARA_FRONTIER_SCREEN=1),
// so when it fires the tier must be visible: one line per call — vendor
// badge, role, verdict chip, candidate id, age, duration — with the
// reasoning digest behind a click.
//
// The load-bearing honesty rule (the 2026-08-16 lesson): a DEAD VENDOR MUST
// NEVER LOOK LIKE A QUIET REVIEWER. On 08-16 the codex CLI returned HTTP 400
// for ~6 hours and every consumer read the silence as "inconclusive". The
// backend derives per-vendor consecutive-nonzero-exit streaks from the same
// ledger tail (loop_health's detect_frontier_vendor_down shape, threshold
// 3); this component only passes the verdicts through — rows of a down
// vendor carry a loud amber "VENDOR DOWN?" chip, and nonzero exits show
// their code in rose.
//
// Everything is backend-passthrough: a missing field renders "—", never a
// guess; a failed poll keeps the last rows and says STALE; an empty ledger
// says so honestly (the screen fires on promotion candidates only).
//
// Local fetcher + types on the ModelIO.tsx precedent (getRuntimeActivity):
// this build owns only this NEW file plus its one-line mount, so nothing
// widens the shared api/ clients.
import { useEffect, useState } from "react";
import Card from "../design/Card";
import { fmt } from "../format";

// ─── wire types (passthrough rows — fields may be absent on old rows) ───

interface FrontierCall {
  timestamp?: string | null;
  vendor?: string | null;
  cli_version?: string | null;
  role?: string | null;
  candidate_id?: string | null;
  verdict?: string | null;
  reasoning_digest?: string | null;
  duration_ms?: number | null;
  exit_code?: number | null;
  prompt_sha256?: string | null;
}

interface FrontierSummary {
  last_call_ts: string | null;
  calls_24h: number;
  consecutive_nonzero_exit_by_vendor: Record<string, number>;
  vendors_down: string[];
  down_streak_threshold: number;
}

interface FrontierCallsResponse {
  available: boolean;
  calls: FrontierCall[];
  rows_in_window: number;
  summary: FrontierSummary;
  window_bytes: number;
  window_truncated: boolean;
  generated_at: string;
}

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

async function getFrontierCalls(limit = 30): Promise<FrontierCallsResponse> {
  const resp = await fetch(`${API_BASE}/api/frontier_calls?limit=${limit}`);
  if (!resp.ok) throw new Error(`frontier_calls ${resp.status}`);
  return (await resp.json()) as FrontierCallsResponse;
}

// ─── tones (LOCAL additive maps, per the roles.ts additive-only contract:
//     NEW ink only — no existing badge family is retinted, and lookups are
//     own-key only so a producer string named "toString" can never leak a
//     function into className) ────────────────────────────────────────────

const TONE_QUIET = "bg-zinc-800 text-zinc-400";

// Vendor tones: claude rides the fuchsia family roles.ts already gives the
// `anthropic` backend; codex gets teal — distinct from claude AND from the
// gemma-emerald / qwen-sky families, so a frontier badge never reads as a
// local model.
const VENDOR_TONE: Record<string, string> = {
  claude: "bg-fuchsia-950 text-fuchsia-300",
  codex: "bg-teal-950 text-teal-300",
};

// Verdict chips: veto rose, pass emerald, inconclusive zinc. An UNKNOWN
// verdict string renders raw in quiet zinc (never filtered); null renders
// as an honest "—" outside this map.
const VERDICT_TONE: Record<string, string> = {
  veto: "bg-rose-950 text-rose-300",
  pass: "bg-emerald-950 text-emerald-300",
  inconclusive: TONE_QUIET,
};

function toneOf(map: Record<string, string>, key: unknown): string {
  if (typeof key !== "string" || key.trim() === "") return TONE_QUIET;
  return Object.prototype.hasOwnProperty.call(map, key)
    ? map[key]
    : TONE_QUIET;
}

// Compact age ("3m") from an ISO timestamp — the ModelIO.tsx ageOf idiom,
// copied (not imported) to avoid a route↔component import cycle. The nowMs
// parameter exists so tests never race the clock.
export function frontierAge(
  ts: string | null | undefined,
  nowMs: number = Date.now(),
): string {
  if (!ts) return "—";
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

// ─── one call row ────────────────────────────────────────────────────────

function FrontierRow({
  call,
  down,
  streak,
}: {
  call: FrontierCall;
  down: boolean;
  streak: number | null;
}) {
  const [open, setOpen] = useState(false);
  const digest =
    typeof call.reasoning_digest === "string" &&
    call.reasoning_digest.trim() !== ""
      ? call.reasoning_digest
      : null;
  const verdict = typeof call.verdict === "string" ? call.verdict : null;
  const exitCode =
    typeof call.exit_code === "number" ? call.exit_code : null;
  const toggle = () => {
    if (digest != null) setOpen((o) => !o);
  };
  return (
    <div className="border-b border-zinc-800/60 last:border-0">
      <div
        role={digest != null ? "button" : undefined}
        tabIndex={digest != null ? 0 : undefined}
        data-testid="frontier-row"
        className={`flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-xs ${
          digest != null ? "cursor-pointer hover:bg-zinc-900/50" : ""
        }`}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
      >
        <span
          className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${toneOf(
            VENDOR_TONE,
            call.vendor,
          )}`}
          data-testid="vendor-badge"
          title={call.cli_version ?? undefined}
        >
          {call.vendor ?? "—"}
        </span>
        {down && (
          <span
            className="rounded bg-amber-950 px-1.5 py-0.5 font-mono text-[10px] text-amber-300"
            data-testid="vendor-down-chip"
            title={`the last ${streak ?? "?"} ${
              call.vendor ?? "?"
            } calls all exited nonzero — a dead CLI can masquerade as an inconclusive reviewer (2026-08-16 lesson)`}
          >
            VENDOR DOWN?
          </span>
        )}
        <span className="font-mono text-zinc-300">{call.role ?? "—"}</span>
        {verdict != null ? (
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${toneOf(
              VERDICT_TONE,
              verdict,
            )}`}
            data-testid="verdict-chip"
          >
            {verdict}
          </span>
        ) : (
          <span className="font-mono text-zinc-600" data-testid="verdict-null">
            —
          </span>
        )}
        {call.candidate_id && (
          <span
            className="truncate font-mono text-[10px] text-zinc-500"
            style={{ maxWidth: "14rem" }}
            data-testid="candidate-id"
            title={call.candidate_id}
          >
            {call.candidate_id}
          </span>
        )}
        {exitCode != null && exitCode !== 0 && (
          <span
            className="rounded bg-rose-950 px-1.5 py-0.5 font-mono text-[10px] text-rose-300"
            data-testid="exit-chip"
            title="nonzero CLI exit — outage evidence, not a review"
          >
            exit {exitCode}
          </span>
        )}
        {digest != null && (
          <span aria-hidden className="text-zinc-600">
            {open ? "▾" : "▸"}
          </span>
        )}
        <span className="ml-auto font-mono tabular-nums text-zinc-400">
          {call.duration_ms != null ? `${fmt(call.duration_ms, 0)}ms` : "—"}
        </span>
        <span
          className="font-mono text-zinc-600"
          title={call.timestamp ?? ""}
        >
          {frontierAge(call.timestamp)}
        </span>
      </div>
      {open && digest != null && (
        <div
          className="mb-1.5 whitespace-pre-wrap rounded border border-zinc-800/60 bg-zinc-950/40 p-1.5 text-xs text-zinc-300"
          data-testid="digest-body"
        >
          {digest}
        </div>
      )}
    </div>
  );
}

// ─── the section ─────────────────────────────────────────────────────────

export default function FrontierReviews({
  pollMs = 15000,
}: {
  pollMs?: number;
}) {
  const [data, setData] = useState<FrontierCallsResponse | null>(null);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let on = true;
    const load = () => {
      getFrontierCalls()
        .then((r) => {
          if (!on) return;
          setData(r);
          setStale(false);
        })
        .catch(() => {
          // Keep the last rows; say they are stale rather than blanking.
          if (on) setStale(true);
        });
    };
    load();
    const id = setInterval(load, pollMs);
    return () => {
      on = false;
      clearInterval(id);
    };
  }, [pollMs]);

  // Defensive against a version-skewed backend answering a foreign body.
  const calls = Array.isArray(data?.calls) ? data.calls : [];
  const summary = data?.summary;
  const vendorsDown = Array.isArray(summary?.vendors_down)
    ? summary.vendors_down
    : [];
  const streaks = summary?.consecutive_nonzero_exit_by_vendor ?? {};
  const streakOf = (vendor: unknown): number | null =>
    typeof vendor === "string" &&
    Object.prototype.hasOwnProperty.call(streaks, vendor) &&
    typeof streaks[vendor] === "number"
      ? streaks[vendor]
      : null;

  return (
    <Card
      className="mt-3"
      title="Frontier reviews"
      testId="frontier-reviews"
    >
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-[11px] text-zinc-500">
          the frontier tier (D-061: claude = methods, codex = novelty —
          falsifiers only) off{" "}
          <span className="font-mono">run_state/frontier_calls.jsonl</span>
        </span>
        {data != null && summary != null && (
          <span
            className="font-mono text-[11px] text-zinc-600"
            data-testid="frontier-summary"
          >
            {summary.calls_24h} calls/24h · last{" "}
            {frontierAge(summary.last_call_ts)}
          </span>
        )}
        {stale && (
          <span className="text-[11px] text-amber-400/80">
            poll failed — showing the last loaded rows; live state UNKNOWN.
          </span>
        )}
      </div>

      {data == null ? (
        <div className="text-xs text-zinc-500">
          /api/frontier_calls not loaded — frontier tier state UNKNOWN, not
          idle.
        </div>
      ) : !data.available ? (
        <div className="text-xs text-zinc-500" data-testid="frontier-absent">
          frontier ledger absent (
          <span className="font-mono">run_state/frontier_calls.jsonl</span>)
          — no frontier call has ever been logged here.
        </div>
      ) : calls.length === 0 ? (
        <div className="text-xs text-zinc-500" data-testid="frontier-empty">
          no frontier calls in the recent tail — the promotion screen
          (NARA_FRONTIER_SCREEN) fires on promotion candidates only, so an
          empty tail between candidates is normal, not an outage.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          {calls.map((c, i) => (
            <FrontierRow
              key={`${c.timestamp ?? "row"}-${i}`}
              call={c}
              down={
                typeof c.vendor === "string" &&
                vendorsDown.includes(c.vendor)
              }
              streak={streakOf(c.vendor)}
            />
          ))}
        </div>
      )}

      {/* The bound, stated: rows AND the derived summary come from the same
          bounded ledger tail. */}
      {data != null && data.available && (
        <div
          className="mt-1.5 text-[11px] text-zinc-600"
          data-testid="frontier-footnote"
        >
          bounded tail — newest {calls.length} of {data.rows_in_window} rows
          in the last {data.window_bytes} bytes
          {data.window_truncated
            ? "; older rows exist beyond the window (counts are floors)"
            : ""}
          . verdicts are review-layer fields — null on plain CLI-invocation
          rows.
        </div>
      )}
    </Card>
  );
}
