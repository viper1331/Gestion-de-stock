import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

import { decideAriCertification, listAriPending, listAriSessions } from "../../api/ari";
import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useFeatureFlagsStore } from "../../app/featureFlags";
import type { AriSession } from "../../types/ari";
import { DecideAriCertificationModal } from "./modals/DecideAriCertificationModal";
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

  const { data: pending = [], isLoading } = useQuery({
    queryKey: ["ari", "pending"],
    queryFn: () => listAriPending(),
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
    const items = pending.map((entry) => {
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
  }, [collaboratorMap, lastSessionByCollaborator, pending, sortMode]);

  const decideCertification = useMutation({
    mutationFn: (payload: { collaborator_id: number; status: DecisionStatus; comment?: string | null }) =>
      decideAriCertification(payload),
    onSuccess: () => {
      toast.success("Décision enregistrée.");
      queryClient.invalidateQueries({ queryKey: ["ari", "pending"] });
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour certifier.");
        return;
      }
      toast.error("Impossible d'enregistrer la décision.");
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
            Consultez les séances en attente et validez les certifications.
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
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {isLoading ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={4}>
                    Chargement des certifications...
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={4}>
                    Aucune certification en attente.
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
                      <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-200">
                        En attente
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                        onClick={() => setSelectedCollaboratorId(entry.collaborator_id)}
                      >
                        Décider
                      </button>
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
    </div>
  );
}
