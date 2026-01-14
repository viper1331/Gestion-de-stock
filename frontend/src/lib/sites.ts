import { api } from "./api";

export interface SiteInfo {
  site_key: string;
  display_name: string;
  db_path: string;
  is_active: boolean;
}

export interface SiteContext {
  assigned_site_key: string;
  active_site_key: string;
  override_site_key?: string | null;
  sites?: SiteInfo[];
}

export async function fetchSiteContext(): Promise<SiteContext> {
  const response = await api.get<SiteContext>("/sites/active");
  return response.data;
}

export async function updateActiveSite(siteKey: string | null): Promise<SiteContext> {
  const response = await api.put<SiteContext>("/sites/active", { site_key: siteKey });
  return response.data;
}
