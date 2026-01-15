import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../../lib/api";
import { AppTextInput } from "../../components/AppTextInput";
import { FieldHelpTooltip } from "../../components/FieldHelpTooltip";
import { LINK_CATEGORY_FIELD_HELP } from "../linkCategories/linkCategoryHelp";
import { useAuth } from "../auth/useAuth";

type LinkModule = "vehicle_qr" | "pharmacy";

interface LinkCategory {
  id: number;
  module: LinkModule;
  key: string;
  label: string;
  placeholder: string | null;
  help_text: string | null;
  is_required: boolean;
  sort_order: number;
  is_active: boolean;
}

const EMPTY_CATEGORY = {
  key: "",
  label: "",
  placeholder: "",
  help_text: "",
  is_required: false,
  sort_order: 0,
  is_active: true
};

export function LinkCategoriesPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [module, setModule] = useState<LinkModule>("vehicle_qr");
  const [newCategory, setNewCategory] = useState(EMPTY_CATEGORY);
  const [drafts, setDrafts] = useState<Record<number, LinkCategory>>({});
  const [status, setStatus] = useState<string | null>(null);

  const { data: categories = [], isLoading } = useQuery({
    queryKey: ["link-categories-admin", module],
    queryFn: async () => {
      const response = await api.get<LinkCategory[]>("/link-categories", {
        params: { module }
      });
      return response.data;
    },
    enabled: user?.role === "admin"
  });

  useEffect(() => {
    const next: Record<number, LinkCategory> = {};
    categories.forEach((category) => {
      next[category.id] = { ...category };
    });
    setDrafts(next);
  }, [categories]);

  const sortedCategories = useMemo(() => {
    return [...categories].sort((a, b) => {
      if (a.sort_order !== b.sort_order) {
        return a.sort_order - b.sort_order;
      }
      return a.label.localeCompare(b.label, "fr");
    });
  }, [categories]);

  const createCategory = useMutation({
    mutationFn: async () => {
      const payload = {
        module,
        key: newCategory.key,
        label: newCategory.label,
        placeholder: newCategory.placeholder || null,
        help_text: newCategory.help_text || null,
        is_required: newCategory.is_required,
        sort_order: Number(newCategory.sort_order) || 0,
        is_active: newCategory.is_active
      };
      await api.post("/link-categories", payload);
    },
    onSuccess: async () => {
      setStatus("Catégorie créée.");
      setNewCategory(EMPTY_CATEGORY);
      await queryClient.invalidateQueries({ queryKey: ["link-categories-admin", module] });
    },
    onError: (error) => {
      let message = "Impossible de créer la catégorie.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setStatus(message);
    }
  });

  const updateCategory = useMutation({
    mutationFn: async (categoryId: number) => {
      const draft = drafts[categoryId];
      if (!draft) {
        return;
      }
      await api.put(`/link-categories/${categoryId}`, {
        module: draft.module,
        key: draft.key,
        label: draft.label,
        placeholder: draft.placeholder,
        help_text: draft.help_text,
        is_required: draft.is_required,
        sort_order: draft.sort_order,
        is_active: draft.is_active
      });
    },
    onSuccess: async () => {
      setStatus("Catégorie mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["link-categories-admin", module] });
    },
    onError: (error) => {
      let message = "Impossible de mettre à jour la catégorie.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setStatus(message);
    }
  });

  const deleteCategory = useMutation({
    mutationFn: async (categoryId: number) => {
      await api.delete(`/link-categories/${categoryId}`);
    },
    onSuccess: async () => {
      setStatus("Catégorie désactivée.");
      await queryClient.invalidateQueries({ queryKey: ["link-categories-admin", module] });
    },
    onError: (error) => {
      let message = "Impossible de désactiver la catégorie.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setStatus(message);
    }
  });

  const handleDraftChange = (categoryId: number, patch: Partial<LinkCategory>) => {
    setDrafts((previous) => ({
      ...previous,
      [categoryId]: {
        ...(previous[categoryId] ?? categories.find((entry) => entry.id === categoryId)),
        ...patch
      }
    }));
  };

  if (user?.role !== "admin") {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        Cette page est réservée aux administrateurs.
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">
            Configuration des liens
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Définissez les catégories de liens disponibles pour les opérations.
          </p>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
            <span>Module</span>
            <FieldHelpTooltip
              text={LINK_CATEGORY_FIELD_HELP.module}
              ariaLabel="Aide sur le module"
            />
          </div>
          <select
            value={module}
            onChange={(event) => setModule(event.target.value as LinkModule)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            <option value="vehicle_qr">QR véhicules</option>
            <option value="pharmacy">Pharmacie</option>
          </select>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">Nouvelle catégorie</h2>
        <div className="mt-4 grid min-w-0 gap-3 lg:grid-cols-6">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>Libellé</span>
              <FieldHelpTooltip
                text={LINK_CATEGORY_FIELD_HELP.label}
                ariaLabel="Aide sur le libellé"
              />
            </div>
            <AppTextInput
              value={newCategory.label}
              onChange={(event) =>
                setNewCategory((prev) => ({ ...prev, label: event.target.value }))
              }
              placeholder="Libellé"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>Clé</span>
              <FieldHelpTooltip text={LINK_CATEGORY_FIELD_HELP.key} ariaLabel="Aide sur la clé" />
            </div>
            <AppTextInput
              value={newCategory.key}
              onChange={(event) => setNewCategory((prev) => ({ ...prev, key: event.target.value }))}
              placeholder="Clé (slug)"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>Placeholder</span>
              <FieldHelpTooltip
                text={LINK_CATEGORY_FIELD_HELP.placeholder}
                ariaLabel="Aide sur le placeholder"
              />
            </div>
            <AppTextInput
              value={newCategory.placeholder}
              onChange={(event) =>
                setNewCategory((prev) => ({ ...prev, placeholder: event.target.value }))
              }
              placeholder="Placeholder"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>Aide</span>
              <FieldHelpTooltip
                text={LINK_CATEGORY_FIELD_HELP.help_text}
                ariaLabel="Aide sur le texte d'aide"
              />
            </div>
            <AppTextInput
              value={newCategory.help_text}
              onChange={(event) =>
                setNewCategory((prev) => ({ ...prev, help_text: event.target.value }))
              }
              placeholder="Aide"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>Ordre</span>
              <FieldHelpTooltip
                text={LINK_CATEGORY_FIELD_HELP.sort_order}
                ariaLabel="Aide sur l'ordre"
              />
            </div>
            <AppTextInput
              type="number"
              value={newCategory.sort_order}
              onChange={(event) =>
                setNewCategory((prev) => ({ ...prev, sort_order: Number(event.target.value) }))
              }
              placeholder="Ordre"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
                <AppTextInput
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
                  checked={newCategory.is_required}
                  onChange={(event) =>
                    setNewCategory((prev) => ({ ...prev, is_required: event.target.checked }))
                  }
                />
                <span className="inline-flex items-center gap-1">
                  Requis
                  <FieldHelpTooltip
                    text={LINK_CATEGORY_FIELD_HELP.is_required}
                    ariaLabel="Aide sur le caractère requis"
                  />
                </span>
              </label>
              <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
                <AppTextInput
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
                  checked={newCategory.is_active}
                  onChange={(event) =>
                    setNewCategory((prev) => ({ ...prev, is_active: event.target.checked }))
                  }
                />
                <span className="inline-flex items-center gap-1">
                  Actif
                  <FieldHelpTooltip
                    text={LINK_CATEGORY_FIELD_HELP.is_active}
                    ariaLabel="Aide sur le statut actif"
                  />
                </span>
              </label>
            </div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
          <button
            type="button"
            onClick={() => createCategory.mutate()}
            disabled={createCategory.isPending || !newCategory.label || !newCategory.key}
            className="inline-flex items-center gap-2 rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {createCategory.isPending ? "Création..." : "Créer"}
          </button>
          {status && <span>{status}</span>}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">Catégories existantes</h2>
        <div className="mt-4 overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>Libellé</span>
                    <FieldHelpTooltip
                      text={LINK_CATEGORY_FIELD_HELP.label}
                      ariaLabel="Aide sur le libellé"
                    />
                  </div>
                </th>
                <th className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>Clé</span>
                    <FieldHelpTooltip text={LINK_CATEGORY_FIELD_HELP.key} ariaLabel="Aide sur la clé" />
                  </div>
                </th>
                <th className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>Placeholder</span>
                    <FieldHelpTooltip
                      text={LINK_CATEGORY_FIELD_HELP.placeholder}
                      ariaLabel="Aide sur le placeholder"
                    />
                  </div>
                </th>
                <th className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>Aide</span>
                    <FieldHelpTooltip
                      text={LINK_CATEGORY_FIELD_HELP.help_text}
                      ariaLabel="Aide sur le texte d'aide"
                    />
                  </div>
                </th>
                <th className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>Ordre</span>
                    <FieldHelpTooltip
                      text={LINK_CATEGORY_FIELD_HELP.sort_order}
                      ariaLabel="Aide sur l'ordre"
                    />
                  </div>
                </th>
                <th className="px-3 py-2">Statut</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-slate-500">
                    Chargement...
                  </td>
                </tr>
              ) : sortedCategories.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-slate-500">
                    Aucune catégorie enregistrée.
                  </td>
                </tr>
              ) : (
                sortedCategories.map((category) => {
                  const draft = drafts[category.id] ?? category;
                  return (
                    <tr
                      key={category.id}
                      className="border-t border-slate-100 dark:border-slate-800"
                    >
                      <td className="px-3 py-2">
                        <AppTextInput
                          value={draft.label}
                          onChange={(event) =>
                            handleDraftChange(category.id, { label: event.target.value })
                          }
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <AppTextInput
                          value={draft.key}
                          onChange={(event) =>
                            handleDraftChange(category.id, { key: event.target.value })
                          }
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <AppTextInput
                          value={draft.placeholder ?? ""}
                          onChange={(event) =>
                            handleDraftChange(category.id, { placeholder: event.target.value })
                          }
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <AppTextInput
                          value={draft.help_text ?? ""}
                          onChange={(event) =>
                            handleDraftChange(category.id, { help_text: event.target.value })
                          }
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <AppTextInput
                          type="number"
                          value={draft.sort_order}
                          onChange={(event) =>
                            handleDraftChange(category.id, {
                              sort_order: Number(event.target.value)
                            })
                          }
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col gap-2">
                          <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
                            <AppTextInput
                              type="checkbox"
                              className="h-4 w-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
                              checked={draft.is_required}
                              onChange={(event) =>
                                handleDraftChange(category.id, {
                                  is_required: event.target.checked
                                })
                              }
                            />
                            <span className="inline-flex items-center gap-1">
                              Requis
                              <FieldHelpTooltip
                                text={LINK_CATEGORY_FIELD_HELP.is_required}
                                ariaLabel="Aide sur le caractère requis"
                              />
                            </span>
                          </label>
                          <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
                            <AppTextInput
                              type="checkbox"
                              className="h-4 w-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
                              checked={draft.is_active}
                              onChange={(event) =>
                                handleDraftChange(category.id, {
                                  is_active: event.target.checked
                                })
                              }
                            />
                            <span className="inline-flex items-center gap-1">
                              Actif
                              <FieldHelpTooltip
                                text={LINK_CATEGORY_FIELD_HELP.is_active}
                                ariaLabel="Aide sur le statut actif"
                              />
                            </span>
                          </label>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col gap-2">
                          <button
                            type="button"
                            onClick={() => updateCategory.mutate(category.id)}
                            disabled={updateCategory.isPending}
                            className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                          >
                            Mettre à jour
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteCategory.mutate(category.id)}
                            disabled={deleteCategory.isPending}
                            className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-500/10"
                          >
                            Désactiver
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
