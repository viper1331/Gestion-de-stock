import { useEffect, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";
import type { AriSettings } from "../../../types/ari";

interface AriSettingsModalProps {
  open: boolean;
  onClose: () => void;
  settings: AriSettings | null;
  onSubmit: (payload: AriSettings) => Promise<void>;
}

export function AriSettingsModal({ open, onClose, settings, onSubmit }: AriSettingsModalProps) {
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [stressRequired, setStressRequired] = useState(true);
  const [rpeEnabled, setRpeEnabled] = useState(false);
  const [minSessions, setMinSessions] = useState(1);
  const [certValidityDays, setCertValidityDays] = useState(365);
  const [certWarningDays, setCertWarningDays] = useState(30);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setFeatureEnabled(settings?.feature_enabled ?? false);
    setStressRequired(settings?.stress_required ?? true);
    setRpeEnabled(settings?.rpe_enabled ?? false);
    setMinSessions(settings?.min_sessions_for_certification ?? 1);
    setCertValidityDays(settings?.cert_validity_days ?? 365);
    setCertWarningDays(settings?.cert_expiry_warning_days ?? 30);
  }, [open, settings]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await onSubmit({
        feature_enabled: featureEnabled,
        stress_required: stressRequired,
        rpe_enabled: rpeEnabled,
        min_sessions_for_certification: minSessions,
        cert_validity_days: certValidityDays,
        cert_expiry_warning_days: certWarningDays
      });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DraggableModal
      open={open}
      onClose={onClose}
      title="Paramètres ARI"
      maxWidthClassName="max-w-lg"
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
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Enregistrement...
              </>
            ) : (
              "Enregistrer"
            )}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-4 text-sm text-slate-200">
        <label className="flex items-center justify-between gap-4">
          <span>Activer le module ARI</span>
          <input
            type="checkbox"
            checked={featureEnabled}
            onChange={(event) => setFeatureEnabled(event.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
          />
        </label>
        <label className="flex items-center justify-between gap-4">
          <span>Stress requis</span>
          <input
            type="checkbox"
            checked={stressRequired}
            onChange={(event) => setStressRequired(event.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
          />
        </label>
        <label className="flex items-center justify-between gap-4">
          <span>RPE activé</span>
          <input
            type="checkbox"
            checked={rpeEnabled}
            onChange={(event) => setRpeEnabled(event.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
          />
        </label>
        <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Minimum de séances pour certification
          <input
            type="number"
            min={1}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={minSessions}
            onChange={(event) => setMinSessions(Number(event.target.value))}
          />
        </label>
        <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Durée de validité (jours)
          <input
            type="number"
            min={1}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={certValidityDays}
            onChange={(event) => setCertValidityDays(Number(event.target.value))}
          />
        </label>
        <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Alerte avant expiration (jours)
          <input
            type="number"
            min={0}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={certWarningDays}
            onChange={(event) => setCertWarningDays(Number(event.target.value))}
          />
        </label>
      </div>
    </DraggableModal>
  );
}
