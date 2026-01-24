import { FormEvent, useMemo, useState } from "react";
import { QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import {
  formatPurchaseOrderItemLabel,
  type BarcodeLookupItem,
  type PurchaseOrderItemLabelData,
  usePurchaseOrderBarcodeScan
} from "../purchasing/usePurchaseOrderBarcodeScan";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { DraggableModal } from "components/DraggableModal";
import { PurchaseOrderCreateModal } from "components/PurchaseOrderCreateModal";

interface Supplier {
  id: number;
  name: string;
  email: string | null;
  address: string | null;
}

interface ItemOption {
  id: number;
  name: string;
  sku?: string | null;
  size?: string | null;
  quantity?: number | null;
  supplier_id?: number | null;
  extra?: Record<string, unknown>;
}

type ItemIdKey = "item_id" | "remise_item_id" | "pharmacy_item_id";

interface PurchaseOrderItem {
  id: number;
  item_id?: number;
  remise_item_id?: number;
  pharmacy_item_id?: number;
  item_name: string | null;
  quantity_ordered: number;
  quantity_received: number;
}

interface PurchaseOrderDetail {
  id: number;
  supplier_id: number | null;
  supplier_name: string | null;
  supplier_email: string | null;
  supplier_missing?: boolean;
  supplier_missing_reason?: string | null;
  status: string;
  created_at: string;
  note: string | null;
  auto_created: boolean;
  last_sent_at: string | null;
  last_sent_to: string | null;
  last_sent_by: string | null;
  items: PurchaseOrderItem[];
}

interface CreateOrderPayload {
  supplier_id: number | null;
  status: string;
  note: string | null;
  items: Array<{ quantity_ordered: number } & Partial<Record<ItemIdKey, number>>>;
}

interface ReceiveOrderPayload {
  orderId: number;
  lines: Array<{ line_id: number; qty: number }>;
}

interface UpdateOrderPayload {
  orderId: number;
  supplier_id?: number | null;
  status?: string;
  note?: string | null;
  successMessage?: string;
}

interface PurchaseOrderEmailLogEntry {
  id: number;
  created_at: string;
  supplier_email: string;
  user_email?: string | null;
  status: "sent" | "failed";
  message_id?: string | null;
  error_message?: string | null;
}

type ApiErrorResponse = { detail?: string };

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

interface PurchaseOrdersPanelProps {
  suppliers: Supplier[];
  purchaseOrdersPath?: string;
  itemsPath?: string;
  ordersQueryKey?: QueryKey;
  itemsQueryKey?: QueryKey;
  title?: string;
  description?: string;
  downloadPrefix?: string;
  itemIdField?: ItemIdKey;
}

export function PurchaseOrdersPanel({
  suppliers,
  purchaseOrdersPath = "/purchase-orders",
  itemsPath = "/items",
  ordersQueryKey = ["purchase-orders"],
  itemsQueryKey = ["items"],
  title = "Bons de commande",
  description = "Suivez les commandes fournisseurs et marquez les réceptions pour mettre à jour les stocks.",
  downloadPrefix = "bon_commande",
  itemIdField = "item_id"
}: PurchaseOrdersPanelProps) {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canSendEmail = useMemo(
    () => Boolean(user && (user.role === "admin" || modulePermissions.canAccess("clothing", "edit"))),
    [modulePermissions, user]
  );
  const queryClient = useQueryClient();
  const [draftSupplier, setDraftSupplier] = useState<number | "">("");
  const [draftStatus, setDraftStatus] = useState<string>("ORDERED");
  const [draftNote, setDraftNote] = useState("");
  const [draftLines, setDraftLines] = useState<DraftLine[]>([{ itemId: "", quantity: 1 }]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingOrder, setEditingOrder] = useState<PurchaseOrderDetail | null>(null);
  const [editSupplier, setEditSupplier] = useState<number | "">("");
  const [editStatus, setEditStatus] = useState<string>("ORDERED");
  const [editNote, setEditNote] = useState<string>("");
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [sendModalOrder, setSendModalOrder] = useState<PurchaseOrderDetail | null>(null);
  const [overrideEmail, setOverrideEmail] = useState<string>("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [receiveModalOrder, setReceiveModalOrder] = useState<PurchaseOrderDetail | null>(null);
  const [receiveQuantities, setReceiveQuantities] = useState<Record<number, number>>({});
  const [receiveFormError, setReceiveFormError] = useState<string | null>(null);
  const selectedDraftSupplier = useMemo(
    () => suppliers.find((supplier) => supplier.id === draftSupplier),
    [draftSupplier, suppliers]
  );
  const selectedEditSupplier = useMemo(
    () => suppliers.find((supplier) => supplier.id === editSupplier),
    [editSupplier, suppliers]
  );
  const createFormId = `purchase-order-create-${itemIdField}`;
  const suppliersById = useMemo(() => {
    return new Map(suppliers.map((supplier) => [supplier.id, supplier.name]));
  }, [suppliers]);

  const renderSupplierDetails = (supplier?: Supplier) => {
    if (!supplier) {
      return null;
    }
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-email-display">
            Email
          </label>
          <AppTextInput
            id="supplier-email-display"
            value={supplier.email ?? ""}
            placeholder="Non renseigné"
            readOnly
            disabled
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-address-display">
            Adresse
          </label>
          <AppTextArea
            id="supplier-address-display"
            value={supplier.address ?? ""}
            placeholder="Non renseignée"
            rows={2}
            readOnly
            disabled
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          />
        </div>
      </div>
    );
  };

  const resolveItemId = (item: PurchaseOrderItem) => {
    const candidate = item[itemIdField];
    if (typeof candidate === "number") {
      return candidate;
    }
    return item.item_id ?? null;
  };

  const handleAddItemLine = (match: BarcodeLookupItem) => {
    setDraftLines((prev) => {
      const existingIndex = prev.findIndex((line) => line.itemId === match.id);
      if (existingIndex >= 0) {
        const next = [...prev];
        next[existingIndex] = {
          ...next[existingIndex],
          quantity: next[existingIndex].quantity + 1
        };
        return next;
      }
      return [...prev, { itemId: match.id, quantity: 1 }];
    });
  };

  const barcodeModule = itemIdField === "remise_item_id" ? "remise" : "clothing";
  const {
    barcodeInput,
    setBarcodeInput,
    inputRef,
    conflictMatches,
    isResolving: isResolvingBarcode,
    handleKeyDown: handleBarcodeKeyDown,
    submitBarcode,
    selectConflictMatch,
    clearConflictMatches
  } = usePurchaseOrderBarcodeScan({
    module: barcodeModule,
    onAddItem: handleAddItemLine
  });

  const formatItemLabel = (item: ItemOption) => {
    const supplierName = item.supplier_id ? suppliersById.get(item.supplier_id) : undefined;
    return formatPurchaseOrderItemLabel(item as PurchaseOrderItemLabelData, supplierName);
  };

  const formatConflictLabel = (match: BarcodeLookupItem) => {
    const item = items.find((candidate) => candidate.id === match.id);
    return item ? formatItemLabel(item) : match.name;
  };

  const getSupplierSendState = (order: PurchaseOrderDetail) => {
    const missingReason = order.supplier_missing_reason;
    const isMissingSupplier =
      order.supplier_missing ||
      missingReason === "SUPPLIER_NOT_FOUND" ||
      missingReason === "SUPPLIER_MISSING" ||
      missingReason === "SUPPLIER_INACTIVE";
    if (isMissingSupplier) {
      return {
        canSend: false,
        tooltip:
          missingReason === "SUPPLIER_MISSING"
            ? "Bon de commande non associé à un fournisseur"
            : "Fournisseur introuvable (supprimé ?)"
      };
    }
    if (
      missingReason === "SUPPLIER_EMAIL_MISSING" ||
      missingReason === "SUPPLIER_EMAIL_INVALID" ||
      !order.supplier_email
    ) {
      return {
        canSend: false,
        tooltip: "Ajoutez un email fournisseur pour activer l'envoi"
      };
    }
    return {
      canSend: true,
      tooltip: "Envoyer le bon de commande au fournisseur"
    };
  };

  const { data: orders = [], isLoading: loadingOrders } = useQuery({
    queryKey: ordersQueryKey,
    queryFn: async () => {
      const response = await api.get<PurchaseOrderDetail[]>(`${purchaseOrdersPath}/`);
      return response.data.map((order) => ({
        ...order,
        items: order.items.map((item) => {
          const candidate = item[itemIdField];
          const normalizedId = typeof candidate === "number" ? candidate : item.item_id;
          return {
            ...item,
            item_id: normalizedId
          } satisfies PurchaseOrderItem;
        })
      }));
    }
  });

  const { data: items = [] } = useQuery({
    queryKey: ["purchase-order-items-options", purchaseOrdersPath],
    queryFn: async () => {
      const response = await api.get<ItemOption[]>(`${itemsPath}/`);
      return response.data;
    }
  });

  const createOrder = useMutation({
    mutationFn: async (payload: CreateOrderPayload) => {
      await api.post(`${purchaseOrdersPath}/`, payload);
    },
    onSuccess: async () => {
      setMessage("Bon de commande créé.");
      setIsCreateModalOpen(false);
      setDraftLines([{ itemId: "", quantity: 1 }]);
      setDraftSupplier("");
      setDraftStatus("ORDERED");
      setDraftNote("");
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
    },
    onError: () => setError("Impossible de créer le bon de commande."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const updateOrder = useMutation<void, AxiosError<ApiErrorResponse>, UpdateOrderPayload>({
    mutationFn: async ({ orderId, successMessage: _successMessage, ...payload }) => {
      await api.put(`${purchaseOrdersPath}/${orderId}`, payload);
    },
    onSuccess: async (_, variables) => {
      setMessage(variables.successMessage ?? "Bon de commande mis à jour.");
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
      if (variables.status === "RECEIVED") {
        await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
      }
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de mettre à jour le bon de commande.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const receiveOrder = useMutation({
    mutationFn: async ({ orderId, lines }: ReceiveOrderPayload) => {
      await api.post(`${purchaseOrdersPath}/${orderId}/receive`, { lines });
    },
    onSuccess: async () => {
      setMessage("Réception enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
    },
    onError: () => setError("Impossible d'enregistrer la réception."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const emailLogQuery = useQuery({
    queryKey: ["purchase-order-email-log", sendModalOrder?.id],
    queryFn: async () => {
      if (!sendModalOrder) {
        return [];
      }
      const response = await api.get<PurchaseOrderEmailLogEntry[]>(
        `${purchaseOrdersPath}/${sendModalOrder.id}/email-log`
      );
      return response.data;
    },
    enabled: Boolean(sendModalOrder)
  });

  const sendToSupplier = useMutation<void, AxiosError<ApiErrorResponse>, PurchaseOrderDetail>({
    mutationFn: async (order) => {
      await api.post(`${purchaseOrdersPath}/${order.id}/send-to-supplier`, {
        to_email_override: overrideEmail.trim() ? overrideEmail.trim() : null
      });
    },
    onSuccess: async (_, order) => {
      setMessage("Email envoyé au fournisseur.");
      setOverrideEmail("");
      setSendModalOrder(null);
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
      await queryClient.invalidateQueries({
        queryKey: ["purchase-order-email-log", order.id]
      });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible d'envoyer l'e-mail.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const deleteOrder = useMutation<void, AxiosError<ApiErrorResponse>, PurchaseOrderDetail>({
    mutationFn: async (order) => {
      await api.delete(`${purchaseOrdersPath}/${order.id}`);
    },
    onMutate: (order) => {
      setDeletingId(order.id);
    },
    onSuccess: async () => {
      setMessage("Bon de commande supprimé.");
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de supprimer le bon de commande.");
    },
    onSettled: () => {
      setDeletingId(null);
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const handleAddLine = () => {
    setDraftLines((prev) => [...prev, { itemId: "", quantity: 1 }]);
  };

  const handleRemoveLine = (index: number) => {
    setDraftLines((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleOpenCreateModal = () => {
    setError(null);
    setIsCreateModalOpen(true);
  };

  const handleCloseCreateModal = () => {
    setIsCreateModalOpen(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    const normalizedLines = draftLines
      .filter((line) => line.itemId !== "" && line.quantity > 0)
      .map((line) => {
        const itemId = Number(line.itemId);
        return {
          [itemIdField]: itemId,
          quantity_ordered: line.quantity
        } satisfies { quantity_ordered: number } & Partial<Record<ItemIdKey, number>>;
      });
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

  const handleOpenReceiveModal = (order: PurchaseOrderDetail) => {
    setReceiveFormError(null);
    setReceiveModalOrder(order);
    setReceiveQuantities(
      order.items.reduce<Record<number, number>>((acc, line) => {
        acc[line.id] = 0;
        return acc;
      }, {})
    );
  };

  const handleCloseReceiveModal = () => {
    setReceiveFormError(null);
    setReceiveModalOrder(null);
    setReceiveQuantities({});
  };

  const handleSubmitPartialReceive = async () => {
    if (!receiveModalOrder) {
      return;
    }
    const payloadLines = receiveModalOrder.items
      .map((line) => {
        const remaining = line.quantity_ordered - line.quantity_received;
        const qty = receiveQuantities[line.id] ?? 0;
        return {
          line_id: line.id,
          qty,
          remaining
        };
      })
      .filter((line) => line.qty > 0);

    const invalidLine = payloadLines.find((line) => line.qty > line.remaining);
    if (invalidLine) {
      setReceiveFormError("La quantité ne peut pas dépasser le restant à recevoir.");
      return;
    }
    if (payloadLines.length === 0) {
      setReceiveFormError("Renseignez au moins une quantité à réceptionner.");
      return;
    }
    setReceiveFormError(null);
    try {
      await receiveOrder.mutateAsync({
        orderId: receiveModalOrder.id,
        lines: payloadLines.map(({ line_id, qty }) => ({ line_id, qty }))
      });
      handleCloseReceiveModal();
    } catch {
      // Les erreurs API sont gérées par la mutation
    }
  };

  const handleFillRemaining = () => {
    if (!receiveModalOrder) {
      return;
    }
    setReceiveQuantities(
      receiveModalOrder.items.reduce<Record<number, number>>((acc, line) => {
        const remaining = line.quantity_ordered - line.quantity_received;
        acc[line.id] = Math.max(0, remaining);
        return acc;
      }, {})
    );
  };

  const handleEditOrder = (order: PurchaseOrderDetail) => {
    setError(null);
    setEditingOrder(order);
    setEditSupplier(order.supplier_id ?? "");
    setEditStatus(order.status);
    setEditNote(order.note ?? "");
  };

  const handleCancelEdit = () => {
    setEditingOrder(null);
    setEditSupplier("");
    setEditStatus("ORDERED");
    setEditNote("");
  };

  const handleEditSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingOrder) {
      return;
    }
    setError(null);
    try {
      await updateOrder.mutateAsync({
        orderId: editingOrder.id,
        supplier_id: editSupplier === "" ? null : Number(editSupplier),
        status: editStatus,
        note: editNote.trim() ? editNote.trim() : null,
        successMessage: "Bon de commande mis à jour."
      });
      handleCancelEdit();
    } catch {
      // Erreur déjà gérée par le mutation handler
    }
  };

  const handleDownload = async (orderId: number) => {
    setError(null);
    setDownloadingId(orderId);
    try {
      const response = await api.get(`${purchaseOrdersPath}/${orderId}/pdf`, {
        responseType: "blob"
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${downloadPrefix}_${orderId}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      setMessage("PDF téléchargé.");
      window.setTimeout(() => setMessage(null), 4000);
    } catch (downloadError) {
      if (downloadError instanceof AxiosError && downloadError.response?.data?.detail) {
        setError(downloadError.response.data.detail ?? "Impossible de télécharger le PDF.");
      } else {
        setError("Impossible de télécharger le PDF.");
      }
    } finally {
      setDownloadingId(null);
    }
  };

  const handleOpenSendModal = (order: PurchaseOrderDetail) => {
    setError(null);
    setOverrideEmail("");
    setSendModalOrder(order);
  };

  const handleCloseSendModal = () => {
    setSendModalOrder(null);
    setOverrideEmail("");
  };

  const handleDeleteOrder = (order: PurchaseOrderDetail) => {
    if (!window.confirm(`Supprimer le bon de commande #${order.id} ?`)) {
      return;
    }
    deleteOrder.mutate(order);
  };

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          <p className="text-sm text-slate-400">{description}</p>
        </div>
        <button
          type="button"
          onClick={handleOpenCreateModal}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
        >
          Créer un bon de commande
        </button>
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
                    .map((line) => {
                      const remaining = line.quantity_ordered - line.quantity_received;
                      if (remaining <= 0) {
                        return null;
                      }
                      return {
                        line_id: line.id,
                        qty: remaining
                      };
                    })
                    .filter((line): line is { line_id: number; qty: number } => line !== null);
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
                      <td className="px-4 py-3 text-slate-200">
                        <div className="flex flex-col">
                          <span>{order.supplier_name ?? "-"}</span>
                          <span className="text-xs text-slate-400">
                            {order.supplier_email ?? "Email manquant"}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-200">
                        <select
                          value={order.status}
                          onChange={(event) => {
                            setError(null);
                            updateOrder.mutate({
                              orderId: order.id,
                              status: event.target.value,
                              successMessage: "Statut mis à jour."
                            });
                          }}
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
                          {order.items.map((line) => {
                            const itemId = resolveItemId(line);
                            return (
                              <li key={line.id}>
                                <span className="font-semibold">{line.item_name ?? `#${itemId}`}</span>
                                {": "}
                                <span>
                                  {line.quantity_received}/{line.quantity_ordered}
                                </span>
                              </li>
                            );
                          })}
                          {order.note ? (
                            <li className="text-slate-400">Note: {order.note}</li>
                          ) : null}
                          {order.last_sent_at ? (
                            <li className="text-slate-400">
                              Dernier envoi: {new Date(order.last_sent_at).toLocaleString()}
                              {order.last_sent_to ? ` → ${order.last_sent_to}` : ""}
                              {order.last_sent_by ? ` (par ${order.last_sent_by})` : ""}
                            </li>
                          ) : null}
                        </ul>
                      </td>
                      <td className="px-4 py-3 text-slate-200">
                        <div className="flex flex-col gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              receiveOrder.mutate({ orderId: order.id, lines: outstanding })
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
                          <button
                            type="button"
                            onClick={() => handleOpenReceiveModal(order)}
                            disabled={!canReceive}
                            className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Réception partielle
                          </button>
                          <button
                            type="button"
                            onClick={() => handleEditOrder(order)}
                            className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownload(order.id)}
                            disabled={downloadingId === order.id}
                            className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {downloadingId === order.id ? "Téléchargement..." : "Télécharger PDF"}
                          </button>
                          {canSendEmail
                            ? (() => {
                                const supplierState = getSupplierSendState(order);
                                return (
                                  <button
                                    type="button"
                                    onClick={() => handleOpenSendModal(order)}
                                    disabled={!supplierState.canSend}
                                    className="rounded bg-indigo-500 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                                    title={supplierState.tooltip}
                                  >
                                    Envoyer au fournisseur
                                  </button>
                                );
                              })()
                            : null}
                          {user?.role === "admin" ? (
                            <button
                              type="button"
                              onClick={() => handleDeleteOrder(order)}
                              disabled={deletingId === order.id}
                              className="rounded border border-red-500/60 px-3 py-1 text-xs font-semibold text-red-200 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {deletingId === order.id ? "Suppression..." : "Supprimer"}
                            </button>
                          ) : null}
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

        {editingOrder ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h4 className="text-sm font-semibold text-white">
              Modifier le bon de commande #{editingOrder.id}
            </h4>
            <form className="mt-4 space-y-4" onSubmit={handleEditSubmit}>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="edit-po-supplier">
                  Fournisseur
                </label>
                <select
                  id="edit-po-supplier"
                  value={editSupplier}
                  onChange={(event) =>
                    setEditSupplier(event.target.value ? Number(event.target.value) : "")
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
              {renderSupplierDetails(selectedEditSupplier)}

              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="edit-po-status">
                  Statut
                </label>
                <select
                  id="edit-po-status"
                  value={editStatus}
                  onChange={(event) => setEditStatus(event.target.value)}
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
                <label className="text-xs font-semibold text-slate-300" htmlFor="edit-po-note">
                  Note
                </label>
                <AppTextArea
                  id="edit-po-note"
                  value={editNote}
                  onChange={(event) => setEditNote(event.target.value)}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Informations complémentaires"
                />
              </div>

              <div className="flex justify-between gap-2">
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
                  disabled={updateOrder.isPending}
                >
                  Mettre à jour
                </button>
              </div>
            </form>
          </div>
        ) : null}
      </div>

      <PurchaseOrderCreateModal
        open={isCreateModalOpen}
        title="Créer un bon de commande"
        onClose={handleCloseCreateModal}
        onSubmit={handleSubmit}
        isSubmitting={createOrder.isPending}
        formId={createFormId}
      >
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
        {renderSupplierDetails(selectedDraftSupplier)}

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
          <AppTextArea
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
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300" htmlFor="po-barcode-input">
              Scanner / saisir un code-barres
            </label>
            <div className="flex gap-2">
              <AppTextInput
                id="po-barcode-input"
                ref={inputRef}
                value={barcodeInput}
                onChange={(event) => setBarcodeInput(event.target.value)}
                onKeyDown={handleBarcodeKeyDown}
                placeholder="Scanner / saisir un code-barres"
                noSpellcheck
                className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={submitBarcode}
                disabled={isResolvingBarcode}
                className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Ajouter
              </button>
            </div>
          </div>
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
                    {formatItemLabel(item)}
                  </option>
                ))}
              </select>
              <AppTextInput
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
      </PurchaseOrderCreateModal>

      <DraggableModal
        open={Boolean(receiveModalOrder)}
        title={
          receiveModalOrder
            ? `Réception partielle · Bon de commande #${receiveModalOrder.id}`
            : "Réception partielle"
        }
        onClose={handleCloseReceiveModal}
        footer={
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={handleFillRemaining}
              className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
            >
              Tout le restant
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleCloseReceiveModal}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={handleSubmitPartialReceive}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                disabled={receiveOrder.isPending}
              >
                Valider réception
              </button>
            </div>
          </div>
        }
      >
        {receiveModalOrder ? (
          <div className="space-y-4 text-sm text-slate-200">
            <p className="text-xs text-slate-400">
              Fournisseur: {receiveModalOrder.supplier_name ?? "Non renseigné"}
            </p>
            {receiveFormError ? (
              <p className="text-xs text-red-400">{receiveFormError}</p>
            ) : null}
            <div className="space-y-3">
              {receiveModalOrder.items.map((line) => {
                const remaining = line.quantity_ordered - line.quantity_received;
                const itemId = resolveItemId(line);
                return (
                  <div
                    key={line.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
                  >
                    <div>
                      <p className="font-semibold">
                        {line.item_name ?? (itemId ? `#${itemId}` : "Article")}
                      </p>
                      <p className="text-xs text-slate-400">
                        Reçu: {line.quantity_received}/{line.quantity_ordered} · Restant:{" "}
                        {Math.max(0, remaining)}
                      </p>
                    </div>
                    <AppTextInput
                      type="number"
                      min={0}
                      max={Math.max(0, remaining)}
                      value={receiveQuantities[line.id] ?? 0}
                      onChange={(event) =>
                        setReceiveQuantities((prev) => ({
                          ...prev,
                          [line.id]: Number(event.target.value)
                        }))
                      }
                      disabled={remaining <= 0}
                      className="w-28 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </DraggableModal>

      {conflictMatches ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4">
          <div className="w-full max-w-lg rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h4 className="text-lg font-semibold text-white">Choisir un article</h4>
                <p className="text-xs text-slate-400">
                  Plusieurs articles correspondent à ce code-barres.
                </p>
              </div>
              <button
                type="button"
                onClick={clearConflictMatches}
                className="text-sm text-slate-400 hover:text-slate-200"
              >
                Fermer
              </button>
            </div>
            <ul className="mt-4 space-y-2 text-sm text-slate-200">
              {conflictMatches.map((match) => (
                <li key={match.id}>
                  <button
                    type="button"
                    onClick={() => selectConflictMatch(match)}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-left text-sm text-slate-100 hover:border-indigo-400 hover:bg-slate-800"
                  >
                    {formatConflictLabel(match)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {sendModalOrder ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4">
          <div className="w-full max-w-xl rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h4 className="text-lg font-semibold text-white">Envoyer au fournisseur</h4>
                <p className="text-xs text-slate-400">
                  Bon de commande #{sendModalOrder.id} · Site {user?.site_key ?? "-"}
                  {sendModalOrder.supplier_name ? ` · ${sendModalOrder.supplier_name}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={handleCloseSendModal}
                className="text-sm text-slate-400 hover:text-slate-200"
              >
                Fermer
              </button>
            </div>

            <div className="mt-4 space-y-3 text-sm text-slate-200">
              <div>
                <p className="text-xs uppercase text-slate-500">Destinataire</p>
                <p className="font-semibold">
                  {sendModalOrder.supplier_missing ||
                  sendModalOrder.supplier_missing_reason === "SUPPLIER_NOT_FOUND" ||
                  sendModalOrder.supplier_missing_reason === "SUPPLIER_INACTIVE"
                    ? "Fournisseur introuvable"
                    : sendModalOrder.supplier_name ?? "Fournisseur"}{" "}
                  · {sendModalOrder.supplier_email ?? "Email manquant"}
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="override-email">
                  Email alternatif (facultatif)
                </label>
                <input
                  id="override-email"
                  type="email"
                  value={overrideEmail}
                  onChange={(event) => setOverrideEmail(event.target.value)}
                  placeholder="contact@fournisseur.com"
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                />
              </div>
              {sendModalOrder.last_sent_at ? (
                <p className="text-xs text-slate-400">
                  Dernier envoi: {new Date(sendModalOrder.last_sent_at).toLocaleString()}
                </p>
              ) : null}
            </div>

            <div className="mt-6 flex flex-wrap justify-between gap-3">
              <button
                type="button"
                onClick={handleCloseSendModal}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => sendToSupplier.mutate(sendModalOrder)}
                disabled={sendToSupplier.isPending}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {sendToSupplier.isPending ? "Envoi..." : "Confirmer l'envoi"}
              </button>
            </div>

            <div className="mt-6">
              <h5 className="text-sm font-semibold text-white">Historique e-mails</h5>
              {emailLogQuery.isLoading ? (
                <p className="text-xs text-slate-400">Chargement de l'historique...</p>
              ) : emailLogQuery.data && emailLogQuery.data.length > 0 ? (
                <ul className="mt-2 space-y-2 text-xs text-slate-300">
                  {emailLogQuery.data.map((entry) => (
                    <li
                      key={entry.id}
                      className="rounded border border-slate-800 bg-slate-950/60 px-3 py-2"
                    >
                      <p className="font-semibold">
                        {new Date(entry.created_at).toLocaleString()} ·{" "}
                        {entry.status === "sent" ? "Envoyé" : "Échec"}
                      </p>
                      <p>
                        À: {entry.supplier_email}
                        {entry.user_email ? ` · Par: ${entry.user_email}` : ""}
                      </p>
                      {entry.error_message ? (
                        <p className="text-rose-300">Erreur: {entry.error_message}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-400">Aucun envoi enregistré.</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
