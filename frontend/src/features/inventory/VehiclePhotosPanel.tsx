import { ChangeEvent, DragEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "../../lib/api";

interface VehiclePhoto {
  id: number;
  image_url: string;
  uploaded_at: string;
}

export function VehiclePhotosPanel() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const photosQuery = useQuery({
    queryKey: ["vehicle-photos"],
    queryFn: async () => {
      const response = await api.get<VehiclePhoto[]>("/vehicle-inventory/photos/");
      return response.data;
    }
  });

  const uploadPhoto = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      await api.post("/vehicle-inventory/photos/", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
    },
    onSuccess: async () => {
      setMessage("Photo importée avec succès.");
      await queryClient.invalidateQueries({ queryKey: ["vehicle-photos"] });
    },
    onError: () => {
      setMessage(null);
      setError("Impossible d'envoyer la photo.");
    }
  });

  const deletePhoto = useMutation({
    mutationFn: async (photoId: number) => {
      await api.delete(`/vehicle-inventory/photos/${photoId}`);
    },
    onSuccess: async () => {
      setMessage("Photo supprimée.");
      await queryClient.invalidateQueries({ queryKey: ["vehicle-photos"] });
      await queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] });
    },
    onError: () => {
      setMessage(null);
      setError("Suppression impossible.");
    }
  });

  useEffect(() => {
    if (message) {
      const timeout = window.setTimeout(() => setMessage(null), 4000);
      return () => window.clearTimeout(timeout);
    }
    return undefined;
  }, [message]);

  useEffect(() => {
    if (error) {
      const timeout = window.setTimeout(() => setError(null), 5000);
      return () => window.clearTimeout(timeout);
    }
    return undefined;
  }, [error]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setMessage(null);
      setError("Seules les images sont autorisées.");
      event.target.value = "";
      return;
    }
    setMessage(null);
    setError(null);
    uploadPhoto.mutate(file);
    event.target.value = "";
  };

  const handleDropZoneDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer) {
      return;
    }
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsDragOver(true);
  };

  const handleDropZoneDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDropZoneDrop = async (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer) {
      return;
    }
    event.preventDefault();
    setIsDragOver(false);
    const files = Array.from(event.dataTransfer.files).filter((file) =>
      file.type.startsWith("image/")
    );
    if (files.length === 0) {
      setMessage(null);
      setError("Déposez uniquement des images (JPG, PNG, WEBP, GIF).");
      return;
    }
    setMessage(null);
    setError(null);
    try {
      for (const file of files) {
        // eslint-disable-next-line no-await-in-loop
        await uploadPhoto.mutateAsync(file);
      }
    } catch {
      // Les erreurs sont gérées par la mutation.
    }
  };

  const handleDelete = (photoId: number) => {
    if (!window.confirm("Supprimer cette photo du véhicule ?")) {
      return;
    }
    setMessage(null);
    setError(null);
    deletePhoto.mutate(photoId);
  };

  const photos = photosQuery.data ?? [];
  const isLoading = photosQuery.isLoading || photosQuery.isFetching;
  const pendingUploads = uploadPhoto.isPending;
  const panelHighlight = useMemo(
    () =>
      clsx(
        "space-y-4 rounded-2xl border p-6 shadow-sm transition",
        isDragOver
          ? "border-blue-400 bg-blue-50/70 dark:border-blue-500 dark:bg-blue-950/40"
          : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
      ),
    [isDragOver]
  );

  return (
    <section
      className={panelHighlight}
      onDragOver={handleDropZoneDragOver}
      onDragLeave={handleDropZoneDragLeave}
      onDrop={handleDropZoneDrop}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Bibliothèque du véhicule
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Chargez des photos de l'aménagement ou de l'extérieur du véhicule pour faciliter le
            rangement par glisser-déposer.
          </p>
        </div>
        <label className="flex w-full flex-col gap-2 text-sm md:w-auto">
          <span className="font-semibold text-slate-700 dark:text-slate-200">
            Ajouter une photo
          </span>
          <input
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            disabled={uploadPhoto.isPending}
            className="w-full cursor-pointer rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            title="Téléverser une image du véhicule"
          />
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            Formats acceptés : JPG, PNG, WEBP ou GIF. Vous pouvez également glisser-déposer des
            images directement sur ce panneau.
          </span>
        </label>
      </div>

      {message ? <PanelAlert tone="success" message={message} /> : null}
      {error ? <PanelAlert tone="error" message={error} /> : null}
      {photosQuery.isError ? (
        <PanelAlert tone="error" message="Impossible de récupérer les photos du véhicule." />
      ) : null}

      {isLoading ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">Chargement des photos…</p>
      ) : null}
      {pendingUploads ? (
        <p className="text-xs text-blue-600 dark:text-blue-300">
          Importation en cours…
        </p>
      ) : null}

      {photos.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {photos.map((photo) => (
            <figure
              key={photo.id}
              className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-950"
            >
              <img
                src={photo.image_url}
                alt="Photo du véhicule"
                className="h-48 w-full object-cover"
              />
              <figcaption className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
                <span>{formatDate(photo.uploaded_at)}</span>
                <button
                  type="button"
                  onClick={() => handleDelete(photo.id)}
                  disabled={deletePhoto.isPending}
                  className="rounded border border-rose-300 px-2 py-1 font-semibold text-rose-600 transition hover:border-rose-400 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-500/60 dark:text-rose-200 dark:hover:border-rose-400 dark:hover:text-rose-100"
                  title="Supprimer cette photo"
                >
                  Supprimer
                </button>
              </figcaption>
            </figure>
          ))}
        </div>
      ) : !isLoading ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Aucune photo enregistrée pour le moment. Ajoutez des images pour documenter chaque
          véhicule.
        </p>
      ) : null}
    </section>
  );
}

function PanelAlert({ tone, message }: { tone: "success" | "error"; message: string }) {
  const styles =
    tone === "success"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
      : "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-200";
  return <div className={`rounded-md border px-4 py-2 text-sm ${styles}`}>{message}</div>;
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: "short"
    }).format(new Date(value));
  } catch (error) {
    return value;
  }
}
