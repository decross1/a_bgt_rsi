import { API_BASE } from "./http";

export type DailyOpsIntent = "question" | "change_request";
export type DailyOpsMessageStatus = "queued" | "delivered" | "acknowledged" | "failed";

export interface DailyOpsMessageRow {
  request_id: string;
  created_at: string;
  actor: "owner" | "oracle" | "system";
  intent: DailyOpsIntent | "reply" | "receipt";
  status: DailyOpsMessageStatus;
  text: string;
  target: "oracle";
  in_reply_to?: string;
  plan_revision: string | null;
}

export interface DailyOpsMessages {
  schema_version: "daily-ops-messages/v1";
  available: boolean;
  writable: boolean;
  rows: DailyOpsMessageRow[];
}

export interface DailyOpsReceipt {
  request_id: string;
  status: "queued";
  accepted_at: string;
  duplicate: boolean;
  expected_plan_revision: string | null;
}

export class DailyOpsError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`${status} ${detail}`);
    this.name = "DailyOpsError";
    this.status = status;
    this.detail = detail;
  }
}

async function bodyOrNull(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function getJson(path: string, accessKey?: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, accessKey ? {
    headers: { Authorization: `Bearer ${accessKey}` },
  } : undefined);
  const body = await bodyOrNull(response);
  if (!response.ok) {
    const detail = body && typeof body === "object" && !Array.isArray(body) &&
      typeof (body as Record<string, unknown>).detail === "string"
      ? String((body as Record<string, unknown>).detail)
      : response.statusText;
    throw new DailyOpsError(response.status, detail || "request failed");
  }
  return body;
}

export const getDailyOpsSummary = (): Promise<unknown> =>
  getJson("/api/daily-ops/summary");

export const getDailyOpsMessages = (accessKey: string): Promise<unknown> =>
  getJson("/api/daily-ops/messages?limit=40", accessKey);

export async function postDailyOpsMessage(input: {
  accessKey: string;
  requestId: string;
  intent: DailyOpsIntent;
  text: string;
  expectedPlanRevision?: string;
}): Promise<DailyOpsReceipt> {
  const response = await fetch(`${API_BASE}/api/daily-ops/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${input.accessKey}`,
    },
    body: JSON.stringify({
      request_id: input.requestId,
      target: "oracle",
      intent: input.intent,
      text: input.text,
      ...(input.expectedPlanRevision
        ? { expected_plan_revision: input.expectedPlanRevision }
        : {}),
    }),
  });
  const body = await bodyOrNull(response);
  if (!response.ok) {
    const detail = body && typeof body === "object" && !Array.isArray(body) &&
      typeof (body as Record<string, unknown>).detail === "string"
      ? String((body as Record<string, unknown>).detail)
      : response.statusText;
    throw new DailyOpsError(response.status, detail || "request failed");
  }
  return body as DailyOpsReceipt;
}
