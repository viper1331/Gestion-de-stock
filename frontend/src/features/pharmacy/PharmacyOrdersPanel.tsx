import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
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

interface PharmacyItemOption {
  id: number;
  name: string;
  barcode?: string | null;
  dosage?: string | null;
  packaging?: string | null;
  quantity?: number | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  extra?: Record<string, unknown>;
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
  supplier_email: string | null;
  status: string;
  created_at: string;
  note: string | null;
  auto_created: boolean;
  is_archived?: boolean;
  archived_at?: string | null;
  archived_by?: number | null;
  items: PharmacyPurchaseOrderItem[];
}

interface PharmacyPurchaseOrderRefreshResponse {
  created: number;
  updated: number;
  skipped: number;
  items_below_threshold: number;
  purchase_order_id: number | null;
}

interface PharmacyOrderDraftLine {
  pharmacyItemId: number | "";
  quantity: number;
}

interface UpdateOrderPayload {
  orderId: number;
  supplier_id?: number | null;
  status?: string;
  note?: string | null;
  successMessage?: string;
}

type ApiErrorResponse = { detail?: string };

const ORDER_STATUSES: Array<{ value: string; label: string }> = [
  { value: "PENDING", label: "En attente" },
  { value: "ORDERED", label: "Commandé" },
  { value: "PARTIALLY_RECEIVED", label: "Partiellement reçu" },
  { value: "RECEIVED", label: "Reçu" },
  { value: "CANCELLED", label: "Annulé" }
];

export function PharmacyOrdersPanel({ canEdit }: { canEdit: boolean }) {
  const { user } = useAuth();
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
  const queryClient = useQueryClient();
  const [draftLines, setDraftLines] = useState<PharmacyOrderDraftLine[]>([
    { pharmacyItemId: "", quantity: 1 }
  ]);
  const [draftSupplier, setDraftSupplier] = useState<number | "">("");
  const [draftStatus, setDraftStatus] = useState<string>("ORDERED");
  const [draftNote, setDraftNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshSummary, setRefreshSummary] = useState<string | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingOrder, setEditingOrder] = useState<PharmacyPurchaseOrderDetail | null>(null);
  const [editSupplier, setEditSupplier] = useState<number | "">("");
  const [editStatus, setEditStatus] = useState<string>("ORDERED");
  const [editNote, setEditNote] = useState<string>("");
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [receiveModalOrder, setReceiveModalOrder] = useState<PharmacyPurchaseOrderDetail | null>(null);
  const [archiveModalOrder, setArchiveModalOrder] =
    useState<PharmacyPurchaseOrderDetail | null>(null);
  const [archiveFilter, setArchiveFilter] = useState<"active" | "archived">("active");
  const [receiveQuantities, setReceiveQuantities] = useState<Record<number, number>>({});
  const [receiveFormError, setReceiveFormError] = useState<string | null>(null);
  const selectedDraftSupplier = suppliers.find((supplier) => supplier.id === draftSupplier);
  const selectedEditSupplier = suppliers.find((supplier) => supplier.id === editSupplier);
  const createFormId = "pharmacy-purchase-order-create";
  const showArchived = archiveFilter === "archived";
  const ordersQueryKey = useMemo(
    () => ["pharmacy-orders", showArchived ? "archived" : "active"],
    [showArchived]
  );
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
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-supplier-email">
            Email
          </label>
          <AppTextInput
            id="pharmacy-supplier-email"
            value={supplier.email ?? ""}
            placeholder="Non renseigné"
            readOnly
            disabled
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-supplier-address">
            Adresse
          </label>
          <AppTextArea
            id="pharmacy-supplier-address"
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

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ordersQueryKey,
    queryFn: async () => {
      const response = await api.get<PharmacyPurchaseOrderDetail[]>("/pharmacy/orders/", {
        params: showArchived ? { include_archived: true } : undefined
      });
      return response.data;
    }
  });

  const visibleOrders = useMemo(
    () => orders.filter((order) => (showArchived ? order.is_archived : !order.is_archived)),
    [orders, showArchived]
  );

  const { data: pharmacyItems = [] } = useQuery({
    queryKey: ["pharmacy-items-options"],
    queryFn: async () => {
      const response = await api.get<PharmacyItemOption[]>("/pharmacy/");
      return response.data;
    }
  });

  const handleAddItemLine = (match: BarcodeLookupItem) => {
    setDraftLines((prev) => {
      const existingIndex = prev.findIndex((line) => line.pharmacyItemId === match.id);
      if (existingIndex >= 0) {
        const next = [...prev];
        next[existingIndex] = {
          ...next[existingIndex],
          quantity: next[existingIndex].quantity + 1
        };
        return next;
      }
      return [...prev, { pharmacyItemId: match.id, quantity: 1 }];
    });
  };

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
    module: "pharmacy",
    onAddItem: handleAddItemLine
  });

  const formatItemLabel = (item: PharmacyItemOption) => {
    const supplierName =
      item.supplier_name ?? (item.supplier_id ? suppliersById.get(item.supplier_id) : undefined);
    return formatPurchaseOrderItemLabel(item as PurchaseOrderItemLabelData, supplierName);
  };

  const formatConflictLabel = (match: BarcodeLookupItem) => {
    const item = pharmacyItems.find((candidate) => candidate.id === match.id);
    return item ? formatItemLabel(item) : match.name;
  };

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
      setIsCreateModalOpen(false);
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

  const updateOrder = useMutation<void, AxiosError<ApiErrorResponse>, UpdateOrderPayload>({
    mutationFn: async ({ orderId, successMessage: _successMessage, ...payload }) => {
      await api.put(`/pharmacy/orders/${orderId}`, payload);
    },
    onSuccess: async (_, variables) => {
      setMessage(variables.successMessage ?? "Bon de commande mis à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de mettre à jour le bon de commande.");
    },
    onSettled: () => window.setTimeout(() => setMessage(null), 4000)
  });

  const receiveOrder = useMutation({
    mutationFn: async ({
      orderId,
      lines
    }: {
      orderId: number;
      lines: Array<{ line_id: number; qty: number }>;
    }) => {
      await api.post(`/pharmacy/orders/${orderId}/receive`, { lines });
    },
    onSuccess: async () => {
      setMessage("Réception enregistrée.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible d'enregistrer la réception."),
    onSettled: () => window.setTimeout(() => setMessage(null), 4000)
  });

  const sendToSupplier = useMutation<void, AxiosError<ApiErrorResponse>, PharmacyPurchaseOrderDetail>({
    mutationFn: async (order) => {
      await api.post(`/pharmacy/orders/${order.id}/send-to-supplier`);
    },
    onMutate: (order) => {
      setSendingId(order.id);
    },
    onSuccess: async () => {
      setMessage("Email envoyé au fournisseur.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible d'envoyer l'e-mail.");
    },
    onSettled: () => {
      setSendingId(null);
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const archiveOrder = useMutation<PharmacyPurchaseOrderDetail, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (orderId) => {
      const response = await api.post<PharmacyPurchaseOrderDetail>(
        `/pharmacy/orders/${orderId}/archive`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Bon de commande archivé.");
      setArchiveModalOrder(null);
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible d'archiver le bon de commande.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const unarchiveOrder = useMutation<
    PharmacyPurchaseOrderDetail,
    AxiosError<ApiErrorResponse>,
    number
  >({
    mutationFn: async (orderId) => {
      const response = await api.post<PharmacyPurchaseOrderDetail>(
        `/pharmacy/orders/${orderId}/unarchive`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Bon de commande restauré.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de restaurer le bon de commande.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const deleteOrder = useMutation<void, AxiosError<ApiErrorResponse>, PharmacyPurchaseOrderDetail>({
    mutationFn: async (order) => {
      await api.delete(`/pharmacy/orders/${order.id}`);
    },
    onMutate: (order) => {
      setDeletingId(order.id);
    },
    onSuccess: async () => {
      setMessage("Bon de commande supprimé.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
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

  const refreshAutoOrders = useMutation<
    PharmacyPurchaseOrderRefreshResponse,
    AxiosError<ApiErrorResponse>
  >({
    mutationFn: async () => {
      const response = await api.post<PharmacyPurchaseOrderRefreshResponse>(
        "/purchase-orders/auto/refresh",
        null,
        { params: { module: "pharmacy" } }
      );
      return response.data;
    },
    onSuccess: async (data) => {
      const totalOrders = data.created + data.updated;
      const summary =
        data.items_below_threshold > 0
          ? `${data.items_below_threshold} article(s) sous seuil → ${totalOrders} BC généré${
              totalOrders > 1 ? "s" : ""
            } / mis à jour`
          : null;
      setMessage("Bons de commande mis à jour.");
      setRefreshSummary(summary);
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-orders"] });
      window.setTimeout(() => {
        setMessage(null);
        setRefreshSummary(null);
      }, 4000);
    },
    onError: (refreshError) => {
      if (refreshError.response?.data?.detail) {
        setError(
          refreshError.response.data.detail ?? "Impossible de rafraîchir les bons de commande."
        );
      } else {
        setError("Impossible de rafraîchir les bons de commande.");
      }
    }
  });

  const handleRefresh = () => {
    setError(null);
    refreshAutoOrders.mutate();
  };

  const handleAddLine = () => {
    setDraftLines((prev) => [...prev, { pharmacyItemId: "", quantity: 1 }]);
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

  const handleOpenReceiveModal = (order: PharmacyPurchaseOrderDetail) => {
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

  const handleEditOrder = (order: PharmacyPurchaseOrderDetail) => {
    if (!canEdit) {
      return;
    }
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
      // Erreur gérée par le mutation handler
    }
  };

  const handleDownload = async (orderId: number) => {
    setError(null);
    setDownloadingId(orderId);
    try {
      const response = await api.get(`/pharmacy/orders/${orderId}/pdf`, {
        responseType: "blob"
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `bon_commande_pharmacie_${orderId}.pdf`;
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

  const handleDeleteOrder = (order: PharmacyPurchaseOrderDetail) => {
    if (!window.confirm(`Supprimer le bon de commande #${order.id} ?`)) {
      return;
    }
    deleteOrder.mutate(order);
  };

  const handleOpenArchiveModal = (order: PharmacyPurchaseOrderDetail) => {
    setError(null);
    setArchiveModalOrder(order);
  };

  const handleCloseArchiveModal = () => {
    setArchiveModalOrder(null);
  };

  const handleConfirmArchive = () => {
    if (!archiveModalOrder) {
      return;
    }
    archiveOrder.mutate(archiveModalOrder.id);
  };

  const handleUnarchiveOrder = (order: PharmacyPurchaseOrderDetail) => {
    if (
      !window.confirm(
        `Désarchiver le bon de commande #${order.id} ? Il réapparaîtra dans la liste active.`
      )
    ) {
      return;
    }
    unarchiveOrder.mutate(order.id);
  };

  return (
    <section className="min-w-0 space-y-4">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Bons de commande pharmacie</h3>
          <p className="text-sm text-slate-400">
            Centralisez les commandes auprès des fournisseurs et mettez à jour les stocks lors des réceptions.
          </p>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshAutoOrders.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {refreshAutoOrders.isPending ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
              ) : null}
              Rafraîchir
            </button>
            <button
              type="button"
              onClick={handleOpenCreateModal}
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
            >
              Créer un bon de commande
            </button>
          </div>
        ) : null}
      </header>

      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {refreshSummary ? <p className="text-xs text-slate-400">{refreshSummary}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="grid min-w-0 gap-6 lg:grid-cols-2">
        <div className="min-w-0 space-y-4">
          <div className="flex w-fit items-center rounded-full border border-slate-800 bg-slate-900/60 p-1 text-xs">
            <button
              type="button"
              onClick={() => setArchiveFilter("active")}
              className={`rounded-full px-3 py-1 font-semibold transition ${
                archiveFilter === "active"
                  ? "bg-indigo-500 text-white"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              Actifs
            </button>
            <button
              type="button"
              onClick={() => setArchiveFilter("archived")}
              className={`rounded-full px-3 py-1 font-semibold transition ${
                archiveFilter === "archived"
                  ? "bg-indigo-500 text-white"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              Archivés
            </button>
          </div>
          <div className="min-w-0 overflow-auto rounded-lg border border-slate-800">
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
                {visibleOrders.map((order) => {
                  const isArchived = Boolean(order.is_archived);
                  const isReadOnly = isArchived;
                  const outstanding = order.items
                    .map((line) => {
                      const remaining = line.quantity_ordered - line.quantity_received;
                      if (remaining <= 0) {
                        return null;
                      }
                      return { line_id: line.id, qty: remaining };
                    })
                    .filter((line): line is { line_id: number; qty: number } => line !== null);
                  const canReceive = outstanding.length > 0 && !isReadOnly;
                  const canSendToSupplier = Boolean(order.supplier_id && order.supplier_email);
                  const sendTooltip = order.supplier_id
                    ? "Ajoutez un email fournisseur pour activer l'envoi"
                    : "Bon de commande non associé à un fournisseur";
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
                        {isArchived ? (
                          <div className="flex flex-col gap-2 text-xs">
                            <span>
                              {ORDER_STATUSES.find((option) => option.value === order.status)?.label ??
                                order.status}
                            </span>
                            <span className="w-fit rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-200">
                              Archivé
                            </span>
                          </div>
                        ) : (
                          <select
                            value={order.status}
                            onChange={(event) => {
                              if (!canEdit) {
                                return;
                              }
                              setError(null);
                              updateOrder.mutate({
                                orderId: order.id,
                                status: event.target.value,
                                successMessage: "Statut mis à jour."
                              });
                            }}
                            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
                            disabled={!canEdit}
                          >
                            {ORDER_STATUSES.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        )}
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
                        <div className="flex flex-col gap-2">
                          <button
                            type="button"
                            onClick={() => handleDownload(order.id)}
                            disabled={downloadingId === order.id}
                            className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {downloadingId === order.id ? "Téléchargement..." : "Télécharger PDF"}
                          </button>
                          {isArchived ? (
                            canEdit ? (
                              <button
                                type="button"
                                onClick={() => handleUnarchiveOrder(order)}
                                disabled={unarchiveOrder.isPending}
                                className="rounded border border-amber-400/60 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                Désarchiver
                              </button>
                            ) : null
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() =>
                                  receiveOrder.mutate({ orderId: order.id, lines: outstanding })
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
                              <button
                                type="button"
                                onClick={() => handleOpenReceiveModal(order)}
                                disabled={!canEdit || !canReceive}
                                className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                Réception partielle
                              </button>
                              {canEdit ? (
                                <button
                                  type="button"
                                  onClick={() => handleEditOrder(order)}
                                  className="rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                                >
                                  Modifier
                                </button>
                              ) : null}
                              {canEdit && order.status !== "RECEIVED" ? (
                                <button
                                  type="button"
                                  onClick={() => sendToSupplier.mutate(order)}
                                  disabled={sendingId === order.id || !canSendToSupplier}
                                  className="rounded bg-indigo-500 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                                  title={
                                    canSendToSupplier
                                      ? "Envoyer le bon de commande au fournisseur"
                                      : sendTooltip
                                  }
                                >
                                  {sendingId === order.id ? "Envoi..." : "Envoyer au fournisseur"}
                                </button>
                              ) : null}
                              {canEdit && order.status === "RECEIVED" ? (
                                <button
                                  type="button"
                                  onClick={() => handleOpenArchiveModal(order)}
                                  className="rounded border border-amber-400/60 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/10"
                                >
                                  Archiver
                                </button>
                              ) : null}
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
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {visibleOrders.length === 0 && !isLoading ? (
                  <tr>
                    <td className="px-4 py-4 text-sm text-slate-400" colSpan={5}>
                      {showArchived
                        ? "Aucun bon de commande archivé."
                        : "Aucun bon de commande enregistré."}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {isLoading ? <p className="text-sm text-slate-400">Chargement...</p> : null}
        </div>

        {canEdit && editingOrder ? (
          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h4 className="text-sm font-semibold text-white">
              Modifier le bon de commande #{editingOrder.id}
            </h4>
            <form className="mt-4 space-y-4" onSubmit={handleEditSubmit}>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-edit-order-supplier">
                  Fournisseur
                </label>
                <select
                  id="pharmacy-edit-order-supplier"
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
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-edit-order-status">
                  Statut
                </label>
                <select
                  id="pharmacy-edit-order-status"
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
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-edit-order-note">
                  Note
                </label>
                <AppTextArea
                  id="pharmacy-edit-order-note"
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
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-order-supplier">
            Fournisseur
          </label>
          <select
            id="pharmacy-order-supplier"
            value={draftSupplier}
            onChange={(event) =>
              setDraftSupplier(event.target.value ? Number(event.target.value) : "")
            }
            className="w-full min-w-0 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
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
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-order-status">
            Statut initial
          </label>
          <select
            id="pharmacy-order-status"
            value={draftStatus}
            onChange={(event) => setDraftStatus(event.target.value)}
            className="w-full min-w-0 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
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
          <AppTextArea
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
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-barcode-input">
              Scanner / saisir un code-barres
            </label>
            <div className="flex min-w-0 gap-2">
              <AppTextInput
                id="pharmacy-barcode-input"
                ref={inputRef}
                value={barcodeInput}
                onChange={(event) => setBarcodeInput(event.target.value)}
                onKeyDown={handleBarcodeKeyDown}
                placeholder="Scanner / saisir un code-barres"
                noSpellcheck
                className="flex-1 min-w-0 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={submitBarcode}
                disabled={isResolvingBarcode}
                className="shrink-0 rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Ajouter
              </button>
            </div>
          </div>
          {draftLines.map((line, index) => (
            <div key={index} className="flex min-w-0 gap-2">
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
                className="w-full min-w-0 flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              >
                <option value="">Sélectionnez un article</option>
                {pharmacyItems.map((item) => (
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
        open={Boolean(archiveModalOrder)}
        title={
          archiveModalOrder
            ? `Archiver le bon de commande #${archiveModalOrder.id}`
            : "Archiver le bon de commande"
        }
        onClose={handleCloseArchiveModal}
      >
        <div className="space-y-4 text-sm text-slate-200">
          <p>
            Archiver ce bon de commande ? Il sera masqué de la liste principale. Action
            réversible.
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCloseArchiveModal}
              className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={handleConfirmArchive}
              disabled={!archiveModalOrder || archiveOrder.isPending}
              className="rounded-md bg-amber-500 px-3 py-2 text-xs font-semibold text-white hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {archiveOrder.isPending ? "Archivage..." : "Archiver"}
            </button>
          </div>
        </div>
      </DraggableModal>

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
            {receiveFormError ? (
              <p className="text-xs text-red-400">{receiveFormError}</p>
            ) : null}
            <div className="space-y-3">
              {receiveModalOrder.items.map((line) => {
                const remaining = line.quantity_ordered - line.quantity_received;
                return (
                  <div
                    key={line.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
                  >
                    <div>
                      <p className="font-semibold">
                        {line.pharmacy_item_name ?? `#${line.pharmacy_item_id}`}
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
    </section>
  );
}
