import axios, { AxiosError } from "axios";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import { applyLatestUpdate, fetchUpdateStatus, revertToPreviousUpdate } from "./api";
import { EditablePageLayout, type EditableLayoutSet, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

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

  const formatApiError = (err: unknown, fallback: string) => {
    if (axios.isAxiosError(err)) {
      const responseMessage = (err as AxiosError<{ detail?: string }>).response?.data?.detail;
      if (typeof responseMessage === "string" && responseMessage.trim()) {
        return responseMessage;
      }
    }
    if (err instanceof Error && err.message) {
      return err.message;
    }
    return fallback;
  };

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
    queryFn: fetchUpdateStatus,
    enabled: user?.role === "admin",
    staleTime: 30_000
  });

  const applyUpdate = useMutation({
    mutationFn: applyLatestUpdate,
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
      setActionError(formatApiError(err, "Impossible d'appliquer la mise à jour."));
    },
    onSettled: () => {
      setTimeout(() => setMessage(null), 4000);
    }
  });

  const revertUpdate = useMutation({
    mutationFn: revertToPreviousUpdate,
    onSuccess: (data) => {
      queryClient.setQueryData(["updates", "status"], data.status);
      setActionError(null);
      setMessage(
        data.updated
          ? "Version précédente restaurée."
          : "Aucune version précédente n'a pu être restaurée."
      );
    },
    onError: (err: unknown) => {
      console.error(err);
      setActionError(formatApiError(err, "Impossible de restaurer la version précédente."));
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
  const formattedPreviousDeployment = useMemo(
    () => formatDate(status?.previous_deployed_at ?? null),
    [status?.previous_deployed_at]
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

  const handleRevert = async () => {
    setActionError(null);
    setMessage(null);
    try {
      await revertUpdate.mutateAsync();
    } catch (err) {
      // L'erreur est gérée dans onError.
    }
  };

  const content = (
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
        <button
          type="button"
          onClick={handleRevert}
          className="inline-flex items-center rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
          disabled={
            revertUpdate.isPending ||
            isFetching ||
            isLoading ||
            !status?.can_revert
          }
        >
          {revertUpdate.isPending ? "Restauration..." : "Restaurer la version précédente"}
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
        {status?.previous_deployed_sha && (
          <p className="mt-1 text-xs opacity-80">
            Version précédente disponible: #{status.previous_deployed_pull ?? "-"} ({truncateCommit(status.previous_deployed_sha)}), déployée le {formattedPreviousDeployment ?? "-"}.
          </p>
        )}
      </section>
    </section>
  );

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [{ i: "updates-main", x: 0, y: 0, w: 12, h: 24 }],
      md: [{ i: "updates-main", x: 0, y: 0, w: 6, h: 24 }],
      sm: [{ i: "updates-main", x: 0, y: 0, w: 1, h: 24 }],
      xs: [{ i: "updates-main", x: 0, y: 0, w: 1, h: 24 }]
    }),
    []
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "updates-main",
      title: "Mises à jour",
      required: true,
      permission: { role: "admin" },
      containerClassName: "rounded-none border-0 bg-transparent p-0",
      render: () => (
        <EditableBlock id="updates-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:updates"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      pagePermission={{ role: "admin" }}
      className="space-y-6"
    />
  );
}
