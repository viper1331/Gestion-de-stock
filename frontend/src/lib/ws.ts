export function createWebSocket(path: string) {
  const base = import.meta.env.VITE_WS_URL ?? "ws://127.0.0.1:8000";
  const url = `${base}${path}`;
  return new WebSocket(url);
}
