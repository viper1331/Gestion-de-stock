import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";

interface ConfigEntry {
  section: string;
  key: string;
  value: string;
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: entries = [], isFetching } = useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const response = await api.get<ConfigEntry[]>("/config/");
      return response.data;
    }
  });

  const [changes, setChanges] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBackingUp, setIsBackingUp] = useState(false);

  const groupedEntries = useMemo(() => {
    return entries.reduce<Record<string, ConfigEntry[]>>((acc, entry) => {
      if (!acc[entry.section]) {
        acc[entry.section] = [];
      }
      acc[entry.section].push(entry);
      return acc;
    }, {});
  }, [entries]);

  const updateConfig = useMutation({
    mutationFn: async (entry: ConfigEntry) => {
      await api.post("/config/", entry);
    },
    onSuccess: async () => {
      setMessage("Paramètre enregistré.");
      await queryClient.invalidateQueries({ queryKey: ["config"] });
    },
    onError: () => setError("Impossible d'enregistrer le paramètre."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const handleSubmit = async (event: FormEvent<HTMLFormElement>, entry: ConfigEntry) => {
    event.preventDefault();
    const key = `${entry.section}.${entry.key}`;
    const value = changes[key] ?? entry.value;
    setMessage(null);
    setError(null);
    await updateConfig.mutateAsync({ ...entry, value });
    setChanges((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleBackup = async () => {
    setIsBackingUp(true);
    setMessage(null);
    setError(null);
    try {
      const response = await api.get<Blob>("/backup/", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = "backup-stock.zip";
      link.click();
      URL.revokeObjectURL(url);
      setMessage("Sauvegarde téléchargée.");
    } catch (err) {
      setError("Impossible de générer la sauvegarde.");
    } finally {
      setIsBackingUp(false);
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Paramètres</h2>
        <p className="text-sm text-slate-400">Synchronisez vos préférences avec le backend.</p>
      </header>
      {isFetching ? <p className="text-sm text-slate-400">Chargement des paramètres...</p> : null}
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <div className="rounded-lg border border-slate-800 bg-slate-900">
        <div className="divide-y divide-slate-900">
          {Object.entries(groupedEntries).map(([section, sectionEntries]) => (
            <div key={section} className="p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">{section}</h3>
              <div className="mt-3 space-y-3">
                {sectionEntries.map((entry) => {
                  const key = `${entry.section}.${entry.key}`;
                  const pendingValue = changes[key] ?? entry.value;
                  return (
                    <form
                      key={key}
                      className="flex flex-wrap items-center gap-3 rounded-md border border-slate-800 bg-slate-950 p-3"
                      onSubmit={(event) => handleSubmit(event, entry)}
                    >
                      <div className="w-full sm:w-48">
                        <p className="text-xs font-semibold text-slate-400">{entry.key}</p>
                        <p className="text-[11px] text-slate-500">Valeur actuelle : {entry.value}</p>
                      </div>
                      <input
                        value={pendingValue}
                        onChange={(event) => setChanges((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="flex-1 rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                        title="Modifier la valeur qui sera synchronisée avec le serveur"
                      />
                      <button
                        type="submit"
                        disabled={updateConfig.isPending || pendingValue === entry.value}
                        className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                        title={
                          updateConfig.isPending
                            ? "Enregistrement en cours"
                            : pendingValue === entry.value
                            ? "Aucune modification à sauvegarder"
                            : "Sauvegarder ce paramètre"
                        }
                      >
                        {updateConfig.isPending ? "Enregistrement..." : "Enregistrer"}
                      </button>
                    </form>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Sauvegarde des bases</h3>
            <p className="text-xs text-slate-400">Téléchargez un export ZIP des bases utilisateurs et stock.</p>
          </div>
          <button
            type="button"
            onClick={handleBackup}
            disabled={isBackingUp}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
            title="Télécharger une sauvegarde complète des données"
          >
            {isBackingUp ? "Sauvegarde..." : "Exporter"}
          </button>
        </div>
      </div>
    </section>
  );
}
