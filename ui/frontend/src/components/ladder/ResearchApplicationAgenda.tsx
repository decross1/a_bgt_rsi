import { useEffect, useMemo, useState } from "react";

import { getResearchApplicationAgenda } from "../../api/researchApplicationAgenda";
import type {
  ResearchApplicationAgendaResponse,
  ResearchApplicationLane,
  ResearchApplicationNextStep,
  ResearchApplicationSource,
} from "../../types/researchApplicationAgenda";

function safeList<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function safeUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function laneOrder(lane: ResearchApplicationLane): number {
  if (lane.id === "options") return 0;
  if (lane.id === "prediction_markets") return 1;
  if (lane.id === "crypto") return 2;
  return 3;
}

export default function ResearchApplicationAgenda({
  initial,
}: {
  initial?: ResearchApplicationAgendaResponse | null;
}) {
  const [response, setResponse] = useState<ResearchApplicationAgendaResponse | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let current = true;
    getResearchApplicationAgenda().then((value) => {
      if (!current) return;
      setResponse(value);
      setLoaded(true);
      setError(null);
    }).catch((reason) => {
      if (!current) return;
      setLoaded(true);
      setError(String(reason));
    });
    return () => { current = false; };
  }, [initial]);

  const agenda = response?.available === true ? response.agenda : null;
  const lanes = useMemo(
    () => safeList<ResearchApplicationLane>(agenda?.lanes).filter((lane) => lane !== null && typeof lane === "object").sort((a, b) => laneOrder(a) - laneOrder(b)),
    [agenda?.lanes],
  );

  if (!loaded) {
    return <section className="mb-5 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-4 text-sm text-[var(--fg-muted)]" aria-label="Application agenda">Loading proposed application agenda…</section>;
  }
  if (agenda === null) {
    return <section className="mb-5 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-4 text-sm text-[var(--fg-muted)]" aria-label="Application agenda">
      Proposed application agenda unavailable{error === null ? "." : `: ${error}`}
    </section>;
  }

  return (
    <section className="mt-5 mb-5 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-4" data-testid="research-application-agenda" aria-labelledby="research-application-agenda-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-4xl">
          <p className="m-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--group-research)]">Proposed application agenda</p>
          <h2 id="research-application-agenda-title" className="mt-1 text-base font-semibold text-[var(--fg)]">Mechanism first · options preferred to investigate</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--fg)]">{agenda.research_question}</p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px] text-[var(--fg-muted)]" aria-label="Agenda qualification">
          <span className="rounded border border-[var(--border-2)] px-2 py-1">proposed</span>
          {agenda.execution_authorized === false && (
            <span className="rounded border border-[var(--border-2)] px-2 py-1">not yet preregistered</span>
          )}
        </div>
      </div>

      <p className="mt-3 text-xs text-[var(--fg-muted)]">{agenda.selection_rule}</p>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        {lanes.map((lane, index) => (
          <article key={lane.id} className={`rounded border p-3 ${index === 0 ? "border-[var(--group-research)] bg-[var(--surface-glass)]" : "border-[var(--border-1)] bg-[var(--surface-2)]"}`}>
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="m-0 text-sm font-semibold text-[var(--fg)]">{lane.label}</h3>
              <span className="text-[10px] text-[var(--fg-muted)]">{index === 0 ? "preferred" : "alternative"}</span>
            </div>
            <p className="mt-2 text-xs leading-5 text-[var(--fg-muted)]">{lane.mechanism}</p>
            <p className="mt-2 text-xs leading-5 text-[var(--fg)]"><strong>Test:</strong> {lane.test}</p>
          </article>
        ))}
      </div>

      <div className="mt-4 border-t border-[var(--border-1)] pt-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-muted)]">Next agenda</p>
        <ol className="mt-2 grid gap-2 md:grid-cols-2">
          {safeList<ResearchApplicationNextStep>(agenda.next_agenda).map((step, index) => (
            <li key={step.id} className="text-xs leading-5 text-[var(--fg)]"><span className="mr-2 text-[var(--fg-muted)]">{index + 1}.</span><strong>{step.label}</strong> · {step.deliverable}</li>
          ))}
        </ol>
      </div>

      <details className="mt-4 border-t border-[var(--border-1)] pt-3 text-xs text-[var(--fg-muted)]">
        <summary className="cursor-pointer font-semibold text-[var(--accent)]">Requirements, kill conditions and sources</summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-3">
          {lanes.map((lane) => <section key={lane.id}>
            <h3 className="text-xs font-semibold text-[var(--fg)]">{lane.label}</h3>
            <ul className="mt-1 list-disc space-y-1 pl-4">{safeList<string>(lane.requirements).map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>
            <p className="mt-2"><strong>Stop if:</strong> {lane.kill_condition}</p>
          </section>)}
        </div>
        <p className="mt-4"><strong>Historical boundary:</strong> {agenda.history_policy}</p>
        <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
          {safeList<ResearchApplicationSource>(agenda.sources).map((source) => {
            const href = safeUrl(source.url);
            return href === null ? <span key={source.id}>{source.title}</span> : <a key={source.id} href={href} rel="noreferrer" target="_blank" className="text-[var(--accent)]">{source.title} ↗</a>;
          })}
        </p>
        <p className="mt-3 font-mono text-[10px]">agenda {agenda.agenda_id} · recorded {agenda.recorded_at} · source {response?.source_sha256 ?? "hash unavailable"}</p>
      </details>
    </section>
  );
}
