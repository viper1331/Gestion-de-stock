import { api } from "../lib/api";

export interface AdminSettings {
  feature_ari_enabled: boolean;
}

export async function fetchAdminSettings(): Promise<AdminSettings> {
  const response = await api.get<AdminSettings>("/admin/settings");
  return response.data;
}

export async function updateAdminSettings(
  payload: Partial<AdminSettings>
): Promise<AdminSettings> {
  const response = await api.patch<AdminSettings>("/admin/settings", payload);
  return response.data;
}
