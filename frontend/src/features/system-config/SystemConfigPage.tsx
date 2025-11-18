import { FormEvent, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import {
  fetchSystemConfig,
  SystemConfig,
  updateSystemConfig
} from "../../lib/systemConfig";
import { ResolvedApiConfig, resolveApiBaseUrl, resolveApiBaseUrlFromConfig } from "../../lib/apiConfig";

interface ConnectivityResult {
  status: "idle" | "success" | "error";
  message: string;
}

const DEFAULT_RESULT: ConnectivityResult = { status: "idle", message: "" };

export function SystemConfigPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const { data: config, isFetching } = useQuery({
    queryKey: ["system-config"],
    queryFn: fetchSystemConfig,
    enabled: isAdmin
  });

  const [form, setForm] = useState<SystemConfig | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityResult>(DEFAULT_RESULT);

  useEffect(() => {
    if (config) {
      setForm(config);
    }
  }, [config]);

  const corsValue = useMemo(() => (form?.cors_origins ?? []).join("\n") ?? "", [form]);
  const resolvedApi = useMemo<ResolvedApiConfig | null>(
    () => (form || config ? resolveApiBaseUrlFromConfig(form ?? config ?? null) : null),
    [config, form]
  );

  const resolvedSourceLabel = useMemo(() => {
    if (!resolvedApi) return "";
    if (resolvedApi.source === "lan") return "LAN";
    if (resolvedApi.source === "public") return "Public";
    return "Variable d'environnement";
  }, [resolvedApi]);

  const updateMutation = useMutation({
    mutationFn: updateSystemConfig,
    onSuccess: async (payload) => {
      setFeedback("Configuration enregistrée.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["system-config"] });
      setForm(payload);
      await resolveApiBaseUrl();
    },
    onError: () => {
      setFeedback(null);
      setError("Impossible d'enregistrer la configuration.");
    }
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form) return;
    setFeedback(null);
    setError(null);
    updateMutation.mutate(form);
  };

  const handleCorsChange = (value: string) => {
    if (!form) return;
    const origins = value
      .split(/\r?\n/)
      .map((origin) => origin.trim())
      .filter(Boolean);
    setForm({ ...form, cors_origins: origins });
  };

  const handleFieldChange = <K extends keyof SystemConfig>(key: K, value: SystemConfig[K]) => {
    if (!form) return;
    setForm({ ...form, [key]: value });
  };

  const testConnectivity = async () => {
    if (!form) return;
    const targetBase = resolvedApi?.baseUrl;
    if (!targetBase) {
      setConnectivity({ status: "error", message: "Aucune URL API résolue." });
      return;
    }
    const base = targetBase.replace(/\/$/, "");
    setConnectivity({ status: "idle", message: "Test de connectivité..." });
    try {
      const response = await axios.get(`${base}/health`, { timeout: 5000 });
      if (response.status === 200) {
        setConnectivity({ status: "success", message: "Le backend répond correctement." });
      } else {
        setConnectivity({ status: "error", message: `Réponse inattendue (${response.status}).` });
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setConnectivity({
          status: "error",
          message: err.message || "Impossible de joindre le backend."
        });
      } else {
        setConnectivity({ status: "error", message: "Impossible de joindre le backend." });
      }
    }
  };

  if (!isAdmin) {
    return (
      <section className="space-y-2">
        <h2 className="text-xl font-semibold text-white">Configuration système</h2>
        <p className="text-sm text-slate-400">Cette page est réservée aux administrateurs.</p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Configuration système</h2>
        <p className="text-sm text-slate-400">
          Paramétrez l'environnement (LAN ou Internet), les URLs et les origines autorisées.
        </p>
      </header>
      {isFetching ? <p className="text-sm text-slate-400">Chargement des paramètres...</p> : null}
      {feedback ? <p className="text-sm text-emerald-300">{feedback}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <form onSubmit={handleSubmit} className="space-y-6 rounded-lg border border-slate-800 bg-slate-950 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              URL backend LAN
            </span>
            <input
              type="url"
              value={form?.backend_url_lan ?? ""}
              onChange={(event) => handleFieldChange("backend_url_lan", event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              URL backend publique
            </span>
            <input
              type="url"
              value={form?.backend_url_public ?? ""}
              onChange={(event) => handleFieldChange("backend_url_public", event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Hôte backend</span>
            <input
              type="text"
              value={form?.backend_host ?? ""}
              onChange={(event) => handleFieldChange("backend_host", event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Port backend</span>
            <input
              type="number"
              min={1}
              max={65535}
              value={form?.backend_port ?? 8000}
              onChange={(event) => handleFieldChange("backend_port", Number(event.target.value))}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Hôte frontend</span>
            <input
              type="text"
              value={form?.frontend_host ?? ""}
              onChange={(event) => handleFieldChange("frontend_host", event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Port frontend</span>
            <input
              type="number"
              min={1}
              max={65535}
              value={form?.frontend_port ?? 5151}
              onChange={(event) => handleFieldChange("frontend_port", Number(event.target.value))}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              URL publique du frontend
            </span>
            <input
              type="url"
              value={form?.frontend_url ?? ""}
              onChange={(event) => handleFieldChange("frontend_url", event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              required
            />
          </label>
          <label className="space-y-2 text-sm text-slate-200">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Mode réseau</span>
            <select
              value={form?.network_mode ?? "auto"}
              onChange={(event) => handleFieldChange("network_mode", event.target.value as SystemConfig["network_mode"])}
              className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            >
              <option value="lan">LAN uniquement</option>
              <option value="public">Internet uniquement</option>
              <option value="auto">Automatique (LAN si IP privée, sinon Public)</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Origines CORS autorisées</span>
            <p className="text-xs text-slate-500">Séparez les origines par des retours à la ligne.</p>
            <textarea
              value={corsValue}
              onChange={(event) => handleCorsChange(event.target.value)}
              className="min-h-[160px] w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              placeholder="http://localhost:5151"
            />
          </div>
          <div className="space-y-3">
            <div className="space-y-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Test de connectivité backend
              </span>
              <p className="text-xs text-slate-500">
                Le test interroge l'endpoint /health du backend configuré pour vérifier son accessibilité.
              </p>
            </div>
            <button
              type="button"
              onClick={testConnectivity}
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
              disabled={!form}
            >
              Tester la connexion
            </button>
            {connectivity.message ? (
              <p
                className={
                  connectivity.status === "success"
                    ? "text-sm text-emerald-300"
                    : connectivity.status === "error"
                    ? "text-sm text-red-400"
                    : "text-sm text-slate-400"
                }
              >
                {connectivity.message}
              </p>
            ) : null}
            <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400">
              <p>URL API active (résolue) : {resolvedApi?.baseUrl ?? "Non définie"}</p>
              <p>Source : {resolvedSourceLabel || "N/A"}</p>
              <p>URL Frontend active : {form?.frontend_url ?? ""}</p>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-md border border-slate-800 bg-slate-900 p-3 text-sm text-slate-200">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Paramètres avancés</p>
            <p className="text-xs text-slate-500">
              Les valeurs supplémentaires sont enregistrées telles quelles dans la configuration système.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(form?.extra ?? {}).map(([key, value]) => (
              <label key={key} className="space-y-1 text-xs text-slate-200">
                <span className="font-semibold uppercase tracking-wide text-slate-400">{key}</span>
                <input
                  type="text"
                  value={value}
                  onChange={(event) => {
                    if (!form) return;
                    setForm({ ...form, extra: { ...form.extra, [key]: event.target.value } });
                  }}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                />
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
          <button
            type="submit"
            disabled={updateMutation.isPending || !form}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {updateMutation.isPending ? "Enregistrement..." : "Enregistrer"}
          </button>
        </div>
      </form>
    </section>
  );
}
