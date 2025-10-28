import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";

interface Supplier {
  id: number;
  name: string;
}

interface PharmacyItemOption {
  id: number;
  name: string;
}

interface PharmacyPurchaseOrderItem {
  id: number;
  pharmacy_item_id: number;
  pharmacy_item_name: string | null;
  quantity_ordered: number;
  quantity_received: number;
}

interface PharmacyPurchaseOrderDetail {
  id: number;
  supplier_id: number | null;
  supplier_name: string | null;
  status: string;
  created_at: string;
  note: string | null;
  items: PharmacyPurchaseOrderItem[];
}

interface PharmacyOrderDraftLine {
  pharmacyItemId: number | "";
  quantity: number;
}

const ORDER_STATUSES: Array<{ value: string; label: string }> = [
  { value: "PENDING", label: "En attente" },
  { value: "ORDERED", label: "Commandé" },
  { value: "PARTIALLY_RECEIVED", label: "Partiellement reçu" },
  { value: "RECEIVED", label: "Reçu" },
  { value: "CANCELLED", label: "Annulé" }
];

export function PharmacyOrdersPanel({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [draftLines, setDraftLines] = useState<PharmacyOrderDraftLine[]>([
    { pharmacyItemId: "", quantity: 1 }
  ]);
  const [draftSupplier, setDraftSupplier] = useState<number | "">("");
  const [draftStatus, setDraftStatus] = useState<string>("ORDERED");
  const [draftNote, setDraftNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["pharmacy-orders"],
    queryFn: async () => {
      const response = await api.get<PharmacyPurchaseOrderDetail[]>("/pharmacy/orders/");
      return response.data;
    }
  });

  const { data: pharmacyItems = [] } = useQuery({
    queryKey: ["pharmacy-items-options"],
    queryFn: async () => {
      const response = await api.get<PharmacyItemOption[]>("/pharmacy/");
      return response.data;
    }
  });

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers", { module: "pharmacy" }],
    queryFn: async () => {
      const response = await api.get<Supplier[]>("/suppliers/", {
        params: { module: "pharmacy" }
      });
      return response.data;
    },
    enabled: canEdit
  });

  const createOrder = useMutation({
    mutationFn: async (payload: {
      supplier_id: number | null;
      status: string;
      note: string | null;
      items: Array<{ pharmacy_item_id: number; quantity_ordered: number }>;
    }) => {
      await api.post("/pharmacy/orders/", payload);
    },
    onSuccess: async () => {
      setMessage("Bon de commande créé.");
      setDraftLines([{ pharmacyItemId: "", quantity: 1 }]);
      setDraftSupplier("");
      setDraftStatus("ORDERED");
      setDraftNote("");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de créer le bon de commande."),
    onSettled: () => window.setTimeout(() => setMessage(null), 4000)
  });

  const updateStatus = useMutation({
    mutationFn: async ({ orderId, status }: { orderId: number; status: string }) => {
      await api.put(`/pharmacy/orders/${orderId}`, { status });
    },
    onSuccess: async () => {
      setMessage("Statut mis à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
    },
    onError: () => setError("Impossible de mettre à jour le statut."),
    onSettled: () => window.setTimeout(() => setMessage(null), 4000)
  });

  const receiveOrder = useMutation({
    mutationFn: async ({
      orderId,
      items
    }: {
      orderId: number;
      items: Array<{ pharmacy_item_id: number; quantity: number }>;
    }) => {
      await api.post(`/pharmacy/orders/${orderId}/receive`, { items });
    },
    onSuccess: async () => {
      setMessage("Réception enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible d'enregistrer la réception."),
    onSettled: () => window.setTimeout(() => setMessage(null), 4000)
  });

  const handleAddLine = () => {
    setDraftLines((prev) => [...prev, { pharmacyItemId: "", quantity: 1 }]);
  };

  const handleRemoveLine = (index: number) => {
    setDraftLines((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    const normalizedLines = draftLines
      .filter((line) => line.pharmacyItemId !== "" && line.quantity > 0)
      .map((line) => ({ pharmacy_item_id: Number(line.pharmacyItemId), quantity_ordered: line.quantity }));
    if (normalizedLines.length === 0) {
      setError("Ajoutez au moins un article dans le bon de commande.");
      return;
    }
    await createOrder.mutateAsync({
      supplier_id: draftSupplier === "" ? null : Number(draftSupplier),
      status: draftStatus,
      note: draftNote.trim() ? draftNote.trim() : null,
      items: normalizedLines
    });
  };

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Bons de commande pharmacie</h3>
          <p className="text-sm text-slate-400">
            Centralisez les commandes auprès des fournisseurs et mettez à jour les stocks lors des réceptions.
          </p>
        </div>
      </header>

      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Créé le</th>
                  <th className="px-4 py-3 text-left">Fournisseur</th>
                  <th className="px-4 py-3 text-left">Statut</th>
                  <th className="px-4 py-3 text-left">Lignes</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900 bg-slate-950/60 text-sm text-slate-100">
                {orders.map((order) => {
                  const outstanding = order.items
                    .map((line) => ({
                      pharmacy_item_id: line.pharmacy_item_id,
                      quantity: line.quantity_ordered - line.quantity_received
                    }))
                    .filter((line) => line.quantity > 0);
                  const canReceive = outstanding.length > 0;
                  return (
                    <tr key={order.id}>
                      <td className="px-4 py-3 text-slate-300">
                        {new Date(order.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-slate-200">{order.supplier_name ?? "-"}</td>
                      <td className="px-4 py-3 text-slate-200">
                        <select
                          value={order.status}
                          onChange={(event) =>
                            updateStatus.mutate({ orderId: order.id, status: event.target.value })
                          }
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
                          disabled={!canEdit}
                        >
                          {ORDER_STATUSES.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3 text-slate-200">
                        <ul className="space-y-1 text-xs">
                          {order.items.map((line) => (
                            <li key={line.id}>
                              <span className="font-semibold">
                                {line.pharmacy_item_name ?? `#${line.pharmacy_item_id}`}
                              </span>
                              {": "}
                              <span>
                                {line.quantity_received}/{line.quantity_ordered}
                              </span>
                            </li>
                          ))}
                          {order.note ? (
                            <li className="text-slate-400">Note: {order.note}</li>
                          ) : null}
                        </ul>
                      </td>
                      <td className="px-4 py-3 text-slate-200">
                        <button
                          type="button"
                          onClick={() =>
                            receiveOrder.mutate({ orderId: order.id, items: outstanding })
                          }
                          disabled={!canEdit || !canReceive}
                          className="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                          title={
                            canReceive
                              ? "Enregistrer la réception des quantités restantes"
                              : "Toutes les quantités ont été réceptionnées"
                          }
                        >
                          Réceptionner tout
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {orders.length === 0 && !isLoading ? (
                  <tr>
                    <td className="px-4 py-4 text-sm text-slate-400" colSpan={5}>
                      Aucun bon de commande enregistré.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {isLoading ? <p className="text-sm text-slate-400">Chargement...</p> : null}
        </div>

        {canEdit ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h4 className="text-sm font-semibold text-white">Créer un bon de commande</h4>
            <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-order-supplier">
                  Fournisseur
                </label>
                <select
                  id="pharmacy-order-supplier"
                  value={draftSupplier}
                  onChange={(event) =>
                    setDraftSupplier(event.target.value ? Number(event.target.value) : "")
                  }
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                >
                  <option value="">Aucun</option>
                  {suppliers.map((supplier) => (
                    <option key={supplier.id} value={supplier.id}>
                      {supplier.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-order-status">
                  Statut initial
                </label>
                <select
                  id="pharmacy-order-status"
                  value={draftStatus}
                  onChange={(event) => setDraftStatus(event.target.value)}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                >
                  {ORDER_STATUSES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-order-note">
                  Note
                </label>
                <textarea
                  id="pharmacy-order-note"
                  value={draftNote}
                  onChange={(event) => setDraftNote(event.target.value)}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Informations complémentaires"
                />
              </div>

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Lignes de commande
                </p>
                {draftLines.map((line, index) => (
                  <div key={index} className="flex gap-2">
                    <select
                      value={line.pharmacyItemId}
                      onChange={(event) =>
                        setDraftLines((prev) => {
                          const next = [...prev];
                          next[index] = {
                            ...next[index],
                            pharmacyItemId: event.target.value ? Number(event.target.value) : ""
                          };
                          return next;
                        })
                      }
                      className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    >
                      <option value="">Sélectionnez un article</option>
                      {pharmacyItems.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={line.quantity}
                      onChange={(event) =>
                        setDraftLines((prev) => {
                          const next = [...prev];
                          next[index] = {
                            ...next[index],
                            quantity: Number(event.target.value)
                          };
                          return next;
                        })
                      }
                      className="w-28 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                    {draftLines.length > 1 ? (
                      <button
                        type="button"
                        onClick={() => handleRemoveLine(index)}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                        title="Supprimer la ligne"
                      >
                        Retirer
                      </button>
                    ) : null}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={handleAddLine}
                  className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                >
                  Ajouter une ligne
                </button>
              </div>

              <div className="flex justify-end">
                <button
                  type="submit"
                  className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
                  disabled={createOrder.isPending}
                >
                  Enregistrer
                </button>
              </div>
            </form>
          </div>
        ) : null}
      </div>
    </section>
  );
}
