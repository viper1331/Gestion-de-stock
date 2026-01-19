import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { fetchSiteContext, updateActiveSite, type SiteContext } from "../../lib/sites";
import {
  CUSTOM_FIELD_SCOPES,
  CUSTOM_FIELD_TYPES,
  CustomFieldDefinition
} from "../../lib/customFields";
import {
  clearPersistedLogs,
  getPersistedLogs,
  isLogPersistenceEnabled,
  setLogPersistenceEnabled
} from "../../lib/logger";
import { useAuth } from "../auth/useAuth";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

interface VehicleTypeEntry {
  id: number;
  code: string;
  label: string;
  is_active: boolean;
}

interface VehicleTypeFormState {
  code: string;
  label: string;
  is_active: boolean;
}

interface CustomFieldFormState {
  scope: string;
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  defaultValue: string;
  options: string;
  is_active: boolean;
  sort_order: number;
}

interface SmtpSettingsResponse {
  host: string | null;
  port: number;
  username: string | null;
  from_email: string;
  use_tls: boolean;
  use_ssl: boolean;
  timeout_seconds: number;
  dev_sink: boolean;
  smtp_password_set: boolean;
}

interface SmtpFormState {
  host: string;
  port: number;
  username: string;
  password: string;
  clearPassword: boolean;
  from_email: string;
  use_tls: boolean;
  use_ssl: boolean;
  timeout_seconds: number;
  dev_sink: boolean;
}

interface OtpEmailSettingsPayload {
  ttl_minutes: number;
  code_length: number;
  max_attempts: number;
  resend_cooldown_seconds: number;
  rate_limit_per_hour: number;
  allow_insecure_dev: boolean;
}

const EMPTY_VEHICLE_TYPE_FORM: VehicleTypeFormState = {
  code: "",
  label: "",
  is_active: true
};

const EMPTY_CUSTOM_FIELD_FORM: CustomFieldFormState = {
  scope: "vehicles",
  key: "",
  label: "",
  field_type: "text",
  required: false,
  defaultValue: "",
  options: "",
  is_active: true,
  sort_order: 0
};

const DEFAULT_SMTP_FORM: SmtpFormState = {
  host: "",
  port: 587,
  username: "",
  password: "",
  clearPassword: false,
  from_email: "StockOps <no-reply@localhost>",
  use_tls: true,
  use_ssl: false,
  timeout_seconds: 10,
  dev_sink: false
};

const DEFAULT_OTP_FORM: OtpEmailSettingsPayload = {
  ttl_minutes: 10,
  code_length: 6,
  max_attempts: 5,
  resend_cooldown_seconds: 45,
  rate_limit_per_hour: 6,
  allow_insecure_dev: false
};

export function AdminSettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"vehicle-types" | "custom-fields">("vehicle-types");
  const [vehicleTypeForm, setVehicleTypeForm] = useState<VehicleTypeFormState>(EMPTY_VEHICLE_TYPE_FORM);
  const [customScope, setCustomScope] = useState<string>(EMPTY_CUSTOM_FIELD_FORM.scope);
  const [customFieldForm, setCustomFieldForm] = useState<CustomFieldFormState>(EMPTY_CUSTOM_FIELD_FORM);
  const [editingVehicleTypeId, setEditingVehicleTypeId] = useState<number | null>(null);
  const [editingCustomFieldId, setEditingCustomFieldId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [smtpForm, setSmtpForm] = useState<SmtpFormState>(DEFAULT_SMTP_FORM);
  const [smtpPasswordSet, setSmtpPasswordSet] = useState<boolean>(false);
  const [smtpMessage, setSmtpMessage] = useState<string | null>(null);
  const [smtpError, setSmtpError] = useState<string | null>(null);
  const [smtpTestEmail, setSmtpTestEmail] = useState<string>("");
  const [smtpTestMessage, setSmtpTestMessage] = useState<string | null>(null);
  const [smtpTestError, setSmtpTestError] = useState<string | null>(null);
  const [otpForm, setOtpForm] = useState<OtpEmailSettingsPayload>(DEFAULT_OTP_FORM);
  const [otpMessage, setOtpMessage] = useState<string | null>(null);
  const [otpError, setOtpError] = useState<string | null>(null);
  const [persistLogsEnabled, setPersistLogsEnabled] = useState<boolean>(() =>
    isLogPersistenceEnabled()
  );
  const [logMessage, setLogMessage] = useState<string | null>(null);
  const [siteMessage, setSiteMessage] = useState<string | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [selectedSite, setSelectedSite] = useState<string>("");

  const { data: vehicleTypes = [] } = useQuery({
    queryKey: ["admin-vehicle-types"],
    queryFn: async () => {
      const response = await api.get<VehicleTypeEntry[]>("/admin/vehicle-types");
      return response.data;
    },
    enabled: isAdmin
  });

  const { data: customFields = [] } = useQuery({
    queryKey: ["admin-custom-fields", customScope],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: customScope }
      });
      return response.data;
    },
    enabled: isAdmin
  });

  const { data: siteContext } = useQuery<SiteContext>({
    queryKey: ["site-context"],
    queryFn: fetchSiteContext,
    enabled: isAdmin
  });

  const { data: smtpSettings } = useQuery<SmtpSettingsResponse>({
    queryKey: ["admin-smtp-settings"],
    queryFn: async () => {
      const response = await api.get<SmtpSettingsResponse>("/admin/email/smtp-settings");
      return response.data;
    },
    enabled: isAdmin
  });

  const { data: otpSettings } = useQuery<OtpEmailSettingsPayload>({
    queryKey: ["admin-otp-email-settings"],
    queryFn: async () => {
      const response = await api.get<OtpEmailSettingsPayload>("/admin/email/otp-settings");
      return response.data;
    },
    enabled: isAdmin
  });

  useEffect(() => {
    setSelectedSite(siteContext?.override_site_key ?? "");
  }, [siteContext?.override_site_key]);

  useEffect(() => {
    if (!smtpSettings) {
      return;
    }
    setSmtpForm((prev) => ({
      ...prev,
      host: smtpSettings.host ?? "",
      port: smtpSettings.port,
      username: smtpSettings.username ?? "",
      from_email: smtpSettings.from_email,
      use_tls: smtpSettings.use_tls,
      use_ssl: smtpSettings.use_ssl,
      timeout_seconds: smtpSettings.timeout_seconds,
      dev_sink: smtpSettings.dev_sink
    }));
    setSmtpPasswordSet(smtpSettings.smtp_password_set);
  }, [smtpSettings]);

  useEffect(() => {
    if (!otpSettings) {
      return;
    }
    setOtpForm(otpSettings);
  }, [otpSettings]);

  const resetVehicleTypeForm = () => {
    setVehicleTypeForm(EMPTY_VEHICLE_TYPE_FORM);
    setEditingVehicleTypeId(null);
  };

  const resetCustomFieldForm = (scope = customScope) => {
    setCustomFieldForm({ ...EMPTY_CUSTOM_FIELD_FORM, scope });
    setEditingCustomFieldId(null);
  };

  const createVehicleType = useMutation({
    mutationFn: async (payload: VehicleTypeFormState) => {
      await api.post("/admin/vehicle-types", payload);
    },
    onSuccess: async () => {
      setMessage("Type de véhicule créé.");
      setError(null);
      resetVehicleTypeForm();
      await queryClient.invalidateQueries({ queryKey: ["admin-vehicle-types"] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de créer le type de véhicule.");
    }
  });

  const updateVehicleType = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: Partial<VehicleTypeFormState> }) => {
      await api.patch(`/admin/vehicle-types/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Type de véhicule mis à jour.");
      setError(null);
      resetVehicleTypeForm();
      await queryClient.invalidateQueries({ queryKey: ["admin-vehicle-types"] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de mettre à jour le type de véhicule.");
    }
  });

  const deleteVehicleType = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/admin/vehicle-types/${id}`);
    },
    onSuccess: async () => {
      setMessage("Type de véhicule désactivé.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-vehicle-types"] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de désactiver le type de véhicule.");
    }
  });

  const createCustomField = useMutation({
    mutationFn: async (payload: CustomFieldFormState) => {
      await api.post("/admin/custom-fields", buildCustomFieldPayload(payload));
    },
    onSuccess: async () => {
      setMessage("Champ personnalisé créé.");
      setError(null);
      resetCustomFieldForm(customScope);
      await queryClient.invalidateQueries({ queryKey: ["admin-custom-fields", customScope] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de créer le champ personnalisé.");
    }
  });

  const updateCustomField = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: CustomFieldFormState }) => {
      await api.patch(`/admin/custom-fields/${id}`, buildCustomFieldPayload(payload));
    },
    onSuccess: async () => {
      setMessage("Champ personnalisé mis à jour.");
      setError(null);
      resetCustomFieldForm(customScope);
      await queryClient.invalidateQueries({ queryKey: ["admin-custom-fields", customScope] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de mettre à jour le champ personnalisé.");
    }
  });

  const deleteCustomField = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/admin/custom-fields/${id}`);
    },
    onSuccess: async () => {
      setMessage("Champ personnalisé désactivé.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-custom-fields", customScope] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible de désactiver le champ personnalisé.");
    }
  });

  const handleVehicleTypeSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    if (editingVehicleTypeId) {
      updateVehicleType.mutate({ id: editingVehicleTypeId, payload: vehicleTypeForm });
    } else {
      createVehicleType.mutate(vehicleTypeForm);
    }
  };

  const handleCustomFieldSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    if (editingCustomFieldId) {
      updateCustomField.mutate({ id: editingCustomFieldId, payload: customFieldForm });
    } else {
      createCustomField.mutate(customFieldForm);
    }
  };

  const sortedCustomFields = useMemo(
    () => customFields.sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label)),
    [customFields]
  );

  const handlePersistLogsToggle = (enabled: boolean) => {
    setPersistLogsEnabled(enabled);
    setLogPersistenceEnabled(enabled);
    setLogMessage(
      enabled ? "Persistance des logs activée." : "Persistance des logs désactivée."
    );
  };

  const handleExportLogs = () => {
    const entries = getPersistedLogs();
    if (entries.length === 0) {
      setLogMessage("Aucun log à exporter.");
      return;
    }
    const payload = {
      exported_at: new Date().toISOString(),
      entries
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json"
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `frontend-logs-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setLogMessage("Export des logs terminé.");
  };

  const handleClearLogs = () => {
    clearPersistedLogs();
    setLogMessage("Logs frontend supprimés.");
  };

  const updateSiteSelection = useMutation({
    mutationFn: async (siteKey: string | null) => updateActiveSite(siteKey),
    onSuccess: async (data) => {
      setSiteMessage("Base de données active mise à jour.");
      setSiteError(null);
      if (data.active_site_key !== (siteContext?.active_site_key ?? null)) {
        queryClient.clear();
      }
      await queryClient.invalidateQueries({ queryKey: ["site-context"] });
      queryClient.setQueryData(["site-context"], data);
    },
    onError: () => {
      setSiteError("Impossible de mettre à jour la base de données active.");
    }
  });

  const updateSmtpSettings = useMutation({
    mutationFn: async (payload: SmtpFormState) => {
      const response = await api.put<SmtpSettingsResponse>("/admin/email/smtp-settings", {
        host: payload.host.trim() || null,
        port: payload.port,
        username: payload.username.trim() || null,
        from_email: payload.from_email.trim(),
        use_tls: payload.use_tls,
        use_ssl: payload.use_ssl,
        timeout_seconds: payload.timeout_seconds,
        dev_sink: payload.dev_sink,
        password: payload.password.trim() ? payload.password : null,
        clear_password: payload.clearPassword
      });
      return response.data;
    },
    onSuccess: async (data) => {
      setSmtpMessage("Paramètres SMTP mis à jour.");
      setSmtpError(null);
      setSmtpPasswordSet(data.smtp_password_set);
      setSmtpForm((prev) => ({ ...prev, password: "", clearPassword: false }));
      await queryClient.invalidateQueries({ queryKey: ["admin-smtp-settings"] });
    },
    onError: () => {
      setSmtpMessage(null);
      setSmtpError("Impossible d'enregistrer la configuration SMTP.");
    }
  });

  const testSmtpSettings = useMutation({
    mutationFn: async (toEmail: string) => {
      const response = await api.post<{ status: string }>("/admin/email/smtp-test", {
        to_email: toEmail.trim()
      });
      return response.data;
    },
    onSuccess: (data) => {
      const status = data.status === "skipped" ? "Test ignoré (dev sink activé)." : "E-mail de test envoyé.";
      setSmtpTestMessage(status);
      setSmtpTestError(null);
    },
    onError: () => {
      setSmtpTestMessage(null);
      setSmtpTestError("Échec de l'envoi de l'e-mail de test.");
    }
  });

  const updateOtpSettings = useMutation({
    mutationFn: async (payload: OtpEmailSettingsPayload) => {
      await api.put("/admin/email/otp-settings", payload);
    },
    onSuccess: async () => {
      setOtpMessage("Paramètres OTP e-mail mis à jour.");
      setOtpError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-otp-email-settings"] });
    },
    onError: () => {
      setOtpMessage(null);
      setOtpError("Impossible d'enregistrer les paramètres OTP e-mail.");
    }
  });

  if (!isAdmin) {
    return (
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold text-white">Paramètres</h2>
        <p className="text-sm text-red-400">Accès réservé aux administrateurs.</p>
      </section>
    );
  }

  const content = (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">Paramètres avancés</h2>
        <p className="text-sm text-slate-400">
          Centralisez les types de véhicules et les champs personnalisés configurables.
        </p>
      </header>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setActiveTab("vehicle-types")}
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            activeTab === "vehicle-types"
              ? "bg-indigo-500 text-white"
              : "border border-slate-700 text-slate-300 hover:border-indigo-400"
          }`}
        >
          Types de véhicules
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("custom-fields")}
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            activeTab === "custom-fields"
              ? "bg-indigo-500 text-white"
              : "border border-slate-700 text-slate-300 hover:border-indigo-400"
          }`}
        >
          Champs personnalisés
        </button>
      </div>

      {message ? (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-200">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {logMessage ? (
        <div className="rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200">
          {logMessage}
        </div>
      ) : null}

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-white">E-mail (SMTP)</h3>
            <p className="text-xs text-slate-400">
              Configurez l'envoi SMTP utilisé pour les notifications et OTP e-mail.
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              smtpPasswordSet ? "bg-emerald-500/20 text-emerald-200" : "bg-slate-800 text-slate-300"
            }`}
          >
            Mot de passe {smtpPasswordSet ? "configuré ✅" : "non configuré ❌"}
          </span>
        </div>
        {smtpMessage ? (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            {smtpMessage}
          </div>
        ) : null}
        {smtpError ? (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {smtpError}
          </div>
        ) : null}
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            setSmtpMessage(null);
            setSmtpError(null);
            updateSmtpSettings.mutate(smtpForm);
          }}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-xs text-slate-300">
              Hôte
              <span
                title="Requis si le dev sink est désactivé."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                value={smtpForm.host}
                onChange={(event) => setSmtpForm((prev) => ({ ...prev, host: event.target.value }))}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Port
              <AppTextInput
                type="number"
                min={1}
                max={65535}
                value={smtpForm.port}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, port: Number(event.target.value) }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Utilisateur
              <AppTextInput
                value={smtpForm.username}
                onChange={(event) => setSmtpForm((prev) => ({ ...prev, username: event.target.value }))}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Mot de passe
              <AppTextInput
                type="password"
                value={smtpForm.password}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, password: event.target.value }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              From Email
              <span
                title="Format recommandé : Nom <email@domaine>."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                value={smtpForm.from_email}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, from_email: event.target.value }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Timeout (s)
              <AppTextInput
                type="number"
                min={1}
                max={120}
                value={smtpForm.timeout_seconds}
                onChange={(event) =>
                  setSmtpForm((prev) => ({
                    ...prev,
                    timeout_seconds: Number(event.target.value)
                  }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-4 text-xs text-slate-300">
            <label className="flex items-center gap-2">
              <AppTextInput
                type="checkbox"
                checked={smtpForm.use_tls}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, use_tls: event.target.checked }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              TLS
              <span
                title="Active StartTLS sur SMTP classique."
                className="text-[11px] text-slate-500"
              >
                ⓘ
              </span>
            </label>
            <label className="flex items-center gap-2">
              <AppTextInput
                type="checkbox"
                checked={smtpForm.use_ssl}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, use_ssl: event.target.checked }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              SSL
              <span
                title="Utilise SMTP via SSL (port 465 typiquement)."
                className="text-[11px] text-slate-500"
              >
                ⓘ
              </span>
            </label>
            <label className="flex items-center gap-2">
              <AppTextInput
                type="checkbox"
                checked={smtpForm.dev_sink}
                onChange={(event) =>
                  setSmtpForm((prev) => ({ ...prev, dev_sink: event.target.checked }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              Dev sink
              <span
                title="Redirige les e-mails vers un fichier local de debug."
                className="text-[11px] text-slate-500"
              >
                ⓘ
              </span>
            </label>
            <label className="flex items-center gap-2">
              <AppTextInput
                type="checkbox"
                checked={smtpForm.clearPassword}
                onChange={(event) =>
                  setSmtpForm((prev) => ({
                    ...prev,
                    clearPassword: event.target.checked,
                    password: event.target.checked ? "" : prev.password
                  }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              Effacer le mot de passe enregistré
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
              disabled={updateSmtpSettings.isPending}
            >
              Enregistrer
            </button>
          </div>
          <div className="grid gap-3 md:grid-cols-[2fr_1fr] items-end">
            <label className="text-xs text-slate-300">
              Adresse de test
              <AppTextInput
                value={smtpTestEmail}
                onChange={(event) => setSmtpTestEmail(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setSmtpTestMessage(null);
                setSmtpTestError(null);
                if (smtpTestEmail.trim()) {
                  testSmtpSettings.mutate(smtpTestEmail);
                } else {
                  setSmtpTestError("Adresse e-mail de test requise.");
                }
              }}
              className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-indigo-400"
              disabled={testSmtpSettings.isPending}
            >
              Tester l'envoi
            </button>
          </div>
          {smtpTestMessage ? (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              {smtpTestMessage}
            </div>
          ) : null}
          {smtpTestError ? (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              {smtpTestError}
            </div>
          ) : null}
        </form>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-white">OTP e-mail</h3>
          <p className="text-xs text-slate-400">
            Ajustez la durée de validité et les limitations des codes OTP envoyés par e-mail.
          </p>
        </div>
        {otpMessage ? (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            {otpMessage}
          </div>
        ) : null}
        {otpError ? (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {otpError}
          </div>
        ) : null}
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            setOtpMessage(null);
            setOtpError(null);
            updateOtpSettings.mutate(otpForm);
          }}
        >
          <div className="grid gap-4 md:grid-cols-3">
            <label className="text-xs text-slate-300">
              TTL (minutes)
              <span
                title="Durée de validité du code (3-60 minutes)."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                type="number"
                min={3}
                max={60}
                value={otpForm.ttl_minutes}
                onChange={(event) =>
                  setOtpForm((prev) => ({ ...prev, ttl_minutes: Number(event.target.value) }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Longueur du code
              <span
                title="Longueur recommandée : 6 (4-10 autorisé)."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                type="number"
                min={4}
                max={10}
                value={otpForm.code_length}
                onChange={(event) =>
                  setOtpForm((prev) => ({ ...prev, code_length: Number(event.target.value) }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Tentatives max
              <span
                title="Nombre d'essais autorisés (3-10)."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                type="number"
                min={3}
                max={10}
                value={otpForm.max_attempts}
                onChange={(event) =>
                  setOtpForm((prev) => ({ ...prev, max_attempts: Number(event.target.value) }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Cooldown resend (s)
              <span
                title="Délai minimum entre deux envois (10-300s)."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                type="number"
                min={10}
                max={300}
                value={otpForm.resend_cooldown_seconds}
                onChange={(event) =>
                  setOtpForm((prev) => ({
                    ...prev,
                    resend_cooldown_seconds: Number(event.target.value)
                  }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300">
              Rate limit /h
              <span
                title="Nombre max d'envois par heure (1-60)."
                className="ml-1 text-[11px] text-slate-500"
              >
                ⓘ
              </span>
              <AppTextInput
                type="number"
                min={1}
                max={60}
                value={otpForm.rate_limit_per_hour}
                onChange={(event) =>
                  setOtpForm((prev) => ({
                    ...prev,
                    rate_limit_per_hour: Number(event.target.value)
                  }))
                }
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
              />
            </label>
            <label className="text-xs text-slate-300 flex items-center gap-2">
              <AppTextInput
                type="checkbox"
                checked={otpForm.allow_insecure_dev}
                onChange={(event) =>
                  setOtpForm((prev) => ({ ...prev, allow_insecure_dev: event.target.checked }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              Autoriser le code dev
              <span
                title="Expose le code OTP dans la réponse (dev uniquement)."
                className="text-[11px] text-slate-500"
              >
                ⓘ
              </span>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
              disabled={updateOtpSettings.isPending}
            >
              Enregistrer
            </button>
          </div>
        </form>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-white">Journalisation frontend</h3>
          <p className="text-xs text-slate-400">
            Activez la persistance locale des logs navigateur (limite 3 000 Ko).
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <AppTextInput
            type="checkbox"
            checked={persistLogsEnabled}
            onChange={(event) => handlePersistLogsToggle(event.target.checked)}
            className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
          />
          Conserver les logs frontend en localStorage
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleExportLogs}
            className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-indigo-400"
          >
            Exporter les logs
          </button>
          <button
            type="button"
            onClick={handleClearLogs}
            className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-red-400"
          >
            Effacer les logs
          </button>
        </div>
      </div>

      {activeTab === "vehicle-types" ? (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-white">Liste des types</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-2 py-2">Code</th>
                    <th className="px-2 py-2">Libellé</th>
                    <th className="px-2 py-2">Actif</th>
                    <th className="px-2 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {vehicleTypes.map((entry) => (
                    <tr key={entry.id} className="border-b border-slate-800">
                      <td className="px-2 py-2">{entry.code}</td>
                      <td className="px-2 py-2">{entry.label}</td>
                      <td className="px-2 py-2">
                        {entry.is_active ? "Oui" : "Non"}
                      </td>
                      <td className="px-2 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingVehicleTypeId(entry.id);
                            setVehicleTypeForm({
                              code: entry.code,
                              label: entry.label,
                              is_active: entry.is_active
                            });
                          }}
                          className="text-indigo-300 hover:text-indigo-200"
                        >
                          Modifier
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteVehicleType.mutate(entry.id)}
                          className="ml-3 text-red-300 hover:text-red-200"
                        >
                          Désactiver
                        </button>
                      </td>
                    </tr>
                  ))}
                  {vehicleTypes.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-2 py-4 text-center text-slate-500">
                        Aucun type configuré.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <form
            className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-3"
            onSubmit={handleVehicleTypeSubmit}
          >
            <h3 className="text-sm font-semibold text-white">
              {editingVehicleTypeId ? "Modifier un type" : "Ajouter un type"}
            </h3>
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-300">Code</span>
              <AppTextInput
                value={vehicleTypeForm.code}
                onChange={(event) => setVehicleTypeForm((prev) => ({ ...prev, code: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-300">Libellé</span>
              <AppTextInput
                value={vehicleTypeForm.label}
                onChange={(event) => setVehicleTypeForm((prev) => ({ ...prev, label: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <AppTextInput
                type="checkbox"
                checked={vehicleTypeForm.is_active}
                onChange={(event) => setVehicleTypeForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
              />
              Actif
            </label>
            <div className="flex gap-2">
              <button
                type="submit"
                className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
              >
                {editingVehicleTypeId ? "Mettre à jour" : "Créer"}
              </button>
              {editingVehicleTypeId ? (
                <button
                  type="button"
                  onClick={resetVehicleTypeForm}
                  className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300"
                >
                  Annuler
                </button>
              ) : null}
            </div>
          </form>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap gap-2">
            {Object.entries(CUSTOM_FIELD_SCOPES).map(([scope, label]) => (
              <button
                key={scope}
                type="button"
                onClick={() => {
                  setCustomScope(scope);
                  resetCustomFieldForm(scope);
                }}
                className={`rounded-full px-3 py-2 text-xs font-semibold ${
                  customScope === scope
                    ? "bg-indigo-500 text-white"
                    : "border border-slate-700 text-slate-300 hover:border-indigo-400"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <h3 className="text-sm font-semibold text-white">Champs configurés</h3>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead>
                    <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="px-2 py-2">Clé</th>
                      <th className="px-2 py-2">Libellé</th>
                      <th className="px-2 py-2">Type</th>
                      <th className="px-2 py-2">Actif</th>
                      <th className="px-2 py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedCustomFields.map((field) => (
                      <tr key={field.id} className="border-b border-slate-800">
                        <td className="px-2 py-2">{field.key}</td>
                        <td className="px-2 py-2">{field.label}</td>
                        <td className="px-2 py-2">{field.field_type}</td>
                        <td className="px-2 py-2">{field.is_active ? "Oui" : "Non"}</td>
                        <td className="px-2 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => {
                              setEditingCustomFieldId(field.id);
                              setCustomFieldForm({
                                scope: field.scope,
                                key: field.key,
                                label: field.label,
                                field_type: field.field_type,
                                required: field.required,
                                defaultValue: field.default_json ? JSON.stringify(field.default_json) : "",
                                options: Array.isArray(field.options_json)
                                  ? field.options_json.join(", ")
                                  : "",
                                is_active: field.is_active,
                                sort_order: field.sort_order
                              });
                            }}
                            className="text-indigo-300 hover:text-indigo-200"
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteCustomField.mutate(field.id)}
                            className="ml-3 text-red-300 hover:text-red-200"
                          >
                            Désactiver
                          </button>
                        </td>
                      </tr>
                    ))}
                    {sortedCustomFields.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-2 py-4 text-center text-slate-500">
                          Aucun champ défini.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <form
              className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-3"
              onSubmit={handleCustomFieldSubmit}
            >
              <h3 className="text-sm font-semibold text-white">
                {editingCustomFieldId ? "Modifier le champ" : "Ajouter un champ"}
              </h3>
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-300">Clé</span>
                <AppTextInput
                  value={customFieldForm.key}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, key: event.target.value }))}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-300">Libellé</span>
                <AppTextInput
                  value={customFieldForm.label}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, label: event.target.value }))}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-300">Type</span>
                <select
                  value={customFieldForm.field_type}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, field_type: event.target.value }))}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                >
                  {CUSTOM_FIELD_TYPES.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <AppTextInput
                  type="checkbox"
                  checked={customFieldForm.required}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, required: event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
                />
                Obligatoire
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-300">Valeur par défaut</span>
                <AppTextInput
                  value={customFieldForm.defaultValue}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, defaultValue: event.target.value }))}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  placeholder="Optionnel"
                />
              </label>
              {customFieldForm.field_type === "select" ? (
                <label className="block space-y-1">
                  <span className="text-xs font-semibold text-slate-300">Options (séparées par des virgules)</span>
                  <AppTextInput
                    value={customFieldForm.options}
                    onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, options: event.target.value }))}
                    className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  />
                </label>
              ) : null}
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-slate-300">Ordre</span>
                <AppTextInput
                  type="number"
                  value={customFieldForm.sort_order}
                  onChange={(event) =>
                    setCustomFieldForm((prev) => ({ ...prev, sort_order: Number(event.target.value) }))
                  }
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                />
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <AppTextInput
                  type="checkbox"
                  checked={customFieldForm.is_active}
                  onChange={(event) => setCustomFieldForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
                />
                Actif
              </label>
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                >
                  {editingCustomFieldId ? "Mettre à jour" : "Créer"}
                </button>
                {editingCustomFieldId ? (
                  <button
                    type="button"
                    onClick={() => resetCustomFieldForm(customScope)}
                    className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300"
                  >
                    Annuler
                  </button>
                ) : null}
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );

  const databaseSection = (
    <section className="space-y-4">
      <header className="space-y-1">
        <h3 className="text-lg font-semibold text-white">Base de Données</h3>
        <p className="text-sm text-slate-400">
          Gérer la base active pour les sites disponibles.
        </p>
      </header>
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">Site assigné</p>
            <p>{siteContext?.assigned_site_key ?? "JLL"}</p>
          </div>
          <div className="space-y-1 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">Site actif</p>
            <p>{siteContext?.active_site_key ?? "JLL"}</p>
          </div>
        </div>
        <label className="block space-y-1 text-xs text-slate-300">
          <span className="font-semibold text-slate-200">Forcer un site</span>
          <select
            value={selectedSite}
            onChange={(event) => setSelectedSite(event.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
          >
            <option value="">Aucun (site assigné)</option>
            {(siteContext?.sites ?? []).map((site) => (
              <option key={site.site_key} value={site.site_key}>
                {site.display_name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => updateSiteSelection.mutate(selectedSite || null)}
            className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
            disabled={updateSiteSelection.isPending}
          >
            Appliquer
          </button>
          <button
            type="button"
            onClick={() => updateSiteSelection.mutate(null)}
            className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300"
            disabled={updateSiteSelection.isPending}
          >
            Réinitialiser
          </button>
        </div>
        {siteMessage ? (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            {siteMessage}
          </div>
        ) : null}
        {siteError ? (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {siteError}
          </div>
        ) : null}
        {siteContext?.sites?.length ? (
          <div className="rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-400">
            {siteContext.sites.map((site) => `${site.site_key} → ${site.db_path}`).join(" • ")}
          </div>
        ) : null}
      </div>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "admin-settings-main",
      title: "Paramètres administrateur",
      required: true,
      permissions: ["admin"],
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      variant: "plain",
      render: () => (
        <EditableBlock id="admin-settings-main">
          {content}
        </EditableBlock>
      )
    },
    {
      id: "admin-db-settings",
      title: "Base de Données",
      required: true,
      permissions: ["admin"],
      defaultLayout: {
        lg: { x: 0, y: 24, w: 12, h: 12 },
        md: { x: 0, y: 24, w: 10, h: 12 },
        sm: { x: 0, y: 24, w: 6, h: 12 },
        xs: { x: 0, y: 24, w: 4, h: 12 }
      },
      variant: "plain",
      render: () => (
        <EditableBlock id="admin-db-settings">
          {databaseSection}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout pageKey="admin:settings" blocks={blocks} className="space-y-6" />
  );
}

function buildCustomFieldPayload(payload: CustomFieldFormState) {
  let defaultValue: unknown = null;
  if (payload.defaultValue.trim()) {
    if (payload.field_type === "number") {
      defaultValue = Number(payload.defaultValue);
    } else if (payload.field_type === "bool") {
      defaultValue = payload.defaultValue.trim().toLowerCase() === "true";
    } else {
      defaultValue = payload.defaultValue;
    }
  }
  const options =
    payload.field_type === "select"
      ? payload.options
          .split(",")
          .map((option) => option.trim())
          .filter(Boolean)
      : undefined;
  return {
    scope: payload.scope,
    key: payload.key.trim(),
    label: payload.label.trim(),
    field_type: payload.field_type,
    required: payload.required,
    default_json: defaultValue,
    options_json: options,
    is_active: payload.is_active,
    sort_order: payload.sort_order
  };
}
