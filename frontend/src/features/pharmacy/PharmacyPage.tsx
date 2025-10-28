import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

interface PharmacyItem {
  id: number;
  name: string;
  dosage: string | null;
  packaging: string | null;
  quantity: number;
  expiration_date: string | null;
  location: string | null;
}

interface PharmacyPayload {
  name: string;
  dosage: string | null;
  packaging: string | null;
  quantity: number;
  expiration_date: string | null;
  location: string | null;
}

export function PharmacyPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PharmacyItem | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("pharmacy");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("pharmacy", "edit");

  const { data: items = [], isFetching } = useQuery({
    queryKey: ["pharmacy"],
    queryFn: async () => {
      const response = await api.get<PharmacyItem[]>("/pharmacy/");
      return response.data;
    },
    enabled: canView
  });

  const createItem = useMutation({
    mutationFn: async (payload: PharmacyPayload) => {
      await api.post("/pharmacy/", payload);
    },
    onSuccess: async () => {
      setMessage("Médicament créé.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de créer l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateItem = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: PharmacyPayload }) => {
      await api.put(`/pharmacy/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Médicament mis à jour.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de mettre à jour l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteItem = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/pharmacy/${id}`);
    },
    onSuccess: async () => {
      setMessage("Médicament supprimé.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de supprimer l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const formValues = useMemo<PharmacyPayload>(() => {
    if (formMode === "edit" && selected) {
      return {
        name: selected.name,
        dosage: selected.dosage,
        packaging: selected.packaging,
        quantity: selected.quantity,
        expiration_date: selected.expiration_date,
        location: selected.location
      };
    }
    return { name: "", dosage: "", packaging: "", quantity: 0, expiration_date: "", location: "" };
  }, [formMode, selected]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
          <p className="text-sm text-slate-400">Suivi des stocks pharmaceutiques.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
          <p className="text-sm text-slate-400">Suivi des stocks pharmaceutiques.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload: PharmacyPayload = {
      name: (formData.get("name") as string).trim(),
      dosage: ((formData.get("dosage") as string) || "").trim() || null,
      packaging: ((formData.get("packaging") as string) || "").trim() || null,
      quantity: Number(formData.get("quantity") ?? 0),
      expiration_date: ((formData.get("expiration_date") as string) || "").trim() || null,
      location: ((formData.get("location") as string) || "").trim() || null
    };
    if (!payload.name) {
      setError("Le nom est obligatoire.");
      return;
    }
    if (payload.quantity < 0) {
      setError("La quantité doit être positive.");
      return;
    }
    setMessage(null);
    setError(null);
    if (formMode === "edit" && selected) {
      await updateItem.mutateAsync({ id: selected.id, payload });
    } else {
      await createItem.mutateAsync(payload);
    }
    event.currentTarget.reset();
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
          <p className="text-sm text-slate-400">Gérez vos médicaments et consommables médicaux.</p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => {
              setSelected(null);
              setFormMode("create");
            }}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
            title="Créer une nouvelle référence pharmaceutique"
          >
            Nouvel article
          </button>
        ) : null}
      </header>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Nom</th>
                  <th className="px-4 py-3 text-left">Dosage</th>
                  <th className="px-4 py-3 text-left">Conditionnement</th>
                  <th className="px-4 py-3 text-left">Quantité</th>
                  <th className="px-4 py-3 text-left">Expiration</th>
                  <th className="px-4 py-3 text-left">Localisation</th>
                  {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={`bg-slate-950 text-sm text-slate-100 ${
                      selected?.id === item.id && formMode === "edit" ? "ring-1 ring-indigo-500" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-medium">{item.name}</td>
                    <td className="px-4 py-3 text-slate-300">{item.dosage ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">{item.packaging ?? "-"}</td>
                    <td className="px-4 py-3 font-semibold">{item.quantity}</td>
                    <td className="px-4 py-3 text-slate-300">{formatDate(item.expiration_date)}</td>
                    <td className="px-4 py-3 text-slate-300">{item.location ?? "-"}</td>
                    {canEdit ? (
                      <td className="px-4 py-3 text-xs text-slate-200">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setSelected(item);
                              setFormMode("edit");
                            }}
                            className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                            title={`Modifier la fiche de ${item.name}`}
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (!window.confirm("Supprimer cet article pharmaceutique ?")) {
                                return;
                              }
                              setMessage(null);
                              setError(null);
                              void deleteItem.mutateAsync(item.id);
                            }}
                            className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                            title={`Supprimer ${item.name} de la pharmacie`}
                          >
                            Supprimer
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {isFetching ? <p className="mt-2 text-xs text-slate-400">Actualisation...</p> : null}
        </div>

        {canEdit ? (
          <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-white">
              {formMode === "edit" ? "Modifier l'article" : "Ajouter un article"}
            </h3>
            <form
              key={`${formMode}-${selected?.id ?? "new"}`}
              className="mt-3 space-y-3"
              onSubmit={handleSubmit}
            >
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-name">
                  Nom
                </label>
                <input
                  id="pharmacy-name"
                  name="name"
                  defaultValue={formValues.name}
                  required
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Nom du médicament ou du consommable"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-dosage">
                  Dosage
                </label>
                <input
                  id="pharmacy-dosage"
                  name="dosage"
                  defaultValue={formValues.dosage ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Dosage ou concentration si applicable"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-packaging">
                  Conditionnement
                </label>
                <input
                  id="pharmacy-packaging"
                  name="packaging"
                  defaultValue={formValues.packaging ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Conditionnement de l'article (boîte, unité...)"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-quantity">
                  Quantité
                </label>
                <input
                  id="pharmacy-quantity"
                  name="quantity"
                  type="number"
                  min={0}
                  defaultValue={formValues.quantity}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  required
                  title="Quantité disponible en stock"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-expiration">
                  Date d'expiration
                </label>
                <input
                  id="pharmacy-expiration"
                  name="expiration_date"
                  type="date"
                  defaultValue={formValues.expiration_date ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Date d'expiration (facultative)"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-location">
                  Localisation
                </label>
                <input
                  id="pharmacy-location"
                  name="location"
                  defaultValue={formValues.location ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Emplacement de stockage (armoire, pièce...)"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={createItem.isPending || updateItem.isPending}
                  className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                  title={
                    formMode === "edit"
                      ? "Enregistrer les modifications du médicament"
                      : "Ajouter ce médicament au stock"
                  }
                >
                  {formMode === "edit"
                    ? updateItem.isPending
                      ? "Mise à jour..."
                      : "Enregistrer"
                    : createItem.isPending
                      ? "Ajout..."
                      : "Ajouter"}
                </button>
                {formMode === "edit" ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(null);
                      setFormMode("create");
                    }}
                    className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                    title="Annuler la modification en cours"
                  >
                    Annuler
                  </button>
                ) : null}
              </div>
            </form>
          </aside>
        ) : null}
      </div>
    </section>
  );
}

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

