// events.jsonl pane (day-3.5 surface). Handles the two known event types
// — human_intervention and calibration_entry — with type-aware rendering,
// and falls back to a generic JSON dump for any other type (the schema is
// not committed yet, so this is forward-compatible by design).
import { useEffect, useState } from "react";
import { getEvents } from "../api/http";
import type { EventRecord, EventsResponse } from "../types/schemas";

function typeClass(eventType: string): string {
  switch (eventType) {
    case "human_intervention":
      return "text-amber-300 border-amber-900 bg-amber-950/40";
    case "calibration_entry":
      return "text-sky-300 border-sky-900 bg-sky-950/30";
    default:
      return "text-zinc-300 border-zinc-800 bg-zinc-900/40";
  }
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function EventRow({ event }: { event: EventRecord }) {
  const otherEntries = Object.entries(event).filter(
    ([k]) => k !== "event_type" && k !== "timestamp",
  );
  return (
    <div className={`rounded border p-3 ${typeClass(event.event_type)}`}>
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-sm">{event.event_type}</span>
        <span className="text-xs text-zinc-500">{event.timestamp ?? ""}</span>
      </div>
      <div className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        {otherEntries.map(([key, value]) => (
          <span key={key} className="contents">
            <span className="font-mono text-zinc-500">{key}</span>
            <span className="font-mono text-zinc-300">{pretty(value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
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
  const filtered = filter === "all" ? events : events.filter((e) => e.event_type === filter);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="font-mono text-lg text-zinc-100">events.jsonl</h1>
      <p className="mt-1 text-xs text-zinc-500">
        Day-3.5 surface — schema not committed yet; rendered generically.
      </p>
      {error && (
        <div className="mt-3 rounded border border-red-900 bg-red-950/50 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {data && !data.available && (
        <div className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-500">
          logs/events.jsonl is not present yet — the day-3.5 schema has not landed.
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
                filter === "all" ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"
              }`}
            >
              all ({events.length})
            </button>
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={`rounded px-2 py-0.5 ${
                  filter === t ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"
                }`}
              >
                {t} ({events.filter((e) => e.event_type === t).length})
              </button>
            ))}
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {filtered.map((event, i) => (
              <EventRow key={i} event={event} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
