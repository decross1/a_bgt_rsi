import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import LoopAlertBanner from "./components/LoopAlertBanner";
import Channel from "./routes/Channel";
import Cycles from "./routes/Cycles";
import DossierIndex from "./routes/DossierIndex";
import DossierReader from "./routes/DossierReader";
import ExperimentDetail from "./routes/ExperimentDetail";
import Experiments from "./routes/Experiments";
import Graph from "./routes/Graph";
import Inspector from "./routes/Inspector";
import Ladder from "./routes/Ladder";
import Pulse from "./routes/Pulse";

// The final UI-simplification shell (docs/ui_simplification_plan_2026-08-15.md,
// S3): the nav is the three owner surfaces — pulse (healthy + do I owe
// anything), ladder (what's cooking), dossiers (the reader — the product) —
// with the uniquely-useful engine internals collapsed behind "engine ▾"
// (cycles, experiments, graph). The old Dashboard/Activity/Todo/Ideas
// surfaces are gone; /todo, /ideas and /coordinator redirect.
const NAV = [
  { to: "/", label: "pulse", end: true },
  { to: "/ladder", label: "ladder", end: false },
  { to: "/dossier", label: "dossiers", end: false },
  // S4: the lab channel — the always-on human ⇄ Nara ⇄ PI conversation.
  { to: "/channel", label: "channel", end: false },
];

// Engine-internal destinations, collapsed. A plain <details> disclosure (no
// new deps): the panel overlays absolutely so opening it never reflows the
// page body.
const ENGINE_NAV = [
  { to: "/cycles", label: "cycles" },
  { to: "/experiments", label: "experiments" },
  { to: "/graph", label: "graph" },
];

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
            <details className="group relative" data-testid="engine-nav">
              <summary className="cursor-pointer list-none border-b-2 border-transparent pb-1 font-mono text-sm text-zinc-400 transition-colors hover:text-zinc-100">
                engine ▾
              </summary>
              <div className="absolute left-0 top-full z-20 mt-1 flex min-w-36 flex-col gap-1 rounded border border-zinc-800 bg-zinc-950 px-3 py-2 shadow-lg">
                {ENGINE_NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `font-mono text-sm transition-colors ${
                        isActive
                          ? "text-zinc-100"
                          : "text-zinc-400 hover:text-zinc-100"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </details>
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
        {/* Page-top loop-alert surface (work order A): red/amber off
            run_state/loop_alert.json; invisible when ok & fresh. */}
        <LoopAlertBanner />
        <Routes>
          <Route path="/" element={<Pulse />} />
          <Route path="/ladder" element={<Ladder />} />
          {/* /ideas folded into /ladder (its ideas.md render is the ladder
              page's fallback body). */}
          <Route path="/ideas" element={<Navigate to="/ladder" replace />} />
          {/* the dossier surfaces (S2): index picker + per-id reader. The old
              /todo cockpit is retired — its bookmark redirects. */}
          <Route path="/dossier" element={<DossierIndex />} />
          <Route path="/dossier/:id" element={<DossierReader />} />
          <Route path="/todo" element={<Navigate to="/dossier" replace />} />
          {/* S4: the lab channel (timeline + turn + delegate; no
              disposition surface — the fence). */}
          <Route path="/channel" element={<Channel />} />
          {/* Engine internals. /coordinator bookmarks redirect to the
              renamed /cycles; /dashboard + /activity are gone (S3). */}
          <Route path="/cycles" element={<Cycles />} />
          <Route path="/coordinator" element={<Navigate to="/cycles" replace />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/experiments/:expId" element={<ExperimentDetail />} />
          {/* Wrapper-rooted tool-call chains (logs/calls.jsonl). */}
          <Route path="/chain/req/:requestId" element={<Inspector />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
