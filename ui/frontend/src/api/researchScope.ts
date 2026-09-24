import {
  scopedResearchApiPath,
  type ResearchCampaignScope,
  type ResearchScope,
  type ResearchScopeMetadata,
} from "../researchScope";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function admitCampaign(value: unknown): ResearchCampaignScope {
  if (!isObject(value)) throw new Error("Research scope integrity error: campaign must be an object");
  for (const key of [
    "campaign_id",
    "title",
    "research_question",
    "manifest_sha256",
    "activated_at",
  ] as const) {
    if (!nonEmptyString(value[key])) {
      throw new Error(`Research scope integrity error: campaign.${key} is missing`);
    }
  }
  return value as unknown as ResearchCampaignScope;
}

export function admitResearchScopeMetadata(
  value: unknown,
  requested: ResearchScope,
): ResearchScopeMetadata {
  if (!isObject(value) || value.mode !== requested || value.history_preserved !== true) {
    throw new Error("Research scope integrity error: response identity is invalid");
  }
  if (requested === "all") {
    if (value.status !== "all_research" || value.campaign !== null) {
      throw new Error("Research scope integrity error: all-history response is invalid");
    }
    return value as unknown as ResearchScopeMetadata;
  }
  if (
    (value.status === "closed" || value.status === "no_active_campaign")
    && value.campaign === null
  ) {
    return value as unknown as ResearchScopeMetadata;
  }
  if (value.status !== "active") {
    throw new Error("Research scope integrity error: active status is invalid");
  }
  return {
    ...(value as unknown as ResearchScopeMetadata),
    campaign: admitCampaign(value.campaign),
  };
}

/**
 * Prove that a successful list response belongs to the requested research
 * view before any records are rendered.  This is load bearing for the active
 * view: an older backend ignores the query parameter and returns global
 * history with no identity envelope.  Treating that payload as current would
 * silently relabel historical work.
 *
 * The all-history API remains backwards compatible.  Current backends omit an
 * envelope for `all`; when a future backend supplies one, validate it.
 */
export function admitScopedResearchPayload<T>(
  value: T,
  requested: ResearchScope,
): T {
  if (!isObject(value)) {
    throw new Error("Research scope integrity error: response must be an object");
  }
  const metadata = value.research_scope;
  if (requested === "active") {
    admitResearchScopeMetadata(metadata, requested);
  } else if (metadata !== undefined) {
    admitResearchScopeMetadata(metadata, requested);
  }
  return value;
}

export async function getResearchScope(
  scope: ResearchScope,
): Promise<ResearchScopeMetadata> {
  const path = scopedResearchApiPath("/api/research_scope", scope);
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The status still establishes failure when the body is not JSON.
    }
    throw new Error(`${response.status} ${detail}`.trim());
  }
  return admitResearchScopeMetadata(await response.json(), scope);
}
