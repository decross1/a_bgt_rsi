// Landing page. The full live dashboard (GPU/vLLM/process panels) is
// build step 6.5; for now this lists recent tasks as inspector entry
// points. See ui_plan.md section 5.3.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHealth, getRecentTasks } from "../api/http";
import type { Health, RecentTask } from "../types/schemas";

function statusClass(status: string | null): string {
  switch (status) {
    case "passed":
      return "text-emerald-400";
    case "failed":
    case "aborted":
      return "text-red-400";
    case "started":
      return "text-amber-400";
    default:
      return "text-zinc-500";
  }
}

export default function Dashboard() {
  const [tasks, setTasks] = useState<RecentTask[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRecentTasks()
      .then((d) => setTasks(d.tasks))
      .catch((e) => setError(String(e)));
    getHealth()
      .then(setHealth)
      .catch(() => {
        /* health is best-effort on this page */
      });
  }, []);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-400">
        The live dashboard (GPU / vLLM / process panels) is build step 6.5. This
        page lists recent orchestrator tasks — click one to open its call-chain
        inspector.
        {health && (
          <span className="ml-1 text-zinc-500">
            Backend {health.version}; telemetry last seen{" "}
            {health.telemetry_last_seen ?? "never"}.
          </span>
        )}
      </div>

      <h2 className="mt-5 text-xs font-medium uppercase tracking-wide text-zinc-500">
        Recent tasks
      </h2>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {tasks && tasks.length === 0 && (
        <div className="mt-2 text-sm text-zinc-500">
          No orchestrator tasks yet — the apparatus has not reached day 6. Point
          the backend at fixtures to see sample data (see ui/backend/README.md).
        </div>
      )}
      {tasks && tasks.length > 0 && (
        <div className="mt-2 divide-y divide-zinc-800 rounded border border-zinc-800">
          {tasks.map((t) => (
            <Link
              key={t.task_id}
              to={`/chain/${encodeURIComponent(t.task_id)}`}
              className="flex items-center gap-3 px-3 py-2 hover:bg-zinc-800/60"
            >
              <span className={`text-xs ${statusClass(t.status)}`}>●</span>
              <span className="font-mono text-sm text-zinc-100">{t.task_id}</span>
              <span className="text-xs text-zinc-500">{t.task_type}</span>
              <span className="ml-auto font-mono text-xs text-zinc-600">
                {t.dispatch_ts}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
