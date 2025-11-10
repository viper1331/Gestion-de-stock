import { api } from "./api";

export interface ConfigEntry {
  section: string;
  key: string;
  value: string;
}

export async function fetchConfigEntries(): Promise<ConfigEntry[]> {
  const response = await api.get<ConfigEntry[]>("/config/");
  return response.data;
}

export async function fetchUserHomepageConfig(): Promise<ConfigEntry[]> {
  const response = await api.get<ConfigEntry[]>("/config/homepage/personal");
  return response.data;
}

export async function updateUserHomepageConfig(entry: ConfigEntry): Promise<void> {
  await api.post("/config/homepage/personal", entry);
}
