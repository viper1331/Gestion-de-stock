import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";
import { DraggableModal } from "../../components/DraggableModal";

interface Collaborator {
  id: number;
  full_name: string;
}

interface Item {
  id: number;
  name: string;
  sku: string;
  quantity: number;
}

interface Dotation {
  id: number;
  collaborator_id: number;
  item_id: number;
  quantity: number;
  notes: string | null;
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
  degraded_qty: number;
  lost_qty: number;
  allocated_at: string;
  is_obsolete: boolean;
  size_variant: string | null;
}

interface DotationFormValues {
  collaborator_id: string;
  item_id: string;
  quantity: number;
  notes: string;
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
  degraded_qty: number;
  lost_qty: number;
}

interface DotationEditFormValues {
  item_id: string;
  quantity: number;
  notes: string;
  perceived_at: string;
  is_lost: boolean;
  is_degraded: boolean;
  degraded_qty: number;
  lost_qty: number;
}

interface ScannedDotationLine {
  item_id: number;
  name: string;
  sku: string;
  quantity: number;
}

type DotationStatus = "RAS" | "DEGRADATION" | "PERTE";

interface DotationChip {
  id: number;
  itemName: string;
  sku: string;
  variant: string | null;
  quantity: number;
  receivedAt: string;
  status: DotationStatus;
}

interface EmployeeDotationsRow {
  collaboratorId: number;
  employeeName: string;
  chips: DotationChip[];
}

const buildDefaultFormValues = (): DotationFormValues => ({
  collaborator_id: "",
  item_id: "",
  quantity: 1,
  notes: "",
  perceived_at: new Date().toISOString().slice(0, 10),
  is_lost: false,
  is_degraded: false,
  degraded_qty: 0,
  lost_qty: 0
});

const clampValue = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

const clampDotationQuantities = (quantity: number, degraded_qty: number, lost_qty: number) => {
  const maxDegraded = Math.max(quantity - lost_qty, 0);
  const nextDegraded = clampValue(degraded_qty, 0, maxDegraded);
  const maxLost = Math.max(quantity - nextDegraded, 0);
  const nextLost = clampValue(lost_qty, 0, maxLost);
  return { degraded_qty: nextDegraded, lost_qty: nextLost };
};

export function DotationsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<{ collaborator: string; item: string }>({ collaborator: "all", item: "all" });
  const [formValues, setFormValues] = useState<DotationFormValues>(() => buildDefaultFormValues());
  const [editingDotationId, setEditingDotationId] = useState<number | null>(null);
  const [editFormValues, setEditFormValues] = useState<DotationEditFormValues | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [scanValue, setScanValue] = useState("");
  const [scannedLines, setScannedLines] = useState<ScannedDotationLine[]>([]);
  const [expandedEmployees, setExpandedEmployees] = useState<Set<number>>(() => new Set());

  const canView = user?.role === "admin" || modulePermissions.canAccess("dotations");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("dotations", "edit");
  const moduleTitle = useModuleTitle("dotations");

  useEffect(() => {
    if (!isCreateModalOpen) {
      return;
    }
    setFormValues(buildDefaultFormValues());
    setScanValue("");
    setScannedLines([]);
    setMessage(null);
    setError(null);
  }, [isCreateModalOpen]);

  const { data: collaborators = [], isFetching: isFetchingCollaborators } = useQuery({
    queryKey: ["dotations", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canView
  });

  const { data: items = [], isFetching: isFetchingItems } = useQuery({
    queryKey: ["dotations", "items"],
    queryFn: async () => {
      const response = await api.get<Item[]>("/items/");
      return response.data;
    },
    enabled: canView
  });

  const { data: dotations = [], isFetching } = useQuery({
    queryKey: ["dotations", "list", filters],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (filters.collaborator !== "all" && filters.collaborator) {
        params.collaborator_id = filters.collaborator;
      }
      if (filters.item !== "all" && filters.item) {
        params.item_id = filters.item;
      }
      const response = await api.get<Dotation[]>("/dotations/dotations", { params });
      return response.data;
    },
    enabled: canView
  });

  const createDotation = useMutation({
    mutationFn: async (payload: {
      collaborator_id: number;
      item_id: number;
      quantity: number;
      notes: string | null;
      perceived_at: string;
      is_lost: boolean;
      is_degraded: boolean;
      degraded_qty: number;
      lost_qty: number;
    }) => {
      await api.post("/dotations/dotations", payload);
    },
    onSuccess: async () => {
      setMessage("Dotation enregistrée.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible d'enregistrer la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });


  const deleteDotation = useMutation({
    mutationFn: async ({ id, restock }: { id: number; restock: boolean }) => {
      await api.delete(`/dotations/dotations/${id}`, { params: { restock } });
    },
    onSuccess: async () => {
      setMessage("Dotation supprimée.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible de supprimer la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateDotation = useMutation({
    mutationFn: async ({
      id,
      payload
    }: {
      id: number;
      payload: {
        item_id: number;
        quantity: number;
        notes: string | null;
        perceived_at: string;
        is_lost: boolean;
        is_degraded: boolean;
        degraded_qty: number;
        lost_qty: number;
      };
    }) => {
      await api.put(`/dotations/dotations/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Dotation mise à jour.");
      setEditingDotationId(null);
      setEditFormValues(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const detail = err.response?.data?.detail;
      setError(detail ?? "Impossible de mettre à jour la dotation.");
    },
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const collaboratorById = useMemo(() => {
    return new Map(collaborators.map((collaborator) => [collaborator.id, collaborator]));
  }, [collaborators]);

  const itemById = useMemo(() => {
    return new Map(items.map((item) => [item.id, item]));
  }, [items]);

  const scanAddDotation = useMutation({
    mutationFn: async (payload: { employee_id: number; barcode: string; quantity: number }) => {
      const response = await api.post<Dotation>("/dotations/scan_add", payload);
      return response.data;
    },
    onSuccess: async (dotation) => {
      const item = itemById.get(dotation.item_id);
      setScannedLines((prev) => {
        const existingIndex = prev.findIndex((line) => line.item_id === dotation.item_id);
        if (existingIndex === -1) {
          return [
            ...prev,
            {
              item_id: dotation.item_id,
              name: item?.name ?? `Article #${dotation.item_id}`,
              sku: item?.sku ?? "",
              quantity: dotation.quantity
            }
          ];
        }
        const next = [...prev];
        const existing = next[existingIndex];
        next[existingIndex] = { ...existing, quantity: existing.quantity + dotation.quantity };
        return next;
      });
      toast.success("Article ajouté à la dotation");
      setScanValue("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dotations", "list"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["items"], exact: false }),
        queryClient.invalidateQueries({ queryKey: ["reports"], exact: false })
      ]);
    },
    onError: (err: AxiosError<{ detail?: string }>) => {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 404) {
        toast.error("Aucun article trouvé pour ce code.");
      } else if (status === 403) {
        toast.error("Autorisations insuffisantes pour ajouter une dotation.");
      } else if (detail) {
        toast.error(detail);
      } else {
        toast.error("Impossible d'ajouter l'article à la dotation.");
      }
    }
  });

  const groupedDotations = useMemo(() => {
    const groups = new Map<
      number,
      {
        collaborator: Collaborator | undefined;
        dotations: Dotation[];
      }
    >();
    for (const dotation of dotations) {
      const collaborator = collaboratorById.get(dotation.collaborator_id);
      if (!groups.has(dotation.collaborator_id)) {
        groups.set(dotation.collaborator_id, {
          collaborator,
          dotations: []
        });
      }
      groups.get(dotation.collaborator_id)?.dotations.push(dotation);
    }
    return Array.from(groups.entries())
      .map(([collaboratorId, value]) => ({ collaboratorId, ...value }))
      .sort((a, b) => {
        const labelA = a.collaborator?.full_name ?? `#${a.collaboratorId}`;
        const labelB = b.collaborator?.full_name ?? `#${b.collaboratorId}`;
        return labelA.localeCompare(labelB, "fr");
      });
  }, [dotations, collaboratorById]);

  const isAllCollaborators = !filters.collaborator || filters.collaborator === "all";

  const compactRows = useMemo<EmployeeDotationsRow[]>(() => {
    return groupedDotations.map((group) => ({
      collaboratorId: group.collaboratorId,
      employeeName: group.collaborator?.full_name ?? `Collaborateur #${group.collaboratorId}`,
      chips: group.dotations.map((dotation) => {
        const item = itemById.get(dotation.item_id);
        return {
          id: dotation.id,
          itemName: item?.name ?? `Article #${dotation.item_id}`,
          sku: item?.sku ?? "",
          variant: dotation.size_variant,
          quantity: dotation.quantity,
          receivedAt: dotation.perceived_at,
          status: getDotationStatus(dotation)
        };
      })
    }));
  }, [groupedDotations, itemById]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Distribution de matériel aux collaborateurs.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Distribution de matériel aux collaborateurs.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!formValues.collaborator_id || !formValues.item_id) {
      setError("Veuillez sélectionner un collaborateur et un article.");
      return;
    }
    if (formValues.quantity <= 0) {
      setError("La quantité doit être positive.");
      return;
    }
    const degradedQty = formValues.is_degraded ? formValues.degraded_qty : 0;
    const lostQty = formValues.is_lost ? formValues.lost_qty : 0;
    if (formValues.is_degraded && degradedQty <= 0) {
      setError("Indiquez une quantité dégradée supérieure à zéro.");
      return;
    }
    if (formValues.is_lost && lostQty <= 0) {
      setError("Indiquez une quantité perdue supérieure à zéro.");
      return;
    }
    if (degradedQty + lostQty > formValues.quantity) {
      setError("Les quantités perdues et dégradées dépassent la quantité attribuée.");
      return;
    }
    setMessage(null);
    setError(null);
    const perceived_at = formValues.perceived_at || new Date().toISOString().slice(0, 10);
    await createDotation.mutateAsync({
      collaborator_id: Number(formValues.collaborator_id),
      item_id: Number(formValues.item_id),
      quantity: formValues.quantity,
      notes: formValues.notes.trim() ? formValues.notes.trim() : null,
      perceived_at,
      is_lost: formValues.is_lost,
      is_degraded: formValues.is_degraded,
      degraded_qty: degradedQty,
      lost_qty: lostQty
    });
    setFormValues(buildDefaultFormValues());
  };

  const handleScanAdd = async () => {
    const trimmed = scanValue.trim();
    if (!trimmed || scanAddDotation.isPending) {
      return;
    }
    if (!formValues.collaborator_id) {
      toast.error("Sélectionnez d’abord un collaborateur avant de scanner un article.");
      return;
    }
    setMessage(null);
    setError(null);
    await scanAddDotation.mutateAsync({
      employee_id: Number(formValues.collaborator_id),
      barcode: trimmed,
      quantity: 1
    });
  };

  const handleStartEditing = (dotation: Dotation) => {
    setMessage(null);
    setError(null);
    setEditingDotationId(dotation.id);
    setEditFormValues({
      item_id: dotation.item_id.toString(),
      quantity: dotation.quantity,
      notes: dotation.notes ?? "",
      perceived_at: dotation.perceived_at.slice(0, 10),
      is_lost: dotation.is_lost,
      is_degraded: dotation.is_degraded,
      degraded_qty: dotation.degraded_qty,
      lost_qty: dotation.lost_qty
    });
  };

  const handleCancelEditing = () => {
    setEditingDotationId(null);
    setEditFormValues(null);
  };

  const handleUpdateSubmit = async (event: FormEvent<HTMLFormElement>, dotation: Dotation) => {
    event.preventDefault();
    if (!editFormValues) {
      return;
    }
    if (!editFormValues.item_id) {
      setError("Veuillez sélectionner un article.");
      return;
    }
    if (editFormValues.quantity <= 0) {
      setError("La quantité doit être positive.");
      return;
    }
    const degradedQty = editFormValues.is_degraded ? editFormValues.degraded_qty : 0;
    const lostQty = editFormValues.is_lost ? editFormValues.lost_qty : 0;
    if (editFormValues.is_degraded && degradedQty <= 0) {
      setError("Indiquez une quantité dégradée supérieure à zéro.");
      return;
    }
    if (editFormValues.is_lost && lostQty <= 0) {
      setError("Indiquez une quantité perdue supérieure à zéro.");
      return;
    }
    if (degradedQty + lostQty > editFormValues.quantity) {
      setError("Les quantités perdues et dégradées dépassent la quantité attribuée.");
      return;
    }
    setMessage(null);
    setError(null);
    const perceived_at = editFormValues.perceived_at || new Date().toISOString().slice(0, 10);
    await updateDotation.mutateAsync({
      id: dotation.id,
      payload: {
        item_id: Number(editFormValues.item_id),
        quantity: editFormValues.quantity,
        notes: editFormValues.notes.trim() ? editFormValues.notes.trim() : null,
        perceived_at,
        is_lost: editFormValues.is_lost,
        is_degraded: editFormValues.is_degraded,
        degraded_qty: degradedQty,
        lost_qty: lostQty
      }
    });
  };

  const renderDotationCard = (dotation: Dotation) => {
    const item = itemById.get(dotation.item_id);
    const isEditing = editingDotationId === dotation.id && editFormValues;
    const alerts: Array<{ key: string; label: string; className: string }> = [];
    if (dotation.is_obsolete) {
      alerts.push({
        key: "obsolete",
        label: "Vétusté",
        className: "rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-300"
      });
    }
    if (dotation.lost_qty > 0) {
      alerts.push({
        key: "lost",
        label: "Perte",
        className: "rounded border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-red-300"
      });
    }
    if (dotation.degraded_qty > 0 && dotation.lost_qty === 0) {
      alerts.push({
        key: "degraded",
        label: "Dégradation",
        className: "rounded border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-orange-300"
      });
    }

    return (
      <article key={dotation.id} className="rounded border border-slate-800 bg-slate-950 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-sm font-semibold text-white">
              {item ? `${item.name} (${item.sku})` : `Article #${dotation.item_id}`}
            </p>
            <p className="text-xs text-slate-400">
              Taille / Variante : {dotation.size_variant ? dotation.size_variant : "—"}
            </p>
            <p className="text-xs text-slate-400">Dotation créée le {formatDate(dotation.allocated_at)}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {alerts.length > 0 ? (
              alerts.map((alert) => (
                <span key={alert.key} className={alert.className}>
                  {alert.label}
                </span>
              ))
            ) : (
              <span className="rounded border border-slate-800 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
                RAS
              </span>
            )}
          </div>
        </div>
        <dl className="mt-3 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">Quantité</dt>
            <dd className="font-semibold text-white">{dotation.quantity}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">Perçue le</dt>
            <dd>{formatDateOnly(dotation.perceived_at)}</dd>
          </div>
          {dotation.degraded_qty > 0 ? (
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Dégradé</dt>
              <dd>
                {dotation.degraded_qty} / {dotation.quantity}
              </dd>
            </div>
          ) : null}
          {dotation.lost_qty > 0 ? (
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Perdu</dt>
              <dd>
                {dotation.lost_qty} / {dotation.quantity}
              </dd>
            </div>
          ) : null}
          <div className="sm:col-span-2">
            <dt className="text-xs uppercase tracking-wide text-slate-500">Notes</dt>
            <dd>{dotation.notes ? dotation.notes : <span className="text-slate-500">-</span>}</dd>
          </div>
        </dl>
        {canEdit ? (
          <div className="mt-4 space-y-3">
            {isEditing ? (
              <form
                className="space-y-3 rounded border border-slate-800 bg-slate-950 p-3"
                onSubmit={(event) => void handleUpdateSubmit(event, dotation)}
              >
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-item-${dotation.id}`}>
                    Article attribué
                  </label>
                  <select
                    id={`edit-item-${dotation.id}`}
                    value={editFormValues?.item_id ?? ""}
                    onChange={(event) =>
                      setEditFormValues((prev) =>
                        prev
                          ? {
                              ...prev,
                              item_id: event.target.value
                            }
                          : prev
                      )
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="">Sélectionner...</option>
                    {items.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name} - Stock: {option.quantity}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-quantity-${dotation.id}`}>
                      Quantité
                    </label>
                    <AppTextInput
                      id={`edit-quantity-${dotation.id}`}
                      type="number"
                      min={1}
                      value={editFormValues?.quantity ?? dotation.quantity}
                      onChange={(event) =>
                        setEditFormValues((prev) =>
                          prev
                            ? {
                                ...prev,
                                quantity: Number(event.target.value),
                                ...(() => {
                                  const nextQuantity = Number(event.target.value);
                                  const { degraded_qty, lost_qty } = clampDotationQuantities(
                                    nextQuantity,
                                    prev.degraded_qty,
                                    prev.lost_qty
                                  );
                                  return {
                                    degraded_qty,
                                    lost_qty,
                                    is_degraded: degraded_qty > 0,
                                    is_lost: lost_qty > 0
                                  };
                                })()
                              }
                            : prev
                        )
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-perceived-${dotation.id}`}>
                      Date de perception
                    </label>
                    <AppTextInput
                      id={`edit-perceived-${dotation.id}`}
                      type="date"
                      value={editFormValues?.perceived_at ?? dotation.perceived_at.slice(0, 10)}
                      onChange={(event) =>
                        setEditFormValues((prev) =>
                          prev
                            ? {
                                ...prev,
                                perceived_at: event.target.value
                              }
                            : prev
                        )
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-notes-${dotation.id}`}>
                    Notes
                  </label>
                  <AppTextArea
                    id={`edit-notes-${dotation.id}`}
                    rows={3}
                    value={editFormValues?.notes ?? dotation.notes ?? ""}
                    onChange={(event) =>
                      setEditFormValues((prev) =>
                        prev
                          ? {
                              ...prev,
                              notes: event.target.value
                            }
                          : prev
                      )
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor={`edit-lost-${dotation.id}`}>
                    <AppTextInput
                      id={`edit-lost-${dotation.id}`}
                      type="checkbox"
                      checked={editFormValues?.is_lost ?? dotation.is_lost}
                      onChange={(event) =>
                        setEditFormValues((prev) =>
                          prev
                            ? {
                                ...prev,
                                is_lost:
                                  event.target.checked &&
                                  Math.max(prev.quantity - prev.degraded_qty, 0) > 0,
                                lost_qty: event.target.checked
                                  ? (() => {
                                      const maxAvailable = Math.max(
                                        prev.quantity - prev.degraded_qty,
                                        0
                                      );
                                      return maxAvailable > 0
                                        ? Math.max(1, Math.min(prev.lost_qty || 1, maxAvailable))
                                        : 0;
                                    })()
                                  : 0
                              }
                            : prev
                        )
                      }
                      className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                    />
                    Perte déclarée
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor={`edit-degraded-${dotation.id}`}>
                    <AppTextInput
                      id={`edit-degraded-${dotation.id}`}
                      type="checkbox"
                      checked={editFormValues?.is_degraded ?? dotation.is_degraded}
                      onChange={(event) =>
                        setEditFormValues((prev) =>
                          prev
                            ? {
                                ...prev,
                                is_degraded:
                                  event.target.checked &&
                                  Math.max(prev.quantity - prev.lost_qty, 0) > 0,
                                degraded_qty: event.target.checked
                                  ? (() => {
                                      const maxAvailable = Math.max(
                                        prev.quantity - prev.lost_qty,
                                        0
                                      );
                                      return maxAvailable > 0
                                        ? Math.max(
                                            1,
                                            Math.min(prev.degraded_qty || 1, maxAvailable)
                                          )
                                        : 0;
                                    })()
                                  : 0
                              }
                            : prev
                        )
                      }
                      className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                    />
                    Dégradation constatée
                  </label>
                </div>
                {(editFormValues?.is_lost ?? false) || (editFormValues?.is_degraded ?? false) ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {editFormValues?.is_degraded ? (
                      <div className="space-y-1">
                        <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-degraded-qty-${dotation.id}`}>
                          Quantité dégradée
                        </label>
                        <AppTextInput
                          id={`edit-degraded-qty-${dotation.id}`}
                          type="number"
                          min={1}
                          max={Math.max((editFormValues?.quantity ?? 0) - (editFormValues?.lost_qty ?? 0), 1)}
                          value={editFormValues?.degraded_qty ?? 0}
                          onChange={(event) =>
                            setEditFormValues((prev) => {
                              if (!prev) {
                                return prev;
                              }
                              const nextQty = Number(event.target.value);
                              const { degraded_qty, lost_qty } = clampDotationQuantities(
                                prev.quantity,
                                nextQty,
                                prev.lost_qty
                              );
                              return {
                                ...prev,
                                degraded_qty,
                                lost_qty,
                                is_degraded: degraded_qty > 0,
                                is_lost: lost_qty > 0
                              };
                            })
                          }
                          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                        />
                      </div>
                    ) : null}
                    {editFormValues?.is_lost ? (
                      <div className="space-y-1">
                        <label className="text-xs font-semibold text-slate-300" htmlFor={`edit-lost-qty-${dotation.id}`}>
                          Quantité perdue
                        </label>
                        <AppTextInput
                          id={`edit-lost-qty-${dotation.id}`}
                          type="number"
                          min={1}
                          max={Math.max((editFormValues?.quantity ?? 0) - (editFormValues?.degraded_qty ?? 0), 1)}
                          value={editFormValues?.lost_qty ?? 0}
                          onChange={(event) =>
                            setEditFormValues((prev) => {
                              if (!prev) {
                                return prev;
                              }
                              const nextQty = Number(event.target.value);
                              const { degraded_qty, lost_qty } = clampDotationQuantities(
                                prev.quantity,
                                prev.degraded_qty,
                                nextQty
                              );
                              return {
                                ...prev,
                                degraded_qty,
                                lost_qty,
                                is_degraded: degraded_qty > 0,
                                is_lost: lost_qty > 0
                              };
                            })
                          }
                          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                        />
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="submit"
                    disabled={updateDotation.isPending}
                    className="rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {updateDotation.isPending ? "Enregistrement..." : "Enregistrer les modifications"}
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelEditing}
                    className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-slate-500"
                  >
                    Annuler
                  </button>
                </div>
              </form>
            ) : (
              <div className="flex flex-wrap gap-3 text-xs">
                <button
                  type="button"
                  onClick={() => handleStartEditing(dotation)}
                  className="rounded-md border border-slate-700 px-3 py-1 font-semibold text-indigo-300 hover:border-indigo-400 hover:text-indigo-200"
                >
                  Modifier
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (!window.confirm("Supprimer cette dotation ?")) {
                      return;
                    }
                    const restock = window.confirm(
                      "Faut-il réintégrer les quantités au stock ?\nOK pour réintégrer, Annuler pour ignorer."
                    );
                    setMessage(null);
                    setError(null);
                    void deleteDotation.mutateAsync({ id: dotation.id, restock });
                  }}
                  className="rounded-md border border-slate-700 px-3 py-1 font-semibold text-red-300 hover:border-red-400 hover:text-red-200"
                >
                  Supprimer
                </button>
              </div>
            )}
          </div>
        ) : null}
      </article>
    );
  };

  const selectedCollaboratorId = !isAllCollaborators && filters.collaborator ? Number(filters.collaborator) : null;
  const selectedCollaborator = selectedCollaboratorId ? collaboratorById.get(selectedCollaboratorId) : undefined;
  const maxChips = 6;

  const handleToggleEmployee = (collaboratorId: number) => {
    setExpandedEmployees((prev) => {
      const next = new Set(prev);
      if (next.has(collaboratorId)) {
        next.delete(collaboratorId);
      } else {
        next.add(collaboratorId);
      }
      return next;
    });
  };

  const content = (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Suivez les dotations et restitutions de matériel.</p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
          >
            Nouvelle dotation
          </button>
        ) : null}
      </header>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Collaborateur
            <select
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={filters.collaborator}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, collaborator: event.target.value }))
              }
              title="Filtrer les dotations par collaborateur"
            >
              <option value="all">Tous</option>
              {collaborators.map((collaborator) => (
                <option key={collaborator.id} value={collaborator.id}>
                  {collaborator.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Article
            <select
              className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={filters.item}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, item: event.target.value }))
              }
              title="Filtrer les dotations par article"
            >
              <option value="all">Tous</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.sku})
                </option>
              ))}
            </select>
          </label>
          {isFetching ? <span className="text-xs text-slate-400">Actualisation...</span> : null}
        </div>
      </div>

      <div className="space-y-5">
        {isFetching ? <p className="text-xs text-slate-400">Actualisation des dotations...</p> : null}
        {groupedDotations.length === 0 ? (
          <p className="rounded-lg border border-slate-800 bg-slate-950 px-4 py-6 text-sm text-slate-400">
            Aucune dotation enregistrée pour le moment.
          </p>
        ) : null}
        {groupedDotations.length > 0 ? (
          isAllCollaborators ? (
            <DotationsCompactList
              rows={compactRows}
              maxChips={maxChips}
              expandedEmployees={expandedEmployees}
              onToggleEmployee={handleToggleEmployee}
            />
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <h3 className="text-lg font-semibold text-white">
                  {selectedCollaborator?.full_name ?? "Collaborateur sélectionné"}
                </h3>
                <p className="text-xs text-slate-400">
                  {dotations.length} article{dotations.length > 1 ? "s" : ""} attribué{dotations.length > 1 ? "s" : ""}
                </p>
              </div>
              <div className="grid gap-4">
                {dotations.map((dotation) => renderDotationCard(dotation))}
              </div>
            </div>
          )
        ) : null}
      </div>

      <DraggableModal
        open={isCreateModalOpen}
        title="Nouvelle dotation"
        onClose={() => setIsCreateModalOpen(false)}
        maxWidthClassName="max-w-[1100px] w-[95vw] max-h-[85vh]"
        bodyClassName="px-6 py-5"
      >
        {canEdit ? (
          <div className="space-y-6">
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-collaborator">
                Collaborateur
              </label>
              <select
                id="dotation-collaborator"
                value={formValues.collaborator_id}
                onChange={(event) => setFormValues((prev) => ({ ...prev, collaborator_id: event.target.value }))}
                className="mt-2 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                disabled={isFetchingCollaborators}
                required
                title="Choisissez le collaborateur bénéficiaire"
              >
                <option value="">Sélectionner...</option>
                {collaborators.map((collaborator) => (
                  <option key={collaborator.id} value={collaborator.id}>
                    {collaborator.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <h4 className="text-sm font-semibold text-white">Scanner un article</h4>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
                <div className="flex-1 space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-scan">
                    Code-barres / SKU
                  </label>
                  <AppTextInput
                    id="dotation-scan"
                    value={scanValue}
                    onChange={(event) => setScanValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void handleScanAdd();
                      }
                    }}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    placeholder="Scanner ou saisir un code"
                    title="Scanner ou saisir un code-barres"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => void handleScanAdd()}
                  disabled={scanAddDotation.isPending}
                  className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {scanAddDotation.isPending ? "Ajout..." : "Ajouter"}
                </button>
              </div>
              <p className="mt-2 text-xs text-slate-400">
                Utilisez un lecteur code-barres ou validez avec Entrée.
              </p>
            </div>

            {scannedLines.length > 0 ? (
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <h4 className="text-sm font-semibold text-white">Articles scannés</h4>
                <ul className="mt-3 space-y-2 text-sm text-slate-200">
                  {scannedLines.map((line) => (
                    <li key={line.item_id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/60 px-3 py-2">
                      <span className="font-semibold text-white">
                        {line.name} {line.sku ? `(${line.sku})` : ""}
                      </span>
                      <span className="text-xs text-slate-300">Quantité : {line.quantity}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <form className="space-y-3 rounded-lg border border-slate-800 bg-slate-950 p-4" onSubmit={handleSubmit}>
              <h4 className="text-sm font-semibold text-white">Saisie manuelle</h4>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-item">
                  Article
                </label>
                <select
                  id="dotation-item"
                  value={formValues.item_id}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, item_id: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  disabled={isFetchingItems}
                  required
                  title="Sélectionnez l'article à allouer"
                >
                  <option value="">Sélectionner...</option>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} - Stock: {item.quantity}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-quantity">
                  Quantité
                </label>
                <AppTextInput
                  id="dotation-quantity"
                  type="number"
                  min={1}
                  value={formValues.quantity}
                  onChange={(event) =>
                    setFormValues((prev) => {
                      const nextQuantity = Number(event.target.value);
                      const { degraded_qty, lost_qty } = clampDotationQuantities(
                        nextQuantity,
                        prev.degraded_qty,
                        prev.lost_qty
                      );
                      return {
                        ...prev,
                        quantity: nextQuantity,
                        degraded_qty,
                        lost_qty,
                        is_degraded: degraded_qty > 0,
                        is_lost: lost_qty > 0
                      };
                    })
                  }
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  required
                  title="Quantité remise au collaborateur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-perceived-at">
                  Date de perception
                </label>
                <AppTextInput
                  id="dotation-perceived-at"
                  type="date"
                  value={formValues.perceived_at}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, perceived_at: event.target.value }))}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  required
                  title="Date de remise au collaborateur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-notes">
                  Notes
                </label>
                <AppTextArea
                  id="dotation-notes"
                  value={formValues.notes}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, notes: event.target.value }))}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  placeholder="Optionnel"
                  title="Ajoutez des précisions (numéro de série, conditions, etc.)"
                />
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-300" htmlFor="dotation-lost">
                  <AppTextInput
                    id="dotation-lost"
                    type="checkbox"
                    checked={formValues.is_lost}
                    onChange={(event) =>
                      setFormValues((prev) => {
                        const maxAvailable = Math.max(prev.quantity - prev.degraded_qty, 0);
                        return {
                          ...prev,
                          is_lost: event.target.checked && maxAvailable > 0,
                          lost_qty: event.target.checked
                            ? maxAvailable > 0
                              ? Math.max(1, Math.min(prev.lost_qty || 1, maxAvailable))
                              : 0
                            : 0
                        };
                      })
                    }
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                  />
                  Perte déclarée
                </label>
                <label
                  className="flex items-center gap-2 text-xs font-semibold text-slate-300"
                  htmlFor="dotation-degraded"
                >
                  <AppTextInput
                    id="dotation-degraded"
                    type="checkbox"
                    checked={formValues.is_degraded}
                    onChange={(event) =>
                      setFormValues((prev) => {
                        const maxAvailable = Math.max(prev.quantity - prev.lost_qty, 0);
                        return {
                          ...prev,
                          is_degraded: event.target.checked && maxAvailable > 0,
                          degraded_qty: event.target.checked
                            ? maxAvailable > 0
                              ? Math.max(1, Math.min(prev.degraded_qty || 1, maxAvailable))
                              : 0
                            : 0
                        };
                      })
                    }
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
                  />
                  Dégradation constatée
                </label>
              </div>
              {formValues.is_lost || formValues.is_degraded ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {formValues.is_degraded ? (
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-degraded-qty">
                        Quantité dégradée
                      </label>
                      <AppTextInput
                        id="dotation-degraded-qty"
                        type="number"
                        min={1}
                        max={Math.max(formValues.quantity - formValues.lost_qty, 1)}
                        value={formValues.degraded_qty}
                        onChange={(event) =>
                          setFormValues((prev) => {
                            const nextQty = Number(event.target.value);
                            const { degraded_qty, lost_qty } = clampDotationQuantities(
                              prev.quantity,
                              nextQty,
                              prev.lost_qty
                            );
                            return {
                              ...prev,
                              degraded_qty,
                              lost_qty,
                              is_degraded: degraded_qty > 0,
                              is_lost: lost_qty > 0
                            };
                          })
                        }
                        className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                      />
                    </div>
                  ) : null}
                  {formValues.is_lost ? (
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-300" htmlFor="dotation-lost-qty">
                        Quantité perdue
                      </label>
                      <AppTextInput
                        id="dotation-lost-qty"
                        type="number"
                        min={1}
                        max={Math.max(formValues.quantity - formValues.degraded_qty, 1)}
                        value={formValues.lost_qty}
                        onChange={(event) =>
                          setFormValues((prev) => {
                            const nextQty = Number(event.target.value);
                            const { degraded_qty, lost_qty } = clampDotationQuantities(
                              prev.quantity,
                              prev.degraded_qty,
                              nextQty
                            );
                            return {
                              ...prev,
                              degraded_qty,
                              lost_qty,
                              is_degraded: degraded_qty > 0,
                              is_lost: lost_qty > 0
                            };
                          })
                        }
                        className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                      />
                    </div>
                  ) : null}
                </div>
              ) : null}
              <button
                type="submit"
                disabled={createDotation.isPending}
                className="w-full rounded-md bg-indigo-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                title="Valider l'enregistrement de la dotation"
              >
                {createDotation.isPending ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        ) : (
          <p className="text-sm text-slate-400">
            Vous ne disposez pas des droits d'écriture pour créer des dotations.
          </p>
        )}
      </DraggableModal>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "dotations-main",
      title: "Dotations",
      required: true,
      permissions: ["dotations"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      render: () => (
        <EditableBlock id="dotations-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:dotations"
      blocks={blocks}
      className="space-y-6"
    />
  );
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

function formatDateOnly(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

function getDotationStatus(dotation: Dotation): DotationStatus {
  if (dotation.lost_qty > 0) {
    return "PERTE";
  }
  if (dotation.degraded_qty > 0) {
    return "DEGRADATION";
  }
  return "RAS";
}

function StatusBadge({ status }: { status: DotationStatus }) {
  const cls =
    status === "PERTE"
      ? "bg-red-500/15 text-red-300 border-red-500/30"
      : status === "DEGRADATION"
      ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
      : "bg-slate-500/15 text-slate-200 border-slate-500/30";

  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs ${cls}`}>
      {status}
    </span>
  );
}

function DotationsCompactList({
  rows,
  maxChips,
  expandedEmployees,
  onToggleEmployee
}: {
  rows: EmployeeDotationsRow[];
  maxChips: number;
  expandedEmployees: Set<number>;
  onToggleEmployee: (collaboratorId: number) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-black/20">
      <div className="grid gap-3 border-b border-white/10 px-4 py-3 text-xs uppercase tracking-wide text-slate-300 sm:grid-cols-[220px_1fr]">
        <div>Collaborateur</div>
        <div>Dotations</div>
      </div>
      <div className="divide-y divide-white/5">
        {rows.map((row) => {
          const isExpanded = expandedEmployees.has(row.collaboratorId);
          const visibleChips = isExpanded ? row.chips : row.chips.slice(0, maxChips);
          const hiddenCount = Math.max(row.chips.length - visibleChips.length, 0);
          return (
            <div key={row.collaboratorId} className="grid gap-3 px-4 py-3 sm:grid-cols-[220px_1fr]">
              <div className="font-medium text-white/90">{row.employeeName}</div>
              <div className="flex flex-wrap items-center gap-2">
                {visibleChips.map((chip) => (
                  <div
                    key={chip.id}
                    className="min-w-[150px] rounded-lg border border-slate-800 bg-slate-950 px-2 py-1"
                  >
                    <div className="flex flex-wrap items-center gap-1 text-[11px] text-slate-300">
                      <span className="font-semibold text-white/90">{chip.itemName}</span>
                      {chip.sku ? <span className="text-[10px] text-slate-400">({chip.sku})</span> : null}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
                      <span title={chip.variant ?? undefined}>
                        Taille: {chip.variant ? chip.variant : "—"}
                      </span>
                      <span>Qté {chip.quantity}</span>
                      <span>{formatDateOnly(chip.receivedAt)}</span>
                      <StatusBadge status={chip.status} />
                    </div>
                  </div>
                ))}
                {hiddenCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => onToggleEmployee(row.collaboratorId)}
                    className="rounded-full border border-slate-700 px-3 py-1 text-[11px] font-semibold text-slate-300 hover:border-slate-500"
                  >
                    +{hiddenCount}
                  </button>
                ) : row.chips.length > maxChips ? (
                  <button
                    type="button"
                    onClick={() => onToggleEmployee(row.collaboratorId)}
                    className="rounded-full border border-slate-700 px-3 py-1 text-[11px] font-semibold text-slate-300 hover:border-slate-500"
                  >
                    Réduire
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
