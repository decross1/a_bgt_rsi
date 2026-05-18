// Orchestrator queue: running tasks and recently-completed tasks, each a
// link into the call-chain inspector. Polls /api/recent_tasks every 3 s.
// See ui_plan.md section 5.3.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getRecentTasks } from "../api/http";
import type { RecentTask } from "../types/schemas";

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

function TaskRow({ task }: { task: RecentTask }) {
  return (
    <Link
      to={`/chain/${encodeURIComponent(task.task_id)}`}
      className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-zinc-800/60"
    >
      <span className={`text-xs ${statusClass(task.status)}`}>●</span>
      <span className="truncate font-mono text-sm text-zinc-100">
        {task.task_id}
      </span>
      <span className="truncate text-xs text-zinc-500">{task.task_type}</span>
      <span className="ml-auto whitespace-nowrap text-xs text-zinc-600">
        {task.status}
      </span>
    </Link>
  );
}

export default function OrchestratorQueue() {
  const [tasks, setTasks] = useState<RecentTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      getRecentTasks(40)
        .then((d) => {
          if (active) {
            setTasks(d.tasks);
            setError(null);
          }
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const running = (tasks ?? []).filter((t) => t.status === "started");
  const recent = (tasks ?? []).filter((t) => t.status !== "started");

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Orchestrator queue
      </h2>
      {error && <div className="mt-2 text-sm text-red-400">{error}</div>}
      {tasks && tasks.length === 0 && (
        <div className="mt-2 text-sm text-zinc-500">
          No orchestrator tasks yet — the apparatus has not reached day 6.
        </div>
      )}

      {running.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-zinc-600">Running ({running.length})</div>
          {running.map((t) => (
            <TaskRow key={t.task_id} task={t} />
          ))}
        </div>
      )}

      {recent.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-zinc-600">Recent ({recent.length})</div>
          <div className="max-h-72 overflow-y-auto">
            {recent.map((t) => (
              <TaskRow key={t.task_id} task={t} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
