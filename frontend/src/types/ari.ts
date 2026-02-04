export type AriSettings = {
  feature_enabled: boolean;
  stress_required: boolean;
  rpe_enabled: boolean;
  min_sessions_for_certification: number;
  cert_validity_days: number;
  cert_expiry_warning_days: number;
};

export type AriSession = {
  id: number;
  collaborator_id: number;
  performed_at: string;
  course_name: string;
  duration_seconds: number;
  start_pressure_bar: number;
  end_pressure_bar: number;
  air_consumed_bar: number;
  cylinder_capacity_l: number;
  air_consumed_l: number;
  air_consumption_lpm: number;
  autonomy_start_min: number;
  autonomy_end_min: number;
  stress_level: number;
  status: "DRAFT" | "COMPLETED" | "CERTIFIED" | "REJECTED";
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
  created_at: string;
  created_by: string;
};

export type AriPurgeRequest = {
  site?: "CURRENT" | "ALL";
  older_than_days?: number | null;
  before_date?: string | null;
  include_certified?: boolean;
  dry_run?: boolean;
};

export type AriPurgeResponse = {
  ok: boolean;
  dry_run: boolean;
  total: number;
  by_site: Record<string, number>;
};

export type AriCertification = {
  collaborator_id: number;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CONDITIONAL" | "NONE";
  comment?: string | null;
  decision_at?: string | null;
  decided_by?: string | null;
  certified_at?: string | null;
  expires_at?: string | null;
  certified_by_user_id?: number | null;
  notes?: string | null;
  reset_at?: string | null;
  reset_by_user_id?: number | null;
  reset_reason?: string | null;
  alert_state?: "valid" | "expiring_soon" | "expired" | "none";
  days_until_expiry?: number | null;
};

export type AriCollaboratorStats = {
  sessions_count: number;
  avg_duration_seconds: number | null;
  avg_air_consumed_bar: number | null;
  avg_air_per_min: number | null;
  avg_stress_level: number | null;
  last_session_at: string | null;
  certification_status: AriCertification["status"];
  certification_decision_at: string | null;
};

export type AriStatsTopSession = {
  session_id: number;
  performed_at: string;
  collaborator_id: number;
  collaborator_name: string;
  air_lpm: number | null;
  duration_min: number | null;
};

export type AriStatsOverview = {
  total_sessions: number;
  distinct_collaborators: number;
  avg_duration_min: number | null;
  avg_air_lpm: number | null;
  validated_count: number;
  rejected_count: number;
  pending_count: number;
  top_sessions_by_air: AriStatsTopSession[];
};

export type AriStatsByCollaboratorRow = {
  collaborator_id: number;
  collaborator_name: string;
  sessions_count: number;
  avg_duration_min: number | null;
  avg_air_lpm: number | null;
  max_air_lpm: number | null;
  last_session_at: string | null;
  status: "pending" | "certified" | "mixed";
};

export type AriStatsByCollaboratorResponse = {
  rows: AriStatsByCollaboratorRow[];
};
