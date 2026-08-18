import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import LoopAlertBanner from "./components/LoopAlertBanner";
import CommandPalette from "./design/CommandPalette";
import "./design/primitives.css";
import Channel from "./routes/Channel";
import Cycles from "./routes/Cycles";
import DossierIndex from "./routes/DossierIndex";
import DossierReader from "./routes/DossierReader";
import ExperimentDetail from "./routes/ExperimentDetail";
import Experiments from "./routes/Experiments";
import Graph from "./routes/Graph";
import Inspector from "./routes/Inspector";
import Ladder from "./routes/Ladder";
import ModelIO from "./routes/ModelIO";
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
  // Model I/O (owner request 2026-08-18): what actually passes through
  // gemma/qwen + the dispatch trace. Also reachable from Pulse's model
  // server cards ("what's passing through →").
  { to: "/model-io", label: "model i/o" },
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
        // R0 shell: the active nav item is the ONE accent usage in the nav
        // (design/tokens.css — accent is links/primary-action/focus/active-nav).
        `border-b-2 pb-1 text-[13px] font-[550] transition-colors ${
          isActive
            ? "border-[var(--accent)] text-[var(--accent)]"
            : "border-transparent text-[var(--fg-muted)] hover:text-[var(--fg)]"
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
      <div className="min-h-screen bg-[var(--bg)] text-[var(--fg)]">
        {/* R0 shell: sticky glass header — with the palette scrim, the only
            two allowed translucent/blurred surfaces (design/primitives.css). */}
        <header className="dsn-header flex items-center gap-5 px-6 py-3">
          <span className="font-mono text-xs uppercase tracking-wide text-[var(--fg-muted)]">
            apparatus observability
          </span>
          <nav className="flex items-center gap-4">
            {NAV.map((item) => (
              <NavTab key={item.to} {...item} />
            ))}
            <details className="group relative" data-testid="engine-nav">
              <summary className="cursor-pointer list-none border-b-2 border-transparent pb-1 text-[13px] font-[550] text-[var(--fg-muted)] transition-colors hover:text-[var(--fg)]">
                engine ▾
              </summary>
              {/* Menus elevate by surface step + 1px border — never shadow. */}
              <div className="absolute left-0 top-full z-20 mt-1 flex min-w-36 flex-col gap-1 rounded-[6px] border border-[var(--border-1)] bg-[var(--surface-3)] px-3 py-2">
                {ENGINE_NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `text-[13px] font-[550] transition-colors ${
                        isActive
                          ? "text-[var(--accent)]"
                          : "text-[var(--fg-muted)] hover:text-[var(--fg)]"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </details>
            {/* Cross-nav to the agent-system brain governance dashboard —
                served by the framework's brain_server.py on :5180 (bound to
                0.0.0.0; /dashboard.html verified serving HTML 2026-08-15).
                The old :5174 http.server no longer listens — that link was a
                dead tab (loop3h-ui-hotfix). Built from the page hostname —
                not localhost — so the link works over the LAN exactly like
                API_BASE does. */}
            <a
              href={`http://${window.location.hostname}:5180/dashboard.html`}
              target="_blank"
              rel="noreferrer"
              className="border-b-2 border-transparent pb-1 text-[13px] font-[550] text-[var(--fg-muted)] transition-colors hover:text-[var(--fg)]"
            >
              brain<span aria-hidden="true" className="ml-0.5">↗</span>
            </a>
          </nav>
          <span className="ml-auto text-xs text-[var(--fg-muted)]">
            ⌘K to jump · call-chain inspector at /chain/req/&lt;request_id&gt;
          </span>
        </header>
        <CommandPalette />
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
          {/* Model I/O viewer: live wrapper-call table (logs/calls.jsonl)
              + dispatch trace (orchestrator.jsonl / spawn ledger). */}
          <Route path="/model-io" element={<ModelIO />} />
          {/* Wrapper-rooted tool-call chains (logs/calls.jsonl). */}
          <Route path="/chain/req/:requestId" element={<Inspector />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
