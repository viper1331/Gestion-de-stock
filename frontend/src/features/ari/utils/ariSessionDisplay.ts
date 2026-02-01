import type { AriSession } from "../../../types/ari";

export const statusBadgeClasses = {
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  CERTIFIED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  REJECTED: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  COMPLETED: "border-slate-600/40 bg-slate-800/40 text-slate-200",
  DRAFT: "border-slate-700/40 bg-slate-800/30 text-slate-300"
};

export const formatMinutes = (value: number | null) => {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(1)} min`;
};

export const formatAir = (value: number | null) => {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(1)} L/min`;
};

export const getAirPerMinute = (session: AriSession): number | null => {
  if (!session.duration_seconds || session.duration_seconds <= 0) {
    return null;
  }
  if (session.air_consumed_bar === null || session.air_consumed_bar === undefined) {
    return null;
  }
  return (session.air_consumed_bar * 60) / session.duration_seconds;
};

export const getDurationMinutes = (session: AriSession): number | null => {
  if (!session.duration_seconds || session.duration_seconds <= 0) {
    return null;
  }
  return session.duration_seconds / 60;
};
