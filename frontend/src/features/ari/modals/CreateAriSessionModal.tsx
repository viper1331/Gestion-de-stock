import { useEffect, useMemo, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";
import type { AriSettings } from "../../../types/ari";

type CreateAriSessionPayload = {
  collaborator_id: number;
  performed_at: string;
  course_name: string;
  duration_seconds: number;
  start_pressure_bar: number;
  end_pressure_bar: number;
  stress_level: number;
  rpe?: number | null;
  physio_notes?: string | null;
  observations?: string | null;
};

interface CreateAriSessionModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateAriSessionPayload) => Promise<void>;
  collaboratorId: number | null;
  settings: AriSettings | null;
}

const toLocalDateTimeInput = (date: Date) => {
  const tzOffset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - tzOffset).toISOString().slice(0, 16);
};

export function CreateAriSessionModal({
  open,
  onClose,
  onSubmit,
  collaboratorId,
  settings
}: CreateAriSessionModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [performedAt, setPerformedAt] = useState(toLocalDateTimeInput(new Date()));
  const [courseName, setCourseName] = useState("");
  const [durationSeconds, setDurationSeconds] = useState(600);
  const [startPressure, setStartPressure] = useState(300);
  const [endPressure, setEndPressure] = useState(200);
  const [stressLevel, setStressLevel] = useState(5);
  const [rpe, setRpe] = useState<number | "">("");
  const [physioNotes, setPhysioNotes] = useState("");
  const [observations, setObservations] = useState("");

  useEffect(() => {
    if (!open) {
      return;
    }
    setPerformedAt(toLocalDateTimeInput(new Date()));
    setCourseName("");
    setDurationSeconds(600);
    setStartPressure(300);
    setEndPressure(200);
    setStressLevel(5);
    setRpe("");
    setPhysioNotes("");
    setObservations("");
  }, [open]);

  const canSubmit = useMemo(() => {
    return Boolean(collaboratorId && courseName.trim() && durationSeconds > 0);
  }, [collaboratorId, courseName, durationSeconds]);

  const handleSubmit = async () => {
    if (!collaboratorId || !canSubmit || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    try {
      const payload: CreateAriSessionPayload = {
        collaborator_id: collaboratorId,
        performed_at: new Date(performedAt).toISOString(),
        course_name: courseName.trim(),
        duration_seconds: Number(durationSeconds),
        start_pressure_bar: Number(startPressure),
        end_pressure_bar: Number(endPressure),
        stress_level: Number(stressLevel),
        rpe: rpe === "" ? null : Number(rpe),
        physio_notes: physioNotes.trim() || null,
        observations: observations.trim() || null
      };
      await onSubmit(payload);
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DraggableModal
      open={open}
      onClose={onClose}
      title="Ajouter une séance ARI"
      maxWidthClassName="max-w-2xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Annuler
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
            onClick={handleSubmit}
            disabled={!canSubmit || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Enregistrement...
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Date & heure
          <input
            type="datetime-local"
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={performedAt}
            onChange={(event) => setPerformedAt(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Parcours
          <input
            type="text"
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={courseName}
            onChange={(event) => setCourseName(event.target.value)}
            placeholder="Parcours ARI"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Durée (s)
          <input
            type="number"
            min={1}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={durationSeconds}
            onChange={(event) => setDurationSeconds(Number(event.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Pression départ (bar)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={startPressure}
            onChange={(event) => setStartPressure(Number(event.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Pression fin (bar)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={endPressure}
            onChange={(event) => setEndPressure(Number(event.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Stress (1-10)
          <input
            type="number"
            min={1}
            max={10}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={stressLevel}
            onChange={(event) => setStressLevel(Number(event.target.value))}
            required={settings?.stress_required ?? true}
          />
        </label>
        {settings?.rpe_enabled ? (
          <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            RPE (1-10)
            <input
              type="number"
              min={1}
              max={10}
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={rpe}
              onChange={(event) => setRpe(event.target.value === "" ? "" : Number(event.target.value))}
            />
          </label>
        ) : null}
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400 sm:col-span-2">
          Notes physiologiques
          <textarea
            rows={3}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={physioNotes}
            onChange={(event) => setPhysioNotes(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400 sm:col-span-2">
          Observations
          <textarea
            rows={3}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={observations}
            onChange={(event) => setObservations(event.target.value)}
          />
        </label>
      </div>
    </DraggableModal>
  );
}
