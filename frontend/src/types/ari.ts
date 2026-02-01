export type AriSettings = {
  feature_enabled: boolean;
  stress_required: boolean;
  rpe_enabled: boolean;
  min_sessions_for_certification: number;
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
  stress_level: number;
  rpe?: number | null;
  physio_notes?: string | null;
  observations?: string | null;
  created_at: string;
  created_by: string;
};

export type AriCertification = {
  collaborator_id: number;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CONDITIONAL";
  comment?: string | null;
  decision_at?: string | null;
  decided_by?: string | null;
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
