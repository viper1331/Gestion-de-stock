import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { downloadAriPdf } from "../../api/ari";
import { useAriStore } from "./store";
import type { AriCertification } from "../../types/ari";
import { CreateAriSessionModal } from "./modals/CreateAriSessionModal";
import { DecideAriCertificationModal } from "./modals/DecideAriCertificationModal";
import { AriSettingsModal } from "./modals/AriSettingsModal";

type Collaborator = {
  id: number;
  full_name: string;
  department?: string | null;
};

const SITE_OPTIONS = [
  { value: "JLL", label: "JLL" },
  { value: "GSM", label: "GSM" },
  { value: "ST_ELOIS", label: "Saint-Élois" },
  { value: "CENTRAL_ENTITY", label: "Entité centrale" }
];

const formatNumber = (value: number | null) =>
  value === null ? "-" : new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(value);

const formatDateTime = (value: string | null) => {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return date.toLocaleString("fr-FR");
};

const statusLabelMap: Record<AriCertification["status"], string> = {
  PENDING: "En attente",
  APPROVED: "Approuvée",
  REJECTED: "Refusée",
  CONDITIONAL: "Conditionnelle",
  NONE: "Non certifiée"
};

const statusClasses: Record<AriCertification["status"], string> = {
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  APPROVED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  REJECTED: "border-red-500/30 bg-red-500/10 text-red-200",
  CONDITIONAL: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  NONE: "border-slate-600/30 bg-slate-800/30 text-slate-300"
};

export function AriPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isDecisionModalOpen, setIsDecisionModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);

  const {
    ariSite,
    setAriSite,
    selectedCollaboratorId,
    setSelectedCollaboratorId,
    settings,
    sessions,
    stats,
    certification,
    isFetchingSettings,
    isFetchingSessions,
    loadSettings,
    saveSettings,
    loadSessions,
    loadStats,
    loadCertification,
    createSession,
    decideCertification
  } = useAriStore();

  const isCertificateur = user?.role === "certificateur";
  const canRead = Boolean(
    user &&
      (user.role === "admin" || user.role === "certificateur" || modulePermissions.canAccess("ari"))
  );
  const canWrite = Boolean(
    user && (user.role === "admin" || modulePermissions.canAccess("ari", "edit"))
  );
  const canCertify = Boolean(user && (user.role === "admin" || user.role === "certificateur"));
  const canAdminSettings = user?.role === "admin";

  const ariSiteHeader = useMemo(() => {
    if (!user) {
      return undefined;
    }
    if (!isCertificateur) {
      return undefined;
    }
    return ariSite ?? user.site_key ?? "JLL";
  }, [ariSite, isCertificateur, user]);

  useEffect(() => {
    if (user?.role === "certificateur" && !ariSite) {
      setAriSite(user.site_key ?? "JLL");
    }
  }, [ariSite, setAriSite, user]);

  useEffect(() => {
    if (!user || !canRead) {
      return;
    }
    if (isCertificateur && !ariSiteHeader) {
      return;
    }
    loadSettings(ariSiteHeader).catch(() => {
      toast.error("Impossible de charger les paramètres ARI.");
    });
  }, [ariSiteHeader, canRead, isCertificateur, loadSettings, user]);

  const { data: collaborators = [], isFetching: isFetchingCollaborators } = useQuery({
    queryKey: ["ari", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canRead
  });

  useEffect(() => {
    if (!selectedCollaboratorId || !canRead) {
      return;
    }
    if (isCertificateur && !ariSiteHeader) {
      return;
    }
    loadSessions(selectedCollaboratorId, ariSiteHeader).catch(() =>
      toast.error("Impossible de charger les séances ARI.")
    );
    loadStats(selectedCollaboratorId, ariSiteHeader).catch(() =>
      toast.error("Impossible de charger les stats ARI.")
    );
    loadCertification(selectedCollaboratorId, ariSiteHeader).catch(() =>
      toast.error("Impossible de charger la certification ARI.")
    );
  }, [
    ariSiteHeader,
    canRead,
    isCertificateur,
    loadCertification,
    loadSessions,
    loadStats,
    selectedCollaboratorId
  ]);

  const activeCertification = certification?.status ?? stats?.certification_status ?? "PENDING";

  const refreshAll = async () => {
    if (!selectedCollaboratorId) {
      return;
    }
    try {
      await Promise.all([
        loadSessions(selectedCollaboratorId, ariSiteHeader),
        loadStats(selectedCollaboratorId, ariSiteHeader),
        loadCertification(selectedCollaboratorId, ariSiteHeader)
      ]);
      toast.success("Données ARI actualisées.");
    } catch {
      toast.error("Impossible d'actualiser les données ARI.");
    }
  };

  if (!canRead) {
    return (
      <div className="p-6 text-slate-200">
        <h2 className="text-xl font-semibold">ARI</h2>
        <p className="mt-2 text-sm text-slate-400">Accès non autorisé.</p>
      </div>
    );
  }

  const isFeatureEnabled = settings?.feature_enabled ?? false;

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
        <div>
          <h2 className="text-xl font-semibold text-white">ARI</h2>
          <p className="text-sm text-slate-400">Suivi du parcours ARI et certifications</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isCertificateur ? (
            <select
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={ariSiteHeader ?? ""}
              onChange={(event) => setAriSite(event.target.value)}
            >
              {SITE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : null}
          <button
            type="button"
            onClick={refreshAll}
            className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
            disabled={!selectedCollaboratorId}
          >
            Rafraîchir
          </button>
          {canAdminSettings ? (
            <button
              type="button"
              onClick={() => setIsSettingsModalOpen(true)}
              className="rounded-md border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200 hover:bg-indigo-500/20"
            >
              Paramètres ARI
            </button>
          ) : null}
        </div>
      </div>

      {isFetchingSettings ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
          Chargement des paramètres ARI...
        </div>
      ) : !isFeatureEnabled ? (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
          <p>Module ARI désactivé pour ce site.</p>
          {canAdminSettings ? (
            <button
              type="button"
              onClick={() => setIsSettingsModalOpen(true)}
              className="mt-3 rounded-md bg-amber-500/20 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-amber-200 hover:bg-amber-500/30"
            >
              Activer dans les paramètres
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="grid flex-1 gap-4 lg:grid-cols-[320px,1fr]">
        <div className="flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900/60">
          <div className="border-b border-slate-800 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-200">Collaborateurs</h3>
          </div>
          <div className="flex-1 overflow-y-auto">
            {isFetchingCollaborators ? (
              <p className="px-4 py-3 text-sm text-slate-400">Chargement...</p>
            ) : collaborators.length === 0 ? (
              <p className="px-4 py-3 text-sm text-slate-400">Aucun collaborateur trouvé.</p>
            ) : (
              <ul className="divide-y divide-slate-800">
                {collaborators.map((collaborator) => {
                  const isActive = collaborator.id === selectedCollaboratorId;
                  return (
                    <li key={collaborator.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedCollaboratorId(collaborator.id)}
                        className={`flex w-full flex-col gap-1 px-4 py-3 text-left text-sm transition ${
                          isActive
                            ? "bg-slate-800/70 text-white"
                            : "text-slate-200 hover:bg-slate-800/40"
                        }`}
                      >
                        <span className="font-medium">{collaborator.full_name}</span>
                        {collaborator.department ? (
                          <span className="text-xs text-slate-400">{collaborator.department}</span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-white">Détails ARI</h3>
                <p className="text-sm text-slate-400">Suivi des séances et certification.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {selectedCollaboratorId && canWrite ? (
                  <button
                    type="button"
                    onClick={() => setIsCreateModalOpen(true)}
                    className="rounded-md bg-indigo-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
                  >
                    + Ajouter séance
                  </button>
                ) : null}
                {selectedCollaboratorId && canCertify ? (
                  <button
                    type="button"
                    onClick={() => setIsDecisionModalOpen(true)}
                    className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                  >
                    Décider
                  </button>
                ) : null}
                {selectedCollaboratorId ? (
                  <button
                    type="button"
                    onClick={async () => {
                      if (!selectedCollaboratorId) {
                        return;
                      }
                      try {
                        await downloadAriPdf(selectedCollaboratorId, ariSiteHeader);
                        toast.success("Export PDF généré.");
                      } catch {
                        toast.error("Impossible d'exporter le PDF.");
                      }
                    }}
                    className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
                  >
                    Exporter PDF
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          {!selectedCollaboratorId ? (
            <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-400">
              Sélectionnez un collaborateur pour afficher son suivi ARI.
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-4">
                <span
                  className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${statusClasses[activeCertification]}`}
                >
                  {statusLabelMap[activeCertification]}
                </span>
                {certification?.decision_at ? (
                  <span className="text-xs text-slate-400">
                    Décision : {formatDateTime(certification.decision_at)}
                  </span>
                ) : null}
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Séances</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {stats?.sessions_count ?? 0}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Durée moyenne (s)</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {formatNumber(stats?.avg_duration_seconds ?? null)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Air/min moyen</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {formatNumber(stats?.avg_air_per_min ?? null)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Air consommé (bar)</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {formatNumber(stats?.avg_air_consumed_bar ?? null)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Stress moyen</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {formatNumber(stats?.avg_stress_level ?? null)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase tracking-wide text-slate-400">Dernière séance</p>
                  <p className="mt-2 text-base font-semibold text-white">
                    {formatDateTime(stats?.last_session_at ?? null)}
                  </p>
                </div>
              </div>

              <div className="flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900/60">
                <div className="border-b border-slate-800 px-4 py-3">
                  <h4 className="text-sm font-semibold text-slate-200">Historique des séances</h4>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-800 text-sm">
                    <thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-4 py-2 text-left">Date</th>
                        <th className="px-4 py-2 text-left">Parcours</th>
                        <th className="px-4 py-2 text-left">Durée (s)</th>
                        <th className="px-4 py-2 text-left">Air (bar)</th>
                        <th className="px-4 py-2 text-left">Stress</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 bg-slate-900">
                      {isFetchingSessions ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-3 text-sm text-slate-400">
                            Chargement...
                          </td>
                        </tr>
                      ) : sessions.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-3 text-sm text-slate-400">
                            Aucune séance enregistrée.
                          </td>
                        </tr>
                      ) : (
                        sessions.map((session) => (
                          <tr key={session.id} className="text-slate-200">
                            <td className="px-4 py-2">{formatDateTime(session.performed_at)}</td>
                            <td className="px-4 py-2">{session.course_name}</td>
                            <td className="px-4 py-2">{session.duration_seconds}</td>
                            <td className="px-4 py-2">{session.air_consumed_bar}</td>
                            <td className="px-4 py-2">{session.stress_level}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <CreateAriSessionModal
        open={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        collaboratorId={selectedCollaboratorId}
        settings={settings}
        collaborators={collaborators}
        onSubmit={async (payload) => {
          try {
            const session = await createSession(payload, ariSiteHeader);
            toast.success("Séance ajoutée.");
            if (selectedCollaboratorId) {
              await Promise.all([
                loadStats(selectedCollaboratorId, ariSiteHeader),
                loadCertification(selectedCollaboratorId, ariSiteHeader)
              ]);
            }
            return session;
          } catch {
            toast.error("Impossible de créer la séance.");
            throw new Error("Création impossible");
          }
        }}
      />

      <DecideAriCertificationModal
        open={isDecisionModalOpen}
        onClose={() => setIsDecisionModalOpen(false)}
        collaboratorId={selectedCollaboratorId}
        onSubmit={async (payload) => {
          try {
            await decideCertification(payload, ariSiteHeader);
            toast.success("Décision enregistrée.");
            if (selectedCollaboratorId) {
              await loadStats(selectedCollaboratorId, ariSiteHeader);
            }
          } catch {
            toast.error("Impossible d'enregistrer la décision.");
          }
        }}
      />

      <AriSettingsModal
        open={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
        settings={settings}
        onSubmit={async (payload) => {
          try {
            await saveSettings(payload, ariSiteHeader);
            toast.success("Paramètres ARI mis à jour.");
          } catch {
            toast.error("Impossible d'enregistrer les paramètres.");
          }
        }}
      />
    </div>
  );
}
