import { api } from "../../lib/api";
import { UpdateApplyResponse, UpdateAvailability, UpdateStatus } from "./types";

export async function fetchUpdateStatus(): Promise<UpdateStatus> {
  const response = await api.get<UpdateStatus>("/updates/status");
  return response.data;
}

export async function fetchUpdateAvailability(): Promise<UpdateAvailability> {
  const response = await api.get<UpdateAvailability>("/updates/availability");
  return response.data;
}

export async function applyLatestUpdate(): Promise<UpdateApplyResponse> {
  const response = await api.post<UpdateApplyResponse>("/updates/apply");
  return response.data;
}

export async function revertToPreviousUpdate(): Promise<UpdateApplyResponse> {
  const response = await api.post<UpdateApplyResponse>("/updates/revert");
  return response.data;
}
