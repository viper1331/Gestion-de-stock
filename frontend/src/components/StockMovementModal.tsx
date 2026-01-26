import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { AxiosError } from "axios";
import { toast } from "sonner";

import { DraggableModal } from "./DraggableModal";
import { AppTextInput } from "./AppTextInput";
import { api } from "../lib/api";

export type BarcodeModuleKey = "clothing" | "remise" | "pharmacy";

interface BarcodeLookupItem {
  id: number;
  name: string;
  sku: string | null;
  module: string;
}

interface BarcodeConflictResponse {
  matches: BarcodeLookupItem[];
}

export interface StockMovementItemOption {
  id: number;
  name: string;
  sku?: string | null;
  details?: string[];
}

interface StockMovementModalProps {
  moduleKey: BarcodeModuleKey;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: StockMovementItemOption[];
  initialItemId?: number | null;
  isSubmitting?: boolean;
  requireReason?: boolean;
  onSubmitted?: () => void;
  onSubmitMovement: (payload: { itemId: number; delta: number; reason: string | null }) => Promise<void>;
}

export function StockMovementModal({
  moduleKey,
  open,
  onOpenChange,
  items,
  initialItemId = null,
  isSubmitting = false,
  requireReason = false,
  onSubmitted,
  onSubmitMovement
}: StockMovementModalProps) {
  const [selectedItemId, setSelectedItemId] = useState<number | null>(initialItemId);
  const [barcodeInput, setBarcodeInput] = useState("");
  const [deltaInput, setDeltaInput] = useState("1");
  const [reason, setReason] = useState("");
  const [resolvedItem, setResolvedItem] = useState<StockMovementItemOption | null>(null);
  const [isResolvingBarcode, setIsResolvingBarcode] = useState(false);
  const barcodeInputRef = useRef<HTMLInputElement | null>(null);

  const mergedItems = useMemo(() => {
    if (!resolvedItem || items.some((item) => item.id === resolvedItem.id)) {
      return items;
    }
    return [resolvedItem, ...items];
  }, [items, resolvedItem]);

  const formattedOptions = useMemo(
    () =>
      mergedItems.map((item) => {
        const details = [item.sku, ...(item.details ?? [])].filter(Boolean);
        const label = details.length ? `${item.name} — ${details.join(" · ")}` : item.name;
        return { id: item.id, label };
      }),
    [mergedItems]
  );

  const focusBarcodeInput = useCallback(() => {
    window.requestAnimationFrame(() => {
      barcodeInputRef.current?.focus();
    });
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedItemId(initialItemId ?? null);
    setBarcodeInput("");
    setDeltaInput("1");
    setReason("");
    setResolvedItem(null);
    focusBarcodeInput();
  }, [focusBarcodeInput, initialItemId, open]);

  const handleClose = () => {
    onOpenChange(false);
  };

  const handleBarcodeLookup = useCallback(async () => {
    const trimmed = barcodeInput.trim();
    if (!trimmed || isResolvingBarcode) {
      return;
    }
    setIsResolvingBarcode(true);
    try {
      const response = await api.get<BarcodeLookupItem>("/items/by-barcode", {
        params: { module: moduleKey, barcode: trimmed }
      });
      const match = response.data;
      setSelectedItemId(match.id);
      setResolvedItem({
        id: match.id,
        name: match.name,
        sku: match.sku ?? null,
        details: ["Code scanné"]
      });
      setBarcodeInput("");
    } catch (error) {
      const axiosError = error as AxiosError<BarcodeConflictResponse>;
      const status = axiosError.response?.status;
      if (status === 404) {
        toast.error("Code-barres inconnu");
      } else if (status === 409) {
        toast.error("Plusieurs articles correspondent au code-barres.");
      } else {
        toast.error("Impossible de récupérer l'article.");
      }
    } finally {
      setIsResolvingBarcode(false);
      focusBarcodeInput();
    }
  }, [barcodeInput, focusBarcodeInput, isResolvingBarcode, moduleKey]);

  const handleBarcodeKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleBarcodeLookup();
    }
  };

  const parsedDelta = Number(deltaInput);
  const trimmedReason = reason.trim();
  const isDeltaValid = deltaInput.trim().length > 0 && !Number.isNaN(parsedDelta) && parsedDelta !== 0;
  const isReasonValid = !requireReason || trimmedReason.length > 0;
  const isFormValid = selectedItemId !== null && isDeltaValid && isReasonValid;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isFormValid || selectedItemId === null) {
      return;
    }
    try {
      await onSubmitMovement({
        itemId: selectedItemId,
        delta: parsedDelta,
        reason: trimmedReason.length > 0 ? trimmedReason : null
      });
      setSelectedItemId(null);
      setBarcodeInput("");
      setDeltaInput("1");
      setReason("");
      setResolvedItem(null);
      onSubmitted?.();
      onOpenChange(false);
    } catch {
      focusBarcodeInput();
    }
  };

  return (
    <DraggableModal
      open={open}
      title="Mouvement de stock"
      onClose={handleClose}
      maxWidthClassName="max-w-2xl"
      bodyClassName="px-4 py-4"
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="stock-movement-item">
            Article concerné
          </label>
          <select
            id="stock-movement-item"
            value={selectedItemId ?? ""}
            onChange={(event) => {
              const value = event.target.value ? Number(event.target.value) : null;
              setSelectedItemId(value);
            }}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Sélectionnez un article pour ce mouvement"
          >
            <option value="">Sélectionnez un article</option>
            {formattedOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="stock-movement-barcode">
            Scan / saisie code-barres
          </label>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <AppTextInput
              id="stock-movement-barcode"
              ref={barcodeInputRef}
              value={barcodeInput}
              onChange={(event) => setBarcodeInput(event.target.value)}
              onKeyDown={handleBarcodeKeyDown}
              placeholder="Scanner ou saisir puis Entrée"
              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              title="Saisissez un code-barres puis appuyez sur Entrée"
            />
            <button
              type="button"
              onClick={handleBarcodeLookup}
              disabled={!barcodeInput.trim() || isResolvingBarcode}
              className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
              title="Rechercher l'article via le code-barres"
            >
              {isResolvingBarcode ? "Recherche..." : "Rechercher"}
            </button>
          </div>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1 space-y-1">
            <label className="text-xs font-semibold text-slate-300" htmlFor="stock-movement-delta">
              Variation
            </label>
            <AppTextInput
              id="stock-movement-delta"
              type="number"
              value={deltaInput}
              onChange={(event) => setDeltaInput(event.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              title="Indiquez la variation positive ou négative"
            />
          </div>
          <div className="flex-1 space-y-1">
            <label className="text-xs font-semibold text-slate-300" htmlFor="stock-movement-reason">
              Motif
            </label>
            <AppTextInput
              id="stock-movement-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Inventaire, sortie..."
              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              title="Précisez le motif du mouvement"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={!isFormValid || isSubmitting}
          className="w-full rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
          title={!isFormValid ? "Sélectionnez un article, une variation et un motif valide" : "Valider le mouvement"}
        >
          {isSubmitting ? "Enregistrement..." : "Valider le mouvement"}
        </button>
      </form>
    </DraggableModal>
  );
}
