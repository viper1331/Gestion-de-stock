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
