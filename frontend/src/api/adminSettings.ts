import { api } from "../lib/api";

export interface AdminSettings {
  feature_ari_enabled: boolean;
  ari_cert_validity_days: number;
  ari_cert_expiry_warning_days: number;
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
