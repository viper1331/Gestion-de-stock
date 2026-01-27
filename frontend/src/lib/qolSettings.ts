import { api } from "./api";

export interface QolSettings {
  timezone: string;
  date_format: string;
  auto_archive_days: number | null;
  note_preview_length: number;
}

export const DEFAULT_QOL_SETTINGS: QolSettings = {
  timezone: "Europe/Paris",
  date_format: "DD/MM/YYYY",
  auto_archive_days: null,
  note_preview_length: 180
};

export async function fetchQolSettings(): Promise<QolSettings> {
  const response = await api.get<QolSettings>("/config/qol-settings");
  return response.data;
}
