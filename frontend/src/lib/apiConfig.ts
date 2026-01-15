import { API_BASE_URL } from "./env";

export interface SystemConfigSnapshot {
  backend_url?: string | null;
  backend_url_lan?: string | null;
  backend_url_public?: string | null;
  network_mode?: string | null;
}

export interface ResolvedApiConfig {
  baseUrl: string;
  source: "lan" | "public" | "env_default";
}

const FALLBACK_BASE_URL = API_BASE_URL.replace(/\/$/, "");

let cachedConfig: ResolvedApiConfig | null = null;
let pendingPromise: Promise<ResolvedApiConfig> | null = null;

function normalizeUrl(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.replace(/\/$/, "");
}

function normalizeNetworkMode(mode?: string | null): "auto" | "lan" | "public" {
  if (mode === "internet") return "public";
  if (mode === "lan" || mode === "public" || mode === "auto") {
    return mode;
  }
  return "auto";
}

function isPrivateHostname(hostname: string): boolean {
  const normalized = hostname.toLowerCase();
  if (normalized === "localhost" || normalized === "127.0.0.1") return true;
  if (/^10\.\d+\.\d+\.\d+$/.test(normalized)) return true;
  if (/^192\.168\.\d+\.\d+$/.test(normalized)) return true;
  if (/^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/.test(normalized)) return true;
  return false;
}

function resolveFromConfig(
  config: SystemConfigSnapshot | null,
  hostname: string
): ResolvedApiConfig {
  const mode = normalizeNetworkMode(config?.network_mode ?? null);
  const lanUrl = normalizeUrl(config?.backend_url_lan) ?? normalizeUrl(config?.backend_url);
  const publicUrl =
    normalizeUrl(config?.backend_url_public) ??
    normalizeUrl((config as Record<string, string | null | undefined> | null)?.backend_public_url);

  const lanCandidate = lanUrl ?? publicUrl ?? FALLBACK_BASE_URL;
  const publicCandidate = publicUrl ?? lanUrl ?? FALLBACK_BASE_URL;

  if (mode === "lan") {
    return { baseUrl: lanCandidate, source: lanUrl ? "lan" : "env_default" };
  }

  if (mode === "public") {
    return { baseUrl: publicCandidate, source: publicUrl ? "public" : "env_default" };
  }

  const isPrivate = isPrivateHostname(hostname);
  if (isPrivate) {
    if (lanUrl) return { baseUrl: lanUrl, source: "lan" };
    if (publicUrl) return { baseUrl: publicUrl, source: "public" };
    return { baseUrl: FALLBACK_BASE_URL, source: "env_default" };
  }

  if (publicUrl) return { baseUrl: publicUrl, source: "public" };
  if (lanUrl) return { baseUrl: lanUrl, source: "lan" };
  return { baseUrl: FALLBACK_BASE_URL, source: "env_default" };
}

async function fetchSystemConfig(): Promise<SystemConfigSnapshot | null> {
  const token = typeof window !== "undefined" ? localStorage.getItem("gsp/token") : null;
  try {
    const response = await fetch(`${FALLBACK_BASE_URL}/system/public-config`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      credentials: "include"
    });
    if (!response.ok) {
      throw new Error(`Config fetch failed (${response.status})`);
    }
    return (await response.json()) as SystemConfigSnapshot;
  } catch (error) {
    console.warn("Impossible de charger la configuration système, fallback sur VITE_API_BASE_URL.", error);
    return null;
  }
}

export function getCachedApiConfig(): ResolvedApiConfig | null {
  return cachedConfig;
}

export function getCachedApiBaseUrl(): string {
  return (cachedConfig?.baseUrl ?? FALLBACK_BASE_URL).replace(/\/$/, "");
}

export function resolveApiBaseUrlFromConfig(config: SystemConfigSnapshot | null): ResolvedApiConfig {
  const hostname = typeof window !== "undefined" ? window.location.hostname : "localhost";
  return resolveFromConfig(config, hostname);
}

export async function resolveApiBaseUrl(): Promise<ResolvedApiConfig> {
  if (cachedConfig) {
    return cachedConfig;
  }

  if (pendingPromise) {
    return pendingPromise;
  }

  pendingPromise = (async () => {
    const hostname = typeof window !== "undefined" ? window.location.hostname : "localhost";
    const remoteConfig = await fetchSystemConfig();
    const resolved = resolveFromConfig(remoteConfig, hostname);
    cachedConfig = resolved;
    pendingPromise = null;
    return resolved;
  })();

  return pendingPromise;
}

export function resetApiConfigCache() {
  cachedConfig = null;
  pendingPromise = null;
}
