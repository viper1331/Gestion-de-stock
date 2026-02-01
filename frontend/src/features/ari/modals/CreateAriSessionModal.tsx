import { useEffect, useMemo, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";
import type { AriSession, AriSettings } from "../../../types/ari";

type CreateAriSessionPayload = {
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

type CollaboratorOption = {
  id: number;
  full_name: string;
  department?: string | null;
};

interface CreateAriSessionModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateAriSessionPayload) => Promise<AriSession>;
  collaboratorId: number | null;
  settings: AriSettings | null;
  collaborators: CollaboratorOption[];
  session?: AriSession | null;
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
  collaborators,
  session
}: CreateAriSessionModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [performedAt, setPerformedAt] = useState(toLocalDateTimeInput(new Date()));
  const [selectedCollaboratorId, setSelectedCollaboratorId] = useState<number | "">(
    collaboratorId ?? ""
  );
  const [courseName, setCourseName] = useState("");
  const [durationInput, setDurationInput] = useState("600");
  const [cylinderCapacity, setCylinderCapacity] = useState("6.8");
  const [startPressure, setStartPressure] = useState("300");
  const [endPressure, setEndPressure] = useState("200");
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
    if (session) {
      setPerformedAt(toLocalDateTimeInput(new Date(session.performed_at)));
      setCourseName(session.course_name || "");
      setDurationInput(String(session.duration_seconds));
      setCylinderCapacity(session.cylinder_capacity_l.toString());
      setStartPressure(session.start_pressure_bar.toString());
      setEndPressure(session.end_pressure_bar.toString());
      setStressLevel(session.stress_level.toString());
      setRpe(session.rpe ? session.rpe.toString() : "");
      setPhysioNotes(session.physio_notes ?? "");
      setObservations(session.observations ?? "");
      setPreValues({
        bp_sys: session.bp_sys_pre?.toString() ?? "",
        bp_dia: session.bp_dia_pre?.toString() ?? "",
        hr: session.hr_pre?.toString() ?? "",
        spo2: session.spo2_pre?.toString() ?? ""
      });
      setPostValues({
        bp_sys: session.bp_sys_post?.toString() ?? "",
        bp_dia: session.bp_dia_post?.toString() ?? "",
        hr: session.hr_post?.toString() ?? "",
        spo2: session.spo2_post?.toString() ?? ""
      });
      setSelectedCollaboratorId(session.collaborator_id);
      return;
    }
    setPerformedAt(toLocalDateTimeInput(new Date()));
    setCourseName("");
    setDurationInput("600");
    setCylinderCapacity("6.8");
    setStartPressure("300");
    setEndPressure("200");
    setStressLevel("5");
    setRpe("");
    setPhysioNotes("");
    setObservations("");
    setPreValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
    setPostValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
    setSelectedCollaboratorId(collaboratorId ?? "");
  }, [open, collaboratorId, session]);

  useEffect(() => {
    if (collaboratorId) {
      setSelectedCollaboratorId(collaboratorId);
    }
  }, [collaboratorId]);

  const durationSeconds = useMemo(
    () => parseDurationInput(durationInput),
    [durationInput]
  );
  const cylinderCapacityValue = useMemo(
    () => parseOptionalNumber(cylinderCapacity),
    [cylinderCapacity]
  );
  const startPressureValue = useMemo(() => parseOptionalNumber(startPressure), [startPressure]);
  const endPressureValue = useMemo(() => parseOptionalNumber(endPressure), [endPressure]);
  const stressValue = useMemo(() => parseOptionalNumber(stressLevel), [stressLevel]);
  const airMetrics = useMemo(() => {
    if (
      cylinderCapacityValue === null ||
      startPressureValue === null ||
      endPressureValue === null ||
      durationSeconds === null ||
      durationSeconds <= 0
    ) {
      return null;
    }
    const deltaBar = startPressureValue - endPressureValue;
    if (deltaBar <= 0) {
      return null;
    }
    const airConsumedL = cylinderCapacityValue * deltaBar;
    const durationMin = durationSeconds / 60;
    if (durationMin <= 0) {
      return null;
    }
    const airConsumptionLpm = airConsumedL / durationMin;
    if (airConsumptionLpm <= 0) {
      return null;
    }
    const autonomyStart = (cylinderCapacityValue * startPressureValue) / airConsumptionLpm;
    const autonomyEnd = (cylinderCapacityValue * endPressureValue) / airConsumptionLpm;
    return {
      airConsumedL,
      airConsumptionLpm,
      autonomyStart,
      autonomyEnd
    };
  }, [cylinderCapacityValue, durationSeconds, endPressureValue, startPressureValue]);
  const canSubmit = useMemo(() => {
    return Boolean(
      selectedCollaboratorId &&
        durationSeconds &&
        durationSeconds > 0 &&
        cylinderCapacityValue !== null &&
        cylinderCapacityValue > 0 &&
        startPressureValue !== null &&
        endPressureValue !== null &&
        stressValue !== null
    );
  }, [
    selectedCollaboratorId,
    durationSeconds,
    cylinderCapacityValue,
    endPressureValue,
    startPressureValue,
    stressValue
  ]);

  const handleSubmit = async () => {
    if (
      !selectedCollaboratorId ||
      !canSubmit ||
      isSubmitting ||
      durationSeconds === null ||
      cylinderCapacityValue === null ||
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
        cylinder_capacity_l: cylinderCapacityValue,
        start_pressure_bar: startPressureValue,
        end_pressure_bar: endPressureValue,
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
      title={session ? "Modifier une séance ARI" : "Ajouter une séance ARI"}
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
              session ? "Mettre à jour" : "Créer"
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
          Capacité bouteille (L)
          <input
            type="number"
            min={0}
            step="0.1"
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={cylinderCapacity}
            onChange={(event) => setCylinderCapacity(event.target.value)}
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
        <div className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-200 sm:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Résultats air (prévisualisation)
          </p>
          {airMetrics ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-slate-400">Volume consommé</p>
                <p className="text-sm font-semibold text-white">
                  {airMetrics.airConsumedL.toFixed(1)} L
                </p>
              </div>
              <div>
                <p className="text-slate-400">Consommation moyenne</p>
                <p className="text-sm font-semibold text-white">
                  {airMetrics.airConsumptionLpm.toFixed(1)} L/min
                </p>
              </div>
              <div>
                <p className="text-slate-400">Autonomie départ</p>
                <p className="text-sm font-semibold text-white">
                  {airMetrics.autonomyStart.toFixed(1)} min
                </p>
              </div>
              <div>
                <p className="text-slate-400">Autonomie fin</p>
                <p className="text-sm font-semibold text-white">
                  {airMetrics.autonomyEnd.toFixed(1)} min
                </p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-400">Renseignez les champs pour voir les calculs.</p>
          )}
        </div>
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
