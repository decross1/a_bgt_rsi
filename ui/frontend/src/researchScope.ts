import { useLocation } from "react-router-dom";

export type ResearchScope = "active" | "all";

export interface ResearchCampaignScope {
  campaign_id: string;
  title: string;
  research_question: string;
  manifest_sha256: string;
  activated_at: string;
}

export interface ResearchScopeMetadata {
  mode: ResearchScope;
  status: "active" | "no_active_campaign" | "all_research";
  campaign: ResearchCampaignScope | null;
  history_preserved: boolean;
  omitted_historical_items?: number;
  global_safety_gates_retained?: boolean;
  omitted_clusters?: number;
}

export function researchScopeFromSearch(search: string): ResearchScope {
  return new URLSearchParams(search).get("research_scope") === "all"
    ? "all"
    : "active";
}

export function browserResearchScope(): ResearchScope {
  return typeof window === "undefined"
    ? "active"
    : researchScopeFromSearch(window.location.search);
}

export function useResearchScope(): ResearchScope {
  return researchScopeFromSearch(useLocation().search);
}

/** Add an explicit scope to an API path. Research API calls never rely on the
 * backend's backwards-compatible `all` default. */
export function scopedResearchApiPath(
  path: string,
  scope: ResearchScope,
): string {
  const url = new URL(path, "http://research-scope.local");
  url.searchParams.set("research_scope", scope);
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Preserve unrelated query/hash state while changing the research view.
 * `active` is the product default and therefore keeps the URL clean. */
export function researchScopedHref(
  target: string,
  scope: ResearchScope,
): string {
  const url = new URL(target, "http://research-scope.local");
  if (scope === "all") url.searchParams.set("research_scope", "all");
  else url.searchParams.delete("research_scope");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function currentPageScopeHref(
  pathname: string,
  search: string,
  hash: string,
  scope: ResearchScope,
): string {
  return researchScopedHref(`${pathname}${search}${hash}`, scope);
}

export function historySuffix(scope: ResearchScope): string {
  return scope === "all" ? " · history" : "";
}
