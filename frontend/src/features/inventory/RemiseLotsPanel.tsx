import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { api } from "../../lib/api";

interface RemiseLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  item_count: number;
  total_quantity: number;
}

interface RemiseLotItem {
  id: number;
  lot_id: number;
  remise_item_id: number;
  quantity: number;
  remise_name: string;
  remise_sku: string;
  available_quantity: number;
}

interface RemiseInventoryItem {
  id: number;
  name: string;
  sku: string;
  quantity: number;
}

interface RemiseLotWithItems extends RemiseLot {
  items: RemiseLotItem[];
}

interface LotFormState {
  name: string;
  description: string;
}

interface LotItemFormState {
  remise_item_id: number | "";
  quantity: number;
}

function formatDate(value: string) {
  const date = new Date(value);
  return date.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric"
  });
}

export function RemiseLotsPanel() {
  const queryClient = useQueryClient();
  const [selectedLotId, setSelectedLotId] = useState<number | null>(null);
  const [lotForm, setLotForm] = useState<LotFormState>({ name: "", description: "" });
  const [editingLotId, setEditingLotId] = useState<number | null>(null);
  const [lotItemForm, setLotItemForm] = useState<LotItemFormState>({ remise_item_id: "", quantity: 1 });
  const [editQuantities, setEditQuantities] = useState<Record<number, number>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const lotsQuery = useQuery({
    queryKey: ["remise-lots"],
    queryFn: async () => {
      const response = await api.get<RemiseLot[]>("/remise-inventory/lots/");
      return response.data;
    }
  });

  const lots = lotsQuery.data ?? [];

  const lotsWithItemsQuery = useQuery({
    queryKey: ["remise-lots-with-items"],
    queryFn: async () => {
      const response = await api.get<RemiseLotWithItems[]>("/remise-inventory/lots/with-items");
      return response.data;
    }
  });

  const lotsWithItems = lotsWithItemsQuery.data ?? [];

  useEffect(() => {
    if (selectedLotId === null && lots.length > 0) {
      setSelectedLotId(lots[0].id);
    }
  }, [lots, selectedLotId]);

  const selectedLot = useMemo(
    () => lots.find((lot) => lot.id === selectedLotId) ?? null,
    [lots, selectedLotId]
  );

  const lotItemsQuery = useQuery({
    queryKey: ["remise-lot-items", selectedLotId],
    enabled: selectedLotId !== null,
    queryFn: async () => {
      if (!selectedLotId) return [] as RemiseLotItem[];
      const response = await api.get<RemiseLotItem[]>(`/remise-inventory/lots/${selectedLotId}/items`);
      return response.data;
    }
  });

  const lotItems = lotItemsQuery.data ?? [];

  const availableInventoryQuery = useQuery({
    queryKey: ["items", { module: "remise-lots" }],
    queryFn: async () => {
      const response = await api.get<RemiseInventoryItem[]>("/remise-inventory/");
      return response.data;
    }
  });

  const availableItems = useMemo(
    () => (availableInventoryQuery.data ?? []).filter((item) => item.quantity > 0),
    [availableInventoryQuery.data]
  );

  const resetLotForm = () => {
    setEditingLotId(null);
    setLotForm({ name: "", description: "" });
  };

  const createLot = useMutation({
    mutationFn: async (payload: LotFormState) => {
      const response = await api.post<RemiseLot>("/remise-inventory/lots/", payload);
      return response.data;
    },
    onSuccess: async (created) => {
      setMessage("Lot créé avec succès.");
      setSelectedLotId(created.id);
      setEditingLotId(created.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] })
      ]);
    },
    onError: () => setError("Impossible de créer le lot.")
  });

  const updateLot = useMutation({
    mutationFn: async ({ lotId, payload }: { lotId: number; payload: LotFormState }) => {
      const response = await api.put<RemiseLot>(`/remise-inventory/lots/${lotId}`, payload);
      return response.data;
    },
    onSuccess: async (updated) => {
      setMessage("Lot mis à jour.");
      setSelectedLotId(updated.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] })
      ]);
    },
    onError: () => setError("Impossible de mettre à jour le lot.")
  });

  const deleteLot = useMutation({
    mutationFn: async (lotId: number) => {
      await api.delete(`/remise-inventory/lots/${lotId}`);
    },
    onSuccess: async () => {
      setMessage("Lot supprimé.");
      setSelectedLotId(null);
      resetLotForm();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: () => setError("Suppression du lot impossible.")
  });

  const addLotItem = useMutation({
    mutationFn: async (payload: LotItemFormState & { lotId: number }) => {
      const response = await api.post<RemiseLotItem>(
        `/remise-inventory/lots/${payload.lotId}/items`,
        {
          remise_item_id: payload.remise_item_id,
          quantity: payload.quantity
        }
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Matériel ajouté au lot.");
      setLotItemForm((prev) => ({ ...prev, remise_item_id: "", quantity: 1 }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lot-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: () => setError("Impossible d'ajouter le matériel au lot.")
  });

  const updateLotItem = useMutation({
    mutationFn: async ({
      lotId,
      lotItemId,
      quantity
    }: {
      lotId: number;
      lotItemId: number;
      quantity: number;
    }) => {
      const response = await api.put<RemiseLotItem>(
        `/remise-inventory/lots/${lotId}/items/${lotItemId}`,
        { quantity }
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Quantité mise à jour.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lot-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: () => setError("Impossible de modifier la quantité.")
  });

  const removeLotItem = useMutation({
    mutationFn: async ({ lotId, lotItemId }: { lotId: number; lotItemId: number }) => {
      await api.delete(`/remise-inventory/lots/${lotId}/items/${lotItemId}`);
    },
    onSuccess: async () => {
      setMessage("Matériel retiré du lot.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lot-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: () => setError("Impossible de retirer le matériel.")
  });

  const handleSubmitLot = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    const payload: LotFormState = {
      name: lotForm.name.trim(),
      description: lotForm.description.trim()
    };
    if (editingLotId) {
      await updateLot.mutateAsync({ lotId: editingLotId, payload });
    } else {
      await createLot.mutateAsync(payload);
    }
  };

  const handleAddItem = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedLotId || !lotItemForm.remise_item_id) return;
    setMessage(null);
    setError(null);
    await addLotItem.mutateAsync({ lotId: selectedLotId, ...lotItemForm });
  };

  const handleUpdateQuantity = async (lotItemId: number) => {
    const fallbackQuantity = lotItems.find((entry) => entry.id === lotItemId)?.quantity ?? 0;
    const quantity = editQuantities[lotItemId] ?? fallbackQuantity;
    if (!selectedLotId || quantity <= 0) return;
    setMessage(null);
    setError(null);
    await updateLotItem.mutateAsync({ lotId: selectedLotId, lotItemId, quantity });
  };

  const handleDeleteLot = async () => {
    if (!editingLotId) return;
    if (!window.confirm("Supprimer définitivement ce lot ?")) return;
    setMessage(null);
    setError(null);
    await deleteLot.mutateAsync(editingLotId);
  };

  const handleRemoveItem = async (lotItemId: number) => {
    if (!selectedLotId) return;
    setMessage(null);
    setError(null);
    await removeLotItem.mutateAsync({ lotId: selectedLotId, lotItemId });
  };

  const availableForForm = useMemo(
    () => availableItems.map((item) => ({
      id: item.id,
      label: `${item.name} (${item.sku})`,
      quantity: item.quantity
    })),
    [availableItems]
  );

  return (
    <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/60 p-6 shadow">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-xl font-semibold text-white">Lots de remise</h3>
          <p className="text-sm text-slate-400">
            Créez des lots, ajustez leur contenu et réservez du matériel disponible.
          </p>
        </div>
      </div>

      {message ? <Alert tone="success" message={message} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4">
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-slate-200">Lots existants</h4>
              <button
                type="button"
                onClick={() => {
                  resetLotForm();
                  setSelectedLotId(null);
                }}
                className="rounded-md border border-indigo-600 px-3 py-1 text-xs font-semibold text-indigo-200 hover:bg-indigo-600/10"
              >
                Nouveau lot
              </button>
            </div>
            <div className="space-y-2">
              {lots.length === 0 ? (
                <p className="text-sm text-slate-400">Aucun lot défini pour le moment.</p>
              ) : (
                lots.map((lot) => {
                  const isSelected = lot.id === selectedLotId;
                  return (
                    <button
                      key={lot.id}
                      type="button"
                      onClick={() => {
                        setSelectedLotId(lot.id);
                        setEditingLotId(lot.id);
                        setLotForm({
                          name: lot.name,
                          description: lot.description ?? ""
                        });
                      }}
                      className={`w-full rounded-md border px-3 py-2 text-left transition ${
                        isSelected
                          ? "border-indigo-500 bg-indigo-900/40 text-white"
                          : "border-slate-800 bg-slate-900/60 text-slate-200 hover:border-indigo-500"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold">{lot.name}</p>
                          {lot.description ? (
                            <p className="text-xs text-slate-400">{lot.description}</p>
                          ) : null}
                          <p className="text-[11px] text-slate-500">Créé le {formatDate(lot.created_at)}</p>
                        </div>
                        <div className="text-right text-xs text-slate-300">
                          <p>{lot.item_count} matériel(s)</p>
                          <p className="text-slate-400">{lot.total_quantity} pièce(s)</p>
                        </div>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-slate-200">
                {editingLotId ? "Modifier le lot" : "Créer un lot"}
              </h4>
              {editingLotId ? (
                <button
                  type="button"
                  onClick={handleDeleteLot}
                  className="rounded-md border border-red-700 px-3 py-1 text-xs font-semibold text-red-200 hover:bg-red-800/30"
                >
                  Supprimer
                </button>
              ) : null}
            </div>
            <form className="space-y-3" onSubmit={handleSubmitLot}>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="lot-name">
                  Nom du lot
                </label>
                <input
                  id="lot-name"
                  type="text"
                  required
                  value={lotForm.name}
                  onChange={(event) => setLotForm((prev) => ({ ...prev, name: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Ex: Lot départ VSAV"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="lot-description">
                  Description
                </label>
                <textarea
                  id="lot-description"
                  value={lotForm.description}
                  onChange={(event) =>
                    setLotForm((prev) => ({ ...prev, description: event.target.value }))
                  }
                  className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  rows={3}
                  placeholder="Détails internes ou destination du lot"
                />
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                >
                  {editingLotId ? "Enregistrer" : "Créer"}
                </button>
                <button
                  type="button"
                  onClick={resetLotForm}
                  className="rounded-md border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
                >
                  Réinitialiser
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="lg:col-span-2">
          <div className="space-y-4 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h4 className="text-sm font-semibold text-slate-200">Contenu du lot</h4>
                <p className="text-xs text-slate-400">
                  {selectedLot
                    ? `${selectedLot.item_count} matériel(s) réservé(s), ${selectedLot.total_quantity} pièce(s) au total.`
                    : "Sélectionnez ou créez un lot pour y ajouter du matériel."}
                </p>
              </div>
              {selectedLot ? (
                <div className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300">
                  Stock réservé : {selectedLot.total_quantity}
                </div>
              ) : null}
            </div>

            {selectedLot ? (
              <>
                <form className="grid gap-3 rounded-md border border-slate-800 bg-slate-900/60 p-3 md:grid-cols-3" onSubmit={handleAddItem}>
                  <div className="md:col-span-2">
                    <label className="mb-1 block text-xs font-semibold text-slate-300" htmlFor="lot-item">
                      Matériel disponible
                    </label>
                    <select
                      id="lot-item"
                      required
                      value={lotItemForm.remise_item_id}
                      onChange={(event) =>
                        setLotItemForm((prev) => ({
                          ...prev,
                          remise_item_id: event.target.value ? Number(event.target.value) : ""
                        }))
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    >
                      <option value="">Sélectionner un matériel</option>
                      {availableForForm.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label} — {item.quantity} en stock
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-300" htmlFor="lot-quantity">
                      Quantité
                    </label>
                    <input
                      id="lot-quantity"
                      type="number"
                      min={1}
                      required
                      value={lotItemForm.quantity}
                      onChange={(event) =>
                        setLotItemForm((prev) => ({
                          ...prev,
                          quantity: Number(event.target.value) || 1
                        }))
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                  </div>
                  <div className="md:col-span-3 flex justify-end">
                    <button
                      type="submit"
                      className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                    >
                      Ajouter au lot
                    </button>
                  </div>
                </form>

                <div className="overflow-hidden rounded-md border border-slate-800">
                  <table className="min-w-full divide-y divide-slate-800">
                    <thead className="bg-slate-900/60">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Matériel
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Quantité lot
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Stock disponible
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 bg-slate-950/60">
                      {lotItems.length === 0 ? (
                        <tr>
                          <td className="px-3 py-3 text-sm text-slate-400" colSpan={4}>
                            Aucun matériel n'est encore réservé dans ce lot.
                          </td>
                        </tr>
                      ) : (
                        lotItems.map((item) => {
                          const quantityValue = editQuantities[item.id] ?? item.quantity;
                          return (
                            <tr key={item.id} className="bg-slate-950/40">
                              <td className="px-3 py-3 text-sm text-slate-100">
                                <p className="font-semibold">{item.remise_name}</p>
                                <p className="text-xs text-slate-400">SKU : {item.remise_sku}</p>
                              </td>
                              <td className="px-3 py-3 text-sm text-slate-200">
                                <input
                                  type="number"
                                  min={1}
                                  value={quantityValue}
                                  onChange={(event) =>
                                    setEditQuantities((prev) => ({
                                      ...prev,
                                      [item.id]: Number(event.target.value)
                                    }))
                                  }
                                  className="w-24 rounded-md border border-slate-800 bg-slate-900 px-2 py-1 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                                />
                              </td>
                              <td className="px-3 py-3 text-sm text-slate-200">{item.available_quantity}</td>
                              <td className="px-3 py-3 text-sm text-slate-200">
                                <div className="flex flex-wrap items-center gap-2">
                                  <button
                                    type="button"
                                    onClick={() => handleUpdateQuantity(item.id)}
                                    className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-500"
                                  >
                                    Mettre à jour
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveItem(item.id)}
                                    className="rounded-md border border-red-700 px-3 py-1 text-xs font-semibold text-red-200 hover:bg-red-800/30"
                                  >
                                    Retirer
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
              </>
            ) : (
              <div className="rounded-md border border-dashed border-slate-800 bg-slate-950/60 p-6 text-sm text-slate-400">
                Sélectionnez un lot pour afficher son contenu et réserver du matériel.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-200">Lots disponibles en stock</h4>
            <p className="text-xs text-slate-400">
              Consultez les lots créés et le détail du matériel réservé.
            </p>
          </div>
          <div className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] text-slate-300">
            {lotsWithItems.length} lot(s)
          </div>
        </div>

        {lotsWithItemsQuery.isLoading ? (
          <p className="text-sm text-slate-400">Chargement des lots...</p>
        ) : lotsWithItemsQuery.isError ? (
          <p className="text-sm text-red-300">Impossible de charger les lots détaillés.</p>
        ) : lotsWithItems.length === 0 ? (
          <p className="text-sm text-slate-400">Aucun lot en stock pour le moment.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {lotsWithItems.map((lot) => (
              <div
                key={lot.id}
                className="space-y-3 rounded-md border border-slate-800 bg-slate-900/60 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">{lot.name}</p>
                    {lot.description ? (
                      <p className="text-xs text-slate-400">{lot.description}</p>
                    ) : null}
                    <p className="text-[11px] text-slate-500">Créé le {formatDate(lot.created_at)}</p>
                  </div>
                  <div className="text-right text-xs text-slate-300">
                    <p>{lot.item_count} matériel(s)</p>
                    <p className="text-slate-400">{lot.total_quantity} pièce(s)</p>
                  </div>
                </div>

                {lot.items.length === 0 ? (
                  <p className="text-sm text-slate-400">Ce lot est encore vide.</p>
                ) : (
                  <ul className="divide-y divide-slate-800 rounded-md border border-slate-800 bg-slate-950/40">
                    {lot.items.map((item) => (
                      <li
                        key={item.id}
                        className="flex items-start justify-between gap-3 px-3 py-2 text-sm text-slate-100"
                      >
                        <div>
                          <p className="font-semibold">{item.remise_name}</p>
                          <p className="text-xs text-slate-400">SKU : {item.remise_sku}</p>
                        </div>
                        <div className="text-right text-xs text-slate-300">
                          <p>Réservé : {item.quantity}</p>
                          <p className="text-slate-400">Dispo : {item.available_quantity}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function Alert({ tone, message }: { tone: "success" | "error"; message: string }) {
  const toneClasses = tone === "success" ? "bg-emerald-900/30 text-emerald-100" : "bg-red-900/30 text-red-100";
  return (
    <div className={`rounded-md border px-4 py-2 text-sm ${toneClasses}`}>
      {message}
    </div>
  );
}

