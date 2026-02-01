import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "../../lib/api";
import { DraggableModal } from "../../components/DraggableModal";
import { AppTextInput } from "../../components/AppTextInput";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

type PhysioSource = "manual" | "sensor";

interface AriPhysioPoint {
  bp_sys?: number;
  bp_dia?: number;
  hr?: number;
  spo2?: number;
}

interface AriPhysioInput {
  source: PhysioSource;
  pre?: AriPhysioPoint | null;
  post?: AriPhysioPoint | null;
  device_id?: string | null;
  captured_at?: string | null;
}

interface AriSession {
  id: number;
  performed_at: string;
  created_at: string;
  created_by: string;
  physio?: AriPhysioInput | null;
}

interface AriSessionCreatePayload {
  performed_at?: string;
  physio?: {
    source: PhysioSource;
    pre?: AriPhysioPoint;
    post?: AriPhysioPoint;
    device_id?: string | null;
  };
}

const parseOptionalInt = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) {
    return undefined;
  }
  return Math.trunc(parsed);
};

const buildPoint = (values: {
  bp_sys: string;
  bp_dia: string;
  hr: string;
  spo2: string;
}) => {
  const point = {
    bp_sys: parseOptionalInt(values.bp_sys),
    bp_dia: parseOptionalInt(values.bp_dia),
    hr: parseOptionalInt(values.hr),
    spo2: parseOptionalInt(values.spo2)
  };
  if (Object.values(point).every((entry) => entry === undefined)) {
    return undefined;
  }
  return point;
};

const formatPhysioSummary = (physio?: AriPhysioInput | null) => {
  if (!physio) {
    return "—";
  }
  const pre = physio.pre ?? {};
  const post = physio.post ?? {};
  const summaryParts = [];
  if (pre.hr !== undefined || post.hr !== undefined) {
    summaryParts.push(`HR ${pre.hr ?? "—"}→${post.hr ?? "—"}`);
  }
  if (pre.spo2 !== undefined || post.spo2 !== undefined) {
    summaryParts.push(`SpO2 ${pre.spo2 ?? "—"}→${post.spo2 ?? "—"}`);
  }
  if (
    pre.bp_sys !== undefined ||
    post.bp_sys !== undefined ||
    pre.bp_dia !== undefined ||
    post.bp_dia !== undefined
  ) {
    const preValue = `${pre.bp_sys ?? "—"}/${pre.bp_dia ?? "—"}`;
    const postValue = `${post.bp_sys ?? "—"}/${post.bp_dia ?? "—"}`;
    summaryParts.push(`TA ${preValue}→${postValue}`);
  }
  return summaryParts.length ? summaryParts.join(" | ") : "—";
};

const formatPhysioTooltip = (physio?: AriPhysioInput | null) => {
  if (!physio) {
    return "Aucune donnée physiologique.";
  }
  const pre = physio.pre ?? {};
  const post = physio.post ?? {};
  return [
    `Source: ${physio.source === "manual" ? "Manuel" : "Capteur"}`,
    physio.device_id ? `Capteur: ${physio.device_id}` : null,
    `TA avant: ${pre.bp_sys ?? "—"}/${pre.bp_dia ?? "—"}`,
    `TA après: ${post.bp_sys ?? "—"}/${post.bp_dia ?? "—"}`,
    `HR avant: ${pre.hr ?? "—"} bpm`,
    `HR après: ${post.hr ?? "—"} bpm`,
    `SpO2 avant: ${pre.spo2 ?? "—"} %`,
    `SpO2 après: ${post.spo2 ?? "—"} %`
  ]
    .filter(Boolean)
    .join("\n");
};

export function AriSessionsPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("ari");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("ari", "edit");
  const queryClient = useQueryClient();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [physioSource, setPhysioSource] = useState<PhysioSource>("manual");
  const [deviceId, setDeviceId] = useState("");
  const [allowManualWithSensor, setAllowManualWithSensor] = useState(false);
  const [includePre, setIncludePre] = useState(false);
  const [includePost, setIncludePost] = useState(false);
  const [preValues, setPreValues] = useState({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
  const [postValues, setPostValues] = useState({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ["ari", "sessions"],
    queryFn: async () => {
      const response = await api.get<AriSession[]>("/ari/sessions");
      return response.data;
    },
    enabled: canView
  });

  const createSession = useMutation({
    mutationFn: async (payload: AriSessionCreatePayload) => {
      const response = await api.post<AriSession>("/ari/sessions", payload);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Séance ARI créée.");
      setIsModalOpen(false);
      setPhysioSource("manual");
      setDeviceId("");
      setAllowManualWithSensor(false);
      setIncludePre(false);
      setIncludePost(false);
      setPreValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
      setPostValues({ bp_sys: "", bp_dia: "", hr: "", spo2: "" });
      queryClient.invalidateQueries({ queryKey: ["ari", "sessions"] });
    },
    onError: () => {
      toast.error("Impossible de créer la séance.");
    }
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit) {
      return;
    }
    const manualEnabled = physioSource === "manual" || allowManualWithSensor;
    const prePoint = manualEnabled && includePre ? buildPoint(preValues) : undefined;
    const postPoint = manualEnabled && includePost ? buildPoint(postValues) : undefined;

    const payload: AriSessionCreatePayload = {
      performed_at: new Date().toISOString()
    };

    if (physioSource === "sensor" || prePoint || postPoint) {
      payload.physio = {
        source: physioSource,
        pre: prePoint,
        post: postPoint,
        device_id: physioSource === "sensor" && deviceId.trim() ? deviceId.trim() : undefined
      };
    }

    createSession.mutate(payload);
  };

  const handleDownloadPdf = async (sessionId: number) => {
    try {
      const response = await api.get(`/ari/sessions/${sessionId}/export/pdf`, {
        responseType: "blob"
      });
      const blob = new Blob([response.data as BlobPart], { type: "application/pdf" });
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.href = url;
      link.download = `ari_session_${sessionId}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error("Impossible de télécharger le PDF.");
    }
  };

  const manualEntryEnabled = physioSource === "manual" || allowManualWithSensor;
  const tableRows = useMemo(
    () =>
      sessions.map((session) => ({
        ...session,
        physioSummary: formatPhysioSummary(session.physio),
        physioTooltip: formatPhysioTooltip(session.physio)
      })),
    [sessions]
  );

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Sessions ARI</h1>
          <p className="text-sm text-slate-300">
            Renseignez les données physiologiques avant et après chaque séance.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:bg-slate-700"
          onClick={() => setIsModalOpen(true)}
          disabled={!canEdit}
        >
          Créer une séance ARI
        </button>
      </header>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-900/80 text-left text-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold">Date</th>
                <th className="px-4 py-3 font-semibold">Créé par</th>
                <th className="px-4 py-3 font-semibold">Physio</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-100">
              {isLoading ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={4}>
                    Chargement des séances...
                  </td>
                </tr>
              ) : tableRows.length === 0 ? (
                <tr>
                  <td className="px-4 py-4 text-slate-400" colSpan={4}>
                    Aucune séance enregistrée.
                  </td>
                </tr>
              ) : (
                tableRows.map((session) => (
                  <tr key={session.id} className="hover:bg-slate-900/60">
                    <td className="px-4 py-3">{new Date(session.performed_at).toLocaleString()}</td>
                    <td className="px-4 py-3">{session.created_by}</td>
                    <td className="px-4 py-3" title={session.physioTooltip}>
                      {session.physioSummary}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                        onClick={() => handleDownloadPdf(session.id)}
                      >
                        Export PDF
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <DraggableModal
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Créer séance ARI"
        maxWidthClassName="max-w-[min(96vw,900px)]"
        bodyClassName="px-6 py-4"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
            >
              Annuler
            </button>
            <button
              type="submit"
              form="ari-session-form"
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:bg-slate-700"
              disabled={createSession.isPending}
            >
              {createSession.isPending ? "Création..." : "Créer"}
            </button>
          </div>
        }
      >
        <form id="ari-session-form" className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <section className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
            <h2 className="text-sm font-semibold text-slate-100">Physiologie</h2>
            <p className="text-xs text-slate-400">
              Choisissez le mode de saisie pour les mesures physiologiques.
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="radio"
                  name="physio-source"
                  value="manual"
                  checked={physioSource === "manual"}
                  onChange={() => setPhysioSource("manual")}
                />
                Saisie manuelle
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="radio"
                  name="physio-source"
                  value="sensor"
                  checked={physioSource === "sensor"}
                  onChange={() => setPhysioSource("sensor")}
                />
                Capteur (bientôt / beta)
              </label>
            </div>

            {physioSource === "sensor" && (
              <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
                <AppTextInput
                  value={deviceId}
                  onChange={(event) => setDeviceId(event.target.value)}
                  placeholder="Identifiant capteur"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                />
                <button
                  type="button"
                  className="rounded-md border border-dashed border-slate-700 px-3 py-2 text-sm text-slate-400"
                  disabled
                >
                  Importer depuis capteur (coming soon)
                </button>
                <label className="flex items-center gap-2 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={allowManualWithSensor}
                    onChange={(event) => setAllowManualWithSensor(event.target.checked)}
                  />
                  Renseigner manuellement malgré capteur
                </label>
              </div>
            )}

            {manualEntryEnabled && (
              <div className="mt-4 grid gap-4">
                <div className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
                  <label className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                    <input
                      type="checkbox"
                      checked={includePre}
                      onChange={(event) => setIncludePre(event.target.checked)}
                    />
                    Mesures avant session
                  </label>
                  {includePre && (
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <AppTextInput
                        value={preValues.bp_sys}
                        onChange={(event) => setPreValues({ ...preValues, bp_sys: event.target.value })}
                        placeholder="TA systolique"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={preValues.bp_dia}
                        onChange={(event) => setPreValues({ ...preValues, bp_dia: event.target.value })}
                        placeholder="TA diastolique"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={preValues.hr}
                        onChange={(event) => setPreValues({ ...preValues, hr: event.target.value })}
                        placeholder="HR (bpm)"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={preValues.spo2}
                        onChange={(event) => setPreValues({ ...preValues, spo2: event.target.value })}
                        placeholder="SpO2 (%)"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                    </div>
                  )}
                </div>
                <div className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
                  <label className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                    <input
                      type="checkbox"
                      checked={includePost}
                      onChange={(event) => setIncludePost(event.target.checked)}
                    />
                    Mesures après session
                  </label>
                  {includePost && (
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <AppTextInput
                        value={postValues.bp_sys}
                        onChange={(event) => setPostValues({ ...postValues, bp_sys: event.target.value })}
                        placeholder="TA systolique"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={postValues.bp_dia}
                        onChange={(event) => setPostValues({ ...postValues, bp_dia: event.target.value })}
                        placeholder="TA diastolique"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={postValues.hr}
                        onChange={(event) => setPostValues({ ...postValues, hr: event.target.value })}
                        placeholder="HR (bpm)"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                      <AppTextInput
                        value={postValues.spo2}
                        onChange={(event) => setPostValues({ ...postValues, spo2: event.target.value })}
                        placeholder="SpO2 (%)"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      />
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </form>
      </DraggableModal>
    </div>
  );
}
