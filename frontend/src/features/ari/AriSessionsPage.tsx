import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { toast } from "sonner";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  createAriSession,
  decideAriCertification,
  getAriCertification,
  listAriPending,
  listAriSessions,
  updateAriSession
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
  getSessionStatus,
  sortAriSessions,
  type AriSessionStatus,
  type AriSessionsSort,
  type AriSessionsSortKey
} from "./utils/ariSessionsFilter";
import { formatAir, formatMinutes, getAirPerMinute, getDurationMinutes, statusBadgeClasses } from "./utils/ariSessionDisplay";

interface Collaborator {
  id: number;
  full_name: string;
  department?: string | null;
}

export function AriSessionsPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
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
  const [editingSession, setEditingSession] = useState<AriSession | null>(null);
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

  const availableCollaborators = useMemo(() => {
    if (!collaborators.length || !sessions.length) {
      return [];
    }
    const activeIds = new Set(sessions.map((session) => session.collaborator_id));
    return collaborators.filter((collaborator) => activeIds.has(collaborator.id));
  }, [collaborators, sessions]);

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

  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    if (!sessionId) {
      return;
    }
    const parsed = Number(sessionId);
    if (!Number.isFinite(parsed)) {
      return;
    }
    const session = sessions.find((entry) => entry.id === parsed);
    if (session) {
      setSelectedSession(session);
    }
  }, [searchParams, sessions]);

  const createSession = useMutation({
    mutationFn: (payload: Parameters<typeof createAriSession>[0]) => createAriSession(payload),
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

  const updateSession = useMutation({
    mutationFn: async (payload: { sessionId: number; data: Parameters<typeof updateAriSession>[1] }) =>
      updateAriSession(payload.sessionId, payload.data),
    onSuccess: () => {
      toast.success("Séance ARI mise à jour.");
      queryClient.invalidateQueries({ queryKey: ["ari", "sessions"] });
      setEditingSession(null);
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 403) {
        toast.error("Vous n'avez pas les droits pour modifier une séance ARI.");
        return;
      }
      toast.error("Impossible de modifier la séance.");
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
        availableCollaborators={availableCollaborators}
        availableCourses={availableCourses}
        availableStatuses={availableStatuses}
        totalCount={sessions.length}
        filteredCount={filteredSessions.length}
        disabled={isLoadingSessions || isLoadingCollaborators || sessions.length === 0}
      />

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed divide-y divide-slate-800 text-sm">
            <colgroup>
              <col className="w-40" />
              <col className="w-56" />
              <col className="w-44" />
              <col className="w-28" />
              <col className="w-56" />
              <col className="w-36" />
              <col className="w-36" />
            </colgroup>
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
                    Air (L/min)
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
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-2">
                          <span>{formatAir(getAirPerMinute(session))}</span>
                          <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-200">
                            <p className="font-semibold text-white">
                              {session.air_consumption_lpm > 0
                                ? `${session.air_consumption_lpm.toFixed(1)} L/min`
                                : "Non renseigné"}
                            </p>
                            <p className="text-slate-400">
                              Air consommé :{" "}
                              {session.air_consumed_l > 0
                                ? `${session.air_consumed_l.toFixed(1)} L`
                                : "—"}
                            </p>
                            <p className="text-slate-400">
                              Autonomie :{" "}
                              {session.autonomy_start_min > 0 && session.autonomy_end_min >= 0
                                ? `${session.autonomy_start_min.toFixed(1)} / ${session.autonomy_end_min.toFixed(1)} min`
                                : "—"}
                            </p>
                          </div>
                        </div>
                      </td>
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
                        <div className="flex justify-end gap-2">
                          {canEdit ? (
                            <button
                              type="button"
                              className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                              onClick={() => setEditingSession(session)}
                            >
                              Modifier
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                            onClick={() => setSelectedSession(session)}
                          >
                            Ouvrir
                          </button>
                        </div>
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

      <CreateAriSessionModal
        open={Boolean(editingSession)}
        onClose={() => setEditingSession(null)}
        collaboratorId={editingSession?.collaborator_id ?? null}
        settings={null}
        collaborators={collaborators}
        session={editingSession}
        onSubmit={(payload) => {
          if (!editingSession) {
            return Promise.reject(new Error("Session manquante"));
          }
          return updateSession.mutateAsync({ sessionId: editingSession.id, data: payload });
        }}
      />

      <SessionDetailModal
        open={Boolean(selectedSession)}
        onClose={() => {
          setSelectedSession(null);
          if (searchParams.get("session_id")) {
            const next = new URLSearchParams(searchParams);
            next.delete("session_id");
            setSearchParams(next, { replace: true });
          }
        }}
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
