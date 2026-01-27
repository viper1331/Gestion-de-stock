import { ReactNode } from "react";

export type StatusBadgeTone = "success" | "danger" | "warning" | "info" | "neutral";

const TONE_STYLES: Record<StatusBadgeTone, string> = {
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
  danger: "border-rose-500/40 bg-rose-500/10 text-rose-100",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-100",
  neutral: "border-slate-500/40 bg-slate-500/10 text-slate-100"
};

export function StatusBadge({
  label,
  tone = "neutral",
  icon,
  tooltip
}: {
  label: string;
  tone?: StatusBadgeTone;
  icon?: ReactNode;
  tooltip?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${TONE_STYLES[tone]}`}
      title={tooltip}
    >
      {icon ? <span className="text-[11px]">{icon}</span> : null}
      {label}
    </span>
  );
}
