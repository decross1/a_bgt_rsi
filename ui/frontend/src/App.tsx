import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import Activity from "./routes/Activity";
import Coordinator from "./routes/Coordinator";
import Dashboard from "./routes/Dashboard";
import ExperimentDetail from "./routes/ExperimentDetail";
import Experiments from "./routes/Experiments";
import Inspector from "./routes/Inspector";
import Todo from "./routes/Todo";

// Primary destinations, surfaced as a nav on every page so the dashboard,
// human queue, activity graph, coordinator narrative, and experiment
// digestion are all one click apart.
const NAV = [
  { to: "/", label: "dashboard", end: true },
  { to: "/todo", label: "todo", end: false },
  { to: "/activity", label: "activity", end: false },
  { to: "/coordinator", label: "coordinator", end: false },
  { to: "/experiments", label: "experiments", end: false },
];

// The /todo route is now the uncertainty-resolution COCKPIT (routes/Todo.tsx):
// the HumanTodoPanel inbox + the two-voice interrogation + pre-verdict
// calibration + the six resolution forms. PART 1 removed the panel from the
// dashboard, so /todo is its single home (2026-06-14 work order).

function NavTab({
  to,
  label,
  end,
}: {
  to: string;
  label: string;
  end: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `border-b-2 pb-1 font-mono text-sm transition-colors ${
          isActive
            ? "border-emerald-500 text-zinc-100"
            : "border-transparent text-zinc-400 hover:text-zinc-100"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-zinc-950 text-zinc-200">
        <header className="flex items-center gap-5 border-b border-zinc-800 px-6 py-3">
          <span className="font-mono text-xs uppercase tracking-wide text-zinc-500">
            apparatus observability
          </span>
          <nav className="flex items-center gap-4">
            {NAV.map((item) => (
              <NavTab key={item.to} {...item} />
            ))}
            {/* Cross-nav to the agent-system brain dashboard (http.server
                :5174). Built from the page hostname — not localhost — so the
                link works over the LAN exactly like API_BASE does. */}
            <a
              href={`http://${window.location.hostname}:5174/dashboard.html`}
              target="_blank"
              rel="noreferrer"
              className="border-b-2 border-transparent pb-1 font-mono text-sm text-zinc-400 transition-colors hover:text-zinc-100"
            >
              brain<span aria-hidden="true" className="ml-0.5 text-zinc-600">↗</span>
            </a>
          </nav>
          <span className="ml-auto text-xs text-zinc-600">
            call-chain inspector at /chain/req/&lt;request_id&gt;
          </span>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/todo" element={<Todo />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/coordinator" element={<Coordinator />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/experiments/:expId" element={<ExperimentDetail />} />
          {/* Wrapper-rooted tool-call chains (logs/calls.jsonl). */}
          <Route path="/chain/req/:requestId" element={<Inspector />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
