import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Dashboard from "./routes/Dashboard";
import EventsViewer from "./routes/EventsViewer";
import Inspector from "./routes/Inspector";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-zinc-950 text-zinc-200">
        <header className="flex items-baseline gap-4 border-b border-zinc-800 px-6 py-3">
          <Link
            to="/"
            className="font-mono text-sm text-zinc-300 hover:text-zinc-100"
          >
            orchestrator dashboard
          </Link>
          <Link
            to="/events"
            className="font-mono text-sm text-zinc-400 hover:text-zinc-100"
          >
            events
          </Link>
          <span className="text-xs text-zinc-600">/ call-chain inspector</span>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chain/:taskId" element={<Inspector />} />
          {/* Day-4 wrapper-rooted tool-call chains (no orchestrator dispatch). */}
          <Route path="/chain/req/:requestId" element={<Inspector />} />
          <Route path="/events" element={<EventsViewer />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
