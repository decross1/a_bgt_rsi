// events.jsonl pane (day-3.5 surface). schema/events.jsonl.schema.json is
// now committed by Track A — a oneOf of two discriminated types — so each
// known event_type gets a renderer driven by that schema's per-type fields.
// An event_type the schema does not define falls back to a generic
// key/value dump, so a new type still surfaces without a code change.
import { useEffect, useState, type ReactNode } from "react";
import { getEvents } from "../api/http";
import type { EventRecord, EventsResponse } from "../types/schemas";

// Per-type fields from schema/events.jsonl.schema.json, beyond the shared
// event_type + timestamp. Drives the per-type renderers and the
// missing-field check below.
const SCHEMA_FIELDS: Record<string, string[]> = {
  human_intervention: ["task_id", "subtype", "reason", "context_hash"],
  calibration_entry: [
    "experiment_id",
    "metric_name",
    "pre_experiment_expected_range",
    "post_experiment_observed",
    "within_range",
    "human_attestation",
  ],
};

function typeClass(eventType: string): string {
  switch (eventType) {
    case "human_intervention":
      return "border-amber-900 bg-amber-950/40";
    case "calibration_entry":
      return "border-sky-900 bg-sky-950/30";
    default:
      return "border-zinc-800 bg-zinc-900/40";
  }
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// A typed event missing a schema-required field is surfaced, not hidden —
// the apparatus discipline is to flag a malformed payload, never paper over
// it (ui_plan.md operating rule 8).
function missingFields(event: EventRecord): string[] {
  const required = SCHEMA_FIELDS[event.event_type];
  if (!required) return [];
  return required.filter(
    (field) => event[field] === undefined || event[field] === null,
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <span className="font-mono text-zinc-500">{label}</span>
      <span className="font-mono text-zinc-300">{children}</span>
    </div>
  );
}

function CardShell({
  event,
  children,
}: {
  event: EventRecord;
  children: ReactNode;
}) {
  const missing = missingFields(event);
  return (
    <div className={`rounded border p-3 ${typeClass(event.event_type)}`}>
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-sm text-zinc-100">{event.event_type}</span>
        <span className="text-xs text-zinc-500">{event.timestamp ?? "—"}</span>
      </div>
      {missing.length > 0 && (
        <div className="mt-2 rounded border border-red-900 bg-red-950/50 px-2 py-1 text-xs text-red-300">
          incomplete record — missing {missing.join(", ")}
        </div>
      )}
      {children}
    </div>
  );
}

// human_intervention (P1): a human action inside an otherwise-agent task.
function HumanInterventionCard({ event }: { event: EventRecord }) {
  return (
    <CardShell event={event}>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="rounded bg-amber-900/60 px-1.5 py-0.5 font-mono text-xs text-amber-200">
          {pretty(event.subtype)}
        </span>
        <span className="font-mono text-xs text-zinc-500">
          {pretty(event.task_id)}
        </span>
      </div>
      <p className="mt-2 text-sm text-zinc-200">{pretty(event.reason)}</p>
      <div className="mt-2 font-mono text-xs text-zinc-600">
        context_hash: {pretty(event.context_hash)}
      </div>
    </CardShell>
  );
}

// calibration_entry (P3): pre-experiment expected range vs observed value.
function CalibrationEntryCard({ event }: { event: EventRecord }) {
  const within = event.within_range;
  const range = event.pre_experiment_expected_range;
  const rangeText = Array.isArray(range) ? `[${range.join(", ")}]` : pretty(range);
  return (
    <CardShell event={event}>
      <div className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        <Field label="experiment_id">{pretty(event.experiment_id)}</Field>
        <Field label="metric_name">{pretty(event.metric_name)}</Field>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-zinc-200">
          observed{" "}
          <span className="font-mono">
            {pretty(event.post_experiment_observed)}
          </span>
        </span>
        <span className="text-zinc-500">
          expected <span className="font-mono">{rangeText}</span>
        </span>
        {typeof within === "boolean" && (
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${
              within
                ? "bg-emerald-950 text-emerald-300"
                : "bg-red-950 text-red-300"
            }`}
          >
            {within ? "within range" : "out of range"}
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-zinc-400">
        <span className="font-mono text-zinc-500">human_attestation: </span>
        {pretty(event.human_attestation)}
      </p>
    </CardShell>
  );
}

// Fallback for an event_type the committed schema does not define — render
// every field generically so a future event type still shows up.
function GenericEventCard({ event }: { event: EventRecord }) {
  const entries = Object.entries(event).filter(
    ([key]) => key !== "event_type" && key !== "timestamp",
  );
  return (
    <CardShell event={event}>
      <div className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        {entries.map(([key, value]) => (
          <Field key={key} label={key}>
            {pretty(value)}
          </Field>
        ))}
      </div>
    </CardShell>
  );
}

function EventCard({ event }: { event: EventRecord }) {
  switch (event.event_type) {
    case "human_intervention":
      return <HumanInterventionCard event={event} />;
    case "calibration_entry":
      return <CalibrationEntryCard event={event} />;
    default:
      return <GenericEventCard event={event} />;
  }
}

export default function EventsViewer() {
  const [data, setData] = useState<EventsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    let active = true;
    const load = () =>
      getEvents()
        .then((d) => {
          if (!active) return;
          setData(d);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const events = data?.events ?? [];
  const types = Array.from(new Set(events.map((e) => e.event_type)));
  const filtered =
    filter === "all" ? events : events.filter((e) => e.event_type === filter);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="font-mono text-lg text-zinc-100">events.jsonl</h1>
      <p className="mt-1 text-xs text-zinc-500">
        Day-3.5 surface — rendered per type from schema/events.jsonl.schema.json;
        an unknown event_type falls back to a generic dump.
      </p>
      {error && (
        <div className="mt-3 rounded border border-red-900 bg-red-950/50 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {data && !data.available && (
        <div className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-500">
          logs/events.jsonl is not present yet — the day-3.5 run has not emitted
          any events.
        </div>
      )}
      {data && data.available && events.length === 0 && (
        <div className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-500">
          logs/events.jsonl is present but empty.
        </div>
      )}
      {events.length > 0 && (
        <>
          <div className="mt-3 flex items-center gap-2 text-xs text-zinc-400">
            <span>filter:</span>
            <button
              onClick={() => setFilter("all")}
              className={`rounded px-2 py-0.5 ${
                filter === "all"
                  ? "bg-zinc-700 text-zinc-100"
                  : "bg-zinc-900 text-zinc-400"
              }`}
            >
              all ({events.length})
            </button>
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={`rounded px-2 py-0.5 ${
                  filter === t
                    ? "bg-zinc-700 text-zinc-100"
                    : "bg-zinc-900 text-zinc-400"
                }`}
              >
                {t} ({events.filter((e) => e.event_type === t).length})
              </button>
            ))}
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {filtered.map((event, i) => (
              <EventCard key={i} event={event} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
