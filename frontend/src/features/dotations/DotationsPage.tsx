import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { EditablePageLayout, type EditableLayoutSet, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

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
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
  allocated_at: string;
  is_obsolete: boolean;
}

interface DotationFormValues {
  collaborator_id: string;
  item_id: string;
  quantity: number;
  notes: string;
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
}

interface DotationEditFormValues {
  item_id: string;
  quantity: number;
  notes: string;
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
}

export function DotationsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<{ collaborator: string; item: string }>({ collaborator: "all", item: "all" });
  const buildDefaultFormValues = () => ({
    collaborator_id: "",
    item_id: "",
    quantity: 1,
    notes: "",
    perceived_at: new Date().toISOString().slice(0, 10),
    is_lost: false,
    is_degraded: false
  });
  const [formValues, setFormValues] = useState<DotationFormValues>(() => buildDefaultFormValues());
  const [editingDotationId, setEditingDotationId] = useState<number | null>(null);
  const [editFormValues, setEditFormValues] = useState<DotationEditFormValues | null>(null);

  const canView = user?.role === "admin" || modulePermissions.canAccess("dotations");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("dotations", "edit");
  const moduleTitle = useModuleTitle("dotations");

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
    mutationFn: async (payload: {
      collaborator_id: number;
      item_id: number;
      quantity: number;
      notes: string | null;
      perceived_at: string;
      is_lost: boolean;
      is_degraded: boolean;
    }) => {
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

  const updateDotation = useMutation({
    mutationFn: async ({
      id,
      payload
    }: {
      id: number;
      payload: {
        item_id: number;
        quantity: number;
        notes: string | null;
        perceived_at: string;
        is_lost: boolean;
        is_degraded: boolean;
      };
    }) => {
      await api.put(`/dotations/dotations/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Dotation mise à jour.");
      setEditingDotationId(null);
      setEditFormValues(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible de mettre à jour la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const collaboratorById = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator]));
  }, [collaborators]);

  const itemById = useMemo(() => {
    return new Map(items.map((item) => [item.id, item]));
  }, [items]);

  const groupedDotations = useMemo(() => {
    const groups = new Map<
      number,
      {
        collaborator: Collaborator | undefined;
        dotations: Dotation[];
      }
    >();
    for (const dotation of dotations) {
      const collaborator = collaboratorById.get(dotation.collaborator_id);
      if (!groups.has(dotation.collaborator_id)) {
        groups.set(dotation.collaborator_id, {
          collaborator,
          dotations: []
        });
      }
      groups.get(dotation.collaborator_id)?.dotations.push(dotation);
    }
    return Array.from(groups.entries())
      .map(([collaboratorId, value]) => ({ collaboratorId, ...value }))
      .sort((a, b) => {
        const labelA = a.collaborator?.full_name ?? `#${a.collaboratorId}`;
        const labelB = b.collaborator?.full_name ?? `#${b.collaboratorId}`;
        return labelA.localeCompare(labelB, "fr");
      });
  }, [dotations, collaboratorById]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
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
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
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
    const perceived_at = formValues.perceived_at || new Date().toISOString().slice(0, 10);
    await createDotation.mutateAsync({
      collaborator_id: Number(formValues.collaborator_id),
      item_id: Number(formValues.item_id),
      quantity: formValues.quantity,
      notes: formValues.notes.trim() ? formValues.notes.trim() : null,
      perceived_at,
      is_lost: formValues.is_lost,
      is_degraded: formValues.is_degraded
    });
    setFormValues(buildDefaultFormValues());
  };

  const handleStartEditing = (dotation: Dotation) => {
    setMessage(null);
    setError(null);
    setEditingDotationId(dotation.id);
    setEditFormValues({
      item_id: dotation.item_id.toString(),
      quantity: dotation.quantity,
      notes: dotation.notes ?? "",
      perceived_at: dotation.perceived_at.slice(0, 10),
      is_lost: dotation.is_lost,
      is_degraded: dotation.is_degraded
    });
  };

  const handleCancelEditing = () => {
    setEditingDotationId(null);
    setEditFormValues(null);
  };

  const handleUpdateSubmit = async (event: FormEvent<HTMLFormElement>, dotation: Dotation) => {
    event.preventDefault();
    if (!editFormValues) {
      return;
    }
    if (!editFormValues.item_id) {
      setError("Veuillez sélectionner un article.");
      return;
    }
    if (editFormValues.quantity <= 0) {
      setError("La quantité doit être positive.");
      return;
    }
    setMessage(null);
    setError(null);
    const perceived_at = editFormValues.perceived_at || new Date().toISOString().slice(0, 10);
    await updateDotation.mutateAsync({
      id: dotation.id,
      payload: {
        item_id: Number(editFormValues.item_id),
        quantity: editFormValues.quantity,
        notes: editFormValues.notes.trim() ? editFormValues.notes.trim() : null,
        perceived_at,
        is_lost: editFormValues.is_lost,
        is_degraded: editFormValues.is_degraded
      }
    });
  };

  const content = (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
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

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          {isFetching ? <p className="text-xs text-slate-400">Actualisation des dotations...</p> : null}
          {groupedDotations.length === 0 ? (
            <p className="rounded-lg border border-slate-800 bg-slate-950 px-4 py-6 text-sm text-slate-400">
              Aucune dotation enregistrée pour le moment.
            </p>
          ) : null}
          {groupedDotations.map(({ collaboratorId, collaborator, dotations: collaboratorDotations }) => (
            <article key={collaboratorId} className="space-y-4 rounded-lg border border-slate-800 bg-slate-950 p-4">
              <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
                <div>
                  <h3 className="text-lg font-semibold text-white">
                    {collaborator?.full_name ?? `Collaborateur #${collaboratorId}`}
                  </h3>
                  <p className="text-xs text-slate-400">
                    {collaboratorDotations.length} article{collaboratorDotations.length > 1 ? "s" : ""} attribué{collaboratorDotations.length > 1 ? "s" : ""}
                  </p>
                </div>
              </header>
              <ul className="space-y-3">
                {collaboratorDotations.map((dotation) => {
                  const item = itemById.get(dotation.item_id);
                  const isEditing = editingDotationId === dotation.id && editFormValues;
                  const alerts: Array<{ key: string; label: string; className: string }> = [];
                  if (dotation.is_obsolete) {
                    alerts.push({
                      key: "obsolete",
                      label: "Vétusté",
                      className: "rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-300"
                    });
                  }
                  if (dotation.is_lost) {
                    alerts.push({
                      key: "lost",
                      label: "Perte",
                      className: "rounded border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-red-300"
                    });
                  }
                  if (dotation.is_degraded) {
                    alerts.push({
                      key: "degraded",
                      label: "Dégradation",
                      className: "rounded border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-orange-300"
                    });
                  }
                  return (
                    <li key={dotation.id} className="rounded border border-slate-800 bg-slate-900/40 p-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-white">
                            {item ? `${item.name} (${item.sku})` : `Article #${dotation.item_id}`}
                          </p>
                          <p className="text-xs text-slate-400">Dotation créée le {formatDate(dotation.allocated_at)}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {alerts.length > 0 ? (
                            alerts.map((alert) => (
                              <span key={alert.key} className={alert.className}>
                                {alert.label}
                              </span>
                            ))
                          ) : (
                            <span className="rounded border border-slate-800 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
                              RAS
                            </span>
                          )}
                        </div>
                      </div>
                      <dl className="mt-3 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
                        <div>
                          <dt className="text-xs uppercase tracking-wide text-slate-500">Quantité</dt>
                          <dd className="font-semibold text-white">{dotation.quantity}</dd>
                        </div>
                        <div>
                          <dt className="text-xs uppercase tracking-wide text-slate-500">Perçue le</dt>
                          <dd>{formatDateOnly(dotation.perceived_at)}</dd>
                        </div>
                        <div className="sm:col-span-2">
                          <dt className="text-xs uppercase tracking-wide text-slate-500">Notes</dt>
                          <dd>{dotation.notes ? dotation.notes : <span className="text-slate-500">-</span>}</dd>
                        </div>
                      </dl>
                      {canEdit ? (
                        <div className="mt-4 space-y-3">
                          {isEditing ? (
                            <form
                              className="space-y-3 rounded border border-slate-800 bg-slate-950 p-3"
                              onSubmit={(event) => void handleUpdateSubmit(event, dotation)}
                            >
                              <div className="space-y-1">
                                <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-item-${dotation.id}`}>
                                  Article attribué
                                </label>
                                <select
                                  id={`edit-item-${dotation.id}`}
                                  value={editFormValues?.item_id ?? ""}
                                  onChange={(event) =>
                                    setEditFormValues((prev) =>
                                      prev
                                        ? {
                                            ...prev,
                                            item_id: event.target.value
                                          }
                                        : prev
                                    )
                                  }
                                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                                >
                                  <option value="">Sélectionner...</option>
                                  {items.map((option) => (
                                    <option key={option.id} value={option.id}>
                                      {option.name} - Stock: {option.quantity}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <div className="grid gap-3 sm:grid-cols-2">
                                <div className="space-y-1">
                                  <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-quantity-${dotation.id}`}>
                                    Quantité
                                  </label>
                                  <AppTextInput
                                    id={`edit-quantity-${dotation.id}`}
                                    type="number"
                                    min={1}
                                    value={editFormValues?.quantity ?? dotation.quantity}
                                    onChange={(event) =>
                                      setEditFormValues((prev) =>
                                        prev
                                          ? {
                                              ...prev,
                                              quantity: Number(event.target.value)
                                            }
                                          : prev
                                      )
                                    }
                                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                                  />
                                </div>
                                <div className="space-y-1">
                                  <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-perceived-${dotation.id}`}>
                                    Date de perception
                                  </label>
                                  <AppTextInput
                                    id={`edit-perceived-${dotation.id}`}
                                    type="date"
                                    value={editFormValues?.perceived_at ?? dotation.perceived_at.slice(0, 10)}
                                    onChange={(event) =>
                                      setEditFormValues((prev) =>
                                        prev
                                          ? {
                                              ...prev,
                                              perceived_at: event.target.value
                                            }
                                          : prev
                                      )
                                    }
                                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                                  />
                                </div>
                              </div>
                              <div className="space-y-1">
                                <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-notes-${dotation.id}`}>
                                  Notes
                                </label>
                                <AppTextArea
                                  id={`edit-notes-${dotation.id}`}
                                  rows={3}
                                  value={editFormValues?.notes ?? dotation.notes ?? ""}
                                  onChange={(event) =>
                                    setEditFormValues((prev) =>
                                      prev
                                        ? {
                                            ...prev,
                                            notes: event.target.value
                                          }
                                        : prev
                                    )
                                  }
                                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                                />
                              </div>
                              <div className="flex flex-wrap items-center gap-4">
                                <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor={`edit-lost-${dotation.id}`}>
                                  <AppTextInput
                                    id={`edit-lost-${dotation.id}`}
                                    type="checkbox"
                                    checked={editFormValues?.is_lost ?? dotation.is_lost}
                                    onChange={(event) =>
                                      setEditFormValues((prev) =>
                                        prev
                                          ? {
                                              ...prev,
                                              is_lost: event.target.checked
                                            }
                                          : prev
                                      )
                                    }
                                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                                  />
                                  Perte déclarée
                                </label>
                                <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor={`edit-degraded-${dotation.id}`}>
                                  <AppTextInput
                                    id={`edit-degraded-${dotation.id}`}
                                    type="checkbox"
                                    checked={editFormValues?.is_degraded ?? dotation.is_degraded}
                                    onChange={(event) =>
                                      setEditFormValues((prev) =>
                                        prev
                                          ? {
                                              ...prev,
                                              is_degraded: event.target.checked
                                            }
                                          : prev
                                      )
                                    }
                                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                                  />
                                  Dégradation constatée
                                </label>
                              </div>
                              <div className="flex flex-wrap items-center gap-3">
                                <button
                                  type="submit"
                                  disabled={updateDotation.isPending}
                                  className="rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-70"
                                >
                                  {updateDotation.isPending ? "Enregistrement..." : "Enregistrer les modifications"}
                                </button>
                                <button
                                  type="button"
                                  onClick={handleCancelEditing}
                                  className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-slate-500"
                                >
                                  Annuler
                                </button>
                              </div>
                            </form>
                          ) : (
                            <div className="flex flex-wrap gap-3 text-xs">
                              <button
                                type="button"
                                onClick={() => handleStartEditing(dotation)}
                                className="rounded-md border border-slate-700 px-3 py-1 font-semibold text-indigo-300 hover:border-indigo-400 hover:text-indigo-200"
                              >
                                Modifier
                              </button>
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
                                className="rounded-md border border-slate-700 px-3 py-1 font-semibold text-red-300 hover:border-red-400 hover:text-red-200"
                              >
                                Supprimer
                              </button>
                            </div>
                          )}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </article>
          ))}
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
                <AppTextInput
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
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-perceived-at">
                  Date de perception
                </label>
                <AppTextInput
                  id="dotation-perceived-at"
                  type="date"
                  value={formValues.perceived_at}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, perceived_at: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  required
                  title="Date de remise au collaborateur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-notes">
                  Notes
                </label>
                <AppTextArea
                  id="dotation-notes"
                  value={formValues.notes}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, notes: event.target.value }))}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Optionnel"
                  title="Ajoutez des précisions (numéro de série, conditions, etc.)"
                />
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor="dotation-lost">
                  <AppTextInput
                    id="dotation-lost"
                    type="checkbox"
                    checked={formValues.is_lost}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, is_lost: event.target.checked }))
                    }
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                  />
                  Perte déclarée
                </label>
                <label
                  className="flex items-center gap-2 text-xs font-semibold text-slate-300"
                  htmlFor="dotation-degraded"
                >
                  <AppTextInput
                    id="dotation-degraded"
                    type="checkbox"
                    checked={formValues.is_degraded}
                    onChange={(event) =>
                      setFormValues((prev) => ({ ...prev, is_degraded: event.target.checked }))
                    }
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                  />
                  Dégradation constatée
                </label>
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

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [{ i: "dotations-main", x: 0, y: 0, w: 12, h: 24 }],
      md: [{ i: "dotations-main", x: 0, y: 0, w: 6, h: 24 }],
      sm: [{ i: "dotations-main", x: 0, y: 0, w: 1, h: 24 }]
    }),
    []
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "dotations-main",
      title: "Dotations",
      required: true,
      permission: { module: "dotations", action: "view" },
      containerClassName: "rounded-none border-0 bg-transparent p-0",
      render: () => (
        <EditableBlock id="dotations-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageId="module:dotations"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      pagePermission={{ module: "dotations", action: "view" }}
      className="space-y-6"
    />
  );
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

function formatDateOnly(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}
