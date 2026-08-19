// Cockpit (/todo) fetch client for the /api/todo/* endpoints. The seams have
// LANDED: ui/backend execs the blessed orchestrator CLI for each outcome —
// authorize_fix, directive_signoff, calibration, and the tutor/two-voice chat
// are live execs (capability-gated by GET /api/todo/available's action flags);
// spawn_topic / abstain are honest SESSION-EXITS (no in-UI one-shot — preview
// only). When a capability flag is OFF the endpoint is preview-only: it returns a
// response that writes NOTHING (inviolate rule 4 — never a faked write/verdict).
//
// This client deliberately mirrors api/attest.ts's idiom: the same API_BASE,
// the same 404 == version-skew quiet degradation, the same {rc, stderr}/error
// envelope (TodoError carries CLI stderr verbatim by DUCK TYPE — `.status`,
// `.rc`, `.stderr` — without `extends HttpError`, the module-mock hazard
// attest.ts documents). It does NOT re-wrap the FOUR already-blessed outcomes
// (gate_verdict / finding_review / bubble_ack / defer): the cockpit imports
// api/attest.ts directly for those. Sign-off WITHOUT a directive is a plain
// gate_verdict via attest.ts; only the directive variant lives here.
import { API_BASE } from "./http";
import type {
  ChatMode,
  ChatStartResult,
  ChatTurnResult,
  CockpitAvailability,
  ConcurrencyStatus,
} from "../types/todo";

// --- error envelope (mirrors attest.ts's AttestError; duck-typed, not a
// subclass — see the module-mock note above) ---
export class TodoError extends Error {
  readonly status: number;
  /** CLI/stub exit code from a 502 `{rc, stderr}` payload; null otherwise. */
  readonly rc: number | null;
  /** stderr VERBATIM from a 502 payload; null otherwise. Render un-summarized. */
  readonly stderr: string | null;
  readonly detail: string;

  constructor(status: number, detail: string, rc: number | null, stderr: string | null) {
    super(`${status} ${detail}`);
    this.name = "TodoError";
    this.status = status;
    this.detail = detail;
    this.rc = rc;
    this.stderr = stderr;
  }
}

// CLI success payloads are producer-owned JSON; callers must probe, not assume.
// When a capability is OFF (or for a session-exit) the body is preview-only and
// writes NOTHING — callers probe `.would_run` / `.stub` and an absent key reads
// as "no preview", never a fabricated ledger row.
export type TodoResult = Record<string, unknown>;

// Producer-owned bodies may be empty / non-JSON (an HTML error page, a 204-ish
// empty 200, a truncated proxy response). `resp.json()` THROWS on those, which
// would crash the reader instead of degrading. Parse defensively: a failed/
// absent parse yields `null`, which every reader below coerces to its safe
// fallback (COCKPIT_UNAVAILABLE / {active:false} / {}). Never lets a malformed
// body throw past the client.
async function parseJsonSafe(resp: Response): Promise<unknown> {
  try {
    return await resp.json();
  } catch {
    return null;
  }
}

// --- capability handshake (GET /api/todo/available) ---

export const COCKPIT_UNAVAILABLE: CockpitAvailability = {
  available: false,
  actions: {
    directive_signoff: false,
    authorize_fix: false,
    spawn_topic: false,
    abstain: false,
    calibration: false,
    two_voice_chat: false,
  },
};

// Producer-owned payload — coerce booleans strictly (=== true), never truthy.
function asAvailability(body: unknown): CockpitAvailability {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return COCKPIT_UNAVAILABLE;
  }
  const b = body as Record<string, unknown>;
  const raw =
    b.actions !== null && typeof b.actions === "object" && !Array.isArray(b.actions)
      ? (b.actions as Record<string, unknown>)
      : {};
  return {
    available: b.available === true,
    actions: {
      directive_signoff: raw.directive_signoff === true,
      authorize_fix: raw.authorize_fix === true,
      spawn_topic: raw.spawn_topic === true,
      abstain: raw.abstain === true,
      calibration: raw.calibration === true,
      two_voice_chat: raw.two_voice_chat === true,
    },
  };
}

export async function getCockpitAvailability(): Promise<CockpitAvailability> {
  const resp = await fetch(`${API_BASE}/api/todo/available`);
  // 404 == version skew (the running backend predates /api/todo/*) — a KNOWN
  // capability endpoint missing is quiet degradation, never an error.
  if (resp.status === 404) return { ...COCKPIT_UNAVAILABLE, skew: true };
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return asAvailability(await parseJsonSafe(resp));
}

// --- concurrency guard (GET /api/todo/concurrency) ---

// Producer-owned payload (ui/backend/todo_cockpit.py GET /concurrency) — coerce
// `active` strictly (=== true), never truthy; an absent active_run.json yields
// exactly `{active:false}`. The optional run-describing fields are surfaced only
// when present (the backend OMITS them when absent), so undefined stays
// undefined here rather than being forced to null.
function asConcurrency(body: unknown): ConcurrencyStatus {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return { active: false };
  }
  const b = body as Record<string, unknown>;
  const out: ConcurrencyStatus = { active: b.active === true };
  if (typeof b.kind === "string") out.kind = b.kind;
  if (typeof b.label === "string") out.label = b.label;
  if (typeof b.narration === "string") out.narration = b.narration;
  return out;
}

export async function getConcurrency(): Promise<ConcurrencyStatus> {
  const resp = await fetch(`${API_BASE}/api/todo/concurrency`);
  // Inactive is the safe default: a missing endpoint (skew) means we cannot
  // detect contention, so we do NOT fabricate a warning — fall back to
  // active:false quietly.
  if (resp.status === 404) return { active: false };
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return asConcurrency(await parseJsonSafe(resp));
}

// --- POST helper (mirrors attest.ts's postAttest error handling) ---

async function postTodo(path: string, body: Record<string, unknown>): Promise<TodoResult> {
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
    // An EMPTY-string `detail` ("") is a present-but-illegible producer value
    // (a misbehaving proxy/CLI emitting {"detail": ""}); treat it as ABSENT and
    // fall through to stderr/statusText, matching http.ts errorFromResponse's
    // `if (body.detail)` truthiness contract. A bare `${status} ` message would
    // bury the only legible signal (the status) — the doctrine wants a legible
    // fallback, not an empty error.
    const detail =
      typeof payload?.detail === "string" && payload.detail !== ""
        ? payload.detail
        : stderr ?? `${resp.status} ${resp.statusText}`;
    throw new TodoError(resp.status, detail, rc, stderr);
  }
  // Success body is producer-owned: a non-JSON or non-object 200 (empty body,
  // HTML, a bare scalar/array) must NOT throw or masquerade as a result map.
  // Degrade to an honest empty stub `{}` — callers probe keys (`.would_run`,
  // `.stub`) and an absent key reads as "no preview", never a fabricated row.
  const ok: unknown = await parseJsonSafe(resp);
  if (ok === null || typeof ok !== "object" || Array.isArray(ok)) {
    return {};
  }
  return ok as TodoResult;
}

// --- POST endpoints ---
// Each posts to a thin ui/backend endpoint that shells the blessed orchestrator
// CLI for that outcome: authorize_fix / directive_signoff / calibration are LIVE
// execs gated by their action flag; spawn_topic / abstain are honest
// SESSION-EXITS (no in-UI one-shot). When a capability is OFF the endpoint is
// preview-only: it returns a response that writes NOTHING.

// Outcome 4 — authorize an autonomous fix → enqueue a spawn-contract that a
// later dev session dispatches (stage (i); the human merges the branch). The
// enqueue shape is designed so an autonomous dispatcher can consume it later
// with no schema change (stage (ii)) — but UI approval authorizes the WORK,
// never an unreviewed merge (rule 4 / D-014 runtime firewall). `task` is the
// spawn-contract statement (REQUIRED — the backend 422s without it).
export const postAuthorizeFix = (body: {
  ref_id: string;
  task: string;
  note: string;
}) => postTodo("/api/todo/authorize_fix", body);

// Outcome 1 variant — directive sign-off: sign off a FINDING (status →
// validated) carrying "proceed to <next step>". Keyed on FINDING_ID, not
// iteration_id (docs/cockpit_seam_wiring.md row 1d): the writer is
// `finding_session --set-status <FINDING_ID> validated --directive <next-step>`;
// the directive lands on the status_audit_row only (loop_feedback stays frozen).
// A bare sign-off (no directive) goes through attest.ts /finding_review.
export const postDirectiveSignoff = (body: {
  finding_id: string;
  note: string;
  directive: string;
}) => postTodo("/api/todo/directive_signoff", body);

// Outcome 5 — spawn a follow-up topic. A SESSION-EXIT: the endpoint validates
// and returns the indicator; end_session is the writer of record for the
// finding_followups row. `kind` selects the followup taxonomy
// ("finding" | "step"); `topic` is the follow-up text.
//
// THE ID KEY IS `finding_id`. This posted `ref_id` until 2026-08-19 and 422'd
// on EVERY call ("finding_id is required") — the backend has always read
// `finding_id`, the same key /api/attest/finding_review, /directive_signoff
// and /abstain use for a finding-scoped id. Nothing caught it because every
// test mocked this function instead of the wire; the body-shape pins in
// tests/test_close_out_strip.tsx (real fetch, asserted body) and
// ui/backend/tests/test_todo_cockpit.py (this literal type, posted at the
// real router) are the ones that would.
export const postSpawnTopic = (body: {
  finding_id: string;
  kind: "finding" | "step";
  topic: string;
}) => postTodo("/api/todo/spawn_topic", body);

// Outcome 6 — abstain: no verdict; honest exit; re-look later.
export const postAbstain = (body: {
  finding_id: string;
  note: string;
}) => postTodo("/api/todo/abstain", body);

// Optional blind calibration (ARCH §6.5.4) — persist the human's prediction +
// confidence as a calibration_entry. Opt-in: it no longer gates the verdict (the
// owner may decide without it); the calibration_entry writer landed P4/D-055.
// FLAT body (the backend takes `confidence` as a top-level number in [0,1]),
// not a nested {calibration:{...}}.
export const postCalibration = (body: {
  ref_id: string;
  prediction: string;
  confidence: number;
}) => postTodo("/api/todo/calibration", body);

// --- LIVE chat seam (U2 tutor / U3 two-voice, 2026-06-18 work order) ---
// Exec path over `finding_session chat start|turn` (the ui/backend chat seam).
// The chat is VERDICT-FENCED (start/turn only); the panes are session-local and
// carry NO verdict props. `postChatStart` opens a session (returns session_id +
// stances); `postChatTurn` sends one human-directed turn and returns the reply
// envelope. Errors surface as TodoError (the CLI's stderr verbatim) like the
// other cockpit POSTs.
export const postChatStart = (body: {
  mode: ChatMode;
  finding_id: string;
}): Promise<ChatStartResult> => postTodo("/api/todo/chat/start", body);

export const postChatTurn = (body: {
  mode: ChatMode;
  finding_id: string;
  session_id: string;
  message: string;
  // two_voice only; tutor mode rejects an addressee (single-voice).
  addressee?: "defender" | "attacker" | "both";
}): Promise<ChatTurnResult> => postTodo("/api/todo/chat/turn", body);
