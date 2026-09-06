import { API_BASE } from "./http";
import { getPollSnapshot, refreshPoll, usePolled, usePollActivity, usePollAsOf } from "./pollhub";
export type RecordValue = Record<string, unknown>;
export type Source = { data: RecordValue | null; receivedAt: string | null; loading: boolean; error: string | null };
const isRecord = (v: unknown): v is RecordValue => v !== null && typeof v === "object" && !Array.isArray(v);
const endpoints = {
  ladder: "/api/ladder",
  frontier: "/api/frontier_reviews?limit=100",
  channel: "/api/channel/timeline?limit=1000",
  health: "/api/health",
} as const;
type SourceKey = keyof typeof endpoints;
const keys = Object.keys(endpoints) as SourceKey[];

function validate(key: SourceKey, body: unknown): RecordValue {
  if (!isRecord(body)) throw new Error("Source missing or response shape unknown");
  const field = key === "ladder" ? "clusters" : key === "frontier" ? "events" : key === "channel" ? "rows" : null;
  if (field && (!Array.isArray(body[field]) || !(body[field] as unknown[]).every(isRecord))) {
    throw new Error(`Source missing or invalid ${field}; no zero count inferred`);
  }
  if (key === "ladder" && (!isRecord(body.counts) || !["open", "surfaced", "killed"].every((name) => {
    const count = (body.counts as RecordValue)[name];
    return typeof count === "number" && Number.isInteger(count) && count >= 0;
  }))) throw new Error("Recorded counts missing or invalid; no zero count inferred");
  return body;
}


const pollKey = (key: SourceKey) => `development:${endpoints[key]}`;
async function fetchSource(key: SourceKey): Promise<RecordValue> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${API_BASE}${endpoints[key]}`, { signal: controller.signal });
    if (!response.ok || response.status === 204) throw new Error(`HTTP ${response.status}`);
    return validate(key, await response.json());
  } finally { clearTimeout(timer); }
}
function useSource(key: SourceKey): Source {
  const id = pollKey(key);
  usePolled(id, () => fetchSource(key), { intervalMs: Infinity, deadlineMs: 16_000 });
  const loading = usePollActivity(id);
  usePollAsOf(id);
  // Activity also wakes this reader for repeated failures, when unchanged
  // failure state deliberately does not notify ordinary payload subscribers.
  const snapshot = getPollSnapshot<RecordValue>(id);
  return {
    data: snapshot.data ?? null,
    receivedAt: snapshot.asOf === null ? null : new Date(snapshot.asOf).toISOString(),
    loading: loading || (snapshot.data === undefined && !snapshot.failing),
    error: snapshot.failing ? String(snapshot.error) : null,
  };
}
export function useDevelopmentSources() {
  const ladder = useSource("ladder");
  const frontier = useSource("frontier");
  const channel = useSource("channel");
  const health = useSource("health");
  return { sources: { ladder, frontier, channel, health }, refreshSources: () => keys.forEach((key) => refreshPoll(pollKey(key))) };
}
