import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { buildModuleTitleMap, useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";
import { fetchConfigEntries } from "../../lib/config";

const EXCLUDED_MODULE_KEYS = new Set([
  "vehicle_inventory",
  "vehicle-inventory",
  "vehicleInventory"
]);

export function BarcodePage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("barcode");
  const canEdit =
    user?.role === "admin" || modulePermissions.canAccess("barcode", "edit");
  const moduleTitle = useModuleTitle("barcode");
  const { data: configEntries = [] } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries,
    enabled: Boolean(user)
  });
  const moduleTitles = useMemo(() => buildModuleTitleMap(configEntries), [configEntries]);

  const [sku, setSku] = useState("");
  const [moduleFilter, setModuleFilter] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");
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
  const [catalogEntries, setCatalogEntries] = useState<BarcodeCatalogEntry[]>([]);
  const [isCatalogLoading, setIsCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const isMountedRef = useRef(true);
  const lastModuleRef = useRef(moduleFilter);

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

  const refreshCatalog = useCallback(
    async (nextModule: string, nextQuery: string) => {
      if (!canView || !isMountedRef.current) {
        return;
      }

      setIsCatalogLoading(true);
      setCatalogError(null);
      const wasModuleChanged = lastModuleRef.current !== nextModule;

      try {
        const response = await api.get<BarcodeCatalogEntry[]>("/barcode/catalog", {
          params: {
            module: nextModule,
            q: nextQuery.trim() ? nextQuery.trim() : undefined
          }
        });
        if (!isMountedRef.current) {
          return;
        }
        const entries = response.data;
        setCatalogEntries(entries);
        if (wasModuleChanged && sku && !entries.some((entry) => entry.sku === sku)) {
          setSku("");
        }
      } catch (err) {
        if (!isMountedRef.current) {
          return;
        }
        setCatalogEntries([]);
        setCatalogError("Impossible de charger la liste des articles.");
      } finally {
        if (isMountedRef.current) {
          lastModuleRef.current = nextModule;
          setIsCatalogLoading(false);
        }
      }
    },
    [canView, sku]
  );

  const refreshGallery = useCallback(
    async (nextModule: string, nextQuery: string) => {
    if (!canView || !isMountedRef.current) {
      return;
    }

    setIsGalleryLoading(true);
    setGalleryError(null);

    try {
      const response = await api.get<BarcodeSummary[]>("/barcode", {
        params: {
          module: nextModule,
          q: nextQuery.trim() ? nextQuery.trim() : undefined
        }
      });
      const entries = response.data;
      const visuals = await Promise.all(
        entries.map(async (entry) => {
          try {
            const assetPath =
              entry.asset_path ?? `/barcode/assets/${encodeURIComponent(entry.filename)}`;
            const assetResponse = await api.get(assetPath, {
              responseType: "blob"
            });
            if (!isMountedRef.current) {
              return null;
            }
            const objectUrl = URL.createObjectURL(assetResponse.data);
            return {
              sku: entry.sku,
              filename: entry.filename,
              modifiedAt: entry.created_at ?? entry.modified_at ?? "",
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
    },
    [canView]
  );

  useEffect(() => {
    if (canView) {
      const handle = window.setTimeout(() => {
        void refreshGallery(moduleFilter, searchTerm);
      }, 300);
      return () => {
        window.clearTimeout(handle);
      };
    }
    return undefined;
  }, [canView, moduleFilter, refreshGallery, searchTerm]);

  useEffect(() => {
    if (!canView) {
      return;
    }
    const handle = window.setTimeout(() => {
      void refreshCatalog(moduleFilter, searchTerm);
    }, 300);
    return () => {
      window.clearTimeout(handle);
    };
  }, [canView, moduleFilter, refreshCatalog, searchTerm]);

  const handleGenerate = async () => {
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
      void refreshGallery(moduleFilter, searchTerm);
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
      void refreshGallery(moduleFilter, searchTerm);
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
      void refreshGallery(moduleFilter, searchTerm);
    } catch (err) {
      setError("Impossible de supprimer le fichier généré.");
    } finally {
        setDeletingSku(null);
      }
    },
    [canEdit, imageUrl, moduleFilter, refreshGallery, searchTerm, sku]
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

  const moduleFilterOptions = useMemo(
    () => [
      { value: "all", label: "Tous" },
      { value: "vehicle_inventory", label: moduleTitles.vehicle_inventory ?? "Inventaire véhicules" },
      { value: "pharmacy", label: moduleTitles.pharmacy ?? "Pharmacie" },
      { value: "clothing", label: moduleTitles.clothing ?? "Inventaire habillement" },
      { value: "inventory_remise", label: moduleTitles.inventory_remise ?? "Inventaire remises" }
    ],
    [moduleTitles]
  );

  const permittedModuleOptions = useMemo(() => {
    if (user?.role === "admin") {
      return moduleFilterOptions;
    }
    return moduleFilterOptions.filter(
      (option) => option.value === "all" || modulePermissions.canAccess(option.value)
    );
  }, [moduleFilterOptions, modulePermissions, user]);

  const visibleModuleOptions = useMemo(
    () =>
      permittedModuleOptions.filter((option) => {
        const key = option.value ?? (option as { key?: string }).key ?? (option as { id?: string }).id;
        return key ? !EXCLUDED_MODULE_KEYS.has(key) : true;
      }),
    [permittedModuleOptions]
  );

  useEffect(() => {
    if (!visibleModuleOptions.length) {
      return;
    }
    const visibleValues = new Set(
      visibleModuleOptions.map(
        (option) =>
          option.value ?? (option as { key?: string }).key ?? (option as { id?: string }).id ?? ""
      )
    );
    if (!visibleValues.has(moduleFilter)) {
      const fallback =
        visibleModuleOptions.find((option) => option.value === "all") ?? visibleModuleOptions[0];
      if (fallback?.value && fallback.value !== moduleFilter) {
        setModuleFilter(fallback.value);
      }
    }
  }, [moduleFilter, visibleModuleOptions]);

  const selectedCatalogEntry = useMemo(
    () => catalogEntries.find((entry) => entry.sku === sku) ?? null,
    [catalogEntries, sku]
  );

  const selectedCatalogValue = selectedCatalogEntry
    ? `${selectedCatalogEntry.module}::${selectedCatalogEntry.sku}`
    : "";

  const gateContent = (() => {
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

    return null;
  })();

  const pageContent = gateContent ?? (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
        <p className="text-sm text-slate-400">Générez ou scannez les codes-barres des articles.</p>
      </header>
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-end gap-4">
          {visibleModuleOptions.length > 1 ? (
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Module
              <select
                className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                value={moduleFilter}
                onChange={(event) => setModuleFilter(event.target.value)}
                title="Filtrer les articles par module"
              >
                {visibleModuleOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Recherche
            <AppTextInput
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Nom ou SKU"
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              title="Rechercher un article par nom ou SKU"
            />
          </label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Article
            <select
              className="mt-1 min-w-[220px] rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={selectedCatalogValue}
              onChange={(event) => {
                const [, selectedSku] = event.target.value.split("::");
                if (selectedSku) {
                  setSku(selectedSku);
                }
              }}
              title="Sélectionner un article"
            >
              <option value="">Sélectionner un article...</option>
              {catalogEntries.map((entry) => (
                <option key={`${entry.module}-${entry.sku}`} value={`${entry.module}::${entry.sku}`}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            SKU
            <AppTextInput
              value={sku}
              onChange={(event) => setSku(event.target.value)}
              placeholder="SKU"
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              title="Identifiant de l'article pour générer le code-barres"
            />
          </label>
          <button
            type="button"
            onClick={handleGenerate}
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
        </div>
        {isCatalogLoading ? (
          <p className="mt-3 text-xs text-slate-400">Chargement de la liste des articles...</p>
        ) : null}
        {catalogError ? <p className="mt-3 text-xs text-yellow-300">{catalogError}</p> : null}
        {!isCatalogLoading && catalogEntries.length ? (
          <p className="mt-2 text-xs text-slate-400">
            Sélectionnez un article pour préremplir le SKU ou saisissez-le manuellement.
          </p>
        ) : null}
      </div>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
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

  const blocks: EditablePageBlock[] = [
    {
      id: "barcode-main",
      title: moduleTitle,
      permissions: ["barcode"],
      required: true,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 20 },
        md: { x: 0, y: 0, w: 10, h: 20 },
        sm: { x: 0, y: 0, w: 6, h: 20 },
        xs: { x: 0, y: 0, w: 4, h: 20 }
      },
      render: () => (
        <EditableBlock id="barcode-main">
          {pageContent}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout pageKey="module:barcode" blocks={blocks} className="space-y-6" />
  );
}

type BarcodeSummary = {
  sku: string;
  filename: string;
  module: string;
  label?: string | null;
  created_at?: string;
  modified_at?: string;
  asset_path?: string;
};

type BarcodeCatalogEntry = {
  sku: string;
  label: string;
  name: string;
  module: string;
  item_id: number | null;
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
