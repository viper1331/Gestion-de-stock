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
  air_consumed_bar?: number | null;
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

type CollaboratorOption = {
  id: number;
  full_name: string;
  department?: string | null;
};

interface CreateAriSessionModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateAriSessionPayload) => Promise<void>;
  collaboratorId: number | null;
  settings: AriSettings | null;
  collaborators: CollaboratorOption[];
}

const toLocalDateTimeInput = (date: Date) => {
  const tzOffset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - tzOffset).toISOString().slice(0, 16);
};

const parseOptionalNumber = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return parsed;
};

const parseDurationInput = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.includes(":")) {
    const [minutes, seconds] = trimmed.split(":").map((entry) => Number(entry));
    if (Number.isNaN(minutes) || Number.isNaN(seconds)) {
      return null;
    }
    return minutes * 60 + seconds;
  }
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return parsed;
};

export function CreateAriSessionModal({
  open,
  onClose,
  onSubmit,
  collaboratorId,
  settings,
  collaborators
}: CreateAriSessionModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [performedAt, setPerformedAt] = useState(toLocalDateTimeInput(new Date()));
  const [selectedCollaboratorId, setSelectedCollaboratorId] = useState<number | "">(
    collaboratorId ?? ""
  );
  const [courseName, setCourseName] = useState("");
  const [durationInput, setDurationInput] = useState("600");
  const [startPressure, setStartPressure] = useState("300");
  const [endPressure, setEndPressure] = useState("200");
  const [airConsumed, setAirConsumed] = useState("");
  const [stressLevel, setStressLevel] = useState("5");
  const [rpe, setRpe] = useState("");
  const [physioNotes, setPhysioNotes] = useState("");
  const [observations, setObservations] = useState("");
  const [preValues, setPreValues] = useState({
    bp_sys: "",
    bp_dia: "",
    hr: "",
    spo2: ""
  });
  const [postValues, setPostValues] = useState({
    bp_sys: "",
    bp_dia: "",
    hr: "",
    spo2: ""
  });

  useEffect(() => {
    if (!open) {
      return;
    }
    setPerformedAt(toLocalDateTimeInput(new Date()));
    setCourseName("");
    setDurationInput("600");
    setStartPressure("300");
    setEndPressure("200");
    setAirConsumed("");
    setStressLevel("5");
    setRpe("");
    setPhysioNotes("");
    setObservations("");
    setPreValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
    setPostValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
    setSelectedCollaboratorId(collaboratorId ?? "");
  }, [open]);

  useEffect(() => {
    if (collaboratorId) {
      setSelectedCollaboratorId(collaboratorId);
    }
  }, [collaboratorId]);

  const durationSeconds = useMemo(
    () => parseDurationInput(durationInput),
    [durationInput]
  );
  const startPressureValue = useMemo(() => parseOptionalNumber(startPressure), [startPressure]);
  const endPressureValue = useMemo(() => parseOptionalNumber(endPressure), [endPressure]);
  const stressValue = useMemo(() => parseOptionalNumber(stressLevel), [stressLevel]);
  const canSubmit = useMemo(() => {
    return Boolean(
      selectedCollaboratorId &&
        durationSeconds &&
        durationSeconds > 0 &&
        startPressureValue !== null &&
        endPressureValue !== null &&
        stressValue !== null
    );
  }, [selectedCollaboratorId, durationSeconds, endPressureValue, startPressureValue, stressValue]);

  const handleSubmit = async () => {
    if (
      !selectedCollaboratorId ||
      !canSubmit ||
      isSubmitting ||
      durationSeconds === null ||
      startPressureValue === null ||
      endPressureValue === null ||
      stressValue === null
    ) {
      return;
    }
    setIsSubmitting(true);
    try {
      const payload: CreateAriSessionPayload = {
        collaborator_id: Number(selectedCollaboratorId),
        performed_at: new Date(performedAt).toISOString(),
        course_name: courseName.trim() || "Séance ARI",
        duration_seconds: durationSeconds,
        start_pressure_bar: startPressureValue,
        end_pressure_bar: endPressureValue,
        air_consumed_bar: parseOptionalNumber(airConsumed),
        stress_level: stressValue,
        rpe: parseOptionalNumber(rpe),
        physio_notes: physioNotes.trim() || null,
        observations: observations.trim() || null,
        bp_sys_pre: parseOptionalNumber(preValues.bp_sys),
        bp_dia_pre: parseOptionalNumber(preValues.bp_dia),
        hr_pre: parseOptionalNumber(preValues.hr),
        spo2_pre: parseOptionalNumber(preValues.spo2),
        bp_sys_post: parseOptionalNumber(postValues.bp_sys),
        bp_dia_post: parseOptionalNumber(postValues.bp_dia),
        hr_post: parseOptionalNumber(postValues.hr),
        spo2_post: parseOptionalNumber(postValues.spo2)
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
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400 sm:col-span-2">
          Collaborateur
          <select
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={selectedCollaboratorId}
            onChange={(event) =>
              setSelectedCollaboratorId(event.target.value ? Number(event.target.value) : "")
            }
          >
            <option value="">Sélectionner un collaborateur</option>
            {collaborators.map((collaborator) => (
              <option key={collaborator.id} value={collaborator.id}>
                {collaborator.full_name}
                {collaborator.department ? ` · ${collaborator.department}` : ""}
              </option>
            ))}
          </select>
        </label>
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
          Temps (mm:ss ou secondes)
          <input
            type="text"
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={durationInput}
            onChange={(event) => setDurationInput(event.target.value)}
            placeholder="Ex: 12:30"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Pression départ (bar)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={startPressure}
            onChange={(event) => setStartPressure(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Pression fin (bar)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={endPressure}
            onChange={(event) => setEndPressure(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Consommation d'air (bar)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={airConsumed}
            onChange={(event) => setAirConsumed(event.target.value)}
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
            onChange={(event) => setStressLevel(event.target.value)}
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
              onChange={(event) => setRpe(event.target.value)}
            />
          </label>
        ) : null}
        <div className="grid gap-3 sm:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Physiologie avant
          </p>
          <div className="grid gap-3 sm:grid-cols-4">
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={preValues.bp_sys}
              onChange={(event) => setPreValues({ ...preValues, bp_sys: event.target.value })}
              placeholder="TA systolique"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={preValues.bp_dia}
              onChange={(event) => setPreValues({ ...preValues, bp_dia: event.target.value })}
              placeholder="TA diastolique"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={preValues.hr}
              onChange={(event) => setPreValues({ ...preValues, hr: event.target.value })}
              placeholder="HR"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={preValues.spo2}
              onChange={(event) => setPreValues({ ...preValues, spo2: event.target.value })}
              placeholder="SpO2"
            />
          </div>
        </div>
        <div className="grid gap-3 sm:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Physiologie après
          </p>
          <div className="grid gap-3 sm:grid-cols-4">
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={postValues.bp_sys}
              onChange={(event) => setPostValues({ ...postValues, bp_sys: event.target.value })}
              placeholder="TA systolique"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={postValues.bp_dia}
              onChange={(event) => setPostValues({ ...postValues, bp_dia: event.target.value })}
              placeholder="TA diastolique"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={postValues.hr}
              onChange={(event) => setPostValues({ ...postValues, hr: event.target.value })}
              placeholder="HR"
            />
            <input
              type="number"
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={postValues.spo2}
              onChange={(event) => setPostValues({ ...postValues, spo2: event.target.value })}
              placeholder="SpO2"
            />
          </div>
        </div>
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
