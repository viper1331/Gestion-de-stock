import { api } from "./api";
import { resetApiConfigCache } from "./apiConfig";

export type NetworkMode = "auto" | "lan" | "public";

export interface SystemConfig {
  backend_url?: string | null;
  backend_url_lan?: string | null;
  backend_url_public?: string | null;
  frontend_url: string;
  backend_host: string;
  backend_port: number;
  frontend_host: string;
  frontend_port: number;
  cors_origins: string[];
  network_mode: NetworkMode;
  extra: Record<string, string>;
  backend_public_url?: string | null;
}

export interface PublicSystemConfig {
  idle_logout_minutes: number;
}

function normalizeConfig(payload: SystemConfig): SystemConfig {
  const network_mode: NetworkMode =
    payload.network_mode === "lan" || payload.network_mode === "public" || payload.network_mode === "auto"
      ? payload.network_mode
      : payload.network_mode === "internet"
      ? "public"
      : "auto";

  return {
    ...payload,
    backend_url_public: payload.backend_url_public ?? payload.backend_public_url ?? payload.backend_url ?? null,
    backend_url_lan: payload.backend_url_lan ?? payload.backend_url ?? null,
    network_mode
  };
}

export async function fetchSystemConfig(): Promise<SystemConfig> {
  const response = await api.get<SystemConfig>("/system/config");
  return normalizeConfig(response.data);
}

export async function updateSystemConfig(payload: SystemConfig): Promise<SystemConfig> {
  const response = await api.post<SystemConfig>("/system/config", payload);
  resetApiConfigCache();
  return normalizeConfig(response.data);
}

export async function fetchPublicSystemConfig(): Promise<PublicSystemConfig> {
  const response = await api.get<PublicSystemConfig>("/system/public-config");
  return response.data;
}
