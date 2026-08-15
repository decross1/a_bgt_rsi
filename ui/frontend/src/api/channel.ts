// Lab-channel fetch client for the /api/channel/* endpoints (S4). The
// backend seam execs the ONE blessed CLI (orchestrator.lab_channel) whose
// surface is exactly {timeline, turn, delegate} — no disposition verb exists
// there, so none can exist here (the fence is structural end-to-end).
//
// Mirrors api/todo.ts's idiom: the same API_BASE, the same 404 == version-skew
// quiet degradation (the running :8700 binary may predate /api/channel/*), the
// same {rc, stderr} error envelope (ChannelError carries CLI stderr verbatim
// by DUCK TYPE — `.status`, `.rc`, `.stderr` — not by subclassing HttpError,
// the module-mock hazard attest.ts documents).
import { API_BASE } from "./http";

// One timeline row: stored transcript turns (human/nara/pi) + events derived
// by the CLI at read time (kind "event"). Producer-owned — consumers coerce.
export interface ChannelRow {
  ts: string;
  kind: string; // "human" | "nara" | "pi" | "event" (open set — never assume)
  message: string;
}

export interface ChannelTimeline {
  rows: ChannelRow[];
}

export interface ChannelAvailability {
  available: boolean;
  actions: { timeline: boolean; turn: boolean; delegate: boolean };
  /** True when the running backend predates /api/channel/* (404). */
  skew?: boolean;
}

export interface ChannelTurnResult {
  status?: string; // "passed" | "preview"
  role?: string;
  reply?: string;
  [k: string]: unknown;
}

// delegate returns the CLI's stdout JSON verbatim ({status, kind, rows,
// mirror}) or the preview shape — producer-owned, probe don't assume.
export type ChannelDelegateResult = Record<string, unknown>;

export class ChannelError extends Error {
  readonly status: number;
  /** CLI exit code from a 502 `{rc, stderr}` payload; null otherwise. */
  readonly rc: number | null;
  /** stderr VERBATIM from a 502 payload; null otherwise. Render un-summarized. */
  readonly stderr: string | null;
  readonly detail: string;

  constructor(status: number, detail: string, rc: number | null, stderr: string | null) {
    super(`${status} ${detail}`);
    this.name = "ChannelError";
    this.status = status;
    this.detail = detail;
    this.rc = rc;
    this.stderr = stderr;
  }
}

// Producer-owned bodies may be empty / non-JSON; a failed parse degrades to
// null rather than throwing past the client (api/todo.ts parseJsonSafe idiom).
async function parseJsonSafe(resp: Response): Promise<unknown> {
  try {
    return await resp.json();
  } catch {
    return null;
  }
}

export const CHANNEL_UNAVAILABLE: ChannelAvailability = {
  available: false,
  actions: { timeline: false, turn: false, delegate: false },
};

function asAvailability(body: unknown): ChannelAvailability {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return CHANNEL_UNAVAILABLE;
  }
  const b = body as Record<string, unknown>;
  const raw =
    b.actions !== null && typeof b.actions === "object" && !Array.isArray(b.actions)
      ? (b.actions as Record<string, unknown>)
      : {};
  return {
    available: b.available === true,
    actions: {
      timeline: raw.timeline === true,
      turn: raw.turn === true,
      delegate: raw.delegate === true,
    },
  };
}

export async function getChannelAvailability(): Promise<ChannelAvailability> {
  const resp = await fetch(`${API_BASE}/api/channel/available`);
  // 404 == version skew (the running backend predates /api/channel/*) — quiet
  // degradation to preview-only, never an error.
  if (resp.status === 404) return { ...CHANNEL_UNAVAILABLE, skew: true };
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return asAvailability(await parseJsonSafe(resp));
}

// Coerce the timeline body defensively: a malformed row degrades field-by-
// field (never a crash in the feed); non-object rows are dropped.
function asRows(body: unknown): ChannelRow[] {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return [];
  const raw = (body as { rows?: unknown }).rows;
  if (!Array.isArray(raw)) return [];
  const out: ChannelRow[] = [];
  for (const r of raw as unknown[]) {
    if (r === null || typeof r !== "object" || Array.isArray(r)) continue;
    const o = r as Record<string, unknown>;
    out.push({
      ts: typeof o.ts === "string" ? o.ts : "",
      kind: typeof o.kind === "string" ? o.kind : "?",
      message: typeof o.message === "string" ? o.message : "",
    });
  }
  return out;
}

export async function getChannelTimeline(
  since?: string,
  limit?: number,
): Promise<ChannelTimeline> {
  const params = new URLSearchParams();
  if (since !== undefined && since !== "") params.set("since", since);
  if (limit !== undefined) params.set("limit", String(limit));
  const qs = params.toString();
  const resp = await fetch(
    `${API_BASE}/api/channel/timeline${qs ? `?${qs}` : ""}`,
  );
  if (!resp.ok) {
    const payload = await parseJsonSafe(resp);
    const p =
      payload !== null && typeof payload === "object" && !Array.isArray(payload)
        ? (payload as Record<string, unknown>)
        : null;
    const stderr = typeof p?.stderr === "string" ? p.stderr : null;
    const rc = typeof p?.rc === "number" ? p.rc : null;
    const detail =
      typeof p?.detail === "string" && p.detail !== ""
        ? p.detail
        : (stderr ?? `${resp.status} ${resp.statusText}`);
    // Carries `.status` so the route can route a 404 through the production
    // isVersionSkew404 path (duck-typed, module-mock safe).
    throw new ChannelError(resp.status, detail, rc, stderr);
  }
  return { rows: asRows(await parseJsonSafe(resp)) };
}

async function postChannel(
  path: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const payload = await parseJsonSafe(resp);
    const p =
      payload !== null && typeof payload === "object" && !Array.isArray(payload)
        ? (payload as Record<string, unknown>)
        : null;
    const stderr = typeof p?.stderr === "string" ? p.stderr : null;
    const rc = typeof p?.rc === "number" ? p.rc : null;
    const detail =
      typeof p?.detail === "string" && p.detail !== ""
        ? p.detail
        : (stderr ?? `${resp.status} ${resp.statusText}`);
    throw new ChannelError(resp.status, detail, rc, stderr);
  }
  const ok = await parseJsonSafe(resp);
  if (ok === null || typeof ok !== "object" || Array.isArray(ok)) return {};
  return ok as Record<string, unknown>;
}

export const postChannelTurn = (body: {
  role: "nara" | "pi";
  message: string;
}): Promise<ChannelTurnResult> => postChannel("/api/channel/turn", body);

// Reached ONLY from the delegate confirm-card's confirm click (the page
// enforces that; this function is the single code path that posts).
export const postChannelDelegate = (body: {
  kind: "research" | "improvement";
  text: string;
  cluster_id?: string;
  objective?: string;
}): Promise<ChannelDelegateResult> => postChannel("/api/channel/delegate", body);
