import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { fetchConfigEntries } from "../../lib/config";
import type { ConfigEntry } from "../../lib/config";

interface BackupScheduleStatus {
  enabled: boolean;
  days: string[];
  time: string;
  next_run: string | null;
  last_run: string | null;
}

interface BackupScheduleInput {
  enabled: boolean;
  days: string[];
  time: string;
}

const WEEK_DAYS = [
  { value: "monday", label: "Lundi" },
  { value: "tuesday", label: "Mardi" },
  { value: "wednesday", label: "Mercredi" },
  { value: "thursday", label: "Jeudi" },
  { value: "friday", label: "Vendredi" },
  { value: "saturday", label: "Samedi" },
  { value: "sunday", label: "Dimanche" }
];

const WEEK_DAY_ORDER = WEEK_DAYS.map((day) => day.value);

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: entries = [], isFetching } = useQuery({
    queryKey: ["config"],
    queryFn: fetchConfigEntries
  });
  const { data: scheduleStatus, isFetching: isScheduleFetching } = useQuery({
    queryKey: ["backup", "schedule"],
    queryFn: async () => {
      const response = await api.get<BackupScheduleStatus>("/backup/schedule");
      return response.data;
    }
  });

  const [changes, setChanges] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scheduleForm, setScheduleForm] = useState<BackupScheduleInput>({
    enabled: false,
    days: [],
    time: "02:00"
  });
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (scheduleStatus) {
      setScheduleForm({
        enabled: scheduleStatus.enabled,
        days: scheduleStatus.days,
        time: scheduleStatus.time
      });
    }
  }, [scheduleStatus]);

  const orderDays = (days: string[]) => WEEK_DAY_ORDER.filter((value) => days.includes(value));

  const toggleDay = (value: string) => {
    setScheduleForm((prev) => {
      const exists = prev.days.includes(value);
      const nextDays = exists ? prev.days.filter((day) => day !== value) : [...prev.days, value];
      return { ...prev, days: orderDays(nextDays) };
    });
  };

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

  const updateSchedule = useMutation({
    mutationFn: async (payload: BackupScheduleInput) => {
      await api.post("/backup/schedule", payload);
    },
    onSuccess: async () => {
      setMessage("Planification enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ["backup", "schedule"] });
    },
    onError: () => setError("Impossible d'enregistrer la planification."),
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

  const handleImport = async () => {
    if (!selectedFile) {
      setError("Veuillez sélectionner un fichier de sauvegarde.");
      return;
    }
    setIsImporting(true);
    setMessage(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      await api.post("/backup/import", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      setMessage("Sauvegarde importée.");
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (err) {
      setError("Impossible d'importer la sauvegarde.");
    } finally {
      setIsImporting(false);
    }
  };

  const handleScheduleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (scheduleForm.enabled && scheduleForm.days.length === 0) {
      setError("Sélectionnez au moins un jour pour la sauvegarde automatique.");
      return;
    }
    setMessage(null);
    setError(null);
    try {
      await updateSchedule.mutateAsync(scheduleForm);
    } catch (err) {
      // L'erreur est gérée via onError.
    }
  };

  const formatDateTime = (value: string | null) => {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  };

  const nextRunLabel = formatDateTime(scheduleStatus?.next_run ?? null);
  const lastRunLabel = formatDateTime(scheduleStatus?.last_run ?? null);

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
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Sauvegarde manuelle</h3>
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
        <div className="border-t border-slate-800 pt-4">
          <h3 className="text-sm font-semibold text-white">Importer une sauvegarde</h3>
          <p className="text-xs text-slate-400">Restaurez une archive créée précédemment.</p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              onChange={(event) => setSelectedFile(event.target.files ? event.target.files[0] : null)}
              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleImport}
              disabled={isImporting || !selectedFile}
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isImporting ? "Importation..." : "Importer"}
            </button>
          </div>
        </div>
        <div className="border-t border-slate-800 pt-4">
          <h3 className="text-sm font-semibold text-white">Sauvegarde automatique</h3>
          <p className="text-xs text-slate-400">Planifiez des sauvegardes régulières selon vos besoins.</p>
          {isScheduleFetching && !scheduleStatus ? (
            <p className="mt-3 text-xs text-slate-400">Chargement de la planification...</p>
          ) : (
            <form onSubmit={handleScheduleSubmit} className="mt-3 space-y-4">
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={scheduleForm.enabled}
                  onChange={(event) =>
                    setScheduleForm((prev) => ({ ...prev, enabled: event.target.checked }))
                  }
                  className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                />
                Activer les sauvegardes automatiques
              </label>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Jours de sauvegarde
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {WEEK_DAYS.map((day) => (
                    <label
                      key={day.value}
                      className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-2 text-xs text-slate-200"
                    >
                      <input
                        type="checkbox"
                        checked={scheduleForm.days.includes(day.value)}
                        onChange={() => toggleDay(day.value)}
                        disabled={!scheduleForm.enabled}
                        className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                      />
                      {day.label}
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-400" htmlFor="backup-time">
                  Heure de sauvegarde
                </label>
                <input
                  id="backup-time"
                  type="time"
                  value={scheduleForm.time}
                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, time: event.target.value }))}
                  disabled={!scheduleForm.enabled}
                  className="w-full max-w-xs rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                />
              </div>
              <button
                type="submit"
                disabled={
                  updateSchedule.isPending ||
                  (scheduleForm.enabled && scheduleForm.days.length === 0)
                }
                className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {updateSchedule.isPending ? "Enregistrement..." : "Sauvegarder la planification"}
              </button>
            </form>
          )}
          <div className="mt-4 space-y-1 text-xs text-slate-400">
            <p>
              Prochaine sauvegarde :
              {nextRunLabel ? ` ${nextRunLabel}` : " aucune sauvegarde planifiée."}
            </p>
            <p>
              Dernière sauvegarde automatique :
              {lastRunLabel ? ` ${lastRunLabel}` : " jamais exécutée."}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
