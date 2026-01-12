import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { isAxiosError } from "axios";

import { api } from "../../lib/api";
import { resolveMediaUrl } from "../../lib/media";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

interface VehicleQrInfo {
  item_id: number;
  name: string;
  sku: string;
  category_name: string | null;
  image_url: string | null;
  shared_file_url: string | null;
  documentation_url: string | null;
  tutorial_url: string | null;
}

export function VehicleGuidePage() {
  const { qrToken } = useParams();
  const [info, setInfo] = useState<VehicleQrInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchInfo = async () => {
      try {
        const response = await api.get<VehicleQrInfo>(`/vehicle-inventory/public/${qrToken}`);
        setInfo(response.data);
      } catch (err) {
        let message = "Impossible de charger les informations liées à ce QR code. Le lien a peut-être expiré.";
        if (isAxiosError(err)) {
          const detail = err.response?.data?.detail;
          if (typeof detail === "string" && detail.trim().length > 0) {
            message = detail;
          }
        }
        setError(message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchInfo();
  }, [qrToken]);

  const coverUrl = useMemo(() => resolveMediaUrl(info?.image_url), [info?.image_url]);

  const content = (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 px-4 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl rounded-3xl border border-slate-800/60 bg-slate-900/70 shadow-2xl backdrop-blur">
        <div className="border-b border-slate-800/60 px-6 pb-4 pt-6">
          <p className="text-xs uppercase tracking-[0.2em] text-sky-300/80">Fiche matériel véhicule</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">{info?.name ?? "Accès QR"}</h1>
          {info?.category_name && (
            <p className="text-sm text-slate-300">Rattaché à : {info.category_name}</p>
          )}
        </div>

        <div className="grid gap-8 px-6 py-8 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-4">
            {isLoading ? (
              <p className="text-slate-300">Chargement des informations...</p>
            ) : error ? (
              <p className="rounded-lg bg-rose-900/40 p-4 text-rose-200">{error}</p>
            ) : info ? (
              <>
                <p className="text-sm text-slate-200">
                  Référence interne : <span className="font-semibold">{info.sku}</span>
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  <ResourceCard
                    title="Fichier associé (OneDrive)"
                    description="Accédez directement au fichier partagé pour ce matériel."
                    url={info.shared_file_url}
                  />
                  <ResourceCard
                    title="Documentation technique"
                    description="Consultez les notices, schémas et informations clés pour ce matériel."
                    url={info.documentation_url}
                  />
                  <ResourceCard
                    title="Tutoriel d'utilisation"
                    description="Procédures, vidéos ou guides pas à pas pour manipuler l'équipement."
                    url={info.tutorial_url}
                  />
                </div>
              </>
            ) : null}
          </div>

          <div className="relative overflow-hidden rounded-2xl border border-slate-800/70 bg-slate-950/60 shadow-inner">
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={info?.name ?? "Matériel"}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full min-h-[240px] items-center justify-center bg-slate-900/70">
                <p className="text-sm text-slate-400">Aucune image n'est disponible pour cet équipement.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "vehicle-guide-main",
      title: "Fiche matériel véhicule",
      required: true,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 20 },
        md: { x: 0, y: 0, w: 10, h: 20 },
        sm: { x: 0, y: 0, w: 6, h: 20 },
        xs: { x: 0, y: 0, w: 4, h: 20 }
      },
      render: () => (
        <EditableBlock id="vehicle-guide-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return <EditablePageLayout pageKey="module:vehicle:guide" blocks={blocks} className="space-y-6" />;
}

interface ResourceCardProps {
  title: string;
  description: string;
  url: string | null;
}

function ResourceCard({ title, description, url }: ResourceCardProps) {
  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4 shadow-sm">
      <h2 className="text-base font-semibold text-white">{title}</h2>
      <p className="mt-1 text-sm text-slate-300">{description}</p>
      {url ? (
        <a
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-sky-400"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Ouvrir le lien
          <span aria-hidden>↗</span>
        </a>
      ) : (
        <p className="mt-3 text-xs text-amber-200">Aucun lien n'a été renseigné.</p>
      )}
    </div>
  );
}
