import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

interface Collaborator {
  id: number;
  full_name: string;
}

interface Item {
  id: number;
  name: string;
  sku: string;
  quantity: number;
}

interface Dotation {
  id: number;
  collaborator_id: number;
  item_id: number;
  quantity: number;
  notes: string | null;
  allocated_at: string;
}

interface DotationFormValues {
  collaborator_id: string;
  item_id: string;
  quantity: number;
  notes: string;
}

export function DotationsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<{ collaborator: string; item: string }>({ collaborator: "all", item: "all" });
  const [formValues, setFormValues] = useState<DotationFormValues>({
    collaborator_id: "",
    item_id: "",
    quantity: 1,
    notes: ""
  });

  const canView = user?.role === "admin" || modulePermissions.canAccess("dotations");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("dotations", "edit");

  const { data: collaborators = [], isFetching: isFetchingCollaborators } = useQuery({
    queryKey: ["dotations", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canView
  });

  const { data: items = [], isFetching: isFetchingItems } = useQuery({
    queryKey: ["dotations", "items"],
    queryFn: async () => {
      const response = await api.get<Item[]>("/items/");
      return response.data;
    },
    enabled: canView
  });

  const { data: dotations = [], isFetching } = useQuery({
    queryKey: ["dotations", "list", filters],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (filters.collaborator !== "all" && filters.collaborator) {
        params.collaborator_id = filters.collaborator;
      }
      if (filters.item !== "all" && filters.item) {
        params.item_id = filters.item;
      }
      const response = await api.get<Dotation[]>("/dotations/dotations", { params });
      return response.data;
    },
    enabled: canView
  });

  const createDotation = useMutation({
    mutationFn: async (payload: { collaborator_id: number; item_id: number; quantity: number; notes: string | null }) => {
      await api.post("/dotations/dotations", payload);
    },
    onSuccess: async () => {
      setMessage("Dotation enregistrée.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible d'enregistrer la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteDotation = useMutation({
    mutationFn: async ({ id, restock }: { id: number; restock: boolean }) => {
      await api.delete(`/dotations/dotations/${id}`, { params: { restock } });
    },
    onSuccess: async () => {
      setMessage("Dotation supprimée.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible de supprimer la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const collaboratorById = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator]));
  }, [collaborators]);

  const itemById = useMemo(() => {
    return new Map(items.map((item) => [item.id, item]));
  }, [items]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Dotations</h2>
          <p className="text-sm text-slate-400">Distribution de matériel aux collaborateurs.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Dotations</h2>
          <p className="text-sm text-slate-400">Distribution de matériel aux collaborateurs.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!formValues.collaborator_id || !formValues.item_id) {
      setError("Veuillez sélectionner un collaborateur et un article.");
      return;
    }
    if (formValues.quantity <= 0) {
      setError("La quantité doit être positive.");
      return;
    }
    setMessage(null);
    setError(null);
    await createDotation.mutateAsync({
      collaborator_id: Number(formValues.collaborator_id),
      item_id: Number(formValues.item_id),
      quantity: formValues.quantity,
      notes: formValues.notes.trim() ? formValues.notes.trim() : null
    });
    setFormValues({ collaborator_id: "", item_id: "", quantity: 1, notes: "" });
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Dotations</h2>
        <p className="text-sm text-slate-400">Suivez les dotations et restitutions de matériel.</p>
      </header>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Collaborateur
            <select
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={filters.collaborator}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, collaborator: event.target.value }))
              }
              title="Filtrer les dotations par collaborateur"
            >
              <option value="all">Tous</option>
              {collaborators.map((collaborator) => (
                <option key={collaborator.id} value={collaborator.id}>
                  {collaborator.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Article
            <select
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={filters.item}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, item: event.target.value }))
              }
              title="Filtrer les dotations par article"
            >
              <option value="all">Tous</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.sku})
                </option>
              ))}
            </select>
          </label>
          {isFetching ? <span className="text-xs text-slate-400">Actualisation...</span> : null}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Collaborateur</th>
                  <th className="px-4 py-3 text-left">Article</th>
                  <th className="px-4 py-3 text-left">Quantité</th>
                  <th className="px-4 py-3 text-left">Notes</th>
                  <th className="px-4 py-3 text-left">Date</th>
                  {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {dotations.map((dotation) => {
                  const collaborator = collaboratorById.get(dotation.collaborator_id);
                  const item = itemById.get(dotation.item_id);
                  return (
                    <tr key={dotation.id} className="bg-slate-950 text-sm text-slate-100">
                      <td className="px-4 py-3 font-medium">{collaborator?.full_name ?? `#${dotation.collaborator_id}`}</td>
                      <td className="px-4 py-3 text-slate-300">{item ? `${item.name} (${item.sku})` : `#${dotation.item_id}`}</td>
                      <td className="px-4 py-3 font-semibold">{dotation.quantity}</td>
                      <td className="px-4 py-3 text-slate-300">{dotation.notes ?? "-"}</td>
                      <td className="px-4 py-3 text-slate-300">{formatDate(dotation.allocated_at)}</td>
                      {canEdit ? (
                        <td className="px-4 py-3 text-xs">
                          <button
                            type="button"
                            onClick={() => {
                              if (!window.confirm("Supprimer cette dotation ?")) {
                                return;
                              }
                              const restock = window.confirm(
                                "Faut-il réintégrer les quantités au stock ?\nOK pour réintégrer, Annuler pour ignorer."
                              );
                              setMessage(null);
                              setError(null);
                              void deleteDotation.mutateAsync({ id: dotation.id, restock });
                            }}
                            className="rounded bg-red-600 px-3 py-1 font-semibold text-white hover:bg-red-500"
                            title="Supprimer la dotation et éventuellement réintégrer le stock"
                          >
                            Supprimer
                          </button>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {isFetching ? <p className="mt-2 text-xs text-slate-400">Chargement des dotations...</p> : null}
        </div>

        <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h3 className="text-sm font-semibold text-white">Nouvelle dotation</h3>
          {canEdit ? (
            <form className="mt-3 space-y-3" onSubmit={handleSubmit}>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-collaborator">
                  Collaborateur
                </label>
                <select
                  id="dotation-collaborator"
                  value={formValues.collaborator_id}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, collaborator_id: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  disabled={isFetchingCollaborators}
                  required
                  title="Choisissez le collaborateur bénéficiaire"
                >
                  <option value="">Sélectionner...</option>
                  {collaborators.map((collaborator) => (
                    <option key={collaborator.id} value={collaborator.id}>
                      {collaborator.full_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-item">
                  Article
                </label>
                <select
                  id="dotation-item"
                  value={formValues.item_id}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, item_id: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  disabled={isFetchingItems}
                  required
                  title="Sélectionnez l'article à allouer"
                >
                  <option value="">Sélectionner...</option>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} - Stock: {item.quantity}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-quantity">
                  Quantité
                </label>
                <input
                  id="dotation-quantity"
                  type="number"
                  min={1}
                  value={formValues.quantity}
                  onChange={(event) =>
                    setFormValues((prev) => ({ ...prev, quantity: Number(event.target.value) }))
                  }
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  required
                  title="Quantité remise au collaborateur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-notes">
                  Notes
                </label>
                <textarea
                  id="dotation-notes"
                  value={formValues.notes}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, notes: event.target.value }))}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Optionnel"
                  title="Ajoutez des précisions (numéro de série, conditions, etc.)"
                />
              </div>
              <button
                type="submit"
                disabled={createDotation.isPending}
                className="w-full rounded-md bg-indigo-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                title="Valider l'enregistrement de la dotation"
              >
                {createDotation.isPending ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          ) : (
            <p className="mt-3 text-sm text-slate-400">
              Vous ne disposez pas des droits d'écriture pour créer des dotations.
            </p>
          )}
        </aside>
      </div>
    </section>
  );
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

