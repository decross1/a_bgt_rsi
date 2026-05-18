# Frontend

React + Vite + TypeScript + Tailwind SPA: the dashboard and call-chain
inspector. See `ui_plan.md` §5.3. Dark mode only.

Build status: both views are built — the **live dashboard** (`/`, steps
6.5-6.7: health strip, orchestrator queue, vLLM panel, process grid,
baseline card) and the **call-chain inspector** (`/chain/:taskId`,
step 6.3). Telemetry streams over the `/api/live` WebSocket.

## Run (dev)

```sh
cd ui/frontend
npm install
npm run dev          # Vite dev server on :5173 (binds 0.0.0.0)
```

The backend must also be running (`ui/backend/run.sh`, :8700). The SPA
derives the API URL from the page host, so no config is needed.

## Viewing from a remote desktop

The DGX Spark is headless. To view the UI from a local machine:

**Option A — SSH tunnel (recommended).** From the local machine:

```sh
ssh -L 5173:localhost:5173 -L 8700:localhost:8700 <user>@<spark-host>
```

Then open `http://localhost:5173` in the local browser. Both the SPA
and its API calls travel through the tunnel.

**Option B — direct LAN.** If the local machine is on the same network,
open `http://<spark-ip>:5173` directly. The dev server and backend both
bind `0.0.0.0`; the SPA will call the backend at `<spark-ip>:8700`.

## Build / test

```sh
npm run build        # tsc typecheck + vite production build -> dist/
npm test             # vitest
```
