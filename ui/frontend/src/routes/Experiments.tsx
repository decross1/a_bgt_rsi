import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { getResearch } from "../api/experiments";
import type {
  ResearchBridge,
  ResearchExperiment,
  ResearchResponse,
  ResearchVerdict,
} from "../types/experiments";
import "./experiments.css";

interface Props {
  initial?: ResearchResponse | null;
  /** Retained for fixture compatibility. Operational cycles are intentionally ignored. */
  initialCoordinatorCycles?: unknown[];
}

type RecordValue = Record<string, unknown>;

interface CatalogEntry {
  key: string;
  id: string;
  title: string;
  tierId: string;
  tierLabel: string;
  mapped: boolean;
  experiment: ResearchExperiment;
}

interface NormalizedCatalog {
  entries: CatalogEntry[];
  malformedRows: number;
  malformedTopLevel: boolean;
}

function isRecord(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function safeEncodePath(id: string): string {
  try {
    return encodeURIComponent(id);
  } catch {
    const stripped = id.replace(
      /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g,
      "",
    );
    try {
      return encodeURIComponent(stripped);
    } catch {
      return "";
    }
  }
}

function normalizeCatalog(data: ResearchResponse | null): NormalizedCatalog {
  if (!data || !isRecord(data)) {
    return { entries: [], malformedRows: 0, malformedTopLevel: false };
  }

  const tiersValue = data.tiers as unknown;
  const untieredValue = data.untiered as unknown;
  const malformedTopLevel =
    data.available === true &&
    (!Array.isArray(tiersValue) || !Array.isArray(untieredValue));
  const entries: CatalogEntry[] = [];
  let malformedRows = 0;
  let order = 0;

  for (const tierValue of asArray<unknown>(tiersValue)) {
    if (!isRecord(tierValue)) {
      malformedRows += 1;
      continue;
    }
    const tierId = asText(tierValue.tier) ?? "unknown-tier";
    const tierLabel = asText(tierValue.label) ?? "Unknown grouping";
    const experimentsValue = tierValue.experiments;
    if (!Array.isArray(experimentsValue)) malformedRows += 1;
    for (const experimentValue of asArray<unknown>(experimentsValue)) {
      if (!isRecord(experimentValue)) {
        malformedRows += 1;
        continue;
      }
      const experiment = experimentValue as unknown as ResearchExperiment;
      const id = asText(experimentValue.id) ?? "";
      const title = asText(experimentValue.title) ?? (id || "Unnamed source entry");
      if (!id) malformedRows += 1;
      entries.push({
        key: `mapped-${order++}-${id}`,
        id,
        title,
        tierId,
        tierLabel,
        mapped: true,
        experiment,
      });
    }
  }

  for (const experimentValue of asArray<unknown>(untieredValue)) {
    if (!isRecord(experimentValue)) {
      malformedRows += 1;
      continue;
    }
    const experiment = experimentValue as unknown as ResearchExperiment;
    const id = asText(experimentValue.id) ?? "";
    const title = asText(experimentValue.title) ?? (id || "Unnamed source entry");
    if (!id) malformedRows += 1;
    entries.push({
      key: `unmapped-${order++}-${id}`,
      id,
      title,
      tierId: "unmapped",
      tierLabel: "Unmapped source",
      mapped: false,
      experiment,
    });
  }

  return { entries, malformedRows, malformedTopLevel };
}

function validVerdict(value: unknown): ResearchVerdict | null {
  if (!isRecord(value)) return null;
  const text = asText(value.text);
  if (text === null) return null;
  return value as unknown as ResearchVerdict;
}

function verdictTone(verdict: ResearchVerdict | null): string {
  if (!verdict || typeof verdict.tone !== "string") return "unknown";
  return ["ok", "warn", "bad"].includes(verdict.tone)
    ? verdict.tone
    : "unknown";
}

function validBridges(value: unknown): ResearchBridge[] {
  return asArray<unknown>(value).filter(
    (bridge): bridge is ResearchBridge => isRecord(bridge),
  );
}

function bridgeLabel(bridge: ResearchBridge): string {
  const iteration = asText(bridge.iteration_id) ?? "Unnamed iteration";
  const metric = asText(bridge.metric) ?? "Metric not reported";
  const value =
    typeof bridge.value === "string" ||
    (typeof bridge.value === "number" && Number.isFinite(bridge.value))
      ? ` = ${bridge.value}`
      : "";
  return `${iteration} · ${metric}${value}`;
}

function evidenceLabel(experiment: ResearchExperiment): string {
  const record = experiment as unknown as RecordValue;
  const resultsDirectory = record.has_results_dir;
  const files = asFiniteNumber(record.n_results_files);
  const artifacts = [
    record.has_summary_json === true ? "JSON summary" : null,
    record.has_summary_md === true ? "authored summary" : null,
    record.has_per_round === true ? "round data" : null,
    record.has_trials === true ? "trial sample" : null,
  ].filter((value): value is string => value !== null);

  if (resultsDirectory === false) return "Results directory reported absent";
  if (resultsDirectory === true && files === 0)
    return "Results directory reported empty";
  if (artifacts.length > 0) {
    const count =
      files === null
        ? "Result files reported"
        : `${files} result file${files === 1 ? "" : "s"}`;
    return `${count} · ${artifacts.join(" · ")}`;
  }
  if (resultsDirectory === true)
    return "Results directory present; readable evidence not reported";
  return "Evidence inventory unknown";
}

function searchableText(entry: CatalogEntry): string {
  const verdict = validVerdict(
    (entry.experiment as unknown as RecordValue).verdict,
  );
  const bridges = validBridges(
    (entry.experiment as unknown as RecordValue).bridge,
  );
  return [
    entry.id,
    entry.title,
    entry.tierId,
    entry.tierLabel,
    asText(verdict?.text) ?? "",
    ...bridges.map(bridgeLabel),
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function SourceEntry({
  entry,
  returnTo,
  linkRef,
}: {
  entry: CatalogEntry;
  returnTo: string;
  linkRef: (node: HTMLAnchorElement | null) => void;
}) {
  const record = entry.experiment as unknown as RecordValue;
  const verdict = validVerdict(record.verdict);
  const verdictText = asText(verdict?.text);
  const bridges = validBridges(record.bridge);
  const evidence = evidenceLabel(entry.experiment);
  const href = entry.id ? `/experiments/${safeEncodePath(entry.id)}` : null;

  return (
    <article
      className="experiment-source-entry"
      data-testid={`research-card-${entry.id}`}
    >
      <div className="experiment-source-entry__heading">
        <div className="experiment-source-entry__identity">
          {href ? (
            <Link
              ref={linkRef}
              to={href}
              state={{
                experimentsReturnTo: returnTo,
                focusExperimentId: entry.id,
              }}
              className="experiment-source-entry__link"
            >
              <span>{entry.title}</span>
              <span aria-hidden="true">→</span>
            </Link>
          ) : (
            <span className="experiment-source-entry__unavailable-link">
              {entry.title}
            </span>
          )}
          <span className="experiment-source-entry__id">
            {entry.id || "Source id unavailable"}
          </span>
        </div>
        <span className="experiment-tier-label">
          {entry.mapped ? entry.tierLabel : "Unmapped source"}
        </span>
      </div>

      <div className="experiment-source-entry__result">
        <span className="experiment-field-label">Reported label</span>
        <span
          className="experiment-result-label"
          data-tone={verdictTone(verdict)}
          data-testid={`verdict-${entry.id}`}
        >
          {verdictText ?? "No result label reported"}
        </span>
        <span className="experiment-result-qualifier">
          Claim binding and independent validity are not reported.
        </span>
      </div>

      <dl className="experiment-source-entry__facts">
        <div>
          <dt>Evidence</dt>
          <dd>{evidence}</dd>
        </div>
        <div>
          <dt>Evaluation mode</dt>
          <dd>Not reported</dd>
        </div>
      </dl>

      <details className="experiment-source-entry__evidence">
        <summary>
          Source evidence
          {bridges.length > 0
            ? ` · ${bridges.length} bridge record${bridges.length === 1 ? "" : "s"}`
            : ""}
        </summary>
        <p>{evidence}.</p>
        {bridges.length === 0 ? (
          <p data-testid={`bridge-${entry.id}`}>
            No bridge records are present in this response.
          </p>
        ) : (
          <ul data-testid={`bridge-${entry.id}`}>
            {bridges.map((bridge, index) => (
              <li key={index}>{bridgeLabel(bridge)}</li>
            ))}
          </ul>
        )}
      </details>
    </article>
  );
}

export default function Experiments({ initial }: Props) {
  const [data, setData] = useState<ResearchResponse | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const linkRefs = useRef(new Map<string, HTMLAnchorElement>());

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    setError(null);
    setData(null);
    getResearch()
      .then((response) => {
        if (active) setData(response);
      })
      .catch((reason) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
    };
  }, [initial, requestVersion]);

  const catalog = useMemo(() => normalizeCatalog(data), [data]);
  const tierOptions = useMemo(() => {
    const options = new Map<string, string>();
    for (const entry of catalog.entries)
      options.set(entry.tierId, entry.tierLabel);
    return [...options.entries()];
  }, [catalog.entries]);
  const query = searchParams.get("q") ?? "";
  const requestedTier = searchParams.get("tier") ?? "all";
  const tier =
    requestedTier === "all" ||
    tierOptions.some(([value]) => value === requestedTier)
      ? requestedTier
      : "all";
  const filteredEntries = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return catalog.entries.filter(
      (entry) =>
        (tier === "all" || entry.tierId === tier) &&
        (!needle || searchableText(entry).includes(needle)),
    );
  }, [catalog.entries, query, tier]);

  useEffect(() => {
    const state = isRecord(location.state) ? location.state : null;
    const focusId = asText(state?.focusExperimentId);
    if (focusId) linkRefs.current.get(focusId)?.focus();
  }, [location.key, filteredEntries]);

  const setParam = (name: "q" | "tier", value: string) => {
    const next = new URLSearchParams(searchParams);
    if (!value || value === "all") next.delete(name);
    else next.set(name, value);
    setSearchParams(next, { replace: true });
  };

  const returnTo = `${location.pathname}${location.search}`;
  const mappedCount = catalog.entries.filter((entry) => entry.mapped).length;
  const evidenceCount = catalog.entries.filter((entry) => {
    const record = entry.experiment as unknown as RecordValue;
    return (
      record.has_results_dir === true &&
      (asFiniteNumber(record.n_results_files) ?? 0) > 0
    );
  }).length;
  const available = data?.available === true;
  const unavailable = data?.available === false;

  return (
    <div className="page-full experiments-page" data-testid="experiments-page">
      <header className="experiments-page__header">
        <div>
          <p className="experiments-eyebrow">Research</p>
          <h1>Experiments</h1>
          <p>
            Find a recorded test source, then inspect the evidence and the scope
            of its reported result.
          </p>
        </div>
        <Link to="/cycles" className="experiments-trace-link">
          View trace history
        </Link>
      </header>

      {error && (
        <div
          className="experiments-state experiments-state--error"
          role="alert"
        >
          <strong>Experiment catalog read failed.</strong>
          <span>{error}. No empty catalog is inferred.</span>
          <button
            type="button"
            onClick={() => setRequestVersion((value) => value + 1)}
          >
            Retry read
          </button>
        </div>
      )}

      {!data && !error && (
        <div className="experiments-state" role="status">
          Reading experiment sources…
        </div>
      )}

      {unavailable && (
        <div
          className="experiments-state experiments-state--warning"
          data-testid="experiments-unavailable"
        >
          <strong>Experiment sources are unavailable.</strong>
          <span>
            {asText((data as unknown as RecordValue).reason) ??
              "The source did not report a reason."}
          </span>
        </div>
      )}

      {available && (
        <>
          <section
            className="experiments-catalog-summary"
            aria-label="Catalog scope"
          >
            <div>
              <strong>{catalog.entries.length}</strong>
              <span>source entries</span>
            </div>
            <div>
              <strong>{mappedCount}</strong>
              <span>mapped to a supplied tier</span>
            </div>
            <div>
              <strong>{evidenceCount}</strong>
              <span>report result files</span>
            </div>
          </section>

          <section
            className="experiments-catalog"
            aria-labelledby="experiment-catalog-title"
          >
            <div className="experiments-catalog__heading">
              <div>
                <h2 id="experiment-catalog-title">Source catalog</h2>
                <p>
                  Tier is a source attribute. Reported labels are not a shared
                  verdict scale or a readiness ranking.
                </p>
              </div>
              <details>
                <summary>How to read these entries</summary>
                <p>
                  Each row preserves the producer label, evidence inventory and
                  exact detail link. Claim binding, validity, mode and
                  application fit remain unknown unless the selected source
                  reports them.
                </p>
              </details>
            </div>

            <div className="experiments-toolbar">
              <label>
                <span>Search source entries</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setParam("q", event.target.value)}
                  placeholder="Title, source id, result label or bridge"
                />
              </label>
              <label>
                <span>Source tier</span>
                <select
                  value={tier}
                  onChange={(event) => setParam("tier", event.target.value)}
                >
                  <option value="all">All source tiers</option>
                  {tierOptions.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <p aria-live="polite">
                Showing {filteredEntries.length} of {catalog.entries.length}
              </p>
            </div>

            {(catalog.malformedTopLevel || catalog.malformedRows > 0) && (
              <div
                className="experiments-inline-warning"
                data-testid="catalog-malformed"
                role="status"
              >
                The response contains malformed catalog fields
                {catalog.malformedRows > 0
                  ? ` or ${catalog.malformedRows} malformed source row${catalog.malformedRows === 1 ? "" : "s"}`
                  : ""}
                . Readable entries remain available; counts exclude unreadable
                rows.
              </div>
            )}

            {catalog.entries.length === 0 ? (
              <div className="experiments-state" data-testid="catalog-empty">
                No source entries were reported in the readable catalog arrays.
              </div>
            ) : filteredEntries.length === 0 ? (
              <div
                className="experiments-state"
                data-testid="catalog-filtered-empty"
              >
                No source entries match this search and tier filter.
              </div>
            ) : (
              <div
                className="experiment-source-list"
                data-testid="source-entry-list"
              >
                {filteredEntries.map((entry) => (
                  <SourceEntry
                    key={entry.key}
                    entry={entry}
                    returnTo={returnTo}
                    linkRef={(node) => {
                      if (node) linkRefs.current.set(entry.id, node);
                      else linkRefs.current.delete(entry.id);
                    }}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <p className="experiments-page__boundary">
        This catalog reads existing sources only. It does not load coordinator
        cycles, run an experiment, select a market or make a scientific ruling.
      </p>
    </div>
  );
}
