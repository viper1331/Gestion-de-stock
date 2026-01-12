import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import {
  fetchConfigEntries,
  fetchUserHomepageConfig,
  updateUserHomepageConfig
} from "../../lib/config";
import type { ConfigEntry } from "../../lib/config";
import { useAuth } from "../auth/useAuth";
import { MODULE_TITLE_DEFAULTS } from "../../lib/moduleTitles";
import {
  buildHomeConfig,
  DEFAULT_HOME_CONFIG,
  HomePageConfigKey,
  isHomePageConfigKey
} from "../home/homepageConfig";
import { DebugFlags } from "../../lib/debug";
import { useSpellcheckSettings } from "../../app/spellcheckSettings";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

const COLLAPSED_STORAGE_KEY = "settings:collapsedSections";

interface BackupScheduleStatus {
  enabled: boolean;
  days: string[];
  times: string[];
  next_run: string | null;
  last_run: string | null;
}

interface BackupScheduleInput {
  enabled: boolean;
  days: string[];
  times: string[];
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

type HomepageFieldType = "text" | "textarea" | "url";

const ENTRY_DESCRIPTIONS: Record<string, string> = {
  "general.inactivity_timeout_minutes":
    "Durée d'inactivité en minutes avant la déconnexion automatique. Définissez 0 ou laissez vide pour désactiver.",
  "modules.barcode": "Titre principal affiché sur la page des codes-barres.",
  "modules.clothing": "Titre principal affiché sur l'inventaire habillement.",
  "modules.dotations": "Titre principal affiché sur la page des dotations.",
  "modules.inventory_remise": "Titre principal affiché sur l'inventaire remises.",
  "modules.pharmacy": "Titre principal affiché sur l'inventaire pharmacie.",
  "modules.suppliers": "Titre principal affiché sur la page fournisseurs.",
  "modules.vehicle_inventory": "Titre principal affiché sur l'inventaire véhicules.",
  "modules.vehicle_qrcodes": "Titre principal affiché sur la gestion des QR codes véhicules."
};

const MODULE_TITLE_ENTRIES: ConfigEntry[] = Object.entries(MODULE_TITLE_DEFAULTS).map(
  ([key, value]) => ({
    section: "modules",
    key,
    value
  })
);

const HOMEPAGE_FIELDS: Array<{
  key: HomePageConfigKey;
  label: string;
  description: string;
  type?: HomepageFieldType;
}> = [
  {
    key: "title",
    label: "Titre principal",
    description: "Titre affiché en haut de la page d'accueil."
  },
  {
    key: "subtitle",
    label: "Sous-titre",
    description: "Texte introductif sous le titre principal.",
    type: "textarea"
  },
  {
    key: "welcome_message",
    label: "Message de bienvenue",
    description: "Paragraphe d'accueil présenté à l'utilisateur connecté.",
    type: "textarea"
  },
  {
    key: "announcement",
    label: "Annonce",
    description: "Encadré d'information mis en avant sur la page.",
    type: "textarea"
  },
  {
    key: "primary_link_label",
    label: "Libellé du lien principal",
    description: "Texte du bouton d'action principal."
  },
  {
    key: "primary_link_path",
    label: "Lien principal",
    description: "Chemin interne ouvert par le bouton principal (ex: /inventory).",
    type: "url"
  },
  {
    key: "secondary_link_label",
    label: "Libellé du lien secondaire",
    description: "Texte du second bouton d'action."
  },
  {
    key: "secondary_link_path",
    label: "Lien secondaire",
    description: "Chemin interne ouvert par le second bouton (ex: /reports).",
    type: "url"
  },
  {
    key: "focus_1_label",
    label: "Priorité 1 - titre",
    description: "Titre du premier encadré de priorité."
  },
  {
    key: "focus_1_description",
    label: "Priorité 1 - description",
    description: "Description du premier encadré.",
    type: "textarea"
  },
  {
    key: "focus_2_label",
    label: "Priorité 2 - titre",
    description: "Titre du second encadré de priorité."
  },
  {
    key: "focus_2_description",
    label: "Priorité 2 - description",
    description: "Description du second encadré.",
    type: "textarea"
  },
  {
    key: "focus_3_label",
    label: "Priorité 3 - titre",
    description: "Titre du troisième encadré de priorité."
  },
  {
    key: "focus_3_description",
    label: "Priorité 3 - description",
    description: "Description du troisième encadré.",
    type: "textarea"
  }
];

export function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { settings: spellcheckSettings, updateSettings: updateSpellcheckSettings } =
    useSpellcheckSettings();
  const queryClient = useQueryClient();
  const { data: entries = [], isFetching } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries
  });
  const { data: scheduleStatus, isFetching: isScheduleFetching } = useQuery({
    queryKey: ["backup", "schedule"],
    queryFn: async () => {
      const response = await api.get<BackupScheduleStatus>("/backup/schedule");
      return response.data;
    },
    enabled: isAdmin
  });
  const { data: personalEntries = [], isFetching: isFetchingPersonal } = useQuery({
    queryKey: ["config", "homepage", "personal"],
    queryFn: fetchUserHomepageConfig
  });

  const [changes, setChanges] = useState<Record<string, string>>({});
  const [homepageChanges, setHomepageChanges] = useState<Partial<Record<HomePageConfigKey, string>>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [scheduleForm, setScheduleForm] = useState<BackupScheduleInput>({
    enabled: false,
    days: [],
    times: ["02:00"]
  });
  const [debugConfig, setDebugConfig] = useState<DebugFlags>({
    frontend_debug: false,
    backend_debug: false,
    inventory_debug: false,
    network_debug: false
  });
  const [isLoadingDebugConfig, setIsLoadingDebugConfig] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => {
    if (typeof window === "undefined") {
      return {};
    }
    try {
      const storedValue = window.localStorage.getItem(COLLAPSED_STORAGE_KEY);
      if (!storedValue) {
        return {};
      }
      const parsed = JSON.parse(storedValue);
      if (typeof parsed !== "object" || parsed === null) {
        return {};
      }
      return Object.entries(parsed as Record<string, unknown>).reduce(
        (acc, [key, value]) => {
          acc[key] = Boolean(value);
          return acc;
        },
        {} as Record<string, boolean>
      );
    } catch (err) {
      console.warn("Impossible de lire l'état des sections masquées", err);
      return {};
    }
  });

  useEffect(() => {
    if (scheduleStatus) {
      setScheduleForm({
        enabled: scheduleStatus.enabled,
        days: scheduleStatus.days,
        times: scheduleStatus.times.length ? scheduleStatus.times : ["02:00"]
      });
    }
  }, [scheduleStatus]);

  useEffect(() => {
    if (!isAdmin) {
      return undefined;
    }

    let ignore = false;
    setIsLoadingDebugConfig(true);

    api
      .get<DebugFlags>("/admin/debug-config")
      .then((response) => {
        if (ignore) {
          return;
        }
        setDebugConfig(response.data);
        Object.entries(response.data).forEach(([key, value]) => {
          if (typeof window !== "undefined") {
            window.localStorage.setItem(key, value ? "1" : "0");
          }
        });
      })
      .catch(() => {
        if (!ignore) {
          setError("Impossible de charger la configuration debug.");
        }
      })
      .finally(() => {
        if (!ignore) {
          setIsLoadingDebugConfig(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [isAdmin]);

  const backupTimeInputs = scheduleForm.times.length ? scheduleForm.times : ["02:00"];

  const orderDays = (days: string[]) => WEEK_DAY_ORDER.filter((value) => days.includes(value));

  const toggleDay = (value: string) => {
    setScheduleForm((prev) => {
      const exists = prev.days.includes(value);
      const nextDays = exists ? prev.days.filter((day) => day !== value) : [...prev.days, value];
      return { ...prev, days: orderDays(nextDays) };
    });
  };

  const entriesWithModuleTitles = useMemo(() => {
    const existingKeys = new Set(entries.map((entry) => `${entry.section}.${entry.key}`));
    const merged = [...entries];
    MODULE_TITLE_ENTRIES.forEach((entry) => {
      const id = `${entry.section}.${entry.key}`;
      if (!existingKeys.has(id)) {
        merged.push(entry);
      }
    });
    return merged;
  }, [entries]);

  const groupedEntries = useMemo(() => {
    return entriesWithModuleTitles
      .filter((entry) => entry.section !== "homepage")
      .reduce<Record<string, ConfigEntry[]>>((acc, entry) => {
        if (!acc[entry.section]) {
          acc[entry.section] = [];
        }
        acc[entry.section].push(entry);
        return acc;
      }, {});
  }, [entriesWithModuleTitles]);

  const personalHomepageMap = useMemo(() => {
    return personalEntries.reduce<Partial<Record<HomePageConfigKey, string>>>((acc, entry) => {
      if (entry.section === "homepage" && isHomePageConfigKey(entry.key)) {
        acc[entry.key] = entry.value;
      }
      return acc;
    }, {});
  }, [personalEntries]);

  const effectiveHomepageConfig = useMemo(
    () => buildHomeConfig([...entries, ...personalEntries]),
    [entries, personalEntries]
  );

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

  const updateHomepagePreference = useMutation({
    mutationFn: updateUserHomepageConfig,
    onSuccess: async () => {
      setMessage("Préférence enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ["config", "homepage", "personal"] });
    },
    onError: () => setError("Impossible d'enregistrer la personnalisation."),
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

  const updateDebugConfig = async (partial: Partial<DebugFlags>) => {
    const newCfg = { ...debugConfig, ...partial };
    setDebugConfig(newCfg);

    Object.entries(newCfg).forEach(([key, value]) => {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(key, value ? "1" : "0");
      }
    });

    try {
      await api.put("/admin/debug-config", newCfg);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Erreur update debug config", err);
    }
  };

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

  const handleHomepageSubmit = async (
    event: FormEvent<HTMLFormElement>,
    key: HomePageConfigKey
  ) => {
    event.preventDefault();
    const pendingValue = homepageChanges[key] ?? personalHomepageMap[key] ?? "";
    setMessage(null);
    setError(null);
    try {
      await updateHomepagePreference.mutateAsync({
        section: "homepage",
        key,
        value: pendingValue
      });
      setHomepageChanges((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } catch (err) {
      // handled in onError
    }
  };

  const handleHomepageReset = async (key: HomePageConfigKey) => {
    setMessage(null);
    setError(null);
    try {
      await updateHomepagePreference.mutateAsync({
        section: "homepage",
        key,
        value: ""
      });
      setHomepageChanges((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } catch (err) {
      // handled in onError
    }
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
    const uniqueTimes = getUniqueTimes(scheduleForm.times);
    if (scheduleForm.enabled && uniqueTimes.length === 0) {
      setError("Ajoutez au moins une heure pour la sauvegarde automatique.");
      return;
    }
    setMessage(null);
    setError(null);
    try {
      await updateSchedule.mutateAsync({ ...scheduleForm, times: uniqueTimes });
    } catch (err) {
      // L'erreur est gérée via onError.
    }
  };

  const getUniqueTimes = (values: string[]) => {
    const seen = new Set<string>();
    return values
      .map((value) => value.trim())
      .filter((value) => value)
      .filter((value) => {
        if (seen.has(value)) {
          return false;
        }
        seen.add(value);
        return true;
      });
  };

  const handleTimeChange = (index: number, value: string) => {
    setScheduleForm((prev) => {
      const updatedTimes = [...prev.times];
      updatedTimes[index] = value;
      return { ...prev, times: updatedTimes };
    });
  };

  const handleAddTime = () => {
    setScheduleForm((prev) => {
      const fallback = prev.times[prev.times.length - 1] ?? "12:00";
      return { ...prev, times: [...prev.times, fallback] };
    });
  };

  const handleRemoveTime = (index: number) => {
    setScheduleForm((prev) => ({
      ...prev,
      times: prev.times.filter((_, idx) => idx !== index)
    }));
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

  const isSectionCollapsed = (id: string) => collapsedSections[id] ?? false;

  const toggleSectionVisibility = (id: string) => {
    setCollapsedSections((prev) => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const handleDebugToggle = (key: keyof DebugFlags, enabled: boolean) => {
    void updateDebugConfig({ [key]: enabled });
  };

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify(collapsedSections));
    } catch (err) {
      console.warn("Impossible d'enregistrer l'état des sections masquées", err);
    }
  }, [collapsedSections]);

  const getSectionContentId = (id: string) =>
    `settings-section-${id.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}`;

  const homepageSectionKey = "homepage";
  const backupsSectionKey = "backups";

  const content = (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Paramètres</h2>
        <p className="text-sm text-slate-400">Synchronisez vos préférences avec le backend.</p>
      </header>
      {isFetching || isFetchingPersonal ? (
        <p className="text-sm text-slate-400">Chargement des paramètres...</p>
      ) : null}
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="space-y-4">
          <header className="space-y-1">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
              Orthographe
            </h3>
            <p className="text-xs text-slate-400">
              Activez le correcteur global et choisissez la langue de vérification.
            </p>
          </header>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
              <span className="text-xs font-semibold text-slate-200">Correcteur activé</span>
              <input
                type="checkbox"
                checked={spellcheckSettings.enabled}
                onChange={(event) => updateSpellcheckSettings({ enabled: event.target.checked })}
                className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
              />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
              <span className="text-xs font-semibold text-slate-200">
                Vérification pendant la saisie
              </span>
              <input
                type="checkbox"
                checked={spellcheckSettings.live}
                onChange={(event) => updateSpellcheckSettings({ live: event.target.checked })}
                className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
              />
            </label>
            <label className="flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200">
              Langue
              <select
                value={spellcheckSettings.language}
                onChange={(event) =>
                  updateSpellcheckSettings({ language: event.target.value as "fr" | "en" })
                }
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
              >
                <option value="fr">Français</option>
                <option value="en">Anglais</option>
              </select>
            </label>
          </div>
        </div>
      </div>
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <header className="space-y-1">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
                Personnalisation de l'accueil
              </h3>
              <p className="text-xs text-slate-400">
                Modifiez vos textes sans impacter les autres utilisateurs. Laisser un champ vide
                rétablit la valeur organisationnelle.
              </p>
            </header>
            <button
              type="button"
              onClick={() => toggleSectionVisibility(homepageSectionKey)}
              className="self-start rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
              aria-expanded={!isSectionCollapsed(homepageSectionKey)}
              aria-controls={getSectionContentId(homepageSectionKey)}
            >
              {isSectionCollapsed(homepageSectionKey) ? "Afficher" : "Masquer"}
            </button>
          </div>
          <div
            id={getSectionContentId(homepageSectionKey)}
            className="space-y-4"
            hidden={isSectionCollapsed(homepageSectionKey)}
          >
            {HOMEPAGE_FIELDS.map((field) => {
              const pendingValue = homepageChanges[field.key] ?? personalHomepageMap[field.key] ?? "";
              const effectiveValue = effectiveHomepageConfig[field.key];
              const isDirty = homepageChanges[field.key] !== undefined;
              const isMultiline = field.type === "textarea";
              return (
                <form
                  key={field.key}
                  onSubmit={(event) => handleHomepageSubmit(event, field.key)}
                  className="space-y-2 rounded-md border border-slate-800 bg-slate-950 p-3"
                >
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold uppercase tracking-wide text-slate-300">
                      {field.label}
                    </label>
                    <p className="text-[11px] text-slate-500">{field.description}</p>
                    <p className="text-[11px] text-slate-500">
                      Valeur appliquée : <span className="text-slate-300">{effectiveValue}</span>
                    </p>
                  </div>
                  {isMultiline ? (
                    <AppTextArea
                      value={pendingValue}
                      onChange={(event) =>
                        setHomepageChanges((prev) => ({ ...prev, [field.key]: event.target.value }))
                      }
                      placeholder={DEFAULT_HOME_CONFIG[field.key]}
                      className="h-28 w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                  ) : (
                    <AppTextInput
                      type={field.type === "url" ? "text" : "text"}
                      value={pendingValue}
                      onChange={(event) =>
                        setHomepageChanges((prev) => ({ ...prev, [field.key]: event.target.value }))
                      }
                      placeholder={DEFAULT_HOME_CONFIG[field.key]}
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                  )}
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
                    <button
                      type="button"
                      onClick={() => handleHomepageReset(field.key)}
                      className="inline-flex items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
                    >
                      Réinitialiser
                    </button>
                    <button
                      type="submit"
                      disabled={
                        updateHomepagePreference.isPending ||
                        (!isDirty && (personalHomepageMap[field.key] ?? "") === pendingValue)
                      }
                      className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {updateHomepagePreference.isPending ? "Enregistrement..." : "Enregistrer"}
                    </button>
                  </div>
                </form>
              );
            })}
          </div>
        </div>
      </div>
      {isAdmin ? (
        <>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
                  Debug (Administrateur)
                </h3>
                <p className="text-xs text-slate-400">
                  Activez les journaux détaillés pour le frontend, les APIs et les interactions drag & drop.
                </p>
              </div>
              {isLoadingDebugConfig ? (
                <span className="text-[11px] text-slate-400">Chargement...</span>
              ) : null}
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="flex items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-slate-200">Frontend debug</p>
                  <p className="text-xs text-slate-400">Journalise les interactions UI en direct.</p>
                </div>
                <AppTextInput
                  type="checkbox"
                  checked={debugConfig.frontend_debug}
                  onChange={(event) => handleDebugToggle("frontend_debug", event.target.checked)}
                  disabled={isLoadingDebugConfig}
                  className="h-5 w-5 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                />
              </label>
              <label className="flex items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-slate-200">Backend debug</p>
                  <p className="text-xs text-slate-400">Active les journaux enrichis côté serveur.</p>
                </div>
                <AppTextInput
                  type="checkbox"
                  checked={debugConfig.backend_debug}
                  onChange={(event) => handleDebugToggle("backend_debug", event.target.checked)}
                  disabled={isLoadingDebugConfig}
                  className="h-5 w-5 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                />
              </label>
              <label className="flex items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-slate-200">Inventory debug (drag & drop)</p>
                  <p className="text-xs text-slate-400">Trace les positions et affectations d'inventaire.</p>
                </div>
                <AppTextInput
                  type="checkbox"
                  checked={debugConfig.inventory_debug}
                  onChange={(event) => handleDebugToggle("inventory_debug", event.target.checked)}
                  disabled={isLoadingDebugConfig}
                  className="h-5 w-5 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                />
              </label>
              <label className="flex items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-slate-200">Network debug (API)</p>
                  <p className="text-xs text-slate-400">Capture les requêtes/réponses API en console.</p>
                </div>
                <AppTextInput
                  type="checkbox"
                  checked={debugConfig.network_debug}
                  onChange={(event) => handleDebugToggle("network_debug", event.target.checked)}
                  disabled={isLoadingDebugConfig}
                  className="h-5 w-5 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                />
              </label>
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900">
            <div className="divide-y divide-slate-900">
              {Object.entries(groupedEntries).map(([section, sectionEntries]) => {
                const sectionKey = `admin:${section}`;
                const sectionContentId = getSectionContentId(sectionKey);
                return (
                <div key={section} className="p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">{section}</h3>
                    <button
                      type="button"
                      onClick={() => toggleSectionVisibility(sectionKey)}
                      className="rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
                      aria-expanded={!isSectionCollapsed(sectionKey)}
                      aria-controls={sectionContentId}
                    >
                      {isSectionCollapsed(sectionKey) ? "Afficher" : "Masquer"}
                    </button>
                  </div>
                  <div
                    id={sectionContentId}
                    className="mt-3 space-y-3"
                    hidden={isSectionCollapsed(sectionKey)}
                  >
                    {sectionEntries.map((entry) => {
                      const key = `${entry.section}.${entry.key}`;
                      const pendingValue = changes[key] ?? entry.value;
                      const description = ENTRY_DESCRIPTIONS[key];
                      return (
                        <form
                          key={key}
                          className="flex flex-wrap items-center gap-3 rounded-md border border-slate-800 bg-slate-950 p-3"
                          onSubmit={(event) => handleSubmit(event, entry)}
                        >
                          <div className="w-full sm:w-48">
                            <p className="text-xs font-semibold text-slate-400">{entry.key}</p>
                            <p className="text-[11px] text-slate-500">Valeur actuelle : {entry.value}</p>
                            {description ? (
                              <p className="text-[11px] text-slate-500">{description}</p>
                            ) : null}
                          </div>
                          <AppTextInput
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
              );
            })}
          </div>
        </div>
        </>
      ) : null}
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Sauvegardes</h3>
              <p className="text-xs text-slate-400">
                Gérez vos sauvegardes manuelles et automatiques pour sécuriser vos données.
              </p>
            </div>
            <button
              type="button"
              onClick={() => toggleSectionVisibility(backupsSectionKey)}
              className="self-start rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
              aria-expanded={!isSectionCollapsed(backupsSectionKey)}
              aria-controls={getSectionContentId(backupsSectionKey)}
            >
              {isSectionCollapsed(backupsSectionKey) ? "Afficher" : "Masquer"}
            </button>
          </div>
          <div
            id={getSectionContentId(backupsSectionKey)}
            className="space-y-6"
            hidden={isSectionCollapsed(backupsSectionKey)}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white">Sauvegarde manuelle</h3>
                <p className="text-xs text-slate-400">
                  Téléchargez un export ZIP des bases utilisateurs et stock.
                </p>
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
                <AppTextInput
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
                    <AppTextInput
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
                          <AppTextInput
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
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Heures de sauvegarde</p>
                    <div className="space-y-2">
                      {backupTimeInputs.map((timeValue, index) => (
                        <div key={`backup-time-${index}`} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                          <AppTextInput
                            type="time"
                            value={timeValue}
                            onChange={(event) => handleTimeChange(index, event.target.value)}
                            disabled={!scheduleForm.enabled}
                            className="w-full max-w-xs rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => handleRemoveTime(index)}
                            disabled={!scheduleForm.enabled || backupTimeInputs.length === 1}
                            className="inline-flex items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
                          >
                            Supprimer
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={handleAddTime}
                        disabled={!scheduleForm.enabled}
                        className="inline-flex items-center justify-center rounded-md border border-indigo-500 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/10 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        Ajouter un horaire
                      </button>
                    </div>
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
        </div>
      </div>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "settings-main",
      title: "Paramètres",
      required: true,
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      variant: "plain",
      render: () => (
        <EditableBlock id="settings-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout pageKey="module:settings" blocks={blocks} className="space-y-6" />
  );
}
