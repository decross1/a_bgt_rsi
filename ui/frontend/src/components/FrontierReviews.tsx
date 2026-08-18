// FrontierReviews — what the frontier tier (D-061) actually SAID, on
// /model-io.
//
// Owner rejection 2026-08-18 of the first cut: it listed CLI invocations
// (vendor/role/exit/latency) with no content — "i can't even see what their
// debating issue was". The panel now reads the SUBSTANCE seam
// (/api/frontier_reviews): a merged newest-first feed of typed events —
// screen cards (cluster + claim head + verdict + BOTH roles' full reasoning
// behind a 2-line clamp + the D-061 cross-run summary), agenda cards
// (topic + rationale), refine cards (round + digest) — under a per-vendor
// health strip with DECODED failures. The old raw invocation table survives
// verbatim behind a "plumbing" disclosure, default closed; its poll only
// runs while the disclosure is open.
//
// The load-bearing honesty rules keep holding:
//  - a DEAD VENDOR MUST NEVER LOOK LIKE A QUIET REVIEWER (2026-08-16): the
//    health strip decodes the backend's exit streaks per vendor — 127 reads
//    "binary not found (PATH)…", not a mystery row;
//  - everything is backend-passthrough: a missing field renders "—" or is
//    simply absent (claim_head is omitted server-side, never fabricated);
//  - a failed poll keeps the last feed and says STALE.
//
// PERF seams kept from the 2026-08-18 /model-io consolidation: pollhub
// scheduling at a 45s cadence, fetchWithDeadline (a hung request can never
// wedge the in-flight guard), initialDelayMs mount stagger, `paused` prop.
import { useRef, useState } from "react";
import Card from "../design/Card";
import { fetchWithDeadline } from "../api/modelIO";
import { usePolled } from "../api/pollhub";
import { useNow } from "../time";
import { fmt } from "../format";
import { ClampedText } from "./payload/bits";

// ─── wire types ──────────────────────────────────────────────────────────

interface RoleReview {
  verdict?: string | null;
  reasoning?: string | null;
  vendor?: string | null;
  closest_prior_work?: string | null;
  cross_run?: RoleReview;
}

interface ReviewEvent {
  type: "screen" | "agenda" | "refine" | string;
  ts?: string | null;
  // screen
  cluster_id?: string | null;
  evidence_level?: string | null;
  verdict?: string | null;
  seconds?: number | null;
  roles?: Record<string, RoleReview>;
  cross_run_summary?: string;
  claim_head?: string;
  // agenda
  proposal_id?: string | null;
  proposed_by?: string | null;
  topic?: string | null;
  rationale?: string | null;
  // refine
  round?: number | null;
  refined_claim_head?: string | null;
  feedback_digest?: string | null;
}

interface VendorHealth {
  calls_24h: number;
  last_ok_ts: string | null;
  last_ok_age_s: number | null;
  consecutive_failures: number;
  last_error: { ts?: string | null; exit_code: number; decoded: string } | null;
}

interface FrontierReviewsResponse {
  available: { screen: boolean; agenda: boolean; calls: boolean };
  events: ReviewEvent[];
  events_in_window: number;
  health: Record<string, VendorHealth>;
  ledger_join: { ok: boolean; error: string | null };
  windows: Record<string, { bytes: number; truncated: boolean }>;
  generated_at: string;
}

// Plumbing wire types (the raw invocation table, unchanged).
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

// generated_at is stripped so the pollhub's change detection compares the
// payload itself — an unchanged compose re-renders nothing.
type ReviewsData = Omit<FrontierReviewsResponse, "generated_at">;
type FrontierData = Omit<FrontierCallsResponse, "generated_at">;

const FRONTIER_POLL_MS = 45_000;

async function getFrontierReviews(limit = 20): Promise<ReviewsData> {
  const resp = await fetchWithDeadline(
    `${API_BASE}/api/frontier_reviews?limit=${limit}`,
  );
  if (!resp.ok) throw new Error(`frontier_reviews ${resp.status}`);
  const { generated_at: _g, ...rest } =
    (await resp.json()) as FrontierReviewsResponse;
  return rest;
}

async function getFrontierCalls(limit = 30): Promise<FrontierData> {
  const resp = await fetchWithDeadline(
    `${API_BASE}/api/frontier_calls?limit=${limit}`,
  );
  if (!resp.ok) throw new Error(`frontier_calls ${resp.status}`);
  const { generated_at: _g, ...rest } =
    (await resp.json()) as FrontierCallsResponse;
  return rest;
}

// ─── tones (LOCAL additive maps; own-key lookups only) ──────────────────

const TONE_QUIET = "bg-zinc-800 text-zinc-400";

const VENDOR_TONE: Record<string, string> = {
  claude: "bg-fuchsia-950 text-fuchsia-300",
  codex: "bg-teal-950 text-teal-300",
};

// Plumbing rows keep their original verdict tones (content unchanged).
const VERDICT_TONE: Record<string, string> = {
  veto: "bg-rose-950 text-rose-300",
  pass: "bg-emerald-950 text-emerald-300",
  inconclusive: TONE_QUIET,
};

// Feed cards: inconclusive is AMBER here — in the substance view "the tier
// could not commit" is a state worth noticing, not background noise.
const CARD_VERDICT_TONE: Record<string, string> = {
  veto: "bg-rose-950 text-rose-300",
  pass: "bg-emerald-950 text-emerald-300",
  inconclusive: "bg-amber-950 text-amber-300",
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

// ─── the health strip (one line per vendor, decoded) ─────────────────────

function healthTone(failures: number, downThreshold = 3): string {
  if (failures >= downThreshold) return "text-rose-400";
  if (failures > 0) return "text-amber-300";
  return "text-emerald-400";
}

function HealthStrip({ health, nowMs }: { health: Record<string, VendorHealth>; nowMs?: number }) {
  const vendors = Object.keys(health).sort();
  if (vendors.length === 0) {
    return (
      <div className="text-[11px] text-zinc-500" data-testid="health-empty">
        no frontier CLI calls in the tail window — vendor health UNKNOWN.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5" data-testid="frontier-health">
      {vendors.map((vendor) => {
        const h = health[vendor];
        const failing = h.consecutive_failures > 0;
        const tone = healthTone(h.consecutive_failures);
        return (
          <div
            key={vendor}
            className="flex flex-wrap items-baseline gap-x-2 text-[11px]"
            data-testid="vendor-health"
          >
            <span aria-hidden className={tone}>
              ●
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${toneOf(
                VENDOR_TONE,
                vendor,
              )}`}
            >
              {vendor}
            </span>
            <span className="font-mono text-zinc-500">
              {h.calls_24h} calls/24h · last ok{" "}
              {h.last_ok_ts != null ? frontierAge(h.last_ok_ts, nowMs) : "never"}
            </span>
            {failing && h.last_error != null && (
              <span className={tone} data-testid="health-decoded">
                {h.consecutive_failures} consecutive failure
                {h.consecutive_failures === 1 ? "" : "s"} —{" "}
                {h.last_error.decoded}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── feed cards ──────────────────────────────────────────────────────────

const CARD_CLS =
  "rounded border border-zinc-800/60 bg-zinc-950/40 p-2 text-xs";
const TYPE_CHIP_CLS =
  "rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500";

// Fixed role order (D-061: claude = methods, codex = novelty), any extra
// role keys the backend ever adds render after, never dropped.
function roleOrder(roles: Record<string, RoleReview>): string[] {
  const known = ["methods", "novelty"].filter((r) => r in roles);
  const rest = Object.keys(roles).filter((r) => !known.includes(r));
  return [...known, ...rest];
}

function ScreenCard({ ev, nowMs }: { ev: ReviewEvent; nowMs: number }) {
  const roles = ev.roles ?? {};
  return (
    <div className={CARD_CLS} data-testid="screen-card">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={TYPE_CHIP_CLS}>screen</span>
        <span className="font-mono text-zinc-300">
          {ev.cluster_id ?? "—"}
        </span>
        {ev.evidence_level != null && (
          <span className={TYPE_CHIP_CLS}>{ev.evidence_level}</span>
        )}
        {typeof ev.verdict === "string" ? (
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${toneOf(
              CARD_VERDICT_TONE,
              ev.verdict,
            )}`}
            data-testid="screen-verdict-chip"
          >
            {ev.verdict}
          </span>
        ) : (
          <span className="font-mono text-zinc-600">—</span>
        )}
        <span
          className="ml-auto font-mono text-[10px] text-zinc-600"
          title={ev.ts ?? ""}
        >
          {frontierAge(ev.ts, nowMs)}
        </span>
      </div>
      {ev.claim_head != null && (
        <div
          className="mt-1 italic text-zinc-400"
          data-testid="screen-claim-head"
        >
          “{ev.claim_head}”
        </div>
      )}
      <div className="mt-1.5 flex flex-col gap-1.5">
        {roleOrder(roles).map((name) => {
          const role = roles[name];
          const reasoning =
            typeof role.reasoning === "string" && role.reasoning.trim() !== ""
              ? role.reasoning
              : null;
          return (
            <div key={name} data-testid="screen-role">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-zinc-400">{name}</span>
                <span
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${toneOf(
                    VENDOR_TONE,
                    role.vendor,
                  )}`}
                >
                  {role.vendor ?? "—"}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${toneOf(
                    CARD_VERDICT_TONE,
                    role.verdict,
                  )}`}
                >
                  {role.verdict ?? "—"}
                </span>
              </div>
              {/* The substance: full reasoning, clamped to 2 lines with the
                  payload family's show-more affordance (text always in the
                  DOM — the clamp is visual only). */}
              {reasoning != null ? (
                <ClampedText text={reasoning} />
              ) : (
                <div className="text-zinc-600">no reasoning captured</div>
              )}
            </div>
          );
        })}
      </div>
      {ev.cross_run_summary != null && (
        <div
          className="mt-1.5 text-[11px] text-amber-300/90"
          data-testid="cross-run-summary"
        >
          ↪ {ev.cross_run_summary}
        </div>
      )}
    </div>
  );
}

function AgendaCard({ ev, nowMs }: { ev: ReviewEvent; nowMs: number }) {
  return (
    <div className={CARD_CLS} data-testid="agenda-card">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={TYPE_CHIP_CLS}>agenda</span>
        <span className="font-mono text-[10px] text-zinc-500">
          {ev.proposed_by ?? "—"}
        </span>
        <span
          className="ml-auto font-mono text-[10px] text-zinc-600"
          title={ev.ts ?? ""}
        >
          {frontierAge(ev.ts, nowMs)}
        </span>
      </div>
      <div className="mt-1 text-zinc-200">{ev.topic ?? "—"}</div>
      {typeof ev.rationale === "string" && ev.rationale.trim() !== "" && (
        <ClampedText text={ev.rationale} />
      )}
    </div>
  );
}

function RefineCard({ ev, nowMs }: { ev: ReviewEvent; nowMs: number }) {
  return (
    <div className={CARD_CLS} data-testid="refine-card">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={TYPE_CHIP_CLS}>refine</span>
        <span className="font-mono text-zinc-400">
          round {ev.round ?? "—"}
        </span>
        <span className="font-mono text-[10px] text-zinc-500">
          {ev.cluster_id ?? "—"}
        </span>
        <span
          className="ml-auto font-mono text-[10px] text-zinc-600"
          title={ev.ts ?? ""}
        >
          {frontierAge(ev.ts, nowMs)}
        </span>
      </div>
      {ev.refined_claim_head != null && (
        <div className="mt-1 text-zinc-200">{ev.refined_claim_head}</div>
      )}
      {typeof ev.feedback_digest === "string" &&
        ev.feedback_digest.trim() !== "" && (
          <ClampedText text={ev.feedback_digest} />
        )}
    </div>
  );
}

function EventCard({ ev, nowMs }: { ev: ReviewEvent; nowMs: number }) {
  if (ev.type === "screen") return <ScreenCard ev={ev} nowMs={nowMs} />;
  if (ev.type === "agenda") return <AgendaCard ev={ev} nowMs={nowMs} />;
  if (ev.type === "refine") return <RefineCard ev={ev} nowMs={nowMs} />;
  // A type this build does not know is still shown, honestly raw.
  return (
    <div className={CARD_CLS} data-testid="unknown-card">
      <span className={TYPE_CHIP_CLS}>{ev.type}</span>{" "}
      <span className="font-mono text-zinc-500">{ev.ts ?? "—"}</span>
    </div>
  );
}

// ─── one raw plumbing row (the ORIGINAL table row, unchanged) ────────────

function FrontierRow({
  call,
  down,
  streak,
  nowMs,
}: {
  call: FrontierCall;
  down: boolean;
  streak: number | null;
  nowMs: number;
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
          {frontierAge(call.timestamp, nowMs)}
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

// ─── the plumbing disclosure (raw table verbatim, default closed) ────────

function PlumbingTable({
  data,
  stale,
  nowMs,
}: {
  data: FrontierData | null;
  stale: boolean;
  nowMs: number;
}) {
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
    <>
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-[11px] text-zinc-500">
          raw CLI invocations off{" "}
          <span className="font-mono">run_state/frontier_calls.jsonl</span>
        </span>
        {data != null && summary != null && (
          <span
            className="font-mono text-[11px] text-zinc-600"
            data-testid="frontier-summary"
          >
            {summary.calls_24h} calls/24h · last{" "}
            {frontierAge(summary.last_call_ts, nowMs)}
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
              nowMs={nowMs}
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
    </>
  );
}

// ─── the section ─────────────────────────────────────────────────────────

export default function FrontierReviews({
  pollMs = FRONTIER_POLL_MS,
  paused = false,
  initialDelayMs = 0,
}: {
  pollMs?: number;
  paused?: boolean;
  /** Mount stagger — /model-io hands this section the last (450 ms) slot. */
  initialDelayMs?: number;
}) {
  // Plumbing is default-CLOSED and its poll only runs while it is open —
  // the substance feed is the panel now, the raw table is for tracing.
  const [plumbingOpen, setPlumbingOpen] = useState(false);

  const reviewsPoll = usePolled<ReviewsData>(
    "modelio:frontier_reviews",
    () => getFrontierReviews(),
    { intervalMs: pollMs, initialDelayMs, enabled: !paused },
  );
  const callsPoll = usePolled<FrontierData>(
    "modelio:frontier_calls",
    () => getFrontierCalls(),
    { intervalMs: pollMs, enabled: !paused && plumbingOpen },
  );

  // SWR across pause: the hub keeps the last payload on a failed refetch;
  // the refs keep it across enabled:false (pause / closed plumbing) too.
  const lastReviewsRef = useRef<ReviewsData | null>(null);
  if (reviewsPoll.data !== undefined) lastReviewsRef.current = reviewsPoll.data;
  const reviews = reviewsPoll.data ?? lastReviewsRef.current;
  const lastCallsRef = useRef<FrontierData | null>(null);
  if (callsPoll.data !== undefined) lastCallsRef.current = callsPoll.data;
  const callsData = callsPoll.data ?? lastCallsRef.current;

  const stale = reviewsPoll.failing;
  // 30s age clock — keeps "3m" honest between (rare) payload changes.
  const now = useNow(30_000);

  // Defensive against a version-skewed backend answering a foreign body.
  const events = Array.isArray(reviews?.events) ? reviews.events : [];
  const health =
    reviews?.health != null && typeof reviews.health === "object"
      ? reviews.health
      : {};
  const join = reviews?.ledger_join;

  return (
    <Card className="mt-3" title="Frontier reviews" testId="frontier-reviews">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-[11px] text-zinc-500">
          what the frontier falsifier tier (D-061: claude = methods, codex =
          novelty — veto/annotate only) actually said
        </span>
        {stale && (
          <span className="text-[11px] text-amber-400/80">
            poll failed — showing the last loaded feed; live state UNKNOWN.
          </span>
        )}
      </div>

      {reviews == null ? (
        <div className="text-xs text-zinc-500">
          /api/frontier_reviews not loaded — frontier tier state UNKNOWN,
          not idle.
        </div>
      ) : (
        <>
          <HealthStrip health={health} nowMs={now} />

          {join != null && join.ok === false && (
            <div
              className="mt-1.5 text-[11px] text-amber-400/80"
              data-testid="ledger-join-error"
            >
              idea-ledger join unavailable — claim heads and refine events
              missing from this feed: {join.error ?? "unknown error"}
            </div>
          )}

          {events.length === 0 ? (
            <div
              className="mt-2 text-xs text-zinc-500"
              data-testid="reviews-empty"
            >
              no frontier review events in the recent tails — the screen
              fires on promotion candidates and the agenda synthesist on its
              own cadence, so an empty feed between candidates is normal,
              not an outage.
            </div>
          ) : (
            <div className="mt-2 flex flex-col gap-1.5">
              {events.map((ev, i) => (
                <EventCard key={`${ev.ts ?? "ev"}-${i}`} ev={ev} nowMs={now} />
              ))}
            </div>
          )}

          {reviews.events_in_window > events.length && (
            <div className="mt-1.5 text-[11px] text-zinc-600">
              newest {events.length} of {reviews.events_in_window} events in
              the tail windows.
            </div>
          )}
        </>
      )}

      {/* The old raw invocation table — tracing detail, behind a disclosure,
          default closed. Controlled <details> (jsdom + poll gating). */}
      <details
        className="mt-2"
        open={plumbingOpen}
        data-testid="frontier-plumbing"
      >
        <summary
          className="cursor-pointer select-none text-[11px] text-zinc-500 hover:text-zinc-300"
          onClick={(e) => {
            e.preventDefault();
            setPlumbingOpen((o) => !o);
          }}
        >
          plumbing — raw CLI invocations {plumbingOpen ? "▾" : "▸"}
        </summary>
        {plumbingOpen && (
          <div className="mt-1.5">
            <PlumbingTable
              data={callsData}
              stale={callsPoll.failing}
              nowMs={now}
            />
          </div>
        )}
      </details>
    </Card>
  );
}
