import { useEffect, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";

interface ResetAriCertificationModalProps {
  open: boolean;
  onClose: () => void;
  collaboratorName?: string;
  onSubmit: (payload: { reason: string }) => Promise<void>;
}

export function ResetAriCertificationModal({
  open,
  onClose,
  collaboratorName,
  onSubmit
}: ResetAriCertificationModalProps) {
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setReason("");
      setIsSubmitting(false);
    }
  }, [open]);

  const handleSubmit = async () => {
    if (!reason.trim() || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmit({ reason: reason.trim() });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DraggableModal
      open={open}
      onClose={onClose}
      title="Réinitialiser la certification"
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
            className="inline-flex items-center gap-2 rounded-md bg-rose-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-70"
            onClick={handleSubmit}
            disabled={isSubmitting || !reason.trim()}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Réinitialisation...
              </>
            ) : (
              "Confirmer"
            )}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-sm text-slate-200">
        <p className="text-sm text-slate-300">
          {collaboratorName
            ? `Certification de ${collaboratorName}`
            : "Certification du collaborateur sélectionné"}
        </p>
        <p className="text-xs text-amber-200">
          Cette action annule la certification et supprime sa date d'expiration.
        </p>
        <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Raison
          <textarea
            className="min-h-[90px] rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-rose-400 focus:outline-none"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Erreur de saisie / session invalide / recyclage nécessaire"
          />
        </label>
      </div>
    </DraggableModal>
  );
}
