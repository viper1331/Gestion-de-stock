import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { CustomFieldsForm } from "../../components/CustomFieldsForm";
import { api } from "../../lib/api";
import { buildCustomFieldDefaults, CustomFieldDefinition } from "../../lib/customFields";
import { resolveMediaUrl } from "../../lib/media";
import { useAuth } from "../auth/useAuth";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";

const LOT_CARDS_COLLAPSED_STORAGE_KEY = "remiseLots:lotCardsCollapsed";
const STOCK_CARDS_COLLAPSED_STORAGE_KEY = "remiseLots:stockCardsCollapsed";

interface RemiseLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  image_url: string | null;
  item_count: number;
  total_quantity: number;
  extra?: Record<string, unknown>;
}

interface RemiseLotItem {
  id: number;
  lot_id: number;
  remise_item_id: number;
  quantity: number;
  remise_name: string;
  remise_sku: string;
  size: string | null;
  available_quantity: number;
}

interface RemiseInventoryItem {
  id: number;
  name: string;
  sku: string;
  size: string | null;
  quantity: number;
}

interface RemiseLotWithItems extends RemiseLot {
  items: RemiseLotItem[];
}

interface LotFormState {
  name: string;
  description: string;
  extra: Record<string, unknown>;
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

function areExtraValuesEqual(
  current: Record<string, unknown> = {},
  next: Record<string, unknown> = {}
) {
  const currentKeys = Object.keys(current);
  const nextKeys = Object.keys(next);
  if (currentKeys.length !== nextKeys.length) {
    return false;
  }
  return currentKeys.every((key) => Object.is(current[key], next[key]));
}

export function RemiseLotsPanel() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const [selectedLotId, setSelectedLotId] = useState<number | null>(null);
  const [lotForm, setLotForm] = useState<LotFormState>({ name: "", description: "", extra: {} });
  const [editingLotId, setEditingLotId] = useState<number | null>(null);
  const [lotItemForm, setLotItemForm] = useState<LotItemFormState>({ remise_item_id: "", quantity: 1 });
  const [editQuantities, setEditQuantities] = useState<Record<number, number>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLotsPanelCollapsed, setIsLotsPanelCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    try {
      return window.localStorage.getItem(LOT_CARDS_COLLAPSED_STORAGE_KEY) === "true";
    } catch (err) {
      console.warn("Impossible de lire l'état de masquage des cartes lots", err);
      return false;
    }
  });
  const [isStockLotsCollapsed, setIsStockLotsCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    try {
      return window.localStorage.getItem(STOCK_CARDS_COLLAPSED_STORAGE_KEY) === "true";
    } catch (err) {
      console.warn("Impossible de lire l'état de masquage des cartes lots en stock", err);
      return false;
    }
  });
  const lotImageInputRef = useRef<HTMLInputElement | null>(null);

  const lotsQuery = useQuery({
    queryKey: ["remise-lots"],
    queryFn: async () => {
      const response = await api.get<RemiseLot[]>("/remise-inventory/lots/");
      return response.data;
    }
  });

  const lots = lotsQuery.data ?? [];

  const { data: customFieldDefinitions = [] } = useQuery({
    queryKey: ["custom-fields", "remise_lots"],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: "remise_lots" }
      });
      return response.data;
    },
    enabled: isAdmin
  });
  const activeCustomFields = useMemo(
    () => customFieldDefinitions.filter((definition) => definition.is_active),
    [customFieldDefinitions]
  );

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

  useEffect(() => {
    // Synchroniser les valeurs custom uniquement si le calcul apporte réellement des changements.
    setLotForm((prev) => {
      const nextExtra = buildCustomFieldDefaults(activeCustomFields, prev.extra ?? {});
      if (areExtraValuesEqual(prev.extra ?? {}, nextExtra)) {
        return prev;
      }
      return {
        ...prev,
        extra: nextExtra
      };
    });
  }, [activeCustomFields]);

  const selectedLot = useMemo(
    () => lots.find((lot) => lot.id === selectedLotId) ?? null,
    [lots, selectedLotId]
  );

  const selectedLotImageUrl = resolveMediaUrl(selectedLot?.image_url);

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

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(LOT_CARDS_COLLAPSED_STORAGE_KEY, String(isLotsPanelCollapsed));
    } catch (err) {
      console.warn("Impossible d'enregistrer l'état de masquage des cartes lots", err);
    }
  }, [isLotsPanelCollapsed]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(STOCK_CARDS_COLLAPSED_STORAGE_KEY, String(isStockLotsCollapsed));
    } catch (err) {
      console.warn("Impossible d'enregistrer l'état de masquage des cartes lots en stock", err);
    }
  }, [isStockLotsCollapsed]);

  const resetLotForm = () => {
    setEditingLotId(null);
    setLotForm({
      name: "",
      description: "",
      extra: buildCustomFieldDefaults(activeCustomFields, {})
    });
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

  const uploadLotImage = useMutation({
    mutationFn: async ({ lotId, file }: { lotId: number; file: File }) => {
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.post<RemiseLot>(`/remise-inventory/lots/${lotId}/image`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Image du lot mise à jour.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lot-items"] })
      ]);
    },
    onError: () => setError("Impossible de mettre à jour l'image du lot.")
  });

  const removeLotImage = useMutation({
    mutationFn: async (lotId: number) => {
      await api.delete(`/remise-inventory/lots/${lotId}/image`);
    },
    onSuccess: async () => {
      setMessage("Image du lot supprimée.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lot-items"] })
      ]);
    },
    onError: () => setError("Impossible de supprimer l'image du lot.")
  });

  const handleSubmitLot = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    const payload: LotFormState = {
      name: lotForm.name.trim(),
      description: lotForm.description.trim(),
      extra: lotForm.extra
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

  const isUpdatingLotImage = uploadLotImage.isPending || removeLotImage.isPending;

  const handleLotImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!selectedLotId) {
      event.currentTarget.value = "";
      return;
    }
    const file = (event.currentTarget.files ?? [])[0];
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setError("Seules les images sont autorisées.");
      event.currentTarget.value = "";
      return;
    }
    setMessage(null);
    setError(null);
    uploadLotImage.mutate({ lotId: selectedLotId, file });
    event.currentTarget.value = "";
  };

  const handleSelectLotImage = () => {
    if (!selectedLotId || isUpdatingLotImage) return;
    lotImageInputRef.current?.click();
  };

  const handleRemoveLotImage = () => {
    if (!selectedLotId || isUpdatingLotImage) return;
    setMessage(null);
    setError(null);
    removeLotImage.mutate(selectedLotId);
  };

  const availableForForm = useMemo(
    () =>
      availableItems.map((item) => ({
        id: item.id,
        label: `${item.name}${item.size ? ` — ${item.size}` : ""} (${item.sku})`,
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
        <button
          type="button"
          onClick={() => setIsLotsPanelCollapsed((value) => !value)}
          aria-expanded={!isLotsPanelCollapsed}
          className="self-start rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 transition hover:bg-slate-800"
        >
          {isLotsPanelCollapsed ? "Afficher" : "Masquer"} les cartes
        </button>
      </div>

      {message ? <Alert tone="success" message={message} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}

      {isLotsPanelCollapsed ? (
        <p className="rounded-md border border-dashed border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
          Cartes masquées. Cliquez sur « Afficher les cartes » pour gérer les lots de remise.
        </p>
      ) : (
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
                          description: lot.description ?? "",
                          extra: buildCustomFieldDefaults(activeCustomFields, lot.extra ?? {})
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
                <AppTextInput
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
                <AppTextArea
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
              {activeCustomFields.length > 0 ? (
                <div className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Champs personnalisés
                  </p>
                  <div className="mt-3">
                    <CustomFieldsForm
                      definitions={activeCustomFields}
                      values={lotForm.extra}
                      onChange={(next) => setLotForm((prev) => ({ ...prev, extra: next }))}
                      disabled={createLot.isPending || updateLot.isPending}
                    />
                  </div>
                </div>
              ) : null}
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
                <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Image du lot
                      </p>
                      <p className="text-xs text-slate-400">
                        Ajoutez une photo de référence pour reconnaître rapidement ce lot.
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={handleSelectLotImage}
                        disabled={isUpdatingLotImage}
                        className="rounded-full border border-indigo-400 px-3 py-1 text-[11px] font-semibold text-indigo-200 transition hover:border-indigo-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isUpdatingLotImage
                          ? "Téléversement..."
                          : selectedLot.image_url
                            ? "Changer d'image"
                            : "Ajouter une image"}
                      </button>
                      {selectedLot.image_url ? (
                        <button
                          type="button"
                          onClick={handleRemoveLotImage}
                          disabled={isUpdatingLotImage}
                          className="rounded-full border border-rose-400 px-3 py-1 text-[11px] font-semibold text-rose-200 transition hover:border-rose-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Supprimer
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="mt-3 flex h-40 items-center justify-center overflow-hidden rounded-md border border-dashed border-slate-800 bg-slate-950/40 p-2">
                    {selectedLotImageUrl ? (
                      <img
                        src={selectedLotImageUrl}
                        alt={`Illustration du lot ${selectedLot.name}`}
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      <p className="text-xs text-slate-500">Aucune image n'est associée à ce lot.</p>
                    )}
                  </div>
                  <AppTextInput
                    ref={lotImageInputRef}
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    onChange={handleLotImageChange}
                  />
                </div>

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
                    <AppTextInput
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

                <div className="min-w-0 overflow-auto rounded-md border border-slate-800">
                  <table className="w-full min-w-full divide-y divide-slate-800">
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
                                <p className="text-xs text-slate-400">
                                  Taille / Variante : {item.size ?? "—"}
                                </p>
                              </td>
                              <td className="px-3 py-3 text-sm text-slate-200">
                                <AppTextInput
                                  type="number"
                                  min={1}
                                  value={quantityValue}
                                  onChange={(event) =>
                                    setEditQuantities((prev) => ({
                                      ...prev,
                                      [item.id]: Number(event.target.value)
                                    }))
                                  }
                                  className="w-full min-w-0 rounded-md border border-slate-800 bg-slate-900 px-2 py-1 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
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
      )}

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
          <button
            type="button"
            onClick={() => setIsStockLotsCollapsed((value) => !value)}
            aria-expanded={!isStockLotsCollapsed}
            className="self-start rounded-md border border-slate-700 px-3 py-1 text-[11px] font-semibold text-slate-200 transition hover:bg-slate-800"
          >
            {isStockLotsCollapsed ? "Afficher" : "Masquer"}
          </button>
        </div>

        {isStockLotsCollapsed ? (
          <p className="rounded-md border border-dashed border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
            Cartes masquées. Cliquez sur « Afficher » pour consulter les lots en stock.
          </p>
        ) : lotsWithItemsQuery.isLoading ? (
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
                <div className="overflow-hidden rounded-md border border-slate-800">
                  {lot.image_url ? (
                    <img
                      src={resolveMediaUrl(lot.image_url) ?? undefined}
                      alt={`Illustration du lot ${lot.name}`}
                      className="h-32 w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-32 items-center justify-center text-xs text-slate-500">
                      Aucune image enregistrée
                    </div>
                  )}
                </div>
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
                          <p className="text-xs text-slate-400">
                            Taille / Variante : {item.size ?? "—"}
                          </p>
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
