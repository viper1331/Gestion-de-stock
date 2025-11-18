import { api } from "./api";

export interface SystemConfig {
  backend_url: string;
  frontend_url: string;
  backend_host: string;
  backend_port: number;
  frontend_host: string;
  frontend_port: number;
  cors_origins: string[];
  network_mode: "lan" | "internet";
  extra: Record<string, string>;
}

export async function fetchSystemConfig(): Promise<SystemConfig> {
  const response = await api.get<SystemConfig>("/system/config");
  return response.data;
}

export async function updateSystemConfig(payload: SystemConfig): Promise<SystemConfig> {
  const response = await api.post<SystemConfig>("/system/config", payload);
  return response.data;
}
