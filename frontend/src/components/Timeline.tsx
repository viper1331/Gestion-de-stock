import { ReactNode } from "react";

export type TimelineEventType =
  | "CREATION"
  | "RECEPTION_CONFORME"
  | "NON_CONFORME"
  | "REMPLACEMENT_DEMANDE"
  | "REMPLACEMENT_CLOTURE"
  | "ENVOI_FOURNISSEUR"
  | "RECEPTION_REMPLACEMENT"
  | "ARCHIVAGE";

export interface TimelineEvent {
  id: string;
  type: TimelineEventType;
  date: string;
  user?: string | null;
  message: string;
}

const EVENT_META: Record<
  TimelineEventType,
  { label: string; icon: ReactNode; className: string }
> = {
  CREATION: {
    label: "Création",
    icon: "🟢",
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
  },
  RECEPTION_CONFORME: {
    label: "Réception conforme",
    icon: "✅",
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
  },
  NON_CONFORME: {
    label: "Non conforme",
    icon: "⚠️",
    className: "border-rose-500/40 bg-rose-500/10 text-rose-100"
  },
  REMPLACEMENT_DEMANDE: {
    label: "Remplacement demandé",
    icon: "🛠️",
    className: "border-amber-500/40 bg-amber-500/10 text-amber-100"
  },
  REMPLACEMENT_CLOTURE: {
    label: "Remplacement clôturé",
    icon: "✅",
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
  },
  ENVOI_FOURNISSEUR: {
    label: "Envoi fournisseur",
    icon: "📤",
    className: "border-sky-500/40 bg-sky-500/10 text-sky-100"
  },
  RECEPTION_REMPLACEMENT: {
    label: "Réception remplacement",
    icon: "📦",
    className: "border-indigo-500/40 bg-indigo-500/10 text-indigo-100"
  },
  ARCHIVAGE: {
    label: "Archivé",
    icon: "🗄️",
    className: "border-slate-500/40 bg-slate-500/10 text-slate-100"
  }
};

export function Timeline({ events, title }: { events: TimelineEvent[]; title?: string }) {
  if (events.length === 0) {
    return (
      <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-400">
        Aucun événement enregistré.
      </div>
    );
  }

  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      {title ? <p className="text-xs font-semibold uppercase text-slate-400">{title}</p> : null}
      <ol className="mt-2 space-y-3">
        {events.map((event) => {
          const meta = EVENT_META[event.type];
          return (
            <li key={event.id} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className="text-base">{meta.icon}</span>
                <span className="mt-1 h-full w-px bg-slate-800" aria-hidden="true" />
              </div>
              <div className="flex-1 rounded border px-3 py-2 text-xs leading-relaxed text-slate-200">
                <div className={`inline-flex items-center gap-2 rounded-full border px-2 py-0.5 text-[10px] ${meta.className}`}>
                  {meta.label}
                </div>
                <div className="mt-1 text-[11px] text-slate-400">
                  {new Date(event.date).toLocaleString()}
                  {event.user ? ` · ${event.user}` : null}
                </div>
                <p className="mt-1 text-slate-100">{event.message}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
