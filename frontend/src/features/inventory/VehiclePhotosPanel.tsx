import { ChangeEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
    setMessage(null);
    setError(null);
    uploadPhoto.mutate(file);
    event.target.value = "";
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

  return (
    <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-6 shadow">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-white">Bibliothèque du véhicule</h3>
          <p className="text-sm text-slate-400">
            Chargez des photos de l'aménagement ou de l'extérieur du véhicule pour faciliter le
            rangement par glisser-déposer.
          </p>
        </div>
        <label className="flex w-full flex-col gap-2 text-sm md:w-auto">
          <span className="font-semibold text-slate-200">Ajouter une photo</span>
          <input
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            disabled={uploadPhoto.isPending}
            className="w-full cursor-pointer rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-70"
            title="Téléverser une image du véhicule"
          />
          <span className="text-[11px] text-slate-500">Formats acceptés : JPG, PNG, WEBP ou GIF.</span>
        </label>
      </div>

      {message ? <PanelAlert tone="success" message={message} /> : null}
      {error ? <PanelAlert tone="error" message={error} /> : null}
      {photosQuery.isError ? (
        <PanelAlert tone="error" message="Impossible de récupérer les photos du véhicule." />
      ) : null}

      {isLoading ? <p className="text-sm text-slate-400">Chargement des photos…</p> : null}

      {photos.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {photos.map((photo) => (
            <figure
              key={photo.id}
              className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950"
            >
              <img
                src={photo.image_url}
                alt="Photo du véhicule"
                className="h-48 w-full object-cover"
              />
              <figcaption className="flex items-center justify-between border-t border-slate-800 px-3 py-2 text-[11px] text-slate-400">
                <span>{formatDate(photo.uploaded_at)}</span>
                <button
                  type="button"
                  onClick={() => handleDelete(photo.id)}
                  disabled={deletePhoto.isPending}
                  className="rounded border border-red-500/40 px-2 py-1 font-semibold text-red-300 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                  title="Supprimer cette photo"
                >
                  Supprimer
                </button>
              </figcaption>
            </figure>
          ))}
        </div>
      ) : !isLoading ? (
        <p className="text-sm text-slate-400">
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
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
      : "border-red-500/40 bg-red-500/10 text-red-200";
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
