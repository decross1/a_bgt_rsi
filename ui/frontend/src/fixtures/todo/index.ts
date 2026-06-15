// Typed fixtures for the /todo cockpit (Role B foundation). Panels and tests
// import these to bypass the network. They are hand-rolled to the types in
// types/todo.ts; the test_todo_foundation.tsx suite asserts they stay type-
// and value-aligned. NOTE the NEW-seam availability flags are FALSE here — the
// cockpit's NEW outcomes are stubs until the PART-2 primary-session seams land
// (docs/todo_cockpit_seam_plan.md), and the fixture reflects that honest state.
import type {
  CalibrationDraft,
  ChatTurn,
  CockpitAvailability,
  ConcurrencyStatus,
  HumanTodoItem,
} from "../../types/todo";

// Capability with every NEW seam OFF — the default the cockpit renders against
// today: each NEW-outcome form sits in its honest "stub — lights up when the
// <named> primary seam lands" state. `available` is false because no NEW seam
// is live yet.
export const AVAILABILITY_STUB: CockpitAvailability = {
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

// Forward-looking: the shape once ALL the PART-2 seams have landed. Not the
// default; here so a test/preview can exercise the "lit up" branch.
export const AVAILABILITY_LIVE: CockpitAvailability = {
  available: true,
  actions: {
    directive_signoff: true,
    authorize_fix: true,
    spawn_topic: true,
    abstain: true,
    calibration: true,
    two_voice_chat: true,
  },
};

// A couple of HumanTodoItems — taxonomy A (gate_verdict, judgment) and B
// (state_file_gate, blocking halt), the two kinds the dashboard's idle-hero N
// counts. Reuses the imported HumanTodoItem (NOT redefined).
export const TODO_ITEMS: HumanTodoItem[] = [
  {
    kind: "gate_verdict",
    id: "iter-2026-06-14-002",
    title: "Verdict needed: novel_on_02 over-gated by primary R0",
    since: "2026-06-14T15:00:00Z",
    detail: "Primary topicality judge condemned a novel on-domain claim.",
    resolve_command:
      ".venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id "
      + "iter-2026-06-14-002 --verdict valid --note <why> --gated-by human:ui",
  },
  {
    kind: "state_file_gate",
    id: "gate-d049-ratification",
    title: "State-file gate: D-049 scheduled cycles await human ratification",
    since: "2026-06-13T09:30:00Z",
    detail: "Presence of run_state/d049_ratified gates the coordinator cycle.",
  },
];

// Pre-verdict calibration draft (ARCH §6.5.4) — prediction + confidence.
export const CALIBRATION_DRAFT: CalibrationDraft = {
  prediction: "This finding survives the Qwen attack panel 2/3.",
  confidence: 0.6,
};

// Concurrency: idle (no contention) and a mid-flight sample (a loop_v0
// iteration is running on the shared models, so the cockpit warns/queues).
// These mirror the BACKEND shape (ui/backend/todo_cockpit.py GET /concurrency):
// `active:false` is the exact idle body an absent active_run.json yields; the
// mid-flight body surfaces kind/label/narration from run_state/active_run.json.
export const CONCURRENCY_IDLE: ConcurrencyStatus = {
  active: false,
};

export const CONCURRENCY_MIDFLIGHT: ConcurrencyStatus = {
  active: true,
  kind: "loop_v0",
  label: "loop_v0-2026-06-14-002",
  narration: "A LOOP_V0 iteration is mid-flight on the shared models (Gemma/Qwen).",
};

// Two chat-turn stubs for the two-voice pane: Gemma DEFENDS, Qwen ATTACKS
// (D-044 independence). Human-driven, not a spectator debate.
export const CHAT_TURNS_STUB: ChatTurn[] = [
  {
    stance: "defender",
    addressee: "human",
    text:
      "Defender (Gemma): the claim holds — the residual on novel_on_02 is a "
      + "primary-judge over-gate, not a substantive falsification.",
  },
  {
    stance: "attacker",
    addressee: "defender",
    text:
      "Attacker (Qwen): then show the on-domain anchor it cited — an "
      + "over-gate still leaves the topicality dissent unaddressed.",
  },
];
