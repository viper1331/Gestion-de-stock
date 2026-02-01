import { useEffect, useMemo, useState } from "react";

import { DraggableModal } from "../../../components/DraggableModal";
import type { AriCertification, AriSession } from "../../../types/ari";

type DecisionStatus = "APPROVED" | "REJECTED";

const statusLabels: Record<AriCertification["status"], string> = {
  PENDING: "En attente",
  APPROVED: "Validé",
  REJECTED: "Refusé",
  CONDITIONAL: "Conditionnel"
};

interface SessionDetailModalProps {
  open: boolean;
  onClose: () => void;
  session: AriSession | null;
  collaboratorName?: string;
  certification: AriCertification | null;
  canCertify: boolean;
  onDecide: (payload: { status: DecisionStatus; comment?: string | null }) => Promise<void>;
}

const formatNumber = (value?: number | null) => (value === null || value === undefined ? "—" : value);

export function SessionDetailModal({
  open,
  onClose,
  session,
  collaboratorName,
  certification,
  canCertify,
  onDecide
}: SessionDetailModalProps) {
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setComment("");
      setIsSubmitting(false);
    }
  }, [open]);

  const pendingBadge = useMemo(() => {
    if (!certification) {
      return "En attente";
    }
    return statusLabels[certification.status];
  }, [certification]);

  const handleDecision = async (status: DecisionStatus) => {
    if (!session || isSubmitting) {
      return;
    }
    if (status === "REJECTED" && !comment.trim()) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onDecide({ status, comment: comment.trim() || null });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DraggableModal
      open={open}
      onClose={onClose}
      title="Détail séance ARI"
      maxWidthClassName="max-w-3xl"
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">
            Statut certification : {pendingBadge}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
              onClick={onClose}
            >
              Fermer
            </button>
            {canCertify ? (
              <>
                <button
                  type="button"
                  className="rounded-md border border-emerald-500/50 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => handleDecision("APPROVED")}
                  disabled={isSubmitting}
                >
                  Valider
                </button>
                <button
                  type="button"
                  className="rounded-md border border-rose-500/50 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-100 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => handleDecision("REJECTED")}
                  disabled={isSubmitting || comment.trim().length === 0}
                >
                  Refuser
                </button>
              </>
            ) : null}
          </div>
        </div>
      }
    >
      {!session ? (
        <p className="text-sm text-slate-400">Aucune séance sélectionnée.</p>
      ) : (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/40 px-4 py-3 text-sm text-slate-200">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Collaborateur</p>
              <p className="font-semibold">{collaboratorName ?? `#${session.collaborator_id}`}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Date</p>
              <p>{new Date(session.performed_at).toLocaleString("fr-FR")}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Parcours</p>
              <p>{session.course_name || "—"}</p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">Durée (s)</p>
              <p className="text-lg font-semibold text-white">
                {formatNumber(session.duration_seconds)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">Air consommé</p>
              <p className="text-lg font-semibold text-white">
                {formatNumber(session.air_consumed_bar)} bar
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">Stress</p>
              <p className="text-lg font-semibold text-white">
                {formatNumber(session.stress_level)}
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-200">
              <p className="text-xs uppercase tracking-wide text-slate-400">Physio avant</p>
              <p>TA: {formatNumber(session.bp_sys_pre)}/{formatNumber(session.bp_dia_pre)}</p>
              <p>HR: {formatNumber(session.hr_pre)} bpm</p>
              <p>SpO2: {formatNumber(session.spo2_pre)} %</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-200">
              <p className="text-xs uppercase tracking-wide text-slate-400">Physio après</p>
              <p>TA: {formatNumber(session.bp_sys_post)}/{formatNumber(session.bp_dia_post)}</p>
              <p>HR: {formatNumber(session.hr_post)} bpm</p>
              <p>SpO2: {formatNumber(session.spo2_post)} %</p>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-200">
            <p className="text-xs uppercase tracking-wide text-slate-400">Notes</p>
            <p className="mt-1 whitespace-pre-wrap">{session.physio_notes || "—"}</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-200">
            <p className="text-xs uppercase tracking-wide text-slate-400">Observations</p>
            <p className="mt-1 whitespace-pre-wrap">{session.observations || "—"}</p>
          </div>

          {canCertify ? (
            <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Commentaire certification
              <textarea
                rows={3}
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Ajouter un commentaire pour la certification"
              />
            </label>
          ) : null}
        </div>
      )}
    </DraggableModal>
  );
}
