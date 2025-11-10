import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

export function BarcodePage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("barcode");
  const canEdit =
    user?.role === "admin" || modulePermissions.canAccess("barcode", "edit");

  const [sku, setSku] = useState("SKU-001");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gallery, setGallery] = useState<BarcodeVisual[]>([]);
  const [isGalleryLoading, setIsGalleryLoading] = useState(false);
  const [galleryError, setGalleryError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
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
      void refreshGallery();
    }
  }, [canView, refreshGallery]);

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
    } catch (err) {
      setError("Impossible de supprimer le fichier généré.");
    } finally {
      setIsDeleting(false);
    }
  };

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Codes-barres</h2>
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
          <h2 className="text-2xl font-semibold text-white">Codes-barres</h2>
          <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Codes-barres</h2>
        <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
      </header>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm text-slate-300">
          SKU
          <input
            value={sku}
            onChange={(event) => setSku(event.target.value)}
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
                  </div>
                </figcaption>
              </figure>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}

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
