import { api } from "../lib/api";
import type {
  AriCertification,
  AriCollaboratorStats,
  AriPurgeRequest,
  AriPurgeResponse,
  AriSession,
  AriSettings,
  AriStatsByCollaboratorResponse,
  AriStatsOverview
} from "../types/ari";

type AriSessionPayload = {
  collaborator_id: number;
  performed_at: string;
  course_name: string;
  duration_seconds: number;
  start_pressure_bar: number;
  end_pressure_bar: number;
  cylinder_capacity_l: number;
  stress_level: number;
  rpe?: number | null;
  physio_notes?: string | null;
  observations?: string | null;
  bp_sys_pre?: number | null;
  bp_dia_pre?: number | null;
  hr_pre?: number | null;
  spo2_pre?: number | null;
  bp_sys_post?: number | null;
  bp_dia_post?: number | null;
  hr_post?: number | null;
  spo2_post?: number | null;
};

type AriDecisionPayload = {
  collaborator_id: number;
  status: "APPROVED" | "REJECTED" | "CONDITIONAL";
  comment?: string | null;
};

type AriSettingsPayload = {
  feature_enabled: boolean;
  stress_required: boolean;
  rpe_enabled: boolean;
  min_sessions_for_certification: number;
};

type AriSessionsQuery = {
  collaborator_id?: number;
  from?: string;
  to?: string;
  course?: string;
  status?: string;
  q?: string;
  sort?: string;
};

const buildAriHeaders = (site?: string) =>
  site ? { "X-ARI-SITE": site } : undefined;

export async function getAriSettings(site?: string) {
  const response = await api.get<AriSettings>("/ari/settings", {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function updateAriSettings(payload: AriSettingsPayload, site?: string) {
  const response = await api.put<AriSettings>("/ari/settings", payload, {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function createAriSession(payload: AriSessionPayload, site?: string) {
  const response = await api.post<AriSession>("/ari/sessions", payload, {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function updateAriSession(
  sessionId: number,
  payload: AriSessionPayload,
  site?: string
) {
  const response = await api.put<AriSession>(`/ari/sessions/${sessionId}`, payload, {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function listAriSessions(
  collaboratorIdOrParams?: number | AriSessionsQuery,
  site?: string
) {
  const params =
    typeof collaboratorIdOrParams === "number" || typeof collaboratorIdOrParams === "undefined"
      ? collaboratorIdOrParams
        ? { collaborator_id: collaboratorIdOrParams }
        : undefined
      : collaboratorIdOrParams;
  const response = await api.get<AriSession[]>("/ari/sessions", {
    params,
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function getAriCollaboratorStats(collaboratorId: number, site?: string) {
  const response = await api.get<AriCollaboratorStats>(
    `/ari/stats/collaborator/${collaboratorId}`,
    { headers: buildAriHeaders(site) }
  );
  return response.data;
}

export async function getAriCertification(collaboratorId: number, site?: string) {
  const response = await api.get<AriCertification>("/ari/certifications", {
    params: { collaborator_id: collaboratorId },
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function listAriPending(site?: string) {
  const response = await api.get<AriCertification[]>("/ari/certifications/pending", {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function decideAriCertification(payload: AriDecisionPayload, site?: string) {
  const response = await api.post<AriCertification>("/ari/certifications/decide", payload, {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function downloadAriPdf(collaboratorId: number, site?: string) {
  const response = await api.get(`/ari/collaborators/${collaboratorId}/export.pdf`, {
    responseType: "blob",
    headers: buildAriHeaders(site)
  });
  const blob = new Blob([response.data], { type: "application/pdf" });
  const url = window.URL.createObjectURL(blob);
  const contentDisposition = response.headers["content-disposition"] as string | undefined;
  const filenameMatch = contentDisposition?.match(/filename=([^;]+)/i);
  const filename = filenameMatch ? filenameMatch[1] : `ari_${collaboratorId}.pdf`;

  const link = document.createElement("a");
  link.href = url;
  link.download = filename.replace(/\"/g, "");
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function purgeAriSessions(payload: AriPurgeRequest, site?: string) {
  const response = await api.post<AriPurgeResponse>("/ari/admin/purge-sessions", payload, {
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function getAriStatsOverview(params?: { from?: string; to?: string }, site?: string) {
  const response = await api.get<AriStatsOverview>("/ari/stats/overview", {
    params,
    headers: buildAriHeaders(site)
  });
  return response.data;
}

export async function getAriStatsByCollaborator(
  params?: { from?: string; to?: string; q?: string; sort?: string },
  site?: string
) {
  const response = await api.get<AriStatsByCollaboratorResponse>("/ari/stats/by-collaborator", {
    params,
    headers: buildAriHeaders(site)
  });
  return response.data;
}
