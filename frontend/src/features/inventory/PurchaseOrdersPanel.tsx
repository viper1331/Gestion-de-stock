import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";

interface Supplier {
  id: number;
  name: string;
}

interface ItemOption {
  id: number;
  name: string;
}

interface PurchaseOrderItem {
  id: number;
  item_id: number;
  item_name: string | null;
  quantity_ordered: number;
  quantity_received: number;
}

interface PurchaseOrderDetail {
  id: number;
  supplier_id: number | null;
  supplier_name: string | null;
  status: string;
  created_at: string;
  note: string | null;
  auto_created: boolean;
  items: PurchaseOrderItem[];
}

interface CreateOrderPayload {
  supplier_id: number | null;
  status: string;
  note: string | null;
  items: Array<{ item_id: number; quantity_ordered: number }>;
}

interface ReceiveOrderPayload {
  orderId: number;
  items: Array<{ item_id: number; quantity: number }>;
}

const ORDER_STATUSES: Array<{ value: string; label: string }> = [
  { value: "PENDING", label: "En attente" },
  { value: "ORDERED", label: "Commandé" },
  { value: "PARTIALLY_RECEIVED", label: "Partiellement reçu" },
  { value: "RECEIVED", label: "Reçu" },
  { value: "CANCELLED", label: "Annulé" }
];

interface DraftLine {
  itemId: number | "";
  quantity: number;
}

export function PurchaseOrdersPanel({ suppliers }: { suppliers: Supplier[] }) {
  const queryClient = useQueryClient();
  const [draftSupplier, setDraftSupplier] = useState<number | "">("");
  const [draftStatus, setDraftStatus] = useState<string>("ORDERED");
  const [draftNote, setDraftNote] = useState("");
  const [draftLines, setDraftLines] = useState<DraftLine[]>([{ itemId: "", quantity: 1 }]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: orders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: async () => {
      const response = await api.get<PurchaseOrderDetail[]>("/purchase-orders/");
      return response.data;
    }
  });

  const { data: items = [] } = useQuery({
    queryKey: ["purchase-order-items-options"],
    queryFn: async () => {
      const response = await api.get<ItemOption[]>("/items/");
      return response.data;
    }
  });

  const createOrder = useMutation({
    mutationFn: async (payload: CreateOrderPayload) => {
      await api.post("/purchase-orders/", payload);
    },
    onSuccess: async () => {
      setMessage("Bon de commande créé.");
      setDraftLines([{ itemId: "", quantity: 1 }]);
      setDraftSupplier("");
      setDraftStatus("ORDERED");
      setDraftNote("");
      await queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError("Impossible de créer le bon de commande."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const updateStatus = useMutation({
    mutationFn: async ({ orderId, status }: { orderId: number; status: string }) => {
      await api.put(`/purchase-orders/${orderId}`, { status });
    },
    onSuccess: async (_, variables) => {
      setMessage("Statut mis à jour.");
      await queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      if (variables.status === "RECEIVED") {
        await queryClient.invalidateQueries({ queryKey: ["items"] });
      }
    },
    onError: () => setError("Impossible de mettre à jour le statut."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const receiveOrder = useMutation({
    mutationFn: async ({ orderId, items }: ReceiveOrderPayload) => {
      await api.post(`/purchase-orders/${orderId}/receive`, { items });
    },
    onSuccess: async () => {
      setMessage("Réception enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError("Impossible d'enregistrer la réception."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const handleAddLine = () => {
    setDraftLines((prev) => [...prev, { itemId: "", quantity: 1 }]);
  };

  const handleRemoveLine = (index: number) => {
    setDraftLines((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    const normalizedLines = draftLines
      .filter((line) => line.itemId !== "" && line.quantity > 0)
      .map((line) => ({ item_id: Number(line.itemId), quantity_ordered: line.quantity }));
    if (normalizedLines.length === 0) {
      setError("Ajoutez au moins une ligne de commande valide.");
      return;
    }
    const payload: CreateOrderPayload = {
      supplier_id: draftSupplier === "" ? null : Number(draftSupplier),
      status: draftStatus,
      note: draftNote.trim() ? draftNote.trim() : null,
      items: normalizedLines
    };
    await createOrder.mutateAsync(payload);
  };

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Bons de commande</h3>
          <p className="text-sm text-slate-400">
            Suivez les commandes fournisseurs et marquez les réceptions pour mettre à jour les stocks.
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
                      item_id: line.item_id,
                      quantity: line.quantity_ordered - line.quantity_received
                    }))
                    .filter((line) => line.quantity > 0);
                  const canReceive = outstanding.length > 0;
                  return (
                    <tr key={order.id}>
                      <td className="px-4 py-3 text-slate-300">
                        {new Date(order.created_at).toLocaleString()}
                        {order.auto_created ? (
                          <span className="ml-2 rounded border border-indigo-500/40 bg-indigo-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-indigo-200">
                            Auto
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-slate-200">{order.supplier_name ?? "-"}</td>
                      <td className="px-4 py-3 text-slate-200">
                        <select
                          value={order.status}
                          onChange={(event) =>
                            updateStatus.mutate({ orderId: order.id, status: event.target.value })
                          }
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
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
                              <span className="font-semibold">{line.item_name ?? `#${line.item_id}`}</span>
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
                        <div className="flex flex-col gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              receiveOrder.mutate({ orderId: order.id, items: outstanding })
                            }
                            disabled={!canReceive}
                            className="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                            title={
                              canReceive
                                ? "Enregistrer la réception des quantités restantes"
                                : "Toutes les quantités ont été réceptionnées"
                            }
                          >
                            Réceptionner tout
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {orders.length === 0 && !loadingOrders ? (
                  <tr>
                    <td className="px-4 py-4 text-sm text-slate-400" colSpan={5}>
                      Aucun bon de commande pour le moment.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {loadingOrders ? (
            <p className="text-sm text-slate-400">Chargement des bons de commande...</p>
          ) : null}
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h4 className="text-sm font-semibold text-white">Créer un bon de commande</h4>
          <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300" htmlFor="po-supplier">
                Fournisseur
              </label>
              <select
                id="po-supplier"
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
              <label className="text-xs font-semibold text-slate-300" htmlFor="po-status">
                Statut initial
              </label>
              <select
                id="po-status"
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
              <label className="text-xs font-semibold text-slate-300" htmlFor="po-note">
                Note
              </label>
              <textarea
                id="po-note"
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
                    value={line.itemId}
                    onChange={(event) =>
                      setDraftLines((prev) => {
                        const next = [...prev];
                        next[index] = {
                          ...next[index],
                          itemId: event.target.value ? Number(event.target.value) : ""
                        };
                        return next;
                      })
                    }
                    className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="">Sélectionnez un article</option>
                    {items.map((item) => (
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
      </div>
    </section>
  );
}
