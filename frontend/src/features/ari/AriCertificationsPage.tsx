import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

import {
  decideAriCertification,
  listAriCertifications,
  listAriSessions,
  resetAriCertification
} from "../../api/ari";
import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useFeatureFlagsStore } from "../../app/featureFlags";
import type { AriSession } from "../../types/ari";
import { DecideAriCertificationModal } from "./modals/DecideAriCertificationModal";
import { ResetAriCertificationModal } from "./modals/ResetAriCertificationModal";
import { canCertifyARI } from "./permissions";

interface Collaborator {
  id: number;
  full_name: string;
  department?: string | null;
}

type SortMode = "date-desc" | "date-asc" | "name-asc" | "name-desc";
type DecisionStatus = "APPROVED" | "REJECTED" | "CONDITIONAL";

const formatDate = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString("fr-FR") : "—";

const alertBadges = {
  valid: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  expiring_soon: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  expired: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  none: "border-slate-600/30 bg-slate-800/30 text-slate-300"
} as const;

export function AriCertificationsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { featureAriEnabled, isLoaded } = useFeatureFlagsStore((state) => ({
    featureAriEnabled: state.featureAriEnabled,
    isLoaded: state.isLoaded
  }));
  const canView = canCertifyARI(user);

  const [sortMode, setSortMode] = useState<SortMode>("date-desc");
  const [selectedCollaboratorId, setSelectedCollaboratorId] = useState<number | null>(null);
  const [resetCollaboratorId, setResetCollaboratorId] = useState<number | null>(null);
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (isLoaded && !featureAriEnabled) {
      navigate("/", { replace: true });
    }
  }, [featureAriEnabled, isLoaded, navigate]);

  const { data: collaborators = [] } = useQuery({
    queryKey: ["ari", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canView && featureAriEnabled
  });

  const { data: sessions = [] } = useQuery({
    queryKey: ["ari", "sessions"],
    queryFn: () => listAriSessions(),
    enabled: canView && featureAriEnabled
  });

  const { data: certifications = [], isLoading } = useQuery({
    queryKey: ["ari", "certifications"],
    queryFn: () => listAriCertifications(),
    enabled: canView && featureAriEnabled
  });

  const collaboratorMap = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator]));
  }, [collaborators]);

  const lastSessionByCollaborator = useMemo(() => {
    const map = new Map<number, AriSession>();
    sessions.forEach((session) => {
      const existing = map.get(session.collaborator_id);
      if (!existing || new Date(session.performed_at) > new Date(existing.performed_at)) {
        map.set(session.collaborator_id, session);
      }
    });
    return map;
  }, [sessions]);

  const rows = useMemo(() => {
    const items = certifications.map((entry) => {
      const collaborator = collaboratorMap.get(entry.collaborator_id);
      const lastSession = lastSessionByCollaborator.get(entry.collaborator_id);
      return { entry, collaborator, lastSession };
    });

    const sorters: Record<SortMode, (a: typeof items[0], b: typeof items[0]) => number> = {
      "date-desc": (a, b) =>
        (b.lastSession ? new Date(b.lastSession.performed_at).getTime() : 0) -
        (a.lastSession ? new Date(a.lastSession.performed_at).getTime() : 0),
      "date-asc": (a, b) =>
        (a.lastSession ? new Date(a.lastSession.performed_at).getTime() : 0) -
        (b.lastSession ? new Date(b.lastSession.performed_at).getTime() : 0),
      "name-asc": (a, b) => (a.collaborator?.full_name || "").localeCompare(b.collaborator?.full_name || ""),
      "name-desc": (a, b) => (b.collaborator?.full_name || "").localeCompare(a.collaborator?.full_name || "")
    };

    return [...items].sort(sorters[sortMode]);
  }, [certifications, collaboratorMap, lastSessionByCollaborator, sortMode]);

  const decideCertification = useMutation({
    mutationFn: (payload: { collaborator_id: number; status: DecisionStatus; comment?: string | null }) =>
      decideAriCertification(payload),
    onSuccess: () => {
      toast.success("Décision enregistrée.");
      queryClient.invalidateQueries({ queryKey: ["ari", "certifications"] });
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour certifier.");
        return;
      }
      toast.error("Impossible d'enregistrer la décision.");
    }
  });

  const resetCertification = useMutation({
    mutationFn: (payload: { collaboratorId: number; reason: string }) =>
      resetAriCertification(payload.collaboratorId, { reason: payload.reason }),
    onSuccess: () => {
      toast.success("Certification réinitialisée.");
      queryClient.invalidateQueries({ queryKey: ["ari", "certifications"] });
      queryClient.invalidateQueries({ queryKey: ["ari", "pending"] });
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour réinitialiser.");
        return;
      }
      toast.error("Impossible de réinitialiser la certification.");
    }
  });

  if (!canView) {
    return (
      <div className="p-6 text-slate-200">
        <h2 className="text-xl font-semibold">Certifications ARI</h2>
        <p className="mt-2 text-sm text-slate-400">Accès non autorisé.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Certifications ARI</h1>
          <p className="text-sm text-slate-300">
            Consultez le statut des certifications et gérez les alertes d'expiration.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-200">
          <label className="text-xs uppercase tracking-wide text-slate-400">Tri</label>
          <select
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={sortMode}
            onChange={(event) => setSortMode(event.target.value as SortMode)}
          >
            <option value="date-desc">Date desc</option>
            <option value="date-asc">Date asc</option>
            <option value="name-asc">Collaborateur A-Z</option>
            <option value="name-desc">Collaborateur Z-A</option>
          </select>
        </div>
      </header>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-900/80 text-left text-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold">Collaborateur</th>
                <th className="px-4 py-3 font-semibold">Dernière séance</th>
                <th className="px-4 py-3 font-semibold">Statut</th>
                <th className="px-4 py-3 font-semibold">Expiration</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {isLoading ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={5}>
                    Chargement des certifications...
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={5}>
                    Aucune certification disponible.
                  </td>
                </tr>
              ) : (
                rows.map(({ entry, collaborator, lastSession }) => (
                  <tr key={entry.collaborator_id} className="hover:bg-slate-900/60">
                    <td className="px-4 py-3">
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {collaborator?.full_name ?? `#${entry.collaborator_id}`}
                        </span>
                        {collaborator?.department ? (
                          <span className="text-xs text-slate-400">{collaborator.department}</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-200">{formatDate(lastSession?.performed_at)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-semibold ${
                          alertBadges[entry.alert_state ?? "none"]
                        }`}
                      >
                        {entry.alert_state === "valid" ? "Valide" : null}
                        {entry.alert_state === "expired" ? "Expirée" : null}
                        {entry.alert_state === "none" ? "Non certifié" : null}
                        {entry.alert_state === "expiring_soon" ? (
                          <>
                            Expire bientôt
                            {typeof entry.days_until_expiry === "number"
                              ? ` (J-${Math.max(entry.days_until_expiry, 0)})`
                              : null}
                          </>
                        ) : null}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-200">
                      {entry.expires_at ? formatDate(entry.expires_at) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        {canView && entry.status === "PENDING" ? (
                          <button
                            type="button"
                            className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                            onClick={() => setSelectedCollaboratorId(entry.collaborator_id)}
                          >
                            Décider
                          </button>
                        ) : null}
                        {isAdmin ? (
                          <button
                            type="button"
                            className="rounded-md border border-rose-500/50 px-3 py-1 text-xs font-semibold text-rose-200 hover:bg-rose-500/10"
                            onClick={() => setResetCollaboratorId(entry.collaborator_id)}
                          >
                            Reset
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <DecideAriCertificationModal
        open={selectedCollaboratorId !== null}
        onClose={() => setSelectedCollaboratorId(null)}
        collaboratorId={selectedCollaboratorId}
        onSubmit={async (payload) => {
          await decideCertification.mutateAsync(payload);
          setSelectedCollaboratorId(null);
        }}
      />
      <ResetAriCertificationModal
        open={resetCollaboratorId !== null}
        onClose={() => setResetCollaboratorId(null)}
        collaboratorName={
          resetCollaboratorId ? collaboratorMap.get(resetCollaboratorId)?.full_name : undefined
        }
        onSubmit={async (payload) => {
          if (!resetCollaboratorId) {
            return;
          }
          await resetCertification.mutateAsync({
            collaboratorId: resetCollaboratorId,
            reason: payload.reason
          });
          setResetCollaboratorId(null);
        }}
      />
    </div>
  );
}
