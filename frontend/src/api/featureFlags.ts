import { api } from "../lib/api";

export interface FeatureFlags {
  feature_ari_enabled: boolean;
}

export async function fetchFeatureFlags(): Promise<FeatureFlags> {
  const response = await api.get<FeatureFlags>("/config/feature-flags");
  return response.data;
}
