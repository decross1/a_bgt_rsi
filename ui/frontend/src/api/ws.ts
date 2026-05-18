// WebSocket client for the backend's /api/live stream. Auto-reconnects.
// The host is derived from the page so it works through an SSH tunnel
// and over the LAN alike (see api/http.ts).
import type { LiveMessage } from "../types/schemas";

const WS_URL = `ws://${window.location.hostname}:8700/api/live`;

/**
 * Open the live stream. Returns a disposer that closes it permanently.
 * onStatus(true|false) fires on connect / disconnect.
 */
export function connectLive(
  onMessage: (msg: LiveMessage) => void,
  onStatus?: (connected: boolean) => void,
): () => void {
  let socket: WebSocket | null = null;
  let disposed = false;
  let retryTimer: number | undefined;

  function open() {
    if (disposed) return;
    socket = new WebSocket(WS_URL);
    socket.onopen = () => onStatus?.(true);
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data as string) as LiveMessage);
      } catch {
        /* ignore malformed frame */
      }
    };
    socket.onclose = () => {
      onStatus?.(false);
      if (!disposed) retryTimer = window.setTimeout(open, 2000);
    };
    socket.onerror = () => socket?.close();
  }

  open();

  return () => {
    disposed = true;
    if (retryTimer) window.clearTimeout(retryTimer);
    socket?.close();
  };
}
