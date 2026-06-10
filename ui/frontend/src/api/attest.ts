// In-UI attestation client — the B4 write-back seam (D-046, blessed; see
// docs/human_writeback_contract.md). Talks to the five /api/attest/*
// endpoints on the UI backend (ui/backend/attest.py), which argv-execs the
// blessed CLIs. The CLIs are the writers of record — this client never
// writes a file, and the POST response is NOT the confirmation:
//
//   Confirmation = the queue (contract principle 5). After a successful
//   POST the caller RE-POLLS GET /api/human_todo; the item leaving the
//   queue (or, for defer, gaining its `deferred: true` tag — a deferral
//   assigns the work, it does not resolve the item) is the durable
//   confirmation. `useAttestSubmission` below encodes that sequence.
//
// Other non-negotiables encoded here:
// - 502 carries `{rc, stderr}` with the CLI's stderr VERBATIM; AttestError
//   preserves it un-summarized for the form to render in a red mono block.
// - Success shapes DIFFER by CLI (do not assume one): `gate_cli` and
//   `todo_cli` print the appended ledger row itself (`gated_by` / `ack_by`
//   / `attested_by` = "human:ui"); `finding_session --set-status` prints an
//   ENVELOPE `{finding_id, session_id, outcome, loop_feedback_row,
//   status_audit_row}` whose stamp is `status_audit_row.changed_by`
//   (`loop_feedback_row` is null for `in_review`). `stampOf` resolves the
//   identity stamp across both shapes.
// - The capability handshake GET /api/attest/available is cached per
//   page-load; `available: false` OR a 404 (version skew — the running
//   backend predates the endpoint) degrades every form to the copy-paste
//   CLI fallback, quietly — never a red error.
//
// NOTE on http.ts's HttpError: AttestError below deliberately does NOT
// `extends HttpError`. Several test suites module-mock ../api/http with
// factories that omit the class binding, and `class X extends undefined`
// throws at module load — the same hazard EndpointMissingNote documents.
// Interop is by DUCK TYPE instead: AttestError carries the same `.status`
// field, so EndpointMissingNote.isVersionSkew404 and other status-probing
// consumers treat both identically.
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, getHumanTodo } from "./http";
import type { HumanTodoItem } from "../types/schemas";

// --- frozen enums (docs/human_writeback_contract.md — the CLIs' argparse
// `choices` are authoritative; these mirrors are never wider) ---

export type GateVerdict = "valid" | "invalid" | "needs_revision";
export type FindingStatus = "validated" | "rejected" | "in_review";
export type DeferKind =
  | "gate_verdict"
  | "finding_review"
  | "bubble_ack"
  | "stale_active_run"
  | "state_gate";

export const GATE_VERDICTS: readonly GateVerdict[] = [
  "valid",
  "invalid",
  "needs_revision",
];
export const FINDING_STATUSES: readonly FindingStatus[] = [
  "validated",
  "rejected",
  "in_review",
];

// The queue emits two label generations for the same kinds (the live
// producer's spellings are bubble_ack / state_gate; older fixtures carry
// bubble_unacked / state_file_gate). The defer enum is FROZEN to five
// values, so item kinds normalize through this own-key map; an unknown
// kind maps to null — defer is NOT offered for it (the POST would 422).
const DEFER_KIND_ALIASES: Record<string, DeferKind> = {
  gate_verdict: "gate_verdict",
  finding_review: "finding_review",
  bubble_ack: "bubble_ack",
  bubble_unacked: "bubble_ack",
  stale_active_run: "stale_active_run",
  state_gate: "state_gate",
  state_file_gate: "state_gate",
};

export function deferKindOf(kind: string): DeferKind | null {
  return Object.prototype.hasOwnProperty.call(DEFER_KIND_ALIASES, kind)
    ? DEFER_KIND_ALIASES[kind]
    : null;
}

// Kinds whose DIRECT resolution is not blessed (contract table row 5):
// process autopsy / state-file edits stay primary-session human actions.
// For these the UI offers ONLY defer.
export function deferOnly(kind: string): boolean {
  const normalized = deferKindOf(kind);
  return normalized === "stale_active_run" || normalized === "state_gate";
}

// --- capability handshake ---

export interface AttestActions {
  gate_verdict: boolean;
  finding_review: boolean;
  bubble_ack: boolean;
  defer: boolean;
}

export interface AttestAvailable {
  available: boolean;
  actions: AttestActions;
  /** True when unavailability came from a version-skew 404 (the running
   *  backend binary predates /api/attest/*) rather than a 200 answering
   *  available:false (CLI/interpreter missing under the primary repo).
   *  Distinct renders: skew gets the shared EndpointMissingNote. */
  skew?: boolean;
}

export const ATTEST_UNAVAILABLE: AttestAvailable = {
  available: false,
  actions: {
    gate_verdict: false,
    finding_review: false,
    bubble_ack: false,
    defer: false,
  },
};

// Producer-owned payload — coerce booleans strictly (=== true), never truthy.
function asCapability(body: unknown): AttestAvailable {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return ATTEST_UNAVAILABLE;
  }
  const b = body as Record<string, unknown>;
  const raw =
    b.actions !== null && typeof b.actions === "object" && !Array.isArray(b.actions)
      ? (b.actions as Record<string, unknown>)
      : {};
  return {
    available: b.available === true,
    actions: {
      gate_verdict: raw.gate_verdict === true,
      finding_review: raw.finding_review === true,
      bubble_ack: raw.bubble_ack === true,
      defer: raw.defer === true,
    },
  };
}

async function fetchCapability(): Promise<AttestAvailable> {
  const resp = await fetch(`${API_BASE}/api/attest/available`);
  // 404 == version skew (the running backend predates /api/attest/*) — a
  // KNOWN capability endpoint missing is quiet degradation, never an error.
  if (resp.status === 404) return { ...ATTEST_UNAVAILABLE, skew: true };
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return asCapability(await resp.json());
}

// Cached per page-load: the answer is a property of the running backend
// binary, so one fetch serves every form on the page. A 200 or a 404 (skew)
// is cached; a transport-level failure resolves UNAVAILABLE for this caller
// but clears the cache so a later mount may retry.
let capabilityCache: Promise<AttestAvailable> | null = null;

export function getAttestCapability(): Promise<AttestAvailable> {
  if (capabilityCache === null) {
    capabilityCache = fetchCapability().catch(() => {
      capabilityCache = null;
      return ATTEST_UNAVAILABLE;
    });
  }
  return capabilityCache;
}

// Test hook only: the per-page-load cache outlives a vitest test within one
// file, so suites that stub fetch must reset between tests.
export function resetAttestCapabilityCache(): void {
  capabilityCache = null;
}

// React view of the cached capability: null while unresolved. `override`
// (when not undefined) wins and suppresses the fetch — parents/tests inject
// a known capability; standalone mounts (e.g. GateVerdictForm inside the
// iteration detail modal) pass nothing and self-resolve.
export function useAttestCapability(
  override?: AttestAvailable | null,
): AttestAvailable | null {
  const [cap, setCap] = useState<AttestAvailable | null>(null);
  useEffect(() => {
    if (override !== undefined) return;
    let active = true;
    getAttestCapability().then((c) => {
      if (active) setCap(c);
    });
    return () => {
      active = false;
    };
  }, [override]);
  return override !== undefined ? override : cap;
}

// --- POST endpoints ---

// Success payloads: a ledger row (gate_cli / todo_cli) OR the finding_review
// envelope — both are producer-owned JSON; callers must probe, not assume.
export type AttestResult = Record<string, unknown>;

export class AttestError extends Error {
  readonly status: number;
  /** CLI exit code from a 502 `{rc, stderr}` payload; null otherwise. */
  readonly rc: number | null;
  /** CLI stderr VERBATIM from a 502 payload; null otherwise. Render it
   *  un-summarized — the CLI's own validation message is the truth. */
  readonly stderr: string | null;
  readonly detail: string;

  constructor(status: number, detail: string, rc: number | null, stderr: string | null) {
    super(`${status} ${detail}`);
    this.name = "AttestError";
    this.status = status;
    this.detail = detail;
    this.rc = rc;
    this.stderr = stderr;
  }
}

async function postAttest(path: string, body: Record<string, unknown>): Promise<AttestResult> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let payload: Record<string, unknown> | null = null;
    try {
      const parsed: unknown = await resp.json();
      if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
      }
    } catch {
      /* error response carried no JSON body */
    }
    const stderr = typeof payload?.stderr === "string" ? payload.stderr : null;
    const rc = typeof payload?.rc === "number" ? payload.rc : null;
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : stderr ?? `${resp.status} ${resp.statusText}`;
    throw new AttestError(resp.status, detail, rc, stderr);
  }
  return (await resp.json()) as AttestResult;
}

export const postGateVerdict = (body: {
  iteration_id: string;
  verdict: GateVerdict;
  note: string;
}) => postAttest("/api/attest/gate_verdict", body);

export const postFindingReview = (body: {
  finding_id: string;
  status: FindingStatus;
  note: string;
}) => postAttest("/api/attest/finding_review", body);

export const postBubbleAck = (body: { bubble_run_id: string; note: string }) =>
  postAttest("/api/attest/bubble_ack", body);

export const postDefer = (body: { kind: DeferKind; ref_id: string; note: string }) =>
  postAttest("/api/attest/defer", body);

// --- success-shape helpers ---

// Resolve the human:ui identity stamp across BOTH success shapes:
// the finding_review envelope stamps `status_audit_row.changed_by`; the
// ledger-row shapes stamp `gated_by` (gate_cli) / `ack_by` (todo_cli ack) /
// `attested_by` (todo_cli defer); `by` / `changed_by` are accepted as
// forward-compatible spellings. Null when no string stamp is present —
// the caller renders the absence honestly, never fabricates "human:ui".
export function stampOf(result: AttestResult | null | undefined): string | null {
  if (result === null || result === undefined || typeof result !== "object") return null;
  const audit = result.status_audit_row;
  if (audit !== null && typeof audit === "object" && !Array.isArray(audit)) {
    const changedBy = (audit as Record<string, unknown>).changed_by;
    if (typeof changedBy === "string" && changedBy) return changedBy;
  }
  for (const key of ["gated_by", "ack_by", "attested_by", "changed_by", "by"]) {
    const v = result[key];
    if (typeof v === "string" && v) return v;
  }
  return null;
}

// The finding_review envelope's `status_audit_row`, when present — the
// row the UI renders as the confirmed write (its `changed_by` is the stamp).
export function statusAuditRowOf(
  result: AttestResult | null | undefined,
): Record<string, unknown> | null {
  if (result === null || result === undefined || typeof result !== "object") return null;
  const audit = result.status_audit_row;
  if (audit !== null && typeof audit === "object" && !Array.isArray(audit)) {
    return audit as Record<string, unknown>;
  }
  return null;
}

// --- queue-item probes (shared by the forms' confirm predicates) ---

function rowOf(item: unknown): Record<string, unknown> | null {
  if (item === null || typeof item !== "object" || Array.isArray(item)) return null;
  return item as Record<string, unknown>;
}

// True when the re-polled queue still lists an item of this kind-family and
// id. Kind matching goes through the alias map so bubble_ack/bubble_unacked
// (and state_gate/state_file_gate) generations compare equal.
export function queueHasItem(
  items: HumanTodoItem[],
  kind: string,
  id: string,
): boolean {
  const family = deferKindOf(kind);
  return items.some((item) => {
    const row = rowOf(item);
    if (row === null || row.id !== id) return false;
    const itemKind = typeof row.kind === "string" ? row.kind : "";
    return family !== null ? deferKindOf(itemKind) === family : itemKind === kind;
  });
}

// True when the re-polled queue lists the item WITH its open-deferral tag
// (`deferred: true` — additive, ui/backend/human_todo.py `_tag_deferred`).
export function queueHasDeferredItem(items: HumanTodoItem[], id: string): boolean {
  return items.some((item) => {
    const row = rowOf(item);
    return row !== null && row.id === id && row.deferred === true;
  });
}

// --- submission flow (shared by all four forms) ---

export type AttestPhase =
  | { state: "idle" }
  | { state: "submitting" }
  | {
      state: "done";
      result: AttestResult;
      stamp: string | null;
      /** Whether the re-polled queue showed the expected durable state
       *  (item gone, or deferred-tagged — per the submit's predicate). */
      confirmed: boolean;
      /** Re-poll failure detail; the POST succeeded but the durable
       *  confirmation is UNKNOWN — rendered honestly, never as success. */
      repollError: string | null;
    }
  | {
      state: "error";
      status: number | null;
      rc: number | null;
      stderr: string | null;
      detail: string;
    };

export interface AttestSubmitOptions {
  exec: () => Promise<AttestResult>;
  /** Durable-confirmation predicate over the RE-POLLED queue items
   *  (contract principle 5: the queue, not the POST response, confirms). */
  confirmed: (items: HumanTodoItem[]) => boolean;
  onResolved?: () => void;
}

export function useAttestSubmission(): {
  phase: AttestPhase;
  submit: (opts: AttestSubmitOptions) => Promise<void>;
  reset: () => void;
} {
  const [phase, setPhase] = useState<AttestPhase>({ state: "idle" });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const submit = useCallback(async (opts: AttestSubmitOptions) => {
    if (mounted.current) setPhase({ state: "submitting" });
    let result: AttestResult;
    try {
      result = await opts.exec();
    } catch (err) {
      if (!mounted.current) return;
      if (err instanceof AttestError) {
        setPhase({
          state: "error",
          status: err.status,
          rc: err.rc,
          stderr: err.stderr,
          detail: err.detail,
        });
      } else {
        setPhase({
          state: "error",
          status: null,
          rc: null,
          stderr: null,
          detail: String(err),
        });
      }
      return;
    }
    // Contract principle 5 — confirmation = the queue. Re-poll and let the
    // caller's predicate read the durable state off the fresh items.
    let confirmed = false;
    let repollError: string | null = null;
    try {
      const fresh = await getHumanTodo();
      const items = Array.isArray(fresh?.items) ? fresh.items : [];
      confirmed = opts.confirmed(items);
    } catch (err) {
      repollError = String(err);
    }
    if (mounted.current) {
      setPhase({
        state: "done",
        result,
        stamp: stampOf(result),
        confirmed,
        repollError,
      });
    }
    opts.onResolved?.();
  }, []);

  const reset = useCallback(() => setPhase({ state: "idle" }), []);
  return { phase, submit, reset };
}
