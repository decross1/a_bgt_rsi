import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import HumanTodoPanel from "./components/HumanTodoPanel";
import Activity from "./routes/Activity";
import Coordinator from "./routes/Coordinator";
import Dashboard from "./routes/Dashboard";
import ExperimentDetail from "./routes/ExperimentDetail";
import Experiments from "./routes/Experiments";
import Inspector from "./routes/Inspector";

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

// Page-width view of the human's work queue (the same self-polling panel the
// Dashboard mounts compactly). Its own route so "what is blocked on me" is
// one click / one bookmark away.
function HumanTodoPage() {
  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="human-todo-page">
      <HumanTodoPanel />
    </div>
  );
}

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
          </nav>
          <span className="ml-auto text-xs text-zinc-600">
            call-chain inspector at /chain/req/&lt;request_id&gt;
          </span>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/todo" element={<HumanTodoPage />} />
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
