import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { dossierIdOf, isKilled } from "./ladderModel";
import {
  researchContextForEntry,
  researchEntriesForFamily,
} from "./researchContext";
import type {
  ResearchClaimContext,
  ResearchClaimEntry,
} from "./researchContext";
import type { FamilyRecord, ThesisFamily, ThesisModel } from "./thesisModel";

const FAMILY_OPTION_LIMIT = 40;
const CLAIM_LIMIT = 3;

const META: React.CSSProperties = {
  margin: 0,
  color: "var(--fg-muted)",
  fontSize: "var(--text-meta)",
};

const LABEL: React.CSSProperties = {
  margin: 0,
  color: "var(--fg-muted)",
  fontSize: "var(--text-meta)",
  fontWeight: "var(--weight-semibold)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

interface FamilyOption {
  key: string;
  family: ThesisFamily;
  label: string;
  searchText: string;
}

function recordIdentity(record: FamilyRecord): string {
  return record.hasUniqueSourceId
    ? `source record ${record.id}`
    : `unverified snapshot ${record.unverifiedSnapshotNumber ?? record.key}`;
}

function familyOptionLabel(family: ThesisFamily): string {
  if (family.id.startsWith("record:")) {
    const record = family.records[0];
    return record === undefined
      ? `${family.title} — individual record with unavailable identity`
      : `${family.title} — individual ${recordIdentity(record)}`;
  }
  return `${family.title} — collection · ${family.records.length} ${family.records.length === 1 ? "record" : "records"}`;
}

function claimKey(context: ResearchClaimContext): string {
  return JSON.stringify([context.record.key, context.iterationId]);
}

function matchesFamily(option: FamilyOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (needle === "" || option.searchText.includes(needle)) return true;
  // Search already received text lazily; no raw outcome reads or combined
  // unbounded search document. The visible selector remains bounded.
  return option.family.records.some((record) =>
    [record.id, record.title].some((value) => value.toLowerCase().includes(needle))
    || record.iterations.some((iteration) => [iteration.id, iteration.hypothesis ?? ""]
      .some((value) => value.toLowerCase().includes(needle))));
}

function claimAccessibleName(context: ResearchClaimContext): string {
  const kind = context.isPinnedExactClaim ? "source-bound claim" : "recorded entry";
  return `Select ${kind}, ${recordIdentity(context.record)}, iteration ${context.iterationId}: ${context.shortLabel}`;
}

function domToken(value: string): string {
  return value.replace(/[^A-Za-z0-9_.:-]+/g, "-").slice(0, 80);
}

function evidenceHeadline(context: ResearchClaimContext): string {
  const outcome = context.iteration?.source.experiment_outcome;
  if (outcome !== undefined && outcome !== null) {
    return "Recorded outcome supplied; exact claim binding and evidence validity remain unverified.";
  }
  if (isKilled(context.record.cluster)) {
    return "Recorded negative history; exact evidence validity remains unknown.";
  }
  if (context.isPinnedExactClaim) {
    return "No compatible test recorded in the dated source assessment.";
  }
  return "No outcome is established by this projection.";
}

function nextTestText(context: ResearchClaimContext): string {
  if (context.proposedTest !== undefined) return context.proposedTest;
  if (context.stageRequirement !== undefined) {
    return `No claim-specific accepted test is supplied. Generic stage requirement: ${context.stageRequirement}`;
  }
  return "No claim-specific next test is supplied in this projection.";
}

function EvidenceLines({
  title,
  lines,
}: {
  title: string;
  lines: ResearchClaimContext["supportingEvidence"];
}) {
  if (lines.length === 0) return null;
  return (
    <section style={{ marginTop: "var(--space-4)" }}>
      <h4 style={LABEL}>{title}</h4>
      <dl style={{ margin: "var(--space-2) 0 0" }}>
        {lines.map((line, index) => (
          <div key={`${line.label}-${index}`} style={{ marginTop: index === 0 ? 0 : "var(--space-2)" }}>
            <dt style={{ color: "var(--fg)", fontSize: "var(--text-meta)", fontWeight: "var(--weight-semibold)" }}>
              {line.label}
            </dt>
            <dd style={{ ...META, marginTop: "2px", overflowWrap: "anywhere" }}>{line.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ClaimContext({ context, onBack }: { context?: ResearchClaimContext; onBack: () => void }) {
  if (context === undefined) {
    return (
      <aside className="research-canvas__context" data-testid="research-canvas-context">
        <button type="button" className="research-canvas__back" onClick={onBack} data-testid="research-canvas-back">
          ← Back to thesis
        </button>
        <p style={META}>No recorded claim entry is available for this thesis.</p>
      </aside>
    );
  }

  const dossierId = dossierIdOf(context.iterationId);
  return (
    <aside
      id="research-canvas-selected-context"
      className="research-canvas__context"
      data-testid="research-canvas-context"
      aria-labelledby="research-canvas-context-title"
    >
      <button type="button" className="research-canvas__back" onClick={onBack} data-testid="research-canvas-back">
        ← Back to thesis
      </button>
      <p style={{ ...LABEL, color: "var(--group-research)" }}>Selected claim</p>
      <h3
        id="research-canvas-context-title"
        style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", fontSize: "var(--text-title)", lineHeight: 1.3 }}
      >
        {context.shortLabel}
      </h3>
      <p style={{ margin: "var(--space-3) 0 0", color: "var(--fg)", fontSize: "var(--text-prose-lg)", lineHeight: 1.5 }}>
        {context.summary}
      </p>

      <div className="research-canvas__standing" data-testid="research-canvas-standing">
        <span aria-hidden="true" className="research-canvas__status-dot" />
        {context.claimStanding}
      </div>

      <section className="research-canvas__context-section">
        <h4 style={LABEL}>Evidence now</h4>
        <p data-testid="research-canvas-evidence-state" style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", lineHeight: 1.45 }}>
          {evidenceHeadline(context)}
        </p>
      </section>

      <section className="research-canvas__context-section">
        <h4 style={LABEL}>Next test</h4>
        <p style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", lineHeight: 1.45 }}>
          {context.proposedTest === undefined
            ? "No claim-specific accepted test is supplied."
            : "Model and measurement decisions come first. The dated proposal remains unadopted."}
        </p>
      </section>

      {dossierId !== null && (
        <Link className="research-canvas__dossier" to={`/dossier/${dossierId}`} aria-label={`Open full dossier for ${dossierId}`}>
          Open full dossier ↗
        </Link>
      )}

      <details className="research-canvas__source" data-testid="research-canvas-source-details">
        <summary>Source qualification and recorded fields</summary>
        <p style={{ ...META, marginTop: "var(--space-3)" }}>
          These fields come from the received Ladder and iteration projections. Collection membership is association only; it does not establish evidence, equivalence, causality or progress. Reviews and outcomes are not authenticated here as valid or claim-bound.
        </p>
      <section className="research-canvas__context-section">
        <h4 style={LABEL}>Known blocker</h4>
        <p style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", lineHeight: 1.45 }}>{context.blocker}</p>
      </section>

      <section className="research-canvas__context-section">
        <h4 style={LABEL}>{context.proposedTest === undefined ? "Next test state" : "Proposed next test"}</h4>
        <p style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", lineHeight: 1.45 }}>{nextTestText(context)}</p>
        {context.proposedTest !== undefined && (
          <p style={{ ...META, marginTop: "var(--space-2)" }}>Dated 2026-09-07 engineering proposal · not an adopted protocol</p>
        )}
      </section>
        <dl className="research-canvas__axes">
          <div><dt>Claim standing</dt><dd>{context.claimStanding}</dd></div>
          <div><dt>Application fit</dt><dd>{context.applicationFit}</dd></div>
          <div><dt>Evidence validity</dt><dd>{context.evidenceValidity}</dd></div>
          <div><dt>Execution mode</dt><dd>{context.executionMode}</dd></div>
        </dl>
        <section style={{ marginTop: "var(--space-4)" }}>
          <h4 style={LABEL}>Full recorded hypothesis</h4>
          <p style={{ margin: "var(--space-2) 0 0", color: "var(--fg)", lineHeight: 1.5 }}>{context.hypothesis}</p>
          <p className="font-mono" style={{ ...META, marginTop: "var(--space-2)", overflowWrap: "anywhere" }}>
            {context.iterationId} · source ended {context.sourceEndedAt} · event {context.recordedEventAt}
          </p>
        </section>
        <EvidenceLines title="Raw recorded outcome" lines={context.rawOutcome} />
        <EvidenceLines title="Limiting or negative evidence" lines={context.limitingEvidence} />
        <EvidenceLines title="Recorded producer reviews" lines={context.supportingEvidence} />
        <EvidenceLines title="Present raw provenance fields" lines={context.provenanceFields} />
        <section style={{ marginTop: "var(--space-4)" }}>
          <h4 style={LABEL}>Evidence delta</h4>
          <p style={{ ...META, marginTop: "var(--space-2)" }}>{context.evidenceDelta}</p>
        </section>
      </details>
    </aside>
  );
}

function orderEntries(entries: ResearchClaimEntry[]): ResearchClaimEntry[] {
  const pinned: ResearchClaimEntry[] = [];
  const other: ResearchClaimEntry[] = [];
  for (const entry of entries) (entry.isPinnedExactClaim ? pinned : other).push(entry);
  return [...pinned, ...other];
}

export default function ResearchCanvas({
  model,
  nextOwed,
}: {
  model: ThesisModel;
  nextOwed: Record<string, string>;
}) {
  const rootRef = useRef<HTMLElement>(null);
  const previousMobile = useRef(false);
  const searchId = useId();
  const selectId = useId();
  const familyOptions = useMemo<FamilyOption[]>(() => model.families.map((family) => {
    const label = familyOptionLabel(family);
    return {
      key: family.id,
      family,
      label,
      searchText: [label, family.id, family.basis, ...family.topicLabels].join(" ").toLowerCase(),
    };
  }), [model.families]);
  const preferred = familyOptions.find((option) => option.family.id === "collection:liquid-democracy") ?? familyOptions[0];
  // A null choice follows the best family in the latest source snapshot. This
  // lets separately arriving Ladder/topic payloads promote the real collection
  // without pinning a transient first record. An explicit user choice is kept
  // only while that exact family key still exists.
  const [chosenFamilyKey, setChosenFamilyKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [chosenClaim, setChosenClaim] = useState<{ familyId: string; key: string } | null>(null);
  const [mobileContext, setMobileContext] = useState(false);
  const selectedFamilyOption = familyOptions.find((option) => option.key === chosenFamilyKey) ?? preferred;
  const selectedFamily = selectedFamilyOption?.family;

  const matchingFamilyOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = needle.length === 0
      ? familyOptions
      : familyOptions.filter((option) => matchesFamily(option, needle));
    const visible = matches.slice(0, FAMILY_OPTION_LIMIT);
    if (selectedFamilyOption !== undefined && !visible.some((option) => option.key === selectedFamilyOption.key)) {
      return [selectedFamilyOption, ...visible.slice(0, FAMILY_OPTION_LIMIT - 1)];
    }
    return visible;
  }, [familyOptions, query, selectedFamilyOption]);

  const entries = useMemo(
    () => selectedFamily === undefined ? [] : researchEntriesForFamily(selectedFamily),
    [selectedFamily],
  );
  const orderedEntries = useMemo(() => orderEntries(entries), [entries]);
  const visibleEntries = useMemo(() => orderedEntries.slice(0, CLAIM_LIMIT), [orderedEntries]);
  const visibleContexts = useMemo(
    () => visibleEntries.map((entry) => researchContextForEntry(entry, nextOwed)),
    [visibleEntries, nextOwed],
  );
  const activeContext = visibleContexts.find((context) => chosenClaim?.familyId === selectedFamily?.id && claimKey(context) === chosenClaim.key) ?? visibleContexts[0];

  const chooseFamily = (key: string) => {
    setChosenFamilyKey(key);
    setMobileContext(false);
  };
  const chooseClaim = (key: string) => {
    if (selectedFamily !== undefined) setChosenClaim({ familyId: selectedFamily.id, key });
    setMobileContext(true);
  };

  useEffect(() => {
    if (chosenFamilyKey !== null && !familyOptions.some((option) => option.key === chosenFamilyKey)) {
      setChosenFamilyKey(null);
    }
    if (chosenClaim !== null && (
      !familyOptions.some((option) => option.family.id === chosenClaim.familyId)
      || (selectedFamily?.id === chosenClaim.familyId
        && !entries.some((entry) => JSON.stringify([entry.record.key, entry.iteration?.id ?? "iteration unavailable"]) === chosenClaim.key))
    )) setChosenClaim(null);
  }, [familyOptions, chosenFamilyKey, chosenClaim, selectedFamily?.id, entries]);

  useEffect(() => {
    const wasContext = previousMobile.current;
    previousMobile.current = mobileContext;
    if (window.innerWidth > 760) return;
    if (mobileContext) {
      rootRef.current?.querySelector<HTMLButtonElement>(".research-canvas__back")?.focus();
    } else if (wasContext) {
      rootRef.current?.querySelector<HTMLButtonElement>('.research-canvas__claim[aria-pressed="true"]')?.focus();
    }
  }, [mobileContext, activeContext?.key]);

  if (preferred === undefined) {
    return (
      <section className="research-canvas" data-testid="research-canvas">
        <h2 style={{ margin: 0, color: "var(--fg)", fontSize: "var(--text-title-lg)" }}>Research canvas</h2>
        <p style={{ ...META, marginTop: "var(--space-2)" }}>No thesis collections are available in the received sources.</p>
      </section>
    );
  }

  return (
    <section
      ref={rootRef}
      className="research-canvas"
      data-testid="research-canvas"
      data-mobile-view={mobileContext ? "context" : "membership"}
    >
      <style>{`
        .research-canvas { color: var(--fg); }
        .research-canvas * { box-sizing: border-box; }
        .research-canvas__chooser { display: grid; grid-template-columns: minmax(180px, .7fr) minmax(260px, 1.3fr); gap: var(--space-3); align-items: end; margin-bottom: var(--space-4); }
        .research-canvas__control-label { display: grid; gap: var(--space-1); color: var(--fg-muted); font-size: var(--text-meta); font-weight: var(--weight-semibold); }
        .research-canvas__control { width: 100%; min-width: 0; height: 38px; padding: 0 var(--space-3); border: 1px solid var(--border-2); border-radius: var(--radius-control); background: var(--surface-1); color: var(--fg); font: inherit; }
        .research-canvas__match-note { grid-column: 1 / -1; min-height: 16px; margin: calc(-1 * var(--space-2)) 0 0; color: var(--fg-muted); font-size: var(--text-meta); }
        .research-canvas__workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 370px); min-height: clamp(500px, 66vh, 720px); overflow: hidden; border: 1px solid var(--border-1); border-radius: var(--radius-card); background: var(--surface-1); }
        .research-canvas__membership { min-width: 0; padding: var(--space-8); background: var(--surface-1); }
        .research-canvas__thesis { max-width: 620px; margin: 0 auto; padding: var(--space-5) var(--space-6); border: 1px solid var(--group-research); border-radius: var(--radius-card); background: var(--surface-glass); text-align: center; }
        .research-canvas__claims { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: var(--space-4); max-width: 900px; margin: var(--space-10) auto 0; padding: 0; list-style: none; }
        .research-canvas__claim { width: 100%; min-height: 150px; padding: var(--space-4); border: 1px solid var(--border-1); border-top: 3px solid var(--group-research); border-radius: var(--radius-card); background: var(--surface-1); color: var(--fg); cursor: pointer; text-align: left; transition: border-color var(--motion-hover) var(--ease-out), background var(--motion-hover) var(--ease-out); }
        .research-canvas__claim:hover { border-color: var(--group-research); }
        .research-canvas__claim[aria-pressed="true"] { border-color: var(--accent); border-top-color: var(--accent); background: var(--accent-muted); }
        .research-canvas__claim-kicker { display: block; color: var(--fg-muted); font-size: var(--text-meta); }
        .research-canvas__claim-title { display: block; margin-top: var(--space-2); font-size: var(--text-title); font-weight: var(--weight-semibold); line-height: 1.3; }
        .research-canvas__claim-summary { display: block; margin-top: var(--space-2); color: var(--fg-muted); font-size: var(--text-ui); line-height: 1.45; }
        .research-canvas__context { min-width: 0; padding: var(--space-6); border-left: 1px solid var(--border-1); background: var(--surface-2); overflow-wrap: anywhere; }
        .research-canvas__back { display: none; margin: 0 0 var(--space-5); padding: var(--space-2) var(--space-3); border: 1px solid var(--border-2); border-radius: var(--radius-control); background: var(--surface-1); color: var(--accent); cursor: pointer; font: inherit; }
        .research-canvas__standing { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-4); padding: var(--space-2) var(--space-3); border: 1px solid var(--border-1); border-radius: var(--radius-pill); color: var(--fg-muted); font-size: var(--text-meta); }
        .research-canvas__status-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: var(--status-warn); }
        .research-canvas__context-section { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--border-1); }
        .research-canvas__dossier { display: inline-block; margin-top: var(--space-5); color: var(--accent); font-weight: var(--weight-semibold); text-decoration: none; }
        .research-canvas__source { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--border-1); }
        .research-canvas__source > summary { color: var(--accent); cursor: pointer; font-weight: var(--weight-semibold); }
        .research-canvas__axes { display: grid; gap: var(--space-2); margin: var(--space-4) 0 0; }
        .research-canvas__axes div { padding: var(--space-2); border: 1px solid var(--border-1); border-radius: var(--radius-control); background: var(--surface-1); }
        .research-canvas__axes dt { color: var(--fg-muted); font-size: var(--text-meta); font-weight: var(--weight-semibold); }
        .research-canvas__axes dd { margin: var(--space-1) 0 0; color: var(--fg); font-size: var(--text-meta); }
        @media (max-width: 760px) {
          .research-canvas__chooser { grid-template-columns: 1fr; }
          .research-canvas__match-note { grid-column: 1; }
          .research-canvas__workspace { display: block; min-height: 0; }
          .research-canvas__membership { padding: var(--space-5); }
          .research-canvas__claims { grid-template-columns: 1fr; margin-top: var(--space-6); }
          .research-canvas__context { min-height: 480px; padding: var(--space-5); border-left: 0; }
          .research-canvas__back { display: inline-flex; }
          .research-canvas[data-mobile-view="membership"] .research-canvas__context { display: none; }
          .research-canvas[data-mobile-view="context"] .research-canvas__membership { display: none; }
        }
        @media (prefers-reduced-motion: reduce) { .research-canvas__claim { transition: none; } }
      `}</style>

      <div className="research-canvas__chooser">
        <label className="research-canvas__control-label" htmlFor={searchId}>
          Find a thesis
          <input
            id={searchId}
            className="research-canvas__control"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="Title, topic or source identity"
            data-testid="research-canvas-family-search"
          />
        </label>
        <label className="research-canvas__control-label" htmlFor={selectId}>
          Selected thesis
          <select
            id={selectId}
            className="research-canvas__control"
            value={selectedFamilyOption.key}
            onChange={(event) => chooseFamily(event.currentTarget.value)}
            data-testid="research-canvas-family-select"
          >
            {matchingFamilyOptions.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
          </select>
        </label>
        {query.trim() !== "" && <p className="research-canvas__match-note" role="status">
          {familyOptions.some((option) => matchesFamily(option, query))
            ? "Matching choices shown; the selected thesis is retained."
            : "No matching thesis. Your selected thesis is retained."}
        </p>}
      </div>

      <div className="research-canvas__workspace">
        <section className="research-canvas__membership" aria-labelledby="research-canvas-thesis-title">
          <div className="research-canvas__thesis">
            <p style={{ ...LABEL, color: "var(--group-research)" }}>
              {selectedFamily.id.startsWith("record:") ? "Individual recorded thesis" : "Recorded thesis collection"}
            </p>
            <h2 id="research-canvas-thesis-title" style={{ margin: "var(--space-2) 0 0", fontSize: "var(--text-title)", lineHeight: 1.35 }}>
              {selectedFamily.title}
            </h2>

          </div>

          <div style={{ maxWidth: 900, margin: "var(--space-6) auto 0", textAlign: "center" }}>
            <p style={LABEL}>Recorded membership</p>
            <p style={{ ...META, marginTop: "var(--space-1)" }}>
              Associated claims · not a chain of experimental evidence.
            </p>
          </div>

          {visibleContexts.length === 0 ? (
            <p style={{ ...META, marginTop: "var(--space-8)", textAlign: "center" }}>No recorded claim entries are available for this thesis.</p>
          ) : (
            <ol className="research-canvas__claims" aria-label={`Recorded claim membership for ${selectedFamily.title}`}>
              {visibleContexts.map((context, index) => {
                const selected = activeContext !== undefined && claimKey(activeContext) === claimKey(context);
                return (
                  <li key={claimKey(context)}>
                    <button
                      type="button"
                      className="research-canvas__claim"
                      aria-label={claimAccessibleName(context)}
                      aria-pressed={selected}
                      aria-controls={selected ? "research-canvas-selected-context" : undefined}
                      onClick={() => chooseClaim(claimKey(context))}
                      data-testid={`research-canvas-claim-${domToken(context.iterationId)}-${index}`}
                    >
                      <span className="research-canvas__claim-kicker">
                        {context.isPinnedExactClaim ? `Source-bound claim ${index + 1}` : `Recorded entry ${index + 1}`}
                      </span>
                      <span className="research-canvas__claim-title">{context.shortLabel}</span>
                      <span className="research-canvas__claim-summary">{context.summary}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
          {entries.length > visibleEntries.length && (
            <p style={{ ...META, marginTop: "var(--space-5)", textAlign: "center" }} data-testid="research-canvas-bounded-note">
              Showing {visibleEntries.length} of {entries.length} recorded entries. Full history is in Records and sources.
            </p>
          )}

        </section>

        <ClaimContext context={activeContext} onBack={() => setMobileContext(false)} />
      </div>
    </section>
  );
}
