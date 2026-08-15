// HumanTodoPanel — the human's ESCALATION INBOX (GET /api/human_todo). The one
// surface allowed to DEMAND attention: 11+ iterations were sitting at
// gate_status="pending" with no verdict and nothing on screen said so
// (observability_reconciliation_plan.md §"the human's queue is invisible").
//
// Severity-tiered inbox, not a flat list. Tier order (highest first):
//   blocking  — state_gate / state_file_gate     (red — the loop is gated)
//   ops       — stale_active_run                 (amber — phantom presence)
//   review    — gate_verdict + finding_review    (emerald — the review queue)
//   info      — bubble_ack / bubble_unacked      (zinc — its ack channel is
//               still pending upstream, so bubbles render as information,
//               never as the one decision being demanded)
// Unknown kinds rank below info and render raw (quiet) — a new queue source
// degrades, it never crashes.
//
// The single NEWEST item of the HIGHEST present tier renders as a one-decision
// hero card: kind, title, age, one-line detail, and its action surface.
// Everything else collapses into per-kind group rows (severity dot · count ·
// kind · oldest age) that expand via <details> into the same full rows.
//
// WRITE-BACK (B4, D-046 blessed — docs/human_writeback_contract.md): each
// item renders its in-UI attestation form — GateVerdictForm /
// FindingReviewForm / BubbleAckForm on their kinds, plus a DeferForm on
// every blessed kind (for stale_active_run / state_gate, whose direct
// resolution is NOT blessed, defer is the ONLY in-UI action). Forms are
// capability-gated on GET /api/attest/available (cached per page-load):
// available:false or a version-skew 404 degrades every form to the
// copy-paste fallback. The verbatim resolve_command block is DEMOTED to a
// "CLI fallback" <details> disclosure on each item — collapsed while a form
// is available, forced open when copy-paste is the only path. The command
// comes verbatim from the backend; the panel never invents one. After a
// successful POST the form re-polls /api/human_todo — the item leaving the
// queue (or gaining its deferred tag) is the durable confirmation; an item
// with an open deferral renders its "deferred to dev session" tag and stays
// listed AND counted (a deferral assigns the work, it does not resolve it).
//
// Poll discipline mirrors SurfacedFindingsPanel/BubblesPanel: an `initial`
// prop bypasses polling (tests render synchronously from fixtures) AND
// suppresses the capability fetch — fixture renders stay deterministic; the
// `attest` prop injects a known capability instead. Otherwise it polls
// getHumanTodo(), cleans up on unmount, and surfaces an error string rather
// than throwing. A 404 gets an HONEST error state (the endpoint is missing,
// not the queue empty). Empty queue is the CALM state ("Nothing needs you —
// the loop is unblocked."), not an alarm — the count badge takes the tint of
// the highest present tier and is quiet at zero.
import { useEffect, useState } from "react";
import { getHumanTodo } from "../api/http";
import {
  deferKindOf,
  getAttestCapability,
  type AttestActions,
  type AttestAvailable,
} from "../api/attest";
import BubbleAckForm from "./BubbleAckForm";
import DeferForm from "./DeferForm";
import EndpointMissingNote from "./EndpointMissingNote";
import FindingReviewForm from "./FindingReviewForm";
import GateVerdictForm from "./GateVerdictForm";
import { ageLabel, clearsLadderBar, evidenceLevelOf } from "../ladderBar";
import type { HumanTodoItem } from "../types/schemas";

// Humanized labels for the known queue kinds. Looked up by OWN key only (the
// SurfacedFindingsPanel.toneFor idiom): `kind` is producer-owned, so a value
// colliding with an Object.prototype member ("toString", ...) must not resolve
// to a function through the prototype chain. An unknown kind falls back to the
// raw kind string — rendered quiet, never crashing.
const KIND_LABELS: Record<string, string> = {
  gate_verdict: "awaiting gate verdict",
  finding_review: "finding review",
  bubble_unacked: "bubble unacknowledged",
  stale_active_run: "stale active run",
  state_file_gate: "state-file gate",
  // Aliases matching the live /api/human_todo producer's KINDS exactly
  // (backend/human_todo.py emits these two spellings on its items).
  bubble_ack: "bubble unacknowledged",
  state_gate: "state-file gate",
};

// Display order for kinds inside one tier. Unknown kinds append after, in
// first-appearance order.
const KIND_ORDER = [
  "state_gate",
  "state_file_gate",
  "stale_active_run",
  "gate_verdict",
  "finding_review",
  "bubble_ack",
  "bubble_unacked",
];

// Severity tier per kind — lower is more urgent. Own-key-free switch (no map
// lookup, so no prototype-collision hazard).
function tierOf(kind: string): number {
  switch (kind) {
    case "state_gate":
    case "state_file_gate":
      return 0; // blocking
    case "stale_active_run":
      return 1; // ops
    case "gate_verdict":
    case "finding_review":
      return 2; // review queue
    case "bubble_ack":
    case "bubble_unacked":
      return 3; // informational
    default:
      return 4; // unknown queue source — quiet, last
  }
}

// State dots: emerald/amber/red only (zinc for informational/unknown — not a
// state, just presence).
const TIER_DOT = [
  "bg-red-400",
  "bg-amber-400",
  "bg-emerald-400",
  "bg-zinc-600",
  "bg-zinc-600",
];
const TIER_BADGE = [
  "bg-red-950 text-red-400",
  "bg-amber-950 text-amber-400",
  "bg-emerald-950 text-emerald-400",
  "bg-zinc-800 text-zinc-400",
  "bg-zinc-800 text-zinc-400",
];

// Coerce a producer-owned display scalar to renderable text. An object/array
// rendered as a React child throws and blanks the WHOLE page, so those drop to
// null; a finite number/bool stringifies. (Mirrors SurfacedFindingsPanel.asText.)
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  // object / array / anything else: not safely renderable as text — skip it.
  return null;
}

// --- evidence ladder (2026-08-14 work order B) -------------------------
// The bar logic (BAR_LEVELS / evidenceLevelOf / clearsLadderBar / ageLabel)
// moved VERBATIM to src/ladderBar.ts (UI simplification S1) so the Pulse
// OweStrip shares the one definition of "clears the bar". The inbox bar is
// L4/L5; legacy no-level rows are below-bar by definition, hidden behind the
// "show demoted" toggle rather than deleted. Operational kinds are never
// bar-hidden (hiding a blocking state_gate would fake an unblocked loop).

function isFindingItem(item: HumanTodoItem): boolean {
  return asText(item.kind) === "finding_review";
}

function kindLabel(kind: string): string {
  return Object.prototype.hasOwnProperty.call(KIND_LABELS, kind)
    ? KIND_LABELS[kind]
    : kind;
}

// Copy button for the resolve command. navigator.clipboard is absent in
// non-secure contexts AND in jsdom — guard with `?.` so the button is inert
// (never throwing) where the API is missing.
function CopyButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const writeText = navigator.clipboard?.writeText?.bind(navigator.clipboard);
    if (!writeText) return;
    writeText(command)
      .then(() => setCopied(true))
      .catch(() => {
        /* clipboard write denied — leave the button as-is */
      });
  };
  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(id);
  }, [copied]);
  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy resolve command"
      className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400 hover:bg-zinc-800"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

// One full inbox row — used both as the hero card body and inside expanded
// groups, so every item always carries its action surface (attestation forms
// when the capability handshake allows them) + the verbatim CLI fallback.
// `kindIndex` is the item's oldest-first position WITHIN its kind (stable
// across hero/group placement, so `todo-<kind>-<i>` testids never collide).
function TodoRow({
  item,
  kind,
  kindIndex,
  nowMs,
  hero,
  actions,
  onAttested,
  selectMode,
  onSelect,
  selectedId,
}: {
  item: HumanTodoItem;
  kind: string;
  kindIndex: number;
  nowMs: number;
  hero: boolean;
  // Resolved /api/attest/available actions; null = unknown or not fetched —
  // forms degrade to the copy-paste fallback (rendered open).
  actions: AttestActions | null;
  onAttested: () => void;
  // Select-only mode (FE1): when true the row's GATED writers
  // (GateVerdictForm / FindingReviewForm) are SUPPRESSED — clicking the title
  // selects the item for the calibration-capture flow instead of writing a
  // verdict with no calibration. BubbleAck / Defer / the CLI fallback stay
  // inline (they are not the calibration-bypass). Default-off: absent → the
  // inline writers render exactly as before.
  selectMode?: boolean;
  onSelect?: (id: string) => void;
  selectedId?: string | null;
}) {
  const title = asText(item.title);
  const id = asText(item.id);
  const detail = asText(item.detail);
  const command = asText(item.resolve_command);
  const tier = tierOf(kind);

  // Which attestation surfaces this row gets. `family` folds the two label
  // generations (bubble_unacked→bubble_ack, state_file_gate→state_gate);
  // an unknown kind has no blessed CLI, so it gets no form and no defer —
  // copy-paste only. Forms need the item id verbatim as the CLI argument.
  const family = id !== null ? deferKindOf(kind) : null;
  // Select-only mode gates OFF the calibration-bypassing direct writers BY
  // FAMILY (deferKindOf folds both spellings: bubble_unacked→bubble_ack,
  // state_file_gate→state_gate). gate_verdict + finding_review write a verdict
  // on click with no calibration — suppress them here. bubble_ack stays (it is
  // an ack channel, not a gate decision); defer + CLI fallback stay too.
  const writerSuppressed =
    selectMode === true &&
    (family === "gate_verdict" || family === "finding_review");
  const directForm =
    actions !== null && family !== null && !writerSuppressed
      ? (family === "gate_verdict" && actions.gate_verdict) ||
        (family === "finding_review" && actions.finding_review) ||
        (family === "bubble_ack" && actions.bubble_ack)
      : false;
  const deferForm = actions !== null && actions.defer && family !== null;
  const hasFormSurface = directForm || deferForm;

  // The title becomes a SELECTOR in select mode (id-guarded). It is a
  // standalone button on the title/header region ONLY — not a whole-<li>
  // onClick, which would swallow clicks meant for the kept BubbleAck / Defer /
  // Copy controls below it. The id must be a NON-EMPTY string: asText("")
  // returns "" (not null), so `id !== null` alone would make an empty-id row
  // selectable and fire onSelect("") — a bad selection key the cockpit cannot
  // .find() or target. Require length so onSelect never fires with a bad id.
  const selectId = id !== null && id !== "" ? id : null;
  const selectable = selectMode === true && selectId !== null;
  const isSelected = selectable && selectedId != null && selectedId === selectId;
  const selectThis = () => {
    if (selectId !== null) onSelect?.(selectId);
  };

  // Open-deferral tag (additive backend fields: deferred + deferral{note,by,at}).
  const deferralRaw = item.deferral;
  const deferral =
    deferralRaw !== null && typeof deferralRaw === "object" && !Array.isArray(deferralRaw)
      ? (deferralRaw as Record<string, unknown>)
      : null;
  const deferralBits =
    deferral === null
      ? []
      : [asText(deferral.by), asText(deferral.note)].filter(
          (s): s is string => s !== null && s !== "",
        );

  return (
    <li
      data-testid={`todo-${kind}-${kindIndex}`}
      className={
        hero
          ? "rounded border border-zinc-700 bg-zinc-950/60 px-3 py-2"
          : "rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
      }
    >
      {hero && (
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-zinc-500">
          <span
            aria-hidden="true"
            className={`inline-block h-1.5 w-1.5 rounded-full ${TIER_DOT[tier]}`}
          />
          <span>{kindLabel(kind)}</span>
          <span className="normal-case text-zinc-600">
            {tier === 3 ? "· informational — ack channel pending" : "· needs you"}
          </span>
        </div>
      )}
      <div className={`flex flex-wrap items-baseline gap-2 text-xs ${hero ? "mt-1" : ""}`}>
        {selectable ? (
          <button
            type="button"
            onClick={selectThis}
            aria-pressed={isSelected}
            className={
              isSelected
                ? `rounded border border-emerald-700 bg-emerald-950/30 px-1.5 py-0.5 text-left ${hero ? "text-sm text-zinc-100" : "text-zinc-200"}`
                : `rounded border border-transparent px-1.5 py-0.5 text-left hover:border-zinc-700 ${hero ? "text-sm text-zinc-100" : "text-zinc-200"}`
            }
          >
            {title ?? id ?? "(untitled)"}
          </button>
        ) : (
          <span className={hero ? "text-sm text-zinc-100" : "text-zinc-200"}>
            {title ?? id ?? "(untitled)"}
          </span>
        )}
        {item.deferred === true && (
          <span
            data-testid="todo-deferred-tag"
            className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-400"
            title={deferralBits.join(" · ") || undefined}
          >
            deferred to dev session
            {deferralBits.length > 0 && (
              <span className="text-sky-600"> · {deferralBits.join(" · ")}</span>
            )}
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-zinc-500">
          {ageLabel(item.since, nowMs)}
        </span>
      </div>
      {detail && (
        <div className="mt-0.5 truncate text-[11px] text-zinc-400" title={detail}>
          {detail}
        </div>
      )}

      {/* In-UI attestation (B4): the blessed form for the kind + defer on
          every blessed kind. stale_active_run / state_gate get ONLY defer —
          their direct resolution is not blessed (contract table row 5). */}
      {id !== null && hasFormSurface && (
        <div className="mt-1.5 space-y-1.5">
          {!writerSuppressed && family === "gate_verdict" && actions!.gate_verdict && (
            <GateVerdictForm iterationId={id} onResolved={onAttested} />
          )}
          {!writerSuppressed && family === "finding_review" && actions!.finding_review && (
            <FindingReviewForm findingId={id} onResolved={onAttested} />
          )}
          {family === "bubble_ack" && actions!.bubble_ack && (
            <BubbleAckForm bubbleRunId={id} onResolved={onAttested} />
          )}
          {deferForm && <DeferForm kind={kind} refId={id} onResolved={onAttested} />}
        </div>
      )}

      {/* The verbatim resolve command — DEMOTED to a "CLI fallback"
          disclosure now that forms exist: collapsed while a form is the
          primary surface, forced open when copy-paste is the only path. */}
      {command && (
        <details
          className="mt-1"
          data-testid="todo-cli-fallback"
          open={hasFormSurface ? undefined : true}
        >
          <summary className="cursor-pointer list-none text-[10px] uppercase tracking-wide text-zinc-600 hover:text-zinc-400">
            CLI fallback
          </summary>
          <div className="mt-1 flex items-center gap-2">
            <code className="block flex-1 overflow-x-auto whitespace-pre rounded bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-300">
              {command}
            </code>
            <CopyButton command={command} />
          </div>
        </details>
      )}
    </li>
  );
}

interface Props {
  initial?: HumanTodoItem[];
  pollMs?: number;
  // Capability injection for fixture renders (tests/storybook): undefined =
  // resolve it live (polling mode only); null = unknown (degrade quietly);
  // an object = use as-is. Fixture (`initial`) renders NEVER fetch it.
  attest?: AttestAvailable | null;
  // Select-only mode (FE1): when true the inbox is a SELECTOR for the
  // calibration-capture flow — each row's title becomes a clickable selector
  // (onSelect(id), aria-pressed off selectedId) and the GATED writers
  // (GateVerdictForm / FindingReviewForm) are suppressed so no verdict is
  // written without calibration. Default-off (absent/false) leaves the inline
  // writers exactly as they were.
  selectMode?: boolean;
  onSelect?: (id: string) => void;
  selectedId?: string | null;
}

export default function HumanTodoPanel({
  initial,
  pollMs = 10000,
  attest,
  selectMode,
  onSelect,
  selectedId,
}: Props) {
  const [items, setItems] = useState<HumanTodoItem[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  // Resolved write-back capability (polling mode); the `attest` prop wins.
  const [fetchedAttest, setFetchedAttest] = useState<AttestAvailable | null>(null);
  // Bumped by a form's onResolved so the queue re-renders without waiting a
  // full poll interval (the form already re-polled for ITS confirmation;
  // this refresh keeps the panel's list in step).
  const [refreshTick, setRefreshTick] = useState(0);
  // Ladder toggle: below-bar findings are hidden by default; the human opts
  // into seeing them ("show demoted (N)"). Session-local, default off.
  const [showDemoted, setShowDemoted] = useState(false);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          setItems(r.items);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs, refreshTick]);

  // Producer-owned payload: `items` may not be an array (→ clean empty state,
  // never a `.filter` throw) and a row may be a non-object scalar/null/array
  // (→ skipped, so one malformed line can't blank the queue; an ARRAY row is
  // typeof "object" but has no fields — drop it too). The count badge and
  // empty state reflect renderable rows only.
  const rows = (Array.isArray(items) ? items : []).filter(
    (it): it is HumanTodoItem =>
      typeof it === "object" && it !== null && !Array.isArray(it),
  );

  // Ladder partition (work order B): finding_review rows below L4 (including
  // all legacy no-level rows) are DEMOTED — off the default inbox, behind the
  // toggle. Operational kinds are never demoted (see the ladder note above).
  const findingRows = rows.filter(isFindingItem);
  const demoted = findingRows.filter((it) => !clearsLadderBar(it));
  const surfacedFindingCount = findingRows.length - demoted.length;
  const visible = showDemoted
    ? rows
    : rows.filter((it) => !isFindingItem(it) || clearsLadderBar(it));

  // Per-level histogram over ALL finding rows (demoted included) — derived
  // from the items themselves, no extra fetch. Absent/malformed level counts
  // under "no level" (the legacy bucket), honestly.
  const levelCounts = new Map<string, number>();
  for (const it of findingRows) {
    const level = evidenceLevelOf(it) ?? "no level";
    levelCounts.set(level, (levelCounts.get(level) ?? 0) + 1);
  }
  const levelOrder = [...levelCounts.keys()].sort((a, b) => {
    if (a === "no level") return 1;
    if (b === "no level") return -1;
    return b.localeCompare(a); // L5 first, down the ladder
  });

  // Group by kind (a missing/non-string kind groups under "unknown" rather
  // than being dropped — the item still needs the human), items oldest-first
  // within each group. A missing `since` sorts FIRST (oldest) — an item of
  // unknown age must not jump ahead of known-old items, and must never win
  // the "newest" hero slot over a dated item.
  const groups = new Map<string, HumanTodoItem[]>();
  for (const row of visible) {
    const kind = asText(row.kind) ?? "unknown";
    const group = groups.get(kind);
    if (group) group.push(row);
    else groups.set(kind, [row]);
  }
  for (const group of groups.values()) {
    group.sort((a, b) => {
      const sa = asText(a.since) ?? "";
      const sb = asText(b.since) ?? "";
      return sa.localeCompare(sb);
    });
  }

  // Kinds ordered by tier, then the in-tier KIND_ORDER, then first appearance.
  const orderedKinds = [...groups.keys()].sort((a, b) => {
    const dt = tierOf(a) - tierOf(b);
    if (dt !== 0) return dt;
    const ia = KIND_ORDER.indexOf(a);
    const ib = KIND_ORDER.indexOf(b);
    if (ia !== -1 || ib !== -1) {
      return (ia === -1 ? KIND_ORDER.length : ia) - (ib === -1 ? KIND_ORDER.length : ib);
    }
    return 0; // both unknown: Map preserves first-appearance order; sort is stable
  });

  // The badge counts what the inbox SHOWS (demoted rows re-enter it only
  // when toggled visible — the toggle itself carries their count).
  const total = visible.length;

  // Capability handshake — polling mode only, lazily once something needs a
  // form, and never when `initial`/`attest` pin the render (fixture renders
  // must stay deterministic: no live fetch may decide their DOM). Cached per
  // page-load in api/attest; a 404 (version-skew) or failure resolves
  // unavailable, degrading every form to the copy-paste fallback.
  // Off ALL rows (demoted included) — a toggled-visible demoted row still
  // renders its forms, so the capability must already be resolved.
  const hasRows = rows.length > 0;
  useEffect(() => {
    if (attest !== undefined) return;
    if (initial !== undefined) return;
    if (!hasRows) return;
    let active = true;
    getAttestCapability().then((c) => {
      if (active) setFetchedAttest(c);
    });
    return () => {
      active = false;
    };
  }, [attest, initial, hasRows]);

  const capability = attest !== undefined ? attest : fetchedAttest;
  const attestActions = capability === null ? null : capability.actions;
  const onAttested = () => setRefreshTick((t) => t + 1);

  // The ONE decision: newest item of the highest present tier (groups are
  // oldest-first, so the newest is the last element of the first kind's
  // tier-mates merged). Ties on identical `since` resolve to the earliest
  // kind in display order — deterministic either way.
  let hero: { kind: string; kindIndex: number; item: HumanTodoItem } | null = null;
  if (total > 0) {
    const topTier = tierOf(orderedKinds[0]);
    for (const kind of orderedKinds) {
      if (tierOf(kind) !== topTier) break;
      const group = groups.get(kind)!;
      const idx = group.length - 1; // newest within the kind
      const candidate = { kind, kindIndex: idx, item: group[idx] };
      if (
        hero === null ||
        (asText(candidate.item.since) ?? "").localeCompare(
          asText(hero.item.since) ?? "",
        ) > 0
      ) {
        hero = candidate;
      }
    }
  }

  const topTier = total > 0 ? tierOf(orderedKinds[0]) : null;
  const endpointMissing = error !== null && /\b404\b/.test(error);
  const nowMs = Date.now();

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="human-todo-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Human TODO
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/human_todo · blocked on you
        </span>
        <span
          data-testid="human-todo-count"
          className={`ml-auto rounded px-1.5 py-0.5 text-[11px] ${
            topTier !== null ? TIER_BADGE[topTier] : "text-zinc-500"
          }`}
        >
          {total}
        </span>
      </div>

      {error &&
        (endpointMissing ? (
          // Honest 404 state: the inbox SOURCE is missing — say so, never
          // render the calm "nothing needs you" off a dead endpoint.
          <div className="mt-2 text-xs text-amber-400" data-testid="human-todo-error">
            /api/human_todo returned 404 — the inbox endpoint is missing
            (backend too old or route not mounted), so the queue is UNKNOWN,
            not empty.
          </div>
        ) : (
          <div className="mt-2 text-xs text-red-400" data-testid="human-todo-error">
            {error}
          </div>
        ))}

      {loaded && rows.length === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="human-todo-empty">
          Nothing needs you — the loop is unblocked.
        </div>
      )}

      {/* Evidence-ladder strip (work order B). Honest zero-week state: no
          finding cleared the L4 bar — say so, with the per-level histogram
          derived from the items themselves (no extra fetch). The demoted
          toggle is the ONLY way below-bar findings enter the inbox. */}
      {loaded && !error && surfacedFindingCount === 0 && (
        <div className="mt-2 text-xs text-zinc-500" data-testid="ladder-empty">
          Nothing cleared L4 this week.
        </div>
      )}
      {findingRows.length > 0 && !error && (
        <div
          className="mt-1 font-mono text-[10px] text-zinc-600"
          data-testid="ladder-counts"
        >
          ladder:{" "}
          {levelOrder
            .map((level) => `${level} ×${levelCounts.get(level)}`)
            .join(" · ")}
        </div>
      )}
      {demoted.length > 0 && !error && (
        <button
          type="button"
          data-testid="ladder-toggle"
          aria-pressed={showDemoted}
          onClick={() => setShowDemoted((v) => !v)}
          className="mt-1.5 rounded border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
        >
          {showDemoted
            ? `hide demoted (${demoted.length})`
            : `show demoted (${demoted.length})`}
        </button>
      )}

      {/* Write-back unavailable: quiet zinc, never red (a known capability
          endpoint missing is degradation, not an error). Two honest flavors:
          a version-skew 404 (backend binary predates /api/attest/*) renders
          the shared EndpointMissingNote with the running binary's sha; a 200
          answering available:false (CLI/interpreter missing under the
          primary repo) gets the inline note. Either way every item below
          carries its copy-paste CLI fallback, forced open. */}
      {capability !== null &&
        capability.available === false &&
        total > 0 &&
        (capability.skew === true ? (
          <div className="mt-2">
            <EndpointMissingNote endpoint="/api/attest/available" />
          </div>
        ) : (
          <div data-testid="attest-skew-note" className="mt-2 text-[11px] text-zinc-500">
            in-UI attestation isn’t available from this backend build — each
            item carries its copy-paste CLI fallback below.
          </div>
        ))}

      {hero && (
        <ul className="mt-2" data-testid="human-todo-hero">
          <TodoRow
            item={hero.item}
            kind={hero.kind}
            kindIndex={hero.kindIndex}
            nowMs={nowMs}
            hero
            actions={attestActions}
            onAttested={onAttested}
            selectMode={selectMode}
            onSelect={onSelect}
            selectedId={selectedId}
          />
        </ul>
      )}

      {/* Everything beyond the one decision: per-kind group rows, severity
          dot + count + kind + oldest age, expandable into the full rows. */}
      {orderedKinds.map((kind) => {
        const group = groups.get(kind)!;
        const remaining =
          hero && hero.kind === kind ? group.slice(0, hero.kindIndex) : group;
        if (remaining.length === 0) return null;
        const tier = tierOf(kind);
        const oldest = ageLabel(remaining[0]?.since, nowMs);
        return (
          <details
            key={kind}
            className="group mt-1.5"
            data-testid={`todo-group-${kind}`}
          >
            <summary className="flex cursor-pointer list-none items-baseline gap-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1 text-xs hover:border-zinc-700">
              <span
                aria-hidden="true"
                className={`inline-block h-1.5 w-1.5 self-center rounded-full ${TIER_DOT[tier]}`}
              />
              <span className="text-zinc-300">{remaining.length}</span>
              <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                {kindLabel(kind)}
              </h3>
              {oldest !== "—" && (
                <span className="text-[10px] text-zinc-600">· oldest {oldest}</span>
              )}
              <span className="ml-auto text-[10px] text-zinc-600">
                <span className="group-open:hidden">▸</span>
                <span className="hidden group-open:inline">▾</span>
              </span>
            </summary>
            <ul className="mt-1.5 space-y-1.5 pl-3">
              {remaining.map((item, i) => (
                <TodoRow
                  key={`${asText(item.id) ?? "todo"}-${i}`}
                  item={item}
                  kind={kind}
                  kindIndex={i}
                  nowMs={nowMs}
                  hero={false}
                  actions={attestActions}
                  onAttested={onAttested}
                  selectMode={selectMode}
                  onSelect={onSelect}
                  selectedId={selectedId}
                />
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}
