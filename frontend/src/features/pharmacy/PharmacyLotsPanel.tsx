import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CustomFieldsForm } from "../../components/CustomFieldsForm";
import { api } from "../../lib/api";
import { buildCustomFieldDefaults, CustomFieldDefinition } from "../../lib/customFields";
import { resolveMediaUrl } from "../../lib/media";
import { useAuth } from "../auth/useAuth";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";

interface PharmacyItemOption {
  id: number;
  name: string;
  barcode: string | null;
  quantity: number;
}

interface PharmacyLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  image_url: string | null;
  item_count: number;
  total_quantity: number;
  extra?: Record<string, unknown>;
}

interface PharmacyLotItem {
  id: number;
  lot_id: number;
  pharmacy_item_id: number;
  compartment_name: string | null;
  pharmacy_name: string;
  pharmacy_sku: string;
  quantity: number;
  available_quantity: number;
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

export function PharmacyLotsPanel({ canEdit }: { canEdit: boolean }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const [selectedLotId, setSelectedLotId] = useState<number | null>(null);
  const [lotForm, setLotForm] = useState<{ name: string; description: string; extra: Record<string, unknown> }>({
    name: "",
    description: "",
    extra: {}
  });
  const [lotItemForm, setLotItemForm] = useState<{ pharmacy_item_id: string; quantity: number; compartment_name: string }>(
    {
      pharmacy_item_id: "",
      quantity: 1,
      compartment_name: ""
    }
  );
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingLotId, setEditingLotId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const lotsQuery = useQuery({
    queryKey: ["pharmacy-lots"],
    queryFn: async () => {
      const response = await api.get<PharmacyLot[]>("/pharmacy/lots/");
      return response.data;
    }
  });
  const lots = lotsQuery.data ?? [];

  const { data: customFieldDefinitions = [] } = useQuery({
    queryKey: ["custom-fields", "pharmacy_lots"],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: "pharmacy_lots" }
      });
      return response.data;
    },
    enabled: isAdmin
  });
  const activeCustomFields = useMemo(
    () => customFieldDefinitions.filter((definition) => definition.is_active),
    [customFieldDefinitions]
  );

  const selectedLot = useMemo(() => lots.find((lot) => lot.id === selectedLotId) ?? null, [lots, selectedLotId]);

  useEffect(() => {
    if (selectedLotId === null && lots.length > 0) {
      setSelectedLotId(lots[0].id);
    }
  }, [lots, selectedLotId]);

  useEffect(() => {
    if (editingLotId !== selectedLot?.id) {
      setEditingLotId(selectedLot?.id ?? null);
      setLotForm({
        name: selectedLot?.name ?? "",
        description: selectedLot?.description ?? "",
        extra: buildCustomFieldDefaults(activeCustomFields, selectedLot?.extra ?? {})
      });
    }
  }, [activeCustomFields, selectedLot, editingLotId]);

  useEffect(() => {
    setLotForm((previous) => ({
      ...previous,
      extra: buildCustomFieldDefaults(activeCustomFields, previous.extra ?? {})
    }));
  }, [activeCustomFields]);

  const { data: lotItems = [], isLoading: isLoadingLotItems } = useQuery({
    queryKey: ["pharmacy-lot-items", selectedLotId],
    enabled: selectedLotId !== null,
    queryFn: async () => {
      const response = await api.get<PharmacyLotItem[]>(`/pharmacy/lots/${selectedLotId}/items`);
      return response.data;
    }
  });

  const { data: pharmacyItems = [] } = useQuery({
    queryKey: ["pharmacy"],
    queryFn: async () => {
      const response = await api.get<PharmacyItemOption[]>("/pharmacy/");
      return response.data;
    }
  });

  const createLot = useMutation({
    mutationFn: async (payload: { name: string; description: string | null; extra: Record<string, unknown> }) => {
      const response = await api.post<PharmacyLot>("/pharmacy/lots/", payload);
      return response.data;
    },
    onSuccess: async (data) => {
      setMessage("Lot créé.");
      setSelectedLotId(data.id);
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
      setLotForm({
        name: "",
        description: "",
        extra: buildCustomFieldDefaults(activeCustomFields, {})
      });
    },
    onError: () => setError("Impossible de créer le lot."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const updateLot = useMutation({
    mutationFn: async ({
      lotId,
      payload
    }: {
      lotId: number;
      payload: { name?: string; description?: string | null; extra?: Record<string, unknown> };
    }) => {
      const response = await api.put<PharmacyLot>(`/pharmacy/lots/${lotId}`, payload);
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Lot mis à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
    },
    onError: () => setError("Impossible de mettre à jour le lot."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const deleteLot = useMutation({
    mutationFn: async (lotId: number) => api.delete(`/pharmacy/lots/${lotId}`),
    onSuccess: async () => {
      setMessage("Lot supprimé.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
      setSelectedLotId(null);
    },
    onError: () => setError("Suppression du lot impossible."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const addLotItem = useMutation({
    mutationFn: async ({
      lotId,
      payload
    }: {
      lotId: number;
      payload: { pharmacy_item_id: number; quantity: number; compartment_name: string | null };
    }) => {
      const response = await api.post<PharmacyLotItem>(`/pharmacy/lots/${lotId}/items`, payload);
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Article ajouté au lot.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lot-items"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
      setLotItemForm({ pharmacy_item_id: "", quantity: 1, compartment_name: "" });
    },
    onError: (err) => {
      if (err instanceof Error) {
        setError(err.message || "Impossible d'ajouter l'article au lot.");
      } else {
        setError("Impossible d'ajouter l'article au lot.");
      }
    },
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const updateLotItem = useMutation({
    mutationFn: async ({ lotId, lotItemId, quantity }: { lotId: number; lotItemId: number; quantity: number }) => {
      const response = await api.put<PharmacyLotItem>(`/pharmacy/lots/${lotId}/items/${lotItemId}`, { quantity });
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Quantité mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lot-items"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
    },
    onError: () => setError("Impossible de modifier la quantité."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const removeLotItem = useMutation({
    mutationFn: async ({ lotId, lotItemId }: { lotId: number; lotItemId: number }) => {
      await api.delete(`/pharmacy/lots/${lotId}/items/${lotItemId}`);
    },
    onSuccess: async () => {
      setMessage("Article retiré du lot.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lot-items"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
    },
    onError: () => setError("Impossible de retirer l'article du lot."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const uploadImage = useMutation({
    mutationFn: async ({ lotId, file }: { lotId: number; file: File }) => {
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.post<PharmacyLot>(`/pharmacy/lots/${lotId}/image`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Image mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
    },
    onError: () => setError("Impossible d'envoyer l'image."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const removeImage = useMutation({
    mutationFn: async (lotId: number) => api.delete<PharmacyLot>(`/pharmacy/lots/${lotId}/image`),
    onSuccess: async () => {
      setMessage("Image supprimée.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-lots"] });
    },
    onError: () => setError("Impossible de supprimer l'image."),
    onSettled: () => setTimeout(() => setMessage(null), 3000)
  });

  const handleSubmitLot = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!lotForm.name.trim()) {
      return;
    }
    setError(null);
    if (editingLotId) {
      void updateLot.mutateAsync({
        lotId: editingLotId,
        payload: {
          ...lotForm,
          description: lotForm.description || null
        }
      });
    } else {
      void createLot.mutateAsync({
        name: lotForm.name.trim(),
        description: lotForm.description.trim() || null,
        extra: lotForm.extra
      });
    }
  };

  const handleAddLotItem = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedLotId || !lotItemForm.pharmacy_item_id) return;
    setError(null);
    void addLotItem.mutateAsync({
      lotId: selectedLotId,
      payload: {
        pharmacy_item_id: Number(lotItemForm.pharmacy_item_id),
        quantity: lotItemForm.quantity,
        compartment_name: lotItemForm.compartment_name.trim() || null
      }
    });
  };

  const selectedLotImage = resolveMediaUrl(selectedLot?.image_url ?? null);
  const compartmentOptions = useMemo(
    () =>
      Array.from(
        new Set(
          lotItems
            .map((item) => item.compartment_name)
            .filter((value): value is string => Boolean(value && value.trim()))
        )
      ),
    [lotItems]
  );
  const formatCompartment = (value: string | null) => (value && value.trim() ? value : "Général");

  return (
    <section className="mt-6 min-w-0 space-y-3 rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">Lots pharmacie</h3>
          <p className="text-xs text-slate-400">
            Préparez des kits composés de plusieurs articles pharmaceutiques et vérifiez les quantités disponibles.
          </p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => {
              setEditingLotId(null);
              setLotForm({ name: "", description: "" });
            }}
            className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400"
          >
            Nouveau lot
          </button>
        ) : null}
      </div>

      {message ? <p className="text-xs font-semibold text-emerald-400">{message}</p> : null}
      {error ? <p className="text-xs font-semibold text-red-400">{error}</p> : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <div className="overflow-hidden rounded border border-slate-800 bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              <span>Lots disponibles</span>
              <span>{lots.length}</span>
            </div>
            <div className="divide-y divide-slate-800">
              {lots.length === 0 ? (
                <p className="p-4 text-sm text-slate-400">Aucun lot défini pour le moment.</p>
              ) : (
                lots.map((lot) => {
                  const isSelected = lot.id === selectedLotId;
                  const imageUrl = resolveMediaUrl(lot.image_url);
                  return (
                    <button
                      key={lot.id}
                      type="button"
                      onClick={() => setSelectedLotId(lot.id)}
                      className={`flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-800/60 ${
                        isSelected ? "bg-slate-800/80" : ""
                      }`}
                    >
                      <div className="h-12 w-12 overflow-hidden rounded border border-slate-800 bg-slate-950">
                        {imageUrl ? (
                          <img src={imageUrl} alt={lot.name} className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-500">Aucune</div>
                        )}
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-white">{lot.name}</p>
                        <p className="text-xs text-slate-400 line-clamp-2">{lot.description || "Pas de description"}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                          <span>{lot.item_count} article(s)</span>
                          <span className="text-slate-500">•</span>
                          <span>{lot.total_quantity} pièce(s)</span>
                          <span className="text-slate-500">•</span>
                          <span>Créé le {formatDate(lot.created_at)}</span>
                        </div>
                      </div>
                      {canEdit ? (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!window.confirm("Supprimer définitivement ce lot ?")) return;
                            setError(null);
                            void deleteLot.mutateAsync(lot.id);
                          }}
                          className="text-[11px] font-semibold uppercase tracking-wide text-red-400 hover:text-red-300"
                        >
                          Supprimer
                        </button>
                      ) : null}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-3">
          {canEdit ? (
            <form className="rounded border border-slate-800 bg-slate-900 p-3" onSubmit={handleSubmitLot}>
              <h4 className="text-sm font-semibold text-white">{editingLotId ? "Modifier le lot" : "Créer un lot"}</h4>
              <div className="mt-2 space-y-2 text-sm text-slate-200">
                <div>
                  <label className="text-xs font-semibold text-slate-300" htmlFor="lot-name">
                    Nom
                  </label>
                  <AppTextInput
                    id="lot-name"
                    value={lotForm.name}
                    onChange={(event) => setLotForm((previous) => ({ ...previous, name: event.target.value }))}
                    className="mt-1 w-full rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                    required
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300" htmlFor="lot-description">
                    Description
                  </label>
                  <AppTextArea
                    id="lot-description"
                    value={lotForm.description}
                    onChange={(event) => setLotForm((previous) => ({ ...previous, description: event.target.value }))}
                    className="mt-1 w-full rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                    rows={3}
                  />
                </div>
                {activeCustomFields.length > 0 ? (
                  <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Champs personnalisés
                    </p>
                    <div className="mt-3">
                      <CustomFieldsForm
                        definitions={activeCustomFields}
                        values={lotForm.extra}
                        onChange={(next) => setLotForm((prev) => ({ ...prev, extra: next }))}
                        disabled={!canEdit || createLot.isPending || updateLot.isPending}
                      />
                    </div>
                  </div>
                ) : null}
                <button
                  type="submit"
                  className="rounded bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                  disabled={createLot.isPending || updateLot.isPending}
                >
                  {createLot.isPending || updateLot.isPending ? "Enregistrement..." : "Enregistrer"}
                </button>
              </div>
            </form>
          ) : null}

          <div className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-semibold text-white">Contenu du lot</h4>
                <p className="text-xs text-slate-400">Sélectionnez un lot pour gérer ses articles.</p>
              </div>
              {canEdit && selectedLot ? (
                <div className="flex items-center gap-2 text-xs text-slate-300">
                  <AppTextInput
                    type="file"
                    ref={fileInputRef}
                    accept="image/*"
                    className="hidden"
                    onChange={(event: ChangeEvent<HTMLInputElement>) => {
                      const file = event.target.files?.[0];
                      if (!file || !selectedLotId) return;
                      setError(null);
                      void uploadImage.mutateAsync({ lotId: selectedLotId, file });
                      event.target.value = "";
                    }}
                  />
                  <button
                    type="button"
                    className="rounded border border-slate-700 px-2 py-1 hover:bg-slate-800"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Image
                  </button>
                  {selectedLot?.image_url ? (
                    <button
                      type="button"
                      className="rounded border border-red-700 px-2 py-1 text-red-300 hover:bg-red-900/30"
                      onClick={() => selectedLotId && removeImage.mutate(selectedLotId)}
                    >
                      Retirer
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>

            {selectedLot ? (
              <div className="mt-3 space-y-3">
                {selectedLotImage ? (
                  <div className="overflow-hidden rounded border border-slate-800">
                    <img src={selectedLotImage} alt={`Illustration ${selectedLot.name}`} className="h-36 w-full object-cover" />
                  </div>
                ) : null}

                {canEdit ? (
                  <form className="flex flex-wrap items-end gap-2" onSubmit={handleAddLotItem}>
                    <div className="flex-1 min-w-0">
                      <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-400" htmlFor="pharmacy-lot-item">
                        Article
                      </label>
                      <select
                        id="pharmacy-lot-item"
                        value={lotItemForm.pharmacy_item_id}
                        onChange={(event) => setLotItemForm((previous) => ({ ...previous, pharmacy_item_id: event.target.value }))}
                        className="mt-1 w-full rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                        required
                      >
                        <option value="">Choisir un article</option>
                        {pharmacyItems.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name} (Stock: {item.quantity}{item.barcode ? ` - ${item.barcode}` : ""})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="flex-1 min-w-0 sm:max-w-xs">
                      <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-400" htmlFor="pharmacy-lot-compartment">
                        Compartiment
                      </label>
                      <AppTextInput
                        id="pharmacy-lot-compartment"
                        list="pharmacy-lot-compartment-options"
                        value={lotItemForm.compartment_name}
                        onChange={(event) =>
                          setLotItemForm((previous) => ({ ...previous, compartment_name: event.target.value }))
                        }
                        placeholder="Ex: Poche gauche"
                        className="mt-1 w-full rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                      />
                      {compartmentOptions.length > 0 ? (
                        <datalist id="pharmacy-lot-compartment-options">
                          {compartmentOptions.map((option) => (
                            <option key={option} value={option} />
                          ))}
                        </datalist>
                      ) : null}
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-400" htmlFor="pharmacy-lot-quantity">
                        Quantité
                      </label>
                      <AppTextInput
                        id="pharmacy-lot-quantity"
                        type="number"
                        min={1}
                        value={lotItemForm.quantity}
                        onChange={(event) =>
                          setLotItemForm((previous) => ({ ...previous, quantity: Number(event.target.value) }))
                        }
                        className="mt-1 w-24 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                        required
                      />
                    </div>
                    <button
                      type="submit"
                      className="rounded bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                      disabled={addLotItem.isPending}
                    >
                      {addLotItem.isPending ? "Ajout..." : "Ajouter"}
                    </button>
                  </form>
                ) : null}

                <div className="overflow-hidden rounded border border-slate-800">
                  <table className="min-w-full divide-y divide-slate-800 text-sm text-slate-100">
                    <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-3 py-2 text-left">Article</th>
                        <th className="px-3 py-2 text-left">Compartiment</th>
                        <th className="px-3 py-2 text-left">Quantité réservée</th>
                        <th className="px-3 py-2 text-left">Stock disponible</th>
                        {canEdit ? <th className="px-3 py-2 text-left">Actions</th> : null}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 bg-slate-950/40">
                      {isLoadingLotItems ? (
                        <tr>
                          <td colSpan={canEdit ? 5 : 4} className="px-3 py-3 text-center text-sm text-slate-400">
                            Chargement...
                          </td>
                        </tr>
                      ) : lotItems.length === 0 ? (
                        <tr>
                          <td colSpan={canEdit ? 5 : 4} className="px-3 py-3 text-center text-sm text-slate-400">
                            Aucun article dans ce lot.
                          </td>
                        </tr>
                      ) : (
                        lotItems.map((item) => (
                          <tr key={item.id}>
                            <td className="px-3 py-2">
                              <div className="font-semibold text-white">{item.pharmacy_name}</div>
                              <div className="text-xs text-slate-400">{item.pharmacy_sku || "Sans code-barres"}</div>
                            </td>
                            <td className="px-3 py-2 text-slate-200">{formatCompartment(item.compartment_name)}</td>
                            <td className="px-3 py-2 text-slate-200">{item.quantity}</td>
                            <td className="px-3 py-2 text-slate-200">{item.available_quantity}</td>
                            {canEdit ? (
                              <td className="px-3 py-2 text-xs text-slate-200">
                                <div className="flex flex-wrap gap-2">
                                  <AppTextInput
                                    type="number"
                                    min={1}
                                    defaultValue={item.quantity}
                                    className="w-20 rounded border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-white focus:border-indigo-500 focus:outline-none"
                                    onChange={(event) => {
                                      const value = Number(event.target.value);
                                      updateLotItem.mutate({ lotId: item.lot_id, lotItemId: item.id, quantity: value });
                                    }}
                                  />
                                  <button
                                    type="button"
                                    className="rounded bg-red-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-red-500"
                                    onClick={() => removeLotItem.mutate({ lotId: item.lot_id, lotItemId: item.id })}
                                  >
                                    Retirer
                                  </button>
                                </div>
                              </td>
                            ) : null}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-400">Sélectionnez un lot pour afficher son contenu.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
