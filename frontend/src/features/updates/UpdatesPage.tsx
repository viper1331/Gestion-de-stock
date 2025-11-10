import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";

interface PullRequestInfo {
  number: number;
  title: string;
  url: string;
  merged_at: string | null;
  head_sha: string;
}

interface UpdateStatus {
  repository: string;
  branch: string;
  current_commit: string | null;
  latest_pull_request: PullRequestInfo | null;
  last_deployed_pull: number | null;
  last_deployed_sha: string | null;
  last_deployed_at: string | null;
  pending_update: boolean;
}

interface UpdateApplyResponse {
  updated: boolean;
  status: UpdateStatus;
}

function formatDate(value: string | null) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

function truncateCommit(sha: string | null, length = 8) {
  if (!sha) {
    return null;
  }
  if (sha.length <= length) {
    return sha;
  }
  return sha.slice(0, length);
}

export function UpdatesPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: status,
    isFetching,
    isRefetching,
    isLoading,
    isError,
    error: statusError,
    refetch
  } = useQuery({
    queryKey: ["updates", "status"],
    queryFn: async () => {
      const response = await api.get<UpdateStatus>("/updates/status");
      return response.data;
    },
    enabled: user?.role === "admin",
    staleTime: 30_000
  });

  const applyUpdate = useMutation({
    mutationFn: async () => {
      const response = await api.post<UpdateApplyResponse>("/updates/apply");
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["updates", "status"], data.status);
      setActionError(null);
      setMessage(
        data.updated
          ? "Mise à jour appliquée avec succès."
          : "Le serveur est déjà à jour."
      );
    },
    onError: (err: unknown) => {
      console.error(err);
      setActionError("Impossible d'appliquer la mise à jour.");
    },
    onSettled: () => {
      setTimeout(() => setMessage(null), 4000);
    }
  });

  const fetchErrorMessage = useMemo(() => {
    if (!isError) {
      return null;
    }
    if (statusError instanceof Error) {
      return statusError.message;
    }
    return "Impossible de récupérer l'état des mises à jour.";
  }, [isError, statusError]);

  const latestPullRequest = status?.latest_pull_request ?? null;
  const hasPendingUpdate = Boolean(status?.pending_update);
  const formattedLastDeployment = useMemo(
    () => formatDate(status?.last_deployed_at ?? null),
    [status?.last_deployed_at]
  );
  const formattedMergedAt = useMemo(
    () => formatDate(latestPullRequest?.merged_at ?? null),
    [latestPullRequest?.merged_at]
  );

  if (user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Mises à jour GitHub</h2>
          <p className="text-sm text-slate-400">
            Seuls les administrateurs peuvent consulter cette page.
          </p>
        </header>
        <p className="text-sm text-red-400">Accès interdit.</p>
      </section>
    );
  }

  const handleRefresh = async () => {
    setActionError(null);
    setMessage(null);
    await refetch();
  };

  const handleApply = async () => {
    setActionError(null);
    setMessage(null);
    try {
      await applyUpdate.mutateAsync();
    } catch (err) {
      // L'erreur est gérée dans onError.
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Mises à jour GitHub</h2>
        <p className="text-sm text-slate-400">
          Consultez l'état des mises à jour et appliquez la dernière version disponible depuis GitHub.
        </p>
      </header>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleRefresh}
          className="inline-flex items-center rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-50"
          disabled={isFetching || isRefetching || isLoading}
        >
          {isFetching || isRefetching ? "Actualisation..." : "Actualiser"}
        </button>
        <button
          type="button"
          onClick={handleApply}
          className="inline-flex items-center rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          disabled={applyUpdate.isPending || isFetching || isLoading}
        >
          {applyUpdate.isPending ? "Mise à jour..." : "Appliquer la mise à jour"}
        </button>
      </div>

      {isLoading && !status && (
        <p className="text-sm text-slate-400">Chargement des informations de mise à jour...</p>
      )}

      {fetchErrorMessage && (
        <div className="rounded-md border border-red-500 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {fetchErrorMessage}
        </div>
      )}

      {message && (
        <div className="rounded-md border border-emerald-500 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          {message}
        </div>
      )}

      {actionError && (
        <div className="rounded-md border border-red-500 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {actionError}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/40 p-5">
          <header className="space-y-1">
            <h3 className="text-lg font-semibold text-white">Référentiel</h3>
            <p className="text-xs text-slate-400">
              Informations générales sur le dépôt configuré pour les mises à jour.
            </p>
          </header>
          <dl className="space-y-3 text-sm text-slate-200">
            <div className="flex items-start justify-between gap-4">
              <dt className="text-slate-400">Dépôt</dt>
              <dd className="font-medium text-white">{status?.repository ?? "-"}</dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-slate-400">Branche suivie</dt>
              <dd className="font-medium text-white">{status?.branch ?? "-"}</dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-slate-400">Commit actuel</dt>
              <dd className="font-mono text-sm text-white">
                {truncateCommit(status?.current_commit ?? null) ?? "-"}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4">
              <dt className="text-slate-400">Dernier déploiement</dt>
              <dd className="text-white">
                {formattedLastDeployment ?? "Jamais"}
              </dd>
            </div>
          </dl>
        </section>

        <section className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/40 p-5">
          <header className="space-y-1">
            <h3 className="text-lg font-semibold text-white">Dernier pull request fusionné</h3>
            <p className="text-xs text-slate-400">
              Détails sur la dernière contribution fusionnée dans la branche suivie.
            </p>
          </header>
          {latestPullRequest ? (
            <dl className="space-y-3 text-sm text-slate-200">
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Numéro</dt>
                <dd className="font-medium text-white">#{latestPullRequest.number}</dd>
              </div>
              <div className="space-y-1">
                <dt className="text-slate-400">Titre</dt>
                <dd className="text-white">{latestPullRequest.title}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">SHA</dt>
                <dd className="font-mono text-sm text-white">
                  {truncateCommit(latestPullRequest.head_sha)}
                </dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Fusionné le</dt>
                <dd className="text-white">{formattedMergedAt ?? "-"}</dd>
              </div>
              <div className="flex items-start justify-between gap-4">
                <dt className="text-slate-400">Lien</dt>
                <dd>
                  <a
                    href={latestPullRequest.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-300 hover:text-emerald-200"
                  >
                    Voir sur GitHub
                  </a>
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-slate-400">Aucun pull request fusionné trouvé.</p>
          )}
        </section>
      </div>

      <section className={`rounded-lg border p-5 text-sm ${hasPendingUpdate ? "border-amber-500 bg-amber-500/10 text-amber-100" : "border-slate-700 bg-slate-800/40 text-slate-200"}`}>
        <h3 className="text-lg font-semibold text-white">État de synchronisation</h3>
        {hasPendingUpdate ? (
          <p className="mt-2 text-sm">
            Une mise à jour est disponible. Appliquez la dernière version pour synchroniser le serveur avec GitHub.
          </p>
        ) : (
          <p className="mt-2 text-sm">
            Le serveur est synchronisé avec la dernière version disponible sur GitHub.
          </p>
        )}
        {status?.last_deployed_pull && (
          <p className="mt-3 text-xs opacity-80">
            Dernier pull request déployé: #{status.last_deployed_pull} ({truncateCommit(status.last_deployed_sha)}).
          </p>
        )}
      </section>
    </section>
  );
}
