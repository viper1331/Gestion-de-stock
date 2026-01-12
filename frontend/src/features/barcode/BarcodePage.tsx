import axios from "axios";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditableLayoutSet, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

const DEFAULT_SKU_PLACEHOLDER = "SKU-001";

export function BarcodePage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("barcode");
  const canEdit =
    user?.role === "admin" || modulePermissions.canAccess("barcode", "edit");
  const moduleTitle = useModuleTitle("barcode");

  const [sku, setSku] = useState(DEFAULT_SKU_PLACEHOLDER);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletingSku, setDeletingSku] = useState<string | null>(null);
  const [isExportingPdf, setIsExportingPdf] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gallery, setGallery] = useState<BarcodeVisual[]>([]);
  const [isGalleryLoading, setIsGalleryLoading] = useState(false);
  const [galleryError, setGalleryError] = useState<string | null>(null);
  const [knownBarcodes, setKnownBarcodes] = useState<ExistingBarcodeValue[]>([]);
  const [isKnownBarcodesLoading, setIsKnownBarcodesLoading] = useState(false);
  const [knownBarcodesError, setKnownBarcodesError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      gallery.forEach((entry) => {
        URL.revokeObjectURL(entry.imageUrl);
      });
    };
  }, [gallery]);

  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

  const refreshKnownBarcodes = useCallback(async () => {
    if (!canView || !isMountedRef.current) {
      return;
    }

    setIsKnownBarcodesLoading(true);
    setKnownBarcodesError(null);

    try {
      const response = await api.get<ExistingBarcodeValue[]>("/barcode/existing");
      if (!isMountedRef.current) {
        return;
      }
      const entries = response.data;
      setKnownBarcodes(entries);
      if (entries.length > 0) {
        setSku((previous) => {
          if (
            previous &&
            previous.trim().length > 0 &&
            previous !== DEFAULT_SKU_PLACEHOLDER
          ) {
            return previous;
          }
          return entries[0].sku;
        });
      }
    } catch (err) {
      if (!isMountedRef.current) {
        return;
      }
      setKnownBarcodes([]);
      setKnownBarcodesError("Impossible de charger les codes-barres existants.");
    } finally {
      if (isMountedRef.current) {
        setIsKnownBarcodesLoading(false);
      }
    }
  }, [canView]);

  const refreshGallery = useCallback(async () => {
    if (!canView || !isMountedRef.current) {
      return;
    }

    setIsGalleryLoading(true);
    setGalleryError(null);

    try {
      const response = await api.get<BarcodeSummary[]>("/barcode");
      const entries = response.data;
      const visuals = await Promise.all(
        entries.map(async (entry) => {
          try {
            const assetResponse = await api.get(`/barcode/assets/${encodeURIComponent(entry.filename)}`, {
              responseType: "blob"
            });
            if (!isMountedRef.current) {
              return null;
            }
            const objectUrl = URL.createObjectURL(assetResponse.data);
            return {
              sku: entry.sku,
              filename: entry.filename,
              modifiedAt: entry.modified_at,
              imageUrl: objectUrl
            } as BarcodeVisual;
          } catch (assetError) {
            console.error("Impossible de charger le fichier de code-barres", assetError);
            return null;
          }
        })
      );

      if (!isMountedRef.current) {
        visuals.forEach((entry) => {
          if (entry) {
            URL.revokeObjectURL(entry.imageUrl);
          }
        });
        return;
      }

      const successful = visuals.filter((entry): entry is BarcodeVisual => entry !== null);
      setGallery(successful);
      if (successful.length !== entries.length) {
        setGalleryError("Certains fichiers de code-barres n'ont pas pu être chargés.");
      }
    } catch (err) {
      if (!isMountedRef.current) {
        return;
      }
      setGallery([]);
      setGalleryError("Impossible de récupérer la liste des codes-barres.");
    } finally {
      if (isMountedRef.current) {
        setIsGalleryLoading(false);
      }
    }
  }, [canView]);

  useEffect(() => {
    if (canView) {
      void refreshKnownBarcodes();
      void refreshGallery();
    }
  }, [canView, refreshGallery, refreshKnownBarcodes]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canEdit) {
      return;
    }
    setIsGenerating(true);
    setMessage(null);
    setError(null);
    try {
      const response = await api.post(`/barcode/generate/${sku}`, undefined, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
      setImageUrl(url);
      setMessage("Code-barres généré.");
      void refreshGallery();
      void refreshKnownBarcodes();
    } catch (err) {
      setError("Impossible de générer le code-barres.");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDelete = async () => {
    if (!canEdit) {
      return;
    }
    setIsDeleting(true);
    setMessage(null);
    setError(null);
    try {
      await api.delete(`/barcode/generate/${sku}`);
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
      setImageUrl(null);
      setMessage("Code-barres supprimé.");
      void refreshGallery();
      void refreshKnownBarcodes();
    } catch (err) {
      setError("Impossible de supprimer le fichier généré.");
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeleteVisual = useCallback(
    async (targetSku: string) => {
      if (!canEdit) {
        return;
      }

      setDeletingSku(targetSku);
      setMessage(null);
      setError(null);

      try {
        await api.delete(`/barcode/generate/${targetSku}`);

        if (sku === targetSku && imageUrl) {
          URL.revokeObjectURL(imageUrl);
          setImageUrl(null);
        }

        setMessage("Code-barres supprimé.");
        void refreshGallery();
        void refreshKnownBarcodes();
      } catch (err) {
        setError("Impossible de supprimer le fichier généré.");
      } finally {
        setDeletingSku(null);
      }
    },
    [canEdit, imageUrl, refreshGallery, refreshKnownBarcodes, sku]
  );

  const handleExportPdf = async () => {
    if (!canView || isExportingPdf) {
      return;
    }
    setIsExportingPdf(true);
    setMessage(null);
    setError(null);
    try {
      const response = await api.get(`/barcode/export/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = "codes-barres.pdf";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setMessage("Export PDF téléchargé.");
      window.setTimeout(() => {
        URL.revokeObjectURL(blobUrl);
      }, 500);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        setError("Aucun code-barres disponible pour l'export.");
      } else {
        setError("Impossible de générer le PDF.");
      }
    } finally {
      setIsExportingPdf(false);
    }
  };

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const content = (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
        <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
      </header>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm text-slate-300">
          SKU
          <AppTextInput
            value={sku}
            onChange={(event) => setSku(event.target.value)}
            list="known-barcode-options"
            className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Identifiant de l'article pour générer le code-barres"
          />
        </label>
        <button
          type="submit"
          disabled={isGenerating || !canEdit}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Lancer la génération du code-barres"
        >
          {isGenerating ? "Génération..." : "Générer"}
        </button>
        {imageUrl ? (
          <button
            type="button"
            onClick={handleDelete}
            disabled={isDeleting || !canEdit}
            className="rounded-md bg-red-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-70"
            title="Supprimer le fichier généré sur le serveur"
          >
            {isDeleting ? "Suppression..." : "Supprimer"}
          </button>
        ) : null}
      </form>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      {isKnownBarcodesLoading ? (
        <p className="text-sm text-slate-400">Chargement des codes-barres existants...</p>
      ) : null}
      {knownBarcodesError ? (
        <p className="text-sm text-yellow-300">{knownBarcodesError}</p>
      ) : null}
      {knownBarcodes.length ? (
        <p className="text-xs text-slate-400">
          Sélectionnez un code-barres existant dans la liste ou saisissez-en un nouveau.
        </p>
      ) : null}
      <datalist id="known-barcode-options">
        {knownBarcodes.map((entry) => (
          <option key={entry.sku} value={entry.sku} />
        ))}
      </datalist>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleExportPdf}
          disabled={isExportingPdf}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
          title="Exporter les codes-barres au format PDF A4"
        >
          {isExportingPdf ? "Export en cours..." : "Exporter en PDF A4"}
        </button>
      </div>
      {imageUrl ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-6">
          <img src={imageUrl} alt={`Barcode ${sku}`} className="mx-auto" />
          <div className="mt-4 flex justify-center gap-3 text-sm">
            <a
              href={imageUrl}
              download={`${sku}.png`}
              className="rounded-md bg-slate-800 px-4 py-2 text-slate-200 hover:bg-slate-700"
              title="Télécharger le fichier PNG du code-barres"
            >
              Télécharger
            </a>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(sku)}
              className="rounded-md bg-slate-800 px-4 py-2 text-slate-200 hover:bg-slate-700"
              title="Copier la valeur du SKU dans le presse-papiers"
            >
              Copier le SKU
            </button>
          </div>
        </div>
      ) : null}
      <section className="space-y-3">
        <header className="space-y-1">
          <h3 className="text-xl font-semibold text-white">Codes-barres générés</h3>
          <p className="text-sm text-slate-400">
            Accédez rapidement aux visuels déjà créés pour vos articles.
          </p>
        </header>
        {isGalleryLoading ? <p className="text-sm text-slate-400">Chargement des visuels...</p> : null}
        {galleryError ? <p className="text-sm text-yellow-300">{galleryError}</p> : null}
        {!isGalleryLoading && !gallery.length ? (
          <p className="text-sm text-slate-400">Aucun code-barres généré pour le moment.</p>
        ) : null}
        {gallery.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {gallery.map((entry) => (
              <figure
                key={entry.filename}
                className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4 shadow"
              >
                <img src={entry.imageUrl} alt={`Code-barres ${entry.sku}`} className="mx-auto max-h-48 object-contain" />
                <figcaption className="space-y-1 text-center text-sm text-slate-300">
                  <div className="font-semibold text-white">{entry.sku}</div>
                  <div className="text-xs text-slate-400">{formatTimestamp(entry.modifiedAt)}</div>
                  <div className="flex justify-center gap-2 text-xs">
                    <a
                      href={entry.imageUrl}
                      download={entry.filename}
                      className="rounded-md bg-slate-800 px-3 py-1 text-slate-200 hover:bg-slate-700"
                    >
                      Télécharger
                    </a>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(entry.sku)}
                      className="rounded-md bg-slate-800 px-3 py-1 text-slate-200 hover:bg-slate-700"
                    >
                      Copier le SKU
                    </button>
                    {canEdit ? (
                      <button
                        type="button"
                        onClick={() => void handleDeleteVisual(entry.sku)}
                        disabled={deletingSku === entry.sku}
                        className="rounded-md bg-red-500 px-3 py-1 text-slate-100 shadow hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {deletingSku === entry.sku ? "Suppression..." : "Supprimer"}
                      </button>
                    ) : null}
                  </div>
                </figcaption>
              </figure>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [{ i: "barcode-main", x: 0, y: 0, w: 12, h: 24 }],
      md: [{ i: "barcode-main", x: 0, y: 0, w: 6, h: 24 }],
      sm: [{ i: "barcode-main", x: 0, y: 0, w: 1, h: 24 }],
      xs: [{ i: "barcode-main", x: 0, y: 0, w: 1, h: 24 }]
    }),
    []
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "barcode-main",
      title: "Codes-barres",
      required: true,
      permission: { module: "barcode", action: "view" },
      containerClassName: "rounded-none border-0 bg-transparent p-0",
      render: () => (
        <EditableBlock id="barcode-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:barcode"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      pagePermission={{ module: "barcode", action: "view" }}
      className="space-y-6"
    />
  );
}

type ExistingBarcodeValue = {
  sku: string;
};

type BarcodeSummary = {
  sku: string;
  filename: string;
  modified_at: string;
};

type BarcodeVisual = {
  sku: string;
  filename: string;
  modifiedAt: string;
  imageUrl: string;
};

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleString();
}
