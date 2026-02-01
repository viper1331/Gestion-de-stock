import { useEffect, useMemo, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";

type AriDecisionStatus = "APPROVED" | "REJECTED" | "CONDITIONAL";

interface DecideAriCertificationModalProps {
  open: boolean;
  onClose: () => void;
  collaboratorId: number | null;
  onSubmit: (payload: { collaborator_id: number; status: AriDecisionStatus; comment?: string | null }) => Promise<void>;
}

export function DecideAriCertificationModal({
  open,
  onClose,
  collaboratorId,
  onSubmit
}: DecideAriCertificationModalProps) {
  const [status, setStatus] = useState<AriDecisionStatus>("APPROVED");
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setStatus("APPROVED");
      setComment("");
    }
  }, [open]);

  const requiresComment = status === "REJECTED" || status === "CONDITIONAL";
  const canSubmit = useMemo(() => {
    if (!collaboratorId) {
      return false;
    }
    if (!requiresComment) {
      return true;
    }
    return comment.trim().length > 0;
  }, [collaboratorId, comment, requiresComment]);

  const handleSubmit = async () => {
    if (!collaboratorId || !canSubmit || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmit({
        collaborator_id: collaboratorId,
        status,
        comment: comment.trim() || null
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
      title="Décider la certification"
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
            disabled={!canSubmit || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Validation...
              </>
            ) : (
              "Valider"
            )}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Statut
          <select
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={status}
            onChange={(event) => setStatus(event.target.value as AriDecisionStatus)}
          >
            <option value="APPROVED">Approuvée</option>
            <option value="CONDITIONAL">Conditionnelle</option>
            <option value="REJECTED">Refusée</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Commentaire {requiresComment ? "(obligatoire)" : "(optionnel)"}
          <textarea
            rows={4}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            required={requiresComment}
          />
        </label>
      </div>
    </DraggableModal>
  );
}
