import { FormEvent, useEffect, useState } from "react";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

export function BarcodePage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("clothing");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("clothing", "edit");

  const [sku, setSku] = useState("SKU-001");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

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
    </section>
  );
}
