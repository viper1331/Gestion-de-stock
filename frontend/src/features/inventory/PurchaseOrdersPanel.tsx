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
import { Timeline, type TimelineEvent } from "components/Timeline";
import { StatusBadge } from "components/StatusBadge";
import { TruncatedText } from "components/TruncatedText";
import { fetchQolSettings, DEFAULT_QOL_SETTINGS } from "../../lib/qolSettings";

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
  is_lost?: boolean;
  is_degraded?: boolean;
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
  sku?: string | null;
  size?: string | null;
  unit?: string | null;
  quantity_ordered: number;
  quantity_received: number;
  received_conforme_qty?: number;
  received_non_conforme_qty?: number;
  nonconformity_reason?: string | null;
  is_nonconforme?: boolean;
  beneficiary_employee_id?: number | null;
  beneficiary_name?: string | null;
  line_type?: "standard" | "replacement";
  return_expected?: boolean;
  return_reason?: string | null;
  return_employee_item_id?: number | null;
  target_dotation_id?: number | null;
  return_qty?: number;
  return_status?: "none" | "to_prepare" | "shipped" | "supplier_received" | "cancelled";
}

interface PurchaseOrderReceipt {
  id: number;
  purchase_order_id: number;
  purchase_order_line_id: number;
  module?: string | null;
  received_qty: number;
  conformity_status: "conforme" | "non_conforme";
  nonconformity_reason?: string | null;
  nonconformity_action?: string | null;
  note?: string | null;
  created_by?: string | null;
  created_at: string;
}

interface PurchaseOrderNonconformity {
  id: number;
  module: string;
  purchase_order_id: number;
  purchase_order_line_id: number;
  receipt_id: number;
  status: "open" | "replacement_requested" | "closed";
  reason: string;
  note?: string | null;
  requested_replacement: boolean;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
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
  target_dotation_id?: number | null;
  return_reason?: string | null;
  status: "pending" | "validated" | "cancelled";
  created_at: string;
  validated_at?: string | null;
  validated_by?: string | null;
  source_receipt?: PurchaseOrderReceipt | null;
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
  parent_id?: number | null;
  replacement_for_line_id?: number | null;
  kind?: "standard" | "replacement_request";
  status: string;
  created_at: string;
  note: string | null;
  auto_created: boolean;
  last_sent_at: string | null;
  last_sent_to: string | null;
  last_sent_by: string | null;
  is_archived?: boolean;
  archived_at?: string | null;
  archived_by?: number | null;
  items: PurchaseOrderItem[];
  receipts?: PurchaseOrderReceipt[];
  nonconformities?: PurchaseOrderNonconformity[];
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
        target_dotation_id?: number | null;
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
    note?: string | null;
  }>;
}

interface RequestReplacementPayload {
  orderId: number;
  lineId: number;
}

interface PurchaseOrderReplacementResponse {
  replacement_order_id: number;
  replacement_order_status: string;
  can_send_to_supplier: boolean;
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

interface ReplacementFinalizeSummary {
  lineId: number;
  itemLabel: string;
  sizeLabel: string;
  qty: number;
  reason: string;
}

interface FinalizeNonconformityModalData {
  order: PurchaseOrderDetail;
  replacementOrder: PurchaseOrderDetail;
  lines: ReplacementFinalizeSummary[];
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

const NONCONFORMITY_REASONS = [
  "Endommagé",
  "Erreur taille",
  "Erreur référence",
  "Manquant",
  "Autre"
];

type PrimaryOrderStatus =
  | "CONFORME"
  | "NON_CONFORME"
  | "REMPLACEMENT_DEMANDE"
  | "REMPLACEMENT_EN_COURS"
  | "ARCHIVE";

const STATUS_BADGE_LABELS: Record<PrimaryOrderStatus, { label: string; tone: "success" | "danger" | "warning" | "info" | "neutral"; tooltip: string }> = {
  CONFORME: {
    label: "Conforme",
    tone: "success",
    tooltip: "Bon de commande réceptionné sans non-conformité."
  },
  NON_CONFORME: {
    label: "Non conforme",
    tone: "danger",
    tooltip: "Réception non conforme en attente de traitement."
  },
  REMPLACEMENT_DEMANDE: {
    label: "Remplacement demandé",
    tone: "warning",
    tooltip: "Une demande de remplacement a été créée."
  },
  REMPLACEMENT_EN_COURS: {
    label: "Remplacement en cours",
    tone: "info",
    tooltip: "Demande de remplacement envoyée au fournisseur."
  },
  ARCHIVE: {
    label: "Archivé",
    tone: "neutral",
    tooltip: "Bon de commande archivé en lecture seule."
  }
};


interface DraftLine {
  itemId: number | "";
  quantity: number;
  lineType?: "standard" | "replacement";
  beneficiaryId?: number | "";
  returnExpected?: boolean;
  returnReason?: string;
  returnReasonDetail?: string;
  targetDotationId?: number | "";
  returnQty?: number;
}

const buildPurchaseOrderTimeline = (order: PurchaseOrderDetail): TimelineEvent[] => {
  const events: TimelineEvent[] = [];
  const itemsById = new Map(order.items.map((line) => [line.id, line]));

  events.push({
    id: `creation-${order.id}`,
    type: "CREATION",
    date: order.created_at,
    user: null,
    message: order.auto_created ? "Création automatique du bon de commande." : "Bon de commande créé."
  });

  if (order.last_sent_at) {
    events.push({
      id: `send-${order.id}-${order.last_sent_at}`,
      type: "ENVOI_FOURNISSEUR",
      date: order.last_sent_at,
      user: order.last_sent_by,
      message: order.last_sent_to
        ? `Bon de commande envoyé à ${order.last_sent_to}.`
        : "Bon de commande envoyé au fournisseur."
    });
  }

  (order.receipts ?? []).forEach((receipt) => {
    const item = itemsById.get(receipt.purchase_order_line_id);
    const itemLabel = item?.item_name ?? `Ligne #${receipt.purchase_order_line_id}`;
    const reason = receipt.nonconformity_reason ? ` · Motif: ${receipt.nonconformity_reason}` : "";
    events.push({
      id: `receipt-${receipt.id}`,
      type: receipt.conformity_status === "conforme" ? "RECEPTION_CONFORME" : "NON_CONFORME",
      date: receipt.created_at,
      user: receipt.created_by,
      message: `${itemLabel} · ${receipt.received_qty} reçu${receipt.received_qty > 1 ? "s" : ""}${reason}.`
    });
  });

  (order.nonconformities ?? []).forEach((nonconformity) => {
    if (!nonconformity.requested_replacement) {
      return;
    }
    events.push({
      id: `replacement-${nonconformity.id}`,
      type: "REMPLACEMENT_DEMANDE",
      date: nonconformity.created_at,
      user: nonconformity.created_by,
      message: `Demande de remplacement · ${nonconformity.reason}.`
    });
  });

  if (order.kind === "replacement_request" && order.status === "RECEIVED") {
    events.push({
      id: `replacement-received-${order.id}`,
      type: "RECEPTION_REMPLACEMENT",
      date: order.archived_at ?? order.created_at,
      user: null,
      message: "Réception du remplacement confirmée."
    });
  }

  if (order.archived_at) {
    events.push({
      id: `archive-${order.id}`,
      type: "ARCHIVAGE",
      date: order.archived_at,
      user: null,
      message: "Bon de commande archivé."
    });
  }

  return events.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
};

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
  const { data: qolSettings } = useQuery({
    queryKey: ["qol-settings"],
    queryFn: fetchQolSettings,
    enabled: Boolean(user)
  });
  const notePreviewLength = qolSettings?.note_preview_length ?? DEFAULT_QOL_SETTINGS.note_preview_length;
  const canSendEmail = useMemo(
    () => Boolean(user && (user.role === "admin" || modulePermissions.canAccess("clothing", "edit"))),
    [modulePermissions, user]
  );
  const canManageOrders = useMemo(
    () => Boolean(user && (user.role === "admin" || modulePermissions.canAccess(moduleKey, "edit"))),
    [moduleKey, modulePermissions, user]
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
  const [finalizeModalData, setFinalizeModalData] =
    useState<FinalizeNonconformityModalData | null>(null);
  const [archiveModalOrder, setArchiveModalOrder] = useState<PurchaseOrderDetail | null>(null);
  const [archiveFilter, setArchiveFilter] = useState<"active" | "archived">("active");
  const [receiveQuantities, setReceiveQuantities] = useState<Record<number, number>>({});
  const [receiveFormError, setReceiveFormError] = useState<string | null>(null);
  const [expandedLines, setExpandedLines] = useState<Set<number>>(new Set());
  const [receiveDetails, setReceiveDetails] = useState<
    Record<
      number,
      {
        qty: number;
        conformity_status: "conforme" | "non_conforme";
        nonconformity_reason: string;
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
  const showArchived = archiveFilter === "archived";
  const ordersCacheKey = useMemo(
    () => (Array.isArray(ordersQueryKey) ? ordersQueryKey : [ordersQueryKey]),
    [ordersQueryKey]
  );
  const resolvedOrdersQueryKey = useMemo(
    () => [...ordersCacheKey, showArchived ? "archived" : "active"],
    [ordersCacheKey, showArchived]
  );

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
        targetDotationId: "",
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
    const statusLabel = assignedItem.is_lost
      ? assignedItem.is_degraded
        ? "PERTE/DÉGRADATION"
        : "PERTE"
      : assignedItem.is_degraded
        ? "DÉGRADATION"
        : "RAS";
    return `${assignedItem.name}${sku} — ${size} — ${statusLabel} — x${assignedItem.qty}`;
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

  const resolveOrderStatusLabel = (status: string) => {
    const match = ORDER_STATUSES.find((option) => option.value === status);
    return match ? match.label : status;
  };

  const resolveReplacementStatusLabel = (status: string) => {
    if (status === "PENDING") {
      return "À préparer";
    }
    return resolveOrderStatusLabel(status);
  };

  const { data: orders = [], isLoading: loadingOrders } = useQuery({
    queryKey: resolvedOrdersQueryKey,
    queryFn: async () => {
      const response = await api.get<PurchaseOrderDetail[]>(`${purchaseOrdersPath}/`, {
        params: showArchived ? { include_archived: true } : undefined
      });
      return response.data.map((order) => ({
        ...order,
        kind: order.kind ?? "standard",
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

  const replacementOrdersByParent = useMemo(() => {
    const map = new Map<number, Map<number, PurchaseOrderDetail>>();
    orders.forEach((order) => {
      if (order.kind !== "replacement_request" || !order.parent_id) {
        return;
      }
      const lineId = order.replacement_for_line_id;
      if (!lineId) {
        return;
      }
      const existing = map.get(order.parent_id) ?? new Map<number, PurchaseOrderDetail>();
      existing.set(lineId, order);
      map.set(order.parent_id, existing);
    });
    return map;
  }, [orders]);

  const visibleOrders = useMemo(
    () =>
      orders.filter(
        (order) =>
          order.kind !== "replacement_request" &&
          (showArchived ? order.is_archived : !order.is_archived)
      ),
    [orders, showArchived]
  );

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
        if (
          (assignment.target_dotation_id || assignment.return_employee_item_id) &&
          assignment.employee_id
        ) {
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
    },
    onError: () => setError("Impossible d'enregistrer la réception."),
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const requestReplacement = useMutation<
    PurchaseOrderReplacementResponse,
    AxiosError<ApiErrorResponse>,
    RequestReplacementPayload
  >({
    mutationFn: async ({ orderId, lineId }) => {
      const response = await api.post<PurchaseOrderReplacementResponse>(
        `${purchaseOrdersPath}/${orderId}/nonconformities/${lineId}/replacement-request`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Demande de remplacement créée.");
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de créer la demande de remplacement.");
    },
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
      await queryClient.invalidateQueries({ queryKey: ["clothing-dotations-assignees"] });
      await queryClient.invalidateQueries({ queryKey: ["clothing-assigned-items"] });
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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

  const sendReplacementToSupplier = useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { order: PurchaseOrderDetail; contextNote: string }
  >({
    mutationFn: async ({ order, contextNote }) => {
      await api.post(`${purchaseOrdersPath}/${order.id}/send-to-supplier`, {
        context_note: contextNote
      });
    },
    onSuccess: async (_, { order }) => {
      setMessage("Demande de remplacement envoyée.");
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
      await queryClient.invalidateQueries({
        queryKey: ["purchase-order-email-log", order.id]
      });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible d'envoyer la demande de remplacement.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const finalizeNonconformity = useMutation<
    PurchaseOrderDetail,
    AxiosError<ApiErrorResponse>,
    { orderId: number }
  >({
    mutationFn: async ({ orderId }) => {
      const response = await api.post<PurchaseOrderDetail>(
        `${purchaseOrdersPath}/${orderId}/finalize-nonconformity`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Non-conformité finalisée.");
      setFinalizeModalData(null);
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
      await queryClient.invalidateQueries({ queryKey: itemsQueryKey });
      await queryClient.invalidateQueries({ queryKey: ["clothing-dotations-assignees"] });
      await queryClient.invalidateQueries({ queryKey: ["clothing-assigned-items"] });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de finaliser la non-conformité.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const archiveOrder = useMutation<PurchaseOrderDetail, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (orderId) => {
      const response = await api.post<PurchaseOrderDetail>(
        `${purchaseOrdersPath}/${orderId}/archive`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Bon de commande archivé.");
      setArchiveModalOrder(null);
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible d'archiver le bon de commande.");
    },
    onSettled: () => {
      window.setTimeout(() => setMessage(null), 4000);
    }
  });

  const unarchiveOrder = useMutation<PurchaseOrderDetail, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (orderId) => {
      const response = await api.post<PurchaseOrderDetail>(
        `${purchaseOrdersPath}/${orderId}/unarchive`
      );
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Bon de commande restauré.");
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
    },
    onError: (mutationError) => {
      const detail = mutationError.response?.data?.detail;
      setError(detail ?? "Impossible de restaurer le bon de commande.");
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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
      await queryClient.invalidateQueries({ queryKey: ordersCacheKey });
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
        const targetDotationId =
          line.targetDotationId === "" || line.targetDotationId === undefined
            ? null
            : Number(line.targetDotationId);
        return {
          [itemIdField]: itemId,
          quantity_ordered: line.quantity,
          beneficiary_employee_id: beneficiaryId,
          line_type: lineType,
          return_expected: lineType === "replacement",
          return_reason: returnReason,
          return_employee_item_id: targetDotationId,
          target_dotation_id: targetDotationId,
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
          !line.target_dotation_id ||
          !line.return_qty ||
          line.return_qty <= 0
        );
      });
      if (invalidReplacement) {
        setError(
          "Complétez le bénéficiaire et la dotation en PERTE/DÉGRADATION à remplacer."
        );
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
              note: string;
            }
          >
        >((acc, line) => {
          acc[line.id] = {
            qty: 0,
            conformity_status: "conforme",
            nonconformity_reason: "",
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

  const handleCloseFinalizeModal = () => {
    setFinalizeModalData(null);
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
          !entry.details.nonconformity_reason.trim()
      );
      if (missingNonConformity) {
        setReceiveFormError("Renseignez un motif pour les non-conformités.");
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

  const handleOpenArchiveModal = (order: PurchaseOrderDetail) => {
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

  const handleUnarchiveOrder = (order: PurchaseOrderDetail) => {
    if (
      !window.confirm(
        `Désarchiver le bon de commande #${order.id} ? Il réapparaîtra dans la liste active.`
      )
    ) {
      return;
    }
    unarchiveOrder.mutate(order.id);
  };

  const toggleExpandedLines = (orderId: number) => {
    setExpandedLines((prev) => {
      const next = new Set(prev);
      if (next.has(orderId)) {
        next.delete(orderId);
      } else {
        next.add(orderId);
      }
      return next;
    });
  };

  const orderViews = visibleOrders.map((order) => {
    const isArchived = Boolean(order.is_archived);
    const isReadOnly = isArchived;
    const timelineEvents = buildPurchaseOrderTimeline(order);
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
    const canReceive = outstanding.length > 0 && !isReadOnly;
    const receiptsByLine = new Map<number, PurchaseOrderReceipt[]>();
    (order.receipts ?? []).forEach((receipt) => {
      const existing = receiptsByLine.get(receipt.purchase_order_line_id) ?? [];
      existing.push(receipt);
      receiptsByLine.set(receipt.purchase_order_line_id, existing);
    });
    const nonconformingLineSummaries = order.items
      .map((line) => {
        const lineReceipts = receiptsByLine.get(line.id) ?? [];
        const latestReceipt =
          lineReceipts.length > 0 ? lineReceipts[lineReceipts.length - 1] : null;
        if (latestReceipt?.conformity_status !== "non_conforme") {
          return null;
        }
        const sizeLabel = line.size?.trim() ? line.size.trim() : "—";
        return {
          lineId: line.id,
          itemLabel: line.item_name ?? `#${resolveItemId(line) ?? "?"}`,
          sizeLabel,
          qty: line.received_non_conforme_qty ?? 0,
          reason:
            latestReceipt.nonconformity_reason?.trim() ||
            line.nonconformity_reason?.trim() ||
            "Motif non renseigné"
        } satisfies ReplacementFinalizeSummary;
      })
      .filter((entry): entry is ReplacementFinalizeSummary => entry !== null);
    const hasNonConformingLatestReceipt = nonconformingLineSummaries.length > 0;
    const pendingAssignments = (order.pending_assignments ?? []).filter(
      (assignment) => assignment.status === "pending"
    );
    const conformingPendingAssignments = pendingAssignments.filter(
      (assignment) => assignment.source_receipt?.conformity_status === "conforme"
    );
    const replacementOrdersForLines =
      replacementOrdersByParent.get(order.id) ?? new Map<number, PurchaseOrderDetail>();
    const replacementOrders = Array.from(replacementOrdersForLines.values());
    const replacementRequested =
      hasNonConformingLatestReceipt &&
      ((order.nonconformities ?? []).some((nonconformity) => nonconformity.requested_replacement) ||
        replacementOrders.length > 0);
    const sentReplacementOrders = replacementOrders
      .filter((replacement) => Boolean(replacement.last_sent_at))
      .sort((a, b) => {
        const aSent = a.last_sent_at ? new Date(a.last_sent_at).getTime() : 0;
        const bSent = b.last_sent_at ? new Date(b.last_sent_at).getTime() : 0;
        return bSent - aSent;
      });
    const replacementToSend = replacementOrders.find(
      (replacement) => !replacement.last_sent_at
    );
    const replacementContextNote = nonconformingLineSummaries.length
      ? `Motif non-conformité : ${nonconformingLineSummaries
          .map((line) => line.reason)
          .join(", ")}`
      : "Motif non-conformité : non renseigné";
    const canFinalizeNonconformity =
      enableReplacementFlow &&
      hasNonConformingLatestReceipt &&
      sentReplacementOrders.length > 0;
    const canArchive =
      canManageOrders &&
      order.status === "RECEIVED" &&
      outstanding.length === 0 &&
      !hasNonConformingLatestReceipt &&
      pendingAssignments.length === 0;
    let primaryStatus: PrimaryOrderStatus = "CONFORME";
    if (isArchived) {
      primaryStatus = "ARCHIVE";
    } else if (hasNonConformingLatestReceipt) {
      if (replacementOrders.length > 0) {
        primaryStatus =
          sentReplacementOrders.length > 0 ? "REMPLACEMENT_EN_COURS" : "REMPLACEMENT_DEMANDE";
      } else if (replacementRequested) {
        primaryStatus = "REMPLACEMENT_DEMANDE";
      } else {
        primaryStatus = "NON_CONFORME";
      }
    } else if (order.status === "RECEIVED") {
      primaryStatus = "CONFORME";
    }
    const primaryBadge = STATUS_BADGE_LABELS[primaryStatus];
    let primaryActionKey: string | null = null;
    if (isArchived && canManageOrders) {
      primaryActionKey = "unarchive";
    } else if (canFinalizeNonconformity) {
      primaryActionKey = "receive_all";
    } else if (hasNonConformingLatestReceipt && !replacementRequested && !isReadOnly) {
      primaryActionKey = "request_replacement";
    } else if (hasNonConformingLatestReceipt && replacementToSend) {
      primaryActionKey = "send_replacement";
    } else if (canReceive) {
      primaryActionKey = "receive_all";
    } else if (canSendEmail && order.status !== "RECEIVED") {
      primaryActionKey = "send_supplier";
    } else if (canArchive) {
      primaryActionKey = "archive";
    }
    const receiveAllLabel = canFinalizeNonconformity ? "Valider conforme" : "Réceptionner tout";
    const createdAtLabel = new Date(order.created_at).toLocaleString();
    const shouldClampLines = order.items.length > 3;
    const isExpanded = expandedLines.has(order.id);
    const statusControl = isArchived ? (
      <span className="text-xs text-slate-300">{resolveOrderStatusLabel(order.status)}</span>
    ) : (
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
        disabled={!canManageOrders}
      >
        {ORDER_STATUSES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
    const lineRequestActionClass =
      primaryActionKey === "request_replacement"
        ? "rounded bg-rose-500 px-3 py-1 text-[11px] font-semibold text-white hover:bg-rose-400 ring-1 ring-white/20 disabled:cursor-not-allowed disabled:opacity-60"
        : "rounded border border-rose-400/60 px-3 py-1 text-[11px] font-semibold text-rose-200 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-60";

    const linesList = (
      <ul className="space-y-1 text-xs">
        {order.items.map((line) => {
          const itemId = resolveItemId(line);
          const receipts = receiptsByLine.get(line.id) ?? [];
          const latestReceipt =
            receipts.length > 0 ? receipts[receipts.length - 1] : null;
          const lineNonconformity = (order.nonconformities ?? []).find(
            (nonconformity) =>
              nonconformity.purchase_order_line_id === line.id &&
              (!latestReceipt || nonconformity.receipt_id === latestReceipt.id)
          );
          const latestIsNonConforming =
            latestReceipt?.conformity_status === "non_conforme" ||
            latestReceipt?.is_non_conforming === true ||
            latestReceipt?.non_conforming === true;
          const replacementOrder = replacementOrdersForLines.get(line.id);
          const replacementRequested =
            Boolean(replacementOrder) ||
            Boolean(lineNonconformity?.requested_replacement);
          const receivedConformeQty =
            line.received_conforme_qty ?? line.quantity_received;
          const receivedNonConformeQty = line.received_non_conforme_qty ?? 0;
          return (
            <li key={line.id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">
                  {line.item_name ?? `#${itemId}`}
                </span>
                <span>
                  Conforme: {receivedConformeQty}/{line.quantity_ordered} — Non
                  conforme: {receivedNonConformeQty}
                </span>
                {latestReceipt?.conformity_status === "conforme" ? (
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-200">
                    Conforme
                  </span>
                ) : null}
                {latestReceipt?.conformity_status === "non_conforme" ? (
                  <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] text-rose-200">
                    Non conforme
                  </span>
                ) : null}
              </div>
              {latestReceipt?.conformity_status === "non_conforme" ? (
                <p className="text-[11px] text-rose-300">
                  {latestReceipt.nonconformity_reason
                    ? `Motif: ${latestReceipt.nonconformity_reason}`
                    : "Motif non renseigné"}
                  {latestReceipt.note ? ` · Note: ${latestReceipt.note}` : ""}
                </p>
              ) : null}
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
              {latestIsNonConforming ? (
                <div className="mt-2 space-y-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase text-rose-200">
                    <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] text-rose-200">
                      Non conforme
                    </span>
                    <span>Action recommandée</span>
                  </div>
                  <p className="text-[11px] text-rose-100/90">
                    Motif:{" "}
                    {latestReceipt?.nonconformity_reason ?? "Non précisé"}
                  </p>
                  <p className="text-[11px] text-rose-100/90">
                    Bénéficiaire:{" "}
                    {line.beneficiary_employee_id
                      ? line.beneficiary_name ??
                        resolveCollaboratorName(line.beneficiary_employee_id)
                      : "Non renseigné"}
                  </p>
                  <p className="text-[11px] text-rose-100/90">
                    Retour attendu: {line.return_expected ? "Oui" : "Non"}
                    {line.return_reason ? ` · ${line.return_reason}` : ""}
                  </p>
                  {replacementRequested ? (
                    <div className="space-y-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-2 text-[11px] text-emerald-200">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] uppercase text-emerald-200">
                          Remplacement demandé
                        </span>
                        {lineNonconformity?.created_at ? (
                          <span>
                            {new Date(
                              lineNonconformity.created_at
                            ).toLocaleString()}
                          </span>
                        ) : null}
                        {lineNonconformity?.created_by ? (
                          <span>par {lineNonconformity.created_by}</span>
                        ) : null}
                      </div>
                      {replacementOrder ? (
                        <div className="space-y-1 text-[11px] text-emerald-100/90">
                          <p className="text-[10px] font-semibold uppercase text-emerald-300">
                            Demande de remplacement
                          </p>
                          <p>
                            BC #{replacementOrder.id} (statut:{" "}
                            {resolveReplacementStatusLabel(replacementOrder.status)})
                          </p>
                          <p>Motif: {latestReceipt?.nonconformity_reason ?? "—"}</p>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => handleDownload(replacementOrder.id)}
                              className="rounded border border-emerald-400/60 px-2 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/10"
                            >
                              Télécharger PDF (demande)
                            </button>
                            {(() => {
                              const canSendReplacement =
                                replacementOrder.status === "PENDING" ||
                                replacementOrder.status === "ORDERED";
                              const supplierState =
                                getSupplierSendState(replacementOrder);
                              if (
                                !canManageOrders ||
                                !canSendReplacement ||
                                !supplierState.canSend ||
                                isReadOnly
                              ) {
                                return null;
                              }
                              return (
                                <button
                                  type="button"
                                  onClick={() =>
                                    sendReplacementToSupplier.mutate({
                                      order: replacementOrder,
                                      contextNote: latestReceipt?.nonconformity_reason
                                        ? `Motif non-conformité : ${latestReceipt.nonconformity_reason}`
                                        : "Motif non-conformité : non renseigné"
                                    })
                                  }
                                  disabled={sendReplacementToSupplier.isPending}
                                  className="rounded bg-emerald-500 px-2 py-1 text-[11px] font-semibold text-white hover:bg-emerald-400"
                                >
                                  {sendReplacementToSupplier.isPending
                                    ? "Envoi..."
                                    : "Envoyer demande de remplacement"}
                                </button>
                              );
                            })()}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : !isReadOnly ? (
                    <button
                      type="button"
                      onClick={() =>
                        requestReplacement.mutate({
                          orderId: order.id,
                          lineId: line.id
                        })
                      }
                      disabled={requestReplacement.isPending}
                      className={lineRequestActionClass}
                    >
                      Créer demande de remplacement
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
        {hasNonConformingLatestReceipt ? (
          <li className="pt-2 text-[11px] text-rose-300">
            Réception non conforme : aucune attribution possible.
          </li>
        ) : conformingPendingAssignments.length > 0 ? (
          <li className="space-y-2 pt-2">
            <p className="text-[11px] uppercase text-slate-500">
              Attributions en attente
            </p>
            {conformingPendingAssignments.map((assignment) => {
              const isBlocked =
                assignment.source_receipt?.conformity_status !== "conforme";
              return (
                <div
                  key={assignment.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-1"
                >
                  <div>
                    <p className="text-xs text-slate-200">
                      {resolveCollaboratorName(assignment.employee_id)} ·{" "}
                      {resolveItemLabel(assignment.new_item_id)}
                    </p>
                    {assignment.target_dotation_id ||
                    assignment.return_employee_item_id ? (
                      <p className="text-[11px] text-slate-400">
                        Retour:{" "}
                        {(() => {
                          const targetId =
                            assignment.target_dotation_id ??
                            assignment.return_employee_item_id;
                          const matched = (
                            assignedItemsByBeneficiary.get(assignment.employee_id) ??
                            []
                          ).find(
                            (item) => item.assignment_id === targetId
                          );
                          return matched
                            ? resolveAssignedItemLabel(matched)
                            : `#${targetId}`;
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
                    disabled={
                      validatePendingAssignment.isPending ||
                      isBlocked ||
                      isReadOnly
                    }
                    title={
                      isBlocked
                        ? "Réception non conforme : attribution bloquée"
                        : undefined
                    }
                    className="rounded bg-indigo-500 px-2 py-1 text-[11px] font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Valider attribution + retour
                  </button>
                </div>
              );
            })}
          </li>
        ) : null}
        <li className="pt-2">
          <Timeline events={timelineEvents} title="Historique" />
        </li>
        {isReadOnly ? (
          <li className="text-[11px] text-amber-200">
            Bon de commande archivé : lecture seule activée.
          </li>
        ) : null}
        {order.note ? (
          <li className="text-slate-400">
            Note:{" "}
            <TruncatedText text={order.note} maxLength={notePreviewLength} />
          </li>
        ) : null}
        {order.last_sent_at ? (
          <li className="text-slate-400">
            Dernier envoi: {new Date(order.last_sent_at).toLocaleString()}
            {order.last_sent_to ? ` → ${order.last_sent_to}` : ""}
            {order.last_sent_by ? ` (par ${order.last_sent_by})` : ""}
          </li>
        ) : null}
      </ul>
    );

    const renderActions = (layout: "table" | "card") => {
      const actionWidthClass = layout === "card" ? "w-full" : "";
      const resolveActionClass = (key: string, primary: string, secondary: string) =>
        `${key === primaryActionKey ? `${primary} ring-1 ring-white/20` : secondary} ${actionWidthClass}`.trim();
      const containerClassName =
        layout === "card"
          ? "flex w-full flex-col gap-2"
          : "flex flex-col items-end gap-2";

      return (
        <div className={containerClassName}>
          <button
            type="button"
            onClick={() => handleDownload(order.id)}
            disabled={downloadingId === order.id}
            className={resolveActionClass(
              "download",
              "rounded bg-indigo-500 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60",
              "rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            )}
          >
            {downloadingId === order.id ? "Téléchargement..." : "Télécharger PDF"}
          </button>
          {isArchived ? (
            canManageOrders ? (
              <button
                type="button"
                onClick={() => handleUnarchiveOrder(order)}
                disabled={unarchiveOrder.isPending}
                className={resolveActionClass(
                  "unarchive",
                  "rounded bg-amber-500 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60",
                  "rounded border border-amber-400/60 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                )}
              >
                Désarchiver
              </button>
            ) : null
          ) : (
            <>
              <button
                type="button"
                onClick={() => {
                  if (
                    canManageOrders &&
                    canFinalizeNonconformity &&
                    sentReplacementOrders[0]
                  ) {
                    setFinalizeModalData({
                      order,
                      replacementOrder: sentReplacementOrders[0],
                      lines: nonconformingLineSummaries
                    });
                    return;
                  }
                  if (enableReplacementFlow) {
                    receiveOrderLines.mutate({
                      orderId: order.id,
                      lines: outstanding.map((line) => ({
                        purchase_order_line_id: line.line_id,
                        received_qty: line.qty,
                        conformity_status: "conforme",
                        nonconformity_reason: null,
                        note: null
                      }))
                    });
                  } else {
                    receiveOrder.mutate({ orderId: order.id, lines: outstanding });
                  }
                }}
                disabled={!canReceive}
                className={resolveActionClass(
                  "receive_all",
                  "rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60",
                  "rounded border border-emerald-500/60 px-3 py-1 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                )}
                title={
                  canReceive
                    ? "Enregistrer la réception des quantités restantes"
                    : "Toutes les quantités ont été réceptionnées"
                }
              >
                {receiveAllLabel}
              </button>
              <button
                type="button"
                onClick={() => handleOpenReceiveModal(order)}
                disabled={!canReceive}
                className={resolveActionClass(
                  "receive_partial",
                  "rounded bg-slate-700 px-3 py-1 text-xs font-semibold text-white hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-60",
                  "rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                )}
              >
                Réception partielle
              </button>
              <button
                type="button"
                onClick={() => handleEditOrder(order)}
                disabled={!canManageOrders || isReadOnly}
                className={resolveActionClass(
                  "edit",
                  "rounded bg-slate-700 px-3 py-1 text-xs font-semibold text-white hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-60",
                  "rounded border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                )}
              >
                Modifier
              </button>
              {canManageOrders && hasNonConformingLatestReceipt && replacementToSend
                ? (() => {
                    const supplierState =
                      getSupplierSendState(replacementToSend);
                    if (!supplierState.canSend) {
                      return null;
                    }
                    return (
                      <button
                        type="button"
                        onClick={() =>
                          sendReplacementToSupplier.mutate({
                            order: replacementToSend,
                            contextNote: replacementContextNote
                          })
                        }
                        disabled={sendReplacementToSupplier.isPending}
                        className={resolveActionClass(
                          "send_replacement",
                          "rounded bg-emerald-500 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60",
                          "rounded border border-emerald-400/60 px-3 py-1 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                        )}
                        title="Envoyer la demande de remplacement au fournisseur"
                      >
                        {sendReplacementToSupplier.isPending
                          ? "Envoi..."
                          : "Envoyer demande de remplacement"}
                      </button>
                    );
                  })()
                : null}
              {canSendEmail && order.status !== "RECEIVED"
                ? (() => {
                    const supplierState = getSupplierSendState(order);
                    return (
                      <button
                        type="button"
                        onClick={() => handleOpenSendModal(order)}
                        disabled={!supplierState.canSend}
                        className={resolveActionClass(
                          "send_supplier",
                          "rounded bg-indigo-500 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60",
                          "rounded border border-indigo-400/60 px-3 py-1 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                        )}
                        title={supplierState.tooltip}
                      >
                        Envoyer au fournisseur
                      </button>
                    );
                  })()
                : null}
              {canArchive ? (
                <button
                  type="button"
                  onClick={() => handleOpenArchiveModal(order)}
                  className={resolveActionClass(
                    "archive",
                    "rounded bg-amber-500 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-400",
                    "rounded border border-amber-400/60 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/10"
                  )}
                >
                  Archiver
                </button>
              ) : null}
              {user?.role === "admin" ? (
                <button
                  type="button"
                  onClick={() => handleDeleteOrder(order)}
                  disabled={deletingId === order.id}
                  className={resolveActionClass(
                    "delete",
                    "rounded bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60",
                    "rounded border border-red-500/60 px-3 py-1 text-xs font-semibold text-red-200 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-60"
                  )}
                >
                  {deletingId === order.id ? "Suppression..." : "Supprimer"}
                </button>
              ) : null}
            </>
          )}
        </div>
      );
    };

    const tableRow = (
      <tr key={order.id}>
        <td className="w-[140px] px-4 py-3 text-slate-300">
          {createdAtLabel}
          {order.auto_created ? (
            <span className="ml-2 rounded border border-indigo-500/40 bg-indigo-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-indigo-200">
              Auto
            </span>
          ) : null}
        </td>
        <td className="min-w-[220px] px-4 py-3 text-slate-200">
          <div className="flex flex-col">
            <span>{order.supplier_name ?? "-"}</span>
            <span className="text-xs text-slate-400">
              {order.supplier_email ?? "Email manquant"}
            </span>
          </div>
        </td>
        <td className="w-[160px] px-4 py-3 text-slate-200">
          <div className="flex flex-col gap-2 text-xs">
            <StatusBadge
              label={primaryBadge.label}
              tone={primaryBadge.tone}
              tooltip={primaryBadge.tooltip}
            />
            {statusControl}
          </div>
        </td>
        <td className="min-w-[420px] px-4 py-3 text-slate-200">
          <div
            className={`space-y-1 ${shouldClampLines && !isExpanded ? "md:max-h-40 md:overflow-hidden" : ""}`}
          >
            {linesList}
          </div>
          {shouldClampLines ? (
            <button
              type="button"
              onClick={() => toggleExpandedLines(order.id)}
              className="mt-2 hidden text-xs font-semibold text-indigo-200 hover:text-indigo-100 md:inline-flex lg:hidden"
            >
              {isExpanded ? "Réduire" : "Voir +"}
            </button>
          ) : null}
        </td>
        <td className="w-[220px] px-4 py-3 text-right align-top text-slate-200">
          {renderActions("table")}
        </td>
      </tr>
    );

    const card = (
      <article
        key={`card-${order.id}`}
        className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/70 p-4"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Créé le
            </p>
            <p className="text-sm text-slate-100">{createdAtLabel}</p>
            {order.auto_created ? (
              <span className="inline-flex rounded border border-indigo-500/40 bg-indigo-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-indigo-200">
                Auto
              </span>
            ) : null}
          </div>
          <StatusBadge
            label={primaryBadge.label}
            tone={primaryBadge.tone}
            tooltip={primaryBadge.tooltip}
          />
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Fournisseur
          </p>
          <p className="text-sm text-slate-100">{order.supplier_name ?? "-"}</p>
          <p className="text-xs text-slate-400">{order.supplier_email ?? "Email manquant"}</p>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Statut</p>
          <div className="flex flex-col gap-2 text-xs">
            {statusControl}
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Lignes</p>
          <div
            className={`space-y-1 ${shouldClampLines && !isExpanded ? "max-h-40 overflow-hidden" : ""}`}
          >
            {linesList}
          </div>
          {shouldClampLines ? (
            <button
              type="button"
              onClick={() => toggleExpandedLines(order.id)}
              className="inline-flex text-xs font-semibold text-indigo-200 hover:text-indigo-100 md:hidden"
            >
              {isExpanded ? "Réduire" : "Voir +"}
            </button>
          ) : null}
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Actions</p>
          {renderActions("card")}
        </div>
      </article>
    );

    return { id: order.id, row: tableRow, card };
  });

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

      <div
        className={
          editingOrder
            ? "grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)]"
            : "space-y-4"
        }
      >
        <div className="space-y-4">
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
          <div className="hidden md:block">
            <div className="w-full overflow-x-auto rounded-lg border border-slate-800">
              <table className="w-full table-auto divide-y divide-slate-800">
                <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                  <tr>
                    <th className="w-[140px] px-4 py-3 text-left">Créé le</th>
                    <th className="min-w-[220px] px-4 py-3 text-left">Fournisseur</th>
                    <th className="w-[160px] px-4 py-3 text-left">Statut</th>
                    <th className="min-w-[420px] px-4 py-3 text-left">Lignes</th>
                    <th className="w-[220px] px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900 bg-slate-950/60 text-sm text-slate-100">
                  {orderViews.map((view) => view.row)}
                  {visibleOrders.length === 0 && !loadingOrders ? (
                    <tr>
                      <td className="px-4 py-4 text-sm text-slate-400" colSpan={5}>
                        {showArchived
                          ? "Aucun bon de commande archivé."
                          : "Aucun bon de commande pour le moment."}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
          <div className="space-y-4 md:hidden">
            {orderViews.map((view) => view.card)}
            {visibleOrders.length === 0 && !loadingOrders ? (
              <div className="rounded-lg border border-dashed border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
                {showArchived
                  ? "Aucun bon de commande archivé."
                  : "Aucun bon de commande pour le moment."}
              </div>
            ) : null}
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
            const eligibleAssignments = beneficiaryAssignments.filter(
              (assignment) => Boolean(assignment.is_lost || assignment.is_degraded)
            );
            const filteredAssignments =
              selectedItem && eligibleAssignments.length > 0
                ? eligibleAssignments.filter((assignment) => {
                    const item = itemsById.get(assignment.item_id);
                    return (
                      item &&
                      item.category_id === selectedItem.category_id &&
                      item.size === selectedItem.size
                    );
                  })
                : [];
            const returnOptions =
              filteredAssignments.length > 0 ? filteredAssignments : eligibleAssignments;
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
                              targetDotationId: isReplacement
                                ? next[index].targetDotationId ?? ""
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
                                    targetDotationId: ""
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
                              Dotation à remplacer
                            </label>
                            <select
                              value={line.targetDotationId ?? ""}
                              onChange={(event) =>
                                setDraftLines((prev) => {
                                  const next = [...prev];
                                  next[index] = {
                                    ...next[index],
                                    targetDotationId: event.target.value
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
                                  ? "Sélectionnez une dotation en PERTE/DÉGRADATION"
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
        open={Boolean(finalizeModalData)}
        title={
          finalizeModalData
            ? `Finaliser la non-conformité · BC #${finalizeModalData.order.id}`
            : "Finaliser la non-conformité"
        }
        onClose={handleCloseFinalizeModal}
        footer={
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              {finalizeModalData ? (
                <>
                  <button
                    type="button"
                    onClick={() => handleDownload(finalizeModalData.replacementOrder.id)}
                    className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Télécharger PDF (demande de remplacement)
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDownload(finalizeModalData.order.id)}
                    className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Télécharger PDF (BC initial)
                  </button>
                </>
              ) : null}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleCloseFinalizeModal}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() =>
                  finalizeModalData
                    ? finalizeNonconformity.mutate({ orderId: finalizeModalData.order.id })
                    : null
                }
                disabled={finalizeNonconformity.isPending || !finalizeModalData}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {finalizeNonconformity.isPending
                  ? "Validation..."
                  : "Valider conforme & attribuer"}
              </button>
            </div>
          </div>
        }
      >
        {finalizeModalData ? (
          <div className="space-y-4 text-sm text-slate-200">
            <div className="space-y-1 text-xs text-slate-400">
              <p>BC initial : #{finalizeModalData.order.id}</p>
              <p>BC remplacement : #{finalizeModalData.replacementOrder.id}</p>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase text-slate-400">
                Articles non conformes
              </p>
              <div className="space-y-2">
                {finalizeModalData.lines.map((line) => (
                  <div
                    key={line.lineId}
                    className="rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2"
                  >
                    <p className="font-semibold text-slate-100">{line.itemLabel}</p>
                    <p className="text-xs text-slate-400">
                      Taille/variante : {line.sizeLabel} · Quantité : {line.qty}
                    </p>
                    <p className="text-xs text-rose-200">Motif : {line.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
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
                        </div>
                        {details.conformity_status === "non_conforme" ? (
                          <div className="grid gap-2 md:grid-cols-2">
                            <div className="space-y-1">
                              <label className="text-xs font-semibold text-slate-300">
                                Motif non conforme
                              </label>
                              <select
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
                              >
                                <option value="">Sélectionnez un motif</option>
                                {NONCONFORMITY_REASONS.map((reason) => (
                                  <option key={reason} value={reason}>
                                    {reason}
                                  </option>
                                ))}
                              </select>
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
