import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

import {
  createAriSession,
  decideAriCertification,
  getAriCertification,
  listAriPending,
  listAriSessions
} from "../../api/ari";
import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useFeatureFlagsStore } from "../../app/featureFlags";
import type { AriSession } from "../../types/ari";
import { CreateAriSessionModal } from "./modals/CreateAriSessionModal";
import { SessionDetailModal } from "./modals/SessionDetailModal";
import { canCertifyARI } from "./permissions";
import { AriSessionsFilters } from "./components/AriSessionsFilters";
import {
  applyAriSessionsFilters,
  ariSessionStatusLabels,
  createEmptyAriSessionsFilters,
  getAirPerMinute,
  getDurationMinutes,
  getSessionStatus,
  sortAriSessions,
  type AriSessionStatus,
  type AriSessionsSort,
  type AriSessionsSortKey
} from "./utils/ariSessionsFilter";

interface Collaborator {
  id: number;
  full_name: string;
  department?: string | null;
}

const statusBadgeClasses = {
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  CERTIFIED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  REJECTED: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  COMPLETED: "border-slate-600/40 bg-slate-800/40 text-slate-200",
  DRAFT: "border-slate-700/40 bg-slate-800/30 text-slate-300"
};

const formatMinutes = (value: number | null) => {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(1)} min`;
};

const formatAir = (value: number | null) => {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(1)} L/min`;
};

export function AriSessionsPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { featureAriEnabled, isLoaded } = useFeatureFlagsStore((state) => ({
    featureAriEnabled: state.featureAriEnabled,
    isLoaded: state.isLoaded
  }));

  const canView = Boolean(
    user && (user.role === "admin" || user.role === "certificateur" || modulePermissions.canAccess("ari"))
  );
  const canEdit = Boolean(user && (user.role === "admin" || modulePermissions.canAccess("ari", "edit")));
  const canCertify = canCertifyARI(user);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedSession, setSelectedSession] = useState<AriSession | null>(null);
  const [filters, setFilters] = useState(() => createEmptyAriSessionsFilters());
  const [sort, setSort] = useState<AriSessionsSort>(null);

  useEffect(() => {
    if (isLoaded && !featureAriEnabled) {
      navigate("/", { replace: true });
    }
  }, [featureAriEnabled, isLoaded, navigate]);

  const { data: collaborators = [], isLoading: isLoadingCollaborators } = useQuery({
    queryKey: ["ari", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canView && featureAriEnabled
  });

  const { data: sessions = [], isLoading: isLoadingSessions } = useQuery({
    queryKey: ["ari", "sessions"],
    queryFn: () => listAriSessions(),
    enabled: canView && featureAriEnabled
  });

  const { data: pendingCertifications = [] } = useQuery({
    queryKey: ["ari", "pending"],
    queryFn: () => listAriPending(),
    enabled: canCertify && featureAriEnabled
  });

  const pendingByCollaborator = useMemo(() => {
    return new Set(pendingCertifications.map((entry) => entry.collaborator_id));
  }, [pendingCertifications]);

  const collaboratorMap = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator]));
  }, [collaborators]);

  const availableCourses = useMemo(() => {
    const uniqueCourses = new Set<string>();
    sessions.forEach((session) => {
      if (session.course_name) {
        uniqueCourses.add(session.course_name);
      }
    });
    return Array.from(uniqueCourses).sort((a, b) => a.localeCompare(b, "fr", { sensitivity: "base" }));
  }, [sessions]);

  const availableStatuses = useMemo(() => {
    const statuses = new Set<AriSessionStatus>();
    sessions.forEach((session) => {
      statuses.add(getSessionStatus(session, pendingByCollaborator));
    });
    return Array.from(statuses).sort();
  }, [pendingByCollaborator, sessions]);

  const selectedCollaborator = selectedSession
    ? collaboratorMap.get(selectedSession.collaborator_id)
    : undefined;

  const { data: selectedCertification = null } = useQuery({
    queryKey: ["ari", "certification", selectedSession?.collaborator_id],
    queryFn: () =>
      selectedSession ? getAriCertification(selectedSession.collaborator_id) : Promise.resolve(null),
    enabled: Boolean(selectedSession && canCertify)
  });

  const createSession = useMutation({
    mutationFn: createAriSession,
    onSuccess: () => {
      toast.success("Séance ARI créée.");
      queryClient.invalidateQueries({ queryKey: ["ari", "sessions"] });
      queryClient.invalidateQueries({ queryKey: ["ari", "pending"] });
      setIsCreateModalOpen(false);
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour créer une séance ARI.");
        return;
      }
      toast.error("Impossible de créer la séance.");
    }
  });

  const decideCertification = useMutation({
    mutationFn: async (payload: { collaborator_id: number; status: "APPROVED" | "REJECTED"; comment?: string | null }) => {
      const result = await decideAriCertification(payload);
      return result;
    },
    onSuccess: () => {
      toast.success("Décision enregistrée.");
      queryClient.invalidateQueries({ queryKey: ["ari", "pending"] });
      queryClient.invalidateQueries({ queryKey: ["ari", "certification"] });
      queryClient.invalidateQueries({ queryKey: ["ari", "sessions"] });
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour certifier cette séance.");
        return;
      }
      toast.error("Impossible d'enregistrer la décision.");
    }
  });

  const filteredSessions = useMemo(
    () => applyAriSessionsFilters(sessions, filters, collaboratorMap, pendingByCollaborator),
    [collaboratorMap, filters, pendingByCollaborator, sessions]
  );

  const sortedSessions = useMemo(
    () => sortAriSessions(filteredSessions, sort, collaboratorMap, pendingByCollaborator),
    [collaboratorMap, filteredSessions, pendingByCollaborator, sort]
  );

  const handleSort = (key: AriSessionsSortKey) => {
    setSort((current) => {
      if (!current || current.key !== key) {
        return { key, direction: "asc" };
      }
      return { key, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  };

  const renderSortIndicator = (key: AriSessionsSortKey) => {
    if (!sort || sort.key !== key) {
      return null;
    }
    return (
      <span aria-hidden className="text-xs text-slate-400">
        {sort.direction === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  if (!canView) {
    return (
      <div className="p-6 text-slate-200">
        <h2 className="text-xl font-semibold">Sessions ARI</h2>
        <p className="mt-2 text-sm text-slate-400">Accès non autorisé.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Sessions ARI</h1>
          <p className="text-sm text-slate-300">
            Créez, consultez et certifiez les séances ARI depuis cette liste.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => setIsCreateModalOpen(true)}
          disabled={!canEdit}
        >
          Créer une séance ARI
        </button>
      </header>

      <AriSessionsFilters
        filters={filters}
        onChange={setFilters}
        onReset={() => setFilters(createEmptyAriSessionsFilters())}
        availableCourses={availableCourses}
        availableStatuses={availableStatuses}
        totalCount={sessions.length}
        filteredCount={filteredSessions.length}
        disabled={isLoadingSessions || isLoadingCollaborators || sessions.length === 0}
      />

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-900/80 text-left text-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("date")}
                  >
                    Date
                    {renderSortIndicator("date")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("collaborator")}
                  >
                    Collaborateur
                    {renderSortIndicator("collaborator")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("course")}
                  >
                    Parcours
                    {renderSortIndicator("course")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("duration")}
                  >
                    Durée
                    {renderSortIndicator("duration")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("air")}
                  >
                    Air
                    {renderSortIndicator("air")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleSort("status")}
                  >
                    Statut
                    {renderSortIndicator("status")}
                  </button>
                </th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {isLoadingSessions || isLoadingCollaborators ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={7}>
                    Chargement des séances...
                  </td>
                </tr>
              ) : sessions.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={7}>
                    Aucune séance enregistrée.
                  </td>
                </tr>
              ) : filteredSessions.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={7}>
                    Aucun résultat pour ces filtres.
                  </td>
                </tr>
              ) : (
                sortedSessions.map((session) => {
                  const collaborator = collaboratorMap.get(session.collaborator_id);
                  const sessionStatus = getSessionStatus(session, pendingByCollaborator);
                  const statusLabel = ariSessionStatusLabels[sessionStatus];
                  return (
                    <tr key={session.id} className="hover:bg-slate-900/60">
                      <td className="px-4 py-3">
                        {new Date(session.performed_at).toLocaleString("fr-FR")}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col">
                          <span className="font-medium">
                            {collaborator?.full_name ?? `#${session.collaborator_id}`}
                          </span>
                          {collaborator?.department ? (
                            <span className="text-xs text-slate-400">{collaborator.department}</span>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-4 py-3">{session.course_name || "—"}</td>
                      <td className="px-4 py-3">{formatMinutes(getDurationMinutes(session))}</td>
                      <td className="px-4 py-3">{formatAir(getAirPerMinute(session))}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-semibold ${
                            statusBadgeClasses[sessionStatus]
                          }`}
                        >
                          {statusLabel}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                          onClick={() => setSelectedSession(session)}
                        >
                          Ouvrir
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <CreateAriSessionModal
        open={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        collaboratorId={null}
        settings={null}
        collaborators={collaborators}
        onSubmit={(payload) => createSession.mutateAsync(payload)}
      />

      <SessionDetailModal
        open={Boolean(selectedSession)}
        onClose={() => setSelectedSession(null)}
        session={selectedSession}
        collaboratorName={selectedCollaborator?.full_name}
        certification={selectedCertification}
        canCertify={canCertify}
        onDecide={async ({ status, comment }) => {
          if (!selectedSession) {
            return;
          }
          await decideCertification.mutateAsync({
            collaborator_id: selectedSession.collaborator_id,
            status,
            comment
          });
          setSelectedSession(null);
        }}
      />
    </div>
  );
}
