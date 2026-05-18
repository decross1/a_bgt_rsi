import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Dashboard from "./routes/Dashboard";
import Inspector from "./routes/Inspector";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-zinc-950 text-zinc-200">
        <header className="border-b border-zinc-800 px-6 py-3">
          <Link
            to="/"
            className="font-mono text-sm text-zinc-300 hover:text-zinc-100"
          >
            orchestrator dashboard
          </Link>
          <span className="ml-2 text-xs text-zinc-600">/ call-chain inspector</span>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chain/:taskId" element={<Inspector />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
