import { FormEvent, useEffect, useMemo, useState } from "react";
import { QueryKey, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
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

interface Collaborator {
  id: number;
  full_name: string;
}

interface DotationAssignee {
  employee_id: number;
  display_name: string;
  count: number;
}

interface DotationAssigneesResponse {
  assignees: DotationAssignee[];
}

interface DotationAssigneeItem {
  assignment_id: number;
  item_id: number;
  sku: string;
  name: string;
  size_variant?: string | null;
  qty: number;
}

interface DotationAssigneeItemsResponse {
  items: DotationAssigneeItem[];
}

interface ItemOption {
  id: number;
  name: string;
  sku?: string | null;
  size?: string | null;
  category_id?: number | null;
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
  beneficiary_employee_id?: number | null;
  beneficiary_name?: string | null;
  line_type?: "standard" | "replacement";
  return_expected?: boolean;
  return_reason?: string | null;
  return_employee_item_id?: number | null;
  return_qty?: number;
  return_status?: "none" | "to_prepare" | "shipped" | "supplier_received" | "cancelled";
}

interface PurchaseOrderReceipt {
  id: number;
  purchase_order_id: number;
  purchase_order_line_id: number;
  received_qty: number;
  conformity_status: "conforme" | "non_conforme";
  nonconformity_reason?: string | null;
  nonconformity_action?: "replacement" | "credit_note" | "return_to_supplier" | null;
  note?: string | null;
  created_by?: string | null;
  created_at: string;
}

interface PendingClothingAssignment {
  id: number;
  purchase_order_id: number;
  purchase_order_line_id: number;
  receipt_id: number;
  employee_id: number;
  new_item_id: number;
  qty: number;
  return_employee_item_id?: number | null;
  return_reason?: string | null;
  status: "pending" | "validated" | "cancelled";
  created_at: string;
  validated_at?: string | null;
  validated_by?: string | null;
}

interface ClothingSupplierReturn {
  id: number;
  purchase_order_id: number;
  purchase_order_line_id?: number | null;
  employee_id?: number | null;
  employee_item_id?: number | null;
  item_id?: number | null;
  qty: number;
  reason?: string | null;
  status: "prepared" | "shipped" | "supplier_received";
  created_at: string;
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
  receipts?: PurchaseOrderReceipt[];
  pending_assignments?: PendingClothingAssignment[];
  supplier_returns?: ClothingSupplierReturn[];
}

interface CreateOrderPayload {
  supplier_id: number | null;
  status: string;
  note: string | null;
  items: Array<
    { quantity_ordered: number } & Partial<Record<ItemIdKey, number>> & {
        beneficiary_employee_id?: number | null;
        line_type?: "standard" | "replacement";
        return_expected?: boolean;
        return_reason?: string | null;
        return_employee_item_id?: number | null;
        return_qty?: number | null;
      }
  >;
}

interface ReceiveOrderPayload {
  orderId: number;
  lines: Array<{ line_id: number; qty: number }>;
}

interface ReceiveLinePayload {
  orderId: number;
  lines: Array<{
    purchase_order_line_id: number;
    received_qty: number;
    conformity_status: "conforme" | "non_conforme";
    nonconformity_reason?: string | null;
    nonconformity_action?: "replacement" | "credit_note" | "return_to_supplier" | null;
    note?: string | null;
  }>;
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

interface PurchaseOrderAutoRefreshResponse {
  created: number;
  updated: number;
  skipped: number;
  items_below_threshold: number;
  purchase_order_id: number | null;
}

type ApiErrorResponse = { detail?: string };

const ORDER_STATUSES: Array<{ value: string; label: string }> = [
  { value: "PENDING", label: "En attente" },
  { value: "ORDERED", label: "Commandé" },
  { value: "PARTIALLY_RECEIVED", label: "Partiellement reçu" },
  { value: "RECEIVED", label: "Reçu" },
  { value: "CANCELLED", label: "Annulé" }
];

const RETURN_REASONS = [
  "Vétusté",
  "Endommagé",
  "Erreur taille",
  "Non conforme",
  "Autre"
];

interface DraftLine {
  itemId: number | "";
  quantity: number;
  lineType?: "standard" | "replacement";
  beneficiaryId?: number | "";
  returnExpected?: boolean;
  returnReason?: string;
  returnReasonDetail?: string;
  returnEmployeeItemId?: number | "";
  returnQty?: number;
}

interface PurchaseOrdersPanelProps {
  suppliers: Supplier[];
  purchaseOrdersPath?: string;
  itemsPath?: string;
  ordersQueryKey?: QueryKey;
  itemsQueryKey?: QueryKey;
  moduleKey?: string;
  title?: string;
  description?: string;
  downloadPrefix?: string;
  itemIdField?: ItemIdKey;
  enableReplacementFlow?: boolean;
}

export function PurchaseOrdersPanel({
  suppliers,
  purchaseOrdersPath = "/purchase-orders",
  itemsPath = "/items",
  ordersQueryKey = ["purchase-orders"],
  itemsQueryKey = ["items"],
  moduleKey = "purchase_orders",
  title = "Bons de commande",
  description = "Suivez les commandes fournisseurs et marquez les réceptions pour mettre à jour les stocks.",
  downloadPrefix = "bon_commande",
  itemIdField = "item_id",
  enableReplacementFlow = false
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
  const [draftLines, setDraftLines] = useState<DraftLine[]>([
    { itemId: "", quantity: 1, lineType: "standard", returnExpected: false }
  ]);
  const [replacementAccess, setReplacementAccess] = useState(enableReplacementFlow);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshSummary, setRefreshSummary] = useState<string | null>(null);
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
  const [receiveDetails, setReceiveDetails] = useState<
    Record<
      number,
      {
        qty: number;
        conformity_status: "conforme" | "non_conforme";
        nonconformity_reason: string;
        nonconformity_action: "replacement" | "credit_note" | "return_to_supplier" | "";
        note: string;
      }
    >
  >({});
  const [pendingValidationError, setPendingValidationError] = useState<string | null>(null);
  const selectedDraftSupplier = useMemo(
    () => suppliers.find((supplier) => supplier.id === draftSupplier),
    [draftSupplier, suppliers]
  );
  const selectedEditSupplier = useMemo(
    () => suppliers.find((supplier) => supplier.id === editSupplier),
    [editSupplier, suppliers]
  );
  const createFormId = `purchase-order-create-${itemIdField}`;
  const canRefresh =
    user?.role === "admin" || modulePermissions.canAccess(moduleKey, "edit");

  useEffect(() => {
    setReplacementAccess(enableReplacementFlow);
  }, [enableReplacementFlow]);

  useEffect(() => {
    if (replacementAccess) {
      return;
    }
    setDraftLines((prev) =>
      prev.map((line) => ({
        ...line,
        lineType: "standard",
        returnExpected: false,
        beneficiaryId: "",
        returnReason: "",
        returnEmployeeItemId: "",
        returnQty: 0
      }))
    );
  }, [replacementAccess]);

  const handleDotationsForbidden = (requestError: unknown) => {
    const status = (requestError as AxiosError)?.response?.status;
    if (status === 403) {
      setReplacementAccess(false);
    }
  };

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
      return [
        ...prev,
        { itemId: match.id, quantity: 1, lineType: "standard", returnExpected: false }
      ];
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

  const resolveCollaboratorName = (collaboratorId: number | null | undefined) => {
    if (!collaboratorId) {
      return "-";
    }
    return collaboratorsById.get(collaboratorId) ?? `#${collaboratorId}`;
  };

  const resolveItemLabel = (itemId: number | null | undefined) => {
    if (!itemId) {
      return "-";
    }
    const item = itemsById.get(itemId);
    if (!item) {
      return `#${itemId}`;
    }
    const size = item.size ? ` · ${item.size}` : "";
    const sku = item.sku ? ` (${item.sku})` : "";
    return `${item.name}${sku}${size}`;
  };

  const resolveAssignedItemLabel = (assignedItem: DotationAssigneeItem) => {
    const sku = assignedItem.sku ? ` (${assignedItem.sku})` : "";
    const size = assignedItem.size_variant ? assignedItem.size_variant : "—";
    return `${assignedItem.name}${sku} — ${size} — x${assignedItem.qty}`;
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
        }),
        receipts: order.receipts ?? [],
        pending_assignments: order.pending_assignments ?? [],
        supplier_returns: order.supplier_returns ?? []
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

  const { data: collaborators = [] } = useQuery({
    queryKey: ["clothing-collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/collaborators");
      return response.data;
    },
    enabled: replacementAccess
  });

  const { data: assignees = [] } = useQuery({
    queryKey: ["clothing-dotations-assignees"],
    queryFn: async () => {
      const response = await api.get<DotationAssigneesResponse>("/dotations/assignees", {
        params: { module: "clothing" }
      });
      return response.data.assignees;
    },
    enabled: replacementAccess,
    onError: handleDotationsForbidden
  });

  const assignedItemEmployeeIds = useMemo(() => {
    const ids = new Set<number>();
    draftLines.forEach((line) => {
      if (line.lineType === "replacement" && typeof line.beneficiaryId === "number") {
        ids.add(line.beneficiaryId);
      }
    });
    orders.forEach((order) => {
      (order.pending_assignments ?? []).forEach((assignment) => {
        if (assignment.return_employee_item_id && assignment.employee_id) {
          ids.add(assignment.employee_id);
        }
      });
    });
    return Array.from(ids);
  }, [draftLines, orders]);

  const assignedItemQueries = useMemo(
    () =>
      assignedItemEmployeeIds.map((beneficiaryId) => ({
        queryKey: ["clothing-assigned-items", beneficiaryId],
        queryFn: async () => {
          const response = await api.get<DotationAssigneeItemsResponse>(
            `/dotations/assignees/${beneficiaryId}/items`,
            {
              params: { module: "clothing" }
            }
          );
          return response.data.items;
        },
        enabled: replacementAccess,
        onError: handleDotationsForbidden
      })),
    [assignedItemEmployeeIds, replacementAccess]
  );

  const assignedItemsQueries = useQueries({ queries: assignedItemQueries });

  const assignedItemsByBeneficiary = useMemo(() => {
    const map = new Map<number, DotationAssigneeItem[]>();
    assignedItemsQueries.forEach((query, index) => {
      const beneficiaryId = assignedItemEmployeeIds[index];
      if (beneficiaryId) {
        map.set(beneficiaryId, query.data ?? []);
      }
    });
    return map;
  }, [assignedItemEmployeeIds, assignedItemsQueries]);

  const suppliersById = useMemo(() => {
    return new Map(suppliers.map((supplier) => [supplier.id, supplier.name]));
  }, [suppliers]);
  const itemsById = useMemo(() => {
    return new Map(items.map((item) => [item.id, item]));
  }, [items]);
  const collaboratorsById = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator.full_name]));
  }, [collaborators]);

  const createOrder = useMutation({
    mutationFn: async (payload: CreateOrderPayload) => {
      await api.post(`${purchaseOrdersPath}/`, payload);
    },
    onSuccess: async () => {
      setMessage("Bon de commande créé.");
      setIsCreateModalOpen(false);
      setDraftLines([{ itemId: "", quantity: 1, lineType: "standard", returnExpected: false }]);
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

  const receiveOrderLines = useMutation({
    mutationFn: async ({ orderId, lines }: ReceiveLinePayload) => {
      await Promise.all(
        lines.map((line) =>
          api.post(`${purchaseOrdersPath}/${orderId}/receive-line`, line)
        )
      );
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

  const validatePendingAssignment = useMutation<
    PendingClothingAssignment,
    AxiosError<ApiErrorResponse>,
    { orderId: number; pendingId: number }
  >({
    mutationFn: async ({ orderId, pendingId }) => {
      const response = await api.post<PendingClothingAssignment>(
        `${purchaseOrdersPath}/${orderId}/pending-assignments/${pendingId}/validate`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Attribution validée.");
      setPendingValidationError(null);
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setPendingValidationError(detail ?? "Impossible de valider l'attribution.");
    },
    onSettled: () => {
      window.setTimeout(() => {
        setMessage(null);
        setPendingValidationError(null);
      }, 4000);
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

  const refreshAutoOrders = useMutation<
    PurchaseOrderAutoRefreshResponse,
    AxiosError<ApiErrorResponse>
  >({
    mutationFn: async () => {
      const response = await api.post<PurchaseOrderAutoRefreshResponse>(
        `${purchaseOrdersPath}/auto/refresh`,
        null,
        { params: { module: moduleKey } }
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
      await queryClient.invalidateQueries({ queryKey: ordersQueryKey });
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
    setDraftLines((prev) => [
      ...prev,
      { itemId: "", quantity: 1, lineType: "standard", returnExpected: false }
    ]);
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
        const lineType = line.lineType ?? "standard";
        const beneficiaryId =
          line.beneficiaryId === "" || line.beneficiaryId === undefined
            ? null
            : Number(line.beneficiaryId);
        const returnReason =
          line.returnReason === "Autre"
            ? line.returnReasonDetail?.trim() || null
            : line.returnReason?.trim() || null;
        const returnEmployeeItemId =
          line.returnEmployeeItemId === "" || line.returnEmployeeItemId === undefined
            ? null
            : Number(line.returnEmployeeItemId);
        return {
          [itemIdField]: itemId,
          quantity_ordered: line.quantity,
          beneficiary_employee_id: beneficiaryId,
          line_type: lineType,
          return_expected: lineType === "replacement",
          return_reason: returnReason,
          return_employee_item_id: returnEmployeeItemId,
          return_qty: lineType === "replacement" ? line.returnQty ?? line.quantity : null
        } satisfies { quantity_ordered: number } & Partial<Record<ItemIdKey, number>>;
      });
    if (normalizedLines.length === 0) {
      setError("Ajoutez au moins une ligne de commande valide.");
      return;
    }
    if (replacementAccess) {
      const invalidReplacement = normalizedLines.find((line) => {
        if (line.line_type !== "replacement") {
          return false;
        }
        return (
          !line.beneficiary_employee_id ||
          !line.return_reason ||
          !line.return_employee_item_id ||
          !line.return_qty ||
          line.return_qty <= 0
        );
      });
      if (invalidReplacement) {
        setError("Complétez le bénéficiaire et le retour attendu pour les remplacements.");
        return;
      }
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
    if (enableReplacementFlow) {
      setReceiveDetails(
        order.items.reduce<
          Record<
            number,
            {
              qty: number;
              conformity_status: "conforme" | "non_conforme";
              nonconformity_reason: string;
              nonconformity_action: "replacement" | "credit_note" | "return_to_supplier" | "";
              note: string;
            }
          >
        >((acc, line) => {
          acc[line.id] = {
            qty: 0,
            conformity_status: "conforme",
            nonconformity_reason: "",
            nonconformity_action: "",
            note: ""
          };
          return acc;
        }, {})
      );
    } else {
      setReceiveQuantities(
        order.items.reduce<Record<number, number>>((acc, line) => {
          acc[line.id] = 0;
          return acc;
        }, {})
      );
    }
  };

  const handleCloseReceiveModal = () => {
    setReceiveFormError(null);
    setReceiveModalOrder(null);
    setReceiveQuantities({});
    setReceiveDetails({});
  };

  const handleSubmitPartialReceive = async () => {
    if (!receiveModalOrder) {
      return;
    }
    if (enableReplacementFlow) {
      const payloadLines = receiveModalOrder.items
        .map((line) => {
          const remaining = line.quantity_ordered - line.quantity_received;
          const details = receiveDetails[line.id];
          const qty = details?.qty ?? 0;
          return {
            line,
            remaining,
            details,
            qty
          };
        })
        .filter((entry) => entry.qty > 0 && entry.details);

      const invalidLine = payloadLines.find((entry) => entry.qty > entry.remaining);
      if (invalidLine) {
        setReceiveFormError("La quantité ne peut pas dépasser le restant à recevoir.");
        return;
      }
      const missingNonConformity = payloadLines.find(
        (entry) =>
          entry.details?.conformity_status === "non_conforme" &&
          (!entry.details.nonconformity_reason.trim() ||
            !entry.details.nonconformity_action)
      );
      if (missingNonConformity) {
        setReceiveFormError("Renseignez un motif et une action pour les non-conformités.");
        return;
      }
      if (payloadLines.length === 0) {
        setReceiveFormError("Renseignez au moins une quantité à réceptionner.");
        return;
      }
      setReceiveFormError(null);
      try {
        await receiveOrderLines.mutateAsync({
          orderId: receiveModalOrder.id,
          lines: payloadLines.map((entry) => ({
            purchase_order_line_id: entry.line.id,
            received_qty: entry.qty,
            conformity_status: entry.details!.conformity_status,
            nonconformity_reason: entry.details!.nonconformity_reason.trim()
              ? entry.details!.nonconformity_reason.trim()
              : null,
            nonconformity_action: entry.details!.nonconformity_action || null,
            note: entry.details!.note.trim() ? entry.details!.note.trim() : null
          }))
        });
        handleCloseReceiveModal();
      } catch {
        // Les erreurs API sont gérées par la mutation
      }
    } else {
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
    }
  };

  const handleFillRemaining = () => {
    if (!receiveModalOrder) {
      return;
    }
    if (enableReplacementFlow) {
      setReceiveDetails((prev) => {
        const next = { ...prev };
        receiveModalOrder.items.forEach((line) => {
          const remaining = line.quantity_ordered - line.quantity_received;
          if (!next[line.id]) {
            next[line.id] = {
              qty: 0,
              conformity_status: "conforme",
              nonconformity_reason: "",
              nonconformity_action: "",
              note: ""
            };
          }
          next[line.id] = {
            ...next[line.id],
            qty: Math.max(0, remaining)
          };
        });
        return next;
      });
    } else {
      setReceiveQuantities(
        receiveModalOrder.items.reduce<Record<number, number>>((acc, line) => {
          const remaining = line.quantity_ordered - line.quantity_received;
          acc[line.id] = Math.max(0, remaining);
          return acc;
        }, {})
      );
    }
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
        <div className="flex flex-wrap gap-2">
          {canRefresh ? (
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
          ) : null}
          <button
            type="button"
            onClick={handleOpenCreateModal}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
          >
            Créer un bon de commande
          </button>
        </div>
      </header>

      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {refreshSummary ? <p className="text-xs text-slate-400">{refreshSummary}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      {pendingValidationError ? (
        <p className="text-sm text-red-400">{pendingValidationError}</p>
      ) : null}

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
                            const lineReceipts = (order.receipts ?? []).filter(
                              (receipt) => receipt.purchase_order_line_id === line.id
                            );
                            const hasNonConforming = lineReceipts.some(
                              (receipt) => receipt.conformity_status === "non_conforme"
                            );
                            const hasConforming = lineReceipts.some(
                              (receipt) => receipt.conformity_status === "conforme"
                            );
                            return (
                              <li key={line.id}>
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-semibold">
                                    {line.item_name ?? `#${itemId}`}
                                  </span>
                                  <span>
                                    {line.quantity_received}/{line.quantity_ordered}
                                  </span>
                                  {hasConforming ? (
                                    <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-200">
                                      Conforme
                                    </span>
                                  ) : null}
                                  {hasNonConforming ? (
                                    <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] text-rose-200">
                                      NC
                                    </span>
                                  ) : null}
                                </div>
                                {line.beneficiary_employee_id ? (
                                  <p className="text-[11px] text-slate-400">
                                    Bénéficiaire:{" "}
                                    {line.beneficiary_name ??
                                      resolveCollaboratorName(line.beneficiary_employee_id)}
                                  </p>
                                ) : null}
                                {line.line_type === "replacement" ? (
                                  <p className="text-[11px] text-slate-400">
                                    Retour attendu:{" "}
                                    {line.return_expected ? "Oui" : "Non"}
                                    {line.return_reason ? ` · ${line.return_reason}` : ""}
                                    {line.return_status ? ` · ${line.return_status}` : ""}
                                  </p>
                                ) : null}
                              </li>
                            );
                          })}
                          {(order.pending_assignments ?? []).some(
                            (assignment) => assignment.status === "pending"
                          ) ? (
                            <li className="space-y-2 pt-2">
                              <p className="text-[11px] uppercase text-slate-500">
                                Attributions en attente
                              </p>
                              {(order.pending_assignments ?? [])
                                .filter((assignment) => assignment.status === "pending")
                                .map((assignment) => (
                                  <div
                                    key={assignment.id}
                                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-1"
                                  >
                                    <div>
                                      <p className="text-xs text-slate-200">
                                        {resolveCollaboratorName(assignment.employee_id)} ·{" "}
                                        {resolveItemLabel(assignment.new_item_id)}
                                      </p>
                                      {assignment.return_employee_item_id ? (
                                        <p className="text-[11px] text-slate-400">
                                          Retour:{" "}
                                          {(() => {
                                            const matched = (
                                              assignedItemsByBeneficiary.get(assignment.employee_id) ??
                                              []
                                            ).find(
                                              (item) =>
                                                item.assignment_id === assignment.return_employee_item_id
                                            );
                                            return matched
                                              ? resolveAssignedItemLabel(matched)
                                              : `#${assignment.return_employee_item_id}`;
                                          })()}
                                          {assignment.return_reason
                                            ? ` · ${assignment.return_reason}`
                                            : ""}
                                        </p>
                                      ) : null}
                                    </div>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        validatePendingAssignment.mutate({
                                          orderId: order.id,
                                          pendingId: assignment.id
                                        })
                                      }
                                      disabled={validatePendingAssignment.isPending}
                                      className="rounded bg-indigo-500 px-2 py-1 text-[11px] font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                                    >
                                      Valider attribution + retour
                                    </button>
                                  </div>
                                ))}
                            </li>
                          ) : null}
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
                            onClick={() => {
                              if (enableReplacementFlow) {
                                receiveOrderLines.mutate({
                                  orderId: order.id,
                                  lines: outstanding.map((line) => ({
                                    purchase_order_line_id: line.line_id,
                                    received_qty: line.qty,
                                    conformity_status: "conforme",
                                    nonconformity_reason: null,
                                    nonconformity_action: null,
                                    note: null
                                  }))
                                });
                              } else {
                                receiveOrder.mutate({ orderId: order.id, lines: outstanding });
                              }
                            }}
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
          <label className="text-xs font-semibold text-slate-300" htmlFor="po-status">
            Statut initial
          </label>
          <select
            id="po-status"
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
            <div className="flex min-w-0 gap-2">
              <AppTextInput
                id="po-barcode-input"
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
          {draftLines.map((line, index) => {
            const selectedItem =
              typeof line.itemId === "number" ? itemsById.get(line.itemId) : undefined;
            const beneficiaryId =
              typeof line.beneficiaryId === "number" ? line.beneficiaryId : null;
            const beneficiaryAssignments = beneficiaryId
              ? assignedItemsByBeneficiary.get(beneficiaryId) ?? []
              : [];
            const filteredAssignments =
              selectedItem && beneficiaryAssignments.length > 0
                ? beneficiaryAssignments.filter((assignment) => {
                    const item = itemsById.get(assignment.item_id);
                    return (
                      item &&
                      item.category_id === selectedItem.category_id &&
                      item.size === selectedItem.size
                    );
                  })
                : [];
            const returnOptions =
              filteredAssignments.length > 0 ? filteredAssignments : beneficiaryAssignments;
            const isFiltered = filteredAssignments.length > 0;
            return (
              <div
                key={index}
                className="space-y-3 rounded-md border border-slate-800 bg-slate-950/60 p-3"
              >
                <div className="flex min-w-0 flex-wrap gap-2">
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
                    className="w-full min-w-0 flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
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
                        const qty = Number(event.target.value);
                        next[index] = {
                          ...next[index],
                          quantity: qty,
                          returnQty:
                            next[index].lineType === "replacement" ? qty : next[index].returnQty
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

                {enableReplacementFlow ? (
                  replacementAccess ? (
                  <div className="space-y-3 text-sm text-slate-200">
                    <label className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                      <input
                        type="checkbox"
                        checked={line.lineType === "replacement"}
                        onChange={(event) =>
                          setDraftLines((prev) => {
                            const next = [...prev];
                            const isReplacement = event.target.checked;
                            next[index] = {
                              ...next[index],
                              lineType: isReplacement ? "replacement" : "standard",
                              returnExpected: isReplacement,
                              beneficiaryId: isReplacement ? next[index].beneficiaryId ?? "" : "",
                              returnReason: isReplacement
                                ? next[index].returnReason ?? RETURN_REASONS[0]
                                : "",
                              returnEmployeeItemId: isReplacement
                                ? next[index].returnEmployeeItemId ?? ""
                                : "",
                              returnQty: isReplacement ? next[index].returnQty ?? line.quantity : 0
                            };
                            return next;
                          })
                        }
                      />
                      Remplacement / Retour fournisseur
                    </label>

                    {line.lineType === "replacement" ? (
                      <>
                        <div className="grid gap-2 md:grid-cols-2">
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-300">
                              Bénéficiaire (doté)
                            </label>
                            <select
                              value={line.beneficiaryId ?? ""}
                              onChange={(event) =>
                                setDraftLines((prev) => {
                                  const next = [...prev];
                                  next[index] = {
                                    ...next[index],
                                    beneficiaryId: event.target.value
                                      ? Number(event.target.value)
                                      : "",
                                    returnEmployeeItemId: ""
                                  };
                                  return next;
                                })
                              }
                              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                            >
                              <option value="">Sélectionnez un collaborateur (doté)</option>
                              {assignees.map((beneficiary) => (
                                <option
                                  key={beneficiary.employee_id}
                                  value={beneficiary.employee_id}
                                >
                                  {beneficiary.display_name}
                                  {beneficiary.count > 0
                                    ? ` (${beneficiary.count} ${
                                        beneficiary.count > 1 ? "articles" : "article"
                                      })`
                                    : ""}
                                </option>
                              ))}
                            </select>
                            {assignees.length === 0 ? (
                              <p className="text-xs text-slate-400">
                                Aucun collaborateur doté sur ce site.
                              </p>
                            ) : null}
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-300">
                              Article attribué à retourner
                            </label>
                            <select
                              value={line.returnEmployeeItemId ?? ""}
                              onChange={(event) =>
                                setDraftLines((prev) => {
                                  const next = [...prev];
                                  next[index] = {
                                    ...next[index],
                                    returnEmployeeItemId: event.target.value
                                      ? Number(event.target.value)
                                      : ""
                                  };
                                  return next;
                                })
                              }
                              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                              disabled={!beneficiaryId}
                            >
                              <option value="">
                                {beneficiaryId
                                  ? "Sélectionnez une dotation"
                                  : "Choisissez d'abord un collaborateur"}
                              </option>
                              {returnOptions.map((assignment) => (
                                <option
                                  key={assignment.assignment_id}
                                  value={assignment.assignment_id}
                                >
                                  {resolveAssignedItemLabel(assignment)}
                                </option>
                              ))}
                            </select>
                            {beneficiaryId && isFiltered ? (
                              <p className="text-xs text-slate-400">
                                Suggestions basées sur la catégorie et la taille de l'article.
                              </p>
                            ) : null}
                          </div>
                        </div>
                        <div className="grid gap-2 md:grid-cols-2">
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-300">
                              Motif du retour
                            </label>
                            <select
                              value={line.returnReason ?? RETURN_REASONS[0]}
                              onChange={(event) =>
                                setDraftLines((prev) => {
                                  const next = [...prev];
                                  next[index] = {
                                    ...next[index],
                                    returnReason: event.target.value,
                                    returnReasonDetail:
                                      event.target.value === "Autre"
                                        ? next[index].returnReasonDetail ?? ""
                                        : ""
                                  };
                                  return next;
                                })
                              }
                              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                            >
                              {RETURN_REASONS.map((reason) => (
                                <option key={reason} value={reason}>
                                  {reason}
                                </option>
                              ))}
                            </select>
                            {line.returnReason === "Autre" ? (
                              <AppTextInput
                                value={line.returnReasonDetail ?? ""}
                                onChange={(event) =>
                                  setDraftLines((prev) => {
                                    const next = [...prev];
                                    next[index] = {
                                      ...next[index],
                                      returnReasonDetail: event.target.value
                                    };
                                    return next;
                                  })
                                }
                                placeholder="Précisez le motif"
                                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                              />
                            ) : null}
                          </div>
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-300">
                              Quantité retour
                            </label>
                            <AppTextInput
                              type="number"
                              min={1}
                              value={line.returnQty ?? line.quantity}
                              onChange={(event) =>
                                setDraftLines((prev) => {
                                  const next = [...prev];
                                  next[index] = {
                                    ...next[index],
                                    returnQty: Number(event.target.value)
                                  };
                                  return next;
                                })
                              }
                              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                            />
                          </div>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Accès dotations requis.</p>
                )
                ) : null}
              </div>
            );
          })}
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
                disabled={enableReplacementFlow ? receiveOrderLines.isPending : receiveOrder.isPending}
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
              {enableReplacementFlow
                ? receiveModalOrder.items.map((line) => {
                    const remaining = line.quantity_ordered - line.quantity_received;
                    const itemId = resolveItemId(line);
                    const details = receiveDetails[line.id] ?? {
                      qty: 0,
                      conformity_status: "conforme",
                      nonconformity_reason: "",
                      nonconformity_action: "",
                      note: ""
                    };
                    return (
                      <div
                        key={line.id}
                        className="space-y-3 rounded-md border border-slate-800 bg-slate-950 px-3 py-2"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
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
                            value={details.qty}
                            onChange={(event) =>
                              setReceiveDetails((prev) => ({
                                ...prev,
                                [line.id]: {
                                  ...details,
                                  qty: Number(event.target.value)
                                }
                              }))
                            }
                            disabled={remaining <= 0}
                            className="w-28 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                          />
                        </div>
                        <div className="grid gap-2 md:grid-cols-2">
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-300">
                              Conformité
                            </label>
                            <select
                              value={details.conformity_status}
                              onChange={(event) =>
                                setReceiveDetails((prev) => ({
                                  ...prev,
                                  [line.id]: {
                                    ...details,
                                    conformity_status:
                                      event.target.value === "non_conforme"
                                        ? "non_conforme"
                                        : "conforme"
                                  }
                                }))
                              }
                              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
                            >
                              <option value="conforme">Conforme</option>
                              <option value="non_conforme">Non conforme</option>
                            </select>
                          </div>
                          {details.conformity_status === "non_conforme" ? (
                            <div className="space-y-1">
                              <label className="text-xs font-semibold text-slate-300">
                                Action
                              </label>
                              <select
                                value={details.nonconformity_action}
                                onChange={(event) =>
                                  setReceiveDetails((prev) => ({
                                    ...prev,
                                    [line.id]: {
                                      ...details,
                                      nonconformity_action:
                                        event.target.value as typeof details.nonconformity_action
                                    }
                                  }))
                                }
                                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
                              >
                                <option value="">Sélectionnez une action</option>
                                <option value="replacement">Remplacement</option>
                                <option value="credit_note">Avoir</option>
                                <option value="return_to_supplier">Retour fournisseur</option>
                              </select>
                            </div>
                          ) : null}
                        </div>
                        {details.conformity_status === "non_conforme" ? (
                          <div className="grid gap-2 md:grid-cols-2">
                            <div className="space-y-1">
                              <label className="text-xs font-semibold text-slate-300">
                                Motif non conforme
                              </label>
                              <AppTextInput
                                value={details.nonconformity_reason}
                                onChange={(event) =>
                                  setReceiveDetails((prev) => ({
                                    ...prev,
                                    [line.id]: {
                                      ...details,
                                      nonconformity_reason: event.target.value
                                    }
                                  }))
                                }
                                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
                              />
                            </div>
                            <div className="space-y-1">
                              <label className="text-xs font-semibold text-slate-300">
                                Note
                              </label>
                              <AppTextInput
                                value={details.note}
                                onChange={(event) =>
                                  setReceiveDetails((prev) => ({
                                    ...prev,
                                    [line.id]: {
                                      ...details,
                                      note: event.target.value
                                    }
                                  }))
                                }
                                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none"
                              />
                            </div>
                          </div>
                        ) : null}
                      </div>
                    );
                  })
                : receiveModalOrder.items.map((line) => {
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
