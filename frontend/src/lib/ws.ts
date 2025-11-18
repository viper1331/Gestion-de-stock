import { getCachedApiBaseUrl } from "./apiConfig";

function buildWsBaseUrl() {
  const override = import.meta.env.VITE_WS_URL;
  if (override && override.trim().length > 0) {
    return override.replace(/\/$/, "");
  }

  const normalizedApi = getCachedApiBaseUrl();
  if (normalizedApi.startsWith("https://")) {
    return normalizedApi.replace(/^https:\/\//, "wss://");
  }
  if (normalizedApi.startsWith("http://")) {
    return normalizedApi.replace(/^http:\/\//, "ws://");
  }
  return normalizedApi;
}

export function createWebSocket(path: string) {
  const base = buildWsBaseUrl();
  const url = `${base}${path}`;
  return new WebSocket(url);
}
