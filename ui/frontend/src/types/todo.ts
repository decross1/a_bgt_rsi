// Cockpit (/todo) TS types — the leaf data layer the uncertainty-resolution
// cockpit components import (Role B foundation; see the 2026-06-14 session note
// "## UI session work order" PART 2). These describe the SIX resolution
// outcomes, the cockpit's NEW stub-endpoint payloads, the pre-verdict
// calibration capture (ARCH §6.5.4), the two-voice chat stub, and the
// concurrency guard.
//
// IMPORTANT — STUB SEMANTICS (inviolate rule 4): the NEW outcomes
// (authorize_fix, the directive sign-off, spawn_topic, abstain) and the chat
// pane light up only when the PART-2 primary-session seams land
// (docs/todo_cockpit_seam_plan.md). Until then ui/backend serves these as
// honest STUBS that NEVER write a ledger or fake a verdict — they surface the
// would-run argv read-only. The FOUR already-blessed outcomes (gate_verdict,
// finding_review, bubble_ack, defer) are NOT here: the cockpit reuses
// api/attest.ts directly for those.
//
// HumanTodoItem is IMPORTED from types/schemas.ts — not redefined here.
// Re-exported for the cockpit's convenience so a panel imports one module.
import type { HumanTodoItem } from "./schemas";

export type { HumanTodoItem };

// --- the six resolution outcomes (the cockpit's outcome taxonomy) ---
// 'sign_off'     → verdict ledger + journal (MAY carry a directive)  [mostly exists → attest.ts]
// 'reject'       → invalid verdict; generator steers away            [exists → attest.ts]
// 'refine_defer' → enqueue dev_session_queue via todo_cli defer      [exists → attest.ts]
// 'authorize_fix'→ enqueue a spawn-contract (coding agent → branch)  [NET-NEW, gated — STUB]
// 'spawn_topic'  → finding_followups queue                           [exists; NEW cockpit argv — STUB]
// 'abstain'      → no verdict; honest exit; re-look later            [NEW — STUB]
export type ResolutionOutcome =
  | "sign_off"
  | "reject"
  | "refine_defer"
  | "authorize_fix"
  | "spawn_topic"
  | "abstain";

export const RESOLUTION_OUTCOMES: readonly ResolutionOutcome[] = [
  "sign_off",
  "reject",
  "refine_defer",
  "authorize_fix",
  "spawn_topic",
  "abstain",
];

// --- capability handshake (mirrors GET /api/todo/available) ---
// Per-outcome booleans, mirroring api/attest.ts's AttestAvailable idiom. The
// NEW seams report `false` until their primary-session CLI lands; a `false`
// (or a 404 version-skew) keeps the form in its honest stub state — never an
// error. The four already-blessed outcomes' availability still flows through
// api/attest.ts's own handshake; these flags cover only the cockpit-NEW seams.
export interface CockpitActions {
  /** sign-off WITH an optional directive ("proceed to <next step>") — the NEW
   *  --directive variant of the sign-off path (the bare sign-off is attest). */
  directive_signoff: boolean;
  /** outcome 4 — enqueue a spawn-contract for an autonomous coding agent. */
  authorize_fix: boolean;
  /** outcome 5 — cockpit-driven spawn_topic → finding_followups. */
  spawn_topic: boolean;
  /** outcome 6 — abstain (no verdict; honest exit). */
  abstain: boolean;
  /** pre-verdict calibration capture (ARCH §6.5.4 calibration_entry). */
  calibration: boolean;
  /** two-voice (Gemma defends / Qwen attacks) interrogation chat. */
  two_voice_chat: boolean;
}

export interface CockpitAvailability {
  available: boolean;
  actions: CockpitActions;
  /** True when unavailability came from a version-skew 404 (the running
   *  backend predates /api/todo/*), distinct from a 200 answering
   *  available:false (a seam CLI not yet present under the primary repo). */
  skew?: boolean;
}

// --- pre-verdict calibration (ARCH §6.5.4 / research_program_v2 red-flag) ---
// Captured FIRST, before the verdict form opens — the human's prediction +
// confidence about the finding. Persisted as a `calibration_entry` run-log
// event via the calibration CLI; the UI never writes it.
export interface CalibrationDraft {
  /** the human's prediction about the finding (free text). */
  prediction: string;
  /** confidence 0–1. The cockpit captures this BEFORE the verdict opens. */
  confidence: number;
}

// --- two-voice chat stub (D-044 independence: Gemma DEFENDS, Qwen ATTACKS) ---
// A single rendered turn in the human-DRIVEN interrogation pane. The human
// directs the flow and may address either or both voices — NOT a spectator
// debate. This is the STUB shape; the live transcript is the two-stance
// extension of orchestrator/finding_session.py (a PART-2 seam). `addressee`
// records who the human aimed a turn at (or whose turn this is).
export interface ChatTurn {
  /** which model voice — defender (Gemma) or attacker (Qwen). */
  stance: "defender" | "attacker";
  /** who this turn addresses ('human' | 'defender' | 'attacker' | 'both'). */
  addressee: "human" | "defender" | "attacker" | "both";
  text: string;
}

// --- LIVE chat seam (U2/U3, 2026-06-18 work order) ---
// The single-line JSON envelope `orchestrator/finding_session.py` `chat
// start|turn` emits (via the ui/backend chat exec path). The chat is
// VERDICT-FENCED: only `start` and `turn` exist (no disposition verb).
// `tutor` mode is single-voice (`stances:null`, replies carry `stance:null`,
// no `addressee`); `two_voice` carries the two-stance object + an `addressee`.
// Every field is producer-owned (CLI stdout) — defensive-optional.
export type ChatMode = "tutor" | "two_voice";

// One model reply within a turn. `stance` is null in tutor mode; "defender"
// (Gemma) / "attacker" (Qwen) in two_voice. Index signature stays
// forward-compatible with extra envelope keys.
export interface ChatReply {
  stance?: string | null;
  reply?: string | null;
  request_id?: string | null;
  [key: string]: unknown;
}

// `chat start` envelope. `session_id` threads into every subsequent turn;
// `stances` is null (tutor) or the two-stance object (two_voice).
export interface ChatStartResult {
  ok?: boolean;
  mode?: string;
  action?: "start" | string;
  finding_id?: string;
  session_id?: string;
  stances?: unknown;
  [key: string]: unknown;
}

// `chat turn` envelope. `addressee`/`warning` appear only in two_voice;
// `capped` flags the turn/token cap; `replies` is the model output(s).
export interface ChatTurnResult {
  ok?: boolean;
  mode?: string;
  action?: "turn" | string;
  finding_id?: string;
  session_id?: string;
  turn_index?: number | null;
  capped?: boolean | null;
  addressee?: string | null;
  warning?: string | null;
  replies?: ChatReply[];
  [key: string]: unknown;
}

// --- concurrency guard (mirrors GET /api/todo/concurrency) ---
// The loop and the cockpit reuse the SAME models (Gemma gen+defend; Qwen
// skeptic+attack). When an iteration is mid-flight the cockpit shows an
// explicit warn/queue guard. This is the BACKEND shape verbatim
// (ui/backend/todo_cockpit.py GET /concurrency): `active: false` == no
// contention (and an absent active_run.json yields exactly `{active:false}`).
// When mid-flight, `kind` / `label` / `narration` describe the contending run
// (sourced from run_state/active_run.json, the same mirror the model-health
// panels read); each is OMITTED by the backend when absent, so they are
// optional + nullable here.
export interface ConcurrencyStatus {
  active: boolean;
  /** the run kind (e.g. "loop_v0"), when mid-flight; absent/null when idle. */
  kind?: string | null;
  /** a human-facing run label for the contending run; absent/null when idle. */
  label?: string | null;
  /** the run's current narration the cockpit renders in the warn banner. */
  narration?: string | null;
}
