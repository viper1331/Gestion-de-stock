import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { getAriStatsByCollaborator, getAriStatsOverview, listAriPending, listAriSessions } from "../../api/ari";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useFeatureFlagsStore } from "../../app/featureFlags";
import { AriSessionsFilters } from "./components/AriSessionsFilters";
import { canCertifyARI } from "./permissions";
import {
  applyAriSessionsFilters,
  ariSessionStatusLabels,
  createEmptyAriSessionsFilters,
  getSessionStatus,
  sortAriSessions,
  type AriSessionsSort,
  type AriSessionStatus,
  type AriSessionsSortKey
} from "./utils/ariSessionsFilter";
import { formatAir, formatMinutes, getAirPerMinute, getDurationMinutes, statusBadgeClasses } from "./utils/ariSessionDisplay";

type PeriodPreset = "7d" | "30d" | "90d" | "year" | "custom";

type CollaboratorSortKey =
  | "collaborator"
  | "sessions"
  | "duration"
  | "avgAir"
  | "maxAir"
  | "lastSession"
  | "status";

type CollaboratorSort = {
  key: CollaboratorSortKey;
  direction: "asc" | "desc";
};

const formatDateInputValue = (value: Date) => value.toISOString().slice(0, 10);

const getPresetRange = (preset: PeriodPreset) => {
  const today = new Date();
  const end = formatDateInputValue(today);
  const start = new Date(today);

  switch (preset) {
    case "7d":
      start.setDate(today.getDate() - 6);
      break;
    case "30d":
      start.setDate(today.getDate() - 29);
      break;
    case "90d":
      start.setDate(today.getDate() - 89);
      break;
    case "year":
      start.setMonth(0, 1);
      break;
    case "custom":
    default:
      return { from: "", to: "" };
  }
  return { from: formatDateInputValue(start), to: end };
};

const formatStatValue = (value: number | null, fallback = "—") => {
  if (value === null || Number.isNaN(value)) {
    return fallback;
  }
  return value.toFixed(1);
};

function StatCard(props: {
  title: string;
  value: string;
  subtitle: string;
  variant: "info" | "success" | "warning" | "danger";
}) {
  return (
    <article className="stat-card p-4" data-variant={props.variant}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400">{props.title}</p>
          <p className="mt-1 text-2xl font-semibold text-white">{props.value}</p>
        </div>
        <div className="stat-glow h-8 w-8 rounded-full bg-white/10" aria-hidden />
      </div>
      <p className="mt-2 text-xs text-slate-400">{props.subtitle}</p>
    </article>
  );
}

export function AriStatsPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const { featureAriEnabled, isLoaded } = useFeatureFlagsStore((state) => ({
    featureAriEnabled: state.featureAriEnabled,
    isLoaded: state.isLoaded
  }));
  const canView = Boolean(
    user && (user.role === "admin" || user.role === "certificateur" || modulePermissions.canAccess("ari"))
  );
  const canCertify = canCertifyARI(user);

  const [period, setPeriod] = useState<PeriodPreset>("30d");
  const initialRange = useMemo(() => getPresetRange("30d"), []);
  const [dateFrom, setDateFrom] = useState(initialRange.from);
  const [dateTo, setDateTo] = useState(initialRange.to);

  const [collaboratorQuery, setCollaboratorQuery] = useState("");
  const [collaboratorSort, setCollaboratorSort] = useState<CollaboratorSort>({
    key: "collaborator",
    direction: "asc"
  });
  const [selectedCollaboratorId, setSelectedCollaboratorId] = useState<number | null>(null);

  const [sessionFilters, setSessionFilters] = useState(() => createEmptyAriSessionsFilters());
  const [sessionSort, setSessionSort] = useState<AriSessionsSort>(null);

  useEffect(() => {
    if (isLoaded && !featureAriEnabled) {
      navigate("/", { replace: true });
    }
  }, [featureAriEnabled, isLoaded, navigate]);

  useEffect(() => {
    if (period === "custom") {
      return;
    }
    const next = getPresetRange(period);
    setDateFrom(next.from);
    setDateTo(next.to);
  }, [period]);

  useEffect(() => {
    if (!selectedCollaboratorId) {
      return;
    }
    setSessionFilters({
      ...createEmptyAriSessionsFilters(),
      dateFrom,
      dateTo,
      collaboratorId: String(selectedCollaboratorId)
    });
    setSessionSort(null);
  }, [dateFrom, dateTo, selectedCollaboratorId]);

  const { data: overview, isLoading: isLoadingOverview } = useQuery({
    queryKey: ["ari", "stats", "overview", dateFrom, dateTo],
    queryFn: () => getAriStatsOverview({ from: dateFrom || undefined, to: dateTo || undefined }),
    enabled: canView && featureAriEnabled
  });

  const { data: collaboratorStats, isLoading: isLoadingCollaboratorStats } = useQuery({
    queryKey: ["ari", "stats", "by-collaborator", dateFrom, dateTo],
    queryFn: () => getAriStatsByCollaborator({ from: dateFrom || undefined, to: dateTo || undefined }),
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

  const collaboratorRows = useMemo(() => collaboratorStats?.rows ?? [], [collaboratorStats]);

  const collaboratorMap = useMemo(() => {
    return new Map(collaboratorRows.map((row) => [row.collaborator_id, { full_name: row.collaborator_name }]));
  }, [collaboratorRows]);

  const filteredCollaborators = useMemo(() => {
    const query = collaboratorQuery.trim().toLowerCase();
    if (!query) {
      return collaboratorRows;
    }
    return collaboratorRows.filter((row) => row.collaborator_name.toLowerCase().includes(query));
  }, [collaboratorQuery, collaboratorRows]);

  const sortedCollaborators = useMemo(() => {
    const rows = [...filteredCollaborators];
    const multiplier = collaboratorSort.direction === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      switch (collaboratorSort.key) {
        case "collaborator":
          return (
            a.collaborator_name.localeCompare(b.collaborator_name, "fr", { sensitivity: "base" }) * multiplier
          );
        case "sessions":
          return (a.sessions_count - b.sessions_count) * multiplier;
        case "duration":
          return ((a.avg_duration_min ?? 0) - (b.avg_duration_min ?? 0)) * multiplier;
        case "avgAir":
          return ((a.avg_air_lpm ?? 0) - (b.avg_air_lpm ?? 0)) * multiplier;
        case "maxAir":
          return ((a.max_air_lpm ?? 0) - (b.max_air_lpm ?? 0)) * multiplier;
        case "lastSession":
          return (
            (new Date(a.last_session_at ?? 0).getTime() - new Date(b.last_session_at ?? 0).getTime()) *
            multiplier
          );
        case "status":
          return a.status.localeCompare(b.status) * multiplier;
        default:
          return 0;
      }
    });
    return rows;
  }, [collaboratorSort, filteredCollaborators]);

  const selectedCollaborator = useMemo(() => {
    if (!selectedCollaboratorId) {
      return null;
    }
    return collaboratorRows.find((row) => row.collaborator_id === selectedCollaboratorId) ?? null;
  }, [collaboratorRows, selectedCollaboratorId]);

  const { data: collaboratorSessions = [], isLoading: isLoadingSessions } = useQuery({
    queryKey: ["ari", "stats", "sessions", selectedCollaboratorId],
    queryFn: () => (selectedCollaboratorId ? listAriSessions(selectedCollaboratorId) : Promise.resolve([])),
    enabled: Boolean(selectedCollaboratorId && canView && featureAriEnabled)
  });

  const availableCourses = useMemo(() => {
    const uniqueCourses = new Set<string>();
    collaboratorSessions.forEach((session) => {
      if (session.course_name) {
        uniqueCourses.add(session.course_name);
      }
    });
    return Array.from(uniqueCourses).sort((a, b) => a.localeCompare(b, "fr", { sensitivity: "base" }));
  }, [collaboratorSessions]);

  const availableStatuses = useMemo(() => {
    return Object.keys(ariSessionStatusLabels) as AriSessionStatus[];
  }, []);

  const filteredSessions = useMemo(
    () => applyAriSessionsFilters(collaboratorSessions, sessionFilters, collaboratorMap, pendingByCollaborator),
    [collaboratorSessions, collaboratorMap, pendingByCollaborator, sessionFilters]
  );

  const sortedSessions = useMemo(
    () => sortAriSessions(filteredSessions, sessionSort, collaboratorMap, pendingByCollaborator),
    [collaboratorMap, filteredSessions, pendingByCollaborator, sessionSort]
  );

  const handleSessionSort = (key: AriSessionsSortKey) => {
    setSessionSort((current) => {
      if (!current || current.key !== key) {
        return { key, direction: "asc" };
      }
      return { key, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  };

  const renderSessionSortIndicator = (key: AriSessionsSortKey) => {
    if (!sessionSort || sessionSort.key !== key) {
      return null;
    }
    return (
      <span aria-hidden className="text-xs text-slate-400">
        {sessionSort.direction === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  const handleCollaboratorSort = (key: CollaboratorSortKey) => {
    setCollaboratorSort((current) => {
      if (!current || current.key !== key) {
        return { key, direction: "asc" };
      }
      return { key, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  };

  const renderCollaboratorSortIndicator = (key: CollaboratorSortKey) => {
    if (!collaboratorSort || collaboratorSort.key !== key) {
      return null;
    }
    return (
      <span aria-hidden className="text-xs text-slate-400">
        {collaboratorSort.direction === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  if (!canView) {
    return (
      <div className="p-6 text-slate-200">
        <h2 className="text-xl font-semibold">Statistiques ARI</h2>
        <p className="mt-2 text-sm text-slate-400">Accès non autorisé.</p>
      </div>
    );
  }

  const totalSessions = overview?.total_sessions ?? 0;
  const validatedCount = overview?.validated_count ?? 0;
  const rejectedCount = overview?.rejected_count ?? 0;
  const pendingCount = overview?.pending_count ?? 0;
  const validationRate = totalSessions
    ? `${Math.round((validatedCount / totalSessions) * 100)}%`
    : "—";

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Statistiques ARI</h1>
          <p className="text-sm text-slate-300">Suivez l'activité ARI et la certification par collaborateur.</p>
        </div>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-200">Période</h2>
            <p className="text-xs text-slate-400">Sélectionnez la période analysée.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={period}
              onChange={(event) => setPeriod(event.target.value as PeriodPreset)}
            >
              <option value="7d">7 jours</option>
              <option value="30d">30 jours</option>
              <option value="90d">90 jours</option>
              <option value="year">Année</option>
              <option value="custom">Personnalisé</option>
            </select>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Du
              <input
                type="date"
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-100"
                value={dateFrom}
                onChange={(event) => {
                  setDateFrom(event.target.value);
                  setPeriod("custom");
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Au
              <input
                type="date"
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-100"
                value={dateTo}
                onChange={(event) => {
                  setDateTo(event.target.value);
                  setPeriod("custom");
                }}
              />
            </label>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard
          title="Sessions"
          value={isLoadingOverview ? "…" : String(totalSessions)}
          subtitle="Total sur la période"
          variant="info"
        />
        <StatCard
          title="Collaborateurs"
          value={isLoadingOverview ? "…" : String(overview?.distinct_collaborators ?? 0)}
          subtitle="Avec au moins 1 séance"
          variant="success"
        />
        <StatCard
          title="Durée moyenne"
          value={isLoadingOverview ? "…" : `${formatStatValue(overview?.avg_duration_min ?? null)} min`}
          subtitle="Durée moyenne par séance"
          variant="warning"
        />
        <StatCard
          title="Air moyen"
          value={isLoadingOverview ? "…" : `${formatStatValue(overview?.avg_air_lpm ?? null)} L/min`}
          subtitle="Consommation moyenne"
          variant="warning"
        />
        <StatCard
          title="Validation"
          value={isLoadingOverview ? "…" : validationRate}
          subtitle={`${validatedCount} validées • ${rejectedCount + pendingCount} non validées`}
          variant="danger"
        />
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-200">
              Top 5 consommations élevées
            </h2>
            <p className="text-xs text-slate-400">Séances avec la consommation d'air la plus élevée.</p>
          </div>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full table-fixed divide-y divide-slate-800 text-sm">
            <colgroup>
              <col className="w-40" />
              <col className="w-56" />
              <col className="w-32" />
              <col className="w-32" />
              <col className="w-32" />
            </colgroup>
            <thead className="text-left text-slate-200">
              <tr>
                <th className="px-3 py-2 font-semibold">Date</th>
                <th className="px-3 py-2 font-semibold">Collaborateur</th>
                <th className="px-3 py-2 font-semibold">Air</th>
                <th className="px-3 py-2 font-semibold">Durée</th>
                <th className="px-3 py-2 font-semibold text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {(overview?.top_sessions_by_air ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-3 text-slate-400" colSpan={5}>
                    Aucune séance sur la période.
                  </td>
                </tr>
              ) : (
                overview?.top_sessions_by_air.map((session) => (
                  <tr key={session.session_id} className="hover:bg-slate-900/60">
                    <td className="px-3 py-2">
                      {new Date(session.performed_at).toLocaleDateString("fr-FR")}
                    </td>
                    <td className="px-3 py-2">{session.collaborator_name}</td>
                    <td className="px-3 py-2">{formatAir(session.air_lpm)}</td>
                    <td className="px-3 py-2">{formatMinutes(session.duration_min)}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                        onClick={() => navigate(`/ari/sessions?session_id=${session.session_id}`)}
                      >
                        Ouvrir
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-200">
              Vue par collaborateur
            </h2>
            <p className="text-xs text-slate-400">
              {filteredCollaborators.length} collaborateur{filteredCollaborators.length > 1 ? "s" : ""} •{" "}
              {collaboratorRows.length} au total
            </p>
          </div>
          <input
            type="text"
            placeholder="Rechercher un collaborateur..."
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 md:w-64"
            value={collaboratorQuery}
            onChange={(event) => setCollaboratorQuery(event.target.value)}
          />
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full table-fixed divide-y divide-slate-800 text-sm">
            <colgroup>
              <col className="w-56" />
              <col className="w-24" />
              <col className="w-32" />
              <col className="w-32" />
              <col className="w-32" />
              <col className="w-40" />
              <col className="w-32" />
            </colgroup>
            <thead className="text-left text-slate-200">
              <tr>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("collaborator")}
                  >
                    Collaborateur
                    {renderCollaboratorSortIndicator("collaborator")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("sessions")}
                  >
                    Sessions
                    {renderCollaboratorSortIndicator("sessions")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("duration")}
                  >
                    Durée moy.
                    {renderCollaboratorSortIndicator("duration")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("avgAir")}
                  >
                    Air moy.
                    {renderCollaboratorSortIndicator("avgAir")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("maxAir")}
                  >
                    Air max
                    {renderCollaboratorSortIndicator("maxAir")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("lastSession")}
                  >
                    Dernière session
                    {renderCollaboratorSortIndicator("lastSession")}
                  </button>
                </th>
                <th className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2"
                    onClick={() => handleCollaboratorSort("status")}
                  >
                    Statut
                    {renderCollaboratorSortIndicator("status")}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {isLoadingCollaboratorStats ? (
                <tr>
                  <td className="px-3 py-3 text-slate-400" colSpan={7}>
                    Chargement des statistiques...
                  </td>
                </tr>
              ) : sortedCollaborators.length === 0 ? (
                <tr>
                  <td className="px-3 py-3 text-slate-400" colSpan={7}>
                    Aucun collaborateur pour cette période.
                  </td>
                </tr>
              ) : (
                sortedCollaborators.map((row) => (
                  <tr
                    key={row.collaborator_id}
                    className={`cursor-pointer hover:bg-slate-900/60 ${
                      row.collaborator_id === selectedCollaboratorId ? "bg-slate-900/70" : ""
                    }`}
                    onClick={() => setSelectedCollaboratorId(row.collaborator_id)}
                  >
                    <td className="px-3 py-2 font-medium">{row.collaborator_name}</td>
                    <td className="px-3 py-2">{row.sessions_count}</td>
                    <td className="px-3 py-2">{formatMinutes(row.avg_duration_min)}</td>
                    <td className="px-3 py-2">{formatAir(row.avg_air_lpm)}</td>
                    <td className="px-3 py-2">{formatAir(row.max_air_lpm)}</td>
                    <td className="px-3 py-2">
                      {row.last_session_at ? new Date(row.last_session_at).toLocaleDateString("fr-FR") : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center rounded-full border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-200">
                        {row.status === "certified"
                          ? "Certifié"
                          : row.status === "mixed"
                            ? "À certifier"
                            : "En attente"}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {selectedCollaborator ? (
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-200">
                Séances de {selectedCollaborator.collaborator_name}
              </h2>
              <p className="text-xs text-slate-400">
                {filteredSessions.length} séance{filteredSessions.length > 1 ? "s" : ""} sur la période.
              </p>
            </div>
          </div>

          <div className="mt-4">
            <AriSessionsFilters
              filters={sessionFilters}
              onChange={setSessionFilters}
              onReset={() =>
                setSessionFilters({
                  ...createEmptyAriSessionsFilters(),
                  dateFrom,
                  dateTo,
                  collaboratorId: String(selectedCollaborator.collaborator_id)
                })
              }
              availableCollaborators={collaboratorRows.map((row) => ({
                id: row.collaborator_id,
                full_name: row.collaborator_name
              }))}
              availableCourses={availableCourses}
              availableStatuses={availableStatuses}
              totalCount={collaboratorSessions.length}
              filteredCount={filteredSessions.length}
              disabled={isLoadingSessions || collaboratorSessions.length === 0}
            />
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full table-fixed divide-y divide-slate-800 text-sm">
              <colgroup>
                <col className="w-40" />
                <col className="w-56" />
                <col className="w-44" />
                <col className="w-28" />
                <col className="w-56" />
                <col className="w-36" />
                <col className="w-28" />
              </colgroup>
              <thead className="bg-slate-900/80 text-left text-slate-200">
                <tr>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("date")}
                    >
                      Date
                      {renderSessionSortIndicator("date")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("collaborator")}
                    >
                      Collaborateur
                      {renderSessionSortIndicator("collaborator")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("course")}
                    >
                      Parcours
                      {renderSessionSortIndicator("course")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("duration")}
                    >
                      Durée
                      {renderSessionSortIndicator("duration")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("air")}
                    >
                      Air (L/min)
                      {renderSessionSortIndicator("air")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2"
                      onClick={() => handleSessionSort("status")}
                    >
                      Statut
                      {renderSessionSortIndicator("status")}
                    </button>
                  </th>
                  <th className="px-4 py-3 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-100">
                {isLoadingSessions ? (
                  <tr>
                    <td className="px-4 py-3 text-slate-400" colSpan={7}>
                      Chargement des séances...
                    </td>
                  </tr>
                ) : collaboratorSessions.length === 0 ? (
                  <tr>
                    <td className="px-4 py-3 text-slate-400" colSpan={7}>
                      Aucune séance enregistrée.
                    </td>
                  </tr>
                ) : filteredSessions.length === 0 ? (
                  <tr>
                    <td className="px-4 py-3 text-slate-400" colSpan={7}>
                      Aucun résultat pour ces filtres.
                    </td>
                  </tr>
                ) : (
                  sortedSessions.map((session) => {
                    const collaboratorName =
                      collaboratorMap.get(session.collaborator_id)?.full_name ?? `#${session.collaborator_id}`;
                    const sessionStatus = getSessionStatus(session, pendingByCollaborator);
                    const statusLabel = ariSessionStatusLabels[sessionStatus];
                    return (
                      <tr key={session.id} className="hover:bg-slate-900/60">
                        <td className="px-4 py-3">
                          {new Date(session.performed_at).toLocaleString("fr-FR")}
                        </td>
                        <td className="px-4 py-3">{collaboratorName}</td>
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
                          <button
                            type="button"
                            className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                            onClick={() => navigate(`/ari/sessions?session_id=${session.id}`)}
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
        </section>
      ) : null}
    </div>
  );
}
