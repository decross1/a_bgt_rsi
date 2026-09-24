import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { getResearchScope } from "../api/researchScope";
import {
  currentPageScopeHref,
  researchScopedHref,
  useResearchScope,
  type ResearchScope,
  type ResearchScopeMetadata,
} from "../researchScope";
import "./researchScope.css";

interface ResearchScopeBarProps {
  /** Fixture-backed route renders can keep their no-network contract. */
  fetchMetadata?: boolean;
  initialMetadata?: ResearchScopeMetadata | null;
  className?: string;
  /** A source-library detail may be all-history even when reached through an
   * unqualified URL.  The override keeps its identity selector truthful. */
  scopeOverride?: ResearchScope;
  activeTarget?: string;
  allTarget?: string;
  activeHrefOverride?: string;
  allHrefOverride?: string;
  /** Route-specific boundary text can replace the generic archive note while
   * staying inside the single scope panel. */
  historyExplanation?: string;
  /** Detail readers lead with their source-bound overview, so campaign
   * context stays to one compact identity line above it. */
  compact?: boolean;
}

export default function ResearchScopeBar({
  fetchMetadata = true,
  initialMetadata,
  className = "",
  scopeOverride,
  activeTarget,
  allTarget,
  activeHrefOverride,
  allHrefOverride,
  historyExplanation,
  compact = false,
}: ResearchScopeBarProps) {
  const location = useLocation();
  const routeScope = useResearchScope();
  const scope = scopeOverride ?? routeScope;
  const [metadata, setMetadata] = useState<ResearchScopeMetadata | null>(
    initialMetadata ?? null,
  );
  const [loading, setLoading] = useState(
    fetchMetadata && initialMetadata === undefined,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fetchMetadata || initialMetadata !== undefined) {
      setMetadata(initialMetadata ?? null);
      setLoading(false);
      setError(null);
      return;
    }
    let current = true;
    // A scope change can never retain the prior scope's identity while the
    // new request is in flight. The selector itself uses a document reload,
    // and this reset also covers browser history/client-side navigation.
    setMetadata(null);
    setLoading(true);
    setError(null);
    getResearchScope(scope)
      .then((next) => {
        if (!current) return;
        setMetadata(next);
        setLoading(false);
      })
      .catch((reason) => {
        if (!current) return;
        setError(String(reason));
        setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [fetchMetadata, initialMetadata, scope]);

  const activeHref = activeHrefOverride ?? (activeTarget === undefined
    ? currentPageScopeHref(
      location.pathname,
      location.search,
      location.hash,
      "active",
    )
    : researchScopedHref(activeTarget, "active"));
  const allHref = allHrefOverride ?? (allTarget === undefined
    ? currentPageScopeHref(
      location.pathname,
      location.search,
      location.hash,
      "all",
    )
    : researchScopedHref(allTarget, "all"));

  return (
    <section
      aria-label="Research scope"
      className={`research-scope-bar ${className}`.trim()}
      data-compact={compact ? "true" : "false"}
      data-mode={scope}
      data-testid="research-scope-bar"
    >
      <div className="research-scope-bar__topline">
        <div>
          <p className="research-scope-bar__eyebrow">Research view</p>
          <nav aria-label="Choose research view" className="research-scope-bar__switch">
            <a
              aria-current={scope === "active" ? "page" : undefined}
              className="research-scope-bar__choice"
              data-selected={scope === "active" ? "true" : "false"}
              href={activeHref}
            >
              Current campaign
            </a>
            <a
              aria-current={scope === "all" ? "page" : undefined}
              className="research-scope-bar__choice"
              data-selected={scope === "all" ? "true" : "false"}
              href={allHref}
            >
              All research history
            </a>
          </nav>
        </div>
        <span className="research-scope-bar__boundary">
          {scope === "active" ? "Exact campaign links" : "Preserved archive"}
        </span>
      </div>

      {loading && (
        <p className="research-scope-bar__status" role="status">
          Resolving {scope === "active" ? "active campaign identity" : "history boundary"}…
        </p>
      )}
      {error !== null && (
        <p className="research-scope-bar__error" role="alert" data-testid="research-scope-error">
          {scope === "active"
            ? "Current campaign identity is unavailable. Historical research has not been substituted."
            : "Research history scope is unavailable."}{" "}
          <span>{error}</span>
        </p>
      )}
      {!loading && error === null && metadata?.mode === "active" && metadata.status === "active" && metadata.campaign !== null && (
        <div className="research-scope-bar__campaign" data-testid="research-scope-campaign">
          <div>
            <strong>{metadata.campaign.title}</strong>
            {compact ? <p className="research-scope-bar__execution-note">
              Campaign context for the exact record below. Human-action requests and execution remain separate.
            </p> : <>
              <p>{metadata.campaign.research_question}</p>
              <p className="research-scope-bar__execution-note">
                Current identifies the campaign pointer. It does not establish queued or running work; execution state is reported separately in the Lab queue.
              </p>
            </>}
          </div>
          <code title={metadata.campaign.manifest_sha256}>{metadata.campaign.campaign_id}</code>
        </div>
      )}
      {!loading && error === null && metadata?.mode === "active" && metadata.status === "no_active_campaign" && (
        <p className="research-scope-bar__status" data-testid="research-scope-none">
          No active campaign is recorded. Current-campaign lists remain empty; history is available explicitly.
        </p>
      )}
      {!loading && error === null && metadata?.mode === "active" && metadata.status === "closed" && (
        <p className="research-scope-bar__status" data-testid="research-scope-closed">
          This campaign is closed. Current-campaign lists remain empty; history is available explicitly.
        </p>
      )}
      {!loading && error === null && metadata?.mode === "all" && (
        <p className="research-scope-bar__status" data-testid="research-scope-history">
          {historyExplanation ?? "Showing preserved v0/v1 and campaign records. This view keeps their recorded identity and does not make them current."}
        </p>
      )}
      {!fetchMetadata && metadata === null && (
        <p
          className="research-scope-bar__status"
          data-testid={scope === "all" ? "research-scope-history" : undefined}
        >
          {scope === "active"
            ? "Current-campaign fixture view."
            : historyExplanation ?? "All-history fixture view."}
        </p>
      )}
    </section>
  );
}
